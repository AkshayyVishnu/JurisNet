"""
main.py — interactive CLI for the Query Agent.

Ask a legal query, see the structured JSON result, and answer any clarifying
questions the agent raises (missing-required / ambiguous / jurisdiction) — the
resume loop runs right here in the terminal until the agent reaches a clean,
"ready" set of sub-questions.

Run:
    uv run python main.py

Commands at any prompt:  quit / exit / q  -> leave.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from agents.query_agent import run_query_agent
from agents.schemas import QueryAgentResult

QUIT_WORDS = {"quit", "exit", "q"}
MAX_CLARIFY_ROUNDS = 6   # safety net so a misbehaving model can't loop forever


def _is_quit(text: str) -> bool:
    return text.strip().lower() in QUIT_WORDS


def _print_result(result: QueryAgentResult) -> None:
    """Dump the full structured result as JSON for verification."""
    print("\n--- structured result ---")
    print(json.dumps(result.model_dump(), indent=2, default=str))
    print("-------------------------")


def _ask_followup(result: QueryAgentResult) -> str | None:
    """
    Show the agent's clarifying question (and options, if ambiguous) and read the
    user's answer. Returns the answer, or None if the user chose to quit.
    """
    kind = result.clarification_kind.value if result.clarification_kind else "clarify"
    print(f"\n[agent needs clarification: {kind}]")
    print(f"  (known so far: {result.extracted_facts or '[]'}"
          f" | unknown: {result.unknown_fields or '[]'})")
    print(f"  Q: {result.pending_question}")

    options = result.options
    if options:
        print("  Options:")
        for i, opt in enumerate(options, start=1):
            print(f"    {i}. {opt}")
        print("  (type the option number, or describe your own answer)")

    answer = input("  Your answer: ").strip()
    if _is_quit(answer):
        return None

    # If they typed an option number, expand it to the option text.
    if options and answer.isdigit():
        idx = int(answer) - 1
        if 0 <= idx < len(options):
            answer = options[idx]
            print(f"  -> {answer}")
    return answer


def _handle_query(raw_query: str) -> None:
    """Run one query through the agent, looping on clarifications until ready."""
    history: list[dict] = []

    for _ in range(MAX_CLARIFY_ROUNDS + 1):
        try:
            result = run_query_agent(raw_query, history=history)
        except Exception as e:  # noqa: BLE001 - keep the CLI alive on transient API errors
            print(f"\n[error] {type(e).__name__}: {e}")
            return

        _print_result(result)

        if result.is_ready:
            print(f"\nREADY: {len(result.sub_questions)} sub-question(s) "
                  f"to send to the Researcher.")
            return

        answer = _ask_followup(result)
        if answer is None:
            print("  (cancelled this query)")
            return
        history.append({
            "question": result.pending_question,
            "answer": answer,
            "kind": result.clarification_kind.value if result.clarification_kind else None,
        })

    print("\n[stopped] still not resolved after "
          f"{MAX_CLARIFY_ROUNDS} clarification rounds.")


def run_cli() -> None:
    load_dotenv()
    if not os.environ.get("GROQ_API_KEY"):
        print("GROQ_API_KEY is not set. Add it to .env "
              "(free key: https://console.groq.com/keys), then re-run.")
        return

    print("=" * 60)
    print(" Query Agent CLI  -  ask a civil-law (CPC) question")
    print(" Commands: quit / exit / q")
    print("=" * 60)

    while True:
        try:
            query = input("\nEnter your legal query: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return

        if not query:
            continue
        if _is_quit(query):
            print("bye.")
            return

        _handle_query(query)


if __name__ == "__main__":
    run_cli()
