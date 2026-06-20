"""
schemas.py
──────────
Pydantic shapes for the Query Agent (CLAUDE.md §2b, §6).

Two layers:

  1. LLM-facing drafts  — bound to `.with_structured_output(...)`. These are what
     the model fills in a single call. They deliberately OMIT the shared context
     object so the model never retypes the original query N times (token waste +
     drift risk). Field descriptions here ARE the model's instructions.

  2. Final public shapes — what `run_query_agent()` returns. Code assembles these
     from the LLM draft (e.g. assigns ids, attaches SharedContext to every
     sub-question).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class Complexity(str, Enum):
    """
    Per-sub-question difficulty. Drives THREE downstream decisions in the
    Researcher (CLAUDE.md §2, §5):
      • top_k sizing for vector search (Pull A)
      • local (one-hop) vs global (community-summary) knowledge-graph search (Pull B)
      • whether the community-lookup fallback fires at all
    "simple" is the literal the Researcher checks against, so keep this value.
    """
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class QueryType(str, Enum):
    """
    Per-sub-question type classification. Drives downstream pipeline routing:
      • test_application — the sub-question asks whether a fact pattern satisfies
        a legal test/standard. Full pipeline: Researcher → Checklist Resolver →
        Auditor → Adjudicator.
      • informational — the sub-question is explanatory, definitional, or
        procedural. Short pipeline: Researcher → Adjudicator directly, skipping
        Checklist Resolver and Auditor entirely.
    The distinction matters because informational queries have no checklist to
    resolve and no facts to audit — forcing them through those stages wastes
    tokens and risks hallucinated checklists on definitional content.
    """
    TEST_APPLICATION = "test_application"
    INFORMATIONAL = "informational"


class RelationshipType(str, Enum):
    """
    How a sub-question relates to its siblings. Drives the Adjudicator (CLAUDE.md §2b):
      • independent → answer separately, present as unrelated findings
      • dependent   → one sub-answer feeds another; order matters (see depends_on)
      • causal      → linked by a cause/effect chain in the original query; synthesize together
    """
    INDEPENDENT = "independent"
    DEPENDENT = "dependent"
    CAUSAL = "causal"


class ClarificationKind(str, Enum):
    """Which gate in the §2b decision flow stopped to ask the user."""
    MISSING_REQUIRED = "missing_required"   # no identifiable legal issue to retrieve on
    AMBIGUOUS = "ambiguous"                 # one input, multiple valid interpretations
    JURISDICTION = "jurisdiction"           # incomplete in a way that changes domain/jurisdiction


# ─────────────────────────────────────────────
# LLM-facing drafts (bound to with_structured_output)
# ─────────────────────────────────────────────

class SubQuestionDraft(BaseModel):
    """One self-contained sub-question as emitted by the LLM (no shared context)."""
    text: str = Field(
        description=(
            "A single, self-contained legal question. If the relationship_type is "
            "'causal', you MUST embed that causal link or reason in this question text "
            "itself (e.g. 'Is the rent increase valid, given that the tenant refused the request to vacate?')."
        )
    )
    query_type: QueryType = Field(
        description=(
            "Classify this sub-question's type for downstream pipeline routing:\n"
            "  • test_application — the question asks whether a specific fact pattern "
            "satisfies a legal test, standard, or set of statutory conditions. "
            "Examples: 'Can my landlord evict me for non-payment?', 'Does this "
            "contract clause violate Section 23 of the Indian Contract Act?'\n"
            "  • informational — the question is explanatory, definitional, or "
            "procedural. It asks WHAT something is, HOW a process works, or WHAT a "
            "provision says — without applying it to a fact pattern. "
            "Examples: 'What does Order 1 Rule 10 CPC allow?', 'What is the "
            "procedure for filing a civil suit?', 'What is res judicata?'"
        )
    )
    provision_key: Optional[str] = Field(
        default=None,
        description=(
            "The identified legal provision this sub-question targets, if one is "
            "identifiable. Use the most specific provision reference available — "
            "this can be a statute section (e.g. 'Order 1 Rule 10 CPC', 'Section 23 "
            "Indian Contract Act'), a case-law doctrine (e.g. 'res judicata', "
            "'doctrine of frustration'), or a procedural rule. This is NOT limited "
            "to statutes — case-law-only doctrines are valid provision keys. "
            "Null if the sub-question is too general to tie to a specific provision."
        ),
    )
    complexity: Complexity = Field(
        description=(
            "simple = one fact/section lookup; moderate = needs a couple of sources "
            "combined; complex = multi-issue or needs broad context."
        )
    )
    relationship_type: RelationshipType = Field(
        description=(
            "How this sub-question relates to the others. Use 'independent' if it "
            "stands alone. Set 'causal' if the user's query indicates that this "
            "issue or action happened BECAUSE of or in response to another sub-question's "
            "issue (e.g., rent raised because tenant refused to vacate). Set 'dependent' if "
            "answering this question requires knowing the answer to another sub-question first."
        )
    )
    depends_on: List[int] = Field(
        default_factory=list,
        description=(
            "1-based positions/indexes of the OTHER sub-questions in this list that "
            "this question hinges on, is caused by, or must be answered before this one. "
            "Must be populated if relationship_type is 'causal' or 'dependent'."
        ),
    )
    known_facts: List[str] = Field(
        default_factory=list,
        description=(
            "Facts from the user's query specifically relevant to THIS sub-question, "
            "each as a COMPLETE statement preserving the action/event (e.g. 'the "
            "business partner is selling the disputed plot'), not a bare entity label."
        ),
    )

    # Groq (esp. the smaller Llama models) sometimes emits `null` for an array field
    # instead of omitting it or sending []. `default_factory` only fills MISSING keys,
    # so an explicit null would raise a validation error — coerce it to [] here.
    @field_validator("depends_on", "known_facts", mode="before")
    @classmethod
    def _none_to_empty_list(cls, v):
        return [] if v is None else v


class QueryAnalysis(BaseModel):
    """
    Top-level single-call output of the Query Agent.

    The model returns EITHER a clarification request OR a finished split — never
    both. The §2b decision tree (required → ambiguous → jurisdiction) is encoded
    here as a schema, not as separate API calls.
    """
    reformulated_query: str = Field(
        description=(
            "Restate what the user is actually asking in clear legal terms. This is a "
            "distinct step (CLAUDE.md §2b): surface the real question before splitting. "
            "If the query is already clear, repeat it cleaned up."
        )
    )
    extracted_facts: Optional[List[str]] = Field(
        default_factory=list,
        description=(
            "All concrete facts present in the user's input, extracted before any "
            "split (parties, amounts, dates, actions, locations). These travel with "
            "every sub-question as shared context. "
            "CRITICAL: write each fact as a COMPLETE statement that preserves the "
            "ACTION/EVENT and its object — never reduce it to a bare entity label. "
            "E.g. for 'my business partner is selling our disputed plot', extract "
            "['the business partner is selling the disputed plot'], NOT "
            "['business partner', 'disputed plot']. The downstream Auditor verifies "
            "these facts against statutory conditions, so a dropped verb (sold, "
            "demolished, notified, paid) silently breaks verification. "
            "Empty list if none stated."
        ),
    )
    needs_clarification: bool = Field(
        description=(
            "True if the agent must stop and ask the user before retrieval can begin. "
            "Apply the gates in PRIORITY ORDER and surface only the HIGHEST-priority "
            "issue:\n"
            "  1. missing_required — there is no identifiable legal issue/question to "
            "retrieve on at all (the ONLY required field; do NOT ask for case details "
            "like dates/amounts/clauses — those are gathered later by the Auditor).\n"
            "  2. ambiguous — one input has multiple distinct valid interpretations.\n"
            "  3. jurisdiction — the query is incomplete in a way that materially "
            "changes the legal domain or jurisdiction.\n"
            "If none apply, set False and fill sub_questions instead."
        )
    )
    clarification_kind: Optional[ClarificationKind] = Field(
        default=None,
        description="Which gate fired. Required when needs_clarification is True, else null.",
    )
    pending_question: Optional[str] = Field(
        default=None,
        description=(
            "The single, specific question to put to the user. Required when "
            "needs_clarification is True, else null."
        ),
    )
    options: Optional[List[str]] = Field(
        default_factory=list,
        description=(
            "Only for clarification_kind='ambiguous': the distinct interpretations to "
            "offer the user (e.g. ['get the deposit back', 'challenge the eviction "
            "notice']). Empty otherwise."
        ),
    )
    sub_questions: Optional[List[SubQuestionDraft]] = Field(
        default_factory=list,
        description=(
            "The clean, split sub-questions to send downstream. Fill this ONLY when "
            "needs_clarification is False. One entry for a simple query; multiple for "
            "a compound one."
        ),
    )
    unknown_fields: Optional[List[str]] = Field(
        default_factory=list,
        description=(
            "Information you ASKED the user for but they could not provide, so you are "
            "proceeding WITHOUT it. Give each gap a short label, e.g. "
            "'jurisdiction/state' or 'eviction grounds'. Leave empty unless the "
            "conversation shows the user could not supply something you asked about. "
            "This is NOT for facts the user simply never mentioned — only for gaps the "
            "user was asked about and could not fill."
        ),
    )

    # Groq sometimes emits `null` for an array field instead of [] (CLAUDE.md §2b).
    # `default_factory` only fills MISSING keys, so an explicit null would raise a
    # validation error mid-call — coerce every list field to [] before validation.
    @field_validator(
        "extracted_facts", "options", "sub_questions", "unknown_fields", mode="before"
    )
    @classmethod
    def _none_to_empty_list(cls, v):
        return [] if v is None else v


# ─────────────────────────────────────────────
# Final public shapes (returned by run_query_agent)
# ─────────────────────────────────────────────

class SharedContext(BaseModel):
    """
    Mechanism 1 of §2b context preservation: travels with EVERY sub-question so no
    sub-question loses sight of the whole. Assembled by code, not by the LLM.
    """
    original_query: str
    known_facts: List[str] = Field(default_factory=list)
    # Gaps the user was asked about but could not fill (e.g. "jurisdiction/state").
    # Carried downstream so the Auditor/Adjudicator know the gap is acknowledged,
    # not silently dropped. Distinct from "never mentioned".
    unknown_fields: List[str] = Field(default_factory=list)


class SubQuestion(BaseModel):
    """A finished sub-question handed to the Researcher."""
    id: int
    text: str
    query_type: QueryType
    provision_key: Optional[str] = None
    complexity: Complexity
    relationship_type: RelationshipType
    depends_on: List[int] = Field(default_factory=list)
    known_facts: List[str] = Field(default_factory=list)
    shared_context: SharedContext

    @property
    def recommended_pipeline(self) -> str:
        """
        The downstream pipeline this sub-question should follow:
          • 'full'  (test_application) → Researcher → Checklist Resolver → Auditor → Adjudicator
          • 'short' (informational)    → Researcher → Adjudicator (skip Checklist Resolver + Auditor)
        """
        return "full" if self.query_type == QueryType.TEST_APPLICATION else "short"


class QueryAgentResult(BaseModel):
    """
    The Query Agent's return value. Exactly one of two states:
      • status='ready'   → sub_questions populated, safe to send to the Researcher.
      • status='clarify' → pending_question populated; caller asks the user, appends
                           the answer to history, and re-invokes (the resume loop).
    """
    status: str  # "ready" | "clarify"
    reformulated_query: str = ""
    sub_questions: List[SubQuestion] = Field(default_factory=list)

    # always populated — visibility for BOTH states (what got extracted so far, and
    # which asked-about gaps are being treated as unknown). Lets a clarify turn show
    # what's already filled instead of hiding it.
    extracted_facts: List[str] = Field(default_factory=list)
    unknown_fields: List[str] = Field(default_factory=list)

    # populated only when status == "clarify"
    pending_question: Optional[str] = None
    clarification_kind: Optional[ClarificationKind] = None
    options: List[str] = Field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


# ─────────────────────────────────────────────
# Checklist Resolver schemas (CLAUDE.md §2, §7)
# ─────────────────────────────────────────────

class ChecklistCondition(BaseModel):
    """A single extractable condition from a legal provision."""
    text: str = Field(
        description=(
            "A single, self-contained, verifiable legal condition. "
            "Extract ONLY from the provision text provided."
        )
    )
    critical: bool = Field(
        description=(
            "true ONLY if failing this specific condition means the "
            "provision cannot apply AT ALL — no court could excuse it. "
            "If the statute text elsewhere states that defects in this "
            "condition are excused, cured, or not grounds for dismissal "
            '(e.g., "shall not be dismissed merely by reason of..."), '
            "mark this condition false, even though it may be phrased "
            'as mandatory ("shall").'
        )
    )
    alternative_group: Optional[str] = Field(
        default=None,
        description=(
            "If this condition is one of several alternatives where "
            "satisfying ANY ONE is sufficient (e.g. 'if X is tendered, "
            "OR if proof of Y is given'), assign all alternatives in "
            "the same set the SAME tag string (e.g. 'stoppage_alternatives'). "
            "null if the condition is standalone (not part of an OR group)."
        )
    )


class ChecklistGroup(BaseModel):
    """A group of related conditions from one part of a legal provision."""
    group_label: str = Field(
        description=(
            "A short label for this group of conditions, e.g. "
            "'Sub-section (1) requirements', 'Proviso conditions', "
            "'General conditions'. Use the sub-section reference from "
            "the provision text when available."
        )
    )
    conditions: List[ChecklistCondition] = Field(
        description=(
            "Each condition as a ChecklistCondition with text and "
            "critical flag. Extract ONLY from the provision text."
        )
    )


class ChecklistExtraction(BaseModel):
    """
    LLM-facing schema: structured extraction of a checklist from a
    provision's text. Bound to .with_structured_output(...).
    """
    provision_name: str = Field(
        description="The name/reference of the provision being analyzed."
    )
    groups: List[ChecklistGroup] = Field(
        description=(
            "Groups of related conditions extracted from the provision. "
            "Group by sub-section, clause, or logical category. Each group "
            "has a label and a list of ChecklistCondition objects."
        )
    )


class ChecklistResult(BaseModel):
    """
    Public output of the Checklist Resolver for one provision.

    checklist is list[list[ChecklistCondition]] — each inner list is a
    group of related conditions. group_labels[i] names checklist[i].
    """
    provision_key: str = ""           # Original key as passed in
    canonical_key: str = ""           # Normalized cache key
    checklist: List[List[ChecklistCondition]] = Field(default_factory=list)
    group_labels: List[str] = Field(default_factory=list)
    source: str = ""                  # "cache" | "llm" | "not_found"
    provision_text_snippet: str = ""  # First ~200 chars of matched doc (debug)


# ─────────────────────────────────────────────
# Auditor schemas (CLAUDE.md §2, §2a, §6, §7)
# ─────────────────────────────────────────────

class AuditStatus(str, Enum):
    """
    Per-condition verdict the Auditor assigns when checking a checklist
    condition against the user's known facts (CLAUDE.md §2):
      • satisfied — the known facts clearly establish the condition IS met
      • failed    — the known facts clearly establish the condition is NOT met
      • unknown   — the facts are silent/insufficient -> candidate for a question to the user
    """
    SATISFIED = "satisfied"
    FAILED = "failed"
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────
# LLM-facing draft (bound to with_structured_output)
# ─────────────────────────────────────────────

class ConditionVerdict(BaseModel):
    """One verdict for one numbered checklist condition, emitted by the LLM."""
    index: int = Field(
        description=(
            "The 1-based index of the condition being judged. It MUST match the "
            "number shown next to that condition in the checklist you were given. "
            "Return exactly one verdict per numbered condition."
        )
    )
    status: AuditStatus = Field(
        description=(
            "satisfied = the KNOWN FACTS clearly establish this condition is met; "
            "failed = the known facts clearly establish this condition is NOT met; "
            "unknown = the facts are silent or insufficient to decide either way. "
            "Do NOT guess: if the facts do not address the condition, it is 'unknown', "
            "never a guessed 'satisfied'/'failed'."
        )
    )
    rationale: str = Field(
        description=(
            "One short sentence. For satisfied/failed: cite the specific known fact "
            "that decides it. For unknown: state exactly what fact is missing."
        )
    )


class AuditAssessment(BaseModel):
    """
    Single-call Auditor output: a verdict for every checklist condition, plus the
    single most pivotal follow-up question when an UNKNOWN blocks a determination.
    The decision of WHETHER to surface that question (and the satisfied/failed/applies
    math) is owned by code, not the model — see auditor.py.
    """
    verdicts: List[ConditionVerdict] = Field(
        description=(
            "Exactly one verdict per numbered condition you were given (any order). "
            "Do NOT invent conditions that were not listed."
        )
    )
    next_question: Optional[str] = Field(
        default=None,
        description=(
            "If one or more conditions are UNKNOWN and learning that fact could change "
            "whether the provision applies, write the SINGLE most pivotal, specific "
            "question to put to the user. Ask for ONE concrete fact in plain language "
            "(e.g. 'Did you deliver a written notice to the government at least two "
            "months before filing the suit, and to which officer?'). Null if nothing "
            "is unknown, or no answer could change the outcome."
        ),
    )
    next_question_index: Optional[int] = Field(
        default=None,
        description=(
            "The index of the condition your next_question is trying to resolve. "
            "Null when next_question is null."
        ),
    )


# ─────────────────────────────────────────────
# Final public shapes (returned by run_auditor)
# ─────────────────────────────────────────────

class AuditedCondition(BaseModel):
    """One checklist condition with the Auditor's verdict attached."""
    group_label: str = ""
    text: str
    critical: bool = False
    alternative_group: Optional[str] = None
    status: AuditStatus
    rationale: str = ""


