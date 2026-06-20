"""
query_agent.py
──────────────
The Query Agent (CLAUDE.md §2b). FIRST stage of the pipeline.

It turns a raw user query into clean, self-contained `SubQuestion`s for the
Researcher — OR it stops and asks the user ONE clarifying question.

Design (approved):
  • Single structured LLM call. The §2b decision tree (reformulate → extract →
    required/ambiguous/jurisdiction gates → split) is encoded as the output schema
    (schemas.QueryAnalysis), not as four separate API round-trips.
  • Resume loop. On a clarification, the caller appends {question, answer} to
    `history` and re-invokes — framework-agnostic, and maps onto a LangGraph
    interrupt later.
  • Injectable LLM. `run_query_agent(..., llm=...)` lets tests drive the assembly
    logic with a fake LLM (no API key) and lets the harness inject real Groq.

Public entry point:
    run_query_agent(raw_query: str, history=None, llm=None) -> QueryAgentResult
"""

from __future__ import annotations

import os
import re
from typing import Any, List, Optional

from dotenv import load_dotenv

from .schemas import (
    ClarificationKind,
    Complexity,
    QueryAnalysis,
    QueryAgentResult,
    QueryType,
    RelationshipType,
    SharedContext,
    SubQuestion,
    SubQuestionDraft,
)

# §4 / §2b model-tier re-test (2026-06-20): llama-3.1-8b-instant FAILED the live
# run — its tool-calls were malformed (text-wrapped <function=...>, Python `True`,
# `null` for arrays) and Groq rejected them 400. llama-3.3-70b-versatile passes the
# same queries cleanly with function_calling. json_schema mode is unsupported on
# both Llama models, so we stay on function_calling. Bumped to the balanced tier.
DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Clarification loop control (CLAUDE.md §2b "missing-required" fix).
# A single clarification field/gate is asked at most twice; after that it is marked
# UNKNOWN and we proceed. We also stop immediately if the user says they can't
# provide it, rather than re-asking the same thing.
MAX_ASKS_PER_FIELD = 2

_DONT_KNOW_RE = re.compile(
    r"\b("
    r"i\s*(do\s*not|don'?t|dont)\s*know"
    r"|no\s*idea|not\s*sure|unsure|uncertain|not\s*certain"
    r"|can'?t\s*(tell|say|remember|recall)|don'?t\s*(remember|recall)"
    r"|dunno|no\s*clue|prefer\s*not|rather\s*not|none\s*of\s*your"
    r"|n/?a"
    r")\b",
    re.IGNORECASE,
)


def _is_dont_know(answer: str) -> bool:
    """True if the user's answer signals they can't/won't provide the asked info."""
    return bool(answer and _DONT_KNOW_RE.search(answer))


