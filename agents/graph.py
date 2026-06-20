"""
graph.py
────────
LangGraph wiring for the agentic legal pipeline (CLAUDE.md §2, §4, §6).

Connects the five components into one `StateGraph`:

    Query Agent ─▶ Researcher ─▶ Checklist Resolver ─▶ Auditor ─▶ Adjudicator

Routing (CLAUDE.md §2 per-sub-question pipeline):
  • test_application sub-question → full path (Researcher→Checklist→Auditor→Adjudicator)
  • informational sub-question    → short path (Researcher→Adjudicator, skips Checklist+Auditor)

Sub-questions are processed SEQUENTIALLY via a `current_index` cursor — clean with the
two human-in-the-loop pauses (the Query Agent's clarification gate and the Auditor's
❓ loop), which are implemented as native LangGraph `interrupt()`s resumed with
`Command(resume=<answer>)`. A `MemorySaver` checkpointer persists thread state across
the pauses.

Each clarifying node self-loops: it runs its agent once and, on a clarify, calls
`interrupt()` for exactly ONE answer, then routes back to itself to re-run with the
extended history. Keeping one interrupt per node invocation avoids interrupt-replay
ordering pitfalls.

Single primary provision per test_application sub-question (decision 2026-06-21):
`sub_question.provision_key`, else the top Pull-C surfaced statute.

Public:
    build_graph(retriever=None) -> compiled StateGraph (with checkpointer)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .adjudicator import run_adjudicator
from .auditor import run_auditor
from .checklist_resolver import resolve_checklist
from .query_agent import run_query_agent
from .researcher import run_researcher
from .schemas import AdjudicationResult, AuditResult, ChecklistResult, SubQuestion


# ─────────────────────────────────────────────
# Graph state
# ─────────────────────────────────────────────

class PipelineState(TypedDict, total=False):
    raw_query: str
    qa_history: List[dict]                 # Query Agent clarify turns
    sub_questions: List[SubQuestion]
    current_index: int                     # which sub-question is being processed
    evidence: Dict[int, list]              # sq.id -> retrieved chunks (Pull A/B)
    surfaced: Dict[int, List[str]]         # sq.id -> Pull C statutes
    checklists: Dict[int, ChecklistResult] # sq.id -> resolved checklist
    audit_history: List[dict]              # Auditor clarify turns for the CURRENT sq
    audit_results: Dict[int, AuditResult]  # sq.id -> audit result
    adjudication: Optional[AdjudicationResult]


# ─────────────────────────────────────────────
# Degraded retriever (used when the RAG stores aren't up)
# ─────────────────────────────────────────────

class _NullRetriever:
    """Stands in for HybridRetriever when stores are unavailable: retrieval yields
    nothing, so the pipeline runs on Pull C + provision text only (graceful degrade)."""

    def retrieve(self, query: str, intent: str = "DEFAULT", top_k: int = 20) -> list:
        return []

    def close(self) -> None:
        pass


def _make_retriever(retriever: Any) -> Any:
    """Build (once) the shared retriever, or fall back to the null retriever."""
    if retriever is not None:
        return retriever
    try:
        from retrieval.hybrid_retriever import HybridRetriever
        return HybridRetriever()
    except Exception as e:  # noqa: BLE001 — stores down / not configured → degrade
        print(f"[graph] HybridRetriever unavailable ({type(e).__name__}: {e}); "
              "running with empty retrieval.")
        return _NullRetriever()


# ─────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────

def _current_sq(state: PipelineState) -> SubQuestion:
    return state["sub_questions"][state["current_index"]]


def _primary_provision(sq: SubQuestion, surfaced: List[str]) -> Optional[str]:
    """Single provision to verify: the Query Agent's key, else the top surfaced statute."""
    if sq.provision_key:
        return sq.provision_key
    return surfaced[0] if surfaced else None


# ─────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────

def _query_agent_node(state: PipelineState) -> dict:
    history = list(state.get("qa_history") or [])
    result = run_query_agent(state["raw_query"], history=history)
    if result.is_ready:
        return {"sub_questions": result.sub_questions, "current_index": 0,
                "qa_history": history}
    answer = interrupt({
        "type": "query_clarification",
        "kind": result.clarification_kind.value if result.clarification_kind else None,
        "question": result.pending_question,
        "options": result.options,
        "extracted_facts": result.extracted_facts,
    })
    history.append({
        "question": result.pending_question,
        "answer": answer,
        "kind": result.clarification_kind.value if result.clarification_kind else None,
    })
    return {"qa_history": history}


