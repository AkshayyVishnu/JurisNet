# 🧠 Project Memory — Indian Legal Agentic RAG
> Last updated: Session 1 — June 19, 2026
> Purpose: Running context doc so Claude can resume accurately after context resets.

---

## 🏗️ What We're Building

A **production-ready, scalable Agentic AI + Advanced RAG system** for the Indian legal domain.

- **Data source**: Indian Kanoon — **1036 docs (76 MB), already downloaded as structured JSON**
- **Goal**: Contextual fidelity under stress, zero hallucination tolerance on citations
- **Stack**: Full-stack — chunker + knowledge stores + retrieval engine + multi-agent layer + guardrails + production infra

---

## ✅ Current State

- [x] Architecture designed — 7 layers, 28 components
- [x] Chunking strategy designed — **8 chunk types**, 6-stage pipeline
- [x] Agent topology designed — 13 agents across 5 tiers, hybrid hierarchical orchestration
- [x] Embedding strategy designed — poly-vector: voyage-context-3 (content) + gemini-embedding-001 (label)
- [x] Free-tier build path mapped — all components have $0 options
- [x] **Chunker built and tested** — `chunker.py` works on real IK JSON files
- [x] **Data format analyzed** — IK provides `data-structure` attributes (section labels for free) and `citedby` arrays (Neo4j edges for free)
- [ ] LLM batch calls wired (ratio/obiter, issue-held, citation relationships) — 3 TODOs in chunker.py
- [ ] Embedding pipeline built
- [ ] Knowledge stores set up (Qdrant + Neo4j + SQLite FTS5)
- [ ] Retrieval engine built
- [ ] Agents implemented
- [ ] Guardrails implemented

---

## 🏛️ Architecture: 7 Layers (Summary)

1. **Data Ingestion** — ~~IK Async Crawler, Multi-Format Parser~~ **NOT NEEDED. Data already acquired as structured JSON.** Only Citation Normalizer needed (regex on inline citations).
2. **Knowledge Representation** — Legal Hierarchical Chunker (**BUILT**: `chunker.py`), Metadata Enricher (built into chunker), Ratio/Obiter Tagger (TODO: LLM batch call), **Poly-vector Embedders** (voyage-context-3 + gemini-embedding-001)
3. **Knowledge Stores** — Qdrant (vector — TWO collections for poly-vector), Neo4j (citations — **from day one**), SQLite FTS5 (BM25, swap to Elasticsearch at >50K docs), JSON file (statute ontology, swap to PostgreSQL+ltree later)
4. **Retrieval Engine** — Hybrid Retriever (RRF over content vector + label vector + BM25 + citation graph), Authority Re-ranker, Citation Chain Traverser, Jurisdiction & Validity Filter
5. **Agent Orchestration** — 13 agents, hybrid hierarchical (see below)
6. **Safety & Guardrails** — Citation Verifier, Groundedness Checker, Ratio/Obiter Enforcer, Disclaimer + Confidence
7. **Production Infrastructure** — Semantic Query Cache, Delta Ingestion (cron script, not Airflow at this scale), Legal RAG Evaluator, **Langfuse** (observability — from day one)

---

## 📂 Data Format Discoveries (from real IK JSON files)

### Judgment JSON (e.g. 70075.json)
```json
{
  "tid": 70075,                         // unique IK document ID
  "publishdate": "1917-11-07",
  "title": "Gobind Ram And Ors. vs Jwala Pershad And Ors.",
  "doc": "<html with data-structure attributes>",  // see below
  "numcites": 0,
  "numcitedby": 5,
  "docsource": "Allahabad High Court",   // court identification
  "divtype": "judgments",                 // distinguishes from statutes
  "relatedqs": [{"value": "mortgage"}],  // IK-provided related queries
}
```

**Key discovery**: The HTML in `doc` has `data-structure` attributes on `<p>` tags:
```html
<p data-structure="Facts" id="p_1">...</p>
```
This means **section classification (Facts/Issues/Held/Reasoning) requires 0 LLM calls** — IK provides it for free.

