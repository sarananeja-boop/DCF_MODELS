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
    ("GROWW.NS", "IN", 10),
    ("RELIANCE.NS", "IN", 10),
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
    chk_map = {c["id"]: c for c in recons["checks"]}
    if "cf_cash_rollforward" in chk_map:
        assert chk_map["cf_cash_rollforward"]["status"] == "PASS"


def test_corrupted_balance_sheet_warns_without_blocking_valuation():
    sd = fetch_stock_data("DUOL", "US")
    met = copy.deepcopy(compute_historical_metrics(sd))
    # Inject a 15% Balance Sheet imbalance into Total Assets
    met["statements"]["balance_sheet"]["Total Assets"][-1] *= 1.15

    recons = run_accounting_reconciliations(sd, met, None, None)
    chk_map = {c["id"]: c for c in recons["checks"]}
    assert chk_map["bs_identity"]["status"] == "WARN"
    assert recons["blocking_accounting_failures"] == []
    gate = evaluate_validation_status(sd, met, None, None, None, reconciliations=recons)
    assert gate["validation_status"] != "BLOCKED_ACCOUNTING_RECONCILIATION"
    assert gate["is_blocked"] is False


def test_corrupted_cash_rollforward_warns_without_blocking_valuation():
    sd = fetch_stock_data("CESC.NS", "IN")
    met = copy.deepcopy(compute_historical_metrics(sd))
    met["statements"]["cash_flow"]["Ending Cash Position"][-1] += 10e9

    recons = run_accounting_reconciliations(sd, met, None, None)
    chk_map = {c["id"]: c for c in recons["checks"]}
    assert chk_map["cf_cash_rollforward"]["status"] == "WARN"
    assert recons["blocking_accounting_failures"] == []
    gate = evaluate_validation_status(sd, met, None, None, None, reconciliations=recons)
    assert gate["validation_status"] != "BLOCKED_ACCOUNTING_RECONCILIATION"
    assert gate["is_blocked"] is False


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



def test_yahoo_other_cash_adjustment_outside_change_in_cash_conventions():
    """
    Yahoo Finance reports "Other Cash Adjustment Outside Changein Cash" under two
    conventions:
      1) Additive outside-CF bridge item (e.g., JIOFIN/RELIANCE/SUNPHARMA demerger
         & subsidiary cash transfers) needed to reconcile Beg + Chg + FX + Oth = End.
      2) Non-additive memo already reflected in Changes In Cash (e.g., HDFCBANK FY24),
         where Beg + Chg + FX already equals End and adding Oth would corrupt Cash.
    """
    from engine.data_layer import _copy_stock_data, compute_historical_metrics, fetch_stock_data
    from engine.validators import run_accounting_reconciliations

    base_sd = fetch_stock_data("CESC.NS", "IN")
    base_metrics = compute_historical_metrics(_copy_stock_data(base_sd))
    base_fx_latest = float(
        base_metrics["statements"]["cash_flow"]["Effect of Exchange Rate Changes (FX)"][-1]
    )

    # Case 1: Additive outside-CF adjustment (JIOFIN-style)
    add_sd = _copy_stock_data(base_sd)
    adj_amt = 442_600_000.0
    cf_add = add_sd["cash_flow"]
    oth_series = [adj_amt] + [0.0] * (len(cf_add) - 1)
    cf_add["Other Cash Adjustment Outside Changein Cash"] = oth_series
    end_col = cf_add.columns.get_loc("End Cash Position")
    cf_add.iloc[0, end_col] = float(cf_add.iloc[0, end_col]) + adj_amt

    m_add = compute_historical_metrics(add_sd)
    r_add = run_accounting_reconciliations(add_sd, m_add)
    chk_add = {c["id"]: c for c in r_add["checks"]}
    assert chk_add["cf_cash_rollforward"]["status"] == "PASS"
    assert chk_add["cf_cash_rollforward"]["max_abs_diff"] < 1.0
    assert abs(
        float(m_add["statements"]["cash_flow"]["Effect of Exchange Rate Changes (FX)"][-1])
        - (base_fx_latest + adj_amt)
    ) < 1.0

    # Case 2: Already-reflected non-additive memo (HDFCBANK-style)
    memo_sd = _copy_stock_data(base_sd)
    memo_amt = 111_817_100_000.0
    cf_memo = memo_sd["cash_flow"]
    cf_memo["Other Cash Adjustment Outside Changein Cash"] = [memo_amt] + [0.0] * (len(cf_memo) - 1)

    m_memo = compute_historical_metrics(memo_sd)
    r_memo = run_accounting_reconciliations(memo_sd, m_memo)
    chk_memo = {c["id"]: c for c in r_memo["checks"]}
    assert chk_memo["cf_cash_rollforward"]["status"] == "PASS"
    assert chk_memo["cf_cash_rollforward"]["max_abs_diff"] < 1.0
    assert abs(
        float(m_memo["statements"]["cash_flow"]["Effect of Exchange Rate Changes (FX)"][-1])
        - base_fx_latest
    ) < 1.0



