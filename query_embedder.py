"""
query_embedder.py
─────────────────
Query-time embedding strategy for the poly-vector retrieval system.

The problem: We have TWO Qdrant collections (content + label), each using
a different embedder. Naively embedding every query with BOTH embedders
wastes API calls and burns free-tier quota. Instead, we use the query
intent (from the Query Understanding Agent) to decide which embedders
to call.

Three modes:
    STATUTORY / CITATION_LOOKUP  → label vector + BM25 only  (skip voyage — save quota)
    PRECEDENT / CONCEPTUAL       → content vector + graph     (skip gemini — not useful)
    MIXED / DEFAULT              → both vectors + BM25 + graph

This saves an API call on ~40% of queries, which matters at Voyage's
3 RPM free-tier limit (effectively 1.5 queries/minute if calling both).

Usage:
    from query_embedder import embed_query, QueryPlan

    plan = embed_query(
        query="What does Section 302 IPC say about murder?",
        intent="STATUTORY",
        voyage_client=voyage_client,
        gemini_client=gemini_client,
    )
    # plan.content_vector → None (skipped)
    # plan.label_vector   → [0.12, -0.34, ...] (768 dims)
    # plan.search_collections → ["label", "bm25"]
    # plan.rrf_weights → {"label_vector": 0.30, "bm25": 0.40, ...}
"""

from dataclasses import dataclass, field
from typing import List, Optional, Protocol
from graph_ranker import get_rrf_weights


# ─────────────────────────────────────────────
# Embedding client protocols (duck-typed)
# ─────────────────────────────────────────────
# These match the interface of both voyage and gemini clients.
# LiteLLM or raw API calls both work.

class EmbeddingClient(Protocol):
    def embed(self, text: str) -> List[float]:
        """Embed a single text string, return a vector."""
        ...


# ─────────────────────────────────────────────
# Query plan — what the retriever receives
# ─────────────────────────────────────────────

@dataclass
class QueryPlan:
    """
    Complete query execution plan including vectors, collections to
    search, RRF weights, and agent routing. Passed to the retrieval engine.
    """
    query_text: str
    intent: str

    # Vectors — None means "skip this collection"
    content_vector: Optional[List[float]] = None
    label_vector: Optional[List[float]] = None

    # Which retrieval sources to actually run
    search_sources: List[str] = field(default_factory=list)
    # → subset of: ["content_vector", "label_vector", "bm25", "citation_graph"]

    # RRF weights — only for the sources we're actually searching
    rrf_weights: dict = field(default_factory=dict)

    # Agent routing — should the adversarial Counsel pair run?
    # INFORMATIONAL: "What does Section 302 say?" → skip Counsels, direct to Synthesis
    # ARGUMENTATIVE: "Can a tenant be evicted without notice?" → run both Counsels
    query_mode: str = "INFORMATIONAL"
    # → "INFORMATIONAL" or "ARGUMENTATIVE"

    # API calls used (for quota tracking)
    api_calls_made: dict = field(default_factory=dict)


# ─────────────────────────────────────────────
# Intent → embedding routing
# ─────────────────────────────────────────────

# Which embedders to call per intent type.
# True = call this embedder. False = skip.

EMBEDDING_ROUTES: dict[str, dict] = {
    # "Section 302 IPC", "Article 21" — label match is the primary signal
    "STATUTORY": {
        "content": False,
        "label":   True,
        "sources": ["label_vector", "bm25"],
        "query_mode": "INFORMATIONAL",    # "what does the law say" — no adversarial pair
    },

    # "Look up AIR 1997 SC 3011" — exact citation lookup
    "CITATION_LOOKUP": {
        "content": False,
        "label":   True,
        "sources": ["label_vector", "bm25"],
        "query_mode": "INFORMATIONAL",
    },

    # "Cases that followed Vishaka on workplace harassment"
    "PRECEDENT": {
        "content": True,
        "label":   False,
        "sources": ["content_vector", "bm25", "citation_graph"],
        "query_mode": "INFORMATIONAL",    # looking up precedent, not arguing
    },

    # "Right to privacy evolution", "What is mens rea?"
    "CONCEPTUAL": {
        "content": True,
        "label":   False,
        "sources": ["content_vector", "bm25", "citation_graph"],
        "query_mode": "INFORMATIONAL",
    },

    # "Right to life under Article 21" — needs both concept + identifier
    "RIGHTS": {
        "content": True,
        "label":   True,
        "sources": ["content_vector", "label_vector", "bm25", "citation_graph"],
        "query_mode": "ARGUMENTATIVE",    # rights questions often have competing interests
    },

    # "Compare Vishaka guidelines with POSH Act 2013"
    "COMPARISON": {
        "content": True,
        "label":   True,
        "sources": ["content_vector", "label_vector", "bm25", "citation_graph"],
        "query_mode": "ARGUMENTATIVE",    # comparisons benefit from both sides
    },

    # "How to file an appeal under Section 96 CPC?"
    "PROCEDURAL": {
        "content": True,
        "label":   True,
        "sources": ["content_vector", "label_vector", "bm25"],
        "query_mode": "INFORMATIONAL",    # procedure is factual, not argumentative
    },

    # "Can a tenant be evicted without notice in Delhi?"
    "ARGUMENTATIVE": {
        "content": True,
        "label":   True,
        "sources": ["content_vector", "label_vector", "bm25", "citation_graph"],
        "query_mode": "ARGUMENTATIVE",    # explicit argumentative query
    },

    # Fallback — search everything, assume argumentative to be safe
    "DEFAULT": {
        "content": True,
        "label":   True,
        "sources": ["content_vector", "label_vector", "bm25", "citation_graph"],
        "query_mode": "ARGUMENTATIVE",
    },
}


