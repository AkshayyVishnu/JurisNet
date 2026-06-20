"""
demo_checklist.py
─────────────────
Demo script for the Checklist Resolver.
Shows cache miss (LLM extraction) vs cache hit (instant) behavior.

Requires GOOGLE_API_KEY in .env.
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from agents.checklist_resolver import resolve_checklist

def run_demo():
    load_dotenv()
    if not os.environ.get("GOOGLE_API_KEY") and not os.environ.get("GROQ_API_KEY"):
        print("Error: Neither GOOGLE_API_KEY nor GROQ_API_KEY found in .env")
        print("Please add one to run the demo.")
        return

    # 1. Only clear cache if --fresh flag is passed
    db_path = Path("checklist_cache.db")
    if "--fresh" in sys.argv:
        if db_path.exists():
            db_path.unlink()
            print("Cleared existing cache (deleted checklist_cache.db)\n")

    # 2. Provisions to test (these exist in LEGAL_DATA/provisions/)
    queries = [
        "Section 80 CPC",
        "Section 69 CPC",
        "Section 14A CPC",
    ]

    print("=== First Run: Cache Misses (LLM Calls) ===")
    for q in queries:
        t0 = time.time()
        result = resolve_checklist(q)
        elapsed = time.time() - t0
        
        num_groups = len(result.checklist)
        num_conds = sum(len(g) for g in result.checklist)
        
        print(f"\n[MISS] {q:<35} -> {elapsed:.3f}s (source: {result.source}, "
              f"{num_groups} groups, {num_conds} conditions)")
              
        # Print the actual extracted checklist
        for label, group in zip(result.group_labels, result.checklist):
            print(f"  [{label}]")
            for condition in group:
                flag = "CRITICAL" if condition.critical else "optional"
                alt = f" (alt: {condition.alternative_group})" if condition.alternative_group else ""
                print(f"    [{flag}] {condition.text}{alt}")
        print("-" * 50)

    print("\n=== Second Run: Cache Hits (Instant) ===")
    for q in queries:
        t0 = time.time()
        result = resolve_checklist(q)
        elapsed = time.time() - t0
        print(f"[HIT]  {q:<35} -> {elapsed:.3f}s (source: {result.source})")

    print("\n=== Third Run: Different Phrasing (Cache Hit) ===")
    rephrased = "Code of Civil Procedure Section 80"
    t0 = time.time()
    result = resolve_checklist(rephrased)
    elapsed = time.time() - t0
    print(f"[HIT]  {rephrased:<35} -> {elapsed:.3f}s (source: {result.source}, "
          f"canonical_key: {result.canonical_key})")

    print("\n=== Fourth Run: Provision Not Found ===")
    not_found = "res judicata"
    t0 = time.time()
    result = resolve_checklist(not_found)
    elapsed = time.time() - t0
    print(f"[MISS] {not_found:<35} -> {elapsed:.3f}s (source: {result.source})")


if __name__ == "__main__":
    run_demo()