def test_scale_monetary_df_preserves_share_counts_and_tax_rate():
    """Cross-currency FX and unit-scale scaling must never multiply share counts or tax rates."""
    import pandas as pd
    from engine.data_layer import _scale_monetary_df

    df = pd.DataFrame(
        {
            "Total Revenue": [20_158_000_000.0],
            "Net Income": [3_313_000_000.0],
            "Basic Average Shares": [4_112_814_745.0],
            "Diluted Average Shares": [4_120_108_168.0],
            "Ordinary Shares Number": [4_046_940_812.0],
            "Share Issued": [4_055_591_723.0],
            "Tax Rate For Calcs": [0.264],
            "Basic EPS": [0.81],
            "Diluted EPS": [0.80],
        },
        index=[pd.Timestamp("2026-03-31")],
    )

    fx_df = _scale_monetary_df(df, 94.23, scale_per_share=True)
    assert abs(fx_df["Net Income"].iloc[0] - 3_313_000_000.0 * 94.23) < 1e-3
    assert abs(fx_df["Diluted EPS"].iloc[0] - 0.80 * 94.23) < 1e-6
    assert fx_df["Basic Average Shares"].iloc[0] == 4_112_814_745.0
    assert fx_df["Diluted Average Shares"].iloc[0] == 4_120_108_168.0
    assert fx_df["Ordinary Shares Number"].iloc[0] == 4_046_940_812.0
    assert fx_df["Share Issued"].iloc[0] == 4_055_591_723.0
    assert fx_df["Tax Rate For Calcs"].iloc[0] == 0.264

    unit_df = _scale_monetary_df(df, 100.0, scale_per_share=False)
    assert abs(unit_df["Total Revenue"].iloc[0] - 20_158_000_000.0 * 100.0) < 1e-3
    assert unit_df["Diluted Average Shares"].iloc[0] == 4_120_108_168.0
    assert unit_df["Tax Rate For Calcs"].iloc[0] == 0.264
    assert unit_df["Diluted EPS"].iloc[0] == 0.80


def test_sec_revenue_tag_prefers_consolidated_revenues_on_same_year_tie():
    """
    SEC EDGAR consolidated Revenues (including REIT lease revenue / insurer premiums)
    must win over ASC 606 RevenueFromContractWithCustomerExcludingAssessedTax on tie,
    while allowing newer ASC 606 years when Revenues stopped earlier.
    """
    from engine.sec_edgar import _pick_annual_duration_facts

    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-20", "frame": "CY2024", "val": 10_000_000_000.0}
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-20", "frame": "CY2024", "val": 900_000_000.0},
                            {"form": "10-K", "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-20", "frame": "CY2025", "val": 1_050_000_000.0},
                        ]
                    }
                },
            }
        }
    }
    picked = _pick_annual_duration_facts(
        facts,
        "us-gaap",
        ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        "USD",
    )
    assert picked[2024]["tag"] == "us-gaap:Revenues"
    assert picked[2024]["value"] == 10_000_000_000.0
    assert picked[2025]["tag"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert picked[2025]["value"] == 1_050_000_000.0
