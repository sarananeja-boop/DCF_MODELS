"""
Core Valuation Mathematical Invariants Suite
============================================
Verifies partial derivative monotonicity, EV-to-Equity bridge conservation,
ROIC terminal reinvestment linkage, Corporate DDM / Bank FCFE identities, and zero opaque plugs.
"""

import math
import pytest

from engine.data_layer import fetch_stock_data, compute_historical_metrics
from engine.market_config import MARKET_PROFILES
from engine.dcf_engine import compute_wacc, run_dcf, compute_dcf_scenarios
from engine.bank_engine import compute_bank_cost_of_equity, run_bank_valuation


def test_fcff_valuation_monotonicity_invariants():
    sd = fetch_stock_data("DUOL", "US")
    met = compute_historical_metrics(sd)
    mp = MARKET_PROFILES["US"]
    wacc = compute_wacc(sd, met, mp)

    g0 = met["avg_rev_growth"]
    m0 = met["avg_ebit_margin"]
    cm0 = met["ebit_margins"][-1]
    w0 = wacc["wacc"]
    tg0 = mp["terminal_growth"]

    base = run_dcf(g0, m0, w0, met, wacc, sd, terminal_growth=tg0, current_margin=cm0)
    hi_wacc = run_dcf(g0, m0, w0 + 0.015, met, wacc, sd, terminal_growth=tg0, current_margin=cm0)
    hi_margin = run_dcf(g0, m0 + 0.03, w0, met, wacc, sd, terminal_growth=tg0, current_margin=cm0)
    hi_growth = run_dcf(g0 + 0.05, m0, w0, met, wacc, sd, terminal_growth=tg0, current_margin=cm0)
    hi_tg = run_dcf(g0, m0, w0, met, wacc, sd, terminal_growth=tg0 + 0.005, current_margin=cm0)

    assert hi_wacc["implied_price"] < base["implied_price"]
    assert hi_margin["implied_price"] > base["implied_price"]
    assert hi_growth["implied_price"] > base["implied_price"]
    assert hi_tg["implied_price"] > base["implied_price"]


def test_ev_to_equity_bridge_conservation_and_diluted_shares():
    sd = fetch_stock_data("CESC.NS", "IN")
    met = compute_historical_metrics(sd)
    mp = MARKET_PROFILES["IN"]
    wacc = compute_wacc(sd, met, mp)
    dcf = run_dcf(
        start_growth=met["avg_rev_growth"],
        ebit_margin=met["avg_ebit_margin"],
        discount_rate=wacc["wacc"],
        metrics=met,
        wacc_data=wacc,
        stock_data=sd,
        terminal_growth=mp["terminal_growth"],
    )

    assert math.isclose(dcf["enterprise_value"], dcf["pv_ufcf"] + dcf["pv_terminal_value"], rel_tol=1e-9)
    expected_eq = max(
        0.0,
        dcf["enterprise_value"] + dcf["cash"] - dcf["total_debt"] - dcf["minority_interest"] - dcf["preferred_stock"],
    )
    assert math.isclose(dcf["equity_value"], expected_eq, rel_tol=1e-9)
    assert math.isclose(dcf["implied_price"], dcf["equity_value"] / dcf["shares_used"], rel_tol=1e-9)
    assert dcf["minority_interest"] > 0  # CESC has non-controlling interest on consolidated BS


def test_roic_linked_terminal_reinvestment_and_scenarios():
    sd = fetch_stock_data("DUOL", "US")
    met = compute_historical_metrics(sd)
    mp = MARKET_PROFILES["US"]
    wacc = compute_wacc(sd, met, mp)
    dcf = run_dcf(
        start_growth=met["avg_rev_growth"],
        ebit_margin=met["avg_ebit_margin"],
        discount_rate=wacc["wacc"],
        metrics=met,
        wacc_data=wacc,
        stock_data=sd,
        terminal_growth=mp["terminal_growth"],
        current_margin=met["ebit_margins"][-1],
    )

    expected_roic_reinv = dcf["effective_terminal_growth"] / dcf["sustainable_roic"]
    assert dcf["terminal_reinv_rate"] >= min(expected_roic_reinv, 0.05) - 1e-9
    assert math.isclose(dcf["roic_reinv"], expected_roic_reinv, rel_tol=1e-6)

    scen = compute_dcf_scenarios(
        met["avg_rev_growth"],
        met["avg_ebit_margin"],
        wacc["wacc"],
        met,
        wacc,
        sd,
        terminal_growth=mp["terminal_growth"],
        current_margin=met["ebit_margins"][-1],
    )
    assert "base" in scen and scen["base"]["implied_price"] == pytest.approx(dcf["implied_price"], rel=1e-6)
    assert scen["full_rsu_dilution"]["implied_price"] <= scen["base"]["implied_price"]


