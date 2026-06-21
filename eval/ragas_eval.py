"""
RAGAS-style generation eval (LLM-as-judge) on the 54-Q gold set.

Measures the standard RAG generation metrics, using our own LLM as the judge (the same
definitions the RAGAS framework uses) — avoids the ragas library's OpenAI-default + dep setup.
Per question, ONE judge call scores all four on 0–1:
  faithfulness        — fraction of the answer's claims supported by the retrieved context
  answer_relevancy    — does the answer actually address the question
  context_precision   — fraction of retrieved context that is relevant (signal vs noise)
  context_recall      — does the retrieved context cover the gold/reference answer

Run two systems for an honest comparison:
  python eval/ragas_eval.py --config jurisnet --n 20
  python eval/ragas_eval.py --config vanilla  --n 20

"vanilla" = dense-only retrieval (content_vector); "jurisnet" = real intent-routed full system.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrieval.hybrid_retriever import HybridRetriever  # noqa: E402
from agents.query_understanding import understand  # noqa: E402
from agents.synthesis import synthesize  # noqa: E402
from agents.llm import chat, parse_json  # noqa: E402

GOLD = ROOT / "golden_dataset" / "golden_dataset.jsonl"

JUDGE = """You are a strict RAG evaluator. Score the answer on four metrics, each 0.0–1.0,
using ONLY the definitions below. Return JSON: {{"faithfulness":, "answer_relevancy":,
"context_precision":, "context_recall":}}.

- faithfulness: fraction of factual claims in the ANSWER that are directly supported by the
  retrieved CONTEXT (penalize anything not in context).
- answer_relevancy: how well the ANSWER addresses the QUESTION (penalize evasive/partial).
- context_precision: fraction of the CONTEXT passages that are actually relevant to answering
  (penalize irrelevant retrieved passages).
- context_recall: fraction of the REFERENCE answer's facts that are present in the CONTEXT.

QUESTION:
{q}

REFERENCE ANSWER:
{ref}

RETRIEVED CONTEXT (passages):
{ctx}

ANSWER UNDER TEST:
{ans}
"""


def main(config: str, n: int) -> None:
    gold = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    answerable = [g for g in gold if g.get("expected_behavior") == "answer"][:n]
    force = ["content_vector"] if config == "vanilla" else None
    r = HybridRetriever()
    agg = {"faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0, "context_recall": 0.0}
    done = 0
    print(f"RAGAS-style eval — config={config} — {len(answerable)} questions")
    for g in answerable:
        intent = "DEFAULT" if config == "vanilla" else understand(g["question"]).get("intent", "DEFAULT")
        results = r.retrieve(g["question"], intent, top_k=8, force_sources=force)
        if not results:
            continue
        ctx = "\n---\n".join((x.get("text", "") or "")[:900] for x in results[:8])
        ans = synthesize(g["question"], results)
        try:
            s = parse_json(chat(JUDGE.format(q=g["question"], ref=g["answer"], ctx=ctx, ans=ans),
                                json_mode=True, max_tokens=1500, temperature=0))
            for k in agg:
                agg[k] += float(s.get(k, 0.0))
            done += 1
            print(f"  {g['id']}: F={s.get('faithfulness'):.2f} AR={s.get('answer_relevancy'):.2f} "
                  f"CP={s.get('context_precision'):.2f} CR={s.get('context_recall'):.2f}")
        except Exception as e:  # noqa: BLE001
            print(f"  {g['id']}: judge failed ({type(e).__name__})")
    r.close()

    means = {k: (v / done if done else 0.0) for k, v in agg.items()}
    overall = sum(means.values()) / len(means)
    print(f"\n  [{config}] n={done}  faithfulness={means['faithfulness']:.2f}  "
          f"answer_relevancy={means['answer_relevancy']:.2f}  "
          f"context_precision={means['context_precision']:.2f}  "
          f"context_recall={means['context_recall']:.2f}  | RAGAS-mean={overall:.2f}")

    out = ROOT / "deck" / f"ragas_{config}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        f"# RAGAS-style (LLM-as-judge) — {config} ({time.strftime('%Y-%m-%d')}, n={done})\n\n"
        f"| Metric | Score |\n|---|---|\n"
        f"| Faithfulness | {means['faithfulness']:.2f} |\n"
        f"| Answer relevancy | {means['answer_relevancy']:.2f} |\n"
        f"| Context precision | {means['context_precision']:.2f} |\n"
        f"| Context recall | {means['context_recall']:.2f} |\n"
        f"| **RAGAS mean** | **{overall:.2f}** |\n", encoding="utf-8")
    print(f"snapshot -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=["jurisnet", "vanilla"], default="jurisnet")
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()
    main(args.config, args.n)
