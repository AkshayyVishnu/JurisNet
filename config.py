"""
Central configuration for JurisNet.

Single source of truth for paths, model names, embedding dims, store URLs, and
the rotating LLM key pools. Import from here rather than reading os.environ or
hard-coding constants across the pipeline.

    from config import VOYAGE_API_KEY, EMBED_DIM, QDRANT_URL, GROQ_POOL
"""

from __future__ import annotations

import os
from pathlib import Path

# transformers (pulled in transitively by voyageai/sentence-transformers) tries to
# load a TensorFlow backend if TF is installed, which conflicts with Keras 3.
# We only ever use the PyTorch path — disable the TF/Flax backends before any
# transformers import happens.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv not installed yet — env may still be set
    pass

# Re-export the rotating key pools so callers have one import surface.
from llm_keys import GROQ_POOL, GEMINI_POOL, call_with_rotation  # noqa: E402,F401

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
CORPUS_DIR = ROOT / "LEGAL_DATA"
JUDGMENTS_DIR = CORPUS_DIR / "judgments"
PROVISIONS_DIR = CORPUS_DIR / "provisions"

CHUNKS_DIR = ROOT / "chunks"
CHUNKS_JUDGMENTS_DIR = CHUNKS_DIR / "judgments"
CHUNKS_PROVISIONS_DIR = CHUNKS_DIR / "provisions"
CITATION_EDGES_FILE = CHUNKS_DIR / "_citation_edges.json"

# Persistent SQLite FTS5 database (legal_fts5 uses :memory: by default).
FTS5_DB_PATH = ROOT / "legal_fts5.db"

# ─────────────────────────────────────────────
# Embeddings
# ─────────────────────────────────────────────
# Both Qdrant collections and all query vectors MUST share this dimension.
# Mismatch silently breaks vector search (see PROJECT_MEMORY known issue).
EMBED_DIM = 1024

VOYAGE_DOC_MODEL = "voyage-4-large"   # API, document indexing (embed_documents_large)
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "").strip()

# Query-time embedding: "large" = Voyage API (no local model, uses quota per query);
# "nano" = local voyage-4-nano (free/fast, needs sentence-transformers + model download).
# Both share the same vector space, so you can switch without re-indexing.
QUERY_EMBED_MODE = os.environ.get("QUERY_EMBED_MODE", "large").strip()
VOYAGE_QUERY_MODEL = "voyage-4-large" if QUERY_EMBED_MODE == "large" else "voyage-4-nano"

# voyage-4-large batch limit ~120K tokens ≈ 100 chunks at ~1000 tokens each.
EMBED_BATCH_SIZE = 100

# ─────────────────────────────────────────────
# Vector store — Qdrant
# ─────────────────────────────────────────────
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333").strip()
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "").strip() or None
QDRANT_CONTENT_COLLECTION = "content"  # judgment/provision body chunks
QDRANT_LABEL_COLLECTION = "label"      # statute labels / headings
QDRANT_DISTANCE = "Cosine"

# ─────────────────────────────────────────────
# Graph store — Neo4j
# ─────────────────────────────────────────────
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687").strip()
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j").strip()
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password").strip()

# ─────────────────────────────────────────────
# Agent LLMs (routed through LiteLLM; keys rotated via the pools above)
# ─────────────────────────────────────────────
GROQ_MODEL = "llama-3.1-8b-instant"        # Query Understanding + Citation Verifier
GEMINI_MODEL = "gemini-2.5-flash"          # Synthesis

# Cooldown (seconds) a key sits out after a 429 before the rotator reuses it.
KEY_COOLDOWN_SECONDS = 60.0

# ─────────────────────────────────────────────
# Sanity check
# ─────────────────────────────────────────────
def validate(require_agent_keys: bool = False) -> None:
    """Fail fast on missing config. Call at the top of pipeline entrypoints."""
    problems = []
    if not VOYAGE_API_KEY:
        problems.append("VOYAGE_API_KEY is empty (required for indexing).")
    if not CORPUS_DIR.exists():
        problems.append(f"Corpus dir not found: {CORPUS_DIR}")
    if require_agent_keys:
        if len(GROQ_POOL) == 0:
            problems.append("No GROQ keys loaded (GROQ_API_KEY, GROQ_API_KEY2, ...).")
        if len(GEMINI_POOL) == 0:
            problems.append("No GOOGLE keys loaded (GOOGLE_API_KEY, GOOGLE_API_KEY2, ...).")
    if problems:
        raise RuntimeError("Config errors:\n  - " + "\n  - ".join(problems))


if __name__ == "__main__":
    print(f"ROOT             : {ROOT}")
    print(f"Corpus exists    : {CORPUS_DIR.exists()}  ({CORPUS_DIR})")
    print(f"EMBED_DIM        : {EMBED_DIM}")
    print(f"Voyage key set   : {bool(VOYAGE_API_KEY)}")
    print(f"Qdrant URL       : {QDRANT_URL}")
    print(f"Neo4j URI        : {NEO4J_URI}")
    print(f"Groq keys        : {len(GROQ_POOL)}")
    print(f"Gemini keys      : {len(GEMINI_POOL)}")
    validate()
    print("validate(): OK")
