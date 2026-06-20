"""
test_checklist_resolver.py
──────────────────────────
Offline tests for the Checklist Resolver module.

Same pattern as test_query_agent.py: injectable fake LLM, no API key
needed, deterministic. Tests cover key canonicalization, cache hit/miss,
provision lookup, and result schema.
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.checklist_resolver import (
    _cache_get,
    _cache_put,
    _canonicalize,
    _init_cache,
    _lookup_provision,
    resolve_checklist,
)
from agents.schemas import (
    ChecklistCondition,
    ChecklistExtraction,
    ChecklistGroup,
    ChecklistResult,
)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _make_fake_llm(groups: list[dict] | None = None):
    """
    Build a fake LLM that returns a ChecklistExtraction when .invoke() is called.
    """
    if groups is None:
        groups = [
            {
                "group_label": "General conditions",
                "conditions": [
                    {"text": "Condition A", "critical": True},
                    {"text": "Condition B", "critical": False},
                ],
            },
            {
                "group_label": "Proviso",
                "conditions": [
                    {"text": "Proviso condition 1", "critical": False},
                ],
            },
        ]
    extraction = ChecklistExtraction(
        provision_name="Test Provision",
        groups=[ChecklistGroup(**g) for g in groups],
    )
    llm = MagicMock()
    llm.invoke.return_value = extraction
    return llm


def _make_temp_db() -> str:
    """Return a path to a temp SQLite file that will be auto-cleaned."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _make_provision_dir(provisions: list[dict]) -> str:
    """Create a temp dir with provision JSON files."""
    d = tempfile.mkdtemp()
    for prov in provisions:
        fpath = os.path.join(d, f"{prov['doc_id']}.json")
        with open(fpath, "w") as f:
            json.dump(prov, f)
    return d


def _make_orders_dir(orders: list[dict]) -> str:
    """Create a temp dir mirroring Orders_Rules/ schema ({doc_id, identifier, text})."""
    d = tempfile.mkdtemp()
    for o in orders:
        fpath = os.path.join(d, f"{o['doc_id']}.json")
        with open(fpath, "w") as f:
            json.dump(o, f)
    return d


# Mirrors the real Orders_Rules/ schema: identifier/text (NOT title/body), and the
# rule text does NOT mention "Code of Civil Procedure" anywhere — so act-verification
# must be skipped for the orders source.
ORDER_RULE_PROVISION = {
    "doc_id": 90001,
    "identifier": "Order 39 Rule 1",
    "text": (
        "1. Cases in which temporary injunction may be granted. - Where in any suit it "
        "is proved by affidavit or otherwise- (a) that any property in dispute in a suit "
        "is in danger of being wasted, damaged or alienated by any party to the suit, or "
        "wrongfully sold in execution of a decree, or (b) that the defendant threatens to "
        "remove or dispose of his property with a view to defrauding his creditors, the "
        "Court may by order grant a temporary injunction to restrain such act."
    ),
    "cited_by": [],
}


SAMPLE_PROVISION = {
    "doc_id": 55198661,
    "title": "Section 80",
    "body": (
        "Section 80 in The Code of Civil Procedure, 1908 80. Notice .- (1) "
        "Save as otherwise provided in sub-section (2), no suit shall be "
        "instituted against the Government or against a public officer in "
        "respect of any act purporting to be done by such public officer in "
        "his official capacity, until the expiration of two months next after "
        "notice in writing has been delivered to, or left at the office of..."
    ),
    "cases_citedby": [176234487],
}


# ─────────────────────────────────────────────
# Canonicalization tests
# ─────────────────────────────────────────────

class TestCanonicalize:
    """Test _canonicalize handles reordering, abbreviations, and fallbacks."""

    def test_section_act_forward(self):
        assert _canonicalize("Section 23 Indian Contract Act") == "section_23__indian_contract_act"

    def test_section_act_reversed(self):
        """Key decision: 'Indian Contract Act Section 23' must produce the SAME key."""
        assert _canonicalize("Indian Contract Act Section 23") == "section_23__indian_contract_act"

    def test_abbreviation_cpc(self):
        result = _canonicalize("S. 80 CPC")
        assert result == "section_80__code_of_civil_procedure"

    def test_full_name_cpc(self):
        result = _canonicalize("Section 80 Code of Civil Procedure")
        assert result == "section_80__code_of_civil_procedure"

    def test_same_key_for_abbreviation_and_full(self):
        a = _canonicalize("S. 80 CPC")
        b = _canonicalize("Section 80 Code of Civil Procedure")
        assert a == b

    def test_order_rule(self):
        result = _canonicalize("Order 39 Rule 1 CPC")
        assert result == "order_39_rule_1__code_of_civil_procedure"

    def test_article(self):
        result = _canonicalize("Article 21 Constitution of India")
        assert result == "article_21__constitution_of_india"

    def test_doctrine_fallback(self):
        """Case-law doctrines with no section number fall back to underscore form."""
        result = _canonicalize("res judicata")
        assert result == "res_judicata"

    def test_empty_string(self):
        assert _canonicalize("") == ""

    def test_none_string(self):
        assert _canonicalize(None) == ""

    def test_whitespace_only(self):
        assert _canonicalize("   ") == ""


