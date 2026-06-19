"""
legal_chunker.py  v2
─────────────────────
Converts Indian Kanoon JSON documents directly into chunk objects ready
for embedding and storage.

v2 changes:
  • Added L3 Atomic Proposition chunks (sentence-level from Held/Reasoning)
  • Fixed court authority hierarchy (SC > HC > Privy Council > District > Tribunal)
  • Added case-name citation extraction (Party1 v. Party2)
  • Improved statute auto-detection (handles state statutes)

Works on TWO document types (auto-detected):
  • judgments  → divtype == "judgments"
  • statutes   → docsource contains "Section" or has cleaned_text without doc

NO LLM calls in this file — three spots marked TODO where LLM is needed.

Usage:
    from chunker import chunk_document
    chunks = chunk_document(json.load(open("70075.json")))
"""

import re
import json
from bs4 import BeautifulSoup
from dataclasses import dataclass, field, asdict
from typing import List, Optional


# ─────────────────────────────────────────────
# Court authority scores  (Article 141 hierarchy)
# ─────────────────────────────────────────────
# Clear separation:  SC (1.0) > HC (0.7) > Privy Council (0.55)
#                    > District (0.35) > Tribunal (0.25) > Commission (0.2)
#
# Privy Council: abolished 1949. Decisions are persuasive only post-
# independence, not binding. Scored BELOW HC because a 2023 Bombay HC
# decision on contract law is more relevant than a 1920 PC decision.
# Bench-strength multipliers applied separately at retrieval time.

COURT_AUTHORITY: dict[str, float] = {
    "Supreme Court of India": 1.0,
}

# Privy Council — persuasive only, NOT binding post-1950
PRIVY_COUNCIL_SCORE = 0.55

# High Courts — all at the same base level (Article 141: SC binds all,
# but one HC does not bind another HC)
HC_KEYWORDS = [
    "High Court", "Bombay", "Madras", "Calcutta", "Delhi", "Allahabad",
    "Karnataka", "Kerala", "Patna", "Gujarat", "Rajasthan", "Punjab",
    "Haryana", "Andhra Pradesh", "Telangana", "Orissa", "Odisha",
    "Himachal", "Gauhati", "Jharkhand", "Uttarakhand", "Chhattisgarh",
    "Meghalaya", "Manipur", "Tripura", "Sikkim", "Jammu",
]
HC_SCORE = 0.70

# District / Sessions courts
DISTRICT_KEYWORDS = ["District", "Sessions", "Magistrate", "Civil Judge"]
DISTRICT_SCORE = 0.35

# Tribunals (NCLT, ITAT, NCLAT, SAT, DRT, DRAT, NGT, AFT, CAT, etc.)
TRIBUNAL_KEYWORDS = [
    "Tribunal", "NCLT", "NCLAT", "ITAT", "SAT", "DRT", "DRAT",
    "NGT", "AFT", "CAT", "Appellate Tribunal",
]
TRIBUNAL_SCORE = 0.25

# Commissions (NHRC, State Consumer, National Consumer, etc.)
COMMISSION_KEYWORDS = ["Commission", "NHRC", "Consumer Forum", "NCDRC", "SCDRC"]
COMMISSION_SCORE = 0.20

# Catch-all for unrecognized courts
DEFAULT_SCORE = 0.15


def court_authority_score(docsource: str) -> tuple[float, bool]:
    """
    Returns (score, is_persuasive_only).
    Persuasive-only means NOT binding on lower courts (e.g. Privy Council).
    """
    if not docsource:
        return DEFAULT_SCORE, False

    ds = docsource.lower()

    # Supreme Court
    if "supreme court" in ds:
        return 1.0, False

    # Privy Council — persuasive only
    if "privy council" in ds:
        return PRIVY_COUNCIL_SCORE, True

    # High Courts
    for kw in HC_KEYWORDS:
        if kw.lower() in ds:
            return HC_SCORE, False

    # District / Sessions
    for kw in DISTRICT_KEYWORDS:
        if kw.lower() in ds:
            return DISTRICT_SCORE, False

    # Tribunals
    for kw in TRIBUNAL_KEYWORDS:
        if kw.lower() in ds:
            return TRIBUNAL_SCORE, False

    # Commissions
    for kw in COMMISSION_KEYWORDS:
        if kw.lower() in ds:
            return COMMISSION_SCORE, False

    return DEFAULT_SCORE, False


# ─────────────────────────────────────────────
# Citation extraction
# ─────────────────────────────────────────────

