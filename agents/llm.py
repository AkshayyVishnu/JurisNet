"""
Shared LLM helper for the agents — one chat() over a provider chain with key
rotation + fallback (Cerebras -> Groq -> Gemini), via LiteLLM.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from llm_keys import CEREBRAS_POOL, GROQ_POOL, GEMINI_POOL, _is_rate_limit  # noqa: E402
import litellm  # noqa: E402

litellm.suppress_debug_info = True
litellm.drop_params = True

# (model, key pool, rate-limit cooldown seconds), tried in order.
_CHAIN = (
    [(config.STAGE_B_CEREBRAS_MODEL, CEREBRAS_POOL, 20),
     (config.STAGE_B_GROQ_MODEL, GROQ_POOL, 15)]
    + [(m, GEMINI_POOL, config.KEY_COOLDOWN_SECONDS) for m in config.STAGE_B_GEMINI_MODELS]
)


def chat(prompt: str, system: str | None = None, json_mode: bool = False,
         max_tokens: int = 3000, temperature: float = 0.2) -> str:
    """Return the model's text. Rotates keys; falls through providers on failure."""
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    last: Exception | None = None
    for model, pool, cooldown in _CHAIN:
        if len(pool) == 0:
            continue
        for _ in range(max(len(pool), 1)):
            key = pool.next()
            try:
                kw = {"response_format": {"type": "json_object"}} if json_mode else {}
                r = litellm.completion(model=model, messages=msgs, api_key=key,
                                       temperature=temperature, max_tokens=max_tokens, **kw)
                content = r.choices[0].message.content
                if content:
                    return content
            except Exception as e:  # noqa: BLE001
                last = e
                if _is_rate_limit(e):
                    pool.penalize(key, cooldown)
                else:
                    break  # provider-level issue -> next provider
    raise last or RuntimeError("all LLM providers failed")


def chat_stream(prompt: str, system: str | None = None,
                max_tokens: int = 2000, temperature: float = 0.2):
    """Yield answer tokens as they arrive. Falls through providers if one fails
    before producing any token; once a provider starts streaming we commit to it."""
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    last: Exception | None = None
    for model, pool, cooldown in _CHAIN:
        if len(pool) == 0:
            continue
        key = pool.next()
        try:
            stream = litellm.completion(model=model, messages=msgs, api_key=key,
                                        temperature=temperature, max_tokens=max_tokens,
                                        stream=True)
            produced = False
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    produced = True
                    yield delta
            if produced:
                return
        except Exception as e:  # noqa: BLE001
            last = e
            if _is_rate_limit(e):
                pool.penalize(key, cooldown)
            continue
    raise last or RuntimeError("all LLM providers failed (stream)")


def parse_json(text: str) -> dict:
    """Tolerant JSON parse: strip code fences / surrounding prose."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1] if i != -1 and j != -1 else t)