# ─────────────────────────────────────────────
# Cache layer tests
# ─────────────────────────────────────────────

class TestCache:
    def test_miss_returns_none(self):
        db_path = _make_temp_db()
        try:
            conn = _init_cache(db_path)
            assert _cache_get(conn, "section_80__cpc") is None
            conn.close()
        finally:
            os.unlink(db_path)

    def test_put_then_get(self):
        db_path = _make_temp_db()
        try:
            conn = _init_cache(db_path)
            result = ChecklistResult(
                provision_key="Section 80 CPC",
                canonical_key="section_80__code_of_civil_procedure",
                checklist=[
                    [
                        ChecklistCondition(text="Condition A", critical=True),
                        ChecklistCondition(text="Condition B", critical=False),
                    ],
                    [ChecklistCondition(text="Proviso 1", critical=False)],
                ],
                group_labels=["General", "Proviso"],
                source="llm",
                provision_text_snippet="Section 80 in The Code...",
            )
            _cache_put(conn, result)
            cached = _cache_get(conn, "section_80__code_of_civil_procedure")
            assert cached is not None
            assert cached.source == "cache"
            assert cached.checklist[0][0].text == "Condition A"
            assert cached.checklist[0][0].critical is True
            assert cached.checklist[0][1].critical is False
            assert cached.group_labels == ["General", "Proviso"]
            conn.close()
        finally:
            os.unlink(db_path)


# ─────────────────────────────────────────────
# Provision lookup tests
# ─────────────────────────────────────────────

class TestLookupProvision:
    def test_finds_matching_provision(self):
        data_dir = _make_provision_dir([SAMPLE_PROVISION])
        result = _lookup_provision("Section 80 CPC", data_dir)
        assert result is not None
        body, doc_id = result
        assert doc_id == 55198661
        assert "Notice" in body

    def test_no_match_returns_none(self):
        data_dir = _make_provision_dir([SAMPLE_PROVISION])
        result = _lookup_provision("Section 999 CPC", data_dir)
        assert result is None

    def test_wrong_act_returns_none(self):
        data_dir = _make_provision_dir([SAMPLE_PROVISION])
        # Section 80 exists, but in CPC not IPC
        result = _lookup_provision("Section 80 IPC", data_dir)
        assert result is None


# ─────────────────────────────────────────────
# resolve_checklist integration tests
# ─────────────────────────────────────────────