# Reporter-format citations: AIR 2019 SC 123, (2019) 3 SCC 456, etc.
REPORTER_PATTERN = re.compile(
    r'(AIR\s*\d{4}\s*\w+\s*\d+|'
    r'\(\d{4}\)\s*\d+\s*SCC\s*\(?\w*\)?\s*\d+|'
    r'\d{4}\s*SCR\s*\d+|'
    r'\d+\s*IND\.\s*CAS\.\s*\d+|'
    r'\d{4}\s*Cr\.?\s*L\.?\s*J\.?\s*\d+|'
    r'\d{4}\s*SCC\s*OnLine\s*\w+\s*\d+)',
    re.IGNORECASE
)

# Case-name citations: "Party1 v. Party2" / "Party1 vs Party2"
# Captures: "Maneka Gandhi v. Union of India", "State of Maharashtra vs Mohd. Yakub"
CASE_NAME_PATTERN = re.compile(
    r'([A-Z][A-Za-z\.\s&,]+?)\s+v[s]?\.?\s+([A-Z][A-Za-z\.\s&,]+?)(?=\s*[\(\[,;\.]|\s+on\s|\s+\d{4}|\s*$)',
    re.MULTILINE
)

def extract_reporter_citations(text: str) -> List[str]:
    """Pull reporter-format citations (AIR, SCC, SCR, IND.CAS., CrLJ)."""
    return [m.strip() for m in REPORTER_PATTERN.findall(text)]

def extract_case_name_citations(text: str) -> List[dict]:
    """
    Pull case-name citations (Party1 v. Party2).
    Returns dicts with petitioner, respondent, raw_text.
    These don't give us a tid — need fuzzy matching against corpus titles later.
    """
    results = []
    for m in CASE_NAME_PATTERN.finditer(text):
        pet = m.group(1).strip().rstrip(",. ")
        res = m.group(2).strip().rstrip(",. ")
        # Skip false positives: too short, or common non-case patterns
        if len(pet) < 3 or len(res) < 3:
            continue
        if pet.lower() in ("the", "this", "that", "said", "in", "see", "also"):
            continue
        results.append({
            "petitioner": pet,
            "respondent": res,
            "raw_text": m.group(0).strip(),
        })
    return results


# ─────────────────────────────────────────────
# Sentence splitter for L3 atomic chunks
# ─────────────────────────────────────────────

# Legal text often has numbered points: "1. ...", "(a) ...", "(i) ..."
# We split on sentence boundaries AND numbered sub-points.
SENTENCE_SPLIT = re.compile(
    r'(?<=[.?!])\s+(?=[A-Z(0-9])|'   # Standard sentence end
    r'(?<=\.)\s*\n\s*|'               # Newline after period
    r'(?<=:)\s*\n\s*'                 # Newline after colon (introduces a list)
)

def split_into_propositions(text: str, min_words: int = 10) -> List[str]:
    """
    Split a paragraph into atomic propositions (sentences).
    Filters out sentences < min_words (noise: "We agree.", "Appeal dismissed.").
    """
    raw = SENTENCE_SPLIT.split(text)
    return [s.strip() for s in raw if len(s.split()) >= min_words]


# ─────────────────────────────────────────────
# Dataclasses — one per chunk type
# ─────────────────────────────────────────────

@dataclass
class L0Chunk:
    """One per judgment. Metadata + summary for broad discovery."""
    chunk_type: str = "L0_document"
    tid: int = 0
    title: str = ""
    date: str = ""
    court: str = ""
    authority_score: float = 0.7
    persuasive_only: bool = False
    citations_raw: List[str] = field(default_factory=list)
    numcitedby: int = 0
    citation_status: str = "GOOD_LAW"
    related_queries: List[str] = field(default_factory=list)
    text: str = ""

@dataclass
class L1SectionChunk:
    """One per section (Facts / Issues / Held / Reasoning / etc.)."""
    chunk_type: str = "L1_section"
    tid: int = 0
    title: str = ""
    section_type: str = ""
    para_ids: List[str] = field(default_factory=list)
    text: str = ""

@dataclass
class L2ParaChunk:
    """One per paragraph, with 1-paragraph sliding overlap prepended."""
    chunk_type: str = "L2_paragraph"
    tid: int = 0
    title: str = ""
    para_id: str = ""
    section_type: str = ""
    text: str = ""

@dataclass
class L3AtomicChunk:
    """
    One sentence = one atomic legal proposition.
    Extracted from Held / Reasoning sections.
    Used by Groundedness Critic for NLI verification.
    """
    chunk_type: str = "L3_atomic"
    tid: int = 0
    title: str = ""
    para_id: str = ""
    section_type: str = ""
    sentence_index: int = 0
    text: str = ""

