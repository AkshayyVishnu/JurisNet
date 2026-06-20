# 🧱 JurisNet — Chunking & Ingestion Stages

> Created: Session 3 — June 20, 2026
> Supersedes the Phase 1 chunking section of `IMPLEMENTATION_PLAN.md`, which assumed
> the raw Indian Kanoon API schema. The real `LEGAL_DATA` schema is different (see below),
> so chunking is split into **Stage A (structural)** + **Stage B (LLM enrichment)**, with
> **Stage C (corpus expansion)** as an additive, incremental step for new data.

---

## 0. Why this exists — the schema reality

`chunker.py` (v2) was written for the **raw Indian Kanoon API** schema (`data["doc"]`
HTML with `<p data-structure="held">` section labels, `tid`, `docsource`, `citedby`).
**Our actual corpus uses a cleaned, flat schema** — verified consistent across all files:

**Judgments (637 files)** — keys:
`doc_id, title, date, body, cited_provisions[], cited_judgements[], orders_and_rules[]`

**Provisions / statutes (142 files)** — keys:
`doc_id, title, body, cases_citedby[]`

### Measured corpus facts (drive every design choice below)
| Finding | Value | Implication |
|---|---|---|
| Schema consistency | 100% (both types) | No edge-case parsing |
| `cited_provisions` resolve in-corpus | **100%** (5,299 edges) | Statute graph is the **strong backbone** |
| `cases_citedby` resolve | **99.9%** (703 edges) | Reverse statute links solid |
| `cited_judgements` resolve | **2.2%** (70 / 3,142) | ⚠️ Precedent graph is **mostly external** today → fixed by Stage C |
| Judgment body size | median ~26K chars, **max ~381K (~95K tokens)** | Must chunk; long docs need long-context LLM |
| Provision body size | median ~660 chars | One chunk each (no splitting) |
| Numbered paragraphs present | 609 / 637 (95.6%) | Reliable L2 segmentation |
| Court detectable from header | ~95% (28 need fallback) | Authority scoring works |
| Section labels (HELD/FACTS/…) | **essentially absent** | L1/L3/ratio **cannot** be parsed — must be LLM-derived |
| HTML entities in body | pervasive | Must `html.unescape` |

**Consequence:** structure (L1/L3/ratio) must be *derived by LLM*, not parsed. Graph
density (judgment→judgment) must be *expanded with more data*, not extracted differently.

Reusable from `chunker.py`: the dataclasses (L0/L1/L2/L3/Ratio/StatuteProvisionChunk/
CitationEdge), `court_authority_score`, `_breadcrumb`, `split_into_propositions`,
`_generate_statute_aliases`.

---

## 1. Stage A — Structural chunking (deterministic, NO LLM)

**Goal:** turn raw JSON → chunk files using only rules. Fast, reproducible, never blocks.

**Script:** `pipeline/01_chunk.py` → writes `chunks/judgments/`, `chunks/provisions/`,
and merged `chunks/_citation_edges.json`.

### Produces
- **L0 (doc summary chunk)** — per judgment: `title + date + court + section refs`
  (derived from `cited_provisions` titles + `orders_and_rules`). No headnote available.
- **L2 (paragraph chunks)** — segment `body` by numbered markers (`1.`, `2.`, …) with
  1-paragraph sliding overlap. The 28 unnumbered docs → fixed-size sentence-window fallback.
  **This is the primary retrieval unit for the MVP.**
- **Statute provision chunk** — one `StatuteProvisionChunk` per provision; parse
  `act_name` + `section_ref` from title (e.g. "Section 22A in The Code of Civil Procedure, 1908"),
  generate aliases.
- **Citation graph edges** (built directly from pre-resolved ID lists — no regex):
  - judgment → `cited_provisions`  ⇒ `CITES_STATUTE` (100% in-corpus)
  - provision → `cases_citedby`     ⇒ `CITED_BY_CASE` (reverse, 99.9% in-corpus)
  - judgment → `cited_judgements`   ⇒ `CITES_CASE` (keep all; tag `in_corpus: bool`; 2.2% today)
  - `orders_and_rules` strings       ⇒ kept on L0 metadata (procedural refs, no IDs yet)

