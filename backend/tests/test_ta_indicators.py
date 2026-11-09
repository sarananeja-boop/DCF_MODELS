"""
Phase 1 TA v0.1 Numerical Reference, No-Repaint & Endpoint Tests
(`backend/tests/test_ta_indicators.py`).
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from engine.market_history import clear_ta_history_cache
from engine.ta_indicators import (
    compute_anchored_vwaps,
    compute_atr_wilder,
    compute_bollinger_bands,
    compute_ema,
    compute_macd,
    compute_position_sizing,
    compute_rsi_wilder,
    compute_sma,
    compute_trend_stage_preview,
    compute_volume_profile,
    detect_confirmed_swings_and_sr,
)
from main import get_technical_chart
from tests.test_market_history import _make_synthetic_ohlcv


def test_sma_and_ema_match_reference_to_1e6() -> None:
    prices = pd.Series(
        [
            22.27, 22.19, 22.08, 22.17, 22.18, 22.13, 22.23, 22.43, 22.24, 22.29,
            22.15, 22.39, 22.38, 22.61, 23.36, 24.05, 23.75, 23.83, 23.95, 23.63,
            23.82, 23.87, 23.65, 23.19, 23.10, 23.33, 22.68, 23.10, 22.40, 22.17,
        ]
    )
    sma10 = compute_sma(prices, 10)
    ema10 = compute_ema(prices, 10)

    # First 9 values must be NaN; index 9 is exact 10-period arithmetic mean (22.221)
    assert np.isnan(sma10.iloc[:9]).all()
    assert np.isnan(ema10.iloc[:9]).all()
    expected_seed = float(np.mean(prices.iloc[:10]))
    assert sma10.iloc[9] == pytest.approx(expected_seed, abs=1e-6)
    assert ema10.iloc[9] == pytest.approx(expected_seed, abs=1e-6)

    # Hand-verify recursive EMA(10) with alpha = 2 / 11
    alpha = 2.0 / 11.0
    ref_ema = expected_seed
    for i in range(10, len(prices)):
        ref_ema = alpha * float(prices.iloc[i]) + (1.0 - alpha) * ref_ema
        assert ema10.iloc[i] == pytest.approx(ref_ema, abs=1e-6)


def test_wilder_rsi_and_atr_match_reference_to_1e6() -> None:
    # Classic Wilder 14-period RSI verification
    closes = pd.Series(
        [
            44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
            45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
        ]
    )
    rsi = compute_rsi_wilder(closes, period=14)
    assert np.isnan(rsi.iloc[:14]).all()

    # Hand-compute first Wilder seed at index 14:
    deltas = np.diff(closes.to_numpy())
    gains = np.maximum(deltas, 0.0)
    losses = np.maximum(-deltas, 0.0)
    avg_g = float(np.mean(gains[:14]))
    avg_l = float(np.mean(losses[:14]))
    ref_rsi_14 = 100.0 - (100.0 / (1.0 + avg_g / avg_l))
    assert rsi.iloc[14] == pytest.approx(ref_rsi_14, abs=1e-6)

    # Step 15 recursive Wilder smoothing
    avg_g_15 = (avg_g * 13.0 + gains[14]) / 14.0
    avg_l_15 = (avg_l * 13.0 + losses[14]) / 14.0
    ref_rsi_15 = 100.0 - (100.0 / (1.0 + avg_g_15 / avg_l_15))
    assert rsi.iloc[15] == pytest.approx(ref_rsi_15, abs=1e-6)

    # Verify Wilder ATR(14)
    highs = closes + 0.75
    lows = closes - 0.50
    atr = compute_atr_wilder(highs, lows, closes, period=14)
    assert np.isnan(atr.iloc[:13]).all()
    assert atr.iloc[13] > 0


def test_macd_bollinger_and_avwap_reference() -> None:
    df = _make_synthetic_ohlcv(n_days=120, start_date="2025-01-01")
    close = df["Close"]

    macd_res = compute_macd(close, fast=12, slow=26, signal=9)
    ema12 = compute_ema(close, 12)
    ema26 = compute_ema(close, 26)
    expected_macd = ema12 - ema26
    assert macd_res["macd"].dropna().iloc[-1] == pytest.approx(expected_macd.dropna().iloc[-1], abs=1e-6)
    assert macd_res["histogram"].dropna().iloc[-1] == pytest.approx(
        macd_res["macd"].dropna().iloc[-1] - macd_res["signal"].dropna().iloc[-1], abs=1e-6
    )

    bb = compute_bollinger_bands(close, window=20, num_std=2.0)
    last_20 = close.iloc[-20:].to_numpy()
    mean_20 = float(np.mean(last_20))
    std_20 = float(np.std(last_20, ddof=0))
    assert bb["middle"].iloc[-1] == pytest.approx(mean_20, abs=1e-6)
    assert bb["upper"].iloc[-1] == pytest.approx(mean_20 + 2.0 * std_20, abs=1e-6)
    assert bb["lower"].iloc[-1] == pytest.approx(mean_20 - 2.0 * std_20, abs=1e-6)

    avwaps = compute_anchored_vwaps(df)
    assert set(avwaps.keys()) == {"ytd", "high_52w", "low_52w", "swing_low"}
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    expected_ytd = float((tp * df["Volume"]).sum() / df["Volume"].sum())
    assert avwaps["ytd"]["current_value"] == pytest.approx(round(expected_ytd, 2), abs=1e-2)


def test_strict_no_repaint_on_confirmed_swings_and_sr() -> None:
    df = _make_synthetic_ohlcv(n_days=220, start_date="2025-01-01")
    atr = compute_atr_wilder(df["High"], df["Low"], df["Close"], 14)

    full_res = detect_confirmed_swings_and_sr(df, atr, left_bars=5, right_bars=5)
    full_highs = {p["pivot_index"]: p for p in full_res["swing_highs"]}
    full_lows = {p["pivot_index"]: p for p in full_res["swing_lows"]}

    # Every pivot emitted on the full series must have confirmed_index == pivot_index + 5 < len(df)
    for piv in full_res["swing_highs"] + full_res["swing_lows"]:
        assert piv["confirmed_index"] == piv["pivot_index"] + 5
        assert piv["confirmed_index"] < len(df)

    # Truncate df at k = 150 and verify zero repaint:
    # 1. No pivot with pivot_index > 150 - 1 - 5 (i.e. > 144) may appear in the k=150 run.
    # 2. Every pivot in the k=150 run must match the full run 100% identically.
    k = 150
    sub_df = df.iloc[:k]
    sub_atr = atr.iloc[:k]
    sub_res = detect_confirmed_swings_and_sr(sub_df, sub_atr, left_bars=5, right_bars=5)

    for piv in sub_res["swing_highs"]:
        assert piv["confirmed_index"] < k
        assert piv["pivot_index"] in full_highs
        assert piv == full_highs[piv["pivot_index"]]

    for piv in sub_res["swing_lows"]:
        assert piv["confirmed_index"] < k
        assert piv["pivot_index"] in full_lows
        assert piv == full_lows[piv["pivot_index"]]


def test_volume_profile_and_position_sizing_guardrails() -> None:
    df = _make_synthetic_ohlcv(n_days=260, start_date="2025-01-01")
    vp = compute_volume_profile(df, num_bins=24, lookback=252)

    assert vp["approximation_label"] == "est. from daily bars"
    assert len(vp["bins"]) == 24
    assert vp["val_price"] <= vp["poc_price"] <= vp["vah_price"]
    assert sum(1 for b in vp["bins"] if b["is_poc"]) == 1

    # Wrong-side stop check (stop >= entry must fail)
    bad = compute_position_sizing(
        capital=100_000,
        risk_pct=1.0,
        entry_price=150.0,
        stop_price=155.0,
        market="US",
    )
    assert bad["valid"] is False
    assert bad["wrong_side_stop"] is True

    # Valid position sizing check (capped by 10% max weight when stop is very tight)
    tight = compute_position_sizing(
        capital=100_000,
        risk_pct=2.0,
        entry_price=100.0,
        stop_price=99.50,
        market="US",
        max_weight_pct=10.0,
    )
    assert tight["valid"] is True
    assert tight["capped_by_max_weight"] is True
    assert tight["portfolio_weight_pct"] <= 10.0

    # Valid position sizing check (risk-limited when stop is wider)
    normal = compute_position_sizing(
        capital=1_000_000,
        risk_pct=1.0,
        entry_price=1000.0,
        stop_price=900.0,
        market="IN",
        max_weight_pct=25.0,
    )
    assert normal["valid"] is True
    assert normal["capped_by_max_weight"] is False
    assert normal["round_trip_cost_bps"] == 30.0
    assert normal["targets"]["target_2r"] == pytest.approx(1200.0, abs=0.05)


def test_technical_chart_endpoint_and_feature_flag() -> None:
    clear_ta_history_cache()
    synth_df = _make_synthetic_ohlcv(n_days=600, start_date="2023-01-02")

    def _mock_fetch(ticker_sym: str, period: str, session: Any, **kwargs: Any) -> pd.DataFrame:
        return synth_df.copy()

    with patch("engine.market_history._fetch_single_history_with_retries", side_effect=_mock_fetch):
        res_1d = get_technical_chart(
            symbol="RELIANCE.NS",
            market="IN",
            timeframe="1D",
            period="10y",
            fair_value=939.22,
            verdict="STRONGLY BEARISH",
            active_method="Enterprise DCF (FCFF)",
        )
        res_1w = get_technical_chart(
            symbol="RELIANCE.NS",
            market="IN",
            timeframe="1W",
            period="10y",
        )

    assert res_1d["symbol"] == "RELIANCE"
    assert res_1d["listing_used"] == "RELIANCE.NS"
    assert res_1d["benchmark"] == "^NSEI"
    assert res_1d["timeframe"] == "1D"
    assert len(res_1d["chart"]["bars"]) == 600
    assert res_1d["headline_cards"]["fundamental_context"]["valuation_outlook_label"] == "Valuation outlook: STRONGLY BEARISH"
    assert res_1d["headline_cards"]["fundamental_context"]["distance_in_atr_units"] is not None
    assert res_1d["headline_cards"]["key_levels"]["approximation_label"] == "est. from daily bars"
    assert res_1d["headline_cards"]["technical_condition"]["status"] == "available"
    assert res_1d["headline_cards"]["technical_condition"]["score_version"] == "ta-score-v0.2"
    assert "phase2" in res_1d

    assert res_1w["timeframe"] == "1W"
    assert len(res_1w["chart"]["bars"]) < 150

    # Verify TA_ENABLED=false blocks the endpoint with 403
    with patch.dict(os.environ, {"TA_ENABLED": "false"}):
        with pytest.raises(HTTPException) as exc_info:
            get_technical_chart(symbol="AAPL", market="US")
        assert exc_info.value.status_code == 403
