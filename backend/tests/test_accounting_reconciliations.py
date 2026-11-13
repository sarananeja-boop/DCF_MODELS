"""
Accounting Reconciliation Suite
================================
Tests all statutory 3-statement reconciliation identities, FX cash rollforward handling,
D&A symmetry, TSM share bridges, lease/cash alignment, and fail-closed blocking on corrupted inputs.
"""

import copy
import pytest

from engine.data_layer import fetch_stock_data, compute_historical_metrics
from engine.market_config import MARKET_PROFILES
from engine.dcf_engine import compute_wacc, run_dcf
from engine.monte_carlo import run_monte_carlo
from engine.validators import run_accounting_reconciliations, evaluate_validation_status


@pytest.mark.parametrize("ticker,market,min_checks", [
    ("DUOL", "US", 10),
    ("CESC.NS", "IN", 10),
    ("HDFCBANK.NS", "IN", 8),
])
def test_all_statutory_reconciliations_pass_on_clean_fixtures(ticker, market, min_checks):
    sd = fetch_stock_data(ticker, market)
    met = compute_historical_metrics(sd)
    recons = run_accounting_reconciliations(sd, met, None, None)

    assert len(recons["checks"]) >= min_checks
    assert recons["blocking_accounting_failures"] == [], (
        f"Unexpected blocking failures for {ticker}: {recons['blocking_accounting_failures']}"
    )
    assert recons["blocking_data_failures"] == []
    assert recons["reconciled_all_periods"] is True


def test_corrupted_balance_sheet_triggers_blocking_accounting_reconciliation():
    sd = fetch_stock_data("DUOL", "US")
    met = copy.deepcopy(compute_historical_metrics(sd))
    # Inject a 15% Balance Sheet imbalance into Total Assets
    met["statements"]["balance_sheet"]["Total Assets"][-1] *= 1.15

    recons = run_accounting_reconciliations(sd, met, None, None)
    assert "bs_identity" in recons["blocking_accounting_failures"]
    gate = evaluate_validation_status(sd, met, None, None, None, reconciliations=recons)
    assert gate["validation_status"] == "BLOCKED_ACCOUNTING_RECONCILIATION"
    assert gate["is_blocked"] is True


def test_corrupted_cash_rollforward_triggers_blocking_failure():
    sd = fetch_stock_data("CESC.NS", "IN")
    met = copy.deepcopy(compute_historical_metrics(sd))
    met["statements"]["cash_flow"]["Ending Cash Position"][-1] += 10e9

    recons = run_accounting_reconciliations(sd, met, None, None)
    assert "cf_cash_rollforward" in recons["blocking_accounting_failures"]
    gate = evaluate_validation_status(sd, met, None, None, None, reconciliations=recons)
    assert gate["validation_status"] == "BLOCKED_ACCOUNTING_RECONCILIATION"
    assert gate["is_blocked"] is True


def test_mc_draw_identity_and_lease_cash_policy_alignment():
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
        current_margin=met["ebit_margins"][-1],
    )
    mc = run_monte_carlo(
        metrics=met,
        wacc_data=wacc,
        stock_data=sd,
        market_profile=mp,
        terminal_growth=mp["terminal_growth"],
        iterations=500,
        base_growth=met["avg_rev_growth"],
        base_margin=met["avg_ebit_margin"],
        base_wacc=wacc["wacc"],
        current_margin=met["ebit_margins"][-1],
    )
    recons = run_accounting_reconciliations(sd, met, dcf, mc)
    chk_map = {c["id"]: c for c in recons["checks"]}
    assert chk_map["mc_accounting_identity"]["status"] == "PASS"
    assert chk_map["lease_cash_policy"]["status"] == "PASS"
    assert chk_map["share_bridge"]["status"] == "PASS"
