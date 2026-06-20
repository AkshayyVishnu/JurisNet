"""
researcher.py
─────────────
The Researcher module (CLAUDE.md §2, §2a, §6, §7). SECOND stage of the pipeline.

It takes a sub-question, determines the retrieval budget (top_k) based on
complexity, calls the teammate's HybridRetriever (Pull A/B), and runs regex-based
statute/provision extraction (Pull C) over the retrieved chunks, the sub-question
text, and the seed provision key.

Public entry point:
    run_researcher(sub_question: SubQuestion, *, retriever: Any = None)
        -> tuple[list[dict], list[str]]
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .schemas import Complexity, SubQuestion

# Act mappings for canonical suffix normalization
_ACT_MAP = {
    "cpc": "CPC",
    "c.p.c.": "CPC",
    "code of civil procedure": "CPC",
    "civil procedure": "CPC",
    "indian contract act": "Indian Contract Act",
    "contract act": "Indian Contract Act",
    "transfer of property": "Transfer of Property Act",
    "tpa": "Transfer of Property Act",
    "t.p.a.": "Transfer of Property Act",
    "specific relief": "Specific Relief Act",
    "sra": "Specific Relief Act",
    "s.r.a.": "Specific Relief Act",
    "limitation act": "Limitation Act",
    "arbitration act": "Arbitration and Conciliation Act",
    "arbitration and conciliation": "Arbitration and Conciliation Act",
}

# ─────────────────────────────────────────────
# Regex patterns for Pull C
# ─────────────────────────────────────────────

# Matches: "Order 39 Rule 1 CPC", "Order XXXIX Rule 1 of Code of Civil Procedure"
_ORDER_RULE_RE = re.compile(
    r'\b(?:Order|Ord\.)\s+([ivxlcdm\d]+)(?:\s*,\s*|\s+)(?:Rule|R\.)\s+(\d+[a-z]?)\b(?:\s+(?:of\s+)?(?:the\s+)?([A-Za-z\s\.]+Act|Code\s+of\s+Civil\s+Procedure|CPC|C\.P\.C\.))?',
    re.IGNORECASE
)

# Matches: "Rule 1 of Order 39", "Rule 10, Order 1 CPC"
_RULE_OF_ORDER_RE = re.compile(
    r'\b(?:Rule|R\.)\s+(\d+[a-z]?)\s+(?:of\s+)?(?:Order|Ord\.)\s+([ivxlcdm\d]+)\b(?:\s+(?:of\s+)?(?:the\s+)?([A-Za-z\s\.]+Act|Code\s+of\s+Civil\s+Procedure|CPC|C\.P\.C\.))?',
    re.IGNORECASE
)

# Matches: "Section 80 CPC", "Section 23 of the Indian Contract Act", "Section 53A TPA"
_SECTION_ACT_RE = re.compile(
    r'\b(?:Section|Sec\.|S\.)\s*(\d+[a-z]?)\s+(?:of\s+)?(?:the\s+)?([A-Za-z\s\.]+Act|Code\s+of\s+Civil\s+Procedure|CPC|C\.P\.C\.|TPA|T\.P\.A\.|SRA|S\.R\.A\.|Limitation\s+Act|Arbitration\s+Act)\b',
    re.IGNORECASE
)

# Matches: "Section 80", "S. 23", "Sec. 53A" (standalone, needs context_title to resolve Act name)
_SECTION_STANDALONE_RE = re.compile(
    r'\b(?:Section|Sec\.|S\.)\s*(\d+[a-z]?)\b',
    re.IGNORECASE
)

# Matches: "Order 39 Rule 1" (standalone, defaults to CPC in our civil scope)
_ORDER_RULE_STANDALONE_RE = re.compile(
    r'\b(?:Order|Ord\.)\s+([ivxlcdm\d]+)(?:\s*,\s*|\s+)(?:Rule|R\.)\s+(\d+[a-z]?)\b',
    re.IGNORECASE
)


def _detect_act(text: str) -> Optional[str]:
    """Identify act name and return its canonical abbreviation/suffix."""
    if not text:
        return None
    lower = text.lower()
    for name, canonical in _ACT_MAP.items():
        clean_name = name.replace(".", "").replace(" ", "")
        clean_lower = lower.replace(".", "").replace(" ", "")
        if clean_name in clean_lower:
            return canonical
    return None


def extract_statutes_from_text(text: str, context_title: Optional[str] = None) -> List[str]:
    """
    Run regex-based parser (Pull C) over a target text block.
    Resolves standalone sections using context_title if available.
    """
    if not text:
        return []

    results: Set[str] = set()

    # 1. Search for Order + Rule mentions
    # (a) Order X Rule Y Act
    for m in _ORDER_RULE_RE.finditer(text):
        order_num = m.group(1).upper()
        rule_num = m.group(2)
        act_text = m.group(3)
        act_name = _detect_act(act_text) if act_text else "CPC"
        results.add(f"Order {order_num} Rule {rule_num} {act_name}")

    # (b) Rule Y of Order X Act
    for m in _RULE_OF_ORDER_RE.finditer(text):
        rule_num = m.group(1)
        order_num = m.group(2).upper()
        act_text = m.group(3)
        act_name = _detect_act(act_text) if act_text else "CPC"
        results.add(f"Order {order_num} Rule {rule_num} {act_name}")

    # 2. Search for Section + Act mentions
    for m in _SECTION_ACT_RE.finditer(text):
        sec_num = m.group(1)
        act_text = m.group(2)
        act_name = _detect_act(act_text) or act_text.strip()
        results.add(f"Section {sec_num} {act_name}")

    # 3. Standalone Order + Rule (defaults to CPC)
    for m in _ORDER_RULE_STANDALONE_RE.finditer(text):
        order_num = m.group(1).upper()
        rule_num = m.group(2)
        # Check if CPC was already added for this order/rule to avoid double adding
        results.add(f"Order {order_num} Rule {rule_num} CPC")

    # 4. Standalone Sections (requires context_title to resolve Act name)
    act_from_context = _detect_act(context_title) if context_title else None
    if act_from_context:
        for m in _SECTION_STANDALONE_RE.finditer(text):
            sec_num = m.group(1)
            results.add(f"Section {sec_num} {act_from_context}")

    return sorted(list(results))


def run_researcher(
    sub_question: SubQuestion,
    *,
    retriever: Any = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Run the Researcher stage for a sub-question.

    Args:
        sub_question: The SubQuestion to perform retrieval for.
        retriever:    Injectable retriever instance. If None, constructs HybridRetriever.

    Returns:
        tuple (evidence_pool, surfaced_statutes)
    """
    # 1. Map complexity to search budget (top_k sizing)
    complexity_map = {
        Complexity.SIMPLE: 10,
        Complexity.MODERATE: 20,
        Complexity.COMPLEX: 40,
    }
    top_k = complexity_map.get(sub_question.complexity, 20)

    # 2. Retrieve chunks (Pull A + B)
    evidence_pool: List[Dict[str, Any]] = []
    
    # Try to load retriever dynamically if not injected
    if retriever is None:
        try:
            from retrieval.hybrid_retriever import HybridRetriever
            # Instantiate client
            retriever = HybridRetriever()
            should_close = True
        except Exception:
            retriever = None
            should_close = False
    else:
        should_close = False

    if retriever is not None:
        try:
            # We callretrieve. Note that hybrid_retriever maps search based on intent.
            # Default to "DEFAULT" or resolve intent.
            evidence_pool = retriever.retrieve(sub_question.text, top_k=top_k)
        except Exception as e:
            # Degrade gracefully in tests / missing DB context
            print(f"[Researcher warning] Retrieval failed: {e}")
            evidence_pool = []
        finally:
            if should_close and hasattr(retriever, "close"):
                retriever.close()

    # 3. Pull C: regex statute extraction
    surfaced_statutes: Set[str] = set()

    # Add seed provision_key if Query Agent supplied it
    if sub_question.provision_key:
        extracted = extract_statutes_from_text(sub_question.provision_key)
        if extracted:
            surfaced_statutes.update(extracted)
        else:
            surfaced_statutes.add(sub_question.provision_key.strip())

    # Scan the sub-question text itself
    surfaced_statutes.update(extract_statutes_from_text(sub_question.text))

    # Scan each retrieved chunk text and title
    for chunk in evidence_pool:
        text = chunk.get("text", "")
        title = chunk.get("title", "")
        surfaced_statutes.update(extract_statutes_from_text(text, context_title=title))

    return evidence_pool, sorted(list(surfaced_statutes))
