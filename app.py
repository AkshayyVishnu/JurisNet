"""
JurisNet CLI — ask a civil-law question, get a grounded, cited answer.

Pipeline:  query -> understand (intent) -> hybrid retrieve -> synthesize -> print.

Run:
  python app.py "Can an ex-parte decree be set aside if summons was not served?"
  python app.py            # interactive
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from retrieval.hybrid_retriever import HybridRetriever  # noqa: E402
from agents.query_understanding import understand  # noqa: E402
from agents.synthesis import synthesize  # noqa: E402


def answer(query: str, retriever: HybridRetriever, top_k: int = 15) -> None:
    t0 = time.time()
    u = understand(query)
    intent = u["intent"]
    print(f"\n[intent: {intent}]  entities: {u['entities']}")

    results = retriever.retrieve(query, intent, top_k=top_k)
    print(f"[retrieved {len(results)} docs in {time.time()-t0:.1f}s]")
    if not results:
        print("\nNo relevant material found.")
        return

    print("\n" + "=" * 72)
    print(synthesize(query, results))
    print("=" * 72)
    print("\nSOURCES:")
    for r in results[:10]:
        flag = " ⚠" if r.get("caution_flag") else ""
        print(f"  [tid {r['tid']}] {r.get('title','')[:60]} ({r['chunk_type']}){flag}")
    print(f"\n[total {time.time()-t0:.1f}s]")


def main() -> None:
    q = " ".join(sys.argv[1:]).strip()
    retriever = HybridRetriever()
    try:
        if q:
            answer(q, retriever)
        else:
            print("JurisNet — ask a civil-law question (blank line to quit).")
            while True:
                q = input("\n> ").strip()
                if not q:
                    break
                answer(q, retriever)
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