def _make_researcher_node(retriever: Any):
    def _researcher_node(state: PipelineState) -> dict:
        sq = _current_sq(state)
        ev, surf = run_researcher(sq, retriever=retriever)
        evidence = dict(state.get("evidence") or {}); evidence[sq.id] = ev
        surfaced = dict(state.get("surfaced") or {}); surfaced[sq.id] = surf
        return {"evidence": evidence, "surfaced": surfaced}
    return _researcher_node


def _checklist_node(state: PipelineState) -> dict:
    sq = _current_sq(state)
    surfaced = (state.get("surfaced") or {}).get(sq.id, [])
    provision = _primary_provision(sq, surfaced)
    cr = resolve_checklist(provision, query_type=sq.query_type.value)
    checklists = dict(state.get("checklists") or {}); checklists[sq.id] = cr
    # Reset the per-sub-question audit clarify history before the Auditor runs.
    return {"checklists": checklists, "audit_history": []}


def _auditor_node(state: PipelineState) -> dict:
    sq = _current_sq(state)
    cr = (state.get("checklists") or {}).get(sq.id)
    checklist = cr.checklist if cr else []
    group_labels = cr.group_labels if cr else []
    provision_key = (cr.provision_key if cr and cr.provision_key else sq.provision_key) or ""
    known = list(sq.known_facts) + list(sq.shared_context.known_facts)
    history = list(state.get("audit_history") or [])

    result = run_auditor(checklist, known, group_labels=group_labels,
                         provision_key=provision_key, history=history)
    if result.is_complete:
        audit_results = dict(state.get("audit_results") or {}); audit_results[sq.id] = result
        return {"audit_results": audit_results, "audit_history": history}
    answer = interrupt({
        "type": "audit_clarification",
        "provision": result.provision_key,
        "question": result.pending_question,
        "condition": result.pending_condition,
    })
    history.append({
        "question": result.pending_question,
        "answer": answer,
        "condition": result.pending_condition,
    })
    return {"audit_history": history}


def _advance_node(state: PipelineState) -> dict:
    return {"current_index": state["current_index"] + 1}


def _adjudicator_node(state: PipelineState) -> dict:
    result = run_adjudicator(
        state["sub_questions"],
        state.get("audit_results") or {},
        state.get("evidence") or {},
    )
    return {"adjudication": result}


# ─────────────────────────────────────────────
# Routers (conditional edges)
# ─────────────────────────────────────────────

def _after_query_agent(state: PipelineState) -> str:
    return "researcher" if state.get("sub_questions") else "query_agent"


def _after_researcher(state: PipelineState) -> str:
    # full pipeline (test_application) → checklist; short (informational) → skip ahead
    return "checklist" if _current_sq(state).recommended_pipeline == "full" else "advance"


def _after_auditor(state: PipelineState) -> str:
    sq = _current_sq(state)
    return "advance" if sq.id in (state.get("audit_results") or {}) else "auditor"


def _after_advance(state: PipelineState) -> str:
    return "researcher" if state["current_index"] < len(state["sub_questions"]) else "adjudicator"


# ─────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────

def build_graph(retriever: Any = None, *, checkpointer: Any = None):
    """
    Compile the pipeline graph. `retriever` is built once and shared by every
    researcher invocation (falls back to a null retriever if stores are down).
    A `MemorySaver` checkpointer is used by default so `interrupt()`/`Command(resume=...)`
    work; pass your own for persistence.
    """
    shared_retriever = _make_retriever(retriever)

    g = StateGraph(PipelineState)
    g.add_node("query_agent", _query_agent_node)
    g.add_node("researcher", _make_researcher_node(shared_retriever))
    g.add_node("checklist", _checklist_node)
    g.add_node("auditor", _auditor_node)
    g.add_node("advance", _advance_node)
    g.add_node("adjudicator", _adjudicator_node)

    g.add_edge(START, "query_agent")
    g.add_conditional_edges("query_agent", _after_query_agent,
                            {"researcher": "researcher", "query_agent": "query_agent"})
    g.add_conditional_edges("researcher", _after_researcher,
                            {"checklist": "checklist", "advance": "advance"})
    g.add_edge("checklist", "auditor")
    g.add_conditional_edges("auditor", _after_auditor,
                            {"advance": "advance", "auditor": "auditor"})
    g.add_conditional_edges("advance", _after_advance,
                            {"researcher": "researcher", "adjudicator": "adjudicator"})
    g.add_edge("adjudicator", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
