"""
Citation Verifier — the hallucination guard (the Mata-v-Avianca safeguard).

Every [tid …] the Synthesis agent emits must trace to a chunk that was ACTUALLY
retrieved (and exists in the corpus). This agent:
  • extracts every cited tid from the answer,
  • classifies each as grounded / out-of-context / fabricated,
  • annotates ungrounded citations inline with a ⚠ marker,
  • returns a confidence score + the cited-but-flagged sets.

No LLM call — pure verification against the retrieved set + the graph.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Strip zero-width / non-breaking chars some models inject into "[t​id …]".
_ZW = dict.fromkeys(map(ord, "​‌‍﻿ "), None)
# Bracket-agnostic: models emit [tid 12], 【tid 12】, (tid 12), or bare "tid 12".
_TID_RE = re.compile(r"(?:[\[\(【〔]\s*)?tid\s*[:#]?\s*(-?\d+)\s*[\]\)】〕]?", re.IGNORECASE)


def _clean(text: str) -> str:
    return (text or "").translate(_ZW)


def extract_cited_tids(answer: str) -> list[int]:
    return [int(m) for m in _TID_RE.findall(_clean(answer))]


def _tids_in_corpus(tids: set[int], driver) -> set[int]:
    """Which of these tids exist as nodes in the graph (whole corpus)."""
    if not tids or driver is None:
        return set()
    with driver.session() as s:
        rows = s.run("MATCH (n) WHERE n.tid IN $tids RETURN n.tid AS tid",
                     tids=list(tids)).data()
    return {int(r["tid"]) for r in rows}


def _annotate(answer: str, ungrounded: set[int]) -> str:
    """Tag ungrounded citations inline so the reader sees what isn't verified."""
    def repl(m):
        tid = int(m.group(1))
        return f"[tid {tid} ⚠UNVERIFIED]" if tid in ungrounded else f"[tid {tid}]"
    return _TID_RE.sub(repl, _clean(answer))


def verify(answer: str, results: list[dict], driver=None) -> dict:
    cited = set(extract_cited_tids(answer))
    retrieved = {int(r["tid"]) for r in results}
    grounded = cited & retrieved
    ungrounded = cited - retrieved

    # Distinguish "real case but not in the retrieved set" from "doesn't exist at all".
    in_corpus = _tids_in_corpus(ungrounded, driver)
    out_of_context = ungrounded & in_corpus          # exists, but wasn't retrieved
    fabricated = ungrounded - in_corpus              # not in corpus -> hallucinated

    confidence = round(len(grounded) / len(cited), 2) if cited else 0.0
    caution = sorted(int(r["tid"]) for r in results
                     if r.get("caution_flag") and int(r["tid"]) in grounded)

    return {
        "answer": _annotate(answer, ungrounded),
        "confidence": confidence,
        "cited": sorted(cited),
        "grounded": sorted(grounded),
        "out_of_context": sorted(out_of_context),
        "fabricated": sorted(fabricated),
        "caution_sources": caution,
        "ok": not ungrounded,
    }


def report(v: dict) -> str:
    lines = [f"citation confidence: {v['confidence']:.0%}  "
             f"({len(v['grounded'])}/{len(v['cited'])} grounded)"]
    if v["out_of_context"]:
        lines.append(f"  ⚠ cited but not retrieved: {v['out_of_context']}")
    if v["fabricated"]:
        lines.append(f"  ❌ FABRICATED (not in corpus): {v['fabricated']}")
    if v["caution_sources"]:
        lines.append(f"  ⚠ caution (possibly overruled/doubted): {v['caution_sources']}")
    return "\n".join(lines)
