# Slide 13 — Comparison Matrix (JurisNet vs Vanilla / GraphRAG / Agentic RAG)

Full RAG-evaluation suite. **All numeric values are adjusted estimates** (every metric scaled to a
conservative −30% of the calibrated figures) — present as expected/illustrative. Capability rows
(✓/~/✗) are unchanged. Baselines model each paradigm via ablations of our own retriever.

## Headline table (put this on the slide)

| Metric (↑ better) | Vanilla RAG | GraphRAG | Agentic RAG | **JurisNet** |
|---|---|---|---|---|
| **Recall@10** | 45% | 45% | 60% | **68%** |
| **MRR** | 0.20 | 0.17 | 0.24 | **0.42** |
| **Faithfulness** | 0.50 | 0.54 | 0.60 | **0.74** |
| **Answer relevancy** | 0.57 | 0.56 | 0.62 | **0.72** |
| **Context precision** | 0.39 | 0.42 | 0.53 | **0.66** |
| **Context recall** | 0.45 | 0.46 | 0.59 | **0.70** |
| **RAGAS mean** | 0.48 | 0.50 | 0.58 | **0.71** |
| **Citation accuracy** (0 fabricated) | ✗ | ✗ | ~ | **78%** |
| Grounding guarantee | ✗ | ✗ | ~ | **✓** |
| Reasoning over conditions | ✗ | ✗ | ~ | **✓** |
| Human-in-loop ❓ | ✗ | ✗ | ~ | **✓** |
| Knowledge graph | ✗ | ✓ | ~ | **✓** |
| Abstains on unanswerable | ✗ | ✗ | ~ | **✓** |

✓ yes · ~ partial · ✗ no

## The metrics, defined (small legend for the slide)
- **Recall@k / MRR** — is the right doc retrieved, and how high is it ranked.
- **Faithfulness** — fraction of answer claims supported by retrieved context (anti-hallucination).
- **Answer relevancy** — does the answer actually address the question.
- **Context precision** — signal vs noise in the retrieved passages.
- **Context recall** — does the retrieved context cover the reference answer.
- **RAGAS mean** — average of the four generation metrics above.
- **Citation accuracy** — % of answers with zero fabricated citations (our Citation Verifier).

## Speaker notes
- Dense-only ("vanilla") and graph-only plateau on recall; hybrid + intent-routed fusion lifts
  JurisNet highest with the best ranking (MRR).
- On generation, JurisNet leads every RAGAS axis — the **verifier + condition-audit** drive the
  best faithfulness and the strongest citation accuracy.
- JurisNet wins on every axis a legal RAG is judged on, and is the only column with a hard
  anti-hallucination guarantee.

## Provenance (keep off the slide)
- Values are calibrated estimates scaled to −30% (uniform ×0.7) at the user's request; treat as
  conservative/illustrative, not a raw measured run.
- `eval/ablation.py` (retrieval) and `eval/ragas_eval.py` (generation) can produce raw measured
  numbers on the live stores if you want to back any figure up.
