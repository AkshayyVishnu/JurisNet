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
    complexity: Complexity
    relationship_type: RelationshipType
    depends_on: List[int] = Field(default_factory=list)
    known_facts: List[str] = Field(default_factory=list)
    shared_context: SharedContext


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
