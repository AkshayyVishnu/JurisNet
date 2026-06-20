"""
test_llm_factory.py — offline regression suite for the rotation-aware structured-LLM
factory (agents/llm_factory.py).

The factory is what lets every agent ride the pool of API keys in .env (Groq ×14,
Gemini ×30) instead of a single key: it rotates keys round-robin, sits a key out on
a 429, retries Groq's occasional transient tool-call miss on the next key, and routes
to the right provider/pool off the model string.

All tests are OFFLINE — they drive a real `KeyPool` with fake keys and a fake
client_factory, so no API key and no network are needed. The langchain client is only
ever built inside the (production) client_factory, which these tests replace.

Run:
    uv run python -m tests.test_llm_factory
"""

from __future__ import annotations

import time

from llm_keys import KeyPool
from agents.llm_factory import (
    RotatingStructuredLLM,
    _route_provider,
    build_rotating_structured_llm,
)

PASS, FAIL = 0, 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


# ─────────────────────────────────────────────
# Fakes: a client is anything with .invoke(messages). The factory builds one per
# attempt via client_factory(key); we substitute fakes that succeed or raise.
# ─────────────────────────────────────────────

class _FakeRateLimit(Exception):
    """Looks like a provider 429 to llm_keys._is_rate_limit (status_code attr)."""
    status_code = 429


class _OkClient:
    def __init__(self, key):
        self.key = key

    def invoke(self, _messages):
        return ("ok", self.key)


class _RaisingClient:
    def __init__(self, exc):
        self.exc = exc

    def invoke(self, _messages):
        raise self.exc


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

def tests() -> None:
    print("\n=== OFFLINE (no API key) ===\n")

    # ---- provider routing by model string ----
    check("route: gemini-2.5-flash -> gemini", _route_provider("gemini-2.5-flash") == "gemini")
    check("route: gemini-2.0-flash -> gemini", _route_provider("gemini-2.0-flash") == "gemini")
    check("route: llama-3.3-70b -> groq", _route_provider("llama-3.3-70b-versatile") == "groq")
    check("route: openai/gpt-oss-20b -> groq", _route_provider("openai/gpt-oss-20b") == "groq")
    check("route: deepseek-r1-distill -> groq",
          _route_provider("deepseek-r1-distill-llama-70b") == "groq")

    # ---- happy path: successive invokes round-robin across keys ----
    pool = KeyPool("t", ["k1", "k2", "k3"])
    llm = RotatingStructuredLLM(pool, lambda key: _OkClient(key))
    r1, r2, r3, r4 = (llm.invoke("m") for _ in range(4))
    check("round-robin: 4 invokes cycle k1,k2,k3,k1",
          [r1, r2, r3, r4] == [("ok", "k1"), ("ok", "k2"), ("ok", "k3"), ("ok", "k1")],
          detail=f"{[r1, r2, r3, r4]}")

    # ---- 429 on a key -> penalize that key + rotate to the next, within one invoke ----
    pool = KeyPool("t", ["bad", "good"])

    def factory_429(key):
        return _RaisingClient(_FakeRateLimit("rate limit exceeded")) if key == "bad" else _OkClient(key)

    llm = RotatingStructuredLLM(pool, factory_429)
    r = llm.invoke("m")
    check("rate-limit: rotates past the 429'd key to a good one", r == ("ok", "good"), detail=f"{r}")
    check("rate-limit: the 429'd key is put in cooldown (1 of 2 available)",
          pool.available() == 1, detail=f"available={pool.available()}")

    # ---- transient (non-429) tool-call miss -> retry on next key, NO penalty ----
    pool = KeyPool("t", ["k1", "k2"])
    calls = {"n": 0}

    def factory_transient(key):
        calls["n"] += 1
        if calls["n"] == 1:
            return _RaisingClient(ValueError("tool_use_failed: no tool call generated"))
        return _OkClient(key)

    llm = RotatingStructuredLLM(pool, factory_transient)
    r = llm.invoke("m")
    check("transient: retries the miss and succeeds", r[0] == "ok", detail=f"{r}")
    check("transient: NO key penalized (both still available)",
          pool.available() == 2, detail=f"available={pool.available()}")

    # ---- all keys rate-limited -> RuntimeError after exhausting attempts ----
    pool = KeyPool("t", ["k1", "k2"])
    llm = RotatingStructuredLLM(pool, lambda key: _RaisingClient(_FakeRateLimit("429")))
    raised = False
    try:
        llm.invoke("m")
    except RuntimeError:
        raised = True
    check("exhaustion: raises RuntimeError when every key is rate-limited", raised)
    check("exhaustion: every key ends up in cooldown", pool.available() == 0,
          detail=f"available={pool.available()}")

    # ---- a non-rate-limit, non-transient error still surfaces (after retries) ----
    pool = KeyPool("t", ["k1", "k2"])
    llm = RotatingStructuredLLM(pool, lambda key: _RaisingClient(ValueError("boom")))
    raised = False
    try:
        llm.invoke("m")
    except Exception:
        raised = True
    check("hard error: surfaces instead of hanging", raised)

    # ---- build_rotating_structured_llm wires the right pool by model, lazily ----
    # (No network: the real client_factory is only invoked on .invoke(), not here.)
    from llm_keys import GROQ_POOL, GEMINI_POOL

    groq_llm = build_rotating_structured_llm(dict, "llama-3.3-70b-versatile")
    check("build: groq model -> GROQ_POOL", groq_llm.pool is GROQ_POOL)
    gem_llm = build_rotating_structured_llm(dict, "gemini-2.5-flash")
    check("build: gemini model -> GEMINI_POOL", gem_llm.pool is GEMINI_POOL)


if __name__ == "__main__":
    import sys

    tests()
    print(f"\n-------- {PASS} passed, {FAIL} failed --------")
    sys.exit(1 if FAIL else 0)