def embed_query(
    query: str,
    intent: str,
    voyage_client: Optional[EmbeddingClient] = None,
    gemini_client: Optional[EmbeddingClient] = None,
) -> QueryPlan:
    """
    Embed the query with the appropriate embedder(s) based on intent.

    Args:
        query:          The user's legal query text
        intent:         Intent from Query Understanding Agent
                        (STATUTORY / PRECEDENT / CONCEPTUAL / RIGHTS /
                         COMPARISON / PROCEDURAL / CITATION_LOOKUP / DEFAULT)
        voyage_client:  Content embedder (voyage-context-3)
        gemini_client:  Label embedder (gemini-embedding-001)

    Returns:
        QueryPlan with vectors, search sources, and RRF weights
    """
    route = EMBEDDING_ROUTES.get(intent.upper(), EMBEDDING_ROUTES["DEFAULT"])

    plan = QueryPlan(
        query_text     = query,
        intent         = intent.upper(),
        search_sources = route["sources"],
        query_mode     = route.get("query_mode", "ARGUMENTATIVE"),
    )

    # Embed with content embedder (voyage-context-3) if needed
    if route["content"] and voyage_client is not None:
        plan.content_vector = voyage_client.embed(query)
        plan.api_calls_made["voyage"] = 1

    # Embed with label embedder (gemini-embedding-001) if needed
    if route["label"] and gemini_client is not None:
        plan.label_vector = gemini_client.embed(query)
        plan.api_calls_made["gemini"] = 1

    # Get RRF weights for the intent — only for sources we're searching
    full_weights = get_rrf_weights(intent)
    plan.rrf_weights = {
        source: full_weights.get(source, 0.0)
        for source in plan.search_sources
    }

    # Re-normalize weights to sum to 1.0 (since we may have dropped sources)
    total = sum(plan.rrf_weights.values())
    if total > 0:
        plan.rrf_weights = {k: v / total for k, v in plan.rrf_weights.items()}

    return plan


# ─────────────────────────────────────────────
# Quota tracking — helps plan free-tier usage
# ─────────────────────────────────────────────

@dataclass
class QuotaTracker:
    """
    Tracks API calls per provider across a session.
    Helps stay within free-tier limits.
    """
    voyage_calls: int = 0
    gemini_calls: int = 0

    # Free-tier limits (verify before implementation — these change)
    VOYAGE_RPM_FREE: int = 3         # 3 RPM without payment method
    GEMINI_RPD_FREE: int = 1000      # 1000 requests per day

    def record(self, plan: QueryPlan):
        self.voyage_calls += plan.api_calls_made.get("voyage", 0)
        self.gemini_calls += plan.api_calls_made.get("gemini", 0)

    @property
    def voyage_remaining_today(self) -> str:
        """Rough estimate — actual limit is RPM-based, not daily."""
        return f"~{self.VOYAGE_RPM_FREE * 60 * 8 - self.voyage_calls} calls remaining (8hr day)"

    @property
    def gemini_remaining_today(self) -> int:
        return self.GEMINI_RPD_FREE - self.gemini_calls


# ─────────────────────────────────────────────
# Example usage
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Simulated — no real API calls
    class MockEmbedder:
        def embed(self, text: str) -> List[float]:
            return [0.0] * 10  # placeholder

    voyage = MockEmbedder()
    gemini = MockEmbedder()
    tracker = QuotaTracker()

    test_queries = [
        ("What does Section 302 IPC say?",                     "STATUTORY"),
        ("Cases that followed Vishaka on workplace harassment", "PRECEDENT"),
        ("Right to privacy under Article 21",                  "RIGHTS"),
        ("Look up AIR 1997 SC 3011",                           "CITATION_LOOKUP"),
        ("What is mens rea in Indian criminal law?",           "CONCEPTUAL"),
        ("Can a tenant be evicted without notice in Delhi?",   "ARGUMENTATIVE"),
        ("How to file an appeal under Section 96 CPC?",        "PROCEDURAL"),
    ]

    print("=== Query-time embedding + agent routing decisions ===\n")
    for query, intent in test_queries:
        plan = embed_query(query, intent, voyage, gemini)
        tracker.record(plan)

        calls = []
        if plan.content_vector is not None:
            calls.append("voyage ✓")
        else:
            calls.append("voyage ✗")
        if plan.label_vector is not None:
            calls.append("gemini ✓")
        else:
            calls.append("gemini ✗")

        counsel = "→ Petitioner + Respondent Counsels" if plan.query_mode == "ARGUMENTATIVE" else "→ Direct to Synthesis (skip Counsels)"

        print(f"  Query:   {query}")
        print(f"  Intent:  {intent}  |  Mode: {plan.query_mode}")
        print(f"  Calls:   {', '.join(calls)}")
        print(f"  Sources: {plan.search_sources}")
        print(f"  Agent:   {counsel}")
        print()

    n = len(test_queries)
    print(f"Total API calls: voyage={tracker.voyage_calls}, gemini={tracker.gemini_calls}")
    print(f"Saved {n - tracker.voyage_calls} voyage + {n - tracker.gemini_calls} gemini calls out of {n} queries")
    print(f"Adversarial pair skipped on {sum(1 for q, i in test_queries if EMBEDDING_ROUTES.get(i.upper(), EMBEDDING_ROUTES['DEFAULT'])['query_mode'] == 'INFORMATIONAL')} of {n} queries")
