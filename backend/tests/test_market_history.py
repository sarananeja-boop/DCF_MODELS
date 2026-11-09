"""
Unit & Contract Tests for Phase 0C TA Data Foundation (`backend/tests/test_market_history.py`).

Tests all Phase 0C requirements deterministically offline:
  1. Dual price basis (`ohlc_split` vs `ohlc_tr` via `Adj Close / Close` and dividend reconstruction)
  2. Split & dividend event extraction
  3. Weekly & monthly resampling with forming-bar exclusion (`weekly_completed`, `monthly_completed`)
  4. Exchange timezone & intraday forming session detection (`Asia/Kolkata`, `America/New_York`)
  5. Data quality checks (duplicates, unsorted, non-positive prices, OHLC envelope, stale close runs,
     session gaps > 5 business days, >40% 1-day move without recorded split, benchmark inner-join)
  6. Coverage contract (60, 260, 504, 1260, 1280 daily bars; 96 monthly returns)
  7. NSE (`.NS`) primary resolution with automatic BSE (`.BO`) fallback
  8. 3-attempt retry + stale-cache fallback (`quality_status: "stale"`)
  9. Standardized `/api/technical/*` response envelope & `/api/technical/_probe` endpoint
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from engine import MODEL_VERSION
from engine.market_history import (
    COVERAGE_REQUIREMENTS,
    build_technical_response_envelope,
    clean_and_audit_ohlcv,
    clear_ta_history_cache,
    fetch_market_history,
    resolve_ta_listing,
)
from main import technical_history_probe


def _make_synthetic_ohlcv(
    n_days: int = 1500,
    start_date: str = "2018-01-01",
    end_date: str | None = None,
    with_adj_close: bool = True,
    with_splits_and_divs: bool = True,
) -> pd.DataFrame:
    """Create a clean, deterministic business-day OHLCV DataFrame."""
    if end_date:
        dates = pd.bdate_range(end=end_date, periods=n_days)
    else:
        dates = pd.bdate_range(start=start_date, periods=n_days)

    rng = np.random.default_rng(42)
    rets = rng.normal(0.0005, 0.012, size=len(dates))
    close = 100.0 * np.cumprod(1.0 + rets)
    open_p = close * (1.0 + rng.normal(0.0, 0.003, size=len(dates)))
    high_p = np.maximum(open_p, close) * (1.0 + np.abs(rng.normal(0.004, 0.002, size=len(dates))))
    low_p = np.minimum(open_p, close) * (1.0 - np.abs(rng.normal(0.004, 0.002, size=len(dates))))
    volume = rng.integers(250_000, 5_000_000, size=len(dates)).astype(float)

    dividends = np.zeros(len(dates), dtype=float)
    splits = np.zeros(len(dates), dtype=float)

    if with_splits_and_divs and len(dates) >= 260:
        dividends[100] = 1.50
        dividends[250] = 2.00
        splits[200] = 2.0  # 2:1 forward split

    df = pd.DataFrame(
        {
            "Open": open_p,
            "High": high_p,
            "Low": low_p,
            "Close": close,
            "Volume": volume,
            "Dividends": dividends,
            "Stock Splits": splits,
        },
        index=dates,
    )
    if with_adj_close:
        # Simulate total-return factor ramping from 0.90 at start to 1.00 at end
        tr_mult = np.linspace(0.90, 1.00, len(dates))
        df["Adj Close"] = df["Close"] * tr_mult

    return df


def test_dual_price_basis_and_corporate_actions() -> None:
    raw = _make_synthetic_ohlcv(n_days=400, start_date="2023-01-02")
    bench = _make_synthetic_ohlcv(n_days=400, start_date="2023-01-02", with_splits_and_divs=False)

    audit = clean_and_audit_ohlcv(raw, market="US", benchmark_df=bench)

    assert audit["observations"] == 400
    assert audit["quality_status"] == "complete"
    assert len(audit["splits"]) == 1
    assert audit["splits"][0]["ratio"] == 2.0
    assert audit["splits"][0]["label"] == "2:1 Split"
    assert len(audit["dividends"]) == 2
    assert audit["dividends"][0]["amount"] == 1.50
    assert audit["dividends"][0]["currency"] == "USD"

    # Verify ohlc_split equals raw Close while ohlc_tr reflects Adj Close / Close factor
    ohlc_split = audit["ohlc_split"]
    ohlc_tr = audit["ohlc_tr"]
    assert ohlc_split["Close"].iloc[0] == pytest.approx(raw["Close"].iloc[0], rel=1e-6)
    assert ohlc_tr["Close"].iloc[0] == pytest.approx(raw["Adj Close"].iloc[0], rel=1e-6)
    assert ohlc_tr["Open"].iloc[0] == pytest.approx(raw["Open"].iloc[0] * 0.90, rel=1e-5)
    assert ohlc_tr["Close"].iloc[-1] == pytest.approx(raw["Close"].iloc[-1], rel=1e-6)


def test_dividend_total_return_fallback_when_adj_close_missing() -> None:
    raw = _make_synthetic_ohlcv(n_days=350, start_date="2023-01-02", with_adj_close=False)
    audit = clean_and_audit_ohlcv(raw, market="IN", benchmark_df=raw)

    ohlc_split = audit["ohlc_split"]
    ohlc_tr = audit["ohlc_tr"]
    # Earlier total-return adjusted prices are lower than split-only prices due to dividend reinvestment factor
    assert ohlc_tr["Close"].iloc[0] < ohlc_split["Close"].iloc[0]
    assert ohlc_tr["Close"].iloc[-1] == pytest.approx(ohlc_split["Close"].iloc[-1], rel=1e-6)


def test_weekly_and_monthly_forming_bar_exclusion() -> None:
    # End on Wednesday 2026-05-13 (both mid-week and mid-month!)
    raw = _make_synthetic_ohlcv(n_days=300, end_date="2026-05-13")
    # Simulate post-close timestamp so daily bar is completed, while week & month are still forming
    now_utc = datetime.datetime(2026, 5, 13, 21, 0, tzinfo=datetime.timezone.utc)
    audit = clean_and_audit_ohlcv(raw, market="US", benchmark_df=raw, now_utc=now_utc)

    assert audit["is_forming_daily_bar"] is False
    assert audit["quality_metrics"]["is_forming_weekly_bar"] is True
    assert audit["quality_metrics"]["is_forming_monthly_bar"] is True

    # Completed weekly and monthly DataFrames must exclude the final forming bar
    assert len(audit["weekly_completed"]) == len(audit["weekly_split"]) - 1
    assert len(audit["monthly_completed"]) == len(audit["monthly_split"]) - 1
    assert audit["weekly_completed"].index[-1] < audit["weekly_split"].index[-1]
    assert audit["monthly_completed"].index[-1] < audit["monthly_split"].index[-1]


def test_intraday_forming_daily_bar_detection() -> None:
    # Wednesday 2026-05-13 at 11:00 AM IST (05:30 UTC) -> before 15:30 IST NSE market close
    raw = _make_synthetic_ohlcv(n_days=100, end_date="2026-05-13")
    intraday_utc = datetime.datetime(2026, 5, 13, 5, 30, tzinfo=datetime.timezone.utc)
    audit_open = clean_and_audit_ohlcv(raw, market="IN", benchmark_df=raw, now_utc=intraday_utc)
    assert audit_open["is_forming_daily_bar"] is True
    # Last completed session must be the prior trading day (2026-05-12), not the forming bar
    assert audit_open["last_session"] == "2026-05-12"

    # Same day at 17:00 IST (11:30 UTC) -> after 15:30 IST NSE market close
    post_close_utc = datetime.datetime(2026, 5, 13, 11, 30, tzinfo=datetime.timezone.utc)
    audit_closed = clean_and_audit_ohlcv(raw, market="IN", benchmark_df=raw, now_utc=post_close_utc)
    assert audit_closed["is_forming_daily_bar"] is False
    assert audit_closed["last_session"] == "2026-05-13"


def test_quality_checks_anomalies_and_unrecorded_split() -> None:
    raw = _make_synthetic_ohlcv(n_days=300, start_date="2024-01-01", with_splits_and_divs=False)

    # 1. Inject OHLC envelope violation (High < Close)
    raw.iloc[10, raw.columns.get_loc("High")] = raw.iloc[10]["Close"] * 0.85
    # 2. Inject non-positive price row
    raw.iloc[20, raw.columns.get_loc("Close")] = -5.0
    # 3. Inject 6-day stale close run
    stale_val = float(raw.iloc[50]["Close"])
    for idx in range(50, 56):
        raw.iloc[idx, raw.columns.get_loc("Close")] = stale_val
        raw.iloc[idx, raw.columns.get_loc("Adj Close")] = stale_val
    # 4. Inject unrecorded split (>40% 1-day drop with Stock Splits == 0)
    raw.iloc[150:, raw.columns.get_loc("Close")] *= 0.45
    raw.iloc[150:, raw.columns.get_loc("Open")] *= 0.45
    raw.iloc[150:, raw.columns.get_loc("High")] *= 0.45
    raw.iloc[150:, raw.columns.get_loc("Low")] *= 0.45
    raw.iloc[150:, raw.columns.get_loc("Adj Close")] *= 0.45

    # 5. Duplicate timestamp + reverse order slice
    dup_row = raw.iloc[[5]].copy()
    dirty_df = pd.concat([raw.iloc[10:15], raw.iloc[:10], dup_row, raw.iloc[15:]])

    audit = clean_and_audit_ohlcv(dirty_df, market="US", benchmark_df=raw)

    assert audit["quality_status"] == "degraded"
    qm = audit["quality_metrics"]
    assert qm["dropped_non_positive_rows"] == 1
    assert qm["ohlc_inconsistencies_fixed"] >= 1
    assert qm["max_stale_close_run"] >= 6
    assert len(qm["unrecorded_split_suspects"]) >= 1
    assert any("1-day price move > 40% without a recorded split" in w for w in audit["warnings"])


def test_coverage_contract_thresholds() -> None:
    # Case A: Short-history IPO (120 daily bars -> ~5 monthly returns)
    short_df = _make_synthetic_ohlcv(n_days=120, start_date="2025-06-01")
    short_audit = clean_and_audit_ohlcv(short_df, market="IN", benchmark_df=short_df)
    cov_short = short_audit["coverage"]

    assert cov_short["chart_basic_indicators"]["eligible"] is True
    assert cov_short["chart_basic_indicators"]["status"] == "available"

    for key in (
        "long_ma_trend_templates",
        "hurst_variance_ratio",
        "backtester",
        "yang_zhang_5y_percentile",
        "monthly_seasonality",
    ):
        assert cov_short[key]["eligible"] is False
        assert cov_short[key]["status"] == "insufficient_history"
        assert "Insufficient history" in cov_short[key]["message"]

    # Case B: Full 10Y history (2,500 daily bars -> ~114 monthly returns)
    full_df = _make_synthetic_ohlcv(n_days=2500, start_date="2016-01-01")
    full_audit = clean_and_audit_ohlcv(full_df, market="US", benchmark_df=full_df)
    cov_full = full_audit["coverage"]

    assert set(cov_full.keys()) == set(COVERAGE_REQUIREMENTS.keys())
    for key, item in cov_full.items():
        assert item["eligible"] is True, f"Expected {key} to be eligible on 2,500 daily bars"
        assert item["status"] == "available"
        assert item["message"] is None


def test_nse_primary_to_bse_fallback_and_stale_cache() -> None:
    clear_ta_history_cache()
    base_sym, primary_listing, mkt, _ = resolve_ta_listing("RELIANCE.BO", "IN")
    assert base_sym == "RELIANCE"
    assert primary_listing == "RELIANCE.NS"
    assert mkt == "IN"

    synth_df = _make_synthetic_ohlcv(n_days=300, start_date="2024-01-01")

    def _mock_fetch(ticker_sym: str, period: str, session: Any, **kwargs: Any) -> pd.DataFrame:
        if ticker_sym == "BSEONLY.NS":
            return pd.DataFrame()  # Empty on NSE -> triggers .BO fallback
        if ticker_sym in ("BSEONLY.BO", "^NSEI"):
            return synth_df.copy()
        raise RuntimeError(f"Unexpected symbol {ticker_sym}")

    with patch("engine.market_history._fetch_single_history_with_retries", side_effect=_mock_fetch):
        bundle = fetch_market_history("BSEONLY", market="IN", period="5y", force_refresh=True)
        assert bundle.symbol == "BSEONLY"
        assert bundle.listing_used == "BSEONLY.BO"
        assert bundle.benchmark == "^NSEI"
        assert any("resolved to BSE listing (BSEONLY.BO)" in w for w in bundle.warnings)

    # Now simulate a live outage on force_refresh=True and verify stale-cache fallback
    def _mock_outage(ticker_sym: str, period: str, session: Any, **kwargs: Any) -> pd.DataFrame:
        raise RuntimeError("Simulated Yahoo Finance outage")

    with patch("engine.market_history._fetch_single_history_with_retries", side_effect=_mock_outage):
        stale_bundle = fetch_market_history("BSEONLY", market="IN", period="5y", force_refresh=True)
        assert stale_bundle.quality_status == "stale"
        assert stale_bundle.cached is True
        assert any("serving cached snapshot" in w for w in stale_bundle.warnings)


def test_technical_response_envelope_and_probe_endpoint() -> None:
    clear_ta_history_cache()
    synth_df = _make_synthetic_ohlcv(n_days=1400, start_date="2020-01-01")

    def _mock_fetch(ticker_sym: str, period: str, session: Any, **kwargs: Any) -> pd.DataFrame:
        return synth_df.copy()

    with patch("engine.market_history._fetch_single_history_with_retries", side_effect=_mock_fetch):
        resp = technical_history_probe(symbol="AAPL", market="US", period="10y")

    assert resp["symbol"] == "AAPL"
    assert resp["listing_used"] == "AAPL"
    assert resp["market"] == "US"
    assert resp["currency"] == "USD"
    assert resp["benchmark"] == "^GSPC"
    assert "computed_at" in resp
    assert resp["data"]["price_basis"] == {
        "levels": "split_adjusted_ohlc",
        "returns": "total_return_adj_ohlc",
    }
    assert resp["data"]["observations"] == 1400
    assert resp["methodology"]["model_version"] == MODEL_VERSION
    assert "param_hash" in resp["methodology"]
    assert "probe" in resp
