"""
Stage B — LLM enrichment (Gemini 2.5 Flash, 1 call per judgment).

Adds to each judgment chunk file (built by Stage A):
  - L0.text  := LLM headnote summary (+ existing cites tail)  [replaces metadata-only]
  - L1_facts := facts summary chunk (factual-similarity retrieval)
  - ratio    := binding rule chunk
  - L3 atomic := verbatim sentence-split of the holding paragraphs (TIGHT scope)
  - L0.disposition := outcome tag

The single LLM call returns 5 fields: summary, facts_summary, ratio,
holding_para_ids, disposition. L3 is then derived deterministically (no LLM)
from the verbatim text of holding_para_ids.

Resumable: skips files already marked stage_b_done. See PIPELINE_STAGES.md (Stage B).

Run:
  python pipeline/02_enrich.py --limit 2 --dry     # test on 2 cases, print, no write
  python pipeline/02_enrich.py                      # full batch (resumable)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from llm_keys import CEREBRAS_POOL, GEMINI_POOL, GROQ_POOL, _is_rate_limit  # noqa: E402
from chunker import (  # noqa: E402
    L1SectionChunk,
    L3AtomicChunk,
    RatioChunk,
    _breadcrumb,
    split_into_propositions,
)

import litellm  # noqa: E402  — unified gateway (avoids the google-genai SDK bug)

litellm.suppress_debug_info = True
litellm.drop_params = True  # silently drop unsupported params per provider

# UTF-8 + line-buffered so progress shows in redirected logs (and no cp1252 crash).
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:  # noqa: BLE001
    pass

VALID_DISPOSITIONS = {"ALLOWED", "DISMISSED", "PARTLY_ALLOWED", "REMANDED", "DISPOSED"}

PROMPT = """You are an expert Indian legal analyst. You are given a court judgment as a list of numbered paragraphs (each tagged with its paragraph id in square brackets).

Return ONLY a JSON object with these exact keys:
{{
  "summary": "2-3 sentence neutral headnote: what the dispute was about and what the court decided",
  "facts_summary": "2-3 sentence summary of the material FACTS only (the factual background, parties, what happened) - no legal reasoning",
  "ratio": "the binding rule of law (ratio decidendi) the case establishes, stated as a general legal principle. If none is articulated, return an empty string.",
  "holding_para_ids": ["the paragraph ids (exactly as shown in brackets) that contain the court's holding/decision and the reasoning that directly supports it - usually a small number near the end"],
  "disposition": "one of: ALLOWED, DISMISSED, PARTLY_ALLOWED, REMANDED, DISPOSED"
}}

Rules:
- holding_para_ids MUST be a subset of the paragraph ids actually shown below. Keep it TIGHT (only the genuine holding paragraphs).
- Do not invent facts. Base everything strictly on the text.

JUDGMENT PARAGRAPHS:
{paras}
"""


# Stage B routing (all calls via LiteLLM):
#   - Groq 70B is primary (high daily quota, per-minute limits recover fast).
#   - Gemini (flash-lite first) handles prompts too big for Groq's token/min cap.
# Rate limits are retried in place across the key pool; only a NON-rate-limit Groq
# error (e.g. context length) escalates to Gemini.


def _parse_json(text: str) -> dict:
    """Tolerant JSON parse: strip code fences / surrounding prose."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1] if i != -1 and j != -1 else t)


def _complete(model: str, key: str, prompt: str) -> dict:
    r = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        api_key=key,
        temperature=0.1,
        response_format={"type": "json_object"},
        max_tokens=2500,  # truncated reasoning budget for gpt-oss + JSON output (faster)
    )
    content = r.choices[0].message.content
    if not content:
        raise ValueError("empty completion content")  # triggers retry
    return _parse_json(content)


def _groq_json(prompt: str) -> dict:
    """Groq JSON via LiteLLM; retries rate limits across keys, raises other errors."""
    last_exc: Exception | None = None
    delay = 8.0
    for _ in range(5):  # rounds over the whole key pool
        for _ in range(max(len(GROQ_POOL), 1)):
            key = GROQ_POOL.next()
            try:
                return _complete(config.STAGE_B_GROQ_MODEL, key, prompt)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if _is_rate_limit(exc):
                    GROQ_POOL.penalize(key, 15)  # per-minute limit; short cooldown
                else:
                    raise  # context-length / other -> let caller try Gemini
        time.sleep(delay + random.uniform(0, delay * 0.3))
        delay = min(delay * 2, 60)
    raise last_exc or RuntimeError("groq call failed after retries")


def _gemini_json(prompt: str) -> dict:
    """Gemini JSON via LiteLLM, rotating across (model x key); each model is a
    separate daily free bucket."""
    last_exc: Exception | None = None
    for model in config.STAGE_B_GEMINI_MODELS:
        for _ in range(max(len(GEMINI_POOL), 1)):
            key = GEMINI_POOL.next()
            try:
                return _complete(model, key, prompt)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if _is_rate_limit(exc):
                    GEMINI_POOL.penalize(key, config.KEY_COOLDOWN_SECONDS)
                # else: try next key/model
    raise last_exc or RuntimeError("gemini fallback failed")


