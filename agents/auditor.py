"""
auditor.py
──────────
The Auditor agent (CLAUDE.md §2, §2a, §6, §7). FOURTH stage of the pipeline,
between the Checklist Resolver and the Adjudicator.

It takes a checklist (grouped conditions, each flagged CRITICAL or optional, some
tagged into OR alternative-groups) plus the user's known facts, and decides for
EACH condition: satisfied / failed / unknown — checking facts against the
statute, never guessing ahead of evidence.

The loop lives here (§2a). If a condition the outcome depends on is unknown, the
Auditor formulates ONE specific question and STOPS, returning status="clarify". The
caller asks the user, appends {question, answer, condition} to `history`, and
re-invokes — the resume loop, which maps onto a LangGraph interrupt later. When no
outcome-changing unknown remains (or the user can't supply it), it returns
status="complete" with the verified surviving set for the Adjudicator.

CRITICAL vs optional is the backbone of the determination (the model only judges
each condition; this module owns the applies/fails/indeterminate math):
  • a CRITICAL condition that FAILS  → provision FAILS (and we stop asking)
  • every CRITICAL condition SATISFIED → provision APPLIES
  • a CRITICAL condition left UNKNOWN  → INDETERMINATE (user couldn't supply it)
  • an optional condition NEVER kills the provision — tracked, never fatal
  • alternative-group: satisfied if ANY member is; counts as CRITICAL if ANY is.

The Auditor is checklist-source-agnostic: the same mechanism audits a substantive
checklist or a jurisdiction checklist (§7) — just pass whichever checklist in.

Public entry point:
    run_auditor(checklist, known_facts, *, group_labels=None, provision_key="",
                history=None, llm=None, model=None) -> AuditResult
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from .llm_factory import build_rotating_structured_llm
from .query_agent import _is_dont_know  # reuse the don't-know detector (CLAUDE.md §2b)
from .schemas import (
    AuditAssessment,
    AuditedCondition,
    AuditResult,
    AuditStatus,
    ChecklistCondition,
    ConditionVerdict,
)

# Auditor is the highest-stakes step (§4). Default to Groq llama-3.3-70b-versatile:
# fastest inference (LPU), reliable structured output via function_calling (the same
# path the Query Agent uses), and — now that we rotate 14 Groq keys round-robin
# (llm_keys) — the free-tier daily cap that once pushed this onto Gemini (§3 risk 4)
# is no longer the bottleneck. Overridable via $AUDITOR_MODEL with no code change; a
# gemini-* value transparently routes to the 30-key Gemini pool instead.
_DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Loop control (mirrors the Query Agent's clarify-cap, CLAUDE.md §2b PART 1):
MAX_ASKS_PER_CONDITION = 2   # ask about one condition at most twice, then mark it unknown
MAX_TOTAL_ASKS = 6           # hard ceiling on audit questions per sub-question (safety net)


SYSTEM_PROMPT = """\
You are the Auditor for an Indian CIVIL-law (Code of Civil Procedure) legal
assistant. You verify a fact pattern against a statutory checklist. You do NOT
retrieve, you do NOT write the final answer, and you do NOT invent conditions.

You are given:
  • a numbered CHECKLIST of conditions extracted from one legal provision. Each
    condition is tagged [CRITICAL] (failing it means the provision cannot apply) or
    [optional] (relevant but not fatal). Some conditions share an (alt: <tag>) marker,
    meaning they are ALTERNATIVES — only ONE of that group needs to be satisfied.
  • the KNOWN FACTS the user has provided so far.

For EACH numbered condition, return a verdict:
  • satisfied — the known facts CLEARLY establish this condition is met.
  • failed    — the known facts CLEARLY establish this condition is NOT met.
  • unknown   — the facts are silent or insufficient to decide.