SYSTEM_PROMPT = """\
You are the Query Agent for an Indian CIVIL-law (Code of Civil Procedure) legal
assistant. You are the FIRST stage of the pipeline. You do NOT answer the legal
question and you do NOT retrieve anything. You either (a) produce clean,
self-contained sub-questions for the retrieval stage, or (b) stop and ask the user
exactly ONE clarifying question.

SCOPE: civil cases only. If a query is purely criminal-law, it is out of scope —
set needs_clarification=True, clarification_kind="missing_required", and say it is
outside the civil-law scope.

Do your job in this order:

1. REFORMULATE — restate what is actually being asked, in clear legal terms.

2. EXTRACT FACTS — pull every concrete fact stated (parties, amounts, dates,
   actions, locations). These become shared context for every sub-question.
   Write each fact as a COMPLETE statement that keeps the ACTION/EVENT together with
   its object — do NOT reduce a fact to bare nouns. E.g. for "my partner is selling
   our disputed plot" extract "the business partner is selling the disputed plot",
   NOT "business partner" + "disputed plot". The Auditor later checks these facts
   against statutory conditions, so a dropped verb (sold, demolished, notified, paid)
   silently breaks verification.

3. DECIDE WHETHER TO CLARIFY. Check these gates in PRIORITY ORDER and surface ONLY
   the single highest-priority issue (ask one question, never several):
   a. missing_required — there is NO identifiable legal question to retrieve on.
      This is the ONLY thing you may demand. Do NOT ask the user for case details
      such as dates, amounts, contract clauses, or whether notice was given — a
      later component (the Auditor) gathers those against the actual statute. If
      there is a clear legal question, this gate does NOT fire.
   b. ambiguous — the input maps to two or more DISTINCT legal questions/provisions
      and you cannot tell which the user means. PREFER this over missing_required when
      the user HAS stated a goal but it has several plausible legal readings. Put each
      reading in `options` (2-4 short phrases) and ask which they mean.
      Example: "Can I get my money back from my landlord?" -> ambiguous, options =
      ["return of security deposit", "refund of overcharged maintenance", "recovery of
      advance rent"]. Do NOT collapse a genuinely multi-reading query into a single
      "what is the reason?" question.
   c. jurisdiction — fire ONLY when the answer is a state-determined NUMBER or
      PROCEDURE that literally cannot be given without knowing the State, and no State
      is stated. This is narrow: court fees, limitation periods, stamp duty, pecuniary
      jurisdiction, or a specific State's CPC amendment. For these, the whole answer
      changes with the State, so you must ask which State.
      Do NOT fire jurisdiction for SUBSTANTIVE rights questions — eviction, security
      deposit, contract validity, property, landlord-tenant rights, etc. Those have a
      general civil-law framework that retrieval can answer, and any state-specific
      nuance is gathered later downstream — proceed and split instead of asking for the
      State. Example that must NOT trigger jurisdiction: "Can I recover my security
      deposit and can my landlord evict me?" -> proceed to sub-questions.
   If none fire, set needs_clarification=False and split instead.

4. SPLIT into sub-questions (only when not clarifying). DEFAULT TO NOT SPLITTING.
   Most queries are ONE sub-question. Only split when the query contains genuinely
   separate, INDEPENDENTLY-CHECKABLE legal issues — not when a single question can
   be broken into hierarchical or definitional steps.

   The test: would the user recognise each sub-question as something they actually
   asked? If a "sub-question" exists only to give background or definition for
   answering another, it is NOT a separate sub-question — collapse it into the real
   one.

   Decisive heuristic: would answering the parts hit the SAME provision/statute or
   DIFFERENT ones? Same provision -> ONE sub-question, no matter how many concepts
   are mentioned. Different provisions, each independently relevant to what was
   asked -> split.

   Do NOT split for hierarchical decomposition. Structural/definitional context
   (how a rule relates to its parent order, or to the code it sits under) is handled
   downstream by graph expansion — you do NOT ask "what is X" before asking about a
   specific provision of X.

   WRONG — single provision lookup split into 3:
     Query: "What does Order 1 Rule 10 of the Code of Civil Procedure allow?"
     Bad:  ["What is the Code of Civil Procedure?",
            "What is Order 1 of the Code of Civil Procedure?",
            "What does Rule 10 of Order 1 allow?"]
     Right: ONE sub-question — "What does Order 1 Rule 10 of the Code of Civil
     Procedure allow?"

   RIGHT — two genuinely separate claims (different provisions):
     Query: "My landlord is keeping my deposit and threatening to evict me because
     I complained about water leakage."
     Right: TWO sub-questions — one about deposit recovery, one about eviction
     protection — each checks a different provision against different facts, and the
     user is asking about both.

   For each sub-question you DO emit:
    - It MUST read completely on its own. When the original query links issues
      causally, BAKE that link into the sub-question text — do not drop it and do not
      leave it for a later stage to reconstruct.
    - Set query_type for each sub-question (REQUIRED — this drives pipeline routing):
        * test_application — the sub-question asks whether a specific fact pattern
          satisfies a legal test, standard, or set of statutory/case-law conditions.
          These need the full verification pipeline (Researcher → Checklist Resolver →
          Auditor → Adjudicator). Examples: "Can my landlord evict me for non-payment?",
          "Does this contract clause violate Section 23?"
        * informational — the sub-question is explanatory, definitional, or procedural.
          It asks WHAT something is, HOW a process works, or WHAT a provision says —
          without applying it to a specific fact pattern. These skip straight from
          Researcher to Adjudicator (no checklist, no audit). Examples: "What does Order
          1 Rule 10 CPC allow?", "What is the procedure for filing a suit?", "What is
          res judicata?"
    - Set provision_key if a specific legal provision or doctrine is identifiable. This
      is the lookup key for the Checklist Resolver downstream, so be precise. It is NOT
      limited to statute sections — case-law-only doctrines (e.g. "res judicata",
      "doctrine of frustration") are valid provision keys. Null only if the sub-question
      is too general to tie to any specific provision.
    - Set relationship_type for each sub-question:
        * independent — stands alone, unrelated to the other sub-questions.
        * causal — the original query ties this issue to another by cause/effect.
          Example: "my landlord raised my rent BECAUSE I refused to vacate" → the
          rent-increase sub-question is 'causal' and its depends_on lists the
          sub-question it hinges on (the vacate-request one).
        * dependent — answering this needs another sub-question's answer first.
      When the original query uses a linking word (because, after, since, so, as a
      result, in response to, when I) prefer causal/dependent and set depends_on to the
      id(s) it links to. Use independent ONLY when the issues are genuinely unrelated.
    - Rate complexity: simple = one provision/fact lookup; moderate = a few sources
      combined; complex = multi-issue or needs broad context.

If the conversation already contains the user's answer to a previous clarifying
question, USE it and continue — do not ask the same thing again.

If the user indicates they cannot provide something you asked for (e.g. "I don't
know", "not sure"), do NOT ask it again: record a short label for that gap in
unknown_fields, set needs_clarification=false, and proceed with the information you
do have. Never ask about the same missing item more than twice.
"""


