# Project: Agentic Legal Assistant (Hackathon)

> **Maintenance instruction (for Claude/Claude Code reading this file):**
> Update this file whenever architecture, conventions, schemas, or build status change.
> Do this proactively at the end of any session where something material changed —
> don't wait to be asked. Keep sections current rather than appending a changelog.
> Last updated: 2026-06-20

## 1. What this project is

An agentic RAG system that answers legal questions by routing a user query through
a pipeline of agents and modules that retrieve evidence, verify it against actual
statutory conditions, and only then generate an answer — every claim must trace
back to a verified, surviving piece of evidence. No agent guesses ahead of evidence;
statute identification is a *finding*, not a *premise*.

**Scope constraints:**
- **Scoped only to Indian Legal System**
- **Civil cases only.** No criminal law. This narrows which statutes/checklists are ever built and keeps the Checklist Resolver's cache scoped to one domain.
- **~1,000 source documents total.** Small, fixed corpus — not a scale problem. The
  priority is retrieval *correctness* on this set, not throughput or indexing at scale.
  Don't over-engineer for scale we don't have; do make sure recall is solid on what we do have.

Built for a hackathon. Two-person team:
- **Me (this repo's primary focus): agent orchestration** — Query Agent, Checklist
  Resolver, Auditor, Adjudicator, and the LangGraph wiring connecting them.
- **Teammate: RAG layer** — vector store, chunking, embeddings, knowledge graph
  (citation edges + community clustering). I consume their output through the
  interface contract in §5 — I don't need their internals. Their code lives in `rag/`.

## 2. Architecture — 3 phases, 3 agents + 2 modules

```
USER QUERY
   │
   ▼
[AGENT: Query Agent] → splits into sub-questions, rates complexity, extracts known
                         facts, flags missing/ambiguous fields
   │
   ▼ (clean structured sub-question objects only)
[MODULE: Researcher]  ← runs per sub-question, parallelizable
  → Pull A: vector semantic search (top-k sized by complexity)
  → Pull B: graph lookup (1-hop always; + community summaries if complex)
  → Pull C: regex statute extraction from the retrieved pool — no LLM, no guessing
   │
   ▼ (candidate pool + statute list)
[MODULE: Checklist Resolver]  ← runs per surfaced statute
  → cache hit? return checklist. cache miss? one LLM extraction call → cache → return.
   │
   ▼ (checklists per provision)
[AGENT: Auditor]  ← the loop lives here
  → checks each checklist item against known facts → ✅ Satisfied / ❌ Fails / ❓ Unknown
  → if ❓ unknowns: ask user the specific missing fact → re-run
  → if no unknowns: output verified surviving set only
   │
   ▼ (verified, cited set only)
[AGENT: Adjudicator]
  → writes final answer, every claim cited to a surviving verified item
  → presents single answer or multiple options depending on what survived
   │
   ▼
FINAL ANSWER
```

**Important: do not reduce this architecture for hackathon time pressure.** All 3
agents + 2 modules, the cache-by-provision-ID mechanism, the regex-only Pull C, and
the ✅/❌/❓ verification step are implemented as specified — not flattened into a
single "RAG + LLM" pass, even if that would demo faster. The one explicitly approved
scope-cut is the community-lookup fallback inside Pull B — see §3, risk 1. That is
the only sanctioned simplification; everything else stays as specified.

## 2a. Agent vs Module — who actually needs to be an LLM-in-a-loop

| Component | Type | Why |
|---|---|---|
| Query Agent | 🤖 True agent | Decides sub-question count, complexity rating, and what counts as ambiguous — judgment calls; no fixed branching logic can make these |
| Researcher | ⚙️ Module | Executes a deterministic complexity→retrieval branching tree that's already fully defined — this is code, not a decision-maker, even though Pull C/checklist steps call an LLM internally |
| Checklist Resolver | ⚙️ Module | Pure mechanical cache check + one structured LLM extraction call on a miss — no decision-making |
| Auditor | 🤖 True agent | Must loop — pauses on ❓ unknowns, formulates a question, waits for the user, re-runs. Decides when it has enough information |
| Adjudicator | 🤖 True agent | Synthesizes across multiple surviving provisions, resolves conflicts between them, decides single-answer vs. multi-option presentation |

Don't wrap Researcher or Checklist Resolver in agent reasoning loops they don't
need — they're plain functions (with an LLM call inside, in Checklist Resolver's
case). Don't under-build Query Agent/Auditor/Adjudicator into fixed pipelines either
— their whole value is the judgment calls a fixed branch tree can't make.

