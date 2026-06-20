"""
Phase 2 — Embedding & Indexing.

Reads chunk files (Stage A/B output) -> embeds with voyage-4-large -> upserts to
Qdrant (content + label collections) -> indexes SQLite FTS5. Neo4j graph load is
pipeline/03b_graph.py.

Idempotent: deterministic point IDs mean re-running after more Stage B docs finish
just upserts the new chunks (L1/L3/ratio) without duplicating L0/L2.

Run:
  python pipeline/03_index.py --limit 50      # smoke test on first 50 chunks/collection
  python pipeline/03_index.py                 # full index
  python pipeline/03_index.py --recreate      # drop + rebuild collections first
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hashlib  # noqa: E402
import sqlite3  # noqa: E402
import struct  # noqa: E402

import config  # noqa: E402
from stores import qdrant_store  # noqa: E402
from legal_fts5 import LegalFTS5  # noqa: E402
from llm_keys import VOYAGE_POOL, _is_rate_limit  # noqa: E402
import voyageai  # noqa: E402

# Persistent embedding cache: sha1(text) -> vector. Survives --recreate so we
# NEVER re-embed text we've already embedded (re-runs only embed new/changed chunks).
EMBED_CACHE_PATH = config.ROOT / "embed_cache.db"

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:  # noqa: BLE001
    pass

CONTENT = config.QDRANT_CONTENT_COLLECTION
LABEL = config.QDRANT_LABEL_COLLECTION


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"), strict=False)


# ─────────────────────────────────────────────
# Chunk reader — one record per embeddable chunk
# ─────────────────────────────────────────────

def _rec(collection, chunk_id, chunk_type, tid, text, **extra) -> dict:
    payload = {"tid": tid, "chunk_type": chunk_type, "text": text, **extra}
    return {"collection": collection, "chunk_id": chunk_id, "text": text, "payload": payload}


def iter_chunks():
    # Judgments -> content collection
    for p in sorted(config.CHUNKS_JUDGMENTS_DIR.glob("*.json")):
        d = _load(p)
        l0 = d["l0"]
        tid, title = l0["tid"], l0["title"]
        meta = {"title": title, "court": l0.get("court", ""), "date": l0.get("date", ""),
                "authority_score": l0.get("authority_score", 0.7),
                "disposition": l0.get("disposition", "")}
        if l0.get("text"):
            yield _rec(CONTENT, f"{tid}:L0", "L0_document", tid, l0["text"], **meta)
        for c in d.get("l1_sections", []):
            yield _rec(CONTENT, f"{tid}:L1:{c['section_type']}", "L1_section", tid, c["text"],
                       section_type=c["section_type"], **meta)
        for c in d.get("l2_paragraphs", []):
            yield _rec(CONTENT, f"{tid}:L2:{c['para_id']}", "L2_paragraph", tid, c["text"],
                       para_id=c["para_id"], **meta)
        for c in d.get("l3_atomic", []):
            yield _rec(CONTENT, f"{tid}:L3:{c['para_id']}:{c['sentence_index']}", "L3_atomic", tid,
                       c["text"], para_id=c["para_id"], **meta)
        for i, c in enumerate(d.get("ratio_chunks", [])):
            yield _rec(CONTENT, f"{tid}:RATIO:{i}", "ratio", tid, c["text"],
                       authority_score=c.get("authority_score", meta["authority_score"]),
                       title=title, court=meta["court"], date=meta["date"],
                       disposition=meta["disposition"])

    # Provisions + Rules -> label collection (both are provision-like)
    def _provision_rec(d, chunk_type, suffix):
        pv = d["provision"]
        tid = pv["tid"]
        aliases = "; ".join(pv.get("aliases", []))
        embed_text = f"{pv['section_ref']} {pv['act_name']}. {aliases}. {pv['text']}".strip()
        return _rec(LABEL, f"{tid}:{suffix}", chunk_type, tid, embed_text,
                    title=pv["title"], section_ref=pv["section_ref"], act_name=pv["act_name"],
                    aliases=pv.get("aliases", []))

    for p in sorted(config.CHUNKS_PROVISIONS_DIR.glob("*.json")):
        yield _provision_rec(_load(p), "statute_provision", "STATUTE")

    if config.CHUNKS_RULES_DIR.exists():  # Stage C
        for p in sorted(config.CHUNKS_RULES_DIR.glob("*.json")):
            yield _provision_rec(_load(p), "rule_provision", "RULE")


# ─────────────────────────────────────────────
# Embedding cache + voyage-4-large (key rotation, batched, retry)
# ─────────────────────────────────────────────

class EmbedCache:
    """sha1(text) -> 1024-float vector, stored as packed float32 in SQLite."""

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("CREATE TABLE IF NOT EXISTS emb (h TEXT PRIMARY KEY, v BLOB)")
        self.conn.commit()

    def get_many(self, hashes: list[str]) -> dict[str, list[float]]:
        out, cur = {}, self.conn.cursor()
        uniq = list(set(hashes))
        for i in range(0, len(uniq), 800):
            block = uniq[i:i + 800]
            q = "SELECT h, v FROM emb WHERE h IN (%s)" % ",".join("?" * len(block))
            for h, v in cur.execute(q, block):
                out[h] = list(struct.unpack(f"{len(v) // 4}f", v))
        return out

    def put_many(self, items: list[tuple[str, list[float]]]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO emb (h, v) VALUES (?, ?)",
            [(h, struct.pack(f"{len(vec)}f", *vec)) for h, vec in items],
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# The bare VOYAGE_API_KEY org has billing enabled (2000 RPM, high TPM), so we
# embed through it alone with large batches. Free keys would just 429 and slow
# the rotation. Voyage caps a request at 1000 inputs / ~120K tokens.
_PAID_KEY = config.VOYAGE_API_KEY
_TOKEN_BUDGET = 80000    # est tokens/request (chars/4 undershoots real; Voyage cap 120K)
_MAX_TEXTS = 1000        # Voyage hard cap on inputs per request
_MAX_ATTEMPTS = 8        # only transient/network retries expected on paid tier


def _est_tokens(text: str) -> int:
    return len(text) // 4 + 1


def _token_batches(items: list[tuple[int, str]]):
    """Yield batches of (idx, text) capped at ~_TOKEN_BUDGET tokens / _MAX_TEXTS inputs."""
    batch, toks = [], 0
    for idx, text in items:
        tt = _est_tokens(text)
        if batch and (toks + tt > _TOKEN_BUDGET or len(batch) >= _MAX_TEXTS):
            yield batch
            batch, toks = [], 0
        batch.append((idx, text))
        toks += tt
    if batch:
        yield batch


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed one batch via voyage-4-large on the paid key (rotation fallback if unset)."""
    delay = 5.0
    last = None
    for attempt in range(_MAX_ATTEMPTS):
        key = _PAID_KEY or VOYAGE_POOL.next()
        try:
            res = voyageai.Client(api_key=key).embed(
                texts, model=config.VOYAGE_DOC_MODEL,
                input_type="document", output_dimension=config.EMBED_DIM)
            return res.embeddings
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 30)
    raise last or RuntimeError("embed failed")