### Normalization
- `html.unescape(body)`, collapse whitespace, strip page-footer noise
  ("Signature Not Verified", "Page X of Y").
- Court: scan first ~400 chars of body → `court_authority_score`; fallback `DEFAULT_SCORE`.

### ✅ Checkpoint A
- `chunks/judgments/` = 637 files, `chunks/provisions/` = 142 files.
- Every chunk text starts with a `[breadcrumb]`.
- Statutes produce exactly ONE chunk (provisos intact, not split).
- `chunks/_citation_edges.json` non-empty; statute edges dominate; `in_corpus` flag present.
- Log docs producing 0 L2 chunks (the 28 unnumbered → confirm fallback fired).

---

## 2. Stage B — LLM enrichment (L1 / L3 / ratio)

**Goal:** add the structure the raw text lacks. This is JurisNet's **main legal-quality
lever** — and because the precedent graph is sparse (until Stage C), it is the *only*
source of holding-level reasoning in the MVP. Do it; don't skip it.

**Script:** `pipeline/02_enrich.py` — reads Stage A chunk files, **adds** fields, rewrites
them. Idempotent + **resumable** (checkpoint per `doc_id`); never re-embeds (Stage A output
is untouched at the vector level).

### Design
- **Model: Gemini 2.5 Flash** (the 20 `GOOGLE_API_KEY*` keys, round-robin via `llm_keys.py`).
  Long context handles the 95K-token outliers in one call. Groq 8B (~8K ctx) **cannot**
  ingest big docs → not used for this stage.
- **1 LLM call per judgment** → structured JSON: section spans (L1) + ratio. Combined
  because both need whole-doc understanding.
- **L3 atomic = NO LLM.** Derive deterministically by sentence-splitting the
  reasoning/held spans that L1 returns (`split_into_propositions`).
- **Long-doc handling:** docs over the safe context budget → map-reduce (section-type
  per window, then merge). Most docs fit in one call.

### Produces (added to each judgment chunk file)
- **L1 (section chunks)** — typed spans: `FACTS / ISSUES / ARGUMENTS / REASONING / HELD / ORDER`.
- **L3 (atomic chunks)** — sentence-level units from REASONING/HELD (for fine-grained
  grounding in the Citation Verifier).
- **ratio chunks** — the binding rule(s) the case establishes (vs. obiter).
- (Later/optional) **issue-held pairs**, and **typing of `CITES_CASE` edges**
  (FOLLOWED / RELIED_ON / DISTINGUISHED / OVERRULED) — most useful once Stage C makes
  those edges in-corpus.

### Cost / time (637 judgments)
- ~637 calls, ~6M input + ~1M output tokens. Quota is **not** the bottleneck across 20 keys.
- **Compute: ~20–30 min** full run (rotation + light concurrency); ~45–75 min single-key.
- **First-time effort incl. prompt tuning + retries: ~1–1.5 hr.** Resumable, so never one block.
- Budget ~10–20% retry overhead for JSON-parse/timeout on the giant docs.

### ✅ Checkpoint B (10-doc sample)
- Ratio chunks present and non-trivial; L1 spans cover the doc; L3 parses as valid units.
- JSON schema-validated; failures logged with `doc_id` and retried, not silently dropped.

> **Ordering decision:** Run Stage A → Stage B → **index once** (so the first index has full
> structure). Safety valve: if Stage B stalls, you can index Stage A output alone and still
> demo. Adding Stage B chunks later is an **incremental upsert** (see §4), never a full rebuild.

---

## 3. Stage C — Corpus expansion (judgment→judgment + orders/rules)  ⟵ NEW DATA

**Trigger:** new data arrives with (a) the **cited judgments themselves** (so
`cited_judgements` IDs resolve in-corpus) and (b) **`orders_and_rules`** entries under
the CPC (and similar procedural codes) as first-class documents.

