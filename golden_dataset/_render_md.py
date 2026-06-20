"""Renders golden_dataset.md (human-readable) from golden_dataset.jsonl.
Run:  python golden_dataset/_render_md.py
"""
import json, io, os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
recs = [json.loads(l) for l in io.open(os.path.join(HERE, "golden_dataset.jsonl"), encoding="utf-8") if l.strip()]

ORDER = ["single_hop_metadata","statute_lookup","single_hop_holding",
         "multi_hop_judgment_to_provision","multi_hop_provision_to_cases",
         "multi_hop_bridge","comparison_cross_doc","doctrine_conceptual",
         "case_to_case_citation","temporal_amendment","negative_unanswerable"]
LABEL = {
 "single_hop_metadata":"Single-hop · case metadata",
 "statute_lookup":"Single-hop · statute lookup",
 "single_hop_holding":"Single-hop · holding / ratio",
 "multi_hop_judgment_to_provision":"Multi-hop (2) · judgment → provision",
 "multi_hop_provision_to_cases":"Multi-hop (2) · provision → cases",
 "multi_hop_bridge":"Multi-hop (3) · bridge across cases",
 "comparison_cross_doc":"Comparison · cross-document",
 "doctrine_conceptual":"Doctrine / conceptual",
 "case_to_case_citation":"Case → case citation",
 "temporal_amendment":"Temporal / amendment",
 "negative_unanswerable":"Negative · must abstain",
}

groups = defaultdict(list)
for r in recs: groups[r["question_type"]].append(r)

def esc(s): return (s or "").replace("|", "\\|").replace("\n", " ")

out = []
out.append("# Golden Evaluation Dataset — Indian Legal RAG (CPC corpus)\n")
out.append(f"**{len(recs)} questions** hand-curated from `LEGAL_DATA/` and traced to source `doc_id`s. ")
out.append("Machine-readable source of truth: `golden_dataset.jsonl`. Validate with `python validate_golden.py`.\n")

# summary tables
from collections import Counter
bt = Counter(r["question_type"] for r in recs)
bd = Counter(r["difficulty"] for r in recs)
out.append("## Coverage\n")
out.append("| Question type | Count |")
out.append("|---|---|")
for t in ORDER: out.append(f"| {LABEL[t]} | {bt[t]} |")
out.append(f"| **Total** | **{len(recs)}** |\n")
out.append("Difficulty: " + ", ".join(f"**{d}** {bd[d]}" for d in ("easy","medium","hard")) + "\n")

out.append("## How to cross-verify an answer\n")
out.append("Open `LEGAL_DATA/judgments/<doc_id>.json` or `LEGAL_DATA/provisions/<doc_id>.json`, "
           "search its `body` for the quoted **Source span**, and confirm the answer. "
           "For multi-hop rows, the `verification_note` names the exact citation edge "
           "(e.g. `judgment.cited_provisions` or `provision.cases_citedby`) that links the documents.\n")

for t in ORDER:
    rows = groups.get(t, [])
    if not rows: continue
    out.append(f"## {LABEL[t]}\n")
    for r in rows:
        out.append(f"### {r['id']} · {r['difficulty']} · {r['hop_count']} hop(s)\n")
        out.append(f"**Q:** {esc(r['question'])}\n")
        out.append(f"**Gold answer:** {esc(r['answer'])}\n")
        if r.get("source_span"):
            out.append(f"**Source span:** \"{esc(r['source_span'])}\"\n")
        ids = ", ".join(str(i) for i in r["source_doc_ids"]) or "— (none; abstain)"
        out.append(f"**Source doc_ids:** {ids}  ·  **expected:** `{r['expected_behavior']}`\n")
        out.append(f"_Verify:_ {esc(r['verification_note'])}\n")

md = "\n".join(out) + "\n"
with open(os.path.join(HERE, "golden_dataset.md"), "w", encoding="utf-8") as f:
    f.write(md)
print("Wrote golden_dataset.md")
