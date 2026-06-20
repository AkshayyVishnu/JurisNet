"""
Query Understanding — classify a query's intent (for retrieval routing) and pull
key legal entities. Intent must be one of query_embedder.QUERY_ROUTES so it feeds
embed_query / the RRF weight presets.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.llm import chat, parse_json  # noqa: E402

INTENTS = ["STATUTORY", "CITATION_LOOKUP", "PRECEDENT", "CONCEPTUAL",
           "RIGHTS", "COMPARISON", "PROCEDURAL", "ARGUMENTATIVE"]

_PROMPT = """You route Indian civil-law queries. Classify the query's intent as EXACTLY one of:
- STATUTORY: asks what a specific section/provision says
- CITATION_LOOKUP: a specific citation/case reference (e.g. "AIR 1997 SC 3011")
- PRECEDENT: cases that followed/distinguished/applied something
- CONCEPTUAL: a legal concept/doctrine (e.g. "what is res judicata")
- RIGHTS: a right and competing rights
- COMPARISON: compare two provisions/cases
- PROCEDURAL: how to do a procedure (file, serve, set aside)
- ARGUMENTATIVE: a fact pattern asking whether something is allowed (two sides)

Return ONLY JSON: {{"intent": "<one of the above>", "entities": ["key sections/acts/concepts/cases"]}}

Query: {query}"""


def understand(query: str) -> dict:
    try:
        out = parse_json(chat(_PROMPT.format(query=query), json_mode=True,
                              max_tokens=600, temperature=0))
        intent = str(out.get("intent", "")).upper().strip()
        if intent not in INTENTS:
            intent = "DEFAULT"
        return {"intent": intent, "entities": out.get("entities", [])}
    except Exception:  # noqa: BLE001 — never block retrieval on classification
        return {"intent": "DEFAULT", "entities": []}


if __name__ == "__main__":
    import json
    q = " ".join(sys.argv[1:]) or "What does Order 9 Rule 13 CPC allow?"
    print(json.dumps(understand(q), indent=2))
