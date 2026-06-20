"""
checklist_resolver.py
─────────────────────
Checklist Resolver module (CLAUDE.md §2, §2a, §7).

A MECHANICAL cache-backed module (not an agent). Takes a provision name
string, looks up the actual provision document in LEGAL_DATA/provisions/,
makes one grounded LLM extraction call on a cache miss, caches the result,
and returns a grouped checklist.

Public entry point:
    resolve_checklist(provision_key, llm=None, db_path=None, data_dir=None)
        -> ChecklistResult
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from .schemas import ChecklistCondition, ChecklistExtraction, ChecklistResult

# ─────────────────────────────────────────────
# Default paths (relative to repo root)
# ─────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = str(_REPO_ROOT / "checklist_cache.db")
_DEFAULT_DATA_DIR = str(_REPO_ROOT / "LEGAL_DATA" / "provisions")
_DEFAULT_MODEL = "gemini-2.0-flash"

# Act name → abbreviation map (shared with chunker's _generate_statute_aliases)
_ACT_ABBREVS: dict[str, list[str]] = {
    "code of civil procedure": ["cpc", "c.p.c."],
    "code of criminal procedure": ["crpc", "cr.p.c."],
    "indian penal code": ["ipc", "i.p.c."],
    "bharatiya nyaya sanhita": ["bns", "b.n.s."],
    "bharatiya nagarik suraksha sanhita": ["bnss", "b.n.s.s."],
    "bharatiya sakshya adhiniyam": ["bsa", "b.s.a."],
    "indian evidence act": ["iea", "evidence act"],
    "companies act": ["companies act"],
    "income tax act": ["it act", "income tax"],
    "constitution of india": ["constitution", "coi"],
    "transfer of property act": ["tpa", "t.p.a."],
    "indian contract act": ["contract act"],
    "negotiable instruments act": ["ni act", "n.i. act"],
    "specific relief act": ["sra", "specific relief"],
    "limitation act": ["limitation act"],
    "arbitration and conciliation act": ["arbitration act"],
}

# Reverse map: abbreviation → full name (first full name wins)
_ABBREV_TO_FULL: dict[str, str] = {}
for _full, _abbrevs in _ACT_ABBREVS.items():
    for _abbr in _abbrevs:
        _ABBREV_TO_FULL.setdefault(_abbr.lower(), _full)
# Add the full names themselves as identity mappings
for _full in _ACT_ABBREVS:
    _ABBREV_TO_FULL.setdefault(_full.lower(), _full)


# ─────────────────────────────────────────────
# Key canonicalization (reorder-safe)
# ─────────────────────────────────────────────

# Patterns to extract section/article/order+rule identifiers
_SECTION_RE = re.compile(
    r'\b(?:section|sec\.|s\.)\s*(\d+[a-z]?)\b', re.IGNORECASE
)
_ARTICLE_RE = re.compile(
    r'\b(?:article|art\.)\s*(\d+(?:\s*\([^)]+\))*)\b', re.IGNORECASE
)
_ORDER_RULE_RE = re.compile(
    r'\border(?:er)?\s+(\d+|[ivxlcdm]+)\s+rule\s+(\d+[a-z]?)\b', re.IGNORECASE
)
_ORDER_RE = re.compile(
    r'\border(?:er)?\s+(\d+|[ivxlcdm]+)\b', re.IGNORECASE
)
_RULE_RE = re.compile(
    r'\brule\s+(\d+[a-z]?)\b', re.IGNORECASE
)


def _extract_act_name(text: str) -> str | None:
    """
    Try to identify which act the text refers to. Check the full act names
    first, then abbreviations, longest match first to avoid partial hits.
    """
    lower = text.lower()
    # Sort candidates by length (longest first) so "code of civil procedure"
    # matches before "civil procedure" if both were in the map.
    for name in sorted(_ABBREV_TO_FULL, key=len, reverse=True):
        # Strip periods from both sides for matching (e.g. "c.p.c." vs "cpc")
        clean_name = name.replace(".", "").replace(" ", "")
        clean_lower = lower.replace(".", "").replace(" ", "")
        if clean_name in clean_lower:
            return _ABBREV_TO_FULL[name]
        if name in lower:
            return _ABBREV_TO_FULL[name]
    return None


def _canonicalize(provision_key: str) -> str:
    """
    Produce a canonical cache key that is order-independent.

    "Section 23 Indian Contract Act" → "section_23__indian_contract_act"
    "Indian Contract Act Section 23" → "section_23__indian_contract_act"
    "S. 80 CPC"                      → "section_80__code_of_civil_procedure"
    "Order 39 Rule 1 CPC"            → "order_39_rule_1__code_of_civil_procedure"
    "res judicata"                    → "res_judicata" (fallback)
    """
    if not provision_key or not provision_key.strip():
        return ""

    text = provision_key.strip()

    # Try to extract structured parts
    identifier = ""

    # Order + Rule (most specific, check first)
    m = _ORDER_RULE_RE.search(text)
    if m:
        identifier = f"order_{m.group(1).lower()}_rule_{m.group(2).lower()}"
    else:
        # Section
        m = _SECTION_RE.search(text)
        if m:
            identifier = f"section_{m.group(1).lower()}"
        else:
            # Article
            m = _ARTICLE_RE.search(text)
            if m:
                num = m.group(1).replace("(", "_").replace(")", "").replace(" ", "").lower()
                identifier = f"article_{num}"
            else:
                # Standalone Order
                m = _ORDER_RE.search(text)
                if m:
                    identifier = f"order_{m.group(1).lower()}"
                else:
                    # Standalone Rule
                    m = _RULE_RE.search(text)
                    if m:
                        identifier = f"rule_{m.group(1).lower()}"

    # Try to extract act name
    act = _extract_act_name(text)
    act_part = act.lower().replace(" ", "_") if act else ""

    if identifier and act_part:
        return f"{identifier}__{act_part}"
    elif identifier:
        return identifier
    elif act_part:
        return act_part
    else:
        # Fallback: collapse to a simple normalized form
        return re.sub(r'\s+', '_', text.strip().lower())


# ─────────────────────────────────────────────
# SQLite cache layer
# ─────────────────────────────────────────────

def _init_cache(db_path: str) -> sqlite3.Connection:
    """Create the cache table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checklists (
            canonical_key TEXT PRIMARY KEY,
            provision_key TEXT NOT NULL,
            checklist_json TEXT NOT NULL,
            group_labels_json TEXT NOT NULL,
            group_gates_json TEXT NOT NULL DEFAULT '[]',
            provision_snippet TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def _cache_get(conn: sqlite3.Connection, canonical_key: str) -> ChecklistResult | None:
    """Lookup a cached checklist by canonical key."""
    row = conn.execute(
        "SELECT provision_key, checklist_json, group_labels_json, "
        "group_gates_json, provision_snippet "
        "FROM checklists WHERE canonical_key = ?",
        (canonical_key,),
    ).fetchone()
    if row is None:
        return None
    # Deserialize: each condition is stored as {"text": ..., "critical": ...}
    raw_checklist = json.loads(row[1])
    checklist = [
        [ChecklistCondition(**c) for c in group]
        for group in raw_checklist
    ]
    return ChecklistResult(
        provision_key=row[0],
        canonical_key=canonical_key,
        checklist=checklist,
        group_labels=json.loads(row[2]),
        group_gates=json.loads(row[3]),
        source="cache",
        provision_text_snippet=row[4],
    )


def _cache_put(conn: sqlite3.Connection, result: ChecklistResult) -> None:
    """Insert or replace a checklist in the cache."""
    conn.execute(
        "INSERT OR REPLACE INTO checklists "
        "(canonical_key, provision_key, checklist_json, group_labels_json, "
        "group_gates_json, provision_snippet) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            result.canonical_key,
            result.provision_key,
            json.dumps([[c.model_dump() for c in group] for group in result.checklist]),
            json.dumps(result.group_labels),
            json.dumps(result.group_gates),
            result.provision_text_snippet,
        ),
    )
    conn.commit()


