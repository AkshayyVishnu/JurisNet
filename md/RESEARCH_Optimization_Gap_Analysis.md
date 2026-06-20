# 🔬 Optimization & Gap Analysis — Indian Legal Agentic RAG

> Date: June 20, 2026
> Method: Cross-checked the current plan (`PROJECT_MEMORY.md`) against 2025–2026 papers on agentic/reasoning RAG, legal RAG faithfulness, retrieval, and Indian legal benchmarks.
> Goal: Find good methods NOT yet in the project, ranked by leverage for an Indian-legal chatbot.

---

## 0. What the plan already does well (no change needed)

Hybrid retrieval (dense + BM25 + graph) with RRF, cross-encoder reranking, adversarial Counsel pair, mandatory Citation Verifier, NLI Groundedness Critic, ReAct orchestration, Langfuse + ragas, poly-vector embeddings. These are state-of-practice. **Do not re-open them.** The gaps below are genuinely additive.

---

## 1. HIGH leverage — adopt these

### 1.1 Adaptive retrieval depth (replace the fixed 12-step ReAct budget)
**Gap:** The Orchestrator uses a *fixed* 12-step budget. The 2025–2026 reasoning-RAG line (Search-R1, R1-Searcher, AutoSearch, the System-1/System-2 survey) shows retrieval depth should be **dynamic and confidence-gated** — keep retrieving only while confidence is below threshold, stop early otherwise.
**Why it matters here:** A statute lookup ("What does Section 302 IPC say?") should terminate in 1 hop; a doctrinal argument may need 8. A fixed budget over-spends on easy queries and under-serves hard ones.
**Action (no RL training required):** Add a **confidence-gated stop condition** to the Orchestrator — after each retrieval round, the Groundedness/Reflection signal decides continue-vs-stop, capped by a max budget. This is the cheap, prompt-level version of Search-R1's learned policy.
**Effort:** Low. Reuses Reflection + Groundedness Critic you already have.

### 1.2 Claim/span-level attribution + abstention gate
**Gap:** Citation Verifier checks that cited cases *exist*; Groundedness Critic does whole-answer NLI. Neither does **per-claim span matching**. Stanford's 2025 legal-RAG study found even well-built legal RAG **fabricates citations** (asserts a source supports a proposition when it doesn't). REFIND (SemEval-2025) and the abstention-policy hallucination benchmarks show the fix: match **each generated claim to a specific retrieved span**, flag/strip unsupported claims, and **abstain** when evidence is insufficient.
**Why it matters here:** This is the *Mata v. Avianca* failure mode you already flagged — but your current check is coarser than the research standard. Legal users need "I cannot find authority for this" over a confident fabrication.
**Action:** (a) Upgrade Groundedness Critic to **sentence/claim-level attribution** (each output sentence → supporting span ID, else flagged). (b) Add an explicit **Abstention gate**: if a sub-claim has no supporting span above threshold, refuse or hedge that claim rather than emit it.
**Effort:** Medium. Extends the existing critic; pairs naturally with L3 atomic chunks (which you built exactly for this).

### 1.3 Legal-specific evaluation (not just ragas)
**Gap:** Eval plan is ragas + promptfoo (generic). Missing legal/Indian-specific evaluation.
**Add:**
- **IL-TUR** (Indian legal benchmark — statute retrieval, rhetorical-role labeling, judgment prediction; multilingual incl. Hindi).
- **LRAGE** (Legal RAG Evaluation tool — legal-specific retrieval + generation metrics).
- **"Are LLMs Court-Ready?"** (Indian SC Advocate-on-Record exam) as a reasoning stress test.
- **AQgR**-style retrieval AP on a held-out Indian case-law set.
**Why it matters:** Generic faithfulness ≠ correct statute identification or precedent ranking. You need court-hierarchy-aware retrieval metrics.
**Effort:** Low–Medium (wire benchmarks into the existing evaluator).

---

## 2. MEDIUM leverage — strongly consider

### 2.1 Late-interaction (ColBERT/ColPali-style) reranker for legal exact-match
**Gap:** Retrieval is single-vector dense + cross-encoder rerank. **Late interaction** (ColBERTv2 token-level MaxSim) gives fine-grained token matching — strong exactly where legal text is hardest: precise identifiers and phrasing ("Section 302", "Article 19(1)(g)", party names). Qdrant supports multivectors natively.
**Why it matters:** Complements your FTS5 token-normalization trick with a *semantic* token-level match, catching paraphrased-but-precise references BM25 misses.
**Trade-off:** ~10× storage for token vectors (ColBERTv2 quantization mitigates). Suggest as a **reranking stage over top-50 candidates**, not a full index, to bound cost.
**Effort:** Medium.

