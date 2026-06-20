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

from pydantic import BaseModel, Field


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
            "A single, self-contained legal question. If the original query linked "
            "ideas causally (e.g. a withheld deposit AND a retaliation complaint), "
            "bake that link INTO this text so it reads completely on its own — do not "
            "rely on the other sub-questions for meaning."
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
            "stands alone, 'dependent' if it needs another sub-question's answer "
            "first, 'causal' if it is linked to another by a cause/effect chain in "
            "the original query. If there is only one sub-question, use 'independent'."
        )
    )
    depends_on: List[int] = Field(
        default_factory=list,
        description=(
            "1-based positions of the OTHER sub-questions in this list that must be "
            "answered before this one. Empty if independent."
        ),
    )
    known_facts: List[str] = Field(
        default_factory=list,
        description="Facts from the user's query that are specifically relevant to THIS sub-question.",
    )


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
    extracted_facts: List[str] = Field(
        default_factory=list,
        description=(
            "All concrete facts present in the user's input, extracted before any "
            "split (parties, amounts, dates, actions, locations). These travel with "
            "every sub-question as shared context. Empty list if none stated."
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
    options: List[str] = Field(
        default_factory=list,
        description=(
            "Only for clarification_kind='ambiguous': the distinct interpretations to "
            "offer the user (e.g. ['get the deposit back', 'challenge the eviction "
            "notice']). Empty otherwise."
        ),
    )
    sub_questions: List[SubQuestionDraft] = Field(
        default_factory=list,
        description=(
            "The clean, split sub-questions to send downstream. Fill this ONLY when "
            "needs_clarification is False. One entry for a simple query; multiple for "
            "a compound one."
        ),
    )
    unknown_fields: List[str] = Field(
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