### Statute JSON (e.g. 30062.json)
```json
{
  "tid": 157220060,
  "title": "Section 2 in The Code Of Civil Procedure (Amendment) Act, 2002",
  "docsource": "Union of India - Section",  // identifies as statute
  "cleaned_text": "Section 2 in The Code Of Civil Procedure...",  // already plain text
  "cites": [],
  "citedby": [                              // FREE Neo4j edges!
    {"tid": 108460608, "title": "Sri Chaitanya..."},
    ...8 entries
  ]
}
```

**Key discovery**: `citedby` array gives us case→statute citation edges with zero LLM calls. For the full statute corpus, the citation graph may be mostly pre-built from JSON alone.

### Auto-detection rule
- `divtype == "judgments"` → judgment chunker
- `docsource` starts with "Union of India" → statute chunker
- Fallback: has `cleaned_text` but no `doc` → statute; else → judgment

---

## 🧩 Chunking Strategy — 6-stage pipeline, 8 chunk types

### The 8 chunk types

| # | Chunk Type | Granularity | Solves |
|---|---|---|---|
| 1 | **L0 Document** (includes headnote/summary) | Whole-doc metadata + summary | Broad case discovery |
| 2 | **L1 Section** (Facts/Issues/Held/Reasoning) | One section, whole, regardless of length | Section-specific retrieval |
| 3 | **L2 Paragraph** (+ 1-para overlap) | One paragraph with sliding window | Standard semantic retrieval |
| 4 | **L3 Atomic proposition** | One holding = one chunk | Groundedness verification (NLI) |
| 5 | **Ratio** | Binding holding only, 1.3× boost | Precedent retrieval |
| 6 | **Issue-Held pair** | Framed question + court's answer | Q&A intent matching |
| 7 | **Citation** | Citing sentence + cited case + rel type | Multi-hop citation traversal (→ Neo4j edge) |
| 8 | **Statute provision** | Section + ALL provisos + explanations, NEVER split | Statutory interpretation, atomic |

**Previously 9 — merged L0 + Headnote.** L0's `summary_text` field IS the headnote if IK provides one (via `relatedqs` and editorial summary), else auto-generated. One chunk per document, period.

### The 6 pipeline stages

1. **Structural parse** — extract paragraphs, section labels (from IK `data-structure` attribute — **0 LLM calls**), citation strings, metadata
2. **Multi-granular chunking** — L0/L1/L2 all coexist with `granularity` field
3. **Specialized chunk extraction** — ratio (TODO: LLM), issue-held pairs (TODO: LLM), citation edges (regex + TODO: LLM for relationship type)
4. **Edge extraction** — emit typed edges to Neo4j: FOLLOWED/OVERRULED/DISTINGUISHED/RELIED_ON. Statute `citedby` arrays give CITES_STATUTE edges for free.
5. **Temporal & validity tagging** — effective_from/to, citation_status, per_incuriam, sub_silentio
6. **Multi-store distribution** — fan out to Qdrant (2 collections) / Neo4j / SQLite FTS5

**Previously 7 stages — dropped contextual enrichment** because voyage-context-3 bakes document-context-aware embedding into the model itself. No separate LLM pre-processing step needed.

### LLM calls per judgment — corrected twice

| Task | LLM calls | Status |
|---|---|---|
| Section classification (Facts/Issues/Held) | **0** — IK provides `data-structure` attribute | ✅ Free |
| Ratio/Obiter tagging | 1 batched call | TODO in chunker.py |
| Issue-Held pair extraction | 1-2 calls | TODO in chunker.py |
| Citation relationship classification | 1-2 batched calls | TODO in chunker.py |
| **Total per judgment** | **~3-4 calls** | |

For 1036 docs (est. ~800 judgments): ~2,400-3,200 LLM calls total. One afternoon on Cerebras free tier.

### Why dense embeddings + graph + BM25 (not one or the other)

Three retrieval modes solve three different questions:
- **Dense embeddings**: "what is semantically similar?" — wins on paraphrases, fuzzy concepts
- **Knowledge graph**: "what is connected to this entity, by what relationship?" — wins on multi-hop traversal
- **BM25**: "what contains these exact words?" — wins on identifiers ("Section 302 IPC", "Article 21")