### 2.2 Reconsider query augmentation — for legal specifically (AQgR, Indian)
**Note:** The plan eliminated a Query Rewriter (MA-RAG ablation: "no measurable benefit"). But that ablation was *general-domain*. **AQgR (Indian case law, 2025)** shows multi-query reformulation + generated clarifying questions + structured judgment summaries measurably improve **Indian** legal retrieval (vocabulary gap between lay phrasing and judicial language is large).
**Reconciliation:** You likely get most of this *for free* from the **DRIFT follow-up generation** in the previous report — DRIFT's primer already spawns sub-questions. So: don't add a standalone rewriter; instead ensure the **DRIFT/Decomposer path performs multi-query expansion** for ARGUMENTATIVE/CONCEPTUAL legal queries. Verify, don't duplicate.
**Effort:** Low (folds into DRIFT work already proposed).

### 2.3 Verify "late chunking" is actually covered, not assumed
**Note:** The plan dropped contextual enrichment, claiming "voyage-4-large bakes it in." That is *plausibly* true — voyage-context-3/4 are contextualized-chunk-embedding models, the same family as Jina's **late chunking** (embed full doc, pool per chunk → preserves cross-chunk context). **But this only holds if you call the contextual/document-aware API path**, passing the surrounding document, not embedding chunks in isolation.
**Action:** Confirm the indexing pipeline feeds document context to voyage-4-large (not bare chunks). If chunks are embedded standalone, you are **not** getting late-chunking benefits and the "+20.54% context" claim doesn't apply. Also consider **selective contextualization** ("good" vs "bad" chunks — only contextualize chunks that need it) to save tokens.
**Effort:** Low (a verification + possible pipeline fix, not a new component).

---

## 3. FUTURE / Phase 2 — promising but heavier

- **RL-trained retrieval policy (Search-R1 / AutoSearch / MARAG-R1 / Search-P1):** Learn when/what/how-deep to retrieve from outcome rewards. High ceiling, but needs training infra + reward design — defer until the heuristic adaptive-depth (1.1) plateaus.
- **MCTS-RAG / tree-of-search retrieval:** Monte-Carlo search over retrieval paths for hard multi-hop precedent chains. Note: you already eliminated Tree-of-Thought for *generation* (legal reasoning is sequential), but MCTS over the *citation graph* is a different, defensible use.
- **Sparse-autoencoder faithfulness (2512.08892):** Steer generation toward grounded features. Research-grade; watch, don't build.
- **Process-supervised verification (TreePS-RAG):** Dense per-step rewards for the verification chain. Phase 2.

---

## 4. Explicitly DON'T add (avoid over-engineering)

- A standalone Query Rewriter agent — superseded by DRIFT follow-ups (§2.2).
- ColPali/visual late-interaction over PDFs — your data is already structured JSON; no PDF parsing needed.
- Full ColBERT *index* (vs rerank stage) — storage cost not justified at 779 docs.
- RL retrieval training before the prompt-level adaptive-depth heuristic is exhausted.

---

## 5. Recommended sequencing

1. **Confidence-gated adaptive retrieval depth** (§1.1) — cheap, immediate quality+cost win.
2. **Claim-level attribution + abstention gate** (§1.2) — biggest risk reduction (anti-fabrication).
3. **Verify late-chunking is actually wired** (§2.3) — cheap correctness check on a core assumption.
4. **Legal-specific eval harness: IL-TUR + LRAGE** (§1.3) — so you can *measure* 1–3.
5. **Late-interaction reranker** (§2.1) — once eval can prove the lift.
6. Fold **multi-query expansion into DRIFT** (§2.2).

---

## 6. Sources

- [Reasoning RAG via System 1 or System 2: A Survey (arXiv:2506.10408)](https://arxiv.org/pdf/2506.10408)
- [RAG-R1: Incentivizing Search & Reasoning via RL (arXiv:2507.02962)](https://arxiv.org/pdf/2507.02962)
- [AutoSearch: Adaptive Search Depth for Efficient Agentic RAG via RL (arXiv:2604.17337)](https://arxiv.org/html/2604.17337v1)
- [MARAG-R1: RL Multi-Tool Agentic Retrieval (arXiv:2510.27569)](https://arxiv.org/pdf/2510.27569)
- [Stanford: Legal RAG Hallucinations (J. Empirical Legal Studies 2025)](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)
- [Benchmarking LLM Faithfulness in RAG / FaithJudge (arXiv:2505.04847)](https://arxiv.org/pdf/2505.04847)
- [Toward Faithful RAG with Sparse Autoencoders (arXiv:2512.08892)](https://arxiv.org/pdf/2512.08892)
- [Augmented Question-guided Retrieval (AQgR) of Indian Case Law (arXiv:2508.04710)](https://arxiv.org/pdf/2508.04710)
- [LRAGE: Legal RAG Evaluation Tool (arXiv:2504.01840)](https://arxiv.org/pdf/2504.01840)
- [Are LLMs Court-Ready? Indian Legal Reasoning (arXiv:2510.17900)](https://www.arxiv.org/pdf/2510.17900)
- [Late Chunking: Contextual Chunk Embeddings (arXiv:2409.04701)](https://arxiv.org/pdf/2409.04701)
- [Late Interaction Overview: ColBERT/ColPali/ColQwen (Weaviate)](https://weaviate.io/blog/late-interaction-overview)
- [IL-TUR: Indian Legal Benchmark](https://arxiv.org/pdf/2308.05502)
