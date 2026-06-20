"""
run_pipeline.py — full agentic-pipeline chatbot CLI (LangGraph).

A conversational terminal client for the whole pipeline:

    Query Agent → Researcher → Checklist Resolver → Auditor → Adjudicator

It runs a REPL: you ask a civil-law question, the graph streams its stages live,
pauses to ask you clarifying questions when it needs to (the Query Agent's
clarification gate and the Auditor's ❓ loop — native LangGraph interrupts), and
then prints a grounded, cited adjudication. Ask as many questions as you like;
each is its own pipeline run. Type `quit` to leave.

Run:
    uv run python run_pipeline.py
    uv run python run_pipeline.py "your first question"   # optional seed query

(main.py remains the Query-Agent-only CLI; this drives the full pipeline.)
"""

from __future__ import annotations

import sys
import uuid
from typing import Any, Optional

from dotenv import load_dotenv
from langgraph.types import Command

from agents.graph import build_graph

# Best-effort UTF-8 so the glyphs below render on Windows consoles too.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

QUIT = {"quit", "exit", "q", ":q"}
HELP = {"help", "?", "/help"}

STAGE_LABEL = {
    "query_agent": "Understanding & splitting the question",
    "researcher": "Retrieving judgments, statutes & rules",
    "checklist": "Resolving the statutory checklist",
    "auditor": "Verifying the facts against each condition",
    "adjudicator": "Writing the grounded answer",
}

DIM, BOLD, ACCENT, GREEN, YELLOW, RESET = (
    "\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[0m",
)


# ─────────────────────────────────────────────
# Printing helpers
# ─────────────────────────────────────────────

def _banner() -> None:
    print(f"{BOLD}JurisNet — agentic Indian civil-law assistant{RESET}")
    print(f"{DIM}Full pipeline: Query Agent → Researcher → Checklist → Auditor → Adjudicator{RESET}")
    print(f"{DIM}Ask a civil-law question. Commands: help · quit{RESET}")
    print("─" * 70)


def _help() -> None:
    print(f"{DIM}Ask any Indian civil-law (CPC) question in plain English, e.g.:{RESET}")
    print("  • What is the test for a temporary injunction under Order 39 Rule 1 CPC?")
    print("  • Can I get my deposit back and challenge an eviction notice?")
    print("  • What does res judicata under Section 11 CPC mean?")
    print(f"{DIM}The assistant may ask you to clarify or supply a fact — just answer inline.{RESET}")
    print(f"{DIM}Commands: help · quit/exit/q{RESET}")


def _stage(node: str) -> None:
    label = STAGE_LABEL.get(node)
    if label:
        print(f"  {ACCENT}▸{RESET} {label}…")


def _print_subquestions(subs: list) -> None:
    if not subs:
        return
    print(f"  {DIM}Split into {len(subs)} sub-question(s):{RESET}")
    for sq in subs:
        kind = "verify" if sq.query_type.value == "test_application" else "explain"
        prov = f" {DIM}· {sq.provision_key}{RESET}" if sq.provision_key else ""
        print(f"    {DIM}{sq.id}.{RESET} [{kind}] {sq.text}{prov}")


def _print_sources(evidence: dict) -> None:
    if not evidence:
        return
    newest = evidence[max(evidence)] or []
    if not newest:
        print(f"    {DIM}(no documents retrieved — answering from provision text only){RESET}")
        return
    print(f"    {DIM}retrieved {len(newest)} document(s); top:{RESET}")
    for c in newest[:3]:
        title = (c.get("title") or "Untitled")[:70]
        print(f"      {DIM}- {title}{RESET}")


def _clarify_prompt(payload: dict) -> str:
    print()
    if payload.get("type") == "audit_clarification":
        print(f"  {YELLOW}❓ To verify this I need a fact{RESET}"
              f"{DIM} (provision: {payload.get('provision')}){RESET}")
        if payload.get("condition"):
            print(f"     {DIM}condition: {payload['condition']}{RESET}")
    else:
        kind = payload.get("kind") or "clarification"
        print(f"  {YELLOW}❓ Clarification needed{RESET} {DIM}({kind}){RESET}")
    print(f"  {BOLD}{payload.get('question')}{RESET}")
    options = payload.get("options") or []
    for i, opt in enumerate(options, start=1):
        print(f"     {i}. {opt}")
    if options:
        print(f"     {DIM}(type a number, or describe your own answer){RESET}")
    ans = input(f"  {ACCENT}your answer ›{RESET} ").strip()
    if options and ans.isdigit() and 1 <= int(ans) <= len(options):
        ans = options[int(ans) - 1]
    return ans


