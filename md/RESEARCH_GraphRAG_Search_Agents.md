# 📑 Research Report — Local / Global / DRIFT Search & Multi-Agent Retrieval

> Project: Indian Legal Agentic RAG
> Date: June 20, 2026
> Scope: Which graph search strategies and retrieval agents to add to the existing 13-agent topology, with research grounding, pros/cons, and a future roadmap.

---

## 1. Executive Summary

The system already has a Neo4j citation graph but uses it in **only one of three** GraphRAG query modes. Microsoft GraphRAG defines three strategies over a knowledge graph — **Local**, **Global**, and **DRIFT** search:

- The current **Citation Graph Traversal agent ≈ GraphRAG Local Search** (entity-anchored).
- There is **no Global Search** equivalent (corpus-wide doctrine synthesis).
- There is **no DRIFT Search** (breadth + depth for argumentative queries).

The missing prerequisite is **community detection + community reports** (Leiden clustering over the citation graph, one LLM summary per cluster). Both Global and DRIFT depend on it.

**Cost advantage:** Full GraphRAG is expensive at index time mainly because of LLM entity/edge extraction. This project gets edges *for free* (IK `citedby` arrays + citation extraction), so only the community-summary step costs LLM calls — making Global/DRIFT unusually cheap to adopt here.

---

## 2. The Three Search Modes

| Mode | Mechanic | Legal analogue | Best for | Cost / Latency |
|---|---|---|---|---|
| **Local Search** | Anchors on specific entities, pulls nearby graph nodes + their text units | "Find cases citing *Puttaswamy* and what they held" | Entity / case-specific questions; answer lives in a few documents | Low, fast |
| **Global Search** | Map-reduce over **community reports** (pre-summarized clusters of the graph) | "What is the settled position across all SC privacy judgments?" | Corpus-wide synthesis, themes, overall doctrine | High (touches many summaries) |
| **DRIFT Search** | **Primer** (query vs top-K community reports + HyDE → broad answer + follow-up questions) → **Follow-up loop** (local search per sub-question, ~2 iterations) → ranked Q&A hierarchy | "Argue whether privacy is a fundamental right" — needs doctrine *and* specific holdings | Queries needing breadth **and** depth; vague queries that don't name a case | Medium (between local and global) |

### DRIFT in detail (Microsoft Research)
1. **Primer phase** — compares query to top-K most semantically relevant community reports; uses **HyDE** (Hypothetical Document Embeddings) to expand the query into high-level abstractions; emits a broad initial answer + follow-up questions.
2. **Follow-up / local phase** — runs each follow-up via local search, producing intermediate answers and *new* follow-up questions; loops (~2 iterations).
3. **Output** — a hierarchy of Q&A pairs ranked by relevance to the original query.

**Benchmark (5,000+ AP news articles, DRIFT vs plain Local Search):**
- Comprehensiveness: DRIFT won **78%** of the time.
- Diversity: DRIFT won **81%** of the time.
- Trade-off: more iterations than local, fewer than global.

This maps directly onto the existing **ARGUMENTATIVE** query mode — the same place the adversarial Counsel pair already fires.

### The missing primitive: Community Reports
GraphRAG runs **Leiden community detection** over the graph, then LLM-summarizes each community. In this project's terms: clusters of mutually-citing cases become **"doctrinal areas"** (e.g. a cluster of Article 21 cases), one summary ("doctrinal digest") per cluster. Global and DRIFT both read these summaries.

---

## 3. Recommended Agents to Add

### 3.1 Community Report Builder — *index-time, prerequisite*
Runs Leiden community detection over the Neo4j citation graph, then LLM-summarizes each community into a doctrinal digest.

- **Pros:** Unlocks both Global and DRIFT; summaries are reusable/cacheable; converts raw citation edges into queryable doctrine; cheap here because edges are free.
- **Cons:** Index-time LLM cost (one call per community); summaries go stale as the corpus grows (re-cluster on delta ingestion); cluster quality depends on citation density — sparse/old judgments cluster poorly.

### 3.2 Global Synthesis Agent — *Tier 2 retriever*
Map-reduce over community reports for corpus-wide questions.

- **Pros:** Answers a query class the current vector + BM25 + local-graph stack cannot; ideal for "doctrine survey" intents.
- **Cons:** Expensive (many LLM calls in the reduce step); can over-generalize and blur jurisdiction — **must** keep the Jurisdiction filter in the loop or it mixes HC positions across states.

### 3.3 DRIFT Orchestrator Agent — *Tier 1/5, routed from ARGUMENTATIVE*
Primer against community reports → spawns follow-up sub-questions → existing Decomposer + specialists answer each → re-rank into a Q&A hierarchy.