# ─────────────────────────────────────────────
# LLM construction (real Groq, structured output)
# ─────────────────────────────────────────────

def build_structured_llm(model: Optional[str] = None) -> Any:
    """
    Build a rotation-aware structured LLM that returns a `QueryAnalysis` directly.
    Reads model from env/default, handles routing and rotation across API key pools.
    """
    load_dotenv()
    model = model or os.environ.get("QUERY_AGENT_MODEL") or DEFAULT_MODEL
    from .llm_factory import build_rotating_structured_llm
    return build_rotating_structured_llm(QueryAnalysis, model)



# ─────────────────────────────────────────────
# Message assembly (original query + resume history)
# ─────────────────────────────────────────────

def _build_messages(
    raw_query: str, history: List[dict], directive: Optional[str] = None
) -> list:
    """
    Render the conversation for the model: the original query, then each prior
    clarification round so the model can use answers it already received. An optional
    `directive` (e.g. "stop asking X, treat as unknown, proceed") is appended last.

    history items: {"question": <asked>, "answer": <user reply>, "kind": <gate>}
    """
    messages: list = [
        ("system", SYSTEM_PROMPT),
        ("human", f"Original user query:\n{raw_query}"),
    ]
    for turn in history:
        q = turn.get("question", "")
        a = turn.get("answer", "")
        messages.append(("ai", f"(clarifying question) {q}"))
        messages.append(("human", f"(user answer) {a}"))
    if directive:
        messages.append(("human", directive))
    return messages


# ─────────────────────────────────────────────
# Clarification loop control — don't-know + 2-ask cap (PART 1)
# ─────────────────────────────────────────────

def _forced_unknown_kinds(history: List[dict]) -> set:
    """
    Clarification kinds we must STOP asking about and treat as UNKNOWN:
      • the user's most recent answer is an explicit "I don't know", or
      • that kind has already been asked MAX_ASKS_PER_FIELD times (hard cap).
    Relies on history entries carrying 'kind' (the caller records it when it appends
    a clarify turn). Entries without 'kind' still feed the don't-know check.
    """
    forced: set = set()
    counts: dict = {}
    for turn in history:
        k = turn.get("kind")
        if k:
            counts[k] = counts.get(k, 0) + 1
    for k, c in counts.items():
        if c >= MAX_ASKS_PER_FIELD:
            forced.add(k)
    if history and _is_dont_know(history[-1].get("answer", "")):
        k = history[-1].get("kind")
        if k:
            forced.add(k)
    return forced


def _proceed_directive(history: List[dict], forced: set) -> Optional[str]:
    """Instruct the model to stop asking about forced-unknown gaps and proceed."""
    if not forced:
        return None
    questions = [
        turn["question"]
        for turn in history
        if turn.get("kind") in forced and turn.get("question")
    ]
    asked = "; ".join(f'"{q}"' for q in dict.fromkeys(questions)) or ", ".join(sorted(forced))
    return (
        f"NOTE: The user could not provide: {asked}. Do NOT ask about this again. "
        "Treat each as UNKNOWN: add a short label for each gap to unknown_fields, set "
        "needs_clarification=false, and produce the best sub-question(s) you can from "
        "the information that IS available."
    )


# ─────────────────────────────────────────────
# Post-processing: LLM draft → final result
# ─────────────────────────────────────────────

