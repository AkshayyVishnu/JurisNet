"""
Round-robin API-key rotation for free-tier LLM providers.

We hold many keys per provider (Groq ×14, Gemini ×20) and cycle through them so
no single key hits its per-minute / per-day rate limit. On a rate-limit error a
key is put in a short cooldown and the next available key is used.

Usage
-----
    from llm_keys import GROQ_POOL, GEMINI_POOL

    key = GROQ_POOL.next()              # round-robin, skips keys in cooldown
    ...                                 # make the API call with `key`
    GROQ_POOL.penalize(key, 60)         # on a 429, sit this key out for 60s

Or let the helper handle retry + rotation for you:

    from llm_keys import call_with_rotation, GROQ_POOL

    def do_call(api_key):
        client = Groq(api_key=api_key)
        return client.chat.completions.create(...)

    resp = call_with_rotation(GROQ_POOL, do_call)
"""

from __future__ import annotations

import itertools
import os
import threading
import time
from typing import Callable, List, Optional, TypeVar

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv not installed yet — env may still be set
    pass


# How many numbered slots to scan per provider (generous; empties are skipped).
_MAX_SLOTS = 50

# Default cooldown (seconds) applied to a key when penalize() is called w/o a value.
DEFAULT_COOLDOWN = 60.0


def _load_keys(prefix: str) -> List[str]:
    """
    Collect non-empty env vars for a provider, in order.

    Naming convention in .env: the first key is the bare PREFIX (no number),
    then PREFIX2, PREFIX3, ... e.g. GROQ_API_KEY, GROQ_API_KEY2, GROQ_API_KEY3.
    """
    keys = []
    bare = os.environ.get(prefix, "").strip()
    if bare:
        keys.append(bare)
    for i in range(2, _MAX_SLOTS + 1):
        val = os.environ.get(f"{prefix}{i}", "").strip()
        if val:
            keys.append(val)
    return keys


class KeyPool:
    """Thread-safe round-robin pool of API keys with per-key cooldown."""

    def __init__(self, name: str, keys: List[str]):
        self.name = name
        self._keys = list(keys)
        self._lock = threading.Lock()
        self._cursor = itertools.cycle(range(len(self._keys))) if self._keys else None
        # key -> unix timestamp until which the key is unavailable
        self._cooldown_until = {k: 0.0 for k in self._keys}

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def keys(self) -> List[str]:
        return list(self._keys)

    def next(self) -> str:
        """Return the next key not in cooldown. Falls back to the soonest-free key."""
        if not self._keys:
            raise RuntimeError(
                f"No API keys configured for '{self.name}' in .env "
                f"(expected the bare provider key plus numbered variants, e.g. "
                f"GROQ_API_KEY, GROQ_API_KEY2, ...)"
            )
        with self._lock:
            now = time.time()
            # One full pass looking for an available key.
            for _ in range(len(self._keys)):
                idx = next(self._cursor)
                key = self._keys[idx]
                if self._cooldown_until.get(key, 0.0) <= now:
                    return key
            # All keys cooling down — return the one that frees up soonest.
            return min(self._keys, key=lambda k: self._cooldown_until.get(k, 0.0))

    def penalize(self, key: str, seconds: float = DEFAULT_COOLDOWN) -> None:
        """Put `key` in cooldown for `seconds` (call this after a 429)."""
        with self._lock:
            self._cooldown_until[key] = time.time() + seconds

    def available(self) -> int:
        """Count of keys not currently in cooldown."""
        now = time.time()
        return sum(1 for k in self._keys if self._cooldown_until.get(k, 0.0) <= now)


# Module-level singletons — import these.
GROQ_POOL = KeyPool("groq", _load_keys("GROQ_API_KEY"))
GEMINI_POOL = KeyPool("gemini", _load_keys("GOOGLE_API_KEY"))


T = TypeVar("T")


def _is_rate_limit(exc: Exception) -> bool:
    """Best-effort detection of a rate-limit / quota error across SDKs."""
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429:
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(s in text for s in ("rate limit", "429", "quota", "resource_exhausted", "too many requests"))


def call_with_rotation(
    pool: KeyPool,
    fn: Callable[[str], T],
    *,
    max_attempts: Optional[int] = None,
    cooldown: float = DEFAULT_COOLDOWN,
) -> T:
    """
    Call `fn(api_key)`, rotating to the next key on a rate-limit error.

    Penalizes the offending key and retries with the next available one.
    Re-raises non-rate-limit errors immediately. Defaults to one attempt per key.
    """
    attempts = max_attempts if max_attempts is not None else max(len(pool), 1)
    last_exc: Optional[Exception] = None
    for _ in range(attempts):
        key = pool.next()
        try:
            return fn(key)
        except Exception as exc:  # noqa: BLE001 — we re-raise non-rate-limit below
            if not _is_rate_limit(exc):
                raise
            pool.penalize(key, cooldown)
            last_exc = exc
    raise RuntimeError(
        f"All {pool.name} keys exhausted after {attempts} attempts"
    ) from last_exc


if __name__ == "__main__":
    print(f"Groq keys loaded:   {len(GROQ_POOL)}  (available now: {GROQ_POOL.available()})")
    print(f"Gemini keys loaded: {len(GEMINI_POOL)}  (available now: {GEMINI_POOL.available()})")
    # Show round-robin order on the first few picks (masked).
    if len(GROQ_POOL):
        picks = [GROQ_POOL.next()[-4:] for _ in range(min(4, len(GROQ_POOL) + 1))]
        print("Groq round-robin (last 4 chars):", picks)
