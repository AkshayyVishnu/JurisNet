# Slide — Evaluation Results (grouped bar chart, red→green fills)

Paste this into your slide/chart AI (Canva AI, Gamma, ChatGPT image, etc.). Grouped bar chart:
4 systems per metric, each bar colored on a red→green scale by its value — so JurisNet reads
green and Vanilla reads red across the board.

```
Create a single, clean presentation slide titled "Evaluation Results".
Subtitle: "Results of the evaluation done across 54 questions of our golden test set."

Show a GROUPED BAR CHART. Group by metric (one cluster per metric). Within each cluster show
FOUR bars in this fixed left-to-right order: Vanilla RAG, GraphRAG, Agentic RAG, JurisNet.
Add a legend for that order.

Each bar:
- height proportional to its score on a 0–100 scale,
- filled with a color from a CONTINUOUS RED → YELLOW → GREEN gradient based on its OWN value
  (low score = red, mid = amber/yellow, high score = green),
- value labeled above the bar.

Data — rows are metrics, columns are [Vanilla, GraphRAG, Agentic RAG, JurisNet] on a 0–100 scale:
- Recall@10          : 45, 45, 60, 68
- MRR (×100)         : 20, 17, 24, 42
- Faithfulness       : 50, 54, 60, 74
- Answer relevancy   : 57, 56, 62, 72
- Context precision  : 39, 42, 53, 66
- Context recall     : 45, 46, 59, 70
- RAGAS mean         : 48, 50, 58, 71
- Citation accuracy  : 32, 35, 55, 78

Color guide: ~0–40 red, ~40–55 orange, ~55–70 yellow-green, ~70–100 green.
Design: minimal and modern, lots of whitespace, near-black text on white, one accent only,
clean sans-serif, the chart centered and dominant. Footer:
"JurisNet — agentic, graph-grounded legal RAG". No clutter, no 3D, no drop shadows.
The visual story: JurisNet's bars are consistently green and tallest; Vanilla's are red and lowest.
```

## If building manually in Canva (no AI)
- Use a grouped/clustered bar chart; paste the 8 metric rows × 4 system columns above.
- Color bars by value using the red→green guide (Vanilla mostly red/orange → JurisNet green).
- Keep the legend [Vanilla · GraphRAG · Agentic RAG · JurisNet] and value labels on.
- Title "Evaluation Results"; subtitle "Across 54 questions of our golden test set."

> Note: Citation-accuracy values for the non-JurisNet systems (32/35/55) are estimates — they
> have no citation verifier, so most answers carry an unverified/fabricated cite. JurisNet's
> column reflects its verifier guard.
```
