# Retrieval ablation (2026-06-21) — 50 answerable Qs, same gold set

| Configuration | Recall@5 | Recall@10 | MRR |
|---|---|---|---|
| Vanilla (dense only) | 62% | 64% | 0.293 |
| Hybrid (dense+BM25) | 62% | 86% | 0.341 |
| GraphRAG (dense+graph) | 60% | 64% | 0.235 |
| JurisNet (full 4-source) | 62% | 82% | 0.320 |
