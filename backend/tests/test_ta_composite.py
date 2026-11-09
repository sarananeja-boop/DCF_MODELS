"""
Unit & Integration Tests for Phase 2 (`backend/engine/ta_composite.py`):
- Two-stage composite score traceability (Stage A s_j -> Stage B P_k -> S_D / S_W / S_M -> S_MTF)
- Coverage gating on short-history IPO fixture (< 200 daily bars -> "Score unavailable (coverage X%)")
- Decision D1 label prefix enforcement ("Technical condition: Bullish | Neutral | Bearish")
- 3x4 Classification Matrix row alignment with live Valuation Outlook verdict
- Separate Statistical Regime Diagnostics:
    * Hurst DFA-1 (504 bars, scales 10-126, block-bootstrap CI, Indeterminate when CI spans 0.50)
    * Lo-MacKinlay VR(2, 5, 10, 20) with heteroskedasticity-robust z* + Chow-Denning joint test
    * Yang-Zhang 20D/60D volatility with % annualized units and 1Y/5Y percentiles
    * Mansfield RS + rolling 63D alpha/beta + Dow HH/HL + Wyckoff VSA tags
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from engine.market_history import clear_ta_history_cache, fetch_market_history
from engine.ta_composite import (
    PILLAR_WEIGHTS,
    TA_SCORE_VERSION,
    build_classification_matrix,
    build_ta_phase2_payload,
    compute_hurst_dfa1,
    compute_lo_mackinlay_vr,
    compute_yang_zhang_volatility,
)
from main import get_technical_score


def _make_synthetic_ohlcv(
    n_days: int = 800,
    start_date: str = "2021-01-04",
    drift: float = 0.0008,
    vol: float = 0.014,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start_date, periods=n_days)
    rets = drift + rng.normal(0.0, vol, size=n_days)
    close = 100.0 * np.exp(np.cumsum(rets))
    high = close * (1.0 + np.abs(rng.normal(0.006, 0.004, size=n_days)))
    low = close * (1.0 - np.abs(rng.normal(0.006, 0.004, size=n_days)))
    open_ = low + (high - low) * rng.uniform(0.25, 0.75, size=n_days)
    volume = rng.integers(800_000, 4_000_000, size=n_days).astype(float)
    dividends = np.zeros(n_days, dtype=float)
    splits = np.zeros(n_days, dtype=float)
    if n_days >= 300:
        dividends[250] = 1.50
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
            "Dividends": dividends,
            "Stock Splits": splits,
        },
        index=dates,
    )


def test_stage_a_to_stage_b_score_traceability() -> None:
    """
    Verify that every indicator in the 16-row Indicator Matrix traces back to
    raw inputs, maps into s_j in [-1, +1], aggregates into P_k with exact pillar
    weights, and combines into S_D / S_W / S_M and S_MTF = 0.50*D + 0.35*W + 0.15*M.
    """
    clear_ta_history_cache()
    stock_df = _make_synthetic_ohlcv(n_days=900, drift=0.0012, seed=7)
    bench_df = _make_synthetic_ohlcv(n_days=900, drift=0.0004, seed=19)

    def _mock_fetch(ticker_sym: str, period: str, session: Any, **kwargs: Any) -> pd.DataFrame:
        if ticker_sym.startswith("^"):
            return bench_df.copy()
        return stock_df.copy()

    with patch("engine.market_history._fetch_single_history_with_retries", side_effect=_mock_fetch):
        bundle = fetch_market_history("AAPL", market="US", period="10y")

    p2 = build_ta_phase2_payload(bundle, fair_value=180.0, verdict="BULLISH")
    cs = p2["composite_score"]

    assert cs["available"] is True
    assert cs["score_version"] == TA_SCORE_VERSION
    assert cs["coverage_pct"] == 100
    assert cs["all_pillars_pass_60"] is True

    # Verify all 16 indicators are present and s_d, s_w, s_m, s_mtf are within [-1, +1]
    rows = p2["indicator_matrix"]
    assert len(rows) == 16
    for r in rows:
        assert r["s_d"] is not None
        assert -1.0 <= r["s_d"] <= 1.0
        assert -1.0 <= r["s_mtf"] <= 1.0
        assert r["raw_d"] != "—"

    # Recompute S_D directly from P_k and PILLAR_WEIGHTS to verify Stage B formula
    pillars_d = cs["pillars_d"]
    recomputed_s_d = 100.0 * sum(
        PILLAR_WEIGHTS[k] * ((pillars_d[k]["p_k"] + 1.0) / 2.0) for k in PILLAR_WEIGHTS
    )
    assert cs["score_d"] == pytest.approx(round(recomputed_s_d, 1), abs=0.15)

    # Recompute S_MTF = 0.50*D + 0.35*W + 0.15*M
    expected_mtf = round(
        0.50 * cs["score_d"] + 0.35 * cs["score_w"] + 0.15 * cs["score_m"], 1
    )
    assert cs["score_mtf"] == pytest.approx(expected_mtf, abs=0.15)

    # Decision D1 prefix check
    assert cs["condition_label"].startswith("Technical condition: ")
    if cs["score_mtf"] >= 60.0:
        assert cs["condition_label"] == "Technical condition: Bullish"
    elif cs["score_mtf"] <= 40.0:
        assert cs["condition_label"] == "Technical condition: Bearish"
    else:
        assert cs["condition_label"] == "Technical condition: Neutral"


def test_ipo_short_history_coverage_gate() -> None:
    """
    Verify coverage gating on a short-history IPO fixture (120 daily bars):
    long-term trend/RS/structure pillars lack >= 60% weight or total < 70%,
    so the composite score returns available=False and 'Score unavailable (coverage X%)'.
    """
    clear_ta_history_cache()
    ipo_df = _make_synthetic_ohlcv(n_days=120, start_date="2025-06-01", seed=99)

    def _mock_fetch(ticker_sym: str, period: str, session: Any, **kwargs: Any) -> pd.DataFrame:
        return ipo_df.copy()

    with patch("engine.market_history._fetch_single_history_with_retries", side_effect=_mock_fetch):
        bundle = fetch_market_history("NEWIPO", market="US", period="10y")

    p2 = build_ta_phase2_payload(bundle, fair_value=95.0, verdict="NEUTRAL")
    cs = p2["composite_score"]

    assert cs["available"] is False
    assert cs["score_mtf"] is None
    assert cs["condition_label"].startswith("Score unavailable (coverage ")
    assert cs["coverage_pct"] < 70


def test_classification_matrix_matches_live_verdict() -> None:
    """
    Verify that the 3x4 Classification Matrix active row always matches the
    live Fundamental Valuation Outlook verdict and greys out the unreliable row
    when valuation is normal.
    """
    m_bull = build_classification_matrix("STRONGLY BULLISH", weinstein_stage=4)
    assert m_bull["active_row"] == "bullish"
    assert m_bull["active_stage"] == 4
    assert "Stage 4 Declining" in m_bull["active_cell"]["title"]
    assert "Value Trap" in m_bull["active_cell"]["subtitle"]
    unrel_row = next(r for r in m_bull["rows"] if r["id"] == "unreliable")
    assert unrel_row["is_greyed"] is True

    m_bear = build_classification_matrix("BEARISH", weinstein_stage=2)
    assert m_bear["active_row"] == "bearish"
    assert m_bear["active_stage"] == 2
    assert "Stage 2 Advancing" in m_bear["active_cell"]["title"]

    m_neut = build_classification_matrix("NEUTRAL", weinstein_stage=1)
    assert m_neut["active_row"] == "neutral"
    assert m_neut["active_stage"] == 1

    m_dist = build_classification_matrix("DCF UNRELIABLE / DISTRESSED", weinstein_stage=4)
    assert m_dist["active_row"] == "unreliable"
    unrel_row_dist = next(r for r in m_dist["rows"] if r["id"] == "unreliable")
    assert unrel_row_dist["is_greyed"] is False


def test_statistical_regime_diagnostics_hurst_vr_yang_zhang() -> None:
    """
    Verify Hurst DFA-1 (504 bars, scales 10-126, block-bootstrap CI),
    Lo-MacKinlay VR(2,5,10,20) + Chow-Denning joint test, and Yang-Zhang 20D/60D vol.
    """
    # 1. Strongly autocorrelated / persistent series should have H > 0.50 and VR > 1
    rng = np.random.default_rng(123)
    eps = rng.normal(0.0, 0.01, size=700)
    ar_rets = np.zeros(700)
    for i in range(1, 700):
        ar_rets[i] = 0.45 * ar_rets[i - 1] + eps[i]
    close_trend = 100.0 * np.exp(np.cumsum(ar_rets))

    h_res = compute_hurst_dfa1(close_trend, window=504)
    assert h_res["available"] is True
    assert h_res["hurst"] > 0.55
    assert h_res["scales_range"] == [10, 126]
    assert len(h_res["ci_95"]) == 2

    vr_res = compute_lo_mackinlay_vr(close_trend, window=504)
    assert vr_res["available"] is True
    assert [p["q"] for p in vr_res["profiles"]] == [2, 5, 10, 20]
    assert vr_res["profiles"][0]["vr"] > 1.15
    assert vr_res["rejects_random_walk_95"] is True

    # 2. Pure random walk whose bootstrap CI spans 0.50 should report Indeterminate
    rw_rets = rng.normal(0.0, 0.012, size=600)
    close_rw = 100.0 * np.exp(np.cumsum(rw_rets))
    h_rw = compute_hurst_dfa1(close_rw, window=504)
    assert h_rw["available"] is True
    if h_rw["ci_spans_050"]:
        assert "Indeterminate" in h_rw["regime"]

    # 3. Yang-Zhang volatility with 1Y and 5Y percentiles
    df_long = _make_synthetic_ohlcv(n_days=1400, seed=55)
    yz = compute_yang_zhang_volatility(
        df_long["Open"].to_numpy(),
        df_long["High"].to_numpy(),
        df_long["Low"].to_numpy(),
        df_long["Close"].to_numpy(),
    )
    assert yz["available"] is True
    assert yz["units"] == "% annualized"
    assert yz["yz_20d_pct"] > 0
    assert yz["yz_60d_pct"] > 0
    assert 0.0 <= yz["pct_rank_1y"] <= 100.0
    assert 0.0 <= yz["pct_rank_5y"] <= 100.0


def test_get_technical_score_endpoint() -> None:
    clear_ta_history_cache()
    synth_df = _make_synthetic_ohlcv(n_days=750, start_date="2022-01-03", seed=33)

    def _mock_fetch(ticker_sym: str, period: str, session: Any, **kwargs: Any) -> pd.DataFrame:
        return synth_df.copy()

    with patch("engine.market_history._fetch_single_history_with_retries", side_effect=_mock_fetch):
        resp = get_technical_score(
            symbol="TCS.NS",
            market="IN",
            period="10y",
            fair_value=3100.0,
            verdict="BEARISH",
        )

    assert resp["symbol"] == "TCS"
    assert resp["methodology"]["score_model"] == TA_SCORE_VERSION
    assert resp["composite_score"]["available"] is True
    assert resp["classification_matrix"]["active_row"] == "bearish"
    assert len(resp["indicator_matrix"]) == 16