class TestResolveChecklist:
    def test_empty_key_shortcircuits(self):
        result = resolve_checklist(None)
        assert result.source == "not_found"
        assert result.checklist == []

    def test_empty_string_shortcircuits(self):
        result = resolve_checklist("")
        assert result.source == "not_found"

    def test_informational_query_shortcircuits(self):
        result = resolve_checklist("Section 80 CPC", query_type="informational")
        assert result.source == "skipped_informational"
        assert result.checklist == []

    def test_cache_miss_calls_llm(self):
        db_path = _make_temp_db()
        data_dir = _make_provision_dir([SAMPLE_PROVISION])
        fake_llm = _make_fake_llm()
        try:
            result = resolve_checklist(
                "Section 80 CPC", llm=fake_llm, db_path=db_path, data_dir=data_dir
            )
            assert result.source == "llm"
            assert fake_llm.invoke.call_count == 1
            assert len(result.checklist) == 2  # 2 groups
            assert result.checklist[0][0].text == "Condition A"
            assert result.checklist[0][0].critical is True
            assert result.checklist[0][1].text == "Condition B"
            assert result.checklist[0][1].critical is False
            assert result.group_labels[0] == "General conditions"
        finally:
            os.unlink(db_path)

    def test_cache_hit_skips_llm(self):
        db_path = _make_temp_db()
        data_dir = _make_provision_dir([SAMPLE_PROVISION])
        fake_llm = _make_fake_llm()
        try:
            # First call: miss
            resolve_checklist("Section 80 CPC", llm=fake_llm, db_path=db_path, data_dir=data_dir)
            assert fake_llm.invoke.call_count == 1

            # Second call: should be a hit, no LLM call
            result2 = resolve_checklist(
                "Section 80 CPC", llm=fake_llm, db_path=db_path, data_dir=data_dir
            )
            assert result2.source == "cache"
            assert fake_llm.invoke.call_count == 1  # NOT incremented

        finally:
            os.unlink(db_path)

    def test_cache_hit_different_phrasing(self):
        """Different surface form, same canonical key → cache hit."""
        db_path = _make_temp_db()
        data_dir = _make_provision_dir([SAMPLE_PROVISION])
        fake_llm = _make_fake_llm()
        try:
            # Cache "Section 80 CPC"
            resolve_checklist("Section 80 CPC", llm=fake_llm, db_path=db_path, data_dir=data_dir)
            assert fake_llm.invoke.call_count == 1

            # Ask with different phrasing
            result = resolve_checklist(
                "Code of Civil Procedure Section 80",
                llm=fake_llm, db_path=db_path, data_dir=data_dir,
            )
            assert result.source == "cache"
            assert fake_llm.invoke.call_count == 1  # No new LLM call

        finally:
            os.unlink(db_path)

    def test_provision_not_found(self):
        db_path = _make_temp_db()
        data_dir = _make_provision_dir([])  # Empty provisions dir
        fake_llm = _make_fake_llm()
        try:
            result = resolve_checklist(
                "Section 999 Nonexistent Act",
                llm=fake_llm, db_path=db_path, data_dir=data_dir,
            )
            assert result.source == "not_found"
            assert result.checklist == []
            assert fake_llm.invoke.call_count == 0  # No LLM call on not-found
        finally:
            os.unlink(db_path)

    def test_grouped_structure(self):
        """Result checklist is list[list[ChecklistCondition]], group_labels is list[str]."""
        db_path = _make_temp_db()
        data_dir = _make_provision_dir([SAMPLE_PROVISION])
        fake_llm = _make_fake_llm()
        try:
            result = resolve_checklist(
                "Section 80 CPC", llm=fake_llm, db_path=db_path, data_dir=data_dir
            )
            assert isinstance(result.checklist, list)
            for group in result.checklist:
                assert isinstance(group, list)
                for item in group:
                    assert isinstance(item, ChecklistCondition)
                    assert isinstance(item.text, str)
                    assert isinstance(item.critical, bool)
            assert isinstance(result.group_labels, list)
            assert len(result.group_labels) == len(result.checklist)
        finally:
            os.unlink(db_path)

    def test_critical_flag_preserved_through_cache(self):
        """Critical flags survive cache round-trip."""
        db_path = _make_temp_db()
        data_dir = _make_provision_dir([SAMPLE_PROVISION])
        fake_llm = _make_fake_llm()
        try:
            # First call: LLM
            r1 = resolve_checklist(
                "Section 80 CPC", llm=fake_llm, db_path=db_path, data_dir=data_dir
            )
            assert r1.source == "llm"
            assert r1.checklist[0][0].critical is True
            assert r1.checklist[0][1].critical is False

            # Second call: cache — critical flags must match
            r2 = resolve_checklist(
                "Section 80 CPC", llm=fake_llm, db_path=db_path, data_dir=data_dir
            )
            assert r2.source == "cache"
            assert r2.checklist[0][0].critical is True
            assert r2.checklist[0][1].critical is False
        finally:
            os.unlink(db_path)


# ─────────────────────────────────────────────
# Order/Rule lookup tests (Orders_Rules/ schema: identifier/text)
# Regression for the bug where Order/Rule provisions were unreachable:
# wrong directory AND wrong schema keys, so every Order/Rule -> not_found.
# ─────────────────────────────────────────────

class TestLookupOrderRule:
    def test_finds_order_rule_from_orders_dir(self):
        """An Order/Rule provision lives in the orders dir under identifier/text."""
        orders_dir = _make_orders_dir([ORDER_RULE_PROVISION])
        data_dir = _make_provision_dir([])  # no sections
        result = _lookup_provision("Order 39 Rule 1 CPC", data_dir, orders_dir=orders_dir)
        assert result is not None
        body, doc_id = result
        assert doc_id == 90001
        assert "temporary injunction" in body.lower()

    def test_order_rule_act_phrase_absent_still_matches(self):
        """Rule text never says 'Code of Civil Procedure' — must still match (CPC implied)."""
        orders_dir = _make_orders_dir([ORDER_RULE_PROVISION])
        result = _lookup_provision(
            "Order 39 Rule 1 of the Code of Civil Procedure",
            _make_provision_dir([]), orders_dir=orders_dir,
        )
        assert result is not None

    def test_order_rule_wrong_rule_returns_none(self):
        orders_dir = _make_orders_dir([ORDER_RULE_PROVISION])
        result = _lookup_provision("Order 39 Rule 2 CPC", _make_provision_dir([]), orders_dir=orders_dir)
        assert result is None

    def test_resolve_checklist_order_rule_end_to_end(self):
        """resolve_checklist must reach the LLM for an Order/Rule provision (not no-op)."""
        db_path = _make_temp_db()
        orders_dir = _make_orders_dir([ORDER_RULE_PROVISION])
        data_dir = _make_provision_dir([])
        fake_llm = _make_fake_llm()
        try:
            result = resolve_checklist(
                "Order 39 Rule 1 CPC", llm=fake_llm,
                db_path=db_path, data_dir=data_dir, orders_dir=orders_dir,
            )
            assert result.source == "llm"
            assert fake_llm.invoke.call_count == 1
            assert len(result.checklist) == 2
            assert result.canonical_key == "order_39_rule_1__code_of_civil_procedure"
        finally:
            os.unlink(db_path)
