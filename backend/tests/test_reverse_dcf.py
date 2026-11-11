"""Unit tests for the reverse DCF Expectations Investing solver."""

import pytest
from engine.reverse_dcf import calculate_reverse_dcf
from engine.data_layer import fetch_stock_data, compute_historical_metrics
from engine.market_config import get_market_profile
from engine.dcf_engine import compute_wacc, run_dcf


def test_reverse_dcf_basic_fcff():
    stock_data = fetch_stock_data("OFSS.NS", "IN")
    metrics = compute_historical_metrics(stock_data)
    market_profile = get_market_profile("IN")
    wacc_data = compute_wacc(stock_data, metrics, market_profile)

    base_res = run_dcf(
        start_growth=metrics["avg_rev_growth"],
        ebit_margin=metrics["avg_ebit_margin"],
        discount_rate=wacc_data["wacc"],
        metrics=metrics,
        wacc_data=wacc_data,
        stock_data=stock_data,
    )

    rev_dcf = calculate_reverse_dcf(
        current_price=stock_data["current_price"],
        model_fair_value=base_res["implied_price"],
        base_start_growth=metrics["avg_rev_growth"],
        base_target_margin=metrics["avg_ebit_margin"],
        discount_rate=wacc_data["wacc"],
        metrics=metrics,
        stock_data=stock_data,
        wacc_data=wacc_data,
    )

    assert rev_dcf is not None
    assert "market_implied_growth" in rev_dcf
    assert rev_dcf["market_implied_growth"] > rev_dcf["base_growth"]
    assert rev_dcf["growth_hurdle_gap_bps"] > 1000  # OFSS is trading at a premium over DCF
    assert rev_dcf["growth_status"] == "solved"
    assert "narrative" in rev_dcf
    assert len(rev_dcf["narrative"]) > 50


def test_reverse_dcf_invalid_inputs():
    res = calculate_reverse_dcf(
        current_price=0.0,
        model_fair_value=100.0,
        base_start_growth=0.1,
        base_target_margin=0.15,
        discount_rate=0.10,
        metrics={},
        stock_data={},
    )
    assert res["growth_status"] == "insufficient_data"
    assert res["growth_hurdle_gap_bps"] == 0.0
