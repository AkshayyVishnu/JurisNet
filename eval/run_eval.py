"""
JurisNet eval harness (Phase 5) — reuses the existing 54-question golden dataset.

Gold set:  golden_dataset/golden_dataset.jsonl (source_doc_ids = tids, primary_source = tid,
           expected_behavior = "answer" | "abstain").

Retrieval quality (answerable Qs):
  Recall@5/@10/@20  — is primary_source / any source_doc_id in the retriever's top-k tids
  MRR               — reciprocal rank of primary_source
Citation accuracy (--cite, answerable Qs):
  mean confidence + % of answers with 0 fabricated citations (agents/citation_verifier)
Abstain traps (4): report-only (do answers stay low-confidence / 0-fabrication).

Runs the SAME pipeline as app.py: understand(query) -> HybridRetriever.retrieve(query, intent).

Usage:
  python eval/run_eval.py --dry-run    # loads gold set, checks tids exist (no stores needed)
  python eval/run_eval.py              # retrieval metrics (needs .env + live stores)
  python eval/run_eval.py --cite       # + citation accuracy (uses the LLM)
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLD = ROOT / "golden_dataset" / "golden_dataset.jsonl"


def _load_gold() -> list[dict]:
    return [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]


def _corpus_tids() -> set[int]:
    tids = set()
    for sub in ("LEGAL_DATA/judgments", "LEGAL_DATA/provisions"):
        for p in glob.glob(str(ROOT / sub / "*.json")):
            try:
                tids.add(int(json.loads(Path(p).read_text(encoding="utf-8"), strict=False)["doc_id"]))
            except Exception:  # noqa: BLE001
                pass
    return tids


def dry_run() -> None:
    gold = _load_gold()
    from collections import Counter
    ans = [g for g in gold if g.get("expected_behavior") == "answer"]
    abst = [g for g in gold if g.get("expected_behavior") != "answer"]
    print(f"gold records: {len(gold)}  | answerable: {len(ans)}  | abstain: {len(abst)}")
    print("by question_type:", dict(Counter(g.get("question_type", "?") for g in gold)))
    print("by difficulty:", dict(Counter(g.get("difficulty", "?") for g in gold)))

    corpus = _corpus_tids()
    missing = []
    for g in ans:
        for t in g.get("source_doc_ids", []):
            if int(t) not in corpus:
                missing.append((g["id"], t))
    print(f"\nsource_doc_ids checked against {len(corpus)} corpus tids — missing: {len(missing)}")
    for gid, t in missing[:10]:
        print(f"  ! {gid}: tid {t} not under LEGAL_DATA/")
    print("dry-run OK" if not missing else "dry-run: some gold tids missing (see above)")


def run(do_cite: bool) -> None:
    from agents.query_understanding import understand
    from retrieval.hybrid_retriever import HybridRetriever

    gold = _load_gold()
    answerable = [g for g in gold if g.get("expected_behavior") == "answer"]
    abstain = [g for g in gold if g.get("expected_behavior") != "answer"]
    r = HybridRetriever()

    ks = (5, 10, 20)
    hits = {k: 0 for k in ks}
    rr = 0.0
    print("=" * 70); print(f"RETRIEVAL EVAL — {len(answerable)} answerable questions"); print("=" * 70)
    for g in answerable:
        intent = understand(g["question"]).get("intent", "DEFAULT")
        results = r.retrieve(g["question"], intent, top_k=max(ks))
        tids = [int(x["tid"]) for x in results]
        gold_ids = {int(t) for t in g.get("source_doc_ids", [])}
        primary = int(g["primary_source"])
        for k in ks:
            if gold_ids & set(tids[:k]):
                hits[k] += 1
        rank = (tids.index(primary) + 1) if primary in tids else 0
        rr += (1.0 / rank) if rank else 0.0
        mark = "✓" if (gold_ids & set(tids[:10])) else "✗"
        print(f"  {mark} {g['id']} rank={rank or '-':<3} | {g['question'][:50]}")

    n = len(answerable)
    recall = {k: hits[k] / n for k in ks}
    mrr = rr / n
    print(f"\n  Recall@5 {recall[5]:.0%} · @10 {recall[10]:.0%} · @20 {recall[20]:.0%}   MRR {mrr:.3f}")

    cite = None
    if do_cite:
        from agents.synthesis import synthesize
        from agents import citation_verifier
        print("\n" + "=" * 70); print(f"CITATION ACCURACY — {n} answerable (fast path)"); print("=" * 70)
        clean = 0; conf_sum = 0.0
        for g in answerable:
            intent = understand(g["question"]).get("intent", "DEFAULT")
            results = r.retrieve(g["question"], intent, top_k=15)
            if not results:
                continue
            v = citation_verifier.verify(synthesize(g["question"], results), results, driver=r.driver)
            conf_sum += v["confidence"]
            clean += int(not v["fabricated"])
            print(f"  {'✓' if not v['fabricated'] else '✗'} {g['id']} conf={v['confidence']:.0%} fab={v['fabricated']}")
        cite = {"mean_conf": conf_sum / n, "zero_fab_pct": clean / n}
        print(f"\n  Mean confidence {cite['mean_conf']:.0%} · 0-fabrication {cite['zero_fab_pct']:.0%}")

    r.close()

    res = ROOT / "deck" / "RESULTS.md"
    res.parent.mkdir(exist_ok=True)
    lines = [f"# JurisNet — Eval snapshot ({time.strftime('%Y-%m-%d')})", "",
             f"Gold set: {len(gold)} questions ({n} answerable, {len(abstain)} abstain traps)", "",
             "| Metric | Value |", "|---|---|",
             f"| Recall@5 | {recall[5]:.0%} |",
             f"| Recall@10 | {recall[10]:.0%} |",
             f"| Recall@20 | {recall[20]:.0%} |",
             f"| MRR (primary source) | {mrr:.3f} |"]
    if cite:
        lines += [f"| Mean citation confidence | {cite['mean_conf']:.0%} |",
                  f"| Answers with 0 fabricated cites | {cite['zero_fab_pct']:.0%} |"]
    res.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nsnapshot -> {res}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="load gold set + check tids exist (no stores)")
    ap.add_argument("--cite", action="store_true", help="also score citation accuracy (uses the LLM)")
    args = ap.parse_args()
    if args.dry_run:
        dry_run()
    else:
        run(args.cite)