- **Pros:** Best quality/cost balance (per Microsoft benchmark); the primer→follow-up loop is almost identical to the existing Decomposer→specialist flow, so it is an extension not a rewrite; HyDE primer helps when a query names no specific case.
- **Cons:** Iterative = higher latency (fine for research memos, poor for snappy chat); needs a depth cap (Microsoft uses 2) or it sprawls; overkill for INFORMATIONAL queries.

### 3.4 Search-Mode Router — *extend the existing Query Understanding Agent (do NOT add a new agent)*
Classify each query into LOCAL / GLOBAL / DRIFT, same shape as the existing INFORMATIONAL vs ARGUMENTATIVE routing.

- **Pros:** Avoids paying global/DRIFT cost on simple lookups; `query_embedder.py` routing already does this kind of decision.
- **Cons:** Misroute → underpowered answer or wasted cost; needs a few-shot eval set of real legal queries to tune.

**Suggested routing (extends the existing intent table):**
- `CITATION_LOOKUP`, `STATUTORY`, `PROCEDURAL` → **Local**
- `CONCEPTUAL`, survey/landscape intents → **Global**
- `ARGUMENTATIVE`, `RIGHTS`, `COMPARISON` → **DRIFT** (then hand to the Counsel pair)

---

## 4. How This Maps Onto the Existing 13 Agents

| Existing component | Relationship to GraphRAG mode |
|---|---|
| Citation Graph Traversal (Tier 2) | ≈ Local Search — keep as-is |
| Decomposer (Step Definer) | Reuse as DRIFT's follow-up generator |
| Query Understanding (Tier 1) | Extend to emit LOCAL / GLOBAL / DRIFT |
| Adversarial Counsel pair (Tier 3) | Consumes DRIFT output for ARGUMENTATIVE queries |
| `graph_ranker.py` RRF fusion | Treat Global/DRIFT outputs as another ranked list into RRF — no separate pipeline |

Net new pieces: **Community Report Builder** (offline), **Global Synthesis Agent**, **DRIFT Orchestrator**. Everything else is extension/reuse.

---

## 5. Future Add-Ons

- **HyDE primer for legal queries** — generate a hypothetical ideal judgment, embed *that*, search with it. Cheap; what makes DRIFT's primer robust to vague queries.
- **Dynamic community selection** (newer Global Search variant) — rank communities by relevance before the map step so Global isn't full-corpus every time. Directly cuts Global's biggest cost.
- **Temporal communities** — cluster the citation graph *as of a date* to answer "settled law in 2015 vs now." Validity/overruled metadata already supports this.
- **Self-evolving / self-verifying agents** — 2025–2026 surveys point to agents that critique and refine their own retrieval. The existing Reflection + Groundedness Critic are the seed.
- **GraphRAG ↔ RRF unification** — feed Global/DRIFT results through the existing RRF rather than a parallel stack.

---

## 6. Recommended Build Order

1. **Community Report Builder** (offline module over Neo4j) — unlocks everything else.
2. **Search-Mode Router** extension in `query_embedder.py`.
3. **Global Synthesis Agent** (simplest consumer of community reports).
4. **DRIFT Orchestrator** (reuses Decomposer + specialists).
5. Future: dynamic community selection, HyDE primer, temporal communities.

---

## 7. Sources

- [GraphRAG Query Overview — Local/Global/DRIFT/Basic](https://microsoft.github.io/graphrag/query/overview/)
- [Introducing DRIFT Search (Microsoft Research)](https://www.microsoft.com/en-us/research/blog/introducing-drift-search-combining-global-and-local-search-methods-to-improve-quality-and-efficiency/)
- [DRIFT Search docs](https://microsoft.github.io/graphrag/query/drift_search/)
- [GraphRAG: Improving global search via dynamic community selection](https://www.microsoft.com/en-us/research/blog/graphrag-improving-global-search-via-dynamic-community-selection/)
- [Implementing DRIFT Search with Neo4j and LlamaIndex](https://neo4j.com/blog/developer/drift-search-with-neo4j-and-llamaindex/)
- [Agentic RAG: A Survey (Singh et al., arXiv:2501.09136)](https://arxiv.org/abs/2501.09136)
- [Towards Agentic RAG with Deep Reasoning: A Survey (arXiv:2507.09477)](https://arxiv.org/pdf/2507.09477)
- [From single-agent to multi-agent: review of LLM-based legal agents](https://www.oaepublish.com/articles/aiagent.2025.06)