@dataclass
class RatioChunk:
    """
    Binding holding only. Gets 1.3× authority boost at retrieval.
    Ratio/obiter classification is done by LLM (see TODO).
    """
    chunk_type: str = "ratio"
    tid: int = 0
    title: str = ""
    authority_score: float = 1.0
    boost: float = 1.3
    bench_unanimous: Optional[bool] = None
    opinion_type: str = "majority"
    text: str = ""
    # TODO: classification = "RATIO" | "OBITER" | "ARGUMENT"

@dataclass
class IssueHeldPair:
    """Framed issue + court's answer. Extracted by LLM."""
    chunk_type: str = "issue_held"
    tid: int = 0
    title: str = ""
    issue_number: int = 0
    issue: str = ""
    held: str = ""
    text: str = ""
    # TODO: filled by LLM after chunking

@dataclass
class CitationEdge:
    """
    Not a chunk — a graph edge written to Neo4j.
    One per citation reference found in a judgment.
    """
    from_tid: int = 0
    from_title: str = ""
    to_tid: Optional[int] = None
    to_citation_str: str = ""
    citation_type: str = "reporter"    # "reporter" or "case_name"
    rel_type: str = "CITES"
    # TODO: rel_type refined by LLM

@dataclass
class StatuteProvisionChunk:
    """Atomic: section + ALL provisos + ALL explanations. NEVER split."""
    chunk_type: str = "statute_provision"
    tid: int = 0
    title: str = ""
    date: str = ""
    act_name: str = ""
    section_ref: str = ""
    text: str = ""
    aliases: List[str] = field(default_factory=list)
    citedby_tids: List[int] = field(default_factory=list)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _breadcrumb(title: str, court: str, section_type: str, para_id: str = "") -> str:
    parts = [title, court, section_type]
    if para_id:
        parts.append(f"Para {para_id}")
    return "[" + " | ".join(p for p in parts if p) + "]"

def _generate_statute_aliases(title: str) -> List[str]:
    aliases = [title]
    sec_match = re.search(r'Section\s+(\d+[A-Z]?)', title, re.IGNORECASE)
    sec_num = sec_match.group(0) if sec_match else ""

    ACT_ABBREVS = {
        "Code of Civil Procedure": ["CPC", "C.P.C."],
        "Code of Criminal Procedure": ["CrPC", "Cr.P.C."],
        "Indian Penal Code": ["IPC", "I.P.C."],
        "Bharatiya Nyaya Sanhita": ["BNS", "B.N.S."],
        "Bharatiya Nagarik Suraksha Sanhita": ["BNSS", "B.N.S.S."],
        "Bharatiya Sakshya Adhiniyam": ["BSA", "B.S.A."],
        "Indian Evidence Act": ["IEA", "Evidence Act"],
        "Companies Act": ["Companies Act"],
        "Income Tax Act": ["IT Act", "Income Tax"],
        "Constitution of India": ["Constitution", "COI"],
        "Transfer of Property Act": ["TPA", "T.P.A."],
        "Contract Act": ["Indian Contract Act"],
        "Negotiable Instruments Act": ["NI Act", "N.I. Act"],
        "Specific Relief Act": ["SRA", "Specific Relief"],
        "Limitation Act": ["Limitation Act"],
        "Arbitration and Conciliation Act": ["Arbitration Act"],
    }
    for full, abbrevs in ACT_ABBREVS.items():
        if full.lower() in title.lower():
            for abbr in abbrevs:
                if sec_num:
                    aliases.append(f"{sec_num} {abbr}")
                    aliases.append(f"S.{sec_num.split()[-1]} {abbr}")
    return list(dict.fromkeys(aliases))


def _is_statute(data: dict) -> bool:
    """Improved statute detection — handles state statutes too."""
    if data.get("divtype") == "judgments":
        return False
    ds = data.get("docsource", "")
    if ds.startswith("Union of India") or "- Section" in ds or "- Article" in ds:
        return True
    if "State of" in ds and ("Section" in ds or "Article" in ds):
        return True
    if "cleaned_text" in data and "doc" not in data:
        return True
    title = data.get("title", "")
    if re.match(r'^(Section|Article)\s+\d', title, re.IGNORECASE):
        return True
    return False


# ─────────────────────────────────────────────
# JUDGMENT CHUNKER
# ─────────────────────────────────────────────

L3_SECTIONS = {"held", "reasoning", "conclusion", "judgment", "ratio"}