def _to_result(
    raw_query: str, analysis: QueryAnalysis, forced_unknowns: set = frozenset()
) -> QueryAgentResult:
    """
    Convert the single-call LLM output into the public result, applying the
    code-owned steps the LLM never does:
      • assign 1-based ids to sub-questions
      • attach the shared context object to EVERY sub-question (§2b mechanism 1)
      • merge model-declared unknowns with code-forced ones (cap / don't-know)
    Includes defensive fallbacks so a malformed LLM response degrades to a sane
    clarify rather than emitting empty/garbage sub-questions downstream.
    """
    unknown = list(dict.fromkeys([*analysis.unknown_fields, *sorted(forced_unknowns)]))

    if analysis.needs_clarification:
        return QueryAgentResult(
            status="clarify",
            reformulated_query=analysis.reformulated_query,
            pending_question=analysis.pending_question
            or "Could you clarify your legal question?",
            clarification_kind=analysis.clarification_kind
            or ClarificationKind.MISSING_REQUIRED,
            options=analysis.options,
            extracted_facts=analysis.extracted_facts,
            unknown_fields=unknown,
        )

    # Defensive: model said "ready" but gave nothing to work with.
    if not analysis.sub_questions:
        return QueryAgentResult(
            status="clarify",
            reformulated_query=analysis.reformulated_query,
            pending_question="What specifically is your legal question?",
            clarification_kind=ClarificationKind.MISSING_REQUIRED,
            extracted_facts=analysis.extracted_facts,
            unknown_fields=unknown,
        )

    shared = SharedContext(
        original_query=raw_query,
        known_facts=analysis.extracted_facts,
        unknown_fields=unknown,
    )
    sub_questions = [
        SubQuestion(
            id=i,
            text=draft.text,
            query_type=draft.query_type,
            provision_key=draft.provision_key,
            complexity=draft.complexity,
            relationship_type=draft.relationship_type,
            depends_on=draft.depends_on,
            known_facts=draft.known_facts,
            shared_context=shared,
        )
        for i, draft in enumerate(analysis.sub_questions, start=1)
    ]
    return QueryAgentResult(
        status="ready",
        reformulated_query=analysis.reformulated_query,
        sub_questions=sub_questions,
        extracted_facts=analysis.extracted_facts,
        unknown_fields=unknown,
    )


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

def run_query_agent(
    raw_query: str,
    history: Optional[List[dict]] = None,
    llm: Any = None,
    model: Optional[str] = None,
) -> QueryAgentResult:
    """
    Run the Query Agent for one turn.

    Args:
        raw_query: the user's original question (kept verbatim across the loop).
        history:   prior clarification rounds [{"question", "answer"}, ...]. On a
                   clarify result, append the asked question + the user's answer and
                   call again — that is the resume loop.
        llm:       a structured LLM (anything with .invoke(messages) -> QueryAnalysis).
                   If None, a real Groq client is built. Tests inject a fake here.
        model:     explicit Groq model id; if None, uses $QUERY_AGENT_MODEL then
                   DEFAULT_MODEL (only consulted when llm is None).

    Returns:
        QueryAgentResult with status "ready" (sub_questions filled) or "clarify"
        (pending_question filled).
    """
    history = history or []

    # Deterministic pre-check — don't spend an LLM call on empty/blank input.
    if not raw_query or not raw_query.strip():
        return QueryAgentResult(
            status="clarify",
            pending_question="What is your legal question?",
            clarification_kind=ClarificationKind.MISSING_REQUIRED,
        )

    # PART 1: decide which gaps to stop asking about (don't-know / 2-ask cap) and
    # build a directive telling the model to proceed treating them as unknown.
    forced = _forced_unknown_kinds(history)
    directive = _proceed_directive(history, forced)

    structured_llm = llm if llm is not None else build_structured_llm(model)
    analysis: QueryAnalysis = structured_llm.invoke(
        _build_messages(raw_query, history, directive)
    )

    # Enforce the cap: if the model still tries to clarify a forced gap, push once
    # more, then proceed regardless of what it returns.
    if (
        forced
        and analysis.needs_clarification
        and analysis.clarification_kind
        and analysis.clarification_kind.value in forced
    ):
        hard = (directive or "") + (
            " You MUST NOT ask another question now. Set needs_clarification=false "
            "and return sub_questions using what is available."
        )
        analysis = structured_llm.invoke(_build_messages(raw_query, history, hard))

    return _to_result(raw_query, analysis, forced)


# ─────────────────────────────────────────────
# Manual CLI (real Groq): uv run python -m agents.query_agent "your question"
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json

    query = sys.argv[1] if len(sys.argv) > 1 else "What does Order 1 Rule 10 CPC allow?"
    result = run_query_agent(query)
    print(json.dumps(result.model_dump(), indent=2, default=str))