# ─────────────────────────────────────────────
# Provision document lookup
# ─────────────────────────────────────────────

def _lookup_provision(provision_key: str, data_dir: str) -> tuple[str, int] | None:
    """
    Scan LEGAL_DATA/provisions/*.json to find the matching provision.

    Match strategy:
      1. Extract section/article number from provision_key
      2. For each JSON file, check if `title` contains that number
      3. Verify the act name appears in the `body` field
      4. Also check chunker-generated aliases

    Returns (body_text, doc_id) or None if not found.
    """
    if not os.path.isdir(data_dir):
        return None

    key_lower = provision_key.lower().strip()

    # Extract what we're looking for
    section_num = None
    m = _SECTION_RE.search(key_lower)
    if m:
        section_num = m.group(1)
    article_num = None
    m = _ARTICLE_RE.search(key_lower)
    if m:
        article_num = m.group(1).replace(" ", "")
    order_num = None
    m = _ORDER_RE.search(key_lower)
    if m:
        order_num = m.group(1)
    rule_num = None
    m = _RULE_RE.search(key_lower)
    if m:
        rule_num = m.group(1)

    # Extract act name from the provision key
    act_name = _extract_act_name(provision_key)

    for fname in os.listdir(data_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(data_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        title = data.get("title", "")
        body = data.get("body", "")
        title_lower = title.lower()
        body_lower = body.lower()

        # Check title matches the section/article number
        title_match = False
        if section_num and re.search(rf'\bsection\s+{re.escape(section_num)}\b', title_lower):
            title_match = True
        elif article_num and re.search(rf'\barticle\s+{re.escape(article_num)}\b', title_lower):
            title_match = True
        # For Order X Rule Y, the title is often just "Rule Y" or "Order X Rule Y"
        elif order_num and rule_num:
            if (re.search(rf'\border\s+{re.escape(order_num)}\b', title_lower + " " + body_lower[:200])
                    and re.search(rf'\brule\s+{re.escape(rule_num)}\b', title_lower + " " + body_lower[:200])):
                title_match = True

        if not title_match:
            continue

        # If we know which act, verify it appears in the body
        if act_name:
            act_found = False
            # The body text typically starts with "Section X in The [Act Name], [Year]"
            # Check both the full name and abbreviations
            candidates = [act_name.lower()]
            if act_name.lower() in _ACT_ABBREVS:
                candidates.extend(a.lower() for a in _ACT_ABBREVS[act_name.lower()])
            for cand in candidates:
                if cand.replace(".", "") in body_lower.replace(".", ""):
                    act_found = True
                    break
            if not act_found:
                continue

        return body, data.get("doc_id", 0)

    return None


# ─────────────────────────────────────────────
# LLM construction (Google Gemini, structured output)
# ─────────────────────────────────────────────

EXTRACTION_PROMPT = """\
You are a legal checklist extractor for Indian civil law.

Below is the FULL TEXT of a legal provision. Extract every condition,
requirement, or element that must be satisfied for this provision to
apply or be invoked.

RULES:
1. GROUP the conditions by sub-section or logical category. Each group
   should have a label (e.g. "Sub-section (1) requirements") and a list
   of conditions.
2. Each condition must be a SINGLE, self-contained, verifiable statement.
3. If the provision contains ENUMERATED CLAUSES like (a), (b), (c), (d)
   or (i), (ii), (iii), each clause MUST become its OWN separate
   condition. NEVER bundle multiple enumerated clauses into one condition
   string. For example, if the text says "notice shall be delivered to
   (a) Secretary to Central Govt; (b) General Manager of railway; (c)
   Chief Secretary of J&K", produce THREE separate conditions, one per
   clause.
4. If the provision contains multiple distinct provisos or exceptions,
   represent each as its own separate condition.
5. For each condition, set "critical": true ONLY if failing this specific
   condition means the provision cannot apply AT ALL — no court could
   excuse it. If the statute text elsewhere states that defects in this
   condition are excused, cured, or not grounds for dismissal (e.g.,
   "shall not be dismissed merely by reason of..."), mark that condition
   "critical": false, even though it may be phrased as mandatory ("shall").
6. CURING LANGUAGE: if a sub-section contains language that excuses,
   cures, or forgives defects in OTHER conditions (e.g. "shall not be
   dismissed merely by reason of any error or defect in X"), you must:
   (a) Extract that curing language as its own condition, marked
       "critical": false.
   (b) Re-examine every OTHER condition that the curing language refers
       to and mark THOSE as "critical": false too — even if they use
       mandatory phrasing like "shall have given" or "shall have been
       delivered" — because the statute itself excuses getting them wrong.
7. ALTERNATIVES: if a sub-section presents two or more conditions as
   alternatives (e.g. "if X is tendered, OR if proof of Y is given"),
   assign all alternatives the SAME "alternative_group" tag string (e.g.
   "stoppage_alternatives") so the Auditor knows only ONE needs to be
   satisfied. Set "alternative_group": null for standalone conditions.
8. CONDITIONAL GROUPS: if an entire sub-section only applies under a
   specific factual precondition (e.g. sub-section (2) only applies when
   "plaintiff is claiming urgent or immediate relief", or a rule only
   applies when "sale is adjourned for more than thirty days"), set the
   group's "applies_only_if" to that precondition string. The Auditor
   must check this gate FIRST before evaluating the group's conditions.
   Set "applies_only_if": null for unconditionally-applicable groups.
9. Extract ONLY from the text below. Do not add conditions not present
   in the text.
10. Ignore High Court Amendments sections — focus on the main provision
    text only.

--- PROVISION TEXT ---
{provision_body}
--- END ---
"""


def _build_extraction_llm(model: str | None = None) -> Any:
    """
    Build a Google Gemini chat model that returns a ChecklistExtraction.

    Reads GOOGLE_API_KEY from .env / environment.
    Falls back to Groq if GOOGLE_API_KEY is not set but GROQ_API_KEY is.
    """
    load_dotenv()
    model = model or os.environ.get("CHECKLIST_MODEL") or _DEFAULT_MODEL

    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(model=model, temperature=0)
        return llm.with_structured_output(ChecklistExtraction)

    # Fallback: Groq
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        from langchain_groq import ChatGroq
        fallback_model = os.environ.get("CHECKLIST_MODEL") or "llama-3.3-70b-versatile"
        llm = ChatGroq(model=fallback_model, temperature=0)
        return llm.with_structured_output(ChecklistExtraction)

    raise RuntimeError(
        "Neither GOOGLE_API_KEY nor GROQ_API_KEY is set. "
        "Add GOOGLE_API_KEY to .env (free key: https://aistudio.google.com/apikey)."
    )


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

def resolve_checklist(
    provision_key: str | None,
    *,
    query_type: str | None = None,
    llm: Any = None,
    db_path: str | None = None,
    data_dir: str | None = None,
    model: str | None = None,
) -> ChecklistResult:
    """
    Resolve a provision key to a grouped checklist.

    Args:
        provision_key: The statute/provision name (e.g. "Section 80 CPC").
                       None or empty → short-circuit to empty result.
        query_type:    The type of the query. If 'informational', it short-circuits.
        llm:           Injectable structured LLM for testing. If None, builds
                       a real Gemini (or Groq fallback) client.
        db_path:       Path to the SQLite cache file. Defaults to repo root.
        data_dir:      Path to LEGAL_DATA/provisions/. Defaults to repo root.
        model:         Explicit model override (only when llm is None).

    Returns:
        ChecklistResult with source "cache", "llm", "not_found", or "skipped_informational".
    """
    # Short-circuit: informational queries don't need checklists
    if query_type == "informational":
        return ChecklistResult(source="skipped_informational")

    # Short-circuit: empty/None key
    if not provision_key or not provision_key.strip():
        return ChecklistResult(source="not_found")

    provision_key = provision_key.strip()
    canonical = _canonicalize(provision_key)
    db_path = db_path or _DEFAULT_DB_PATH
    data_dir = data_dir or _DEFAULT_DATA_DIR

    # Cache check
    conn = _init_cache(db_path)
    try:
        cached = _cache_get(conn, canonical)
        if cached is not None:
            # Update the provision_key to the one the caller used (may differ)
            cached.provision_key = provision_key
            return cached

        # Cache miss — look up the provision document
        lookup = _lookup_provision(provision_key, data_dir)
        if lookup is None:
            return ChecklistResult(
                provision_key=provision_key,
                canonical_key=canonical,
                source="not_found",
            )

        body_text, doc_id = lookup
        snippet = body_text[:200] + ("..." if len(body_text) > 200 else "")

        # One LLM extraction call, grounded in the actual provision text
        structured_llm = llm if llm is not None else _build_extraction_llm(model)
        messages = [
            ("system", "You extract legal checklists from provision text."),
            ("human", EXTRACTION_PROMPT.format(provision_body=body_text)),
        ]
        extraction: ChecklistExtraction = structured_llm.invoke(messages)

        # Build result
        result = ChecklistResult(
            provision_key=provision_key,
            canonical_key=canonical,
            checklist=[g.conditions for g in extraction.groups],
            group_labels=[g.group_label for g in extraction.groups],
            group_gates=[g.applies_only_if for g in extraction.groups],
            source="llm",
            provision_text_snippet=snippet,
        )

        # Cache the result
        _cache_put(conn, result)
        return result
    finally:
        conn.close()


# ─────────────────────────────────────────────
# Manual CLI: uv run python -m agents.checklist_resolver "Section 80 CPC"
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    key = sys.argv[1] if len(sys.argv) > 1 else "Section 80 CPC"
    print(f"Resolving: {key!r}")
    t0 = time.time()
    result = resolve_checklist(key)
    elapsed = time.time() - t0
    print(f"Source: {result.source}  ({elapsed:.3f}s)")
    print(json.dumps(result.model_dump(), indent=2))
