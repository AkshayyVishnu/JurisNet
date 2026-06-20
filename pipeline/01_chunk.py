"""
Stage A — Structural chunking (deterministic, NO LLM).

Converts the real LEGAL_DATA schema into chunk files:
  - judgments  -> L0 summary + L2 numbered-paragraph chunks (sliding overlap)
  - provisions -> one StatuteProvisionChunk each
  - citation graph edges from the pre-resolved ID lists (no regex)

See PIPELINE_STAGES.md (Stage A). Stage B (pipeline/02_enrich.py) adds L1/L3/ratio.

Run:  python pipeline/01_chunk.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from chunker import (  # noqa: E402  — reuse the built dataclasses + helpers
    L0Chunk,
    L2ParaChunk,
    StatuteProvisionChunk,
    court_authority_score,
    _breadcrumb,
    _generate_statute_aliases,
    extract_reporter_citations,
)

# ─────────────────────────────────────────────
# Body normalization
# ─────────────────────────────────────────────

# NOTE: bodies are largely single-line, so noise patterns must be BOUNDED —
# never use [^\n]* (it would delete to end-of-document).
_NOISE = re.compile(
    r"(Signature Not Verified|Digitally Signed|Signing Date:[\d.:\s]{0,30}|"
    r"Page\s+\d+\s+of\s+\d+|By:[A-Z]{2,})",
    re.IGNORECASE,
)
_WS = re.compile(r"[ \t ]+")


def normalize_body(body: str) -> str:
    text = html.unescape(body or "")
    text = _NOISE.sub(" ", text)
    text = _WS.sub(" ", text)
    return text.strip()


# ─────────────────────────────────────────────
# Court detection (no docsource field in our schema)
# ─────────────────────────────────────────────

_COURT_LINE = re.compile(
    r"(IN THE [A-Z][A-Z .,&'-]*?COURT[A-Z .,&'-]*|"
    r"IN THE INCOME TAX APPELLATE TRIBUNAL[A-Z .,&'-]*|"
    r"[A-Z][A-Z .,&'-]*?(?:HIGH COURT|SUPREME COURT|TRIBUNAL|COMMISSION)[A-Z .,&'-]*)"
)


def detect_court(body: str) -> tuple[str, float, bool]:
    """Return (court_label, authority_score, persuasive_only) from the body header."""
    head = body[:600]
    score, persuasive = court_authority_score(head)
    label = ""
    m = _COURT_LINE.search(head.upper())
    if m:
        lab = re.split(
            r"\b(DATE|DATED|CORAM|BEFORE|JUDGMENT|JUDGEMENT|ORDER|RESERVED|"
            r"PRONOUNCED|DECISION|VERSUS|BETWEEN)\b",
            m.group(1),
        )[0]
        label = " ".join(lab.split()).title().strip()
    if not label:
        # No specific court phrase parsed — label by the score tier that
        # court_authority_score already detected (keywords like "Delhi", "ITAT").
        label = {
            1.0: "Supreme Court of India",
            0.70: "High Court",
            0.55: "Privy Council",
            0.35: "District / Sessions Court",
            0.25: "Tribunal",
            0.20: "Commission",
        }.get(score, "Court (unspecified)")
    return label, score, persuasive


# ─────────────────────────────────────────────
# Paragraph segmentation
# ─────────────────────────────────────────────

# A numbered-paragraph marker: "1. ", "12. " etc. at a word boundary, followed by
# the start of real text (capital / quote / paren). Money/years/sub-clauses like
# "1996" or "17(2)" don't match (no "<num>. <Capital>").
_MARKER = re.compile(r"(?:(?<=\s)|^)(\d{1,3})\.\s+(?=[\"'(A-Z])")


def segment_paragraphs(text: str):
    """
    Sequence-aware split on numbered markers. Returns a list of (para_id, text) or
    None if the doc isn't reliably numbered (caller falls back to windowing).
    """
    matches = list(_MARKER.finditer(text))
    valid = []
    expected = 1
    for m in matches:
        n = int(m.group(1))
        # Accept a marker only if it continues the running sequence (small skips ok).
        if n == expected or expected < n <= expected + 2:
            valid.append((m.start(), n))
            expected = n + 1
    if len(valid) < 3:
        return None

    paras = []
    # Capture the pre-"1." header (parties / coram / counsel) if substantial.
    if valid[0][0] > 200:
        header = text[: valid[0][0]].strip()
        if header:
            paras.append(("header", header))
    for i, (pos, n) in enumerate(valid):
        end = valid[i + 1][0] if i + 1 < len(valid) else len(text)
        seg = text[pos:end].strip()
        if seg:
            paras.append((str(n), seg))
    return paras


# Size guards. voyage-4-large has a per-input token cap and giant chunks ruin
# retrieval precision, so no L2 chunk may exceed ~MAX_PARA_CHARS of body text.
MAX_PARA_CHARS = 5500     # sub-split any paragraph larger than this (~1,400 tokens)
SUBSPLIT_TARGET = 4000    # target size when sub-splitting / windowing
OVERLAP_CHARS = 400       # only the tail of the previous paragraph is prepended


def window_chunks(text: str, target: int = 1500):
    """
    Split text into ~target-char windows on sentence boundaries. A boundary-less
    giant 'sentence' (no punctuation) is hard-sliced so nothing exceeds ~1.5×target.
    """
    sents = re.split(r"(?<=[.?!])\s+", text)
    pieces = []
    for s in sents:
        if len(s) > target * 1.5:
            pieces.extend(s[k:k + target] for k in range(0, len(s), target))
        else:
            pieces.append(s)
    chunks, buf = [], ""
    for s in pieces:
        if buf and len(buf) + len(s) > target:
            chunks.append(buf.strip())
            buf = s
        else:
            buf = f"{buf} {s}" if buf else s
    if buf.strip():
        chunks.append(buf.strip())
    return [(f"w{i}", c) for i, c in enumerate(chunks)]


def enforce_max(paras):
    """Sub-split any paragraph over MAX_PARA_CHARS (ids become '12.0', '12.1', …)."""
    out = []
    for pid, txt in paras:
        if len(txt) <= MAX_PARA_CHARS:
            out.append((pid, txt))
        else:
            for j, (_, sub) in enumerate(window_chunks(txt, SUBSPLIT_TARGET)):
                out.append((f"{pid}.{j}", sub))
    return out


# ─────────────────────────────────────────────
# Judgment chunker
# ─────────────────────────────────────────────

def chunk_judgment(data: dict, prov_map: dict[int, str]) -> tuple[dict, list[dict]]:
    tid = int(data["doc_id"])
    title = data.get("title", "")
    date = data.get("date", "")
    body = normalize_body(data.get("body", ""))
    court, auth, persuasive = detect_court(body)

    cited_prov = [int(x) for x in data.get("cited_provisions", [])]
    cited_judg = [int(x) for x in data.get("cited_judgements", [])]
    orders = data.get("orders_and_rules", [])

    # ── L0 summary ──
    prov_names = [prov_map[p] for p in cited_prov if p in prov_map][:12]
    summary_bits = [title, f"Court: {court}"]
    if prov_names:
        summary_bits.append("Cites: " + "; ".join(prov_names))
    if orders:
        summary_bits.append("Orders/Rules: " + "; ".join(orders[:10]))
    l0 = L0Chunk(
        tid=tid,
        title=title,
        date=date,
        court=court,
        authority_score=auth,
        persuasive_only=persuasive,
        citations_raw=extract_reporter_citations(body)[:10],
        numcitedby=0,  # not available for judgments in this schema
        related_queries=[],
        text=". ".join(b for b in summary_bits if b).strip(),
    )

    # ── L2 paragraph chunks (with bounded sliding overlap) ──
    paras = enforce_max(segment_paragraphs(body) or window_chunks(body))
    l2_dicts: list[dict] = []
    for i, (pid, ptext) in enumerate(paras):
        prev = paras[i - 1][1] if i > 0 else ""
        overlap = (prev[-OVERLAP_CHARS:].strip() + "\n\n") if prev else ""
        breadcrumb = _breadcrumb(title, court, "unclassified", pid)
        c = asdict(L2ParaChunk(
            tid=tid,
            title=title,
            para_id=pid,
            section_type="unclassified",  # Stage B assigns real section types
            text=f"{breadcrumb}\n\n{overlap}{ptext}",
        ))
        c["raw"] = ptext  # clean paragraph text (no breadcrumb/overlap) for Stage B
        l2_dicts.append(c)

    # ── Citation edges (from pre-resolved ID lists) ──
    edges: list[dict] = []
    for pid in cited_prov:
        edges.append({
            "from_tid": tid, "from_title": title,
            "to_tid": pid, "to_title": prov_map.get(pid, ""),
            "rel_type": "CITES_STATUTE", "citation_type": "statute",
            "in_corpus": pid in prov_map,
        })
    for jid in cited_judg:
        edges.append({
            "from_tid": tid, "from_title": title,
            "to_tid": jid, "to_title": "",  # filled in runner if in corpus
            "rel_type": "CITES_CASE", "citation_type": "case",
            "in_corpus": None,  # resolved in runner against the judgment id set
        })
    for rule in orders:
        edges.append({
            "from_tid": tid, "from_title": title,
            "to_tid": None, "to_title": str(rule),
            "rel_type": "CITES_RULE", "citation_type": "rule",
            "in_corpus": False,  # rule text not yet a document (Stage C)
        })

    chunk = {
        "doc_type": "judgment",
        "l0": asdict(l0),
        "l2_paragraphs": l2_dicts,
        # Stage B fills these:
        "l1_sections": [],
        "l3_atomic": [],
        "ratio_chunks": [],
        "issue_held": [],
        "stage_b_done": False,
    }
    return chunk, edges


# ─────────────────────────────────────────────
# Statute / provision chunker
# ─────────────────────────────────────────────

def chunk_statute(data: dict) -> tuple[dict, list[dict]]:
    tid = int(data["doc_id"])
    title = data.get("title", "")
    body = normalize_body(data.get("body", ""))
    citedby = [int(x) for x in data.get("cases_citedby", [])]

    # act_name lives in the body header ("Section 22A in The Code of Civil Procedure, 1908 ...")
    section_ref = title
    act_name = ""
    m = re.match(r"(Section|Article)\s+(\S+)\s+in\s+(.+?)(?:\s+\d|\s*\[|$)", body, re.IGNORECASE)
    if m:
        section_ref = f"{m.group(1)} {m.group(2)}"
        act_name = m.group(3).strip().rstrip(" .,")

    provision = StatuteProvisionChunk(
        tid=tid,
        title=title,
        date="",
        act_name=act_name,
        section_ref=section_ref,
        text=body,
        aliases=_generate_statute_aliases(f"{title} {act_name}"),
        citedby_tids=citedby,
    )

    # Reverse edges: judgments that cite this provision (dedup against judgment side in runner).
    edges = [{
        "from_tid": jid, "from_title": "",
        "to_tid": tid, "to_title": title,
        "rel_type": "CITES_STATUTE", "citation_type": "statute",
        "in_corpus": True,
    } for jid in citedby]

    return {"doc_type": "statute", "provision": asdict(provision)}, edges


# ─────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────

def _load(p: Path) -> dict:
    # strict=False tolerates literal control chars (raw newlines/tabs) some
    # LEGAL_DATA files carry inside string values.
    return json.loads(p.read_text(encoding="utf-8"), strict=False)


def _write(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def run() -> None:
    config.validate()  # Voyage key + corpus presence (cheap fail-fast)

    jdir, pdir = config.JUDGMENTS_DIR, config.PROVISIONS_DIR
    out_j, out_p = config.CHUNKS_JUDGMENTS_DIR, config.CHUNKS_PROVISIONS_DIR
    out_j.mkdir(parents=True, exist_ok=True)
    out_p.mkdir(parents=True, exist_ok=True)

    jpaths = sorted(jdir.glob("*.json"))
    ppaths = sorted(pdir.glob("*.json"))
    print(f"Found {len(jpaths)} judgments, {len(ppaths)} provisions")

    # ── Provisions first: chunk them AND build a rich id->"<section_ref> <act>"
    #    map so judgment L0 summaries name cited statutes (e.g. "Section 75 The
    #    Code of Civil Procedure") instead of bare "Section 75". ──
    prov_map: dict[int, str] = {}
    all_edges: list[dict] = []
    for p in ppaths:
        chunk, edges = chunk_statute(_load(p))
        _write(out_p / p.name, chunk)
        all_edges.extend(edges)
        pv = chunk["provision"]
        label = f"{pv['section_ref']} {pv['act_name']}".strip() if pv["act_name"] else pv["section_ref"]
        prov_map[pv["tid"]] = label

    judg_ids = {int(_load(p)["doc_id"]) for p in jpaths}

    # ── Judgments ──
    stats = Counter()
    zero_para_docs = []
    fallback_docs = []
    for p in jpaths:
        data = _load(p)
        chunk, edges = chunk_judgment(data, prov_map)
        _write(out_j / p.name, chunk)
        all_edges.extend(edges)

        n_l2 = len(chunk["l2_paragraphs"])
        stats["l2"] += n_l2
        if n_l2 == 0:
            zero_para_docs.append(data["doc_id"])
        # Fallback fired if any para_id starts with "w"
        if chunk["l2_paragraphs"] and chunk["l2_paragraphs"][0]["para_id"].startswith("w"):
            fallback_docs.append(data["doc_id"])

    # ── Resolve / dedup edges ──
    judg_titles = {}  # tid -> title, for in-corpus case edges
    for p in jpaths:
        d = _load(p)
        judg_titles[int(d["doc_id"])] = d.get("title", "")

    seen = set()
    merged = []
    edge_stats = Counter()
    for e in all_edges:
        if e["rel_type"] == "CITES_CASE":
            e["in_corpus"] = e["to_tid"] in judg_ids
            if e["in_corpus"]:
                e["to_title"] = judg_titles.get(e["to_tid"], "")
        elif e["rel_type"] == "CITES_STATUTE":
            # Normalize to the rich provision label so judgment-side and
            # provision-side reverse edges dedup to one entry.
            e["to_title"] = prov_map.get(e["to_tid"], e["to_title"])
        # Dedup on the target id (title-independent); rule edges have no id.
        key = ((e["from_tid"], e["to_tid"], e["rel_type"]) if e["to_tid"] is not None
               else (e["from_tid"], e["to_title"], e["rel_type"]))
        if key in seen:
            continue
        seen.add(key)
        merged.append(e)
        edge_stats[e["rel_type"]] += 1
        if e["rel_type"] == "CITES_CASE" and e["in_corpus"]:
            edge_stats["CITES_CASE_in_corpus"] += 1

    _write(config.CITATION_EDGES_FILE, merged)

    # ── Summary / Checkpoint A ──
    print("\n" + "=" * 60)
    print("STAGE A COMPLETE")
    print("=" * 60)
    print(f"  judgment chunk files : {len(jpaths)} -> {out_j}")
    print(f"  provision chunk files: {len(ppaths)} -> {out_p}")
    print(f"  L2 paragraph chunks  : {stats['l2']}")
    print(f"  unnumbered (windowed): {len(fallback_docs)} docs")
    print(f"  zero-paragraph docs  : {len(zero_para_docs)} {zero_para_docs or ''}")
    print(f"\n  citation edges       : {len(merged)} (deduped)")
    for rel, n in edge_stats.most_common():
        print(f"      {rel:24s} {n}")
    print(f"\n  merged edges file    : {config.CITATION_EDGES_FILE}")


if __name__ == "__main__":
    run()
