"""
Unit & Integration Tests for Phase 3 Per-Stock Signal Backtester
(`backend/tests/test_ta_backtester.py`)
================================================================

Verifies all Phase 3 exit criteria from `implementation_plan_v3.md`:
1. 10 frozen signal definitions x 4 horizons (5, 10, 20, 60) = 40 tests.
2. Event dates and bootstrap statistics are 100% reproducible.
3. Strict zero look-ahead:
   - Signal masks at bar t are invariant to any price/volume changes at bars > t.
   - Trade entry fills at `Open_tr[t + 1]` and exits at `Close_tr[t + h]`.
   - Unfinished horizon events (`t + h >= N`) are excluded from completed trades.
4. 20-bar causal de-clustering (`t_next - t_prev >= 20`) with both raw and de-clustered counts.
5. 70/30 chronological in-sample / out-of-sample split.
6. Transaction costs: 10 bps (US) / 30 bps (IN) default, editable, Gross vs Net exact delta.
7. Statistical primitives: Wilson 95% CI, event-block bootstrap 95% CI, BH-FDR q-values across 40 tests, MAE <= 0 and MFE >= 0.
8. Non-promotional labels ("Historically favourable", "No reliable edge", "Insufficient evidence") and compliance guard banning "buy" and "profitable".
9. FastAPI endpoint `GET /api/technical/backtest` and `TA_ENABLED` kill-switch.
"""

from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from engine.market_history import MarketHistoryBundle
from engine.ta_backtester import (
    BACKTEST_HORIZONS,
    DECLUSTER_COOLDOWN_BARS,
    FROZEN_SIGNAL_CATALOG,
    MIN_IS_EVENTS_REQUIRED,
    TA_BACKTEST_VERSION,
    classify_backtest_cell,
    compute_benjamini_hochberg_qvalues,
    decluster_event_indices,
    generate_frozen_signal_masks,
    run_per_stock_backtest,
    wilson_confidence_interval,
)
import main