def test_bank_ddm_cost_of_equity_and_valuation_invariants():
    sd = fetch_stock_data("HDFCBANK.NS", "IN")
    met = compute_historical_metrics(sd)
    mp = MARKET_PROFILES["IN"]
    ke_data = compute_bank_cost_of_equity(sd, mp)
    base = run_bank_valuation(
        start_growth=met["avg_ni_growth"],
        target_roe=met["avg_roe"],
        cost_of_equity=ke_data["cost_of_equity"],
        metrics=met,
        stock_data=sd,
        market_profile=mp,
        terminal_growth=mp["terminal_growth"],
    )
    hi_ke = run_bank_valuation(
        start_growth=met["avg_ni_growth"],
        target_roe=met["avg_roe"],
        cost_of_equity=ke_data["cost_of_equity"] + 0.015,
        metrics=met,
        stock_data=sd,
        market_profile=mp,
        terminal_growth=mp["terminal_growth"],
    )
    assert hi_ke["implied_price"] < base["implied_price"]
    assert math.isclose(base["equity_value"], base["pv_ufcf"] + base["pv_terminal_value"], rel_tol=1e-9)


@pytest.mark.parametrize("ticker,market", [("DUOL", "US"), ("CESC.NS", "IN"), ("HDFCBANK.NS", "IN")])
def test_api_analyze_override_monotonicity_no_discontinuity(ticker, market):
    """Ensure /api/analyze slider overrides match baseline at 0-delta and move monotonically."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    base = client.post("/api/analyze", json={"ticker": ticker, "market": market, "monte_carlo_iterations": 100}).json()
    p0 = base["dcf_result"]["implied_price"]
    diag = base["diagnostics"]
    g0 = diag["default_growth"]
    m0 = diag["default_margin"]
    w0 = diag["default_wacc"]
    tg0 = base["macro"]["terminal_growth"]

    def run_ovr(g=g0, m=m0, w=w0, tg=tg0):
        resp = client.post(
            "/api/analyze",
            json={
                "ticker": ticker,
                "market": market,
                "monte_carlo_iterations": 100,
                "overrides": {
                    "revenue_growth": g,
                    "ebit_margin": m,
                    "wacc": w,
                    "terminal_growth": tg,
                    "projection_years": 5,
                },
            },
        )
        assert resp.status_code == 200
        return resp.json()["dcf_result"]["implied_price"]

    assert math.isclose(run_ovr(), p0, rel_tol=1e-9)
    assert run_ovr(g=g0 - 0.001) < p0 < run_ovr(g=g0 + 0.001)
    assert run_ovr(m=m0 - 0.001) < p0 < run_ovr(m=m0 + 0.001)
    assert run_ovr(w=w0 + 0.001) < p0 < run_ovr(w=w0 - 0.001)
    assert run_ovr(tg=tg0 - 0.001) < p0 <= run_ovr(tg=tg0 + 0.001)


def test_adanient_and_conglomerate_sector_classification():
    from engine.data_layer import classify_sector_dynamics

    assert classify_sector_dynamics("Energy", "Thermal Coal", "ADANIENT.NS", "Adani Enterprises Limited") == (False, False)
    assert classify_sector_dynamics("Energy", "Oil & Gas Refining & Marketing", "RELIANCE.NS", "Reliance Industries Limited") == (False, False)
    assert classify_sector_dynamics("Basic Materials", "Coal", "COALINDIA.NS", "Coal India Limited") == (True, True)
