"""
legal_fts5.py
─────────────
SQLite FTS5 setup for Indian legal search with compound token handling.

The problem: FTS5's default tokenizer splits "Section 302 IPC" into three
separate tokens. A search for `Section 302 IPC` matches ANY document
containing all three words anywhere — not just ones about Section 302.

Solution: Two-layer approach:
  1. Pre-processing: before indexing, wrap known compound legal identifiers
     in a normalized form that FTS5 treats as a single token.
     "Section 302 IPC" → "section_302_ipc" (one token, underscore-joined)
  2. Query-time: same normalization applied to the query before FTS5 search.

This avoids needing a custom C tokenizer (which FTS5 supports but is
painful to build and deploy).

Usage:
    from legal_fts5 import LegalFTS5

    db = LegalFTS5("legal.db")
    db.initialize()

    # Index a chunk:
    db.index_chunk(tid=70075, chunk_id="L2_p1", text="Section 302 of the IPC...")

    # Search:
    results = db.search("Section 302 IPC", top_k=50)
    # → [{"tid": 70075, "chunk_id": "L2_p1", "rank": 1, "snippet": "..."}, ...]
"""

import re
import sqlite3
from typing import List


# ─────────────────────────────────────────────
# Legal compound token patterns
# ─────────────────────────────────────────────
# These patterns are normalized BEFORE indexing and BEFORE querying
# so FTS5 treats them as single tokens.

# "Section 302" / "S. 302" / "Sec. 302A" → "section_302" / "section_302a"
SECTION_PATTERN = re.compile(
    r'\b(?:Section|Sec\.|S\.)\s*(\d+[A-Z]?)\b',
    re.IGNORECASE
)

# "Article 14" / "Art. 14" / "Article 19(1)(g)" → "article_14" / "article_19_1_g"
ARTICLE_PATTERN = re.compile(
    r'\b(?:Article|Art\.)\s*(\d+(?:\s*\([^)]+\))*)',
    re.IGNORECASE
)

# "Order XL" / "Order 21" → "order_xl" / "order_21"
ORDER_PATTERN = re.compile(
    r'\b(?:Order)\s+([IVXLCDM]+|\d+)\b',
    re.IGNORECASE
)

# "Rule 1" → "rule_1"
RULE_PATTERN = re.compile(
    r'\b(?:Rule)\s+(\d+[A-Z]?)\b',
    re.IGNORECASE
)

# Common act abbreviations as single tokens
# "IPC" stays "ipc", "CrPC" stays "crpc", "CPC" stays "cpc"
ACT_ABBREVS = {
    r'\bI\.?P\.?C\.?\b': 'ipc',
    r'\bCr\.?P\.?C\.?\b': 'crpc',
    r'\bC\.?P\.?C\.?\b': 'cpc',
    r'\bI\.?E\.?A\.?\b': 'iea',
    r'\bT\.?P\.?A\.?\b': 'tpa',
    r'\bN\.?I\.?\s*Act\b': 'ni_act',
    r'\bB\.?N\.?S\.?\b': 'bns',
    r'\bB\.?N\.?S\.?S\.?\b': 'bnss',
    r'\bB\.?S\.?A\.?\b': 'bsa',
}

# Compound: "Section 302 IPC" → "section_302_ipc"
SECTION_ACT_PATTERN = re.compile(
    r'\b(?:Section|Sec\.|S\.)\s*(\d+[A-Z]?)\s+(?:of\s+(?:the\s+)?)?'
    r'(IPC|CrPC|CPC|IEA|TPA|BNS|BNSS|BSA|'
    r'Indian Penal Code|Code of Criminal Procedure|'
    r'Code of Civil Procedure|Indian Evidence Act|'
    r'Transfer of Property Act|Constitution(?:\s+of\s+India)?)\b',
    re.IGNORECASE
)

# AIR citations: "AIR 1997 SC 3011" → "air_1997_sc_3011"
AIR_PATTERN = re.compile(
    r'\bAIR\s+(\d{4})\s+(\w+)\s+(\d+)\b',
    re.IGNORECASE
)

# SCC citations: "(1997) 6 SCC 241" → "scc_1997_6_241"
SCC_PATTERN = re.compile(
    r'\((\d{4})\)\s+(\d+)\s+SCC\s+(\d+)\b',
    re.IGNORECASE
)