A KG cannot find conceptually similar text. A vector store cannot traverse OVERRULED edges. BM25 misses paraphrases. We use all three with RRF fusion.

### Chunk-to-embedder mapping

| Chunk type | Content vector (voyage-context-3) | Label vector (gemini-embedding-001) |
|---|---|---|
| L0 Document (summary_text) | ✓ | case name + citation + topic keywords |
| L1 Section | ✓ | — |
| L2 Paragraph | ✓ | — |
| L3 Atomic proposition | ✓ | — |
| Ratio | ✓ | case name + holding subject |
| Issue-Held pair | ✓ | — |
| Citation | **NOT EMBEDDED** — Neo4j edge only | **NOT EMBEDDED** — citing text already in L2 |
| Statute provision | ✓ (note: voyage-context-3's document-context advantage doesn't apply here — each statute is its own JSON file, no larger document for context) | act + section + ALL aliases |

### Conceptual clarifications

**Facts similarity vs Ratio retrieval — different retrieval modes**
- Facts chunk answers "find cases where X happened" (factum probans)
- Ratio chunk answers "what is the binding legal principle from Y" (precedent search)
- Two cases can share ratio but have totally different facts, and vice versa

**Ratio chunk in simple terms**
Only the ratio decidendi is binding on future courts (Article 141). Obiter is just judicial musing. We tag ratio chunks separately and boost them 1.3× in retrieval so the Precedent Specialist agent surfaces binding text, not opinions.