class AuditResult(BaseModel):
    """
    The Auditor's return value. Exactly one of two states (mirrors QueryAgentResult):
      • status='complete' → determination + buckets filled; safe to send the
                            surviving_set to the Adjudicator.
      • status='clarify'  → pending_question filled; caller asks the user, appends
                            {question, answer, condition} to history, and re-invokes
                            (the resume loop → a LangGraph interrupt later).
    """
    status: str  # "clarify" | "complete"
    provision_key: str = ""

    # Set when status == "complete":
    #   "applies"       — every CRITICAL condition is satisfied (provision applies)
    #   "fails"         — a CRITICAL condition failed (provision cannot apply)
    #   "indeterminate" — a critical condition stayed unknown (user couldn't supply it)
    #   "no_checklist"  — nothing to audit (empty checklist came in)
    determination: Optional[str] = None

    # Verdict buckets — populated on BOTH states (snapshot on clarify, final on complete).
    satisfied: List[AuditedCondition] = Field(default_factory=list)
    failed: List[AuditedCondition] = Field(default_factory=list)
    unknown: List[AuditedCondition] = Field(default_factory=list)

    # The verified surviving set handed to the Adjudicator (the satisfied conditions —
    # every downstream claim must trace back to one of these). Filled on complete.
    surviving_set: List[AuditedCondition] = Field(default_factory=list)

    # Populated only when status == "clarify":
    pending_question: Optional[str] = None
    pending_condition: Optional[str] = None   # condition text the question targets (cap attribution)

    # Always populated — visibility into what the audit used / has asked.
    known_facts: List[str] = Field(default_factory=list)
    asked: List[str] = Field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"