def _chunk_judgment(data: dict) -> dict:
    soup = BeautifulSoup(data["doc"], "html.parser")

    # ── extract reporter citations from header ──
    cit_el = soup.find("h3", class_="doc_citations")
    citations_raw_text = cit_el.get_text(" ", strip=True) if cit_el else ""
    reporter_citations = extract_reporter_citations(citations_raw_text)

    # ── collect paragraphs with section labels ──
    raw_paras: List[dict] = []
    for p in soup.find_all("p", id=True):
        text = p.get_text(" ", strip=True)
        if not text:
            continue
        raw_paras.append({
            "id": p.get("id", ""),
            "section_type": p.get("data-structure", "unclassified"),
            "text": text,
        })

    title   = data["title"]
    court   = data["docsource"]
    tid     = data["tid"]
    auth, persuasive = court_authority_score(court)

    # ─── L0 ──────────────────────────────────────────────────
    # summary_text = title + citations + related query keywords.
    # NOTE: relatedqs are IK-provided keywords (e.g. ["mortgage"]),
    # NOT a legal headnote. Actual headnotes unavailable in JSON.
    # TODO: optionally generate a 2-sentence legal summary via LLM.
    rq_text = " | ".join(q["value"] for q in data.get("relatedqs", []))
    summary_text = f"{title}. {citations_raw_text}. Topics: {rq_text}".strip(". ")

    l0 = L0Chunk(
        tid             = tid,
        title           = title,
        date            = data["publishdate"],
        court           = court,
        authority_score = auth,
        persuasive_only = persuasive,
        citations_raw   = reporter_citations,
        numcitedby      = data.get("numcitedby", 0),
        related_queries = [q["value"] for q in data.get("relatedqs", [])],
        text            = summary_text,
    )

    # ─── L1 section chunks ───────────────────────────────────
    section_map: dict[str, list] = {}
    for p in raw_paras:
        section_map.setdefault(p["section_type"], []).append(p)

    l1_chunks: List[L1SectionChunk] = []
    for section_type, paras in section_map.items():
        full_text = "\n\n".join(p["text"] for p in paras)
        breadcrumb = _breadcrumb(title, court, section_type)
        l1_chunks.append(L1SectionChunk(
            tid          = tid,
            title        = title,
            section_type = section_type,
            para_ids     = [p["id"] for p in paras],
            text         = f"{breadcrumb}\n\n{full_text}",
        ))

    # ─── L2 paragraph chunks (1-para sliding overlap) ────────
    l2_chunks: List[L2ParaChunk] = []
    for i, p in enumerate(raw_paras):
        prev_text = raw_paras[i - 1]["text"] if i > 0 else ""
        breadcrumb = _breadcrumb(title, court, p["section_type"], p["id"])
        overlap    = (prev_text + "\n\n") if prev_text else ""
        l2_chunks.append(L2ParaChunk(
            tid          = tid,
            title        = title,
            para_id      = p["id"],
            section_type = p["section_type"],
            text         = f"{breadcrumb}\n\n{overlap}{p['text']}",
        ))

    # ─── L3 atomic proposition chunks ────────────────────────
    # Split Held/Reasoning paragraphs into individual sentences.
    # Each substantial sentence becomes an atomic verifiable unit.
    l3_chunks: List[L3AtomicChunk] = []
    for p in raw_paras:
        if p["section_type"].lower() not in L3_SECTIONS:
            continue
        sentences = split_into_propositions(p["text"], min_words=10)
        for si, sent in enumerate(sentences):
            breadcrumb = _breadcrumb(title, court, "ATOMIC", p["id"])
            l3_chunks.append(L3AtomicChunk(
                tid            = tid,
                title          = title,
                para_id        = p["id"],
                section_type   = p["section_type"],
                sentence_index = si,
                text           = f"{breadcrumb}\n\n{sent}",
            ))

    # ─── Ratio chunks ────────────────────────────────────────
    # TODO: LLM batch call for RATIO / OBITER / ARGUMENT classification.
    # Placeholder: paragraphs from Held/Reasoning treated as candidate ratio.
    ratio_chunks: List[RatioChunk] = []
    for p in raw_paras:
        if p["section_type"].lower() in L3_SECTIONS:
            ratio_chunks.append(RatioChunk(
                tid             = tid,
                title           = title,
                authority_score = auth,
                text            = f"{_breadcrumb(title, court, 'RATIO')}\n\n{p['text']}",
            ))

    # ─── Issue-Held pairs ────────────────────────────────────
    # TODO: LLM extraction
    issue_held_pairs: List[IssueHeldPair] = []

    # ─── Citation edges for Neo4j ────────────────────────────
    # ─── Citation edges for Neo4j (GRAPH-ONLY — NOT embedded) ─
    # Citation edges are written to Neo4j as typed relationships.
    # The citing TEXT already lives in the L2 paragraph chunk and
    # will be found via vector/BM25 search. Embedding citation
    # chunks separately would double storage without retrieval benefit.
    citation_edges: List[CitationEdge] = []
    all_text = " ".join(p["text"] for p in raw_paras)

    # Reporter-format citations (AIR, SCC, etc.)
    for cit_str in extract_reporter_citations(all_text):
        citation_edges.append(CitationEdge(
            from_tid        = tid,
            from_title      = title,
            to_citation_str = cit_str,
            citation_type   = "reporter",
            rel_type        = "CITES",
        ))

    # Case-name citations (Party1 v. Party2)
    for cit in extract_case_name_citations(all_text):
        citation_edges.append(CitationEdge(
            from_tid        = tid,
            from_title      = title,
            to_citation_str = cit["raw_text"],
            citation_type   = "case_name",
            rel_type        = "CITES",
        ))

    return {
        "doc_type"       : "judgment",
        "l0"             : asdict(l0),
        "l1_sections"    : [asdict(c) for c in l1_chunks],
        "l2_paragraphs"  : [asdict(c) for c in l2_chunks],
        "l3_atomic"      : [asdict(c) for c in l3_chunks],
        "ratio_chunks"   : [asdict(c) for c in ratio_chunks],
        "issue_held"     : [asdict(c) for c in issue_held_pairs],
        "citation_edges" : [asdict(e) for e in citation_edges],
    }


