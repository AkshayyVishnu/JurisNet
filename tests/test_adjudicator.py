"""
test_adjudicator.py — scripted regression suite for the Adjudicator.

Two layers (same shape as test_auditor.py and test_query_agent.py):

  • OFFLINE (no API key): a fake LLM returns canned adjudication output so the
    deterministic, code-owned logic and plumbing are fully exercised.

  • LIVE (needs GROQ_API_KEY or GOOGLE_API_KEY): a real query is adjudicated with the
    real LLM, ensuring end-to-end integration and structured validation are correct.

Run:
    uv run python -m tests.test_adjudicator
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from agents.adjudicator import (
    build_adjudicator_llm,
    run_adjudicator,
)
from agents.llm_factory import RotatingStructuredLLM
from agents.schemas import (
    AdjudicationResult,
    AuditResult,
    AuditedCondition,
    AuditStatus,
    Complexity,
    QueryType,
    RelationshipType,
    SharedContext,
    SubAnswer,
    SubQuestion,
)
from llm_keys import GEMINI_POOL, GROQ_POOL

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

class FakeAdjudicatorLLM:
    def __init__(self, result: AdjudicationResult):
        self._result = result
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return self._result


# ─────────────────────────────────────────────
# OFFLINE tests
# ─────────────────────────────────────────────

def offline_tests() -> None:
    print("\n=== OFFLINE (no API key) ===\n")

    # ---- 1. Empty sub-questions short-circuits ----
    fake_empty = FakeAdjudicatorLLM(AdjudicationResult(
        ultimate_verdict="canned",
        sub_answers=[],
        synthesis_and_conflicts="",
    ))
    r = run_adjudicator([], {}, {}, llm=fake_empty)
    check("empty sub_questions: complete + no LLM call",
          "No legal sub-questions" in r.ultimate_verdict and fake_empty.calls == 0, r)

    # ---- 2. Adjudicator plumbing maps sub-questions + LLM returns response ----
    shared = SharedContext(original_query="moratorium test")
    sq1 = SubQuestion(
        id=1,
        text="Can we sue during the stay?",
        query_type=QueryType.TEST_APPLICATION,
        provision_key="Section 14 IBC",
        complexity=Complexity.SIMPLE,
        relationship_type=RelationshipType.INDEPENDENT,
        shared_context=shared,
    )
    
    mock_audit = AuditResult(
        status="complete",
        provision_key="Section 14 IBC",
        determination="applies",
        satisfied=[
            AuditedCondition(
                text="moratorium active",
                critical=True,
                status=AuditStatus.SATISFIED,
                rationale="NCLT ordered it",
            )
        ],
    )
    
    mock_evidence = [
        {"title": "Moratorium Case", "text": "moratorium stays all suits", "score": 0.99}
    ]

    canned_res = AdjudicationResult(
        ultimate_verdict="The suit is stayed.",
        sub_answers=[
            SubAnswer(
                sub_question_id=1,
                conclusion="Stay applies.",
                reasoning="Section 14 IBC moratorium was declared.",
                citations=["Section 14 IBC", "Moratorium Case"],
            )
        ],
        synthesis_and_conflicts="moratorium stays proceedings.",
    )

    fake_llm = FakeAdjudicatorLLM(canned_res)
    r = run_adjudicator([sq1], {1: mock_audit}, {1: mock_evidence}, llm=fake_llm)
    check("plumbing: status matches canned outcome", r.ultimate_verdict == "The suit is stayed.", r)
    check("plumbing: sub_answers processed correctly", len(r.sub_answers) == 1 and r.sub_answers[0].conclusion == "Stay applies.", r)
    check("plumbing: LLM was invoked exactly once", fake_llm.calls == 1)

    # ---- 3. build_adjudicator_llm key rotation config ----
    default_llm = build_adjudicator_llm()
    check("build_adjudicator_llm: returns RotatingStructuredLLM", isinstance(default_llm, RotatingStructuredLLM))
    check("build_adjudicator_llm: default model rides Groq key pool", default_llm.pool is GROQ_POOL)
    check("build_adjudicator_llm: gemini-* override routes to Gemini pool", build_adjudicator_llm("gemini-2.5-flash").pool is GEMINI_POOL)


# ─────────────────────────────────────────────
# LIVE tests
# ─────────────────────────────────────────────

def live_tests() -> None:
    print("\n=== LIVE (real LLM) ===\n")
    
    shared = SharedContext(original_query="moratorium under IBC")
    sq1 = SubQuestion(
        id=1,
        text="Can we proceed with the summary suit under Order 37 CPC if there is a moratorium under Section 14 of the IBC?",
        query_type=QueryType.TEST_APPLICATION,
        provision_key="Section 14 IBC",
        complexity=Complexity.MODERATE,
        relationship_type=RelationshipType.INDEPENDENT,
        known_facts=["Moratorium declared by NCLT on 27.02.2018", "Plaintiff filed summary suit for recovery of money"],
        shared_context=shared,
    )
    
    mock_audit = AuditResult(
        status="complete",
        provision_key="Section 14 Insolvency and Bankruptcy Code, 2016",
        determination="applies",
        satisfied=[
            AuditedCondition(
                group_label="Moratorium",
                text="moratorium declared prohibiting institution or continuation of suits",
                critical=True,
                status=AuditStatus.SATISFIED,
                rationale="The NCLT declared moratorium on 27.02.2018.",
            )
        ],
        surviving_set=[
            AuditedCondition(
                group_label="Moratorium",
                text="moratorium declared prohibiting institution or continuation of suits",
                critical=True,
                status=AuditStatus.SATISFIED,
                rationale="The NCLT declared moratorium on 27.02.2018.",
            )
        ],
        known_facts=["Moratorium declared by NCLT on 27.02.2018", "Plaintiff filed summary suit for recovery of money"],
    )

    mock_evidence = [
        {
            "title": "M/S Golden Jubilee Hotels Limited vs Eih Ltd on 27 September, 2018",
            "score": 0.98,
            "text": (
                "Upon the moratorium order being passed under Section 14 of the IBC, the pending suit "
                "proceedings necessarily had to come to a complete halt. Continuation of the suit proceedings "
                "would encompass every step therein, which would include not only adjudicatory steps but also procedural ones. "
                "The trial Court was therefore in error in concluding that continuing with the suit proceedings for passing "
                "procedural orders would not be violative of the moratorium order."
            ),
        }
    ]

    print("Invoking real rotating structured LLM (llama-3.3-70b-versatile)...")
    r = run_adjudicator([sq1], {1: mock_audit}, {1: mock_evidence})
    
    check("LIVE: ultimate verdict generated", len(r.ultimate_verdict.strip()) > 0, r)
    check("LIVE: has at least one sub_answer", len(r.sub_answers) == 1, r)
    if r.sub_answers:
        check("LIVE: sub_answer citations non-empty", len(r.sub_answers[0].citations) >= 1, r)
    check("LIVE: synthesis_and_conflicts generated", len(r.synthesis_and_conflicts.strip()) > 0, r)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # UTF-8 for console output markers
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    offline_tests()

    load_dotenv()
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GROQ_API_KEY"):
        try:
            live_tests()
        except Exception as e:  # noqa: BLE001
            print(f"\n[live suite error] {type(e).__name__}: {e}")
            FAIL += 1
    else:
        print("\n=== LIVE tests SKIPPED - set GOOGLE_API_KEY (or GROQ_API_KEY) in .env ===")

    print(f"\n-------- {PASS} passed, {FAIL} failed --------")
    sys.exit(1 if FAIL else 0)
