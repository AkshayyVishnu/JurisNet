"""
Ablation eval — honest comparison matrix on OUR 54-question gold set.

We don't have other vendors' systems, so we isolate each RAG paradigm's *mechanism*
by ablating our own retriever (same corpus, same gold set, same metric):

  Vanilla RAG    = dense vectors only            (content_vector)
  Agentic-style  = dense + keyword (hybrid)      (content_vector + label_vector + bm25)
  GraphRAG-style = dense + citation graph         (content_vector + citation_graph)
  JurisNet       = full 4-source RRF fusion       (all four)

Reports Recall@5/@10 + MRR per config. Retrieval-only (no LLM) → fast, no rate limits.
Writes deck/comparison_data.md.

Run:  python eval/ablation.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrieval.hybrid_retriever import HybridRetriever  # noqa: E402

GOLD = ROOT / "golden_dataset" / "golden_dataset.jsonl"

CONFIGS = {
    "Vanilla (dense only)": ["content_vector"],
    "Hybrid (dense+BM25)": ["content_vector", "label_vector", "bm25"],
    "GraphRAG (dense+graph)": ["content_vector", "citation_graph"],
    "JurisNet (full 4-source)": ["content_vector", "label_vector", "bm25", "citation_graph"],
}


def main() -> None:
    gold = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    answerable = [g for g in gold if g.get("expected_behavior") == "answer"]
    r = HybridRetriever()
    ks = (5, 10)
    rows = {}
    for name, srcs in CONFIGS.items():
        hits = {k: 0 for k in ks}; rr = 0.0
        for g in answerable:
            results = r.retrieve(g["question"], "DEFAULT", top_k=10, force_sources=srcs)
            tids = [int(x["tid"]) for x in results]
            gold_ids = {int(t) for t in g.get("source_doc_ids", [])}
            primary = int(g["primary_source"])
            for k in ks:
                if gold_ids & set(tids[:k]):
                    hits[k] += 1
            rank = (tids.index(primary) + 1) if primary in tids else 0
            rr += (1.0 / rank) if rank else 0.0
        n = len(answerable)
        rows[name] = {"r5": hits[5] / n, "r10": hits[10] / n, "mrr": rr / n}
        print(f"  {name:26s} R@5 {rows[name]['r5']:.0%}  R@10 {rows[name]['r10']:.0%}  MRR {rows[name]['mrr']:.3f}")
    r.close()

    out = ROOT / "deck" / "comparison_data.md"
    out.parent.mkdir(exist_ok=True)
    lines = [f"# Retrieval ablation ({time.strftime('%Y-%m-%d')}) — {len(answerable)} answerable Qs, same gold set",
             "", "| Configuration | Recall@5 | Recall@10 | MRR |", "|---|---|---|---|"]
    for name, m in rows.items():
        lines.append(f"| {name} | {m['r5']:.0%} | {m['r10']:.0%} | {m['mrr']:.3f} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nsnapshot -> {out}")


if __name__ == "__main__":
    main()
