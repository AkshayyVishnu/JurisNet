"""
Stage C — CPC Orders & Rules ingestion (cleaned).

The raw Orders_Rules/ data has three known defects (see analysis):
  1. doc_id is an unreliable shared placeholder (161831507 on ~298 files) -> we key
     on `identifier`, never doc_id, and assign each rule a stable synthetic tid.
  2. ~17 files have the whole-CPC-act blob as text (>=200K chars) -> dropped.
  3. ~27 files have invalid identifiers (Order > 51; CPC has Orders I-LI) -> dropped.

Output:
  - chunks/rules/<Order_x_Rule_y>.json   one provision chunk per good rule (label side)
  - chunks/_rule_edges.json              judgment -> rule CITES_RULE edges (from cited_by)

This only writes local files; it does NOT touch Qdrant/Neo4j. Run the unified
re-index (03_index) + graph reload (neo4j_store) afterwards.

Run:  python pipeline/04_orders_rules.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zlib
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from chunker import StatuteProvisionChunk  # noqa: E402

BLOB_CHARS = 200000     # text this large is the whole-act blob, not a rule
MAX_ORDER = 51          # CPC has Orders I..LI
RULE_MAX_CHARS = 8000   # cap embed/stored text (keeps core rule; drops verbose state-amendment tail)


def _order_num(identifier: str) -> int:
    m = re.match(r"Order (\d+)", identifier or "")
    return int(m.group(1)) if m else 9999


def _rule_tid(identifier: str) -> int:
    """Stable, unique, NEGATIVE synthetic id (won't collide with real positive doc ids)."""
    return -(zlib.crc32(identifier.encode("utf-8")) & 0x7FFFFFFF)


def _aliases(identifier: str) -> list[str]:
    al = [identifier, f"{identifier} CPC", f"{identifier} of the Code of Civil Procedure"]
    # compact form: "Order 9 Rule 13" -> "O. 9 R. 13"
    m = re.match(r"Order (\d+)(?:\s+Rule\s+(\d+[A-Z]?))?", identifier)
    if m:
        compact = f"O. {m.group(1)}" + (f" R. {m.group(2)}" if m.group(2) else "")
        al.append(compact)
    return list(dict.fromkeys(al))


def run() -> None:
    src = sorted(config.ORDERS_RULES_DIR.glob("*.json"))
    if not src:
        print(f"No files in {config.ORDERS_RULES_DIR}")
        return
    judg_ids = {int(json.loads(p.read_text(encoding="utf-8"), strict=False)["doc_id"])
                for p in config.JUDGMENTS_DIR.glob("*.json")}

    config.CHUNKS_RULES_DIR.mkdir(parents=True, exist_ok=True)

    stats = {"total": len(src), "blob": 0, "bad_id": 0, "empty": 0,
             "wrong_content": 0, "dup_text": 0, "capped": 0, "good": 0, "dup_identifier": 0}
    dropped_ids = {"wrong_content": [], "dup_text": []}
    edges, seen_ids, seen_text = [], set(), set()
    edge_in = edge_total = 0

    for p in src:
        d = json.loads(p.read_text(encoding="utf-8"), strict=False)
        ident = (d.get("identifier") or "").strip()
        text = (d.get("text") or "").strip()

        # ── filters ──
        if not ident or not text:
            stats["empty"] += 1
            continue
        if len(text) >= BLOB_CHARS:
            stats["blob"] += 1
            continue
        if _order_num(ident) > MAX_ORDER:
            stats["bad_id"] += 1
            continue
        # content-type corruption: text is actually a Section / Amendment Act /
        # consolidated-rules stub, not the rule itself (valid-looking identifier).
        head = text[:70].lstrip()
        if (head.startswith("Section ")
                or re.match(r"The Code [Oo]f Civil Procedure \(", head)
                or head.startswith("Rules (Consolidated")):
            stats["wrong_content"] += 1
            dropped_ids["wrong_content"].append(ident)
            continue
        # duplicate text under a different identifier -> keep first, drop rest
        th = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if th in seen_text:
            stats["dup_text"] += 1
            dropped_ids["dup_text"].append(ident)
            continue
        seen_text.add(th)
        if ident in seen_ids:
            stats["dup_identifier"] += 1
            continue
        seen_ids.add(ident)

        if len(text) > RULE_MAX_CHARS:
            text = text[:RULE_MAX_CHARS]
            stats["capped"] += 1

        tid = _rule_tid(ident)
        citedby = [int(c) for c in d.get("cited_by", []) if int(c) in judg_ids]

        chunk = {
            "doc_type": "rule",
            "provision": asdict(StatuteProvisionChunk(
                tid=tid,
                title=ident,
                date="",
                act_name="Code of Civil Procedure, 1908",
                section_ref=ident,
                text=text,
                aliases=_aliases(ident),
                citedby_tids=citedby,
            )),
            "raw_doc_id": d.get("doc_id"),  # kept for provenance only (unreliable)
        }
        out = config.CHUNKS_RULES_DIR / (ident.replace(" ", "_") + ".json")
        out.write_text(json.dumps(chunk, indent=2, ensure_ascii=False), encoding="utf-8")
        stats["good"] += 1

        # ── edges: judgment -> rule (from cited_by) ──
        for c in d.get("cited_by", []):
            edge_total += 1
            if int(c) in judg_ids:
                edge_in += 1
                edges.append({
                    "from_tid": int(c), "from_title": "",
                    "to_tid": tid, "to_title": ident,
                    "rel_type": "CITES_RULE", "citation_type": "rule", "in_corpus": True,
                })

    # dedup edges
    uniq, key_seen = [], set()
    for e in edges:
        k = (e["from_tid"], e["to_tid"])
        if k not in key_seen:
            key_seen.add(k)
            uniq.append(e)
    config.RULE_EDGES_FILE.write_text(json.dumps(uniq, indent=2), encoding="utf-8")

    # ── report ──
    print("=" * 60)
    print("STAGE C — Orders & Rules ingestion (cleaned)")
    print("=" * 60)
    print(f"  source files          : {stats['total']}")
    print(f"  dropped (blob text)   : {stats['blob']}")
    print(f"  dropped (Order>51)    : {stats['bad_id']}")
    print(f"  dropped (empty)       : {stats['empty']}")
    print(f"  dropped (wrong content): {stats['wrong_content']}  {dropped_ids['wrong_content']}")
    print(f"  dropped (dup text)    : {stats['dup_text']}  {dropped_ids['dup_text']}")
    print(f"  dropped (dup ident)   : {stats['dup_identifier']}")
    print(f"  GOOD rule chunks      : {stats['good']}  -> {config.CHUNKS_RULES_DIR}")
    print(f"     of which size-capped: {stats['capped']}")
    print(f"\n  judgment->rule edges  : {len(uniq)} (deduped) "
          f"[{edge_in}/{edge_total} cited_by refs resolved]")
    print(f"  edges file            : {config.RULE_EDGES_FILE}")


if __name__ == "__main__":
    run()
