# JurisNet — Status

> MVP is complete and runs end-to-end: `python app.py "your civil-law question"`
> Last updated: 2026-06-20

## ✅ Done

**Corpus (1,071 docs)**
- 637 judgments + 142 CPC statute sections + 292 CPC Orders/Rules (Stage C, cleaned of 39 junk files)

**Pipeline**
- Stage A — structural chunking (L0 summary + L2 paragraphs + statute/rule provisions + citation graph) — `pipeline/01_chunk.py`
- Stage B — LLM enrichment (L0 headnote, L1 facts, ratio, L3 atomic, disposition) — `pipeline/02_enrich.py`
  - L3 coverage **88%** (77 hard docs left; not on critical path)
- Stage C — Orders/Rules ingestion — `pipeline/04_orders_rules.py`
- Indexing — embed (voyage-4-large, cached) → Qdrant + FTS5 — `pipeline/03_index.py`

**Stores (live)**
- Qdrant Cloud: 30,564 content + 434 label vectors
- SQLite FTS5: full corpus, legal-token normalized
- Neo4j Aura: 1,071 nodes + 6,776 edges (judgment↔statute↔rule)

**Agents (4-agent MVP)**
- Query Understanding (intent) — `agents/query_understanding.py`
- Hybrid Retriever (4 sources + RRF) — `retrieval/hybrid_retriever.py`
- Synthesis (IRAC + inline `[tid]` citations) — `agents/synthesis.py`
- Citation Verifier (hallucination guard + confidence) — `agents/citation_verifier.py`
- End-to-end CLI — `app.py`

**Infra**
- Multi-provider key rotation (Voyage / Cerebras / Groq / Gemini) — `llm_keys.py`
- Central config — `config.py`
- Persistent embedding cache (no re-embedding)

## ⬜ Left

**Quick / housekeeping**
- Refresh `requirements.txt` (litellm, groq, google-genai, cerebras path) for clean setup elsewhere
- L3 backfill — the remaining 77 docs (deferred; only the Groundedness Critic needs L3)

**Decisions**
- Architecture: keep the 4-agent line **vs.** pivot to the `agents`-branch design
  (Query Agent → Researcher → Checklist Resolver → Auditor → Adjudicator) with this RAG layer as its `rag/` backend

**Next phases**
- Phase 5 — Eval harness: gold-set Recall@10 / MRR + citation accuracy
- LangGraph wiring (`agents/graph.py`) — currently a sequential orchestrator in `app.py`
- Deferred agents (full vision): Decomposer, Counsel pair, Validity Checker, Groundedness Critic (NLI),
  Conflict Resolver, Reflection, Output Formatter
- Optional: Langfuse tracing, deeper Stage A segmentation fix for degenerate docs