def _cerebras_json(prompt: str) -> dict:
    """Cerebras JSON via LiteLLM; retries rate limits across keys, raises other errors."""
    last_exc: Exception | None = None
    delay = 8.0
    for _ in range(5):
        for _ in range(max(len(CEREBRAS_POOL), 1)):
            key = CEREBRAS_POOL.next()
            try:
                return _complete(config.STAGE_B_CEREBRAS_MODEL, key, prompt)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if _is_rate_limit(exc):
                    CEREBRAS_POOL.penalize(key, 20)
                else:
                    raise  # context-length / other -> let caller try Groq/Gemini
        time.sleep(delay + random.uniform(0, delay * 0.3))
        delay = min(delay * 2, 60)
    raise last_exc or RuntimeError("cerebras call failed after retries")


def _call_llm(prompt: str) -> dict:
    """Provider chain: Cerebras (if keys) -> Groq 70B -> Gemini. Each handles its own
    rate limits; a provider's hard failure falls through to the next."""
    if len(CEREBRAS_POOL):
        try:
            return _cerebras_json(prompt)
        except Exception:  # noqa: BLE001 — fall through
            pass
    if len(prompt) <= config.GROQ_MAX_PROMPT_CHARS:
        try:
            return _groq_json(prompt)
        except Exception:  # noqa: BLE001 — fall through to Gemini
            pass
    return _gemini_json(prompt)


# Cap the prompt so no single request blows Groq's per-minute token budget.
# For long judgments keep the head (facts/context) + tail (reasoning/holding/order)
# and drop the bulky middle; holding_para_ids still map to full text for L3.
_LISTING_CAP = 40000  # chars (~10K tokens)


def _build_listing(paras: list[dict]) -> str:
    items = [(c["para_id"], c.get("raw", "")) for c in paras]
    full = "\n".join(f"[{pid}] {txt}" for pid, txt in items)
    if len(full) <= _LISTING_CAP:
        return full

    head_budget = int(_LISTING_CAP * 0.4)
    tail_budget = _LISTING_CAP - head_budget
    head, used = [], 0
    for it in items:
        s = len(f"[{it[0]}] {it[1]}\n")
        if used + s > head_budget:
            break
        head.append(it); used += s
    tail, used = [], 0
    for it in reversed(items):
        s = len(f"[{it[0]}] {it[1]}\n")
        if used + s > tail_budget:
            break
        tail.append(it); used += s
    tail.reverse()
    head_ids = {i[0] for i in head}
    tail = [t for t in tail if t[0] not in head_ids]
    chosen = head + [("...", "[... middle paragraphs omitted for length ...]")] + tail
    return "\n".join(f"[{pid}] {txt}" for pid, txt in chosen)


def enrich_chunk(chunk: dict) -> dict:
    l0 = chunk["l0"]
    tid, title, court = l0["tid"], l0["title"], l0["court"]
    paras = chunk["l2_paragraphs"]
    para_ids = {c["para_id"] for c in paras}
    raw_by_id = {c["para_id"]: c.get("raw", "") for c in paras}

    listing = _build_listing(paras)
    out = _call_llm(PROMPT.format(paras=listing))

    summary = (out.get("summary") or "").strip()
    facts = (out.get("facts_summary") or "").strip()
    ratio = (out.get("ratio") or "").strip()
    disposition = (out.get("disposition") or "").strip().upper()
    holding_ids = [str(p) for p in out.get("holding_para_ids", []) if str(p) in para_ids]

    # ── L0: replace metadata text with headnote, keep the "Cites:" tail ──
    old = l0.get("text", "")
    cites_tail = ""
    if ". Cites:" in old:
        cites_tail = " Cites:" + old.split(". Cites:", 1)[1]
    if summary:
        l0["text"] = (summary + cites_tail).strip()
    l0["disposition"] = disposition if disposition in VALID_DISPOSITIONS else "DISPOSED"

    # ── L1 facts chunk ──
    chunk["l1_sections"] = []
    if facts:
        bc = _breadcrumb(title, court, "FACTS")
        chunk["l1_sections"].append(asdict(L1SectionChunk(
            tid=tid, title=title, section_type="FACTS", para_ids=[],
            text=f"{bc}\n\n{facts}",
        )))

    # ── ratio chunk ──
    chunk["ratio_chunks"] = []
    if ratio:
        bc = _breadcrumb(title, court, "RATIO")
        chunk["ratio_chunks"].append(asdict(RatioChunk(
            tid=tid, title=title, authority_score=l0.get("authority_score", 0.7),
            text=f"{bc}\n\n{ratio}",
        )))

    # ── L3 atomic: verbatim sentence-split of holding paragraphs (tight) ──
    l3 = []
    for pid in holding_ids:
        for si, sent in enumerate(split_into_propositions(raw_by_id.get(pid, ""), min_words=10)):
            bc = _breadcrumb(title, court, "ATOMIC", pid)
            l3.append(asdict(L3AtomicChunk(
                tid=tid, title=title, para_id=pid, section_type="HELD",
                sentence_index=si, text=f"{bc}\n\n{sent}",
            )))
    chunk["l3_atomic"] = l3
    chunk["holding_para_ids"] = holding_ids
    chunk["stage_b_done"] = True
    return chunk