def _make_synthetic_bundle(
    n_bars: int = 1600,
    market: str = "US",
    seed: int = 42,
) -> MarketHistoryBundle:
    """Create a realistic synthetic multi-regime OHLCV MarketHistoryBundle for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_bars)

    # Combine cyclical regime waves + volatility clusters so all 10 signals trigger naturally
    t_grid = np.arange(n_bars, dtype=np.float64)
    cyclical = 0.0012 * np.sin(2.0 * np.pi * t_grid / 95.0) + 0.0008 * np.cos(2.0 * np.pi * t_grid / 32.0)
    noise = rng.normal(0.0003, 0.016, size=n_bars)
    rets = cyclical + noise

    close = 100.0 * np.exp(np.cumsum(rets))
    open_p = np.roll(close, 1) * (1.0 + rng.normal(0.0, 0.003, size=n_bars))
    open_p[0] = 100.0
    spread = np.abs(rng.normal(0.012, 0.006, size=n_bars))
    high = np.maximum(open_p, close) * (1.0 + spread)
    low = np.minimum(open_p, close) * (1.0 - spread)
    volume = rng.integers(500_000, 3_500_000, size=n_bars).astype(np.float64)
    # Inject periodic high-volume breakout spikes
    volume[::37] *= 2.8

    df = pd.DataFrame(
        {
            "Open": open_p,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )

    bench_rets = rng.normal(0.0003, 0.010, size=n_bars)
    bench_close = pd.Series(1000.0 * np.exp(np.cumsum(bench_rets)), index=dates, name="Close")

    is_in = market.upper() == "IN"
    return MarketHistoryBundle(
        symbol="RELIANCE" if is_in else "AAPL",
        listing_used="RELIANCE.NS" if is_in else "AAPL",
        market="IN" if is_in else "US",
        currency="INR" if is_in else "USD",
        currency_symbol="₹" if is_in else "$",
        benchmark="^NSEI" if is_in else "^GSPC",
        period_requested="10y",
        provider="yfinance",
        as_of=str(dates[-1])[:10],
        computed_at="2026-11-10T12:00:00Z",
        last_session=str(dates[-1])[:10],
        exchange_timezone="Asia/Kolkata" if is_in else "America/New_York",
        is_forming_daily_bar=False,
        history_start=str(dates[0])[:10],
        history_end=str(dates[-1])[:10],
        observations=n_bars,
        weekly_observations=n_bars // 5,
        monthly_observations=n_bars // 21,
        monthly_return_observations=max(0, (n_bars // 21) - 1),
        benchmark_observations=n_bars,
        benchmark_dropped_rows=0,
        quality_status="complete",
        warnings=[],
        quality_metrics={},
        coverage={},
        ohlc_split=df.copy(),
        ohlc_tr=df.copy(),
        benchmark_close=bench_close,
    )


def test_40_frozen_tests_structure_and_reproducibility():
    """Verify 10 frozen signals x 4 horizons = 40 tests and 100% deterministic event dates & stats."""
    bundle = _make_synthetic_bundle(n_bars=1600, market="US", seed=42)
    res1 = run_per_stock_backtest(bundle)
    res2 = run_per_stock_backtest(bundle)

    assert res1["available"] is True
    assert res1["version"] == TA_BACKTEST_VERSION
    assert res1["round_trip_cost_bps"] == 10.0
    assert len(res1["signals"]) == 10
    assert len(res1["tests"]) == 40
    assert res1["horizons"] == [5, 10, 20, 60]

    # Exact reproducibility of all event dates and bootstrap CIs across runs
    for c1, c2 in zip(res1["tests"], res2["tests"]):
        assert c1["test_id"] == c2["test_id"]
        assert c1["all_event_dates"] == c2["all_event_dates"]
        assert c1["in_sample"]["bootstrap_95_ci_pct"] == c2["in_sample"]["bootstrap_95_ci_pct"]
        assert c1["q_value_fdr"] == c2["q_value_fdr"]
        assert c1["label"] == c2["label"]


def test_zero_lookahead_signal_generation_and_next_open_execution():
    """
    Prove that signal triggers at bar t never depend on bars > t, and that trade
    entry uses Open_tr[t + 1] while exit uses Close_tr[t + h].
    """
    bundle = _make_synthetic_bundle(n_bars=800, market="US", seed=77)
    df_full = bundle.ohlc_tr.copy()
    cutoff = 550

    # Mutate all future bars after `cutoff` drastically (+400% price jump, 10x volume)
    df_mutated = df_full.copy()
    df_mutated.iloc[cutoff + 1 :, df_mutated.columns.get_loc("Open")] *= 5.0
    df_mutated.iloc[cutoff + 1 :, df_mutated.columns.get_loc("High")] *= 5.0
    df_mutated.iloc[cutoff + 1 :, df_mutated.columns.get_loc("Low")] *= 5.0
    df_mutated.iloc[cutoff + 1 :, df_mutated.columns.get_loc("Close")] *= 5.0
    df_mutated.iloc[cutoff + 1 :, df_mutated.columns.get_loc("Volume")] *= 10.0

    masks_full = generate_frozen_signal_masks(df_full)
    masks_mutated = generate_frozen_signal_masks(df_mutated)
    masks_truncated = generate_frozen_signal_masks(df_full.iloc[: cutoff + 1])

    for sig in FROZEN_SIGNAL_CATALOG:
        sig_id = sig["id"]
        np.testing.assert_array_equal(
            masks_full[sig_id][: cutoff + 1],
            masks_mutated[sig_id][: cutoff + 1],
            err_msg=f"Look-ahead violation detected in {sig_id} when future bars were mutated",
        )
        np.testing.assert_array_equal(
            masks_full[sig_id][: cutoff + 1],
            masks_truncated[sig_id],
            err_msg=f"Look-ahead violation detected in {sig_id} when future bars were truncated",
        )

    # Verify trade execution uses Open_tr[t + 1] and Close_tr[t + h]
    bt = run_per_stock_backtest(bundle)
    dates = [str(idx)[:10] for idx in df_full.index]
    open_arr = df_full["Open"].to_numpy(dtype=np.float64)
    close_arr = df_full["Close"].to_numpy(dtype=np.float64)

    checked_trades = 0
    for cell in bt["tests"]:
        h = cell["horizon_days"]
        d = cell["direction"]
        for tr in cell["recent_events"]:
            t = tr["signal_bar_index"]
            assert t + h < len(df_full), "Completed trade must have t + h < N"
            assert tr["signal_date"] == dates[t]
            assert tr["entry_date"] == dates[t + 1]
            assert tr["exit_date"] == dates[t + h]
            assert tr["entry_price_tr"] == round(float(open_arr[t + 1]), 4)
            assert tr["exit_price_tr"] == round(float(close_arr[t + h]), 4)
            expected_gross = d * (((close_arr[t + h] / open_arr[t + 1]) - 1.0) * 100.0)
            assert abs(tr["gross_return_pct"] - expected_gross) < 1e-3
            checked_trades += 1

    assert checked_trades > 20


def test_20_bar_declustering_and_chronological_split():
    """Verify 20-bar cooldown window on all de-clustered triggers and 70/30 IS/OOS partition."""
    raw = [10, 12, 19, 29, 30, 31, 50, 69, 70]
    dec = decluster_event_indices(raw, cooldown_bars=20)
    assert dec == [10, 30, 50, 70]

    bundle = _make_synthetic_bundle(n_bars=1500, market="IN", seed=99)
    bt = run_per_stock_backtest(bundle)
    assert bt["round_trip_cost_bps"] == 30.0  # IN default = 30 bps
    split_idx = bt["sample_split"]["split_bar_index"]
    assert split_idx == int(0.70 * 1500)

    for cell in bt["tests"]:
        cnt = cell["counts"]
        assert cnt["n_raw_total"] >= cnt["n_declustered_total"]
        assert cnt["n_is"] + cnt["n_oos"] == cnt["n_declustered_total"]
        assert cnt["n_raw_is"] + cnt["n_raw_oos"] == cnt["n_raw_total"]

        # Check 20-bar spacing across all recorded recent events
        recent = cell["recent_events"]
        for i in range(1, len(recent)):
            diff = recent[i]["signal_bar_index"] - recent[i - 1]["signal_bar_index"]
            assert diff >= DECLUSTER_COOLDOWN_BARS


def test_gross_vs_net_cost_sensitivity_and_excursions():
    """Verify editable transaction costs shift net returns by exact bps and MAE <= 0 <= MFE."""
    bundle = _make_synthetic_bundle(n_bars=1400, market="US", seed=123)
    bt_0 = run_per_stock_backtest(bundle, round_trip_cost_bps=0.0)
    bt_50 = run_per_stock_backtest(bundle, round_trip_cost_bps=50.0)  # 0.50%

    for c0, c50 in zip(bt_0["tests"], bt_50["tests"]):
        if c0["in_sample"]["n_events"] > 0:
            gross_0 = c0["in_sample"]["mean_gross_return_pct"]
            net_0 = c0["in_sample"]["mean_net_return_pct"]
            net_50 = c50["in_sample"]["mean_net_return_pct"]
            assert abs(gross_0 - net_0) < 1e-4
            assert abs((gross_0 - net_50) - 0.50) < 1e-3

            assert c0["in_sample"]["median_mae_pct"] <= 0.0
            assert c0["in_sample"]["p90_mae_pct"] <= 0.0
            assert c0["in_sample"]["median_mfe_pct"] >= 0.0
            assert c0["in_sample"]["p90_mfe_pct"] >= 0.0

            w_lo, w_hi = c0["in_sample"]["wilson_95_ci_pct"]
            wr = c0["in_sample"]["win_rate_net_pct"]
            assert 0.0 <= w_lo <= wr <= w_hi <= 100.0


def test_bh_fdr_monotonicity_and_bounds():
    """Verify Benjamini-Hochberg q-values satisfy 0 <= p <= q <= 1 and rank monotonicity."""
    rng = np.random.default_rng(7)
    p_vals = rng.uniform(0.0001, 0.95, size=40).tolist()
    p_vals[0] = 0.0005
    p_vals[1] = 0.0020
    q_vals = compute_benjamini_hochberg_qvalues(p_vals)

    assert len(q_vals) == 40
    for p, q in zip(p_vals, q_vals):
        assert 0.0 <= p <= q <= 1.0

    # Check monotonicity: sorting by p_vals must yield non-decreasing q_vals
    order = np.argsort(p_vals)
    sorted_q = np.array(q_vals)[order]
    assert np.all(np.diff(sorted_q) >= -1e-9)


def test_non_promotional_labeling_states_and_forbidden_words():
    """
    Verify:
    - N_IS < 15 -> 'Insufficient evidence'
    - net_excess_is > 0, ci_low > 0, q < 0.10, net_excess_oos > 0 -> 'Historically favourable'
    - OOS sign mismatch or CI containing 0 or q >= 0.10 -> 'No reliable edge'
    - Words 'buy' and 'profitable' never appear anywhere in the payload.
    """
    # 1. Insufficient evidence (N_IS < 15)
    lbl_insuff, _ = classify_backtest_cell(
        n_is=MIN_IS_EVENTS_REQUIRED - 1,
        net_excess_is_pct=4.5,
        ci_low_is_pct=1.8,
        q_value=0.01,
        n_oos=8,
        net_excess_oos_pct=3.1,
    )
    assert lbl_insuff == "Insufficient evidence"

    # 2. Historically favourable (all 4 gates pass)
    lbl_fav, _ = classify_backtest_cell(
        n_is=22,
        net_excess_is_pct=3.2,
        ci_low_is_pct=0.9,
        q_value=0.04,
        n_oos=9,
        net_excess_oos_pct=1.4,
    )
    assert lbl_fav == "Historically favourable"

    # 3. No reliable edge when OOS has opposite sign
    lbl_oos_fail, reason_oos = classify_backtest_cell(
        n_is=22,
        net_excess_is_pct=3.2,
        ci_low_is_pct=0.9,
        q_value=0.04,
        n_oos=9,
        net_excess_oos_pct=-0.4,
    )
    assert lbl_oos_fail == "No reliable edge"
    assert "out-of-sample" in reason_oos

    # 4. No reliable edge when CI includes 0
    lbl_ci_fail, _ = classify_backtest_cell(
        n_is=22,
        net_excess_is_pct=1.2,
        ci_low_is_pct=-0.3,
        q_value=0.04,
        n_oos=9,
        net_excess_oos_pct=0.8,
    )
    assert lbl_ci_fail == "No reliable edge"

    # 5. Short history IPO fixture -> all cells render 'Insufficient evidence'
    short_bundle = _make_synthetic_bundle(n_bars=180, market="IN", seed=55)
    short_bt = run_per_stock_backtest(short_bundle)
    assert short_bt["coverage_eligible_5y"] is False
    assert short_bt["summary_counts"]["insufficient_evidence"] == 40
    for cell in short_bt["tests"]:
        assert cell["label"] == "Insufficient evidence"

    # 6. Compliance check: 'buy' and 'profitable' must NEVER appear in serialized backtest output
    serialized = json.dumps(short_bt).lower()
    assert "buy" not in serialized
    assert "profitable" not in serialized
    assert "survivorship bias" in serialized


def test_get_technical_backtest_endpoint(monkeypatch):
    """Verify GET /api/technical/backtest returns standardized envelope and honors TA_ENABLED."""
    bundle = _make_synthetic_bundle(n_bars=1500, market="US", seed=42)
    monkeypatch.setattr(
        "engine.market_history.fetch_market_history",
        lambda symbol, market="auto", period="10y", force_refresh=False: bundle,
    )

    client = TestClient(main.app)
    resp = client.get("/api/technical/backtest?symbol=AAPL&market=US&cost_bps=15")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["methodology"]["signal_defs"] == TA_BACKTEST_VERSION
    assert body["backtest"]["round_trip_cost_bps"] == 15.0
    assert len(body["backtest"]["tests"]) == 40

    # Verify kill-switch returns 403
    monkeypatch.setenv("TA_ENABLED", "false")
    resp_disabled = client.get("/api/technical/backtest?symbol=AAPL")
    assert resp_disabled.status_code == 403
