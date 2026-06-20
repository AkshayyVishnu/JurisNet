# 🛠️ JurisNet — Implementation Plan & To-Do

> Created: Session 2 — June 20, 2026
> Scope: Take the 4 built modules → a working end-to-end legal RAG with **4 agents**.
> Priority order (per user): **Chunking → Embedding → Retrieval → Pipeline**, agents last.
> Build the rest of the 13 agents in later phases.

---

## 0. Guiding Principles

- **Vertical slice first.** Get ONE query to flow end-to-end (chunk → index → retrieve → answer → verify) before broadening. A thin working pipeline beats a wide half-built one.
- **Every phase ends in a CHECKPOINT** with concrete pass/fail criteria. Do not start the next phase until the checkpoint is green.
- **Reuse what's built.** `chunker.py`, `graph_ranker.py`, `query_embedder.py`, `legal_fts5.py` are done and tested — the new code wires them to real stores.
- **Corpus**: 779 docs (637 judgments + 142 statutes) in `LEGAL_DATA/`.

---

## 1. The 4 Starter Agents (MVP)

A minimal but complete pipeline: **Understand → Retrieve → Synthesize → Verify**.

| # | Agent | Role | Model (free tier) | Built on |
|---|-------|------|-------------------|----------|
| 1 | **Query Understanding** | Classify intent + extract entities + set `query_mode` | Groq Llama 3.1 8B | feeds `query_embedder.embed_query()` |
| 2 | **Hybrid Retriever** | Run all 4 sources, fuse with RRF, return top-K chunks | no LLM (tool agent) | `query_embedder` + `graph_ranker` + stores |
| 3 | **Synthesis** | Write IRAC answer with inline citations from retrieved context | Gemini 2.5 Flash / Cerebras 70B | retrieved chunks |
| 4 | **Citation Verifier** | MANDATORY guardrail — every cited case/section must exist in corpus + be grounded | Groq 8B + Neo4j/FTS5 lookup | stores |

> The Hybrid Retriever collapses Tier-2's 3 specialists (Statute / Precedent / Graph) into one for the MVP. The adversarial Counsel pair, Decomposer, Validity Checker, Groundedness Critic, Conflict Resolver, Reflection, Formatter come **later**.

### End-to-end flow
```
User query
   │
   ▼
[1] Query Understanding ──► {intent, entities, query_mode}
   │
   ▼
    query_embedder.embed_query()  ──► QueryPlan (vector + sources + rrf_weights)
   │
   ▼
[2] Hybrid Retriever
      ├─ Qdrant content collection   (vector search)
      ├─ Qdrant label collection     (vector search, same vector)
      ├─ SQLite FTS5                  (BM25, legal-normalized)
      └─ Neo4j                        (1–2 hop citation traversal → graph_ranker.score_node)
      └─► graph_ranker.reciprocal_rank_fusion() ──► top-K ranked chunks
   │
   ▼
[3] Synthesis ──► IRAC answer + inline [tid] citations
   │
   ▼
[4] Citation Verifier ──► verified answer (+ flags / confidence / disclaimer)
```

---

## 2. Target Repo Layout

