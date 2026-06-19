"""
query_embedder.py  v2
─────────────────────
Query-time embedding strategy for the poly-vector retrieval system.

v2 architecture: Voyage 4 shared embedding space.

INDEXING (one-time, offline):
  - voyage-4-large for ALL document embedding (content + label collections)
  - Both collections use the same Voyage 4 shared space

QUERYING (every user request):
  - voyage-4-nano running LOCALLY (Apache 2.0, self-hosted)
  - Shared embedding space means nano queries work against large-indexed docs
  - ZERO API calls at query time → ZERO rate limits

Why this beats the previous voyage+gemini split:
  - No gemini dependency
  - No 1000 RPD limit from gemini
  - No different dimensional spaces to manage
  - voyage-4-nano (local) is faster than any API call
  - One provider, one SDK, one set of dimensions

Rate limit notes:
  1. Add a payment method to Voyage — free 200M tokens STILL APPLY,
     but rate limits jump from 3 RPM → 2000 RPM for batch indexing.
  2. voyage-4-nano runs locally — infinite throughput at query time.
  3. voyage-4-large batch token limit: 120K tokens per request.
     Batch chunks in groups of ~100 (1000 tokens avg) per API call.

Usage:
    from query_embedder import embed_query, QueryPlan, load_local_nano

    # Load once at startup
    nano_model = load_local_nano()

    # Per query
    plan = embed_query(
        query="What does Section 302 IPC say about murder?",
        intent="STATUTORY",
        nano_model=nano_model,
    )
    # plan.query_vector → [0.12, ...] (1024 dims, same space as voyage-4-large docs)
    # plan.search_sources → ["label_vector", "bm25"]
    # plan.query_mode → "INFORMATIONAL" (skip Counsel pair)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any
from graph_ranker import get_rrf_weights


def load_local_nano(device: str = "cpu"):
    """
    Load voyage-4-nano locally.
    Apache 2.0 license — free to run anywhere.
    Uses sentence-transformers library.

    Install: pip install sentence-transformers

    For better performance on M1/M2 Mac: device="mps"
    For GPU: device="cuda"
    """
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("voyageai/voyage-4-nano", device=device)
        print(f"voyage-4-nano loaded on {device}")
        return model
    except ImportError:
        raise ImportError(
            "Install sentence-transformers: pip install sentence-transformers"
        )


def embed_with_nano(text: str, model: Any, truncate_dim: int = 1024) -> List[float]:
    """
    Embed a query using local voyage-4-nano.
    truncate_dim: 2048 / 1024 / 512 / 256 via Matryoshka.
    Use the same dim as your Qdrant collections (1024 default).
    """
    # voyage-4-nano uses encode_query for queries, encode_document for docs
    # sentence-transformers wraps both via .encode() with prompt_name parameter
    vector = model.encode(text, prompt_name="query", normalize_embeddings=True)
    # Truncate if needed via Matryoshka
    if truncate_dim and truncate_dim < len(vector):
        vector = vector[:truncate_dim]
    return vector.tolist()


# ─────────────────────────────────────────────
# Query plan
# ─────────────────────────────────────────────

@dataclass
class QueryPlan:
    """
    Complete query execution plan. Passed to the retrieval engine.
    """
    query_text: str
    intent: str

    # Single query vector (voyage-4-nano, shared space with voyage-4-large docs)
    # Same vector used to search BOTH Qdrant collections
    query_vector: Optional[List[float]] = None

    # Which retrieval sources to run
    search_sources: List[str] = field(default_factory=list)
    # → subset of: ["content_vector", "label_vector", "bm25", "citation_graph"]
    # Note: content_vector and label_vector use the SAME query_vector
    # (both collections were indexed with voyage-4-large, queried with voyage-4-nano)

    # RRF weights for the sources we're searching
    rrf_weights: dict = field(default_factory=dict)

    # Agent routing
    # INFORMATIONAL → skip Counsel pair, go direct to Synthesis
    # ARGUMENTATIVE → run Petitioner + Respondent Counsels
    query_mode: str = "INFORMATIONAL"


# ─────────────────────────────────────────────
# Intent → source routing
# ─────────────────────────────────────────────

QUERY_ROUTES: dict[str, dict] = {
    "STATUTORY": {
        "sources":     ["label_vector", "bm25"],
        "query_mode":  "INFORMATIONAL",
        # Label-heavy: "Section 302 IPC" → exact identifier match
    },
    "CITATION_LOOKUP": {
        "sources":     ["label_vector", "bm25"],
        "query_mode":  "INFORMATIONAL",
        # "AIR 1997 SC 3011" → exact citation string
    },
    "PRECEDENT": {
        "sources":     ["content_vector", "bm25", "citation_graph"],
        "query_mode":  "INFORMATIONAL",
        # "cases that followed Vishaka" → semantic + graph traversal
    },
    "CONCEPTUAL": {
        "sources":     ["content_vector", "bm25", "citation_graph"],
        "query_mode":  "INFORMATIONAL",
        # "what is mens rea" → pure semantic retrieval
    },
    "RIGHTS": {
        "sources":     ["content_vector", "label_vector", "bm25", "citation_graph"],
        "query_mode":  "ARGUMENTATIVE",
        # "right to privacy under Article 21" → both identifier + concept + competing rights
    },
    "COMPARISON": {
        "sources":     ["content_vector", "label_vector", "bm25", "citation_graph"],
        "query_mode":  "ARGUMENTATIVE",
        # "compare Vishaka with POSH Act" → adversarial perspectives add value
    },
    "PROCEDURAL": {
        "sources":     ["content_vector", "label_vector", "bm25"],
        "query_mode":  "INFORMATIONAL",
        # "how to file Section 96 CPC appeal" → factual, no adversarial needed
    },
    "ARGUMENTATIVE": {
        "sources":     ["content_vector", "label_vector", "bm25", "citation_graph"],
        "query_mode":  "ARGUMENTATIVE",
        # "can a tenant be evicted without notice" → explicitly wants both sides
    },
    "DEFAULT": {
        "sources":     ["content_vector", "label_vector", "bm25", "citation_graph"],
        "query_mode":  "ARGUMENTATIVE",
    },
}


def embed_query(
    query: str,
    intent: str,
    nano_model: Any,
    truncate_dim: int = 1024,
) -> QueryPlan:
    """
    Embed query with local voyage-4-nano and build the query plan.

    Args:
        query:        User's legal query text
        intent:       Intent from Query Understanding Agent
        nano_model:   Loaded SentenceTransformer model (call load_local_nano() once at startup)
        truncate_dim: Must match dimension of your Qdrant collections (default 1024)
    """
    route = QUERY_ROUTES.get(intent.upper(), QUERY_ROUTES["DEFAULT"])

    # Embed once — same vector searches both content + label collections
    # (because both were indexed with voyage-4-large in the shared embedding space)
    query_vector = embed_with_nano(query, nano_model, truncate_dim)

    plan = QueryPlan(
        query_text     = query,
        intent         = intent.upper(),
        query_vector   = query_vector,
        search_sources = route["sources"],
        query_mode     = route["query_mode"],
    )

    # RRF weights — normalized to the sources we're actually searching
    full_weights = get_rrf_weights(intent)
    raw = {s: full_weights.get(s, 0.0) for s in route["sources"]}
    total = sum(raw.values())
    plan.rrf_weights = {k: round(v / total, 4) for k, v in raw.items()} if total > 0 else raw

    return plan


# ─────────────────────────────────────────────
# Indexing helper — voyage-4-large batched
# ─────────────────────────────────────────────

def embed_documents_large(
    texts: List[str],
    voyage_api_key: str,
    batch_size: int = 100,
    truncate_dim: int = 1024,
) -> List[List[float]]:
    """
    Embed documents using voyage-4-large via API.
    Call this ONCE during indexing (not at query time).

    batch_size: voyage-4-large batch limit ~120K tokens = ~100 chunks at 1000 tokens avg.
    Add a payment method to get 2000 RPM (free tokens still apply).

    Returns list of vectors in the same order as input texts.
    """
    import voyageai
    client = voyageai.Client(api_key=voyage_api_key)

    all_vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        result = client.embed(
            batch,
            model="voyage-4-large",
            input_type="document",
            output_dimension=truncate_dim,
        )
        all_vectors.extend(result.embeddings)

    return all_vectors


# ─────────────────────────────────────────────
# Example / test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Mock nano model for testing without downloading
    class MockNano:
        def encode(self, text, prompt_name=None, normalize_embeddings=True):
            import numpy as np
            return np.zeros(1024)

    nano = MockNano()

    test_queries = [
        ("What does Section 302 IPC say about murder?",           "STATUTORY"),
        ("Cases that followed Vishaka on workplace harassment",    "PRECEDENT"),
        ("Right to privacy under Article 21",                     "RIGHTS"),
        ("AIR 1997 SC 3011",                                      "CITATION_LOOKUP"),
        ("What is mens rea in Indian criminal law?",              "CONCEPTUAL"),
        ("Can a tenant be evicted without notice in Delhi?",      "ARGUMENTATIVE"),
        ("How to file appeal under Section 96 CPC?",             "PROCEDURAL"),
    ]

    print("=== Query routing (v2 — single vector, local nano) ===\n")
    argumentative_count = 0
    for query, intent in test_queries:
        plan = embed_query(query, intent, nano)
        counsel = "→ Counsel pair" if plan.query_mode == "ARGUMENTATIVE" else "→ Direct to Synthesis"
        if plan.query_mode == "ARGUMENTATIVE":
            argumentative_count += 1
        print(f"  [{intent:16s}]  {query[:52]}")
        print(f"    Sources: {plan.search_sources}")
        print(f"    Weights: { {k: v for k, v in plan.rrf_weights.items()} }")
        print(f"    Agents:  {counsel}")
        print()

    print(f"API calls at query time: 0 (all queries use local nano)")
    print(f"Counsel pair fired: {argumentative_count}/{len(test_queries)} queries")