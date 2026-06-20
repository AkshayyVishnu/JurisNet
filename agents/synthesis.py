"""
Synthesis — write a grounded answer from retrieved chunks only, with inline [tid]
citations. No outside knowledge; IRAC structure; flags insufficient context.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.llm import chat  # noqa: E402

_SYSTEM = """You are JurisNet, an Indian CIVIL-law research assistant. Answer using ONLY the \
provided context excerpts — no outside knowledge, no invented cases or sections.

Rules:
- Cite EVERY legal claim with the source tag in square brackets, e.g. [tid 12345].
- Structure the answer as IRAC: **Issue**, **Rule** (with citations), **Application**, **Conclusion**.
- If the context does not contain enough to answer, say so plainly instead of guessing.
- Do not cite any tid that is not in the context.
- End with: "_This is general legal information, not legal advice._"
"""


def _format_context(results: list[dict], max_chunks: int, per_chunk_chars: int) -> str:
    blocks = []
    for r in results[:max_chunks]:
        tag = f"[tid {r['tid']}]"
        meta = " ".join(x for x in [r.get("title", ""), f"({r.get('chunk_type','')})"] if x)
        flag = "  ⚠ caution: possibly overruled/doubted" if r.get("caution_flag") else ""
        blocks.append(f"{tag} {meta}{flag}\n{(r.get('text','') or '')[:per_chunk_chars]}")
    return "\n\n---\n\n".join(blocks)


def synthesize(query: str, results: list[dict], max_chunks: int = 12,
               per_chunk_chars: int = 1200) -> str:
    if not results:
        return ("I couldn't find relevant material in the corpus for this question.\n\n"
                "_This is general legal information, not legal advice._")
    context = _format_context(results, max_chunks, per_chunk_chars)
    prompt = (f"CONTEXT EXCERPTS:\n{context}\n\n"
              f"QUESTION: {query}\n\n"
              "Write the IRAC answer now, citing [tid …] for every legal claim.")
    return chat(prompt, system=_SYSTEM, max_tokens=2000, temperature=0.2)