Hard rules:
  1. NEVER guess. If the facts do not address a condition, it is 'unknown' — not a
     hopeful 'satisfied' and not a pessimistic 'failed'. Guessing here breaks the
     whole system's citation guarantee.
  2. Judge ONLY against the known facts and the condition text. Do not import outside
     assumptions about what "probably" happened.
  3. Give a one-sentence rationale per verdict: cite the deciding fact, or name the
     missing fact for an unknown.
  4. If — and only if — one or more conditions are 'unknown' AND learning that fact
     could change whether the provision applies, propose the SINGLE most pivotal
     follow-up question (next_question) asking the user for ONE concrete fact, and set
     next_question_index to that condition's number. If everything decidable is
     decided, leave next_question null.
  5. Prefer asking about a [CRITICAL] unknown over an [optional] one — criticals
     decide the outcome.
"""


# ─────────────────────────────────────────────
# LLM construction — rotation-aware, shared factory (llm_factory / llm_keys)
# ─────────────────────────────────────────────

def build_audit_llm(model: Optional[str] = None) -> Any:
    """
    Build a rotation-aware chat model that returns an `AuditAssessment` directly.

    Model resolution: explicit `model` arg > $AUDITOR_MODEL > _DEFAULT_MODEL.
    Keys + provider are handled by the shared factory: a Groq model rides the 14-key
    GROQ_POOL, a `gemini-*` override rides the 30-key GEMINI_POOL. Each `.invoke()`
    draws the next key round-robin and sits a key out on a 429 (see llm_factory).
    """
    load_dotenv()
    model = model or os.environ.get("AUDITOR_MODEL") or _DEFAULT_MODEL
    return build_rotating_structured_llm(AuditAssessment, model)


# ─────────────────────────────────────────────
# Flatten the grouped checklist into one numbered list
# ─────────────────────────────────────────────

class _FlatItem:
    """One condition lifted out of its group, with a stable 1-based index."""

    __slots__ = ("index", "group_label", "condition")

    def __init__(self, index: int, group_label: str, condition: ChecklistCondition):
        self.index = index
        self.group_label = group_label
        self.condition = condition


def _flatten(
    checklist: List[List[ChecklistCondition]], group_labels: List[str]
) -> List[_FlatItem]:
    flat: List[_FlatItem] = []
    idx = 1
    for gi, group in enumerate(checklist):
        label = group_labels[gi] if gi < len(group_labels) else f"Group {gi + 1}"
        for cond in group:
            flat.append(_FlatItem(idx, label, cond))
            idx += 1
    return flat


# ─────────────────────────────────────────────
# Message assembly (conditions + known facts + resume history)
# ─────────────────────────────────────────────

def _render_conditions(flat: List[_FlatItem]) -> str:
    lines = []
    for it in flat:
        tag = "CRITICAL" if it.condition.critical else "optional"
        alt = f"  (alt: {it.condition.alternative_group})" if it.condition.alternative_group else ""
        lines.append(f"{it.index}. [{tag}] {it.condition.text}{alt}   <{it.group_label}>")
    return "\n".join(lines)


def _accumulated_facts(known_facts: List[str], history: List[dict]) -> List[str]:
    """Original facts plus every usable answer the user gave during the audit loop."""
    facts = list(known_facts)
    for turn in history:
        ans = (turn.get("answer") or "").strip()
        if ans and not _is_dont_know(ans):
            facts.append(ans)
    return facts


def _build_messages(
    provision_key: str,
    flat: List[_FlatItem],
    known_facts: List[str],
    history: List[dict],
    directive: Optional[str],
) -> list:
    facts = known_facts or ["(no specific facts provided yet)"]
    facts_block = "\n".join(f"  - {f}" for f in facts)
    human = (
        f"PROVISION: {provision_key or '(unnamed provision)'}\n\n"
        f"CHECKLIST (judge every numbered item):\n{_render_conditions(flat)}\n\n"
        f"KNOWN FACTS:\n{facts_block}"
    )
    messages: list = [("system", SYSTEM_PROMPT), ("human", human)]
    for turn in history:
        q = turn.get("question", "")
        a = turn.get("answer", "")
        messages.append(("ai", f"(clarifying question) {q}"))
        messages.append(("human", f"(user answer) {a}"))
    if directive:
        messages.append(("human", directive))
    return messages


# ─────────────────────────────────────────────
# Loop control — forced unknowns (don't-know / 2-ask cap), mirrors query_agent
# ─────────────────────────────────────────────

def _forced_unknown_conditions(history: List[dict]) -> set:
    """
    Condition texts we must STOP asking about and pin as UNKNOWN, because:
      • that condition has already been asked MAX_ASKS_PER_CONDITION times, or
      • the user's most recent answer about it was an explicit "I don't know".
    Relies on history turns carrying 'condition' (the caller records it, like the
    Query Agent records 'kind').
    """
    forced: set = set()
    counts: Dict[str, int] = {}
    for turn in history:
        c = turn.get("condition")
        if c:
            counts[c] = counts.get(c, 0) + 1
    for c, n in counts.items():
        if n >= MAX_ASKS_PER_CONDITION:
            forced.add(c)
    if history and _is_dont_know(history[-1].get("answer", "")):
        c = history[-1].get("condition")
        if c:
            forced.add(c)
    return forced


def _proceed_directive(forced_texts: set) -> Optional[str]:
    if not forced_texts:
        return None
    listed = "; ".join(f'"{t}"' for t in forced_texts)
    return (
        f"NOTE: the user could not provide facts for these condition(s): {listed}. "
        "Do NOT ask about them again — mark each 'unknown' and move on. Still judge "
        "every other condition and only propose next_question for a DIFFERENT unknown."
    )


# ─────────────────────────────────────────────
# Verdict assembly + CRITICAL/optional determination math (code-owned)
# ─────────────────────────────────────────────

def _verdict_map(
    assessment: AuditAssessment, n: int, forced_indexes: set
) -> Dict[int, ConditionVerdict]:
    """LLM verdicts keyed by index, defensively filled, with forced indexes pinned UNKNOWN."""
    m: Dict[int, ConditionVerdict] = {}
    for v in assessment.verdicts:
        if 1 <= v.index <= n and v.index not in m:
            m[v.index] = v
    for i in range(1, n + 1):
        if i not in m:
            m[i] = ConditionVerdict(
                index=i, status=AuditStatus.UNKNOWN,
                rationale="No verdict returned by the model; treated as unknown.",
            )
    for i in forced_indexes:
        if i in m:
            m[i] = ConditionVerdict(
                index=i, status=AuditStatus.UNKNOWN,
                rationale="User could not provide this fact; recorded as unknown.",
            )
    return m


class _Unit:
    """
    A determination unit. Either one standalone condition, or one OR alternative-group.
    `critical` is True if ANY member is critical. `status` is the unit's resolved status:
      • standalone: the condition's own status
      • alt-group: satisfied if ANY member satisfied; failed if ALL failed; else open
    `open_unknown_indexes` are the still-askable condition indexes inside the unit.
    """

    __slots__ = ("key", "critical", "status", "open_unknown_indexes")

    def __init__(self, key, critical, status, open_unknown_indexes):
        self.key = key
        self.critical = critical
        self.status = status  # "satisfied" | "failed" | "open"
        self.open_unknown_indexes = open_unknown_indexes


def _classify_units(
    flat: List[_FlatItem], status_by_index: Dict[int, AuditStatus]
) -> List[_Unit]:
    """Collapse conditions into determination units, respecting alternative-groups."""
    units: List[_Unit] = []
    alt_members: Dict[str, List[_FlatItem]] = {}

    for it in flat:
        tag = it.condition.alternative_group
        if tag:
            alt_members.setdefault(tag, []).append(it)
            continue
        # Standalone condition → its own unit.
        st = status_by_index[it.index]
        unit_status = {
            AuditStatus.SATISFIED: "satisfied",
            AuditStatus.FAILED: "failed",
            AuditStatus.UNKNOWN: "open",
        }[st]
        open_idx = [it.index] if st == AuditStatus.UNKNOWN else []
        units.append(_Unit(f"cond:{it.index}", it.condition.critical, unit_status, open_idx))

    for tag, members in alt_members.items():
        statuses = [status_by_index[m.index] for m in members]
        if any(s == AuditStatus.SATISFIED for s in statuses):
            unit_status = "satisfied"
        elif all(s == AuditStatus.FAILED for s in statuses):
            unit_status = "failed"
        else:
            unit_status = "open"
        critical = any(m.condition.critical for m in members)
        # Only the not-yet-failed unknowns are worth asking about (any one satisfies the group).
        open_idx = [m.index for m in members if status_by_index[m.index] == AuditStatus.UNKNOWN]
        units.append(_Unit(f"alt:{tag}", critical, unit_status, open_idx if unit_status == "open" else []))

    return units


def _determination(units: List[_Unit]) -> str:
    """
    Outcome from the CRITICAL units only (optional units never decide it):
      fails         — any critical unit failed
      applies       — every critical unit satisfied (vacuously true if no criticals)
      indeterminate — a critical unit is still open (unknown, unresolved)
    """
    critical_units = [u for u in units if u.critical]
    if any(u.status == "failed" for u in critical_units):
        return "fails"
    if all(u.status == "satisfied" for u in critical_units):
        return "applies"
    return "indeterminate"


def _ordered_material_indexes(units: List[_Unit]) -> List[int]:
    """
    Condition indexes still worth asking the user about — CRITICAL units first, then
    optional. Empty once the outcome is fixed (handled by the caller for the
    fail short-circuit). Skips alt-groups/standalones already resolved.
    """
    critical_open: List[int] = []
    optional_open: List[int] = []
    for u in units:
        if u.status != "open":
            continue
        (critical_open if u.critical else optional_open).extend(u.open_unknown_indexes)
    # Preserve checklist order within each tier.
    return sorted(dict.fromkeys(critical_open)) + sorted(dict.fromkeys(optional_open))


# ─────────────────────────────────────────────
# Result assembly
# ─────────────────────────────────────────────

def _audited(flat: List[_FlatItem], status_by_index: Dict[int, AuditStatus],
             rationale_by_index: Dict[int, str]) -> List[AuditedCondition]:
    out = []
    for it in flat:
        out.append(AuditedCondition(
            group_label=it.group_label,
            text=it.condition.text,
            critical=it.condition.critical,
            alternative_group=it.condition.alternative_group,
            status=status_by_index[it.index],
            rationale=rationale_by_index.get(it.index, ""),
        ))
    return out


def _bucket(audited: List[AuditedCondition], status: AuditStatus) -> List[AuditedCondition]:
    return [a for a in audited if a.status == status]


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

def run_auditor(
    checklist: List[List[ChecklistCondition]],
    known_facts: List[str],
    *,
    group_labels: Optional[List[str]] = None,
    provision_key: str = "",
    history: Optional[List[dict]] = None,
    llm: Any = None,
    model: Optional[str] = None,
) -> AuditResult:
    """
    Audit one provision's checklist against the user's known facts (one loop turn).

    Args:
        checklist:    grouped conditions from the Checklist Resolver
                      (ChecklistResult.checklist).
        known_facts:  the user's stated facts (e.g. SubQuestion.known_facts +
                      shared_context.known_facts).
        group_labels: labels per group (ChecklistResult.group_labels).
        provision_key: the provision name, for display/grounding.
        history:      prior audit clarifications [{"question","answer","condition"}, ...].
                      On a clarify result, append the asked question + the user's answer
                      + the targeted condition text, then call again (the resume loop).
        llm:          a structured LLM (.invoke(messages) -> AuditAssessment). If None,
                      a rotation-aware Groq (or Gemini, on a gemini-* override) client
                      is built via the shared factory. Tests inject a fake.
        model:        explicit model id; else $AUDITOR_MODEL then _DEFAULT_MODEL.

    Returns:
        AuditResult with status "complete" (determination + surviving_set filled) or
        "clarify" (pending_question filled).
    """
    history = history or []
    group_labels = group_labels or []
    known_now = _accumulated_facts(known_facts, history)

    flat = _flatten(checklist, group_labels)
    n = len(flat)

    # Nothing to audit → nothing to verify (e.g. informational short-circuit upstream).
    if n == 0:
        return AuditResult(
            status="complete",
            provision_key=provision_key,
            determination="no_checklist",
            known_facts=known_now,
            asked=[t.get("question", "") for t in history],
        )

    # Which conditions we must stop asking about (cap / don't-know) → pin them unknown.
    forced_texts = _forced_unknown_conditions(history)
    forced_indexes = {it.index for it in flat if it.condition.text in forced_texts}
    directive = _proceed_directive(forced_texts)

    structured_llm = llm if llm is not None else build_audit_llm(model)
    assessment: AuditAssessment = structured_llm.invoke(
        _build_messages(provision_key, flat, known_now, history, directive)
    )

    verdicts = _verdict_map(assessment, n, forced_indexes)
    status_by_index = {i: verdicts[i].status for i in verdicts}
    rationale_by_index = {i: verdicts[i].rationale for i in verdicts}

    units = _classify_units(flat, status_by_index)
    determination = _determination(units)

    audited = _audited(flat, status_by_index, rationale_by_index)
    satisfied = _bucket(audited, AuditStatus.SATISFIED)
    failed = _bucket(audited, AuditStatus.FAILED)
    unknown = _bucket(audited, AuditStatus.UNKNOWN)
    asked = [t.get("question", "") for t in history]

    # A failed CRITICAL condition means the provision is already barred — stop asking
    # (CLAUDE.md: never interrogate the user once the outcome is fixed).
    short_circuit_fail = determination == "fails"

    # Material unknowns still worth asking about — but never re-ask a condition the
    # user already couldn't answer (forced unknown via don't-know / 2-ask cap). Those
    # stay UNKNOWN and feed the determination (a forced-unknown critical -> indeterminate).
    material = [] if short_circuit_fail else [
        i for i in _ordered_material_indexes(units) if i not in forced_indexes
    ]
    under_cap = len(history) < MAX_TOTAL_ASKS

    if material and under_cap:
        # Prefer the model's proposed question when it targets a genuine material unknown.
        target = None
        if (assessment.next_question and assessment.next_question_index in material):
            target = assessment.next_question_index
        if target is None:
            target = material[0]
        cond_text = next(it.condition.text for it in flat if it.index == target)
        if assessment.next_question and target == assessment.next_question_index:
            question = assessment.next_question
        else:
            question = (
                f'To verify this requirement I need one fact: "{cond_text}". '
                "Is this the case in your situation, and how?"
            )
        return AuditResult(
            status="clarify",
            provision_key=provision_key,
            determination=None,
            satisfied=satisfied, failed=failed, unknown=unknown,
            pending_question=question,
            pending_condition=cond_text,
            known_facts=known_now,
            asked=asked,
        )

    # Complete: outcome is fixed, or we've exhausted what the user can tell us.
    return AuditResult(
        status="complete",
        provision_key=provision_key,
        determination=determination,
        satisfied=satisfied, failed=failed, unknown=unknown,
        surviving_set=satisfied,
        known_facts=known_now,
        asked=asked,
    )


# ─────────────────────────────────────────────
# Manual CLI: uv run python -m agents.auditor
# Resolves a real checklist for a provision, then audits a sample fact set,
# running the clarify/resume loop interactively in the terminal.
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    from .checklist_resolver import resolve_checklist

    provision = sys.argv[1] if len(sys.argv) > 1 else "Section 80 CPC"
    print(f"Resolving checklist for: {provision!r}")
    cr = resolve_checklist(provision)
    print(f"  checklist source: {cr.source}, "
          f"{sum(len(g) for g in cr.checklist)} conditions in {len(cr.checklist)} group(s)\n")

    facts = [
        "The plaintiff wants to sue a government officer for wrongfully seizing his "
        "goods in the officer's official capacity."
    ]
    print(f"Starting facts: {facts}\n" + "=" * 60)

    history: list[dict] = []
    for _ in range(MAX_TOTAL_ASKS + 1):
        result = run_auditor(
            cr.checklist, facts,
            group_labels=cr.group_labels, provision_key=provision, history=history,
        )
        print(json.dumps(result.model_dump(), indent=2, default=str))
        if result.is_complete:
            print("=" * 60)
            print(f"DETERMINATION: {result.determination}  "
                  f"({len(result.surviving_set)} verified condition(s) survive)")
            break
        print("-" * 60)
        print(f"[Auditor needs a fact for]: {result.pending_condition}")
        print(f"  Q: {result.pending_question}")
        answer = input("  Your answer: ").strip()
        history.append({
            "question": result.pending_question,
            "answer": answer,
            "condition": result.pending_condition,
        })
