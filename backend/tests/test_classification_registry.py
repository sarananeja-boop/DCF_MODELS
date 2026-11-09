"""
Tests for Centralized Classification Registry & Ticker Resolution
=================================================================
Verifies:
1. Every entry in CLASSIFICATION_REGISTRY has an explicit reason and valid ISO added date.
2. All exported symbol sets in classification_overrides.py are derived from CLASSIFICATION_REGISTRY.
3. classify_sector_dynamics() and resolve_sector_and_industry() behave deterministically.
4. Legacy/alias ticker resolution maps to canonical symbols.
"""

from __future__ import annotations

import datetime
import pytest

from engine.classification_overrides import (
    CAPTIVE_FINANCE_SYMBOLS,
    CLASSIFICATION_REGISTRY,
    DOWNSTREAM_REFINING_SYMBOLS,
    KNOWN_BALANCE_SHEET_FINANCIAL_SYMBOLS,
    KNOWN_CAPITAL_LIGHT_FINANCIAL_SYMBOLS,
    KNOWN_CYCLICAL_SYMBOLS,
    KNOWN_EXTRACTIVE_SYMBOLS,
    NBFC_CONSOLIDATING_SYMBOLS,
    NON_CYCLICAL_CONGLOMERATE_SYMBOLS,
    USD_REPORTING_INDIAN_ADR_SYMBOLS,
    resolve_sector_and_industry,
)
from engine.data_layer import classify_sector_dynamics
from engine.ticker_universe import resolve_ticker


def test_registry_entries_have_reason_and_iso_date() -> None:
    assert len(CLASSIFICATION_REGISTRY) >= 120
    for sym, entry in CLASSIFICATION_REGISTRY.items():
        assert sym == sym.upper().strip(), f"Symbol {sym} is not uppercase/trimmed"
        assert isinstance(entry.reason, str) and len(entry.reason.strip()) >= 10, (
            f"Registry entry {sym} is missing a descriptive reason"
        )
        # Validate ISO date format YYYY-MM-DD
        parsed_date = datetime.date.fromisoformat(entry.added)
        assert parsed_date.year >= 2026


def test_derived_sets_are_subsets_of_registry() -> None:
    reg_keys = set(CLASSIFICATION_REGISTRY.keys())
    for sym_set in (
        NON_CYCLICAL_CONGLOMERATE_SYMBOLS,
        KNOWN_EXTRACTIVE_SYMBOLS,
        KNOWN_CYCLICAL_SYMBOLS,
        DOWNSTREAM_REFINING_SYMBOLS,
        CAPTIVE_FINANCE_SYMBOLS,
        NBFC_CONSOLIDATING_SYMBOLS,
        USD_REPORTING_INDIAN_ADR_SYMBOLS,
        KNOWN_BALANCE_SHEET_FINANCIAL_SYMBOLS,
        KNOWN_CAPITAL_LIGHT_FINANCIAL_SYMBOLS,
    ):
        assert len(sym_set) > 0
        assert sym_set.issubset(reg_keys)


def test_classify_sector_dynamics_rules() -> None:
    # Diversified conglomerates & specialty chemical compounders -> (False, False)
    assert classify_sector_dynamics("Energy", "Oil & Gas Refining & Marketing", "RELIANCE.NS", "Reliance Industries") == (False, False)
    assert classify_sector_dynamics("Energy", "Thermal Coal", "ADANIENT.NS", "Adani Enterprises") == (False, False)
    assert classify_sector_dynamics("Basic Materials", "Specialty Chemicals", "ASIANPAINT.NS", "Asian Paints") == (False, False)

    # Upstream extractive -> (True, True)
    assert classify_sector_dynamics("Energy", "Oil & Gas Integrated", "ONGC.NS", "Oil and Natural Gas Corp") == (True, True)
    assert classify_sector_dynamics(None, None, "COALINDIA.NS", "Coal India") == (True, True)
    assert classify_sector_dynamics("Energy", "Oil & Gas Integrated", "XOM", "Exxon Mobil") == (True, True)

    # Downstream refining / commodity cyclical -> (False, True)
    assert classify_sector_dynamics("Energy", "Oil & Gas Refining & Marketing", "IOC.NS", "Indian Oil Corp") == (False, True)
    assert classify_sector_dynamics(None, None, "BPCL.NS", "Bharat Petroleum") == (False, True)

    # Secular IT / Consumer -> (False, False)
    assert classify_sector_dynamics("Technology", "Information Technology Services", "TCS.NS", "Tata Consultancy Services") == (False, False)
    assert classify_sector_dynamics("Technology", "Consumer Electronics", "AAPL", "Apple Inc.") == (False, False)


def test_resolve_sector_and_industry_overrides_and_fallbacks() -> None:
    # ADANIENT overrides legacy Yahoo 'Thermal Coal' metadata
    sec, ind = resolve_sector_and_industry("ADANIENT.NS", "Adani Enterprises", "Energy", "Thermal Coal", False, False)
    assert sec == "Industrials"
    assert ind == "Infrastructure & Conglomerates"

    # Deterministic fallback when sector is None (e.g. cloud IP block)
    sec_ongc, ind_ongc = resolve_sector_and_industry("ONGC.NS", "ONGC", None, None, True, True)
    assert sec_ongc == "Energy"
    assert ind_ongc == "Oil & Gas Integrated"

    sec_ioc, ind_ioc = resolve_sector_and_industry("IOC.NS", "Indian Oil Corporation", None, None, False, True)
    assert sec_ioc == "Energy"
    assert ind_ioc == "Oil & Gas Refining & Marketing"

    sec_infy, ind_infy = resolve_sector_and_industry("INFY.NS", "Infosys Limited", None, None, False, False)
    assert sec_infy == "Technology"
    assert ind_infy == "Information Technology Services"


def test_resolve_ticker_aliases() -> None:
    assert resolve_ticker("ZOMATO", "IN")[0] == "ETERNAL.NS"
    assert resolve_ticker("MINDTREE", "IN")[0] == "LTIM.NS"
    assert resolve_ticker("CADILAHC", "IN")[0] == "ZYDUSLIFE.NS"
    assert resolve_ticker("FB", "US")[0] == "META"
    assert resolve_ticker("SQ", "US")[0] == "XYZ"