## 2b. Query Agent — detailed design

Query Agent is a true agent (§2a) — it makes judgment calls, not lookups. Its job
is broader than "extract fields": it also has to prevent context loss when it
splits a compound query, and run a multi-step clarification flow before anything
downstream ever sees its output.

### Avoiding context loss across split sub-questions

Splitting a compound query is correct — it keeps each retrieval pass focused — but
naive splitting throws away the relationship between the pieces. Three mechanisms
prevent that:

1. **Shared context object** travels with every sub-question — not just the
   sub-question's own text. It carries the original raw query plus any facts
   already extracted before the split.
2. **Causal links are embedded into the sub-question text itself, before the
   split** — not stitched back on after the fact. E.g. if the original query
   causally links a deposit withholding to a retaliation complaint, that link is
   part of each resulting sub-question's text, not a separate field the
   Adjudicator has to reconstruct later from scratch.
3. **Relationship type is flagged per sub-question** (dependent / independent /
   causal) so the Adjudicator downstream knows whether to synthesize the
   sub-answers together or present them as separate, unrelated findings.

### Reformulation step

Before/alongside extraction, the agent reformulates or rephrases the raw query if
needed, to surface what's actually being asked before fitting it to the schema.
This is a distinct step the agent can take — not silently folded into extraction.

### Full decision flow (runs before anything reaches the Researcher)

```
Raw user input
   │
   ▼
Extract whatever is present → fill schema (required + optional fields)
   │
   ▼
Check: are all REQUIRED fields filled?
   │
   NO → Ask user for the specific missing required field(s)
        → wait → re-run extraction → check again
   │
  YES
   ▼
Check: is the query ambiguous? (one input, multiple valid interpretations)
   │
   YES → present the interpretations as options, ask user to confirm
         e.g. "Are you asking about (A) getting your deposit back,
         or (B) challenging the eviction notice?"
   │
   NO
   ▼
Check: is the query incomplete in a way that changes legal domain/jurisdiction?
   │
   YES → ask that specific question before proceeding
         (e.g. jurisdiction unknown and it materially changes the answer)
   │
   NO
   ▼
Emit clean sub-question object(s) → pass to Researcher
```

Only clean, complete sub-question objects (no missing required fields, no
unresolved ambiguity, no open jurisdiction question) ever reach the Researcher.
This decision flow, the context-preservation mechanisms above, and the splitting
itself are all Query Agent's responsibility — don't push any of this downstream.

**Note on model tier:** §4 currently assigns Query Agent the fast/small model
(`llama-3.1-8b-instant`) on the assumption its job was mostly one-shot extraction.
Given the multi-step decision flow above (extraction → required-field check →
ambiguity check → jurisdiction check, each potentially looping), re-test reliability
once this is built — if the 8B model struggles to hold context across this longer
flow, move it to the balanced tier (`llama-3.3-70b-versatile`) instead of forcing it.

**Re-test result (2026-06-20): 8B FAILED, moved to 70B.** On the live run,
`llama-3.1-8b-instant` returned malformed tool-calls (text-wrapped `<function=...>`,
Python `True` instead of `true`, `null` for array fields) that Groq rejected with
400s. `llama-3.3-70b-versatile` passes the same queries cleanly. Note: `json_schema`
structured-output mode is unsupported on both Llama models on Groq, so we use the
default `function_calling` method.

