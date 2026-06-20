# Golden Evaluation Dataset

A curated set of **54 questions** (≥ 40 required) for evaluating the Indian-legal RAG
system, every answer traced to real documents in `../LEGAL_DATA/` so results can be
cross-verified by hand and by automated eval tools (`ragas`, `promptfoo`).

## Files

| File | Purpose |
|---|---|
| `golden_dataset.jsonl` | **Source of truth.** One JSON object per question (machine-readable). |
| `golden_dataset.md` | Human-readable rendering grouped by category, for review/cross-checking. |
| `validate_golden.py` | Structural + span validator. Run after any edit. |
| `_build.py` | Regenerates `golden_dataset.jsonl` from the curated records. |
| `_render_md.py` | Regenerates `golden_dataset.md` from the JSONL. |

## Record schema (JSONL)

```json
{
  "id": "Q022",
  "question": "...",
  "question_type": "multi_hop_judgment_to_provision",
  "hop_count": 2,
  "difficulty": "easy | medium | hard",
  "answer": "concise gold answer",
  "source_span": "verbatim quote present in the primary source's body",
  "source_doc_ids": [1077888, 192138551],
  "primary_source": 192138551,
  "verification_note": "names the exact citation edge that links the docs",
  "expected_behavior": "answer | abstain"
}
```

Negative (unanswerable) records use `source_doc_ids: []`, `primary_source: null`,
`source_span: ""`, and `expected_behavior: "abstain"`.

## Question taxonomy

| `question_type` | Hops | Tests | Count |
|---|---|---|---|
| `single_hop_metadata` | 1 | court / date / parties / outcome of one case | 7 |
| `statute_lookup` | 1 | verbatim content of one CPC section | 8 |
| `single_hop_holding` | 1 | what a court actually held | 6 |
| `multi_hop_judgment_to_provision` | 2 | case → section it relied on → what it says | 8 |
| `multi_hop_provision_to_cases` | 2 | section → which corpus cases apply it | 5 |
| `multi_hop_bridge` | 3 | case A → shared section → case B | 4 |
| `comparison_cross_doc` | 2 | contrast two cases or two sections | 5 |
| `doctrine_conceptual` | 1–2 | explain a CPC doctrine, grounded | 3 |
| `case_to_case_citation` | 2 | one corpus case citing another | 2 |
| `temporal_amendment` | 1 | when/how a section was inserted/amended | 2 |
| `negative_unanswerable` | 0 | system must **abstain** (out-of-domain) | 4 |

## Corpus facts that shaped the design

- `LEGAL_DATA/` = **637 judgments** (2000–2026; mostly Supreme Court + High Courts) and
  **142 provisions** (all **Code of Civil Procedure, 1908**).
- `judgment.cited_provisions` resolves **100%** in-corpus, and `provision.cases_citedby`
  resolves **100%** — so the judgment↔provision graph is the **fully-traceable backbone**
  for verifiable multi-hop questions.
- `judgment.cited_judgements` (case→case) resolves only **2%** in-corpus, so case-to-case
  questions are limited to the ~70 in-corpus edges (2 are used here).
- Files contain HTML entities and cp1252 bytes — always read JSON with `encoding="utf-8"`.

## Usage

```bash
# Validate (existence of every doc_id, verbatim span match, citation edges, coverage):
python golden_dataset/validate_golden.py        # exits non-zero on any failure

# Rebuild artifacts after editing curated records in _build.py:
python golden_dataset/_build.py
python golden_dataset/_render_md.py
```

### Smoke eval against the live pipeline (once retrieval is wired)

Feed `golden_dataset.jsonl` to the retriever and check, per record:
1. retrieved chunks include the documents in `source_doc_ids` (retrieval recall);
2. the generated answer entails the gold `answer` / contains the `source_span` facts
   (groundedness — pairs naturally with the project's Groundedness Critic);
3. records with `expected_behavior: "abstain"` trigger a no-answer / disclaimer path
   (hallucination guard — the 4 negatives are traps: IPC §302, a non-existent CPC §500,
   a 2027 ruling, and CrPC §437).