def run(limit: int | None, dry: bool, workers: int) -> None:
    config.validate(require_agent_keys=True)
    files = sorted(config.CHUNKS_JUDGMENTS_DIR.glob("*.json"))
    todo = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"), strict=False)
        if not d.get("stage_b_done"):
            todo.append((f, d))
    if limit:
        todo = todo[:limit]

    print(f"Stage B: {len(todo)} judgments to enrich "
          f"({GEMINI_POOL.available()} Gemini keys, {workers} workers)"
          f"{' [DRY RUN]' if dry else ''}")
    t0 = time.time()

    # Dry run stays sequential for readable previews.
    if dry:
        ok = fail = 0
        for f, d in todo:
            try:
                _preview(f.name, enrich_chunk(d))
                ok += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                print(f"  ! {f.name}: {type(e).__name__}: {e}")
        print(f"\nDone: {ok} enriched, {fail} failed, {time.time()-t0:.1f}s")
        return

    def process(item):
        """Enrich + write one doc. Returns (item, error_or_None) so failures re-queue."""
        f, d = item
        try:
            d = enrich_chunk(d)
            f.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
            return item, None
        except Exception as e:  # noqa: BLE001 — re-queued for a later round
            return item, e

    # Multi-round retry: anything that fails a round is re-queued and retried after a
    # degrading wait, until all succeed or we run out of rounds. This guarantees every
    # chunk gets a fair shot at the LLM even through rate-limit storms.
    pending = todo
    total = len(todo)
    enriched = 0
    last_errs: dict[str, str] = {}
    MAX_ROUNDS = 6

    for rnd in range(1, MAX_ROUNDS + 1):
        if not pending:
            break
        failed = []
        done_this_round = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(process, item) for item in pending]
            for fut in as_completed(futures):
                item, err = fut.result()
                if err:
                    failed.append(item)
                    last_errs[item[0].name] = f"{type(err).__name__}: {err}"
                else:
                    enriched += 1
                    done_this_round += 1
                    last_errs.pop(item[0].name, None)
                if (done_this_round + len(failed)) % 25 == 0:
                    rate = enriched / (time.time() - t0) if enriched else 0
                    eta = (total - enriched) / rate / 60 if rate else 0
                    print(f"  round {rnd}: {enriched}/{total} done "
                          f"({rate:.1f}/s, ~{eta:.1f} min left)")
        pending = failed
        if pending:
            backoff = min(30 * rnd, 180)  # degrading wait between rounds
            print(f"  round {rnd} end: {len(pending)} still failing -> "
                  f"backing off {backoff}s before round {rnd+1}")
            time.sleep(backoff)

    # Persist any permanent failures so they can be inspected / re-run.
    fail_file = config.CHUNKS_DIR / "_stage_b_failures.json"
    if pending:
        payload = [{"file": f.name, "error": last_errs.get(f.name, "")} for f, _ in pending]
        fail_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\n⚠ {len(pending)} docs still failed after {MAX_ROUNDS} rounds -> {fail_file}")
        print("   (they remain stage_b_done=False; just re-run the script to retry them)")
    elif fail_file.exists():
        fail_file.unlink()  # clean slate when everything succeeds

    print(f"\nDone: {enriched}/{total} enriched, {len(pending)} failed, {time.time()-t0:.1f}s")


def _preview(name: str, d: dict) -> None:
    l0 = d["l0"]
    print("\n" + "=" * 72)
    print(f"{name}  |  {l0['title'][:60]}")
    print("-" * 72)
    print("DISPOSITION:", l0.get("disposition"))
    print("\nL0 HEADNOTE:\n ", l0["text"])
    if d["l1_sections"]:
        print("\nL1 FACTS:\n ", d["l1_sections"][0]["text"].split("\n\n", 1)[-1])
    if d["ratio_chunks"]:
        print("\nRATIO:\n ", d["ratio_chunks"][0]["text"].split("\n\n", 1)[-1])
    print(f"\nHOLDING PARA IDS: {d.get('holding_para_ids')}")
    print(f"L3 ATOMIC: {len(d['l3_atomic'])} sentences")
    for c in d["l3_atomic"][:3]:
        print("   -", c["text"].split("\n\n", 1)[-1][:120])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="process at most N judgments")
    ap.add_argument("--dry", action="store_true", help="print results, do not write")
    ap.add_argument("--workers", type=int, default=5, help="concurrent workers (default 5)")
    args = ap.parse_args()
    run(args.limit, args.dry, args.workers)
