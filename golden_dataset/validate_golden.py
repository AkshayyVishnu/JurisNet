"""Validates golden_dataset.jsonl against the real LEGAL_DATA corpus.

Checks, per record:
  (a) every id in source_doc_ids exists as a file under LEGAL_DATA/{judgments,provisions}
  (b) span: the (entity-unescaped, whitespace-collapsed) source_span occurs in the
      primary source's body
  (c) structural citation edges hold for each multi-hop type:
        - multi_hop_judgment_to_provision : provision id in judgment.cited_provisions
        - multi_hop_provision_to_cases    : each case id in provision.cases_citedby
        - multi_hop_bridge                : provision (2nd id) in EVERY judgment id's cited_provisions
        - case_to_case_citation           : target case id in primary judgment.cited_judgements
  (d) negatives have empty source_doc_ids and expected_behavior == "abstain"
  (e) coverage: total >= 40, every question_type non-empty

Exit code 0 on success, 1 on any failure.
Run:  python golden_dataset/validate_golden.py
"""
import json, os, glob, io, html, re, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "LEGAL_DATA")
DS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_dataset.jsonl")

def load(f): return json.load(io.open(f, encoding="utf-8"))

JUDG = {os.path.splitext(os.path.basename(f))[0]: f for f in glob.glob(os.path.join(DATA, "judgments", "*.json"))}
PROV = {os.path.splitext(os.path.basename(f))[0]: f for f in glob.glob(os.path.join(DATA, "provisions", "*.json"))}

_cache = {}
def doc(i):
    i = str(i)
    if i not in _cache:
        p = JUDG.get(i) or PROV.get(i)
        _cache[i] = load(p) if p else None
    return _cache[i]

def norm(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

def exists(i):
    return str(i) in JUDG or str(i) in PROV

errors = []
def err(rid, msg): errors.append(f"{rid}: {msg}")

records = []
with io.open(DS, encoding="utf-8") as f:
    for ln, line in enumerate(f, 1):
        line = line.strip()
        if not line: continue
        try:
            records.append(json.loads(line))
        except Exception as e:
            err(f"line{ln}", f"invalid JSON: {e}")

by_type = Counter()
by_diff = Counter()

for r in records:
    rid = r.get("id", "?")
    qt = r.get("question_type", "?")
    by_type[qt] += 1
    by_diff[r.get("difficulty", "?")] += 1
    ids = r.get("source_doc_ids", [])
    primary = r.get("primary_source")

    if qt == "negative_unanswerable":
        if ids:
            err(rid, "negative record must have empty source_doc_ids")
        if r.get("expected_behavior") != "abstain":
            err(rid, "negative record must have expected_behavior=abstain")
        continue

    # (a) existence
    for i in ids:
        if not exists(i):
            err(rid, f"source_doc_id {i} not found in corpus")
    if primary is not None and not exists(primary):
        err(rid, f"primary_source {primary} not found in corpus")

    # (b) span check against primary
    span = norm(r.get("source_span", ""))
    pdoc = doc(primary) if primary is not None else None
    if span:
        if not pdoc:
            err(rid, "no primary doc to verify span against")
        elif span not in norm(pdoc.get("body", "")):
            err(rid, f"source_span not found verbatim in primary {primary}")

    # (c) structural edges
    if qt == "multi_hop_judgment_to_provision":
        # find the judgment among ids and the provision (primary)
        judg = next((str(i) for i in ids if str(i) in JUDG), None)
        if judg is None:
            err(rid, "no judgment in source_doc_ids")
        elif str(primary) not in [str(x) for x in doc(judg).get("cited_provisions", [])]:
            err(rid, f"provision {primary} not in {judg}.cited_provisions")
    elif qt == "multi_hop_provision_to_cases":
        prov = str(primary)
        cb = set(str(x) for x in (doc(prov).get("cases_citedby", []) if doc(prov) else []))
        for i in ids:
            if str(i) == prov: continue
            if str(i) not in cb:
                err(rid, f"case {i} not in {prov}.cases_citedby")
    elif qt == "multi_hop_bridge":
        # ids = [judgmentA, provision, judgmentB, ...]; provision must be in each judgment's cited_provisions
        prov = str(primary)
        judg_ids = [str(i) for i in ids if str(i) in JUDG]
        if not judg_ids:
            err(rid, "bridge has no judgments")
        for j in judg_ids:
            if prov not in [str(x) for x in doc(j).get("cited_provisions", [])]:
                err(rid, f"bridge provision {prov} not in {j}.cited_provisions")
    elif qt == "case_to_case_citation":
        tgt = next((str(i) for i in ids if str(i) != str(primary)), None)
        if tgt is None:
            err(rid, "no target case in source_doc_ids")
        elif tgt not in [str(x) for x in doc(str(primary)).get("cited_judgements", [])]:
            err(rid, f"target {tgt} not in {primary}.cited_judgements")

# (e) coverage
EXPECTED = {"single_hop_metadata","statute_lookup","single_hop_holding",
            "multi_hop_judgment_to_provision","multi_hop_provision_to_cases",
            "multi_hop_bridge","comparison_cross_doc","doctrine_conceptual",
            "case_to_case_citation","temporal_amendment","negative_unanswerable"}
missing = EXPECTED - set(by_type)
if missing:
    err("coverage", f"missing question types: {sorted(missing)}")
if len(records) < 40:
    err("coverage", f"only {len(records)} records (need >= 40)")

print(f"Records: {len(records)}")
print("By type:")
for k in sorted(by_type): print(f"  {by_type[k]:>2}  {k}")
print("By difficulty:")
for k in sorted(by_diff): print(f"  {by_diff[k]:>2}  {k}")

if errors:
    print(f"\nFAILED with {len(errors)} error(s):")
    for e in errors: print("  -", e)
    sys.exit(1)
print("\nALL CHECKS PASSED")
sys.exit(0)
