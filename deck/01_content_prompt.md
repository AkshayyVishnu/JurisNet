# JurisNet Deck — Content-Generation Prompt

Paste everything in the box below into ChatGPT/Claude. It returns slide-by-slide content
(title, bullets, visual, speaker notes) for ≤20 slides that you then lay out in Canva. Pair it
with `02_screenshots.md` (real screenshots), `03_diagrams.md` (Mermaid diagrams + image prompts),
and `RESULTS.md` (real eval numbers — paste them where the prompt asks).

---

```
You are a senior pitch-deck writer for a hackathon final. Write the COMPLETE content for a
≤20-slide deck for "JurisNet", our submission to *The Arch: RAG & Agentic AI* hackathon
(Legal Services track). Audience = technical judges + industry mentors. Tone = balanced
technical and business (~60% technical), crisp and confident, no fluff, no clichés.

THE CHALLENGE WE ANSWER (use as the narrative spine):
"Build scalable, production-ready Agentic AI and Advanced RAG frameworks. The best teams will
not just build basic wrappers; they will architect systems that maintain absolute contextual
fidelity under rigorous stress tests and deliver clear, real-world utility."

OUTPUT FORMAT — for EACH slide output exactly:
  ## Slide N — <punchy title>
  - 3–6 tight bullets (each ≤14 words, parallel phrasing; lead with the point)
  - Visual: <which screenshot or diagram from the asset list, or "table">
  - Speaker notes: <2–4 sentences a presenter would say>
Keep total ≤20 slides. Every slide must earn its place. Lead problem→solution where natural.

HARD CONSTRAINTS (accuracy & honesty — do not violate):
- Use ONLY the verified facts below. Do not invent numbers, benchmarks, partners, or features.
- Comparisons to other systems are CAPABILITY-based (✓/✗), never invented benchmark numbers.
- Quantitative results come ONLY from the EVAL RESULTS block (paste in). If that block is empty,
  make Slide 16 a qualitative capability slide and say metrics are "measured on a 54-question
  gold set (run pending)".
- Label these as ROADMAP, not done: Global/DRIFT GraphRAG search, span-level attribution,
  the remaining deferred agents, a full automated eval suite.
- State "zero fabricated citations" as a DESIGN GUARANTEE enforced by the Citation Verifier
  (a deterministic, no-LLM check), unless the eval block reports a measured number.

VERIFIED FACTS ABOUT JURISNET (ground truth):
- Domain: Indian civil law (Code of Civil Procedure). Corpus = 1,071 documents:
  637 judgments + 142 CPC statute sections + 292 cleaned CPC Orders/Rules (39 junk filtered out).
- Retrieval = HYBRID, 4 sources fused by Reciprocal Rank Fusion (RRF), weighted by query intent,
  with per-source de-duplication so one doc can't be over-counted:
    1) dense content vectors (Qdrant, 30,564 chunks, voyage-4-large embeddings, 1024-dim)
    2) dense label vectors (statute/rule identifiers)
    3) legal-tokenized BM25 keyword search (SQLite FTS5 — e.g. "Section 302 IPC" stays one token)
    4) citation knowledge graph traversal (Neo4j, 1,071 nodes / 6,776 edges; judgment↔statute↔rule)
- Legal-aware MULTI-LEVEL chunking: L0 headnote · L1 facts · L2 paragraph(+overlap) · L3 atomic
  sentence · ratio (binding holding) · statute/rule provision. (LLM-enriched, deterministic-grounded.)
- TWO answer modes share the retrieval layer:
   • FAST: Query Understanding → Hybrid Retrieve → Synthesis (IRAC answer) → Citation Verifier.
     Streams the answer token-by-token in the web UI.
   • DEEP (agentic): Query Agent (splits the question, classifies it, asks to clarify if ambiguous)
     → Researcher (vector+graph retrieval + regex statute extraction) → Checklist Resolver (turns a
     provision into its statutory conditions, cached) → Auditor (checks each condition against the
     user's facts: ✅ satisfied / ❌ fails / ❓ unknown — and PAUSES to ask the user for a missing
     fact) → Adjudicator (writes the grounded verdict). Wired in LangGraph with interrupt/resume.
- CONTEXTUAL FIDELITY is the core thesis: "no agent guesses ahead of evidence" — statute
  identification is a *finding*, not an assumption; conclusions are audited condition-by-condition
  against the user's stated facts; and the Citation Verifier checks every cited source against the
  retrieved set AND the corpus graph, flagging anything fabricated (the Mata v. Avianca failure mode).
- PRODUCTION-READINESS: multi-provider LLM (Groq / Cerebras / Gemini) with round-robin API-key
  rotation + per-key cooldown + provider fallback (survives rate-limit storms); a persistent
  embedding cache (never re-embeds unchanged text); cloud-hosted Qdrant + Neo4j Aura; and a
  React + FastAPI app that STREAMS pipeline stages live over SSE.
- Verified working end-to-end on the live stores: all four retrieval routes and the full agentic
  ❓-loop (clarify → resume → adjudicate).

WHY VANILLA RAG FAILS FOR LAW (use for Slides 2–3):
- Flat single-vector retrieval misses exact statute/rule identifiers and precedent structure.
- No grounding guarantee → hallucinated case citations (the real Mata v. Avianca sanction).
- No reasoning over statutory CONDITIONS → it summarizes text instead of testing whether the law
  actually applies to the user's facts.
- No notion of authority/precedent → can't tell binding ratio from passing remark.

EVAL RESULTS (measured locally on the 54-question gold set; 50 answerable + 4 abstain traps):
- Retrieval Recall@5 = 86%, Recall@10 = 88%, Recall@20 = 88%
- MRR (rank of the primary source) = 0.531
- Citation accuracy: mean confidence 100%, and 100% of answers had ZERO fabricated citations
- These are real numbers from our hybrid retriever + Citation Verifier on the live stores.
  (So "zero fabricated citations" is MEASURED here, not only by-design.)

SLIDE OUTLINE (follow this order; ≤20):
1  Title — "JurisNet — agentic, graph-grounded legal RAG" + one-line positioning + team + track
2  The problem — production agentic RAG + contextual fidelity under stress + real utility; the
   hallucinated-citation stakes (Mata v. Avianca)
3  Why vanilla RAG fails for law
4    (Diagram A)
5  Domain & corpus (1,071 docs; civil/CPC; why a curated legal corpus matters)
6  Legal-aware multi-level chunking (Diagram C)
7  Hybrid retrieval → RRF, 4 sources (Diagram B)
8  Knowledge graph — Neo4j citation graph (SCREENSHOT) + why precedent/co-citation structure wins
9  The agentic pipeline — Query Agent → Researcher → Checklist → Auditor → Adjudicator (Diagram D)
10 Contextual fidelity = the grounding guarantee + Citation Verifier (Diagram E)
11 Two modes — Fast (streaming, cited) vs Deep (checklist/audit) (UI screenshots)
12 Live product walkthrough (UI screenshots)
13 Comparison matrix — JurisNet vs Vanilla vs GraphRAG vs Agentic RAG (TABLE from 03_diagrams.md)
14 Production-readiness & scale (key rotation, cache, cloud stores, SSE)
15 Stress tests & fidelity — how fidelity holds under pressure (audit loop, verifier, graph)
16 Results — real eval numbers if provided, else qualitative
17 Real-world utility — users (litigants, paralegals, court clerks, law students) + use cases
18 Tech stack — Qdrant · Neo4j · FTS5 · voyage-4-large · LangGraph · Groq/Cerebras/Gemini · React/FastAPI
19 Roadmap — Global/DRIFT GraphRAG, span-level attribution, deferred agents, expanded eval
20 Closing — one-line impact + the ask

ASSET LIST (use these exact references in each slide's "Visual:" line):
- Diagrams A–E and the comparison TABLE → see 03_diagrams.md
- Screenshots: Neo4j graph (wide + ego), Fast-mode answer, Deep-mode (stage tracker / clarify /
  adjudication), landing page, architecture panel → see 02_screenshots.md

Now produce all the slides.
```