def normalize_legal_text(text: str) -> str:
    """
    Normalize legal compound tokens before FTS5 indexing or querying.
    Replaces compound identifiers with underscore-joined single tokens.

    "Section 302 of the Indian Penal Code" → "section_302_ipc"
    "Article 19(1)(g)" → "article_19_1_g"
    "AIR 1997 SC 3011" → "air_1997_sc_3011"
    """
    result = text

    # 1. Compound: "Section 302 IPC" → "section_302_ipc" (most specific first)
    def _section_act_replace(m):
        sec = m.group(1).lower()
        act = m.group(2).strip()
        # Normalize act name to abbreviation
        act_map = {
            "indian penal code": "ipc",
            "code of criminal procedure": "crpc",
            "code of civil procedure": "cpc",
            "indian evidence act": "iea",
            "transfer of property act": "tpa",
            "constitution of india": "constitution",
            "constitution": "constitution",
        }
        act_norm = act_map.get(act.lower(), act.lower().replace(" ", "_"))
        return f"section_{sec}_{act_norm}"

    result = SECTION_ACT_PATTERN.sub(_section_act_replace, result)

    # 2. Standalone sections: "Section 302" → "section_302"
    result = SECTION_PATTERN.sub(
        lambda m: f"section_{m.group(1).lower()}", result
    )

    # 3. Articles: "Article 19(1)(g)" → "article_19_1_g"
    def _article_replace(m):
        num = m.group(1).replace("(", "_").replace(")", "").replace(" ", "").lower()
        return f"article_{num}"
    result = ARTICLE_PATTERN.sub(_article_replace, result)

    # 4. Orders: "Order XL" → "order_xl"
    result = ORDER_PATTERN.sub(
        lambda m: f"order_{m.group(1).lower()}", result
    )

    # 5. Rules: "Rule 1" → "rule_1"
    result = RULE_PATTERN.sub(
        lambda m: f"rule_{m.group(1).lower()}", result
    )

    # 6. Act abbreviations with periods: "I.P.C." → "ipc"
    for pattern, replacement in ACT_ABBREVS.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # 7. AIR citations: "AIR 1997 SC 3011" → "air_1997_sc_3011"
    result = AIR_PATTERN.sub(
        lambda m: f"air_{m.group(1)}_{m.group(2).lower()}_{m.group(3)}", result
    )

    # 8. SCC citations: "(1997) 6 SCC 241" → "scc_1997_6_241"
    result = SCC_PATTERN.sub(
        lambda m: f"scc_{m.group(1)}_{m.group(2)}_{m.group(3)}", result
    )

    return result


class LegalFTS5:
    """
    SQLite FTS5 wrapper with legal compound token normalization.
    Handles indexing and searching with proper legal identifier matching.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def initialize(self):
        """Create the FTS5 virtual table."""
        self.conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS legal_fts USING fts5(
                tid UNINDEXED,
                chunk_id UNINDEXED,
                chunk_type UNINDEXED,
                text,
                tokenize = 'porter unicode61'
            );
        """)
        self.conn.commit()

    def index_chunk(self, tid: int, chunk_id: str, chunk_type: str, text: str):
        """Index a single chunk with legal token normalization."""
        normalized = normalize_legal_text(text)
        self.conn.execute(
            "INSERT INTO legal_fts (tid, chunk_id, chunk_type, text) VALUES (?, ?, ?, ?)",
            (tid, chunk_id, chunk_type, normalized),
        )

    def index_batch(self, chunks: list):
        """Index a batch of chunks. Each dict needs tid, chunk_id, chunk_type, text."""
        rows = [
            (c["tid"], c["chunk_id"], c["chunk_type"], normalize_legal_text(c["text"]))
            for c in chunks
        ]
        self.conn.executemany(
            "INSERT INTO legal_fts (tid, chunk_id, chunk_type, text) VALUES (?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def search(self, query: str, top_k: int = 50) -> List[dict]:
        """
        Search with legal token normalization applied to the query.
        Returns ranked results compatible with RRF fusion.
        """
        normalized_query = normalize_legal_text(query)

        # FTS5 match query — use quotes for phrase matching on compound tokens
        rows = self.conn.execute(
            """
            SELECT tid, chunk_id, chunk_type, rank,
                   snippet(legal_fts, 3, '<b>', '</b>', '...', 30) as snippet
            FROM legal_fts
            WHERE text MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (normalized_query, top_k),
        ).fetchall()

        results = []
        for i, row in enumerate(rows):
            results.append({
                "tid":        row["tid"],
                "chunk_id":   row["chunk_id"],
                "chunk_type": row["chunk_type"],
                "rank":       i + 1,           # 1-indexed for RRF
                "bm25_score": row["rank"],     # FTS5 rank (lower = better match)
                "snippet":    row["snippet"],
            })
        return results

    def close(self):
        self.conn.close()


# ─────────────────────────────────────────────
# Quick test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Normalization examples ===\n")
    tests = [
        "Section 302 of the Indian Penal Code",
        "Section 302 IPC",
        "S. 302 IPC",
        "Article 19(1)(g) of the Constitution",
        "Art. 21",
        "Order XL Rule 1",
        "AIR 1997 SC 3011",
        "(1997) 6 SCC 241",
        "Section 498A of the I.P.C.",
        "Sec. 125 Cr.P.C.",
    ]
    for t in tests:
        print(f"  {t:50s} → {normalize_legal_text(t)}")

    print("\n=== FTS5 search test ===\n")
    db = LegalFTS5()
    db.initialize()

    db.index_chunk(1, "L2_p1", "L2_paragraph",
        "The accused was charged under Section 302 of the Indian Penal Code for murder.")
    db.index_chunk(2, "L2_p2", "L2_paragraph",
        "Article 21 guarantees the right to life and personal liberty.")
    db.index_chunk(3, "L2_p3", "L2_paragraph",
        "The court relied on AIR 1997 SC 3011 for the workplace harassment guidelines.")
    db.conn.commit()

    for q in ["Section 302 IPC", "Article 21", "AIR 1997 SC 3011"]:
        results = db.search(q)
        print(f"  Query: {q}")
        for r in results:
            print(f"    rank={r['rank']}  tid={r['tid']}  snippet={r['snippet'][:80]}")
        print()

    db.close()