**Goal:** raise internal graph density and add procedural-rule nodes — **purely additive.
Existing chunks, embeddings, and the DB are NOT rebuilt.**

**Script:** `pipeline/04_expand.py` — same Stage A→B logic, run only over the *new* docs,
then incremental-upsert. Existing `doc_id`s are skipped (idempotent).

### 3.1 New judgment documents (precedent graph fix)
- Run **Stage A + Stage B** over the new judgment JSONs only.
- Re-evaluate the `in_corpus` flag on **all** `CITES_CASE` edges (old + new): edges that
  pointed "external" may now resolve → flip to in-corpus and load into Neo4j.
  - This is a graph-only update (`MERGE` edges) — **no re-embedding** of existing text.
- Expectation: the 2.2% judgment→judgment resolution rises sharply after a 1-hop expansion,
  turning on real precedent traversal (FOLLOWED / DISTINGUISHED / OVERRULED reasoning).

### 3.2 Orders & Rules as documents (e.g. CPC Orders/Rules)
- Today `orders_and_rules` are bare strings on L0 (e.g. "Order XXI Rule 11").
- When the actual rule text arrives, treat each as a **provision-like node**:
  - Chunk with the **statute path** (one `StatuteProvisionChunk` each; parse Order/Rule ref).
  - Add nodes to Neo4j; add `CITES_RULE` edges from judgments whose `orders_and_rules`
    strings match (normalize "Order XXI Rule 11" ↔ canonical form).
  - Embed + upsert into Qdrant/FTS5 like any other provision.

### 3.3 Where to source it
- **Preferred: official Indian Kanoon API** (per-doc, ToS-clean, reliable).
- **Avoid raw web scraping** for anything you'll demo — against IK ToS, rate-limited,
  fragile, IP-ban risk.
- Snowball strategy: use existing docs' `cited_judgements` IDs as the fetch list (1 hop),
  optionally 2 hops if quota/time allow. Mind Voyage embedding quota — each hop can 3–5× the corpus.

### ✅ Checkpoint C
- New `doc_id`s added; **no existing point/row/node mutated** except `CITES_CASE`
  `in_corpus` flips and newly-resolvable edges.
- `cited_judgements` in-corpus resolution % measurably increased.
- Order/Rule nodes queryable; `CITES_RULE` edges present.

---

## 4. Why adding chunks later needs NO full re-index

Indexing = embed chunks → write to 3 stores. All three support **incremental adds**:

| Store | Add new chunks later | Touches existing? |
|---|---|---|
| **Qdrant** | `upsert` new points (new IDs) | No |
| **SQLite FTS5** | `INSERT` new rows | No |
| **Neo4j** | `MERGE` new nodes/edges (idempotent) | No |

So Stage B chunks and Stage C documents are **embedded once (only the new ones) and
inserted** — existing L0/L2/statute vectors are never recomputed.

**Full re-index is required ONLY if:**
1. The **embedding model or dimension changes** (new vector space) — we stay on
   `voyage-4-large` / **1024**, so never for that reason.
2. The **boundaries of existing chunks change** (e.g. re-segmenting current L2) — adding a
   *new* chunk type (L1/L3/ratio) or *new* documents does **not** do this.

---

## 5. Pipeline order (single source of truth)

```
Stage A  pipeline/01_chunk.py     structural chunks + statute graph        (no LLM)
Stage B  pipeline/02_enrich.py    + L1 / L3 / ratio                        (Gemini Flash)
INDEX    pipeline/03_index.py     embed once → Qdrant + FTS5 + Neo4j       (voyage-4-large)
─────────────────────────────────────────────────────────────────────────────────────
Stage C  pipeline/04_expand.py    new judgments + orders/rules, A+B on new docs,
                                   incremental upsert, flip CITES_CASE in_corpus   (additive)
```

Stages A, B, and C are all **additive and incremental** — none forces a rebuild of work
already done.