### Implemented design (2026-06-20) — `agents/query_agent.py` + `agents/schemas.py`

- **Single structured LLM call**, not four. The decision tree above is encoded as
  the *output schema* (`schemas.QueryAnalysis`), not separate API round-trips: the
  gates are surfaced in priority order (`missing_required` > `ambiguous` >
  `jurisdiction`) inside that one call. Faster, fewer rate-limit hits, holistic.
- **Entry point:** `run_query_agent(raw_query, history=None, llm=None) -> QueryAgentResult`.
  Result is `status="ready"` (sub-questions filled) **or** `status="clarify"`
  (`pending_question` filled). On clarify, the caller appends `{question, answer}`
  to `history` and re-invokes — the resume loop, which maps onto a LangGraph
  interrupt later.
- **Required-field gate is MINIMAL by decision (reaffirmed 2026-06-20, B2).** Fires
  only when there is no identifiable legal issue at all (or the query is criminal-law
  / out of scope). Case facts (dates, amounts, clauses, whether notice was given) are
  NEVER asked here — they're deferred to the Auditor's ❓ loop, preserving "no
  guessing ahead of evidence." Concretely: a partial answer that identifies the issue
  (e.g. "eviction for non-payment") proceeds to `ready`; lease-specific facts are the
  Auditor's job, not a re-ask here.
- **Context preservation (§2b mechanisms):** the LLM emits sub-questions only; code
  attaches one shared `SharedContext` (original query + extracted facts) to every
  sub-question, assigns 1-based ids, and preserves `relationship_type` + `depends_on`.
  A visible `reformulated_query` field keeps reformulation a distinct step.
- **Injectable LLM** (`run_query_agent(..., llm=...)`) so the assembly logic can be
  driven by a fake without a key. Verified end-to-end against real Groq via the
  interactive CLI (`main.py`): simple / compound-split / vague / ambiguous /
  jurisdiction / resume-loop all behave correctly (the 8B→70B bump fixed both the
  over-splitting and the malformed-tool-call 400s). The CLI prints the full
  structured JSON each turn and runs the clarify/resume loop in the terminal.
- **Unanswerable clarifications (PART 1).** If the user answers a clarification with
  "I don't know" (regex-detected via `_is_dont_know`) — or the same gate has been
  asked twice (hard cap `MAX_ASKS_PER_FIELD=2`) — the agent stops asking, records the
  gap in `unknown_fields`, and proceeds. `unknown_fields` rides in `shared_context`
  so the Auditor/Adjudicator see the gap is acknowledged, not silently dropped (it is
  distinct from "never mentioned"). For the per-field cap to attribute asks, the
  caller records `kind` on each history turn (`{question, answer, kind}`).
  `extracted_facts` + `unknown_fields` are surfaced on EVERY result (clarify too) for
  visibility.
- **Regression suite:** `tests/test_query_agent.py` — offline (deterministic: don't-know
  regex, cap computation, unknown-field plumbing, assembly) + live scripted multi-turn
  cases A–E via `run_scripted(query, answers)`. B2 resolved to minimal-required (see
  §2b required-field note); suite asserts the minimal-design invariants.

## 3. Key risks to watch for (hackathon-specific)

1. **Community clustering will be low-signal at ~1,000 docs.** That path pays off
   at 100k+ docs, not here. Strong semantic search (Pull A) + one-hop graph (Pull B)
   is likely sufficient for most queries at this scale. Build the community lookup
   as a fallback, but don't let it dominate build time or the demo. This is the one
   approved scope-cut referenced in §2 — everything else in the architecture stays.
2. **Checklist cache cold start.** At demo time, most provisions will be cache
   misses, so nearly every query pays LLM cost + latency on first touch. Mitigation:
   pre-populate the cache for the ~20-30 statutes most likely to appear in the
   dataset before the demo, or deliberately demo a cache-hit case.
