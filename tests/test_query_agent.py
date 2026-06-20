"""
test_query_agent.py — scripted regression suite for the Query Agent.

Two layers:

  • OFFLINE (no API key): fake LLM + direct calls to the pure helpers. Deterministic
    coverage of PART 1 code logic (don't-know detection, 2-ask cap computation,
    unknown-field plumbing) and the assembly logic.

  • LIVE (needs GROQ_API_KEY): scripted multi-turn cases A–E (+ B3/B4 for the
    don't-know / cap behavior). `run_scripted(query, answers)` simulates each
    clarify-loop turn by feeding scripted answers — no live typing needed.

On FAIL, the offending result JSON is printed so the mismatch is visible at once.

Run:
    uv run python -m tests.test_query_agent
"""

from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv

from agents.query_agent import (
    _forced_unknown_kinds,
    _is_dont_know,
    run_query_agent,
)
from agents.schemas import (
    ClarificationKind,
    Complexity,
    QueryAnalysis,
    QueryType,
    RelationshipType,
    SubQuestionDraft,
)

PASS, FAIL = 0, 0


def _dump(result) -> str:
    return json.dumps(result.model_dump(), indent=2, default=str)


def check(label: str, cond: bool, result=None, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")
        if result is not None:
            print("        result:", _dump(result).replace("\n", "\n        "))


# ─────────────────────────────────────────────
# Fake LLM (offline)
# ─────────────────────────────────────────────

class FakeLLM:
    def __init__(self, analysis: QueryAnalysis):
        self._analysis = analysis
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return self._analysis


# ─────────────────────────────────────────────
# OFFLINE tests
# ─────────────────────────────────────────────

def offline_tests() -> None:
    print("\n=== OFFLINE (no API key) ===\n")

    # --- don't-know detection ---
    for s in ["I don't know", "i dont know", "not sure", "no idea",
              "can't tell", "dunno", "I'm not certain", "n/a"]:
        check(f"dont_know TRUE: {s!r}", _is_dont_know(s) is True)
    for s in ["Maharashtra", "the deposit was 50000", "yes he evicted me"]:
        check(f"dont_know FALSE: {s!r}", _is_dont_know(s) is False)

    # --- forced-unknown computation: cap, don't-know, none ---
    cap_hist = [{"kind": "jurisdiction", "question": "q", "answer": "hmm"},
                {"kind": "jurisdiction", "question": "q", "answer": "huh"}]
    check("cap: 2 asks -> forced", _forced_unknown_kinds(cap_hist) == {"jurisdiction"})
    dk_hist = [{"kind": "jurisdiction", "question": "q", "answer": "no idea"}]
    check("dont-know: forced", _forced_unknown_kinds(dk_hist) == {"jurisdiction"})
    ok_hist = [{"kind": "jurisdiction", "question": "q", "answer": "Maharashtra"}]
    check("resolved answer: not forced", _forced_unknown_kinds(ok_hist) == set())

    # --- plumbing: forced unknowns merge into ready result + shared_context ---
    ready_fake = FakeLLM(QueryAnalysis(
        reformulated_query="court fee question",
        extracted_facts=["civil suit"],
        needs_clarification=False,
        unknown_fields=["filing court"],
        sub_questions=[SubQuestionDraft(
            text="What is the court fee for a civil suit?",
            query_type=QueryType.INFORMATIONAL,
            complexity=Complexity.SIMPLE,
            relationship_type=RelationshipType.INDEPENDENT,
        )],
    ))
    r = run_query_agent("court fee?", history=cap_hist, llm=ready_fake)
    check("plumbing: ready despite forced", r.is_ready, r)
    check("plumbing: result.unknown merges model + forced",
          set(r.unknown_fields) == {"filing court", "jurisdiction"}, r)
    check("plumbing: extracted_facts surfaced", r.extracted_facts == ["civil suit"], r)
    check("plumbing: shared_context carries unknown",
          set(r.sub_questions[0].shared_context.unknown_fields) == {"filing court", "jurisdiction"}, r)

    # --- visibility: a clarify result still exposes extracted_facts ---
    clarify_fake = FakeLLM(QueryAnalysis(
        reformulated_query="landlord issue",
        extracted_facts=["landlord", "deposit"],
        needs_clarification=True,
        clarification_kind=ClarificationKind.MISSING_REQUIRED,
        pending_question="What is the specific issue?",
    ))
    r = run_query_agent("landlord thing", llm=clarify_fake)
    check("visibility: clarify exposes extracted_facts",
          r.extracted_facts == ["landlord", "deposit"], r)

    # --- assembly basics: ids + shared context across a split ---
    split_fake = FakeLLM(QueryAnalysis(
        reformulated_query="two issues",
        extracted_facts=["f"],
        needs_clarification=False,
        sub_questions=[
            SubQuestionDraft(text="A?", query_type=QueryType.INFORMATIONAL,
                             complexity=Complexity.SIMPLE,
                             relationship_type=RelationshipType.INDEPENDENT),
            SubQuestionDraft(text="B?", query_type=QueryType.INFORMATIONAL,
                             complexity=Complexity.SIMPLE,
                             relationship_type=RelationshipType.INDEPENDENT),
        ],
    ))
    r = run_query_agent("raw", llm=split_fake)
    check("assembly: ids 1,2", [s.id for s in r.sub_questions] == [1, 2], r)
    check("assembly: shared context identical",
          r.sub_questions[0].shared_context == r.sub_questions[1].shared_context, r)

    # --- query_type + provision_key plumbing ---
    typed_fake = FakeLLM(QueryAnalysis(
        reformulated_query="eviction test",
        extracted_facts=["tenant", "non-payment"],
        needs_clarification=False,
        sub_questions=[
            SubQuestionDraft(
                text="Can a landlord evict for non-payment?",
                query_type=QueryType.TEST_APPLICATION,
                provision_key="Transfer of Property Act Section 111",
                complexity=Complexity.MODERATE,
                relationship_type=RelationshipType.INDEPENDENT,
            ),
            SubQuestionDraft(
                text="What is the procedure for filing an eviction suit?",
                query_type=QueryType.INFORMATIONAL,
                provision_key="Order 37 CPC",
                complexity=Complexity.SIMPLE,
                relationship_type=RelationshipType.INDEPENDENT,
            ),
        ],
    ))
    r = run_query_agent("eviction stuff", llm=typed_fake)
    check("query_type: test_application passes through",
          r.sub_questions[0].query_type == QueryType.TEST_APPLICATION, r)
    check("query_type: informational passes through",
          r.sub_questions[1].query_type == QueryType.INFORMATIONAL, r)
    check("provision_key: passes through",
          r.sub_questions[0].provision_key == "Transfer of Property Act Section 111", r)
    check("recommended_pipeline: test_application -> full",
          r.sub_questions[0].recommended_pipeline == "full", r)
    check("recommended_pipeline: informational -> short",
          r.sub_questions[1].recommended_pipeline == "short", r)
    check("provision_key: None when not set",
          SubQuestionDraft(
              text="x", query_type=QueryType.INFORMATIONAL,
              complexity=Complexity.SIMPLE,
              relationship_type=RelationshipType.INDEPENDENT,
          ).provision_key is None, r)


# ─────────────────────────────────────────────
# LIVE scripted driver + cases
# ─────────────────────────────────────────────

def run_scripted(query: str, answers: list[str]) -> list:
    """
    Drive the clarify loop, feeding `answers` to each clarification in order.
    Returns the list of results, one per turn (results[0] = first turn).
    """
    history: list[dict] = []
    results: list = []
    for i in range(len(answers) + 1):
        r = run_query_agent(query, history=history)
        results.append(r)
        if r.is_ready or i >= len(answers):
            break
        history.append({
            "question": r.pending_question,
            "answer": answers[i],
            "kind": r.clarification_kind.value if r.clarification_kind else None,
        })
    return results


def _jur_asks(results: list) -> int:
    return sum(
        1 for r in results
        if r.status == "clarify" and r.clarification_kind == ClarificationKind.JURISDICTION
    )


def live_tests() -> None:
    print("\n=== LIVE (real Groq, scripted) ===\n")
    AMBIG = ClarificationKind.AMBIGUOUS
    JUR = ClarificationKind.JURISDICTION
    REQ = ClarificationKind.MISSING_REQUIRED
    DEP_CAUSAL = {RelationshipType.DEPENDENT, RelationshipType.CAUSAL}

    # ---- A. Splitting correctness ----
    print("\n-- A1: atomic lookup (regression) --")
    res = run_scripted("What does Order 1 Rule 10 of the Code of Civil Procedure allow?", [])
    f = res[-1]
    check("A1: ready", f.is_ready, f)
    check("A1: exactly 1 sub-question", len(f.sub_questions) == 1, f,
          detail=f"got {len(f.sub_questions)}")

    print("\n-- A2: genuinely compound (deposit + eviction) --")
    res = run_scripted(
        "My landlord is keeping my security deposit and is also threatening to evict me. "
        "Can I recover the deposit, and can he evict me?", [])
    f = res[-1]
    check("A2: ready", f.is_ready, f)
    check("A2: exactly 2 sub-questions", len(f.sub_questions) == 2, f,
          detail=f"got {len(f.sub_questions)}")

    print("\n-- A3: dependent / causal --")
    res = run_scripted(
        "My landlord raised my rent because I refused his informal request to vacate. "
        "Is the rent increase valid, and was the informal vacate request itself lawful?", [])
    f = res[-1]
    check("A3: ready", f.is_ready, f)
    has_link = any(s.relationship_type in DEP_CAUSAL for s in f.sub_questions)
    check("A3: a sub-question is dependent/causal", has_link, f)
    dep = next((s for s in f.sub_questions if s.relationship_type in DEP_CAUSAL), None)
    check("A3: dependent sub-question has depends_on", bool(dep and dep.depends_on), f)
    causal_text = any(re.search(r"because|after|refus|in response|retaliat", s.text, re.I)
                      for s in f.sub_questions)
    check("A3: causal language embedded in sub-question text", causal_text, f)

    # ---- B. Clarification — missing required field ----
    print("\n-- B1: single missing field --")
    res = run_scripted("I want to file a civil suit.", [])
    f0 = res[0]
    check("B1: first turn clarifies", f0.status == "clarify", f0)
    check("B1: kind == missing_required", f0.clarification_kind == REQ, f0,
          detail=f"got {f0.clarification_kind}")

    print("\n-- B2: partial-answer handling (minimal-required design) --")
    res = run_scripted(
        "My landlord is trying to kick me out of my rented flat.",
        ["He says I haven't paid rent for the last two months."])
    check("B2: turn 1 clarifies the bare query", res[0].status == "clarify", res[0])
    qs = [r.pending_question for r in res if r.status == "clarify"]
    check("B2: never re-asks the identical question", len(qs) == len(set(qs)), res[-1])
    check("B2: reaches ready once the issue is identifiable", res[-1].is_ready, res[-1])
    # Decided (minimal-required): case facts like lease terms / notice are gathered
    # later by the Auditor's checklist loop, NOT interrogated here. Going ready after
    # the eviction reason is correct — we assert the SAFE invariants, not a re-ask.

    print("\n-- B3: 'I don't know' -> mark unknown + proceed (PART 1) --")
    res = run_scripted("What is the court fee for filing a civil suit?", ["I don't know"])
    f = res[-1]
    check("B3: proceeds to ready despite don't-know", f.is_ready, f)
    check("B3: records the gap in unknown_fields", len(f.unknown_fields) >= 1, f)
    check("B3: did not loop (<= 2 turns)", len(res) <= 2, f)

    print("\n-- B4: 2-ask hard cap (PART 1) --")
    res = run_scripted("What is the court fee for filing a civil suit?",
                       ["hmm not sure what you mean", "it's complicated"])
    f = res[-1]
    check("B4: eventually ready", f.is_ready, f)
    check("B4: jurisdiction asked at most twice", _jur_asks(res) <= 2, f,
          detail=f"asked {_jur_asks(res)}x")

    # ---- C. Clarification — ambiguity ----
    print("\n-- C1: real ambiguity --")
    res = run_scripted("Can I get my money back from my landlord?", [])
    f0 = res[0]
    check("C1: kind == ambiguous", f0.clarification_kind == AMBIG, f0,
          detail=f"got {f0.clarification_kind}")
    check("C1: >=2 options offered", len(f0.options) >= 2, f0,
          detail=f"got {len(f0.options)}")

    print("\n-- C2: ambiguity not trigger-happy (negative control) --")
    res = run_scripted("What does Order 1 Rule 10 of the Code of Civil Procedure allow?", [])
    check("C2: never classified ambiguous",
          all(r.clarification_kind != AMBIG for r in res), res[-1])

    # ---- D. Clarification — jurisdiction ----
    print("\n-- D1: jurisdiction entirely blank --")
    res = run_scripted("What is the court fee for filing a civil suit?", [])
    f0 = res[0]
    check("D1: clarifies (no silent default)", f0.status == "clarify", f0)
    check("D1: kind == jurisdiction", f0.clarification_kind == JUR, f0,
          detail=f"got {f0.clarification_kind}")

    print("\n-- D2: jurisdiction partial (country given, state missing) --")
    res = run_scripted("What is the court fee for filing a civil suit in India?", [])
    f0 = res[0]
    check("D2: clarifies for the missing state", f0.status == "clarify", f0)
    check("D2: asks about state/region",
          bool(f0.pending_question and re.search(r"state|region|which", f0.pending_question, re.I)),
          f0)

    print("\n-- D3: fully specified jurisdiction (negative control) --")
    res = run_scripted("What is the court fee for filing a civil suit in Maharashtra?", [])
    f = res[-1]
    check("D3: reaches ready", f.is_ready, f)
    check("D3: never asked about jurisdiction", _jur_asks(res) == 0, f)

    # ---- E. Shared context integrity ----
    print("\n-- E1: shared context integrity (reuse a compound query) --")
    q = ("My landlord is keeping my security deposit and is also threatening to evict me. "
         "Can I recover the deposit, and can he evict me?")
    res = run_scripted(q, [])
    f = res[-1]
    if f.is_ready and len(f.sub_questions) >= 2:
        check("E1: original_query identical across sub-questions",
              all(s.shared_context.original_query == q for s in f.sub_questions), f)
        first_facts = f.sub_questions[0].shared_context.known_facts
        check("E1: known_facts consistent across sub-questions",
              all(s.shared_context.known_facts == first_facts for s in f.sub_questions), f)
    else:
        check("E1: produced a multi-question split to test", False, f)

    # ---- F. Query type classification ----
    print("\n-- F1: informational query (definitional) --")
    res = run_scripted("What does Order 1 Rule 10 of the Code of Civil Procedure allow?", [])
    f = res[-1]
    if f.is_ready:
        check("F1: classified as informational",
              all(s.query_type == QueryType.INFORMATIONAL for s in f.sub_questions), f,
              detail=f"got {[s.query_type.value for s in f.sub_questions]}")
        check("F1: recommended_pipeline == short",
              all(s.recommended_pipeline == "short" for s in f.sub_questions), f)
        check("F1: provision_key populated",
              any(s.provision_key is not None for s in f.sub_questions), f)
    else:
        check("F1: expected ready", False, f)

    print("\n-- F2: test_application query (fact pattern vs legal test) --")
    res = run_scripted(
        "My landlord is trying to evict me because I have not paid rent for "
        "the last three months. Can he do that?", [])
    f = res[-1]
    if f.is_ready:
        check("F2: at least one sub-question classified as test_application",
              any(s.query_type == QueryType.TEST_APPLICATION for s in f.sub_questions), f,
              detail=f"got {[s.query_type.value for s in f.sub_questions]}")
        ta_sq = next((s for s in f.sub_questions
                      if s.query_type == QueryType.TEST_APPLICATION), None)
        check("F2: test_application recommended_pipeline == full",
              ta_sq is not None and ta_sq.recommended_pipeline == "full", f)
    else:
        check("F2: expected ready", False, f)

    print("\n-- F3: mixed query (compound with both types) --")
    res = run_scripted(
        "What is res judicata, and does it apply to my case where the same "
        "issue was already decided by the District Court?", [])
    f = res[-1]
    if f.is_ready and len(f.sub_questions) >= 2:
        types = {s.query_type for s in f.sub_questions}
        check("F3: has both informational and test_application sub-questions",
              QueryType.INFORMATIONAL in types and QueryType.TEST_APPLICATION in types, f,
              detail=f"got {[s.query_type.value for s in f.sub_questions]}")
    elif f.is_ready:
        # Acceptable: model might treat it as a single test_application
        check("F3: at least classified something",
              len(f.sub_questions) >= 1, f)
    else:
        check("F3: expected ready", False, f)

    print("\n-- F4: provision_key covers case-law doctrines (not just statutes) --")
    res = run_scripted("What is the doctrine of res judicata?", [])
    f = res[-1]
    if f.is_ready:
        check("F4: provision_key set for case-law doctrine",
              any(s.provision_key is not None for s in f.sub_questions), f,
              detail=f"provision_keys: {[s.provision_key for s in f.sub_questions]}")
    else:
        check("F4: expected ready", False, f)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    offline_tests()

    load_dotenv()
    if os.environ.get("GROQ_API_KEY"):
        try:
            live_tests()
        except Exception as e:  # noqa: BLE001
            print(f"\n[live suite error] {type(e).__name__}: {e}")
            FAIL += 1
    else:
        print("\n=== LIVE tests SKIPPED - set GROQ_API_KEY in .env to run them ===")

    print(f"\n-------- {PASS} passed, {FAIL} failed --------")
    sys.exit(1 if FAIL else 0)
