"""
Regression Canary Tests (Phase 0A Safety Net)
=============================================
Guards against the specific classes of historical valuation bugs fixed in
recent commits and verifies that our invariant checks fail loudly if any
of those guards are bypassed:
  1. CESC.NS regulated utility terminal reinvestment dilution (6b0b34f)
  2. INFY.NS USD-to-INR ADR statement conversion under cloud blackout (27e2a28)
  3. BYND non-operating debt-extinguishment gain & distressed guardrail (0fb6a79)
  4. ADANIENT.NS legacy Yahoo 'Thermal Coal' sector misclassification (0fb6a79)
  5. SBUX / DG / DNUT ASC 842 operating lease double-count exclusion (0fb6a79)
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

import engine.data_layer as dl
from main import AnalyzeRequest, analyze
from tests.conftest import OfflineFixtureStore


def test_canary_1_cesc_regulated_utility_terminal_reinvestment(
    fixture_store: OfflineFixtureStore,
) -> None:
    """CESC.NS is a regulated power utility (sustainable ROIC ~ 9.25% < WACC ~ 9.77%).
    It must NEVER blend historical negative NWC / CapEx into terminal_reinv_rate."""
    with fixture_store.patch_env(mode="normal"):
        np.random.seed(42)
        res = analyze(AnalyzeRequest(ticker="CESC.NS", market="IN", monte_carlo_iterations=1000))

    dcf = res["dcf_result"]
    assert dcf["is_high_roic"] is False
    assert dcf["terminal_reinv_rate"] == pytest.approx(dcf["roic_reinv"], abs=1e-6)
    assert 0.45 <= dcf["terminal_reinv_rate"] <= 0.65
    assert 75.0 <= float(dcf["implied_price"]) <= 125.0


def test_canary_2_infy_cross_currency_conversion_and_canary_trip(
    fixture_store: OfflineFixtureStore,
) -> None:
    """INFY.NS reports statements in USD while trading in INR on NSE.
    Even in total metadata blackout (cloud_blackout), deterministic ADR detection
    must convert USD statements to INR. If FX conversion is disabled, Invariant 2
    (revenue / market_cap >= 0.015) immediately trips."""
    with fixture_store.patch_env(mode="cloud_blackout"):
        np.random.seed(42)
        res_ok = analyze(AnalyzeRequest(ticker="INFY.NS", market="IN", monte_carlo_iterations=1000))

    iv_ok = float(res_ok["dcf_result"]["implied_price"])
    rev_ratio_ok = float(res_ok["historicals"]["revenue"][-1]) / float(res_ok["market_data"]["market_cap"])
    assert iv_ok > 800.0
    assert 0.15 <= rev_ratio_ok <= 1.50

    # Now simulate the regression where cross-currency FX conversion fails (returns 1.0)
    with fixture_store.patch_env(mode="cloud_blackout"):
        dl._STOCK_DATA_CACHE.clear()
        with patch.object(dl, "get_cross_fx_rate", return_value=1.0):
            res_bug = analyze(AnalyzeRequest(ticker="INFY.NS", market="IN", monte_carlo_iterations=1000))
            rev_ratio_bug = float(res_bug["historicals"]["revenue"][-1]) / float(res_bug["market_data"]["market_cap"])
            # Canary assertion: Invariant 2 threshold (0.015) catches the unscaled USD statements
            assert rev_ratio_bug < 0.015


def test_canary_3_bynd_distressed_and_non_operating_gain_guardrail(
    fixture_store: OfflineFixtureStore,
) -> None:
    """BYND has structural negative operating EBIT and massive debt overhang.
    It must be flagged as DCF UNRELIABLE / DISTRESSED with implied_price == 0.0."""
    with fixture_store.patch_env(mode="normal"):
        np.random.seed(42)
        res = analyze(AnalyzeRequest(ticker="BYND", market="US", monte_carlo_iterations=1000))

    assert res["dcf_result"]["implied_price"] == 0.0
    assert res["verdict"]["verdict"] == "DCF UNRELIABLE / DISTRESSED"
    assert res["diagnostics"]["historical_fcf_negative"] is True


def test_canary_4_adanient_not_thermal_coal_extractive(
    fixture_store: OfflineFixtureStore,
) -> None:
    """ADANIENT.NS must be classified as Industrials / Infrastructure & Conglomerates
    and non-extractive / non-cyclical across both normal and cloud_sim modes."""
    for mode in ("normal", "cloud_sim", "cloud_blackout"):
        with fixture_store.patch_env(mode=mode):
            np.random.seed(42)
            res = analyze(AnalyzeRequest(ticker="ADANIENT.NS", market="IN", monte_carlo_iterations=1000))
            assert res["company"]["sector"] == "Industrials"
            assert res["company"]["industry"] == "Infrastructure & Conglomerates"
            assert res["diagnostics"]["is_extractive"] is False
            assert res["diagnostics"]["is_cyclical"] is False


def test_canary_5_retail_operating_lease_exclusion(
    fixture_store: OfflineFixtureStore,
) -> None:
    """Retail/restaurant chains (DG, SBUX, DNUT) have large ASC 842 operating lease
    liabilities on the balance sheet. Since rent is already expensed in EBIT,
    lease obligations must be excluded from EV-bridge Total Debt so equity value stays positive."""
    with fixture_store.patch_env(mode="normal"):
        for sym in ("DG", "SBUX", "DNUT"):
            np.random.seed(42)
            res = analyze(AnalyzeRequest(ticker=sym, market="US", monte_carlo_iterations=1000))
            assert float(res["dcf_result"]["implied_price"]) > 0.0
            assert float(res["dcf_result"]["equity_value"]) > 0.0


def test_canary_6_capital_light_fintech_and_tech_name_collision_guardrails() -> None:
    """Verifies that fee-based discount brokers (GROWW, 5PAISA, ANGELONE, IBKR) and enterprise
    software companies with 'financial' in their name (OFSS) are NEVER misrouted to
    Tier-1 Banking Regulatory Capital DDM."""
    from engine.ticker_universe import is_capital_light_financial
    from engine.classification_overrides import get_override_entry

    # 1. Brokers & Fintechs must be detected as capital-light
    assert is_capital_light_financial("GROWW.NS", "Billionbrains Garage Ventures Ltd", "Financial Services", "Capital Markets") is True
    assert is_capital_light_financial("ANGELONE.NS", "Angel One Ltd", "Financial Services", "Capital Markets") is True
    assert is_capital_light_financial("5PAISA.NS", "5paisa Capital Ltd", "Financial Services", "Capital Markets") is True
    assert is_capital_light_financial("IBKR", "Interactive Brokers Group, Inc.", "Financial Services", "Capital Markets") is True
    assert is_capital_light_financial("GEOJITFSL.NS", "Geojit Financial Services Ltd", "Financial Services", "Capital Markets") is True
    assert is_capital_light_financial("SHAREINDIA.NS", "Share India Securities Ltd", "Financial Services", "Capital Markets") is True

    # 2. Banks must NOT be capital light
    assert is_capital_light_financial("HDFCBANK.NS", "HDFC Bank Ltd", "Financial Services", "Banks - Diversified") is False
    assert is_capital_light_financial("SBIN.NS", "State Bank of India", "Financial Services", "Banks - Public") is False
    assert is_capital_light_financial("BAJFINANCE.NS", "Bajaj Finance Ltd", "Financial Services", "Credit Services") is False

    # 3. Enterprise software (OFSS) must be forced to Technology / non-financial
    ofss_entry = get_override_entry("OFSS")
    assert ofss_entry is not None
    assert ofss_entry.is_financial is False
    assert ofss_entry.force_sector == "Technology"

