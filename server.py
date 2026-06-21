"""
JurisNet web API (FastAPI + SSE) — drives the FULL agentic pipeline.

    Query Agent → Researcher → Checklist Resolver → Auditor → Adjudicator  (LangGraph)

The pipeline has two human-in-the-loop pauses (the Query Agent clarification gate and
the Auditor ❓ loop), implemented as LangGraph interrupts. Over HTTP we use checkpoint +
resume: each /api/ask call runs ONE segment of the graph (keyed by thread_id) and either
finishes with an answer or pauses with a `clarify` event. The client then POSTs the
answer with the same thread_id to resume.

Run:  uvicorn server:app --port 8000

Note: the pipeline (FTS5 SQLite connection) is single-threaded, so /api/ask uses an
ASYNC generator that runs everything on the main event-loop thread (fine single-user).
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402  (also sets USE_TF=0 before heavy imports)
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from retrieval.hybrid_retriever import HybridRetriever  # noqa: E402
from stores import qdrant_store  # noqa: E402
from agents.graph import build_graph  # noqa: E402
from langgraph.types import Command  # noqa: E402
# Fast path (single-shot retrieve → synthesize → verify):
from agents.query_understanding import understand  # noqa: E402
from agents.synthesis import synthesize_stream  # noqa: E402
from agents import citation_verifier  # noqa: E402

STATE: dict = {}

SUGGESTIONS = [
    "Can a defendant set aside an ex-parte decree if the summons was not served?",
    "What is the test for granting a temporary injunction under Order 39 Rule 1 CPC?",
    "What does Order 9 Rule 13 CPC allow?",
    "What is res judicata under Section 11 CPC?",
    "My landlord kept my deposit and is trying to evict me after I complained about a leak. What can I do?",
    "How can a civil suit be transferred under Section 24 CPC?",
]

# Stage labels for the pipeline nodes (the internal 'advance' cursor node is hidden).
STAGE_LABEL = {
    "query_agent": "Understanding & splitting your question…",
    "researcher": "Searching judgments, statutes & rules…",
    "checklist": "Resolving the statutory checklist…",
    "auditor": "Checking the facts against each condition…",
    "adjudicator": "Writing the grounded answer…",
}


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
        "judgments": labels.get("Judgment", 0), "statutes": labels.get("Statute", 0),
        "rules": labels.get("Rule", 0), "documents": nodes,
        "vector_chunks": content, "label_chunks": label,
        "graph_nodes": nodes, "graph_edges": edges,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE["retriever"] = HybridRetriever()
    STATE["graph"] = build_graph(retriever=STATE["retriever"])  # one shared graph + retriever
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
    query: str | None = None
    thread_id: str | None = None
    resume: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sources_from_evidence(evidence: dict) -> list[dict]:
    """Flatten {sq_id: [chunks]} → unique source items (by tid), preserving order."""
    seen, items = set(), []
    for chunks in (evidence or {}).values():
        for r in chunks:
            tid = r.get("tid")
            if tid in seen:
                continue
            seen.add(tid)
            items.append({
                "tid": tid, "title": r.get("title", ""),
                "chunk_type": r.get("chunk_type", ""),
                "caution_flag": r.get("caution_flag", False),
                "matched": list((r.get("sources") or {}).keys()),
            })
    return items


def _adjudication_dict(adj) -> dict:
    if adj is None:
        return {}
    return adj.model_dump() if hasattr(adj, "model_dump") else dict(adj)


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
            {"name": "Query Agent", "desc": "Splits the query into sub-questions, classifies each, and asks you to clarify if it's ambiguous."},
            {"name": "Researcher", "desc": "Retrieves evidence (dense + BM25 + graph) and regex-extracts the cited provisions."},
            {"name": "Checklist Resolver", "desc": "Turns each provision into a checklist of statutory conditions (cached)."},
            {"name": "Auditor", "desc": "Checks each condition against your facts (✅/❌/❓) and asks for any missing fact."},
            {"name": "Adjudicator", "desc": "Writes the final grounded answer with citations, resolving any conflicts."},
        ],
        "sources": [
            {"name": "Dense vectors", "tech": "Qdrant · voyage-4-large"},
            {"name": "Keyword BM25", "tech": "SQLite FTS5 · legal-token normalized"},
            {"name": "Knowledge graph", "tech": "Neo4j · citation edges"},
            {"name": "Fusion", "tech": "Reciprocal Rank Fusion"},
        ],
        "guarantee": "No agent guesses ahead of evidence — every conclusion traces to a provision whose conditions were audited against your facts.",
        "llm": "Groq (LLaMA-3.3-70B) with round-robin key rotation; Gemini fallback.",
    }


async def _run_fast(query: str):
    """Fast path: understand → hybrid retrieve → stream synthesis → verify citations."""
    t0 = time.time()
    retriever: HybridRetriever = STATE["retriever"]
    try:
        if not query or not query.strip():
            yield _sse("error", {"message": "Empty query."})
            return
        yield _sse("stage", {"name": "understanding", "message": "Understanding your question…"})
        u = understand(query)
        yield _sse("understood", {"intent": u["intent"], "entities": u.get("entities", [])})

        yield _sse("stage", {"name": "retrieving", "message": "Searching judgments, statutes & rules…"})
        results = retriever.retrieve(query, u["intent"], top_k=15)
        items = [{"tid": r["tid"], "title": r.get("title", ""), "chunk_type": r.get("chunk_type", ""),
                  "caution_flag": r.get("caution_flag", False),
                  "matched": list((r.get("sources") or {}).keys())} for r in results]
        yield _sse("sources", {"count": len(results), "items": items})
        if not results:
            yield _sse("verified", {"answer": "No relevant material found in the corpus.",
                                    "confidence": 0.0, "out_of_context": [], "fabricated": []})
            yield _sse("done", {"elapsed_s": round(time.time() - t0, 1)})
            return

        yield _sse("stage", {"name": "synthesizing", "message": "Grounding the answer & putting it together…"})
        parts: list[str] = []
        for tok in synthesize_stream(query, results):
            parts.append(tok)
            yield _sse("token", {"text": tok})
        answer = "".join(parts)

        yield _sse("stage", {"name": "verifying", "message": "Verifying every citation…"})
        v = citation_verifier.verify(answer, results, driver=retriever.driver)
        yield _sse("verified", {"answer": v["answer"], "confidence": v["confidence"],
                                "grounded": v["grounded"], "out_of_context": v["out_of_context"],
                                "fabricated": v["fabricated"], "caution_sources": v["caution_sources"]})
        yield _sse("done", {"elapsed_s": round(time.time() - t0, 1)})
    except Exception as e:  # noqa: BLE001
        yield _sse("error", {"message": f"{type(e).__name__}: {e}"})


async def _run_deep(body: AskBody):
    t0 = time.time()
    graph = STATE["graph"]
    tid = body.thread_id or uuid.uuid4().hex
    cfg = {"configurable": {"thread_id": tid}}
    yield _sse("meta", {"thread_id": tid})

    if body.resume is not None:
        graph_input = Command(resume=body.resume)
    elif body.query and body.query.strip():
        graph_input = {"raw_query": body.query.strip()}
    else:
        yield _sse("error", {"message": "Empty query."})
        return

    try:
        interrupted = False
        for chunk in graph.stream(graph_input, cfg, stream_mode="updates"):
            if "__interrupt__" in chunk:
                intr = chunk["__interrupt__"][0].value
                yield _sse("clarify", {"thread_id": tid, **intr})
                interrupted = True
                break
            for node, upd in chunk.items():
                if node in STAGE_LABEL:
                    yield _sse("stage", {"name": node, "message": STAGE_LABEL[node]})
                if node == "query_agent" and upd and upd.get("sub_questions"):
                    yield _sse("subquestions", {"items": [
                        {"id": s.id, "text": s.text, "query_type": s.query_type.value,
                         "pipeline": s.recommended_pipeline}
                        for s in upd["sub_questions"]]})
                if node == "researcher" and upd:
                    if upd.get("evidence"):
                        items = _sources_from_evidence(upd["evidence"])
                        yield _sse("sources", {"count": len(items), "items": items})
                    if upd.get("surfaced"):
                        statutes = sorted({s for v in upd["surfaced"].values() for s in v})
                        yield _sse("surfaced", {"statutes": statutes})

        if not interrupted:
            st = graph.get_state(cfg).values
            yield _sse("answer", _adjudication_dict(st.get("adjudication")))
            yield _sse("done", {"elapsed_s": round(time.time() - t0, 1)})
    except Exception as e:  # noqa: BLE001
        yield _sse("error", {"message": f"{type(e).__name__}: {e}"})


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@app.post("/api/ask")
async def ask(body: AskBody):
    """Fast streaming path."""
    return StreamingResponse(_run_fast(body.query or ""), media_type="text/event-stream",
                             headers=_SSE_HEADERS)


@app.post("/api/deep")
async def deep(body: AskBody):
    """Full agentic pipeline (clarify/resume via thread_id)."""
    return StreamingResponse(_run_deep(body), media_type="text/event-stream",
                             headers=_SSE_HEADERS)
