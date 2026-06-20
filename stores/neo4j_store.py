"""
Neo4j graph store: load judgment/statute nodes + citation edges, and traverse
the citation graph for GraphRAG retrieval.

Nodes: (:Judgment {tid,title,court,date,authority_score,persuasive_only,disposition,citation_status})
       (:Statute  {tid,title,section_ref,act_name})
Edges: (a)-[:CITES {rel_type}]->(b)   rel_type in CITES_STATUTE | CITES_CASE

traverse() returns graph_ranker.GraphNode objects so the ranker can score them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402
from graph_ranker import GraphNode  # noqa: E402


def get_driver():
    return GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"), strict=False)


def load_graph(driver, wipe: bool = False) -> dict:
    """Load all nodes + in-corpus citation edges from the chunk files."""
    jrows, srows = [], []
    for p in sorted(config.CHUNKS_JUDGMENTS_DIR.glob("*.json")):
        l0 = _load(p)["l0"]
        jrows.append({"tid": int(l0["tid"]), "props": {
            "title": l0.get("title", ""), "court": l0.get("court", ""),
            "date": l0.get("date", ""), "authority_score": float(l0.get("authority_score", 0.5)),
            "persuasive_only": bool(l0.get("persuasive_only", False)),
            "disposition": l0.get("disposition", ""), "citation_status": "GOOD_LAW",
        }})
    for p in sorted(config.CHUNKS_PROVISIONS_DIR.glob("*.json")):
        pv = _load(p)["provision"]
        srows.append({"tid": int(pv["tid"]), "props": {
            "title": pv.get("title", ""), "section_ref": pv.get("section_ref", ""),
            "act_name": pv.get("act_name", ""),
        }})

    edges = _load(config.CITATION_EDGES_FILE) if config.CITATION_EDGES_FILE.exists() else []
    erows = [{"from_tid": int(e["from_tid"]), "to_tid": int(e["to_tid"]), "rel_type": e["rel_type"]}
             for e in edges if e.get("to_tid") is not None]

    with driver.session() as s:
        if wipe:
            s.run("MATCH (n) DETACH DELETE n")
        s.run("CREATE INDEX judg_tid IF NOT EXISTS FOR (n:Judgment) ON (n.tid)")
        s.run("CREATE INDEX stat_tid IF NOT EXISTS FOR (n:Statute) ON (n.tid)")

        for i in range(0, len(jrows), 1000):
            s.run("UNWIND $rows AS r MERGE (d:Judgment {tid:r.tid}) SET d += r.props",
                  rows=jrows[i:i + 1000])
        for i in range(0, len(srows), 1000):
            s.run("UNWIND $rows AS r MERGE (n:Statute {tid:r.tid}) SET n += r.props",
                  rows=srows[i:i + 1000])

        loaded_edges = 0
        for i in range(0, len(erows), 5000):
            batch = erows[i:i + 5000]
            res = s.run(
                """
                UNWIND $rows AS r
                MATCH (a {tid:r.from_tid})
                MATCH (b {tid:r.to_tid})
                MERGE (a)-[rel:CITES {rel_type:r.rel_type}]->(b)
                RETURN count(rel) AS c
                """, rows=batch)
            loaded_edges += res.single()["c"]

        n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        m = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

    return {"nodes": n, "relationships": m, "judgments": len(jrows),
            "statutes": len(srows), "edges_loaded": loaded_edges}


def traverse(driver, seed_tids: list[int], max_hops: int = 2) -> list[GraphNode]:
    """Return judgment nodes within max_hops of any seed (undirected, so
    case->statute<-case co-citation is reachable). Excludes the seeds."""
    hops = max(1, min(int(max_hops), 3))
    cypher = f"""
        MATCH (s:Judgment) WHERE s.tid IN $seeds
        MATCH (s)-[r*1..{hops}]-(n:Judgment)
        WHERE NOT n.tid IN $seeds
        WITH n, min(size(r)) AS hop
        RETURN n.tid AS tid, n.title AS title, n.court AS court, n.date AS date,
               coalesce(n.authority_score, 0.5) AS authority_score,
               coalesce(n.persuasive_only, false) AS persuasive_only,
               coalesce(n.citation_status, 'GOOD_LAW') AS citation_status, hop
        LIMIT 200
    """
    with driver.session() as s:
        rows = s.run(cypher, seeds=[int(t) for t in seed_tids]).data()
    return [GraphNode(
        tid=r["tid"], title=r["title"], court=r["court"] or "", date=r["date"] or "",
        authority_score=r["authority_score"], persuasive_only=r["persuasive_only"],
        citation_status=r["citation_status"], hop_distance=r["hop"],
    ) for r in rows]


if __name__ == "__main__":
    drv = get_driver()
    try:
        print("loading graph...")
        print(load_graph(drv, wipe=True))
    finally:
        drv.close()
