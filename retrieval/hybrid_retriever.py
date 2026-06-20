"""
Phase 3 — Hybrid retriever.

One entrypoint: HybridRetriever().retrieve(query, intent) -> ranked documents
with their best chunk text, ready for synthesis.

Flow (per IMPLEMENTATION_PLAN / PIPELINE_STAGES):
  1. embed_query -> QueryPlan (vector + which sources + RRF weights, by intent)
  2. fan out to the sources the plan selects:
       content_vector -> Qdrant content      label_vector -> Qdrant label
       bm25           -> SQLite FTS5          citation_graph -> Neo4j traverse -> graph_ranker
  3. adapter + per-source tid-collapse (one rank per doc per source)
  4. reciprocal_rank_fusion(weighted) -> ranked tids
  5. chunk-fetch: attach each doc's best chunk text for synthesis
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from stores import qdrant_store  # noqa: E402
from stores import neo4j_store  # noqa: E402
from legal_fts5 import LegalFTS5  # noqa: E402
from query_embedder import embed_query  # noqa: E402
from graph_ranker import reciprocal_rank_fusion, rank_graph_results  # noqa: E402

CONTENT = config.QDRANT_CONTENT_COLLECTION
LABEL = config.QDRANT_LABEL_COLLECTION
PER_SOURCE_K = 50   # candidates pulled from each source before fusion


def _collapse(results: list[dict]):
    """Collapse multiple chunks of the same tid to that source's best (first) rank.
    Returns (ranked_list, chunk_map). results must be in best-first order."""
    ranked, chunk_map, seen = [], {}, set()
    for r in results:
        tid = r.get("tid")
        if tid is None or tid in seen:
            continue
        seen.add(tid)
        ranked.append({"tid": tid, "rank": len(ranked) + 1,
                       "title": r.get("title", ""), "caution_flag": False})
        chunk_map[tid] = {"text": r.get("text", ""), "chunk_type": r.get("chunk_type", ""),
                          "title": r.get("title", ""), "score": r.get("score")}
    return ranked, chunk_map


def _seed_tids(ranked_lists: dict, n: int = 5) -> list[int]:
    """Seed graph traversal from the top vector/bm25 hits."""
    seeds = []
    for src in ("content_vector", "label_vector", "bm25"):
        for item in ranked_lists.get(src, [])[:n]:
            if item["tid"] not in seeds:
                seeds.append(item["tid"])
    return seeds


class HybridRetriever:
    def __init__(self):
        self.qc = qdrant_store.get_client()
        self.fts = LegalFTS5(str(config.FTS5_DB_PATH))
        # Ensure the FTS5 table exists even if legal_fts5.db was never built — otherwise
        # search() raises "no such table: legal_fts" and aborts the whole retrieve().
        # An empty index just contributes no BM25 hits; vector + graph still answer.
        self.fts.initialize()
        self.driver = neo4j_store.get_driver()

    def close(self):
        self.fts.close()
        self.driver.close()

    def retrieve(self, query: str, intent: str = "DEFAULT", top_k: int = 20) -> list[dict]:
        plan = embed_query(
            query, intent,
            mode=config.QUERY_EMBED_MODE,
            voyage_api_key=config.VOYAGE_API_KEY,
            truncate_dim=config.EMBED_DIM,
        )
        sources = plan.search_sources
        ranked_lists: dict[str, list[dict]] = {}
        chunk_map: dict[int, dict] = {}

        if "content_vector" in sources:
            res = qdrant_store.search(self.qc, CONTENT, plan.query_vector, top_k=PER_SOURCE_K)
            ranked_lists["content_vector"], cm = _collapse(res)
            chunk_map.update({k: v for k, v in cm.items() if k not in chunk_map})

        if "label_vector" in sources:
            res = qdrant_store.search(self.qc, LABEL, plan.query_vector, top_k=PER_SOURCE_K)
            ranked_lists["label_vector"], cm = _collapse(res)
            chunk_map.update({k: v for k, v in cm.items() if k not in chunk_map})

        if "bm25" in sources:
            try:
                res = self.fts.search(query, top_k=PER_SOURCE_K)  # tid, rank, snippet (no text)
                ranked_lists["bm25"], _ = _collapse(res)
            except Exception as e:  # noqa: BLE001 — a dead/empty BM25 index must not kill retrieval
                print(f"[HybridRetriever] BM25 source skipped: {e}")

        if "citation_graph" in sources:
            seeds = _seed_tids(ranked_lists)
            if seeds:
                nodes = neo4j_store.traverse(self.driver, seeds, max_hops=2)
                ranked = rank_graph_results(nodes, top_k=PER_SOURCE_K)
                ranked_lists["citation_graph"] = [
                    {"tid": r.tid, "rank": i + 1, "title": r.title, "caution_flag": r.caution_flag}
                    for i, r in enumerate(ranked)
                ]

        fused = reciprocal_rank_fusion(ranked_lists, plan.rrf_weights, top_n=top_k)

        # ── Chunk-fetch: attach best chunk text for synthesis ──
        out = []
        for f in fused:
            cm = chunk_map.get(f.tid)
            if cm is None:
                pl = (qdrant_store.fetch_by_tid(self.qc, CONTENT, f.tid)
                      or qdrant_store.fetch_by_tid(self.qc, LABEL, f.tid) or {})
                cm = {"text": pl.get("text", ""), "chunk_type": pl.get("chunk_type", ""),
                      "title": pl.get("title", "")}
            out.append({
                "tid": f.tid,
                "title": f.title or cm.get("title", ""),
                "rrf_score": round(f.rrf_score, 5),
                "sources": f.sources,
                "caution_flag": f.caution_flag,
                "chunk_type": cm.get("chunk_type", ""),
                "text": cm.get("text", ""),
            })
        return out


if __name__ == "__main__":
    import json
    r = HybridRetriever()
    try:
        for q, intent in [
            ("What is the punishment for murder under Section 302 IPC?", "STATUTORY"),
            ("what is the test for granting a temporary injunction", "CONCEPTUAL"),
        ]:
            print("\n" + "=" * 70)
            print(f"Q: {q}  [{intent}]")
            res = r.retrieve(q, intent, top_k=5)
            for x in res:
                print(f"  tid={x['tid']} rrf={x['rrf_score']} src={list(x['sources'])} "
                      f"{x['chunk_type']:13s} {x['title'][:45]}")
    finally:
        r.close()