def embed_texts(cache: EmbedCache, texts: list[str]) -> list[list[float]]:
    """Return vectors for texts, embedding only cache misses (token-aware batches)."""
    hashes = [_hash(t) for t in texts]
    cached = cache.get_many(hashes)
    result: list = [cached.get(h) for h in hashes]

    miss = [(i, texts[i]) for i, v in enumerate(result) if v is None]
    if not miss:
        print(f"    {len(texts)} chunks all cached (0 embedded)")
        return result

    print(f"    {len(texts)-len(miss)} cached, embedding {len(miss)} new")
    done = 0
    for batch in _token_batches(miss):
        vecs = _embed_batch([t for _, t in batch])
        cache.put_many([(hashes[idx], vec) for (idx, _), vec in zip(batch, vecs)])
        for (idx, _), vec in zip(batch, vecs):
            result[idx] = vec
        done += len(batch)
        print(f"      embedded {done}/{len(miss)}")
    return result


# ─────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────

def run(recreate: bool, limit: int | None) -> None:
    config.validate()
    qc = qdrant_store.get_client()
    qdrant_store.ensure_collections(qc, recreate=recreate)
    # Rebuild FTS5 from scratch each run: its INSERTs aren't idempotent, so a fresh
    # build avoids duplicate rows when re-running after more Stage B docs finish.
    if config.FTS5_DB_PATH.exists():
        config.FTS5_DB_PATH.unlink()
    fts = LegalFTS5(str(config.FTS5_DB_PATH))
    fts.initialize()
    cache = EmbedCache(EMBED_CACHE_PATH)
    print(f"voyage keys: {len(VOYAGE_POOL)}  | embed cache: {EMBED_CACHE_PATH.name}")

    # Bucket records by collection.
    buckets: dict[str, list[dict]] = {CONTENT: [], LABEL: []}
    for r in iter_chunks():
        buckets[r["collection"]].append(r)
    if limit:
        buckets = {k: v[:limit] for k, v in buckets.items()}

    t0 = time.time()
    for collection, records in buckets.items():
        if not records:
            continue
        print(f"\n[{collection}] {len(records)} chunks")
        # Embed + upsert to Qdrant in chunks of 1000 to bound memory.
        for i in range(0, len(records), 1000):
            block = records[i:i + 1000]
            vecs = embed_texts(cache, [r["text"] for r in block])
            qdrant_store.upsert(qc, collection, block, vecs)
            print(f"  upserted {min(i+1000, len(records))}/{len(records)} to Qdrant")
        # FTS5 (index the same text; normalization handled inside).
        fts.index_batch([
            {"tid": r["payload"]["tid"], "chunk_id": r["chunk_id"],
             "chunk_type": r["payload"]["chunk_type"], "text": r["text"]}
            for r in records
        ])
        print(f"  indexed {len(records)} into FTS5")

    print("\n" + "=" * 60)
    print("INDEXING COMPLETE")
    print(f"  Qdrant content: {qdrant_store.count(qc, CONTENT)}")
    print(f"  Qdrant label  : {qdrant_store.count(qc, LABEL)}")
    print(f"  elapsed       : {time.time()-t0:.0f}s")
    fts.close()
    cache.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--recreate", action="store_true", help="drop + recreate collections first")
    ap.add_argument("--limit", type=int, default=None, help="cap chunks per collection (smoke test)")
    args = ap.parse_args()
    run(args.recreate, args.limit)