# ─────────────────────────────────────────────
# STATUTE CHUNKER
# ─────────────────────────────────────────────

def _chunk_statute(data: dict) -> dict:
    title  = data["title"]
    tid    = data["tid"]
    text   = data.get("cleaned_text", "").strip()

    act_name = re.sub(r'^(Section|Article)\s+\S+\s+in\s+', '', title, flags=re.IGNORECASE).strip()
    if not act_name:
        act_name = data.get("docsource", "").replace("Union of India - ", "").strip()

    provision = StatuteProvisionChunk(
        tid          = tid,
        title        = title,
        date         = data.get("publishdate", ""),
        act_name     = act_name,
        section_ref  = re.search(r'(Section|Article)\s+\S+', title, re.IGNORECASE).group(0)
                       if re.search(r'(Section|Article)\s+\S+', title, re.IGNORECASE) else title,
        text         = text,
        aliases      = _generate_statute_aliases(title),
        citedby_tids = [c["tid"] for c in data.get("citedby", [])],
    )

    citation_edges = []
    for citing in data.get("citedby", []):
        citation_edges.append({
            "from_tid"   : citing["tid"],
            "from_title" : citing["title"],
            "to_tid"     : tid,
            "to_title"   : title,
            "rel_type"   : "CITES_STATUTE",
        })

    return {
        "doc_type"       : "statute",
        "provision"      : asdict(provision),
        "citation_edges" : citation_edges,
    }


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def chunk_document(data: dict) -> dict:
    if _is_statute(data):
        return _chunk_statute(data)
    return _chunk_judgment(data)


# ─────────────────────────────────────────────
# BATCH RUNNER
# ─────────────────────────────────────────────

def chunk_directory(json_dir: str, out_dir: str = "./chunks") -> dict:
    import os, pathlib
    pathlib.Path(out_dir).mkdir(exist_ok=True)

    judgments = statutes = total_chunks = 0
    all_edges = []

    for fname in sorted(os.listdir(json_dir)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(json_dir, fname)) as f:
            data = json.load(f)

        result = chunk_document(data)
        out_path = os.path.join(out_dir, fname)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)

        all_edges.extend(result.get("citation_edges", []))

        if result["doc_type"] == "judgment":
            judgments    += 1
            total_chunks += (1
                + len(result["l1_sections"])
                + len(result["l2_paragraphs"])
                + len(result["l3_atomic"])
                + len(result["ratio_chunks"]))
        else:
            statutes     += 1
            total_chunks += 1

    edges_path = os.path.join(out_dir, "_citation_edges.json")
    with open(edges_path, "w") as f:
        json.dump(all_edges, f, indent=2)

    return {
        "judgments"   : judgments,
        "statutes"    : statutes,
        "total_chunks": total_chunks,
        "edge_file"   : edges_path,
    }


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path:
        with open(path) as f:
            data = json.load(f)
        result = chunk_document(data)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python chunker.py path/to/doc.json")