```
E:/IIT-kgp/
├── LEGAL_DATA/              # existing raw JSON (779 docs)
├── chunker.py              # ✅ built
├── graph_ranker.py         # ✅ built
├── query_embedder.py       # ✅ built (v2)
├── legal_fts5.py           # ✅ built
├── config.py               # NEW — paths, model names, dims, store URLs
├── requirements.txt        # NEW
├── docker-compose.yml      # NEW — Qdrant + Neo4j
├── .env.example            # NEW — API keys (VOYAGE, GROQ, GEMINI)
├── pipeline/
│   ├── 01_chunk.py         # NEW — run chunker over corpus → chunks/
│   ├── 02_enrich.py        # NEW — wire 3 LLM TODOs (Phase 1B, optional)
│   └── 03_index.py         # NEW — embed + write to all 3 stores
├── stores/
│   ├── qdrant_store.py     # NEW — collection mgmt, upsert, search
│   ├── neo4j_store.py      # NEW — graph load + traversal
│   └── fts5_store.py       # NEW — thin wrapper around legal_fts5.py (persistent db)
├── retrieval/
│   └── hybrid_retriever.py # NEW — orchestrate 4 sources + RRF fusion
├── agents/
│   ├── query_understanding.py
│   ├── synthesis.py
│   ├── citation_verifier.py
│   └── graph.py            # NEW — LangGraph wiring of the 4 agents
├── app.py                  # NEW — CLI entrypoint (ask a question)
├── eval/
│   ├── gold_set.jsonl      # NEW — ~20 hand-written Q→expected-doc pairs
│   └── run_eval.py         # NEW — retrieval + answer metrics
├── chunks/                 # chunker output (gitignored)
│   ├── judgments/          #   per-subdir (chunk_directory doesn't recurse)
│   └── provisions/         #   + merged _citation_edges.json at chunks/ root
└── tests/                  # pytest unit + integration tests
```

---

## 3. Phased Plan with Checkpoints

### ── PHASE 0 — Environment & Infra ──
**Goal:** all dependencies installed, both DB containers up, all built modules importable.

Deliverables:
- [ ] `requirements.txt` — `qdrant-client`, `neo4j`, `voyageai`, `sentence-transformers`, `langgraph`, `litellm`, `groq`, `google-genai`, `pytest`, `python-dotenv`, `numpy`
- [ ] `docker-compose.yml` — Qdrant (`:6333`) + Neo4j Community (`:7687` / `:7474`)
- [ ] `config.py` — central constants: `EMBED_DIM=1024`, model names, collection names (`content`, `label`), store URLs, corpus path
- [ ] `.env.example` + `.env` (gitignored) for `VOYAGE_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`

**✅ CHECKPOINT 0** — run and confirm:
```bash
docker compose up -d && docker ps          # qdrant + neo4j both "Up"
python -c "import qdrant_client, neo4j, voyageai, sentence_transformers, langgraph; print('deps OK')"
python -c "from query_embedder import load_local_nano; m=load_local_nano(); print('nano dim:', len(m.encode('test')))"
```
PASS = all three print success and nano embedding dim is reported (catches the voyage-4-nano availability risk early).

---

### ── PHASE 1 — Chunking (PRIORITY) ──
**Goal:** turn 779 raw JSON docs into structured chunk files on disk.

#### Phase 1A — Structural chunking (no LLM)
> ⚠️ **`chunk_directory` does NOT recurse** (`chunker.py:583` uses `os.listdir`, skips non-`.json`). `LEGAL_DATA/` holds only the subdirs `judgments/` + `provisions/`, so a single `chunk_directory("LEGAL_DATA", ...)` call processes **zero files**. It also writes edges to a fixed `out_dir/_citation_edges.json` (`chunker.py:607`) — calling it twice into the same dir overwrites the first edge file.

