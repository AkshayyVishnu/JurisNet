"""
graph_ranker.py
───────────────
Converts Neo4j citation graph traversal results into a ranked list
that plugs directly into Reciprocal Rank Fusion alongside vector
and BM25 results.

The problem: RRF needs ranked lists. A graph traversal returns a SET
of connected nodes with no inherent ordering. This module scores each
node and sorts them into a ranked list.

Scoring formula per node:
    graph_score = (1 / hop_distance) × edge_type_weight × authority_score × recency_factor

Where:
    hop_distance:     1-hop = 1.0,  2-hop = 0.5,  3-hop = 0.33
    edge_type_weight: FOLLOWED=1.0, RELIED_ON=0.8, APPROVED=0.7,
                      EXPLAINED=0.6, REFERRED=0.4, DISTINGUISHED=0.3
    authority_score:  SC=1.0, HC=0.7, Privy=0.55, District=0.35, Tribunal=0.25
    recency_factor:   exp(-λ × years_old),  λ=0.02 (slow decay, legal precedent is long-lived)

Special handling:
    OVERRULED edges: the overruling case gets a BOOST (1.2×),
    the overruled case gets a CAUTION flag + score penalty (0.3×).

Usage:
    from graph_ranker import rank_graph_results

    # After Neo4j traversal returns raw nodes:
    raw_nodes = neo4j_traverse(seed_case_id, max_hops=3)
    ranked = rank_graph_results(raw_nodes, top_k=50)
    # → ranked list ready for RRF fusion
"""

import math
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import List, Optional


# ─────────────────────────────────────────────
# Edge type weights — how much retrieval value
# each citation relationship carries
# ─────────────────────────────────────────────

EDGE_WEIGHTS: dict[str, float] = {
    "FOLLOWED":      1.0,    # Court adopted the same reasoning — strongest signal
    "RELIED_ON":     0.8,    # Court relied on this as authority
    "APPROVED":      0.7,    # Court approved the reasoning
    "EXPLAINED":     0.6,    # Court clarified/expanded the principle
    "REFERRED":      0.4,    # Merely mentioned — weak signal
    "DISTINGUISHED": 0.3,    # Court said "this case is different" — weak but informative
    "DOUBTED":       0.2,    # Court expressed doubt — informative for validity
    "CITES":         0.5,    # Unclassified citation (pre-LLM default)
    "CITES_STATUTE": 0.6,    # Case cites a statute section
}

# Overruled gets special handling, not a simple weight
OVERRULED_PENALTY = 0.3      # Overruled case scored at 30% — still retrievable but ranked low
OVERRULING_BOOST  = 1.2      # The case that did the overruling gets a boost

# Recency decay
RECENCY_LAMBDA = 0.02        # Slow decay — legal precedent lives decades
                             # At λ=0.02: 10yr old = 0.82, 30yr old = 0.55, 50yr old = 0.37


@dataclass
class GraphNode:
    """
    One node returned from Neo4j traversal.
    This is the input format — matches what a Cypher query would return.
    """
    tid: int
    title: str
    court: str = ""
    date: str = ""                       # ISO date string
    authority_score: float = 0.5
    persuasive_only: bool = False
    citation_status: str = "GOOD_LAW"    # GOOD_LAW / OVERRULED / DOUBTED
    hop_distance: int = 1                # 1, 2, or 3
    edge_type: str = "CITES"             # relationship from seed case
    overruled_by_tid: Optional[int] = None


@dataclass
class RankedGraphResult:
    """
    One scored node ready for RRF fusion.
    Comparable to a vector search result or BM25 result.
    """
    tid: int
    title: str
    graph_score: float
    rank: int = 0                        # filled after sorting
    hop_distance: int = 1
    edge_type: str = "CITES"
    citation_status: str = "GOOD_LAW"
    caution_flag: bool = False           # True if overruled/doubted
    persuasive_only: bool = False
    debug: dict = field(default_factory=dict)  # component scores for transparency


def _recency_factor(date_str: str) -> float:
    """Exponential decay based on age of the case."""
    if not date_str:
        return 0.5   # unknown date → neutral
    try:
        case_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        years_old = (date.today() - case_date).days / 365.25
        return math.exp(-RECENCY_LAMBDA * max(0, years_old))
    except (ValueError, TypeError):
        return 0.5


def score_node(node: GraphNode) -> RankedGraphResult:
    """
    Score a single graph node using the composite formula.
    Returns a RankedGraphResult with the score and debug info.
    """
    # Component 1: hop distance (closer = better)
    hop_score = 1.0 / max(1, node.hop_distance)

    # Component 2: edge type weight
    edge_weight = EDGE_WEIGHTS.get(node.edge_type, 0.5)

    # Component 3: authority score (from court hierarchy)
    auth = node.authority_score

    # Component 4: recency
    recency = _recency_factor(node.date)

    # Base score
    score = hop_score * edge_weight * auth * recency

    # Special handling: overruled cases
    caution = False
    if node.citation_status == "OVERRULED":
        score *= OVERRULED_PENALTY
        caution = True
    elif node.citation_status == "DOUBTED":
        score *= 0.5
        caution = True

    # Special handling: if this node is the OVERRULING case (it overruled the seed)
    if node.edge_type == "OVERRULED" and node.citation_status == "GOOD_LAW":
        # This is the case that DID the overruling — it's the new authority
        score *= OVERRULING_BOOST

    # Persuasive-only flag (Privy Council etc.)
    if node.persuasive_only:
        score *= 0.85   # slight penalty, not disqualifying

    return RankedGraphResult(
        tid              = node.tid,
        title            = node.title,
        graph_score      = round(score, 6),
        hop_distance     = node.hop_distance,
        edge_type        = node.edge_type,
        citation_status  = node.citation_status,
        caution_flag     = caution,
        persuasive_only  = node.persuasive_only,
        debug = {
            "hop_score":   round(hop_score, 4),
            "edge_weight": edge_weight,
            "authority":   auth,
            "recency":     round(recency, 4),
            "status_mult": OVERRULED_PENALTY if node.citation_status == "OVERRULED" else 1.0,
        },
    )


