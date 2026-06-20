"""
JurisNet web API (FastAPI + SSE).

Wraps the existing pipeline and streams real pipeline stages to the frontend:
  understanding -> retrieving -> synthesizing (token stream) -> verifying -> done.

Run:  uvicorn server:app --reload --port 8000

Note: the pipeline (esp. the FTS5 SQLite connection) is single-threaded, so /api/ask
uses an ASYNC generator that runs everything on the main event-loop thread. Fine for
a single-user demo; blocking calls simply hold the loop during a query.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402  (also sets USE_TF=0 before heavy imports)
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from retrieval.hybrid_retriever import HybridRetriever  # noqa: E402
from stores import qdrant_store  # noqa: E402
from agents.query_understanding import understand  # noqa: E402
from agents.synthesis import synthesize_stream  # noqa: E402
from agents import citation_verifier  # noqa: E402

STATE: dict = {}

SUGGESTIONS = [
    "Can an ex-parte decree be set aside if the summons was not duly served?",
    "What is the test for granting a temporary injunction?",
    "When can a plaint be rejected under Order 7 Rule 11 CPC?",
    "What does Order 9 Rule 13 CPC allow?",
    "What is res judicata?",
    "How can a civil suit be transferred under Section 24 CPC?",
]


def _compute_stats(retriever: HybridRetriever) -> dict:
    qc = retriever.qc
    content = qdrant_store.count(qc, config.QDRANT_CONTENT_COLLECTION)
    label = qdrant_store.count(qc, config.QDRANT_LABEL_COLLECTION)
    with retriever.driver.session() as s:
        nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        labels = {r["l"]: r["c"] for r in
                  s.run("MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c").data()}
    return {
        "judgments": labels.get("Judgment", 0),
        "statutes": labels.get("Statute", 0),
        "rules": labels.get("Rule", 0),
        "documents": nodes,
        "vector_chunks": content,
        "label_chunks": label,
        "graph_nodes": nodes,
        "graph_edges": edges,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE["retriever"] = HybridRetriever()
    try:
        STATE["stats"] = _compute_stats(STATE["retriever"])
    except Exception:  # noqa: BLE001 — stats are best-effort
        STATE["stats"] = {}
    yield
    STATE["retriever"].close()


app = FastAPI(title="JurisNet API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)


class AskBody(BaseModel):
    query: str


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/suggestions")
def suggestions():
    return {"suggestions": SUGGESTIONS}


@app.get("/api/architecture")
def architecture():
    return {
        "stats": STATE.get("stats", {}),
        "agents": [
            {"name": "Query Understanding", "desc": "Classifies intent + extracts legal entities to route retrieval."},
            {"name": "Hybrid Retriever", "desc": "Fuses 4 sources (dense vectors, BM25, knowledge graph) with RRF."},
            {"name": "Synthesis", "desc": "Writes an IRAC answer grounded ONLY in retrieved law, with inline citations."},
            {"name": "Citation Verifier", "desc": "Checks every citation against the retrieved set + corpus graph; scores confidence."},
        ],
        "sources": [
            {"name": "Dense vectors", "tech": "Qdrant · voyage-4-large"},
            {"name": "Keyword BM25", "tech": "SQLite FTS5 · legal-token normalized"},
            {"name": "Knowledge graph", "tech": "Neo4j · citation edges"},
            {"name": "Fusion", "tech": "Reciprocal Rank Fusion, intent-weighted"},
        ],
        "guarantee": "Every cited source is verified against the retrieved set and the corpus graph — fabricated citations are flagged.",
        "llm": "Multi-provider (Cerebras · Groq · Gemini) with key rotation + fallback.",
    }


async def _run(query: str):
    t0 = time.time()
    retriever: HybridRetriever = STATE["retriever"]
    try:
        if not query or not query.strip():
            yield _sse("error", {"message": "Empty query."})
            return

        yield _sse("stage", {"name": "understanding", "message": "Understanding your question…"})
        u = understand(query)
        yield _sse("understood", {"intent": u["intent"], "entities": u.get("entities", [])})

        yield _sse("stage", {"name": "retrieving",
                             "message": "Searching judgments, statutes & rules…"})
        results = retriever.retrieve(query, u["intent"], top_k=15)
        items = [{
            "tid": r["tid"], "title": r.get("title", ""),
            "chunk_type": r.get("chunk_type", ""),
            "caution_flag": r.get("caution_flag", False),
            "matched": list((r.get("sources") or {}).keys()),
        } for r in results]
        yield _sse("sources", {"count": len(results), "items": items})

        if not results:
            yield _sse("verified", {"answer": "No relevant material found in the corpus.",
                                    "confidence": 0.0, "out_of_context": [], "fabricated": []})
            yield _sse("done", {"elapsed_s": round(time.time() - t0, 1)})
            return

        yield _sse("stage", {"name": "synthesizing",
                             "message": "Grounding the answer & putting it together…"})
        parts: list[str] = []
        for tok in synthesize_stream(query, results):
            parts.append(tok)
            yield _sse("token", {"text": tok})
        answer = "".join(parts)

        yield _sse("stage", {"name": "verifying", "message": "Verifying every citation…"})
        v = citation_verifier.verify(answer, results, driver=retriever.driver)
        yield _sse("verified", {
            "answer": v["answer"], "confidence": v["confidence"],
            "grounded": v["grounded"], "out_of_context": v["out_of_context"],
            "fabricated": v["fabricated"], "caution_sources": v["caution_sources"],
        })
        yield _sse("done", {"elapsed_s": round(time.time() - t0, 1)})
    except Exception as e:  # noqa: BLE001
        yield _sse("error", {"message": f"{type(e).__name__}: {e}"})


@app.post("/api/ask")
async def ask(body: AskBody):
    return StreamingResponse(
        _run(body.query), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
