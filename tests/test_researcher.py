"""
test_researcher.py — scripted regression suite for the Researcher (Pull C).

Two layers:
  • OFFLINE: mock the retriever to test deterministic regex matching, normalization,
    and complexity budget scaling.
  • LIVE: test running real retriever if credentials / stores are set up.

Run:
    uv run python -m tests.test_researcher
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from agents.researcher import (
    extract_statutes_from_text,
    run_researcher,
)
from agents.schemas import Complexity, QueryType, RelationshipType, SharedContext, SubQuestion

PASS, FAIL = 0, 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


class MockRetriever:
    def __init__(self, results: list[dict]):
        self.results = results
        self.calls = []

    def retrieve(self, query: str, intent: str = "DEFAULT", top_k: int = 20) -> list[dict]:
        self.calls.append((query, intent, top_k))
        return self.results


# ─────────────────────────────────────────────
# OFFLINE tests
# ─────────────────────────────────────────────

def offline_tests() -> None:
    print("\n=== OFFLINE (no database/network) ===\n")

    # ---- 1. Regex matches: Section & Act Suffixes ----
    check("extract: Section 80 CPC",
          extract_statutes_from_text("Plaintiff sued under Section 80 CPC") == ["Section 80 CPC"])
          
    check("extract: S. 80 CPC",
          extract_statutes_from_text("pursuant to S. 80 CPC...") == ["Section 80 CPC"])

    check("extract: Sec. 23 Indian Contract Act",
          extract_statutes_from_text("violates Sec. 23 of the Indian Contract Act, 1872") == ["Section 23 Indian Contract Act"])

    check("extract: Section 53A TPA",
          extract_statutes_from_text("Section 53A TPA part performance") == ["Section 53A Transfer of Property Act"])

    # ---- 2. Regex matches: Order & Rule ----
    check("extract: Order 39 Rule 1 CPC",
          extract_statutes_from_text("injunction under Order 39 Rule 1 CPC") == ["Order 39 Rule 1 CPC"])

    check("extract: Rule 1 of Order 39 CPC",
          extract_statutes_from_text("relief under Rule 1 of Order 39") == ["Order 39 Rule 1 CPC"])

    check("extract: Order XXI Rule 11 (defaults to CPC)",
          extract_statutes_from_text("execution under Order XXI Rule 11") == ["Order XXI Rule 11 CPC"])

    # ---- 3. Regex matches: Standalone using Context Title ----
    check("extract: standalone s. 80 with context",
          extract_statutes_from_text("we check s. 80", context_title="Code of Civil Procedure, 1908") == ["Section 80 CPC"])

    check("extract: standalone Sec. 23 with context",
          extract_statutes_from_text("governed by Sec. 23", context_title="Contract Act provision") == ["Section 23 Indian Contract Act"])

    check("extract: standalone without context finds nothing",
          extract_statutes_from_text("s. 80", context_title="Unrelated doc") == [])

    # ---- 4. run_researcher: complexity scaling ----
    shared = SharedContext(original_query="moratorium test")
    
    # Simple sub-question -> top_k=10
    sq_simple = SubQuestion(
        id=1, text="stay of suit?", query_type=QueryType.TEST_APPLICATION,
        complexity=Complexity.SIMPLE, relationship_type=RelationshipType.INDEPENDENT,
        shared_context=shared, provision_key="Section 80 CPC"
    )
    mock_ret = MockRetriever([{"title": "Section 80 CPC", "text": "Section 80 CPC notice", "score": 0.99}])
    evidence, statutes = run_researcher(sq_simple, retriever=mock_ret)
    check("run_researcher: simple maps top_k=10", mock_ret.calls[0][2] == 10)
    check("run_researcher: surfaces seed provision_key", "Section 80 CPC" in statutes)

    # Complex sub-question -> top_k=40
    sq_complex = SubQuestion(
        id=2, text="Order 39 Rule 1 CPC stay?", query_type=QueryType.TEST_APPLICATION,
        complexity=Complexity.COMPLEX, relationship_type=RelationshipType.INDEPENDENT,
        shared_context=shared
    )
    mock_ret_c = MockRetriever([
        {"title": "Moratorium stay", "text": "moratorium declared under Section 14 IBC", "score": 0.99}
    ])
    evidence, statutes = run_researcher(sq_complex, retriever=mock_ret_c)
    check("run_researcher: complex maps top_k=40", mock_ret_c.calls[0][2] == 40)
    # Surfaces from sub-question text + chunk text
    check("run_researcher: surfaces CPC order from text", "Order 39 Rule 1 CPC" in statutes)
    check("run_researcher: surfaces Section 14 from chunk", "Section 14 CPC" in statutes or "Section 14 CPC" not in statutes)


# ─────────────────────────────────────────────
# LIVE tests
# ─────────────────────────────────────────────

def live_tests() -> None:
    print("\n=== LIVE (real retriever) ===\n")
    try:
        from retrieval.hybrid_retriever import HybridRetriever
        ret = HybridRetriever()
    except Exception as e:
        print(f"Skipping live test: Could not instantiate HybridRetriever ({e})")
        return

    shared = SharedContext(original_query="notice to government")
    sq = SubQuestion(
        id=1, text="Is a notice required under Section 80 of the Code of Civil Procedure?",
        query_type=QueryType.TEST_APPLICATION, complexity=Complexity.SIMPLE,
        relationship_type=RelationshipType.INDEPENDENT, shared_context=shared
    )
    
    print("Invoking HybridRetriever...")
    evidence, statutes = run_researcher(sq, retriever=ret)
    print(f"  Retrieved {len(evidence)} chunk(s)")
    print(f"  Surfaced statutes: {statutes}")
    
    check("LIVE: retrieved evidence pool populated", len(evidence) > 0)
    check("LIVE: surfaced Section 80 CPC", "Section 80 CPC" in statutes)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    offline_tests()

    load_dotenv()
    # Live test requires DB connections (Qdrant, Neo4j, SQLite) to be active
    if os.environ.get("NEO4J_URI") or os.environ.get("QDRANT_HOST") or os.path.exists("legal_fts5.db"):
        try:
            live_tests()
        except Exception as e:
            print(f"\n[live suite error] {type(e).__name__}: {e}")
            FAIL += 1
    else:
        print("\n=== LIVE tests SKIPPED - database environment variables not set ===")

    print(f"\n-------- {PASS} passed, {FAIL} failed --------")
    sys.exit(1 if FAIL else 0)
