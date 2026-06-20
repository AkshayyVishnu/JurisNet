"""
test_auditor.py — scripted regression suite for the Auditor.

Two layers (same shape as test_query_agent.py):

  • OFFLINE (no API key): a fake LLM returns canned verdicts so the deterministic,
    code-owned logic is fully exercised — CRITICAL vs optional determination,
    alternative-group OR math, the clarify gate, the don't-know / 2-ask cap loop
    control, and defensive verdict filling.

  • LIVE (needs GOOGLE_API_KEY or GROQ_API_KEY): a real checklist for Section 80 CPC
    is resolved, then audited with the real LLM. `run_audit_scripted` drives the
    clarify->resume->complete loop feeding scripted answers, so the FULL human-in-the-loop
    flow runs end-to-end (question -> answer -> re-run -> determination) without live typing.

Run:
    uv run python -m tests.test_auditor
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from agents.auditor import (
    _classify_units,
    _determination,
    _flatten,
    _forced_unknown_conditions,
    _ordered_material_indexes,
    build_audit_llm,
    run_auditor,
)
from agents.llm_factory import RotatingStructuredLLM
from agents.schemas import (
    AuditAssessment,
    AuditStatus,
    ChecklistCondition,
    ConditionVerdict,
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
# Fake LLM (offline): returns a fixed AuditAssessment built from index→status.
# ─────────────────────────────────────────────

class FakeAuditLLM:
    def __init__(self, status_by_index: dict[int, AuditStatus],
                 next_question: str | None = None, next_question_index: int | None = None):
        self._verdicts = [
            ConditionVerdict(index=i, status=s, rationale=f"verdict for {i}")
            for i, s in sorted(status_by_index.items())
        ]
        self._nq = next_question
        self._nqi = next_question_index
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return AuditAssessment(
            verdicts=list(self._verdicts),
            next_question=self._nq,
            next_question_index=self._nqi,
        )


# Reusable checklists -------------------------------------------------------

def _cond(text, critical=False, alt=None):
    return ChecklistCondition(text=text, critical=critical, alternative_group=alt)


# Section-80-like: a critical notice requirement + a critical waiting period + an
# optional curing condition.
NOTICE_CHECKLIST = [
    [
        _cond("A written notice was delivered to the appropriate government officer.", critical=True),
        _cond("Two months elapsed after the notice before the suit was instituted.", critical=True),
    ],
    [
        _cond("The plaint states that notice was delivered.", critical=False),
    ],
]
NOTICE_LABELS = ["Sub-section (1) requirements", "Sub-section (2) requirements"]


# ─────────────────────────────────────────────
# OFFLINE tests
# ─────────────────────────────────────────────

def offline_tests() -> None:
    print("\n=== OFFLINE (no API key) ===\n")

    # ---- determination math: CRITICAL drives the outcome ----
    flat = _flatten(NOTICE_CHECKLIST, NOTICE_LABELS)

    def determine(status_by_index):
        units = _classify_units(flat, status_by_index)
        return _determination(units)

    all_sat = {1: AuditStatus.SATISFIED, 2: AuditStatus.SATISFIED, 3: AuditStatus.SATISFIED}
    check("determination: all critical satisfied -> applies", determine(all_sat) == "applies")

    crit_fail = {1: AuditStatus.FAILED, 2: AuditStatus.SATISFIED, 3: AuditStatus.SATISFIED}
    check("determination: a critical failed -> fails", determine(crit_fail) == "fails")

    crit_unknown = {1: AuditStatus.UNKNOWN, 2: AuditStatus.SATISFIED, 3: AuditStatus.SATISFIED}
    check("determination: critical unknown -> indeterminate", determine(crit_unknown) == "indeterminate")

    # optional failing must NOT fail the provision
    opt_fail = {1: AuditStatus.SATISFIED, 2: AuditStatus.SATISFIED, 3: AuditStatus.FAILED}
    check("determination: optional failed -> still applies", determine(opt_fail) == "applies")

    # ---- alternative-group OR math ----
    alt_checklist = [[
        _cond("Price was tendered to the seller.", critical=True, alt="stoppage"),
        _cond("Proof of earlier payment was produced.", critical=True, alt="stoppage"),
    ]]
    alt_flat = _flatten(alt_checklist, ["Alternatives"])

    one_sat = {1: AuditStatus.SATISFIED, 2: AuditStatus.UNKNOWN}
    check("alt-group: ANY satisfied -> unit satisfied -> applies",
          _determination(_classify_units(alt_flat, one_sat)) == "applies")

    all_failed = {1: AuditStatus.FAILED, 2: AuditStatus.FAILED}
    check("alt-group: ALL failed -> unit failed -> fails",
          _determination(_classify_units(alt_flat, all_failed)) == "fails")

    one_open = {1: AuditStatus.FAILED, 2: AuditStatus.UNKNOWN}
    check("alt-group: one failed one unknown -> open -> indeterminate",
          _determination(_classify_units(alt_flat, one_open)) == "indeterminate")
    # ...and the still-open alternative is the only one worth asking about (not the failed one)
    units = _classify_units(alt_flat, one_open)
    check("alt-group: only the unknown alternative is material",
          _ordered_material_indexes(units) == [2])

    # ---- material ordering: CRITICAL unknowns asked before optional ----
    mixed = {1: AuditStatus.UNKNOWN, 2: AuditStatus.SATISFIED, 3: AuditStatus.UNKNOWN}
    units = _classify_units(flat, mixed)
    check("material order: critical (1) before optional (3)",
          _ordered_material_indexes(units) == [1, 3])

    # ---- forced-unknown loop control (cap + don't-know), mirrors query_agent ----
    cap_hist = [{"condition": "X", "question": "q", "answer": "hmm"},
                {"condition": "X", "question": "q", "answer": "still unsure"}]
    check("cap: condition asked twice -> forced unknown",
          _forced_unknown_conditions(cap_hist) == {"X"})
    dk_hist = [{"condition": "X", "question": "q", "answer": "I don't know"}]
    check("dont-know: condition forced unknown", _forced_unknown_conditions(dk_hist) == {"X"})
    ok_hist = [{"condition": "X", "question": "q", "answer": "yes, notice was delivered"}]
    check("answered: not forced", _forced_unknown_conditions(ok_hist) == set())

    # ---- run_auditor: clarify when a CRITICAL condition is unknown ----
    fake = FakeAuditLLM(
        {1: AuditStatus.UNKNOWN, 2: AuditStatus.SATISFIED, 3: AuditStatus.SATISFIED},
        next_question="Did you deliver a written notice to the government officer?",
        next_question_index=1,
    )
    r = run_auditor(NOTICE_CHECKLIST, ["Plaintiff sued a government officer."],
                    group_labels=NOTICE_LABELS, provision_key="Section 80 CPC", llm=fake)
    check("clarify: critical unknown -> status clarify", r.status == "clarify", r)
    check("clarify: pending_question is the model's question",
          r.pending_question == "Did you deliver a written notice to the government officer?", r)
    check("clarify: pending_condition targets condition 1",
          r.pending_condition == NOTICE_CHECKLIST[0][0].text, r)
    check("clarify: snapshot buckets exposed (1 satisfied so far)",
          len(r.satisfied) == 2, r, detail=f"got {len(r.satisfied)}")

    # ---- run_auditor: complete 'fails' when a CRITICAL condition failed (no question) ----
    fake_fail = FakeAuditLLM(
        {1: AuditStatus.FAILED, 2: AuditStatus.UNKNOWN, 3: AuditStatus.UNKNOWN},
        next_question="ignored because provision already fails",
        next_question_index=2,
    )
    r = run_auditor(NOTICE_CHECKLIST, ["No notice was ever sent."],
                    group_labels=NOTICE_LABELS, provision_key="Section 80 CPC", llm=fake_fail)
    check("fail short-circuit: status complete (no question despite unknowns)",
          r.status == "complete", r)
    check("fail short-circuit: determination == fails", r.determination == "fails", r)
    check("fail short-circuit: did NOT ask a question", r.pending_question is None, r)

    # ---- run_auditor: complete 'applies' when all critical satisfied ----
    fake_ok = FakeAuditLLM({1: AuditStatus.SATISFIED, 2: AuditStatus.SATISFIED, 3: AuditStatus.SATISFIED})
    r = run_auditor(NOTICE_CHECKLIST, ["Notice delivered; two months passed."],
                    group_labels=NOTICE_LABELS, provision_key="Section 80 CPC", llm=fake_ok)
    check("applies: status complete", r.status == "complete", r)
    check("applies: determination == applies", r.determination == "applies", r)
    check("applies: surviving_set == all 3 satisfied", len(r.surviving_set) == 3, r)

    # ---- resume loop: a don't-know on the critical condition -> forced unknown -> indeterminate ----
    fake_unknown = FakeAuditLLM(
        {1: AuditStatus.UNKNOWN, 2: AuditStatus.SATISFIED, 3: AuditStatus.SATISFIED},
        next_question="Did you deliver the notice?", next_question_index=1,
    )
    hist = [{"question": "Did you deliver the notice?",
             "answer": "I don't know",
             "condition": NOTICE_CHECKLIST[0][0].text}]
    r = run_auditor(NOTICE_CHECKLIST, ["Plaintiff sued a government officer."],
                    group_labels=NOTICE_LABELS, provision_key="Section 80 CPC",
                    history=hist, llm=fake_unknown)
    check("resume: don't-know pins critical unknown -> complete", r.status == "complete", r)
    check("resume: determination == indeterminate", r.determination == "indeterminate", r)
    check("resume: the pinned condition lands in the unknown bucket",
          any(c.text == NOTICE_CHECKLIST[0][0].text for c in r.unknown), r)

    # ---- empty checklist short-circuits ----
    r = run_auditor([], ["anything"], group_labels=[], provision_key="res judicata",
                    llm=FakeAuditLLM({}))
    check("empty checklist: complete + no_checklist", r.status == "complete"
          and r.determination == "no_checklist", r)
    check("empty checklist: LLM never called", FakeAuditLLM({}).calls == 0)

    # ---- defensive: missing verdict from model -> treated as unknown ----
    partial = FakeAuditLLM({1: AuditStatus.SATISFIED})  # omits 2 and 3
    r = run_auditor(NOTICE_CHECKLIST, ["Notice delivered."],
                    group_labels=NOTICE_LABELS, provision_key="Section 80 CPC", llm=partial)
    # condition 2 is critical and now unknown -> should clarify, not silently apply
    check("defensive: missing verdict -> unknown -> clarify on critical",
          r.status == "clarify", r)

    # ---- build_audit_llm: rides the rotating key pools (Groq default, Gemini on override) ----
    default_llm = build_audit_llm()
    check("build_audit_llm: returns a rotating LLM (not a single-key client)",
          isinstance(default_llm, RotatingStructuredLLM))
    check("build_audit_llm: default model rides the 14-key Groq pool",
          default_llm.pool is GROQ_POOL)
    check("build_audit_llm: a gemini-* override routes to the Gemini pool",
          build_audit_llm("gemini-2.5-flash").pool is GEMINI_POOL)


# ─────────────────────────────────────────────
# LIVE scripted driver + case (real LLM, full HITL loop)
# ─────────────────────────────────────────────

def run_audit_scripted(checklist, known_facts, answers, *, group_labels, provision_key,
                       verbose=True):
    """
    Drive the audit clarify loop with the REAL LLM, feeding `answers` to each ❓ in
    order. Returns the list of per-turn AuditResults. Prints the full flow when verbose.
    """
    history: list[dict] = []
    results: list = []
    for i in range(len(answers) + 1):
        r = run_auditor(checklist, known_facts, group_labels=group_labels,
                        provision_key=provision_key, history=history)
        results.append(r)
        if verbose:
            print(f"\n  --- turn {i + 1}: status={r.status} "
                  f"determination={r.determination} ---")
            print(f"      ✅ satisfied={[c.text[:48] for c in r.satisfied]}")
            print(f"      ❌ failed={[c.text[:48] for c in r.failed]}")
            print(f"      ❓ unknown={[c.text[:48] for c in r.unknown]}")
            if r.status == "clarify":
                print(f"      ❓ Q (for: {r.pending_condition[:48]}...):\n          {r.pending_question}")
        if r.is_complete or i >= len(answers):
            break
        ans = answers[i]
        if verbose:
            print(f"      👤 scripted answer: {ans!r}")
        history.append({"question": r.pending_question, "answer": ans,
                        "condition": r.pending_condition})
    return results


def live_tests() -> None:
    print("\n=== LIVE (real LLM, scripted HITL) ===\n")
    from agents.checklist_resolver import resolve_checklist

    provision = "Section 80 CPC"
    cr = resolve_checklist(provision)
    print(f"-- checklist for {provision}: source={cr.source}, "
          f"{sum(len(g) for g in cr.checklist)} conditions --")
    if not cr.checklist:
        check("LIVE precondition: Section 80 CPC checklist resolved", False,
              detail=f"source={cr.source}")
        return

    base_facts = [
        "The plaintiff wants to sue a government officer for wrongfully seizing his "
        "goods in the officer's official capacity."
    ]

    # ---- L1: the 'No notice' path -> a CRITICAL condition fails -> provision FAILS ----
    print("\n-- L1: user reveals NO notice was served (critical fail) --")
    res = run_audit_scripted(
        cr.checklist, base_facts,
        answers=["No, I never sent any written notice to the government before filing."],
        group_labels=cr.group_labels, provision_key=provision,
    )
    f = res[-1]
    check("L1: first turn asks a ❓ (notice unknown from base facts)",
          res[0].status == "clarify", res[0])
    check("L1: reaches a complete determination", f.is_complete, f)
    check("L1: determination is fails or indeterminate (not a false 'applies')",
          f.determination in ("fails", "indeterminate"), f,
          detail=f"got {f.determination}")

    # ---- L2: the 'Yes, fully complied' path -> criticals satisfied -> APPLIES ----
    print("\n-- L2: user confirms notice served + two months elapsed (applies) --")
    res = run_audit_scripted(
        cr.checklist, base_facts,
        answers=[
            "Yes, I delivered a written notice to the Secretary to the Government, and "
            "I waited more than two months after that before filing the suit.",
            "Yes, the plaint explicitly states that the notice was delivered.",
            "Yes, more than two months elapsed between the notice and filing.",
        ],
        group_labels=cr.group_labels, provision_key=provision,
    )
    f = res[-1]
    check("L2: reaches complete", f.is_complete, f)
    check("L2: at least one condition verified as satisfied", len(f.satisfied) >= 1, f)
    check("L2: not wrongly 'fails' after full compliance stated",
          f.determination in ("applies", "indeterminate"), f,
          detail=f"got {f.determination}")

    # ---- L3: never interrogates past the cap ----
    print("\n-- L3: persistent 'I don't know' must terminate (cap) --")
    res = run_audit_scripted(
        cr.checklist, base_facts,
        answers=["I don't know"] * 6,
        group_labels=cr.group_labels, provision_key=provision, verbose=False,
    )
    f = res[-1]
    check("L3: terminates without exceeding the ask ceiling", f.is_complete, f,
          detail=f"turns={len(res)}")
    check("L3: ends indeterminate when user can't supply critical facts",
          f.determination in ("indeterminate", "fails"), f, detail=f"got {f.determination}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Windows consoles default to cp1252, which can't encode the ✅/❌/❓ flow markers.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — best-effort; falls back to default stream
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