# ─────────────────────────────────────────────
# Adjudicator schemas (CLAUDE.md §2, §2a, §6, §7)
# ─────────────────────────────────────────────

class SubAnswer(BaseModel):
    """The conclusion, reasoning, and citations for a single sub-question."""
    sub_question_id: int = Field(
        description="The 1-based ID of the sub-question being answered."
    )
    conclusion: str = Field(
        description="Brief legal conclusion for this specific sub-question."
    )
    reasoning: str = Field(
        description=(
            "Detailed legal reasoning for this sub-question. Must be fully "
            "grounded in the surviving verified conditions (if test_application) "
            "or retrieved evidence chunks (if informational). You must explain "
            "which conditions were satisfied or failed, or what information from "
            "the evidence pool resolves the procedural/informational query."
        )
    )
    citations: List[str] = Field(
        default_factory=list,
        description=(
            "A list of specific statutory sections, case citations, rule titles, "
            "or condition texts that support the reasoning."
        )
    )

    # Coerce None to empty list
    @field_validator("citations", mode="before")
    @classmethod
    def _none_to_empty_list(cls, v):
        return [] if v is None else v


class LegalOption(BaseModel):
    """An alternative legal path, scenario, or option depending on the circumstances."""
    title: str = Field(
        description="Title of this legal path or option (e.g. 'Option A: Seek stay of suit', 'Option B: Admit liability')."
    )
    description: str = Field(
        description="Detailed explanation of the legal path, its viability, and the likely outcome."
    )
    citations: List[str] = Field(
        default_factory=list,
        description="Citations supporting this specific legal path or option."
    )

    # Coerce None to empty list
    @field_validator("citations", mode="before")
    @classmethod
    def _none_to_empty_list(cls, v):
        return [] if v is None else v


class AdjudicationResult(BaseModel):
    """
    Top-level structured output of the Adjudicator agent. Emitted as a single
    structured JSON call.
    """
    ultimate_verdict: str = Field(
        description="The ultimate overall legal verdict or summary of the case (1-2 paragraphs)."
    )
    sub_answers: List[SubAnswer] = Field(
        description="Individual answers for each sub-question."
    )
    options: List[LegalOption] = Field(
        default_factory=list,
        description=(
            "If there are multiple legal options or paths depending on the "
            "surviving verified items or evidence, list them here. Otherwise empty."
        )
    )
    synthesis_and_conflicts: str = Field(
        description=(
            "A detailed synthesis of all sub-answers, explaining how they link "
            "(causal, dependent) and resolving any conflicts or overlaps between "
            "provisions (e.g., procedural CPC stays vs substantive rights)."
        )
    )

    # Coerce None to empty list
    @field_validator("sub_answers", "options", mode="before")
    @classmethod
    def _none_to_empty_list(cls, v):
        return [] if v is None else v