3. **The ❓ loop is the most compelling feature — and the easiest to leave to
   chance.** It's what shows reasoning instead of just retrieval. Have a crafted
   demo query ready that reliably triggers an Auditor ❓, don't assume one will
   come up naturally.
4. **Groq free-tier daily token cap.** `llama-3.3-70b-versatile` is limited to
   ~100K tokens/day on the on-demand free tier. A full live test run of the Query
   Agent suite (~13 multi-turn cases) burns ~25-30K tokens, so ~3 runs/day exhausts
   it (then 429 `rate_limit_exceeded`). Mitigation: run the live suite sparingly, lean
   on the offline layer during iteration, demo on a fresh budget, or upgrade tier.
   The model is overridable via the `QUERY_AGENT_MODEL` env var (no code change) —
   temporarily point at another Groq model with a separate budget, then clear it to
   revert to `DEFAULT_MODEL` (`llama-3.3-70b-versatile`). As of 2026-06-20 it is
   temporarily set to `openai/gpt-oss-20b` (NOT yet live-verified for the schema).

## 4. Tech stack & model selection

- **Orchestration:** LangGraph (`StateGraph`) — agents are nodes, routing is conditional edges
- **LLM provider:** Groq (`langchain_groq.ChatGroq`) — open-weight models only, free tier,
  fastest inference available (LPU hardware). `GROQ_API_KEY` in `.env`.
- **Structured output:** Pydantic models + `.with_structured_output(...)` for every agent that emits JSON
- **Env/secrets:** `.env` + `python-dotenv`
- **Package/env management:** `uv` — always `uv run <file>.py` / `uv add <package>`, never bare `pip`/`python`

**Models are tiered by how much reasoning each component's job actually needs** —
don't default to the biggest model everywhere, and don't default to the smallest either:

| Tier | Model (Groq) | Used by | Why this tier |
|---|---|---|---|
| Fast / simple | `llama-3.1-8b-instant` | — (Query Agent started here; re-tested 2026-06-20 and moved to Balanced — see §2b) | High-volume, low-ambiguity structured extraction — speed over deep reasoning. No current user; revisit if a cheaper agent appears |
| Balanced | `llama-3.3-70b-versatile` | Query Agent (moved here after 8B failed tool-calling, §2b), Checklist Resolver (one-time extraction per provision), Adjudicator (final answer synthesis) | Needs solid reading comprehension / writing quality; Checklist Resolver calls are cached so cost is a one-time hit per provision, not per request |
| Deep reasoning | `deepseek-r1-distill-llama-70b` | Auditor (fact-vs-checklist verification) | Highest-stakes step — false ✅/❌ here breaks the whole citation guarantee, worth spending the slower/more careful model here |
| No LLM | — | Researcher Pull C (regex statute extraction) | Deliberately mechanical — see §7 |

Re-evaluate this table if any agent's outputs look unreliable in testing — moving an
agent up a tier is a one-line model-string change, not a refactor.

## 5. Integration contract with the RAG teammate

This is the only RAG detail that matters to my agent code — the shape of what
comes back, not how it was built. Update this section the moment the real
interface is finalized; until then these are the target signatures my code
should mock/stub against.

```python
# Pull A — semantic search
def vector_search(query: str, top_k: int) -> list[Chunk]:
    """Returns top-k chunks by similarity. Chunk has: text, doc_id, score, metadata."""

# Pull B — graph expansion
def graph_expand(doc_ids: list[str]) -> GraphExpansion:
    """Returns one-hop citation neighbors + (if complexity != 'simple' or
    A/B results are weak/conflicting) the community summary for each doc's cluster."""
```

**Do not duplicate teammate's chunking strategy, embedding model choice, or
graph-build details here** — if my code doesn't call it directly, it doesn't
belong in this file. Link to their docs instead if needed.