def rank_graph_results(
    nodes: List[GraphNode],
    top_k: int = 50,
    deduplicate: bool = True,
) -> List[RankedGraphResult]:
    """
    Score all graph nodes, sort by score descending, assign ranks.
    Returns a ranked list ready for RRF fusion.

    Args:
        nodes:       Raw nodes from Neo4j traversal
        top_k:       Max results to return (matches vector/BM25 top-k)
        deduplicate: If True, keep only highest-scored entry per tid
    """
    scored = [score_node(n) for n in nodes]

    # Deduplicate: same case reached via multiple paths → keep best score
    if deduplicate:
        best: dict[int, RankedGraphResult] = {}
        for r in scored:
            if r.tid not in best or r.graph_score > best[r.tid].graph_score:
                best[r.tid] = r
        scored = list(best.values())

    # Sort by score descending
    scored.sort(key=lambda r: r.graph_score, reverse=True)

    # Assign ranks (1-indexed for RRF)
    for i, r in enumerate(scored[:top_k]):
        r.rank = i + 1

    return scored[:top_k]


# ─────────────────────────────────────────────
# RRF FUSION (all 4 ranked lists)
# ─────────────────────────────────────────────

@dataclass
class FusedResult:
    """Final retrieval result after RRF fusion across all sources."""
    tid: int
    title: str = ""
    rrf_score: float = 0.0
    sources: dict = field(default_factory=dict)  # {source_name: rank}
    caution_flag: bool = False


def reciprocal_rank_fusion(
    ranked_lists: dict[str, List[dict]],
    weights: dict[str, float],
    k: int = 60,
    top_n: int = 20,
) -> List[FusedResult]:
    """
    Fuse multiple ranked lists using weighted Reciprocal Rank Fusion.

    RRF score for document d = Σ  weight_i / (k + rank_i(d))

    Args:
        ranked_lists: {
            "content_vector": [{"tid": 123, "rank": 1, ...}, ...],
            "label_vector":   [{"tid": 456, "rank": 1, ...}, ...],
            "bm25":           [{"tid": 789, "rank": 1, ...}, ...],
            "citation_graph": [{"tid": 101, "rank": 1, "caution_flag": False, ...}, ...],
        }
        weights: {
            "content_vector": 0.35,
            "label_vector":   0.15,
            "bm25":           0.25,
            "citation_graph": 0.25,
        }
        k: RRF constant (default 60, standard value)
        top_n: Number of final results to return
    """
    scores: dict[int, FusedResult] = {}

    for source_name, results in ranked_lists.items():
        w = weights.get(source_name, 1.0)
        for item in results:
            tid  = item["tid"]
            rank = item.get("rank", 999)

            if tid not in scores:
                scores[tid] = FusedResult(
                    tid   = tid,
                    title = item.get("title", ""),
                )

            scores[tid].rrf_score += w / (k + rank)
            scores[tid].sources[source_name] = rank

            # Propagate caution flag from graph results
            if item.get("caution_flag", False):
                scores[tid].caution_flag = True

    # Sort by RRF score descending
    fused = sorted(scores.values(), key=lambda r: r.rrf_score, reverse=True)
    return fused[:top_n]


# ─────────────────────────────────────────────
# INTENT-BASED RRF WEIGHT PRESETS
# ─────────────────────────────────────────────
# The Query Understanding Agent outputs an intent type.
# Each intent maps to a weight preset optimizing for
# the retrieval mode most likely to produce good results.

RRF_WEIGHT_PRESETS: dict[str, dict[str, float]] = {
    "PRECEDENT": {
        "content_vector": 0.35,
        "label_vector":   0.10,
        "bm25":           0.15,
        "citation_graph": 0.40,    # graph-heavy: "cases that followed X"
    },
    "STATUTORY": {
        "content_vector": 0.20,
        "label_vector":   0.30,    # label-heavy: "Section 302 IPC"
        "bm25":           0.40,    # exact match critical
        "citation_graph": 0.10,
    },
    "CONCEPTUAL": {
        "content_vector": 0.50,    # semantic-heavy: "right to privacy"
        "label_vector":   0.05,
        "bm25":           0.15,
        "citation_graph": 0.30,
    },
    "PROCEDURAL": {
        "content_vector": 0.30,
        "label_vector":   0.15,
        "bm25":           0.35,    # procedure-specific terms matter
        "citation_graph": 0.20,
    },
    "COMPARISON": {
        "content_vector": 0.30,
        "label_vector":   0.15,
        "bm25":           0.15,
        "citation_graph": 0.40,    # need to find related/conflicting cases
    },
    "DEFAULT": {
        "content_vector": 0.35,
        "label_vector":   0.15,
        "bm25":           0.25,
        "citation_graph": 0.25,
    },
}

def get_rrf_weights(intent: str) -> dict[str, float]:
    """Get the RRF weight preset for a query intent type."""
    return RRF_WEIGHT_PRESETS.get(intent.upper(), RRF_WEIGHT_PRESETS["DEFAULT"])