**L3 atomic vs statute provision — different sources, different authority**
- L3 atomic: from a judgment (court's interpretation) — binding only if from ratio of SC/HC
- Statute provision: from an Act/Rule (Parliament's text) — IS the law itself
- Cannot substitute; different metadata, different retrieval intents, different authority sources

### Pros of 8-chunk strategy
- Right granularity for each query type
- Vector + graph + BM25 cover similarity, structure, and exact-match retrieval gaps
- Statute atomicity prevents the #1 legal RAG bug (proviso-strip changes section meaning)
- Ratio/obiter separation prevents legal malpractice
- Issue-Held format mirrors real legal Q&A intent

### Cons (known trade-offs)
- 15-50 chunks per judgment = storage + indexing overhead
- 3-4 LLM calls per judgment at index time — bottleneck on free tiers
- Same sentence may appear in L2 + L3 + Ratio = de-duplication needed at retrieval
- Citation relationship classification is error-prone; wrong edges → wrong multi-hop
- Headnote quality varies across IK documents

---

## 🎯 Embedding Strategy — Poly-Vector (voyage-context-3 + gemini-embedding-001)

### Research foundation
- **Lima (arxiv:2504.10508, April 2025)** — Poly-Vector Retrieval: separate embeddings for content (sense) and label (reference). Significantly improves label-centric queries on legal corpora.
- **voyage-context-3 (July 2025)** — contextualized chunk embeddings beat Anthropic contextual retrieval by +20.54% on chunk-level retrieval. 200M free tokens.
- **Voyage benchmarks (Jan 2025)** — voyage-3-large outperforms voyage-law-2 on legal datasets. **voyage-law-2 is obsolete; do not use just for the name.**

### The two-embedder architecture

**Content vector** — `voyage-context-3`
- 1024 dims (also supports 256/512/768 via Matryoshka)
- 32K context window — handles atomic statute chunks
- Free: 200M tokens one-time
- Paid: $0.10/MTok ($0.067/MTok batch)

**Label vector** — `gemini-embedding-001`
- 3072 dims native (truncate to 768 via MRL)
- 2048-token input (plenty for labels)
- Free: indefinite at 100 RPM / 1000 RPD (~2M tokens/day sustainable)
- Paid: $0.15/MTok

### Fusion at query time
RRF combines 4 ranked lists:
1. Content vector (voyage-context-3 top-50)
2. Label vector (gemini-embedding-001 top-50)
3. BM25 keyword (SQLite FTS5 top-50, Elasticsearch later)
4. Citation graph 2-hop neighborhood

Weights adjustable per query intent.

---

## 🤖 Agent Topology — 13 agents, 5 tiers, hybrid hierarchical orchestration

### Tier 1 — Pre-retrieval
- **Query Understanding Agent** — disambiguate, intent classify, entity extract
- **Decomposer (Step Definer)** — break into atomic sub-questions

### Tier 2 — Specialist retrievers
- **Statute Specialist** — Acts/Rules/Notifications, amendment-aware
- **Precedent Specialist** — case law via hybrid retriever, authority-weighted
- **Citation Graph Traversal** — Neo4j multi-hop

### Tier 3 — Adversarial pair (highest-leverage addition)
- **Petitioner Counsel** — finds evidence FOR user's position
- **Respondent Counsel** — finds evidence AGAINST

### Tier 4 — Verification & critics
- **Validity Checker** — pre-gen gate
- **Synthesis Judge** — reads both Counsels, synthesizes (needs higher-capacity model)
- **Citation Verifier** — post-gen MANDATORY
- **Groundedness Critic** — NLI check
- **Conflict Resolver** — surfaces same-level court conflicts

### Tier 5 — Orchestration & output
- **Orchestrator (ReAct)** — top of stack, 12-step budget
- **Reflection Agent** — completeness check
- **Output Formatter** — IRAC structure, disclaimers (cheap model is fine)

### Research foundation
MA-RAG (May 2025), ChatLaw (2024), SAMVAD (Sept 2025, India-specific), L4L (Nov 2025), LegalAgentBench (Dec 2024), CRAG (2024), Self-RAG (2023), AusLaw Benchmark (2026), Agentic RAG Survey (Singh et al., Jan 2025)

---

## ❌ Tried & Eliminated

| Approach | Why we dropped it |
|---|---|
| Fixed-size token chunking | Destroys legal reasoning |
| Single chunk granularity | Different queries need different granularity |
| Vector-only retrieval | Can't do multi-hop citation traversal |
| Deleting overruled cases | Historical context needed |
| Plan-and-Execute orchestration | LegalAgentBench: ReAct beats it on legal |
| Monolithic single-agent ReAct | AusLaw: standalone models fail on legal citations |
| Pure Self-RAG reflection tokens | FVA-RAG: intrinsic checks validate poisoned context |
| Separate Query Rewriter agent | MA-RAG ablation: no measurable benefit |
| Per-issue MoE experts (ChatLaw) | Indian law domains too blurred |
| Tree-of-Thought branching | Legal reasoning is sequential-deductive |
| **voyage-law-2** | Outperformed by voyage-3-large and voyage-context-3; misleading "legal" name |
| **Single-embedder content-only** | Poly-vector paper: label queries fail hard on content embeddings |
| **Anthropic contextual retrieval** (separate LLM per chunk) | voyage-context-3 bakes this in — beats it by +20.54% |
| **Cohere embed-v4 free tier** | Only 1000 calls/MONTH total — unusable |
| **OpenAI text-embedding-3** | No free tier; beaten by voyage-context-3 |
| **9 chunk types (L0 + Headnote separate)** | Redundant; merged into L0 with summary_text field |
| **L0 in both Qdrant AND Postgres** | Overengineered; Qdrant payload IS a JSON store; Postgres only for statute ontology |
| **SQLite for citation graph (swap to Neo4j later)** | Migration cost too high; Cypher is the right query language from day one |
| **Separate parser/crawler step** | Data already acquired as structured JSON; IK provides data-structure attributes |
| **LLM for section classification** | IK provides `data-structure` attribute on HTML paragraphs — 0 calls needed |
| **Privy Council authority 0.95** | Too high — surfaces 100-year-old decisions above HCs; lowered to 0.55 with persuasive_only flag |
| **Graph results as unranked set into RRF** | RRF needs ranked lists; created composite scoring: (1/hop) × edge_weight × authority × recency |
| **Always embed query with both embedders** | Wasteful — STATUTORY queries don't need voyage, PRECEDENT queries don't need gemini; intent-based routing saves ~40% |
| **Reporter-only citation extraction** | Most Indian judgments cite by case name ("Party1 v. Party2"); regex-only catches ~30% of actual citations |
| **Embedding citation chunks separately** | Citing text already lives in L2 paragraph chunks; double-embedding wastes storage and creates retrieval duplicates |
| **FTS5 default tokenizer for legal text** | Splits "Section 302" into two tokens; replaced with pre-normalization to single tokens |
| **Per incuriam detection at 1036 docs** | Requires knowing controlling precedent for every issue; deferred to Phase 2 when corpus > 50K |
| **Custom orchestration code for 13 agents** | LangGraph handles state management, parallel execution, conditional branching, and retry logic out of the box |

---

## 🔑 Key Decisions

| Decision | Reasoning |
|---|---|
| Qdrant over Pinecone | Native payload filters, self-hostable, hybrid search |
| Neo4j for citations **from day one** | Graph traversal — vectors can't do BFS; migration from SQL is expensive |
| ReAct over Plan-and-Execute | Legal research is exploratory |
| Adversarial Counsel pair | L4L + SAMVAD: kills confirmation bias |
| Citation Verifier MANDATORY | Mata v Avianca (2023) — sanctioned lawyers |
| Hybrid hierarchical orchestration | Dominant production pattern |
| Higher-capacity model for Synthesis Judge | MA-RAG ablation |
| **8 chunk types** | Each retrieval mode needs different granularity (was 9, merged L0+Headnote) |
| Statute provisions atomic | Splitting provisos changes meaning |
| Citations as graph edges | Multi-hop traversal impossible otherwise |
| voyage-context-3 for content embedding | +20.54% vs Anthropic contextual retrieval, free 200M tokens |
| gemini-embedding-001 for labels | Only perpetual-free embedder; MTEB multilingual leader |
| Two Qdrant collections, RRF fusion | Standard poly-vector pattern |
| Skip Anthropic contextual retrieval | voyage-context-3 makes it redundant |
| **Langfuse from day one** (not LangSmith) | OSS, one Docker command, want agent traces from start |
| **LiteLLM from day one** | OSS library, unified LLM interface, enables provider rotation |
| **Skip parser — chunk directly from JSON** | IK JSON is already structured; data-structure attrs eliminate section classification |
| **L3 Atomic = sentence-level from Held/Reasoning** | Groundedness Critic needs atomic verifiable units; sentence splitting with min 10 words |
| **Privy Council = 0.55 with persuasive_only flag** | Post-1950 decisions are persuasive, not binding; must rank below HC (0.7) |
| **Graph→ranked list via composite score for RRF** | RRF needs ranked lists; graph_score = (1/hop) × edge_weight × authority × recency |
| **Intent-based query-time embedding routing** | Skip unnecessary embedder calls per intent; saves ~40% API calls on free tier |
| **Case-name citation extraction** | Most Indian judgments cite by name ("Party1 v. Party2"), not just reporter format |
| **Adversarial pair only for ARGUMENTATIVE queries** | Informational queries ("What does Section 302 say?") skip Counsels — saves 2 LLM calls |
| **Citation chunks = Neo4j edges only, NOT embedded** | Citing text already in L2 paragraph; embedding duplicates storage without retrieval benefit |
| **FTS5 with legal token normalization** | Pre-normalize "Section 302 IPC" → "section_302_ipc" before indexing AND querying; single-token match |
| **L0 summary_text = title + citations + keywords** | IK relatedqs are topic keywords, NOT legal headnotes; renamed to avoid confusion |
| **LangGraph for agent orchestration** | 13 agents with parallel specialists + adversarial pair + sequential gates needs a framework; LangGraph handles state, branching, and human-in-the-loop |
| **Per incuriam detection → Phase 2** | Requires knowing controlling precedent for every legal issue; infeasible at 1036 docs |
| **voyage-context-3 context benefit = judgments only** | Statute provisions are standalone JSON files (no larger document for context); +20.54% improvement applies to judgment chunks, not statutes |

---

## ⚠️ Known Issues / Gotchas

- Citation formats inconsistent within same document
- "Section 302 IPC" and "Section 302 of the Indian Penal Code" must resolve to same entity (label embedder helps via multi-alias indexing)
- Bench composition in inconsistent formats in older judgments
- HC judgments don't always cite the SC case they're following — implicit precedent
- Regional language documents need translation layer before embedding
- Ratio decidendi not always explicitly marked — needs LLM inference
- ADM Jabalpur overruled by Puttaswamy (2017) but cited 1000s of times — validity propagation critical
- Adversarial Counsel pair must have EQUAL retrieval budget
- Synthesis Judge needs higher-capacity model — don't use Haiku here
- gemini-embedding-001 has 2048-token input limit AND single input per request — fine for labels, useless for chunks
- Voyage 200M free tier is per-account, one-time — burns fast at scale; plan Phase 2 in advance
- Vector dimensions: voyage-context-3 = 1024, gemini = 3072 native (truncate to 768) — different Qdrant collections
- text-embedding-004 is deprecated — use gemini-embedding-001 only
- **Not all IK judgment files may have data-structure attributes** — need fallback LLM call for those without
- **Case-name citation regex produces false positives** — "The State v. accused" patterns need post-filtering; fuzzy match against corpus titles to resolve tid
- **L3 atomic chunks from single-paragraph judgments produce 0 chunks** — old short judgments (pre-1950) often have entire reasoning in one "Facts" paragraph; IK mislabels these
- **FTS5 default tokenizer splits "Section 302" into two tokens** — use phrase queries or custom tokenizer for compound legal identifiers
- **Adversarial Counsel pair should NOT fire on informational queries** — Query Understanding Agent must output `query_mode: INFORMATIONAL | ARGUMENTATIVE` to route correctly
- **Free-tier rate limits are snapshot values (June 2026)** — Groq, OpenRouter, Gemini change limits without notice; verify before implementation
- **relatedqs field is keywords, not a headnote** — IK provides `["mortgage", "mortgaged property"]`, not a structured legal summary; actual headnotes unavailable in JSON format

---

## 💰 $0 Build Path — Full Pipeline on Free Tiers

### Layer-by-layer free choices

| Layer | Component | Tool | Free quota |
|---|---|---|---|
| **L1 Ingestion** | ~~Crawler~~ | **NOT NEEDED** — data already downloaded as JSON | — |
| | ~~PDF parsing~~ | **NOT NEEDED** — IK JSON has HTML/cleaned_text | — |
| **L2 Chunking + Embedding** | Section detection | **IK `data-structure` attribute** — 0 LLM calls | Free |
| | Ratio-obiter classifier | Groq Llama 3.3 70B or Gemini Flash-Lite | 30 RPM / 1K RPD |
| | Content embedder | voyage-context-3 | 200M tokens one-time |
| | Label embedder | gemini-embedding-001 | 100 RPM / 1K RPD perpetual |
| | Embedding fallback | Jina v3 → self-host BGE-M3/Nomic v2 | 10M one-time → ∞ |
| **L3 Stores** | Vector × 2 | Qdrant self-hosted (Docker) | unlimited |
| | Citation graph | **Neo4j Community Edition** (Docker, from day one) | unlimited |
| | BM25 | **SQLite FTS5** (swap to ES at >50K docs) | unlimited |
| | Ontology | **JSON file** (swap to Postgres+ltree later) | unlimited |
| | VM (at scale) | Oracle Cloud Free Tier (2 ARM VMs / 24 GB RAM) | perpetual |
| **L4 Retrieval** | Reranker | Jina Reranker v3 → BGE-Reranker-v2-m3 self-host | 10M tokens → ∞ |
| **L5 Agents** | Orchestrator + Decomposer | Groq Llama 3.3 70B | 1K RPD |
| | Query Understanding + Formatter | Groq Llama 3.1 8B | 14.4K RPD |
| | Specialists | Gemini 2.5 Flash | 250 RPD each |
| | Petitioner / Respondent Counsels | OpenRouter DeepSeek R1 :free | 20 RPM / 200 RPD |
| | Synthesis Judge | Gemini Flash → Cerebras Llama 3.3 70B | 250 RPD + 1M TPD |
| | Verifiers + Critics | bge-reranker self-host + Groq 8B | infinite + cheap |
| | Last-resort fallback | Ollama (local, Qwen3 8B) | infinite |
| **L6 Guardrails** | Citation Verifier + Groundedness | Cypher + bge-reranker self-host | free |
| **L7 Production** | Observability | **Langfuse self-host** (Docker, from day one) | free OSS |
| | Cache | Redis or Python dict | free |
| | Eval | ragas + promptfoo | free OSS |

### Critical patterns
1. **LiteLLM gateway from day one** — unified LLM interface, swap providers via config
2. **Oracle Cloud Free Tier** — perpetually free, 2 ARM VMs, 24 GB RAM (for when you deploy)
3. **Provider rotation per agent** — spread 13 agents across disjoint free quotas
4. **Embedding burn plan** — voyage 200M → Jina 10M → self-host BGE-M3

---

## 🎯 Scale Reality — 1036 docs, 76 MB corpus

### Cost math
- 1036 docs × ~18K tokens = **~18M tokens** (Voyage free covers 11× over)
- Gemini labels: ~3M tokens (~2 days on free)
- LLM chunking: 1036 × 3.5 calls = **~3,600 calls** (4 days Groq free, or 1 afternoon Cerebras)
- **Entire corpus indexable for $0 in under a week**

### MVP stack — what to run

**Docker (4 containers):**
- Qdrant — vector store (2 collections: content + label)
- Neo4j Community Edition — citation graph (from day one)
- Langfuse — agent observability (from day one)
- Redis (optional) — cache

**In-process (no container needed):**
- SQLite FTS5 — BM25 keyword search
- JSON file — statute ontology
- Python script — ingestion orchestration
- LiteLLM — LLM provider abstraction

**Everything runs on a laptop.** ~4-6 GB RAM, ~1 GB disk for indexed corpus.

### Scale-up triggers
- > 50K docs → SQLite FTS5 → Elasticsearch
- > 100K docs → Laptop → Oracle Cloud Free Tier
- > 1M docs → Free tier embedding exhausted → self-host BGE-M3

### Principle — when to swap-later vs build-correct-from-day-one

**Swap-later only when BOTH:** (1) the small version is genuinely easier, AND (2) migration is cheap.

| Build correct from day one | Defer is fine |
|---|---|
| Neo4j — migration is expensive | Elasticsearch — migration is just reindexing |
| Langfuse — one Docker command | Postgres ontology — JSON file works for static data |
| LiteLLM — zero overhead library | Airflow — cron works for one job |

---

## 🔧 Built Artifacts

### `chunker.py` v2 — BUILT AND TESTED
- Auto-detects judgment vs statute from JSON structure (improved: handles state statutes)
- Produces: L0, L1, L2, **L3 Atomic** (sentence-level from Held/Reasoning), Ratio (placeholder), Issue-Held (TODO), Citation edges, Statute provision chunks
- **Court authority hierarchy fixed**: SC=1.0, HC=0.70, Privy Council=0.55 (persuasive_only=True), District=0.35, Tribunal=0.25, Commission=0.20
- **Case-name citation extraction added**: catches "Party1 v. Party2" patterns in addition to AIR/SCC/SCR reporters
- Breadcrumbs auto-prepended to every chunk
- Statute alias generation built in (Section 2 CPC → S.2 CPC, Section 2 C.P.C.)
- Batch runner for full directory processing
- 3 TODO spots for LLM calls: ratio/obiter, issue-held extraction, citation relationship classification

### `graph_ranker.py` — BUILT AND TESTED
Converts citation graph traversal results (a SET of connected nodes) into a ranked list for RRF fusion.

Scoring formula per node:
```
graph_score = (1/hop_distance) × edge_type_weight × authority_score × recency_factor
```

- Edge weights: FOLLOWED=1.0, RELIED_ON=0.8, APPROVED=0.7, EXPLAINED=0.6, REFERRED=0.4, DISTINGUISHED=0.3
- Overruled cases: 0.3× penalty (still retrievable, ranked low, caution_flag=True)
- Overruling cases: 1.2× boost (the new authority)
- Recency: exp(-0.02 × years_old) — slow decay, legal precedent is long-lived
- Deduplication: same case via multiple paths → keep best score
- Includes complete RRF fusion function with intent-based weight presets

RRF weight presets per intent:
- PRECEDENT: graph=0.40, content=0.35 (graph-heavy)
- STATUTORY: bm25=0.40, label=0.30 (exact-match-heavy)
- CONCEPTUAL: content=0.50, graph=0.30 (semantic-heavy)
- DEFAULT: content=0.35, bm25=0.25, graph=0.25, label=0.15 (balanced)

### `query_embedder.py` — BUILT AND TESTED
Intent-based query-time embedding strategy. Decides which embedders to call per query, saving ~40% of API calls.
Also handles **adversarial routing**: outputs `query_mode = INFORMATIONAL | ARGUMENTATIVE` to control whether the Counsel pair runs.

Routing rules:
- STATUTORY / CITATION_LOOKUP / PROCEDURAL / PRECEDENT / CONCEPTUAL → `INFORMATIONAL` (skip Counsels, direct to Synthesis)
- RIGHTS / COMPARISON / ARGUMENTATIVE / DEFAULT → `ARGUMENTATIVE` (run Petitioner + Respondent Counsels)

Tested on 7 query types: Counsels skipped on 5 of 7 (saves 2 LLM calls per informational query).

### `legal_fts5.py` — BUILT AND TESTED
SQLite FTS5 with legal compound token normalization. Solves the "Section 302" splitting problem.

Pre-processes text before indexing AND before querying:
- "Section 302 of the Indian Penal Code" → `section_302_ipc` (single token)
- "S. 302 IPC" → `section_302_ipc` (same token — matches!)
- "Article 19(1)(g)" → `article_19_1_g`
- "AIR 1997 SC 3011" → `air_1997_sc_3011`
- "Order XL Rule 1" → `order_xl rule_1`

Includes complete SQLite FTS5 wrapper with `index_chunk()`, `search()`, and batch indexing.

### Usage
```bash
# Chunk a single file:
python chunker.py 70075.json

# Chunk all files:
python -c "
from chunker import chunk_directory
summary = chunk_directory('./data', './chunks')
print(summary)
"

# Test query-time embedding decisions:
python query_embedder.py
```

---

## 📎 Context Hints for Next Session

- **Domain**: Indian legal, data from Indian Kanoon (1036 docs, 76 MB, structured JSON)
- **Goal**: Production-ready, zero-hallucination agentic RAG
- **Architecture**: 7 layers, 28 components, 13 agents, poly-vector embedding
- **Chunking**: 6-stage pipeline, **8 chunk types** (Citation = graph-only, not embedded), never split statutes
- **Agents**: 13 agents in 5 tiers — adversarial pair ONLY on ARGUMENTATIVE queries; **LangGraph** for orchestration
- **Embeddings**: voyage-context-3 (content; +20.54% context boost for judgments only, not statutes) + gemini-embedding-001 (label); intent-based routing saves ~40% API calls
- **BM25**: SQLite FTS5 with legal token normalization (`section_302_ipc` = single token)
- **Observability**: Langfuse (not LangSmith)
- **Court hierarchy**: SC=1.0 > HC=0.70 > Privy Council=0.55 (persuasive) > District=0.35 > Tribunal=0.25 > Commission=0.20
- **Four modules built**: `chunker.py` v2, `graph_ranker.py`, `query_embedder.py` (with adversarial routing), `legal_fts5.py`
- **L0 summary_text**: title + citations + topic keywords (NOT a headnote — IK JSON has no headnotes)
- **Deferred to Phase 2**: per incuriam detection, Elasticsearch, Airflow
- **MVP stack**: Qdrant + Neo4j + Langfuse (Docker) + SQLite FTS5 + LiteLLM + LangGraph (in-process)
- **ALL 15 audit issues resolved** — 0 remaining
- **Next step**: Wire the 3 LLM TODO calls in chunker.py, then build embedding pipeline + store writes

---
*Update this file at every meaningful milestone.*