def _print_adjudication(state: dict) -> None:
    adj = state.get("adjudication")
    if adj is None:
        print(f"\n  {YELLOW}No answer was produced.{RESET}")
        return

    # Per-sub-question verification summary (test_application sub-questions only).
    audits = state.get("audit_results") or {}
    if audits:
        print(f"\n  {DIM}Verification:{RESET}")
        for sid, ar in sorted(audits.items()):
            det = ar.determination or "—"
            mark = {"applies": GREEN + "✓ applies",
                    "fails": "\033[31m✗ fails",
                    "indeterminate": YELLOW + "~ indeterminate",
                    "no_checklist": DIM + "· no checklist"}.get(det, det)
            print(f"    {DIM}SQ{sid}:{RESET} {mark}{RESET} {DIM}({len(ar.surviving_set)} verified condition(s)){RESET}")

    print(f"\n{BOLD}{ACCENT}╾ Verdict ╼{RESET}")
    print(_wrap(adj.ultimate_verdict, indent="  "))

    if adj.sub_answers:
        print(f"\n{BOLD}Findings{RESET}")
        for sa in adj.sub_answers:
            print(f"  {ACCENT}•{RESET} {BOLD}{sa.conclusion}{RESET}")
            print(_wrap(sa.reasoning, indent="    "))
            if sa.citations:
                print(f"    {DIM}cited: {', '.join(sa.citations)}{RESET}")

    if adj.options:
        print(f"\n{BOLD}Options{RESET}")
        for o in adj.options:
            print(f"  {ACCENT}•{RESET} {BOLD}{o.title}{RESET}")
            print(_wrap(o.description, indent="    "))
            if o.citations:
                print(f"    {DIM}cited: {', '.join(o.citations)}{RESET}")

    if adj.synthesis_and_conflicts:
        print(f"\n{BOLD}Synthesis & conflicts{RESET}")
        print(_wrap(adj.synthesis_and_conflicts, indent="  "))


def _wrap(text: str, indent: str = "", width: int = 92) -> str:
    import textwrap
    out = []
    for para in (text or "").split("\n"):
        out.append(textwrap.fill(para, width=width,
                                 initial_indent=indent, subsequent_indent=indent) or indent.rstrip())
    return "\n".join(out)


# ─────────────────────────────────────────────
# One pipeline turn (stream + inline interrupts)
# ─────────────────────────────────────────────

def _run_turn(graph: Any, query: str) -> None:
    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    payload: Any = {"raw_query": query}

    print(f"\n{DIM}JurisNet is reasoning…{RESET}")
    while True:
        interrupt_val: Optional[dict] = None
        for chunk in graph.stream(payload, config=config, stream_mode="updates"):
            if "__interrupt__" in chunk:
                interrupt_val = chunk["__interrupt__"][0].value or {}
                continue
            for node, delta in chunk.items():
                if not isinstance(delta, dict):
                    continue
                _stage(node)
                if node == "query_agent" and delta.get("sub_questions"):
                    _print_subquestions(delta["sub_questions"])
                if node == "researcher" and "evidence" in delta:
                    _print_sources(delta["evidence"])

        if interrupt_val is None:
            break  # reached END
        answer = _clarify_prompt(interrupt_val)
        payload = Command(resume=answer)

    _print_adjudication(graph.get_state(config).values)


# ─────────────────────────────────────────────
# REPL
# ─────────────────────────────────────────────

def main() -> None:
    load_dotenv()
    _banner()
    print(f"{DIM}Connecting to retrieval + building the graph…{RESET}")
    try:
        graph = build_graph()
    except Exception as e:  # noqa: BLE001
        print(f"{YELLOW}Failed to build the pipeline: {type(e).__name__}: {e}{RESET}")
        return

    seed = " ".join(sys.argv[1:]).strip()
    while True:
        if seed:
            query, seed = seed, ""
            print(f"\n{BOLD}you ›{RESET} {query}")
        else:
            try:
                query = input(f"\n{BOLD}you ›{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nbye.")
                return
        if not query:
            continue
        low = query.lower()
        if low in QUIT:
            print("bye.")
            return
        if low in HELP:
            _help()
            continue
        try:
            _run_turn(graph, query)
        except KeyboardInterrupt:
            print(f"\n{DIM}(interrupted — back to the prompt){RESET}")
        except Exception as e:  # noqa: BLE001 — keep the chat alive on transient errors
            print(f"\n{YELLOW}[error] {type(e).__name__}: {e}{RESET}")


if __name__ == "__main__":
    main()
