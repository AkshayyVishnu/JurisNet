"""
llm_factory.py
──────────────
Rotation-aware structured-LLM builder shared by the agents.

Every agent needs a structured LLM (`.invoke(messages) -> pydantic schema`). On the
free tiers we hold many API keys per provider (Groq ×14, Gemini ×30 in .env) so no
single key hits its per-minute / per-day rate limit. This module is the one place
that turns those pools into a drop-in structured LLM:

  • each `.invoke()` draws the next key from the provider's round-robin pool
    (`llm_keys.GROQ_POOL` / `GEMINI_POOL`),
  • a key that returns a 429 is put in cooldown and the next key is tried,
  • Groq's occasional transient tool-call miss (empty/malformed function call) is
    retried on the next key WITHOUT penalizing it,
  • the langchain client is built per attempt, bound to the chosen key.

Provider is chosen from the model string: `gemini*` → Gemini pool, everything else
(Llama, gpt-oss, deepseek, …) → Groq pool. So `$AUDITOR_MODEL` / `$QUERY_AGENT_MODEL`
can switch providers with no code change.

Usage:
    from .llm_factory import build_rotating_structured_llm
    llm = build_rotating_structured_llm(AuditAssessment, "llama-3.3-70b-versatile")
    result = llm.invoke(messages)        # -> AuditAssessment; key rotation handled

Adopting it elsewhere is a one-liner — `query_agent` and `checklist_resolver` can
swap their single-key builders for this without touching their call sites.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from llm_keys import (
    DEFAULT_COOLDOWN,
    GEMINI_POOL,
    GROQ_POOL,
    KeyPool,
    _is_rate_limit,  # shared rate-limit detector (pipeline/* import it the same way)
)


def _route_provider(model: str) -> str:
    """
    Pick the provider (and thus the key pool) from the model id. Gemini models use the
    Gemini pool; everything else — Llama, gpt-oss, deepseek, etc. — goes to Groq.
    """
    return "gemini" if model.lower().startswith("gemini") else "groq"


class RotatingStructuredLLM:
    """
    A structured LLM whose `.invoke(messages)` draws a fresh key from `pool` per
    attempt via `client_factory(key)` (which returns an object exposing `.invoke()`).

    Failure policy per attempt:
      • rate-limit error  → penalize (cool down) that key, rotate to the next.
      • any other error   → rotate to the next key and retry, no penalty (covers
                            Groq's transient empty/malformed tool call).
    After `max_attempts` failures the last error is wrapped and raised.

    The `client_factory` seam keeps this fully testable offline — tests inject a fake
    factory; production injects the langchain client builder (see
    `build_rotating_structured_llm`).
    """

    def __init__(
        self,
        pool: KeyPool,
        client_factory: Callable[[str], Any],
        *,
        max_attempts: Optional[int] = None,
        cooldown: float = DEFAULT_COOLDOWN,
    ):
        self.pool = pool
        self.client_factory = client_factory
        self.max_attempts = max_attempts
        self.cooldown = cooldown

    def invoke(self, messages: Any) -> Any:
        # Default to one shot per key: enough to rotate past every rate-limited key,
        # and enough retries to ride out a transient tool-call miss.
        attempts = self.max_attempts if self.max_attempts is not None else max(len(self.pool), 1)
        last_exc: Optional[Exception] = None
        for _ in range(attempts):
            key = self.pool.next()
            try:
                return self.client_factory(key).invoke(messages)
            except Exception as exc:  # noqa: BLE001 — wrapped + re-raised once attempts run out
                last_exc = exc
                if _is_rate_limit(exc):
                    self.pool.penalize(key, self.cooldown)
                # otherwise: transient miss — fall through to the next key and retry
        raise RuntimeError(
            f"All {attempts} attempt(s) on the '{self.pool.name}' key pool failed; "
            f"last error: {type(last_exc).__name__}: {last_exc}"
        ) from last_exc


def build_rotating_structured_llm(
    schema: Any,
    model: str,
    *,
    temperature: float = 0.0,
    max_attempts: Optional[int] = None,
    cooldown: float = DEFAULT_COOLDOWN,
) -> RotatingStructuredLLM:
    """
    Build a rotation-aware structured LLM for `schema`, routed to the provider implied
    by `model` (`gemini*` → Gemini, else Groq). The langchain client is constructed
    lazily inside the per-attempt factory, so no import/network cost is paid until
    `.invoke()` is first called.
    """
    provider = _route_provider(model)
    pool = GEMINI_POOL if provider == "gemini" else GROQ_POOL

    def client_factory(key: str) -> Any:
        if provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(model=model, google_api_key=key, temperature=temperature)
        else:
            from langchain_groq import ChatGroq

            llm = ChatGroq(model=model, groq_api_key=key, temperature=temperature)
        return llm.with_structured_output(schema)

    return RotatingStructuredLLM(pool, client_factory, max_attempts=max_attempts, cooldown=cooldown)