**Complexity drives three Researcher decisions** (rated per sub-question by the
Query Agent): (1) top_k sizing for Pull A, (2) **local one-hop vs global
community-summary graph search** for Pull B, and (3) whether the §3-risk-1 community
fallback fires at all. `simple` is the literal value the Researcher checks against,
so the enum string must stay `"simple"`.

**Intent divergence (flagged, unresolved).** The teammate's
`rag/query_embedder.embed_query(query, intent, ...)` routes retrieval by an `intent`
label (STATUTORY / PRECEDENT / …). This contract (`vector_search(query, top_k)`)
routes by *complexity*, not intent, and the Query Agent does **not** emit an intent.
Resolve when wiring the Researcher: either adapt to top_k-only, or have the Query
Agent additionally emit a per-sub-question intent to feed their embedder.

## 6. State schema conventions

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]
    sub_questions: list[SubQuestion]   # Query Agent output — concrete schema in
                                         # agents/schemas.py (SubQuestion: id, text,
                                         # complexity, relationship_type, depends_on,
                                         # known_facts, shared_context)
    evidence_pool: list[Chunk]          # Researcher output (Pulls A+B combined)
    surfaced_statutes: list[str]        # Pull C output
    checklist: list[str]                # Checklist Resolver output
    audit_result: dict                  # Auditor's ✅/❌/❓ buckets
    pending_question: str | None        # set when Query Agent or Auditor needs the user
```

## 7. Key decisions already locked in (don't relitigate these)

- Pull C (statute surfacing) is **regex pattern matching, not an LLM call** — it extracts statutes mentioned in already-retrieved text, it does not guess a statute and retrieve toward it.
- Checklist Resolver is a **mechanical cache, not a reasoning agent** — LLM is called exactly once per provision, ever, then cached by provision ID.
- The user is only interrupted for a missing fact when the Auditor produces an actual ❓ on a real checklist item — never a vague "not sure if I have enough info."
- Jurisdiction is checked with the same Auditor mechanism as substantive law, just against a separate checklist (built from CPC provisions).
- Civil cases only — no criminal-law statutes or checklists in scope.
- Sub-questions must never lose context across a split — see §2b for the three required mechanisms.

## 8. Working style while building this

- **Explain while implementing, don't just hand over finished code.** When building
  each component, walk through the approach before/while writing it, and flag any
  ambiguous design decision back to the user instead of silently picking one.
- **Ask before assuming** on anything not already pinned down in this file (e.g. exact
  regex patterns for Pull C, exact checklist-extraction prompt wording) — these are
  open implementation details, not yet locked-in decisions.

## 9. Code style

- Clear, concise code. Brief comments only where the *why* isn't obvious from the
  code itself — no comment-per-line, no restating what the code already says.
- Prefer small, single-purpose functions per agent node over one large function.

## 10. Build status

| Component | Type | Status | Model |
|---|---|---|---|
| Query Agent | 🤖 Agent | ✅ Done — `agents/query_agent.py`, `agents/schemas.py`; clarify/resume loop with don't-know + 2-ask-cap handling (PART 1) and `unknown_fields` tracking. Scripted suite `tests/test_query_agent.py` (A–E). Entry `run_query_agent(...)` + `main.py` CLI; wraps cleanly for LangGraph | `llama-3.3-70b-versatile` (8B failed re-test, see §2b) |
| Researcher (Pull A/B) | ⚙️ Module | ⬜ Not started — blocked on teammate's RAG interface | n/a (calls teammate's functions) |
| Researcher (Pull C) | ⚙️ Module | ⬜ Not started — regex extraction, independent, can build anytime | no LLM |
| Checklist Resolver | ⚙️ Module | ⬜ Not started | `llama-3.3-70b-versatile` |
| Auditor | 🤖 Agent | ⬜ Not started | `deepseek-r1-distill-llama-70b` |
| Adjudicator | 🤖 Agent | ⬜ Not started | `llama-3.3-70b-versatile` |
| Graph wiring (LangGraph) | — | ⬜ Not started — prototype chatbot validated the pattern, real graph not yet built | n/a |