Deliverables:
- [ ] `pipeline/01_chunk.py` — call `chunk_directory` **once per subdir** into **separate out dirs**:
  - `chunk_directory("LEGAL_DATA/judgments", "chunks/judgments")`
  - `chunk_directory("LEGAL_DATA/provisions", "chunks/provisions")`
  - then **merge** `chunks/judgments/_citation_edges.json` + `chunks/provisions/_citation_edges.json` → `chunks/_citation_edges.json` (so #2 above can't clobber)
- [ ] `.gitignore` entry for `chunks/`

**✅ CHECKPOINT 1A** — verify:
```bash
python pipeline/01_chunk.py
```
- [ ] `chunks/judgments/` == 637 doc files + 1 `_citation_edges.json`; `chunks/provisions/` == 142 doc files + 1 `_citation_edges.json`
- [ ] Merged `chunks/_citation_edges.json` contains the judgments' edges (non-empty)
- [ ] Spot-check a judgment: `l0`, `l1_sections`, `l2_paragraphs` all non-empty
- [ ] Spot-check a statute: produces exactly ONE `StatuteProvisionChunk`, **not split** (provisos intact)
- [ ] Aggregate: sum `total_chunks` from both `chunk_directory` return dicts (~15–50 per judgment → expect ~15–25K chunks). Note: the returned `total_chunks` excludes `issue_held` pairs (a Phase 1B TODO).
- [ ] Assert: every chunk text starts with a `[breadcrumb]`
- [ ] Log any docs that produced 0 L2/L3 chunks (the known "single-paragraph old judgment" issue)

#### Phase 1B — LLM enrichment (the 3 TODOs) — *can run after pipeline is live*
Deliverables:
- [ ] `pipeline/02_enrich.py` — batched LLM calls (Groq/Cerebras via LiteLLM):
  - Ratio/obiter tagging → fills `RatioChunk`
  - Issue-Held extraction → fills `IssueHeldPair`
  - Citation relationship classification → types `CitationEdge` (FOLLOWED/RELIED_ON/DISTINGUISHED/OVERRULED)
- [ ] Heuristic fallback when LLM unavailable (e.g. last "Held" paragraph = ratio) so the pipeline never blocks on this

**✅ CHECKPOINT 1B** — on a 10-doc sample: ratio chunks present, issue-held pairs parse as valid JSON, citation edges carry a `rel_type` ≠ raw `CITES`. Quota note: 637 judgments × ~3.5 calls ≈ 2,200 calls (one Cerebras afternoon).

> **Decision:** ship Phase 1A → continue to Phase 2/3 on structural chunks; run 1B in parallel and re-index enriched chunks later. Do **not** block the vertical slice on 1B.

---

### ── PHASE 2 — Embedding & Indexing (PRIORITY) ──
**Goal:** chunks loaded into all 3 stores; corpus is queryable at the storage layer.

Deliverables:
- [ ] `stores/qdrant_store.py` — create 2 collections (`content`, `label`, size=1024, cosine); `upsert(chunks)`; `search(vector, collection, top_k)`
- [ ] `stores/fts5_store.py` — persistent SQLite (not `:memory:`); use `legal_fts5.LegalFTS5.index_batch()`
- [ ] `stores/neo4j_store.py` — load nodes (one per `tid` with court/date/authority) + typed edges from `CitationEdge` and statute `citedby`; expose `traverse(seed_tids, max_hops)` returning `GraphNode`s
- [ ] `pipeline/03_index.py` — orchestrates: read `chunks/judgments/` + `chunks/provisions/` (and merged `chunks/_citation_edges.json`) → embed content+label text with `query_embedder.embed_documents_large()` (voyage-4-large) → upsert Qdrant → index FTS5 → load Neo4j

**✅ CHECKPOINT 2** — verify each store independently:
- [ ] Qdrant `content` point count ≈ total embeddable chunks; `label` count ≈ statute count; both report `dim == 1024`
- [ ] FTS5 row count == total text chunks; a normalized query (`section_302_ipc`) returns hits
- [ ] Neo4j: `MATCH (n) RETURN count(n)` == 779 nodes; `MATCH ()-[r]->() RETURN count(r)` > 0; statute `citedby` edges present
- [ ] **Smoke search**: embed `"murder under Section 302"` with nano → Qdrant content search returns ≥1 plausible result
- [ ] Dimension guard: assert query `truncate_dim` (1024) == collection dim (mismatch silently breaks search — see PROJECT_MEMORY known issue)

---

### ── PHASE 3 — Retrieval Engine (PRIORITY) ──
**Goal:** one function: query string → fused, ranked list of **documents** (then fetch their best chunks).

> ⚠️ **`reciprocal_rank_fusion` keys on `tid` (document), not chunk** (`graph_ranker.py:220`). Two implications below (steps 3 & 5). Also: each source returns a different shape — FTS5 dicts have no `title` (`legal_fts5.py:238`), Neo4j ranking returns `RankedGraphResult` dataclasses, Qdrant returns `ScoredPoint` — so an adapter is required.

Deliverables:
- [ ] `retrieval/hybrid_retriever.py` — `retrieve(query, intent) -> List[FusedResult]`:
  1. `plan = embed_query(query, intent, nano_model)`
  2. For each source in `plan.search_sources`: query the matching store
     - `content_vector` → Qdrant content; `label_vector` → Qdrant label; `bm25` → FTS5; `citation_graph` → Neo4j traverse (seed from top vector hits) → `graph_ranker.rank_graph_results()`
  3. **Adapter + per-source tid-collapse:** normalize each source's output to `{"tid","rank","title","caution_flag"}` dicts AND collapse multiple chunks of the same `tid` to that source's **best (lowest) rank**, re-ranking 1..N. (Without this, a doc with many matching chunks is added to its RRF score repeatedly and gets over-ranked.)
  4. Pass the collapsed per-source lists + `plan.rrf_weights` to `graph_ranker.reciprocal_rank_fusion()`
  5. **Chunk-fetch:** for each top-`tid` `FusedResult`, fetch the best matching chunk text (highest-ranked chunk seen in step 3) to hand to Synthesis. Return top-K (default 20).
  - Note: `RRF_WEIGHT_PRESETS` (`graph_ranker.py:280`) only defines 6 intents; RIGHTS / CITATION_LOOKUP / ARGUMENTATIVE fall back to DEFAULT weights. Either accept the fallback or add the 3 presets.

**✅ CHECKPOINT 3** — verify routing + fusion on 4 query archetypes:
- [ ] STATUTORY (`"What does Section 302 IPC say?"`) → only `label_vector` + `bm25` queried; statute doc in top-3
- [ ] PRECEDENT (`"cases that followed <known case>"`) → `content` + `bm25` + `graph`; graph contributes results
- [ ] CONCEPTUAL (`"what is mens rea"`) → semantic hits relevant
- [ ] ARGUMENTATIVE → all 4 sources fire; `query_mode == "ARGUMENTATIVE"`
- [ ] Assert RRF weights sum to ~1.0; no duplicate `tid` in final list; each `tid` contributes at most one rank per source (proves the tid-collapse works); `caution_flag` propagates for overruled cases
- [ ] **Golden-doc test**: for 5 hand-picked queries, the known-correct doc appears in top-10 (Recall@10)

---

### ── PHASE 4 — 4-Agent Pipeline ──
**Goal:** the 4 agents wired in LangGraph; a question yields a verified answer.

Deliverables:
- [ ] `agents/query_understanding.py` — LLM → `{intent ∈ QUERY_ROUTES, entities, query_mode}`; strict JSON output, schema-validated
- [ ] `agents/synthesis.py` — prompt enforces: answer ONLY from provided chunks, IRAC structure, inline `[tid]` citations, no outside knowledge
- [ ] `agents/citation_verifier.py` — extract every `[tid]`/section ref from the answer; confirm each exists in Neo4j/FTS5 AND appears in the retrieved set; strip/flag unverifiable citations; attach confidence + legal disclaimer
- [ ] `agents/graph.py` — LangGraph: `understand → retrieve → synthesize → verify`; shared state object carries query, QueryPlan, chunks, draft, verified answer
- [ ] `app.py` — `python app.py "<question>"` prints the verified answer + sources

**✅ CHECKPOINT 4** — verify:
- [ ] Each agent has a unit test (mock LLM) asserting output shape
- [ ] End-to-end: `python app.py "What is the punishment for murder under Section 302 IPC?"` → answer cites the real statute doc
- [ ] **Hallucination test**: feed the verifier an answer with a fabricated citation (`AIR 9999 SC 1`) → it is flagged/removed (proves the Mata-v-Avianca guardrail works)
- [ ] **Grounding test**: every sentence with a citation traces to a retrieved chunk
- [ ] Informational query skips Counsels (n/a yet) and runs in < N seconds; trace visible (add Langfuse in a later phase)

---

### ── PHASE 5 — End-to-End Verification & Eval ──
**Goal:** measurable quality, not vibes.

Deliverables:
- [ ] `eval/gold_set.jsonl` — ~20 queries with expected `tid`(s) and an intent label, spanning all archetypes
- [ ] `eval/run_eval.py` — reports **Recall@10 / MRR** (retrieval) and **citation-accuracy / groundedness** (answer)
- [ ] Short `RESULTS.md` snapshot of the run

**✅ CHECKPOINT 5 (MVP DONE)** — PASS criteria:
- [ ] Retrieval Recall@10 ≥ 0.7 on the gold set
- [ ] Citation accuracy == 100% (zero fabricated citations survive the verifier)
- [ ] All 5 prior checkpoints green and reproducible from a clean `docker compose up`

---

## 4. Master To-Do (single checklist)

**Phase 0 — Infra**
- [ ] requirements.txt
- [ ] docker-compose.yml (Qdrant + Neo4j)
- [ ] config.py + .env.example
- [ ] CHECKPOINT 0 green

**Phase 1 — Chunking**
- [ ] pipeline/01_chunk.py + run over 779 docs
- [ ] CHECKPOINT 1A green
- [ ] pipeline/02_enrich.py (3 LLM TODOs + heuristic fallback)
- [ ] CHECKPOINT 1B green

**Phase 2 — Embedding & Indexing**
- [ ] stores/qdrant_store.py (2 collections)
- [ ] stores/fts5_store.py (persistent)
- [ ] stores/neo4j_store.py (nodes + edges + traverse)
- [ ] pipeline/03_index.py (embed + write all 3)
- [ ] CHECKPOINT 2 green

**Phase 3 — Retrieval**
- [ ] retrieval/hybrid_retriever.py (4 sources + RRF)
- [ ] CHECKPOINT 3 green

**Phase 4 — Agents**
- [ ] agents/query_understanding.py
- [ ] agents/synthesis.py
- [ ] agents/citation_verifier.py
- [ ] agents/graph.py (LangGraph)
- [ ] app.py
- [ ] CHECKPOINT 4 green

**Phase 5 — Eval**
- [ ] eval/gold_set.jsonl
- [ ] eval/run_eval.py
- [ ] CHECKPOINT 5 green → **MVP complete**

---

## 5. Verification Matrix (quick reference)

| Phase | One-line verification |
|-------|----------------------|
| 0 | `docker ps` shows 2 containers; all imports succeed; nano loads |
| 1A | 637 + 142 chunk files (per subdir); merged edges non-empty; statutes unsplit; breadcrumbs present |
| 1B | ratio/issue-held/typed-edges present on 10-doc sample |
| 2 | store counts match; dim==1024; smoke vector search returns hits |
| 3 | intent routing correct; tid-collapse (one rank/source per tid); RRF weights sum~1; golden doc in top-10 |
| 4 | end-to-end answer cites real docs; fake citation flagged |
| 5 | Recall@10 ≥ 0.7; citation accuracy 100% |

---

## 6. Deferred to Later Phases (not in MVP)
- Remaining 9 agents: Decomposer, Statute/Precedent specialists (split out), **Petitioner + Respondent Counsels** (adversarial pair, ARGUMENTATIVE only), Validity Checker, Groundedness Critic (NLI), Conflict Resolver, Reflection, Output Formatter
- Langfuse observability, semantic query cache, delta ingestion
- Per-incuriam detection, Elasticsearch swap, Oracle Cloud deploy
- Authority re-ranker as a distinct stage (currently folded into graph_ranker)

---

## 7. Resolved Decisions (Session 2)
1. **Embedding** — ✅ Voyage key available. Index with **voyage-4-large** (API), query with **local voyage-4-nano**. Phase 2 uses `embed_documents_large()` as written; ensure `VOYAGE_API_KEY` is in `.env`.
2. **Phase 1B timing** — ✅ **Slice first, enrich after.** Ship the vertical slice (Phases 1A → 2 → 3 → 4) on structural chunks, then run `02_enrich.py` and re-index. Phase 1B does NOT block the first end-to-end answer.
3. **Agent LLMs** — ✅ **LiteLLM multi-provider.** Each agent routes to its own free tier (Query Understanding → Groq 8B; Synthesis → Gemini Flash / Cerebras 70B; Citation Verifier → Groq 8B) through a single LiteLLM gateway. Provider config lives in `config.py`.
```
