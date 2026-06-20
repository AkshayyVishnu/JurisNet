"""
Qdrant vector store wrapper.

Two collections (both 1024-dim, cosine):
  - content : judgment chunks (L0, L1 facts, L2, L3, ratio)
  - label   : statute provision chunks

Point IDs are deterministic UUID5(chunk_id) so re-indexing upserts in place
(idempotent) rather than duplicating.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.models import (  # noqa: E402
    Distance, FieldCondition, Filter, MatchValue, PayloadSchemaType,
    PointStruct, VectorParams,
)

# Fixed namespace so chunk_id -> point id is stable across runs.
_NS = uuid.UUID("6f1e2a4c-0b3d-4e5a-9c7f-1a2b3c4d5e6f")


def get_client() -> QdrantClient:
    return QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY, timeout=120)


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NS, chunk_id))


def ensure_collections(client: QdrantClient, recreate: bool = False) -> None:
    for name in (config.QDRANT_CONTENT_COLLECTION, config.QDRANT_LABEL_COLLECTION):
        exists = client.collection_exists(name)
        if recreate and exists:
            client.delete_collection(name)
            exists = False
        if not exists:
            client.create_collection(
                name,
                vectors_config=VectorParams(size=config.EMBED_DIM, distance=Distance.COSINE),
            )
        # Payload index on tid so we can filter/scroll by document id.
        try:
            client.create_payload_index(name, field_name="tid",
                                        field_schema=PayloadSchemaType.INTEGER)
        except Exception:  # noqa: BLE001 — already exists
            pass


def upsert(client: QdrantClient, collection: str, records: list[dict], vectors: list[list[float]]) -> None:
    """records: dicts with 'chunk_id' + 'payload'. vectors aligned by index."""
    points = [
        PointStruct(id=point_id(r["chunk_id"]), vector=vec, payload=r["payload"])
        for r, vec in zip(records, vectors)
    ]
    client.upsert(collection_name=collection, points=points, wait=True)


def count(client: QdrantClient, collection: str) -> int:
    return client.count(collection, exact=True).count


def fetch_by_tid(client: QdrantClient, collection: str, tid: int,
                 prefer_type: str = "L0_document") -> dict | None:
    """Return a representative chunk payload for a document (prefers its L0)."""
    pts, _ = client.scroll(
        collection_name=collection,
        scroll_filter=Filter(must=[FieldCondition(key="tid", match=MatchValue(value=int(tid)))]),
        limit=15, with_payload=True,
    )
    if not pts:
        return None
    for p in pts:
        if (p.payload or {}).get("chunk_type") == prefer_type:
            return p.payload
    return pts[0].payload


def search(client: QdrantClient, collection: str, vector: list[float], top_k: int = 20,
           query_filter=None) -> list[dict]:
    res = client.query_points(
        collection_name=collection,
        query=vector,
        limit=top_k,
        with_payload=True,
        query_filter=query_filter,
    ).points
    return [{"id": p.id, "score": p.score, **(p.payload or {})} for p in res]


if __name__ == "__main__":
    c = get_client()
    ensure_collections(c)
    for name in (config.QDRANT_CONTENT_COLLECTION, config.QDRANT_LABEL_COLLECTION):
        print(f"{name}: {count(c, name)} points")
