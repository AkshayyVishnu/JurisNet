# JurisNet Deck — Screenshots to capture

Real product/graph screenshots to drop into the deck. Capture at high resolution (zoom the
browser to ~110–125%, use a clean window). Prereqs: backend `uvicorn server:app --port 8000`
and frontend `cd frontend && npm run dev` (→ http://localhost:5173) both running with `.env`.

| # | Slide | Capture | How | Proves |
|---|---|---|---|---|
| 1 | 8 | **Neo4j citation graph (wide)** | Neo4j Browser on the Aura instance → run the query below → screenshot the node-link canvas (colorful judgment/statute/rule nodes + edges) | The knowledge graph is real (1,071 nodes / 6,776 edges), not a slide drawing |
| 2 | 8 | **Neo4j ego-graph (focused)** | Run the focused query below on an ex-parte case → screenshot | A single case's citation neighbourhood (precedent/statute structure) |
| 3 | 11 | **Fast mode answer** | UI → toggle **Fast** → ask "What does Order 9 Rule 13 CPC allow?" → wait for stream → screenshot the IRAC answer with clickable `[tid]` chips + the **confidence badge** | Streaming + grounded, verified citations |
| 4 | 9/11 | **Deep mode — stage tracker mid-run** | UI → toggle **Deep analysis** → ask "Can a defendant set aside an ex-parte decree…" → screenshot while the StageTracker shows query_agent→researcher→checklist→auditor | The live agentic pipeline |
| 5 | 9/11 | **Deep mode — clarification prompt** | Same run → when the ❓ ClarifyPrompt appears (question + option buttons) → screenshot | Human-in-the-loop ❓ ("no guessing ahead of evidence") |
| 6 | 9/12 | **Deep mode — adjudication** | Same run → after answering/declining → screenshot the structured Adjudication (verdict + per-issue reasoning + citations) | End-to-end reasoned, cited verdict |
| 7 | 1/12 | **Landing** | UI fresh load → screenshot the suggested-question chips + empty sources rail + header (Fast/Deep toggle) | Polished product entry point |
| 8 | 4/14 | **Architecture panel** | UI → click **Architecture** → screenshot the slide-in panel with live stats (1,071 docs · 30,564 vectors · 6,776 edges) + the 5 agents | Live system stats + pipeline |
| 9 | 12 (opt) | **Terminal ❓-loop** | `python run_pipeline.py "Can a defendant set aside an ex-parte decree if summons not served?"` → screenshot the staged CLI output + a ❓ pause | The pipeline also runs headless |
| 10 | 5/14 (opt) | **Qdrant dashboard** | Qdrant Cloud console → collections view showing `content` (30,564) + `label` (434) | Vector store scale |

## Neo4j Cypher queries (for shots 1 & 2)
Wide graph (judgment → statute/rule edges):
```cypher
MATCH p=(j:Judgment)-[:CITES_STATUTE|CITES_RULE]->(n)
RETURN p LIMIT 75
```
Focused ego-graph around an ex-parte-decree case (use a real judgment tid that cites Order 9 Rule 13,
e.g. one surfaced by the app such as 44063050):
```cypher
MATCH p=(j:Judgment {tid:44063050})-[*1..2]-(m)
RETURN p LIMIT 60
```
Tip: in Neo4j Browser, after running, drag nodes apart for a clean spread and turn on captions
(node labels) before screenshotting.

## Capture tips
- Use the **minimal monochrome** UI as-is — it photographs cleanly on slides.
- For the Fast answer, pick a query that returns 100% confidence (e.g. the Order 9 Rule 13 one) so
  the badge reads well.
- Crop to content; keep generous margins to match the deck's whitespace.
