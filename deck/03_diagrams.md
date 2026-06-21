# JurisNet Deck — Diagrams & Images

Two kinds of visuals. **Diagrams with text** → build from the Mermaid specs below (paste into
[mermaid.live](https://mermaid.live) → export SVG/PNG → drop into Canva). **Never** generate
flowcharts with an AI image tool — it garbles the text. **Illustrative imagery** (hero, section
dividers, motifs) → use the text-free image-gen prompts at the bottom.

Theme for everything: minimal monochrome (near-black on white) + a single accent (indigo `#4f46e5`).

---

## Diagram A — End-to-end architecture (Slide 4)
```mermaid
flowchart LR
    U([User query]) --> QU[Query Understanding<br/>intent + entities]
    QU --> HR{{Hybrid Retriever}}
    subgraph Stores
      V[(Qdrant<br/>30,564 vectors)]
      B[(SQLite FTS5<br/>BM25)]
      G[(Neo4j graph<br/>1,071 nodes · 6,776 edges)]
    end
    HR --- V
    HR --- B
    HR --- G
    HR -->|RRF fusion| SY[Synthesis<br/>IRAC + citations]
    SY --> CV[Citation Verifier<br/>grounding guard]
    CV --> A([Cited, verified answer])
```

## Diagram B — 4-source hybrid retrieval → RRF (Slide 7)
```mermaid
flowchart TD
    Q[Query + intent] --> E[voyage-4-large<br/>query embedding]
    E --> CVc[content_vector<br/>Qdrant]
    E --> LVc[label_vector<br/>Qdrant]
    Q --> BM[bm25<br/>FTS5 legal tokens]
    Q --> CG[citation_graph<br/>Neo4j traverse]
    CVc --> RRF
    LVc --> RRF
    BM --> RRF
    CG --> RRF
    RRF[["Reciprocal Rank Fusion<br/>intent-weighted · per-source tid-collapse"]] --> TOP[Top-K fused documents]
```

## Diagram C — Legal-aware multi-level chunking (Slide 6)
```mermaid
flowchart TD
    DOC[Judgment / Statute / Rule] --> L0[L0 · headnote summary]
    DOC --> L1[L1 · facts]
    DOC --> L2[L2 · paragraph + overlap]
    DOC --> L3[L3 · atomic sentence]
    DOC --> R[ratio · binding holding]
    DOC --> P[statute / rule provision]
    L0 & L1 & L2 & L3 & R --> CC[(content collection)]
    P --> LC[(label collection)]
```

## Diagram D — Agentic pipeline with the ❓ loop (Slide 9) — mirrors agents/graph.py
```mermaid
flowchart TD
    Q([Query]) --> QA[Query Agent<br/>split · classify · clarify?]
    QA -->|❓ ambiguous| QA
    QA --> RS[Researcher<br/>Pull A/B retrieve · Pull C regex statutes]
    RS -->|informational| ADJ
    RS -->|test_application| CR[Checklist Resolver<br/>provision → conditions cached]
    CR --> AU[Auditor<br/>✅ / ❌ / ❓ per condition]
    AU -->|❓ missing fact| AU
    AU --> ADJ[Adjudicator<br/>grounded answer + citations]
    ADJ --> OUT([Verdict])
```

## Diagram E — "No guessing ahead of evidence" grounding loop (Slide 10)
```mermaid
flowchart LR
    C[Claim in answer] --> Q{In retrieved set?}
    Q -->|no| F[flag ⚠ / strip]
    Q -->|yes| G2{Exists in corpus graph?}
    G2 -->|no| FAB[mark FABRICATED]
    G2 -->|yes| OK[✓ grounded · counts toward confidence]
```

## Comparison matrix (Slide 13) — build as a Canva TABLE (not an image)
| Capability | Vanilla RAG | GraphRAG | Agentic RAG | **JurisNet** |
|---|---|---|---|---|
| Dense retrieval | ✓ | ✓ | ✓ | ✓ |
| Keyword/BM25 fusion | ✗ | ~ | ~ | ✓ |
| Knowledge graph | ✗ | ✓ | ~ | ✓ (citation graph) |
| Domain-aware chunking | ✗ | ✗ | ~ | ✓ (L0–L3 + ratio) |
| Reasoning over statutory conditions | ✗ | ✗ | ~ | ✓ (checklist + audit) |
| Human-in-the-loop ❓ for missing facts | ✗ | ✗ | ~ | ✓ |
| Citation verification (anti-hallucination) | ✗ | ✗ | ~ | ✓ (verifier) |
| Production resilience (key rotation/cache) | ✗ | ✗ | ~ | ✓ |

(✓ = yes · ~ = partial/varies · ✗ = no)

---

## Illustrative image-gen prompts (text-free; Midjourney / DALL·E / Canva)
- **Hero (Slide 1):** "Minimalist editorial illustration of justice scales dissolving into a glowing network of connected nodes, near-black on off-white, single indigo accent, generous negative space, premium legal-tech aesthetic, no text."
- **Section divider:** "Abstract knowledge-graph constellation of small nodes and thin edges, monochrome with one indigo accent line, lots of whitespace, minimal, no text."
- **Problem slide motif (Slide 2/3):** "A single document fragment fracturing into scattered question marks, muted monochrome, one indigo accent, conceptual, clean, no text."
- **Production/scale motif (Slide 14):** "Abstract resilient pipeline of rotating interlocking rings suggesting failover and load balancing, monochrome + indigo accent, minimal, no text."
