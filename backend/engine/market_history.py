"""
Technical Analysis Data Foundation (`backend/engine/market_history.py`)
=======================================================================

Provides lazy, isolated OHLCV + benchmark fetching, dual price-basis construction
(split-adjusted `ohlc_split` for chart levels/stops and total-return `ohlc_tr` for
returns/backtests/volatility/seasonality), weekly/monthly resampling with forming-bar
exclusion, data-quality auditing, coverage gating, and standardized response metadata
for `/api/technical/*` endpoints.

Design Invariant:
  - Strictly decoupled from `/api/analyze` and `fetch_stock_data()` so the DCF
    valuation pipeline is never slowed down or altered by TA history fetches.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import datetime
import hashlib
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from . import MODEL_VERSION
from .data_layer import get_yf_session
from .ticker_universe import resolve_ticker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & Coverage Contract
# ---------------------------------------------------------------------------

TA_ENGINE_VERSION = f"ta-foundation-{MODEL_VERSION}"

EXCHANGE_CONFIG: Dict[str, Dict[str, Any]] = {
    "IN": {
        "timezone": "Asia/Kolkata",
        "benchmark": "^NSEI",
        "currency": "INR",
        "currency_symbol": "₹",
        "close_hour": 15,
        "close_minute": 30,
        "primary_suffix": ".NS",
        "fallback_suffix": ".BO",
    },
    "US": {
        "timezone": "America/New_York",
        "benchmark": "^GSPC",
        "currency": "USD",
        "currency_symbol": "$",
        "close_hour": 16,
        "close_minute": 0,
        "primary_suffix": "",
        "fallback_suffix": "",
    },
}

# Minimum observations required per TA capability (Phase 0C Coverage Contract)
COVERAGE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "chart_basic_indicators": {
        "label": "Chart + SMA/EMA <= 50, RSI, MACD, ATR, Bollinger",
        "min_obs": 60,
        "unit": "daily_bars",
    },
    "long_ma_trend_templates": {
        "label": "SMA 150/200, Weinstein Stage & Minervini Trend Template",
        "min_obs": 260,
        "unit": "daily_bars",
    },
    "hurst_variance_ratio": {
        "label": "Hurst Exponent & Lo-MacKinlay Variance Ratio",
        "min_obs": 504,
        "unit": "daily_bars",
    },
    "backtester": {
        "label": "Walk-Forward Signal Backtester",
        "min_obs": 1260,
        "unit": "daily_bars",
    },
    "yang_zhang_5y_percentile": {
        "label": "Yang-Zhang 5Y Realized Volatility Percentile",
        "min_obs": 1280,
        "unit": "daily_bars",
    },
    "monthly_seasonality": {
        "label": "Monthly Seasonality Matrix (8+ Years)",
        "min_obs": 96,
        "unit": "monthly_returns",
    },
}

DEFAULT_PROBE_TICKERS: List[Tuple[str, str]] = [
    ("RELIANCE.NS", "IN"),
    ("TCS.NS", "IN"),
    ("HDFCBANK.NS", "IN"),
    ("INFY.NS", "IN"),
    ("CESC.NS", "IN"),
    ("AAPL", "US"),
    ("MSFT", "US"),
    ("NVDA", "US"),
    ("XOM", "US"),
    ("NVO", "US"),
]

# In-memory cache for TA market history
# Key: f"{listing_used}:{market}:{period}" -> (MarketHistoryBundle, timestamp_float)
_TA_HISTORY_CACHE: Dict[str, Tuple["MarketHistoryBundle", float]] = {}
_TA_CACHE_FRESH_TTL_SECONDS: int = 900       # 15 minutes fresh
_TA_CACHE_STALE_MAX_SECONDS: int = 86400     # 24 hours stale fallback retention
_TA_CACHE_MAX_ENTRIES: int = 60              # Bounded memory footprint (~12 MB max on Render)
_TA_BENCHMARK_CACHE: Dict[str, Tuple[pd.DataFrame, float]] = {}
_TA_BENCHMARK_TTL_SECONDS: int = 3600        # 1 hour fresh benchmark cache
_TA_CACHE_META_LOCK = threading.Lock()
_TA_INFLIGHT_LOCKS: Dict[str, threading.Lock] = {}
_TA_BENCHMARK_LOCK = threading.Lock()


@dataclass
class MarketHistoryBundle:
    """Container for cleaned daily/weekly/monthly OHLCV, corporate actions, and quality metadata."""

    symbol: str
    listing_used: str
    market: str
    currency: str
    currency_symbol: str
    benchmark: str
    period_requested: str
    provider: str
    as_of: str
    computed_at: str
    last_session: Optional[str]
    exchange_timezone: str
    is_forming_daily_bar: bool
    history_start: Optional[str]
    history_end: Optional[str]
    observations: int
    weekly_observations: int
    monthly_observations: int
    monthly_return_observations: int
    benchmark_observations: int
    benchmark_dropped_rows: int
    quality_status: str  # "complete" | "partial" | "stale" | "degraded"
    warnings: List[str] = field(default_factory=list)
    quality_metrics: Dict[str, Any] = field(default_factory=dict)
    coverage: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    ohlc_split: pd.DataFrame = field(default_factory=pd.DataFrame)
    ohlc_tr: pd.DataFrame = field(default_factory=pd.DataFrame)
    weekly_split: pd.DataFrame = field(default_factory=pd.DataFrame)
    weekly_completed: pd.DataFrame = field(default_factory=pd.DataFrame)
    monthly_split: pd.DataFrame = field(default_factory=pd.DataFrame)
    monthly_completed: pd.DataFrame = field(default_factory=pd.DataFrame)
    monthly_tr_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    benchmark_close: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    aligned_returns: pd.DataFrame = field(default_factory=pd.DataFrame)
    splits: List[Dict[str, Any]] = field(default_factory=list)
    dividends: List[Dict[str, Any]] = field(default_factory=list)
    cached: bool = False
    fetch_latency_ms: float = 0.0


def clear_ta_history_cache() -> None:
    """Clear all cached TA market history and benchmark series."""
    _TA_HISTORY_CACHE.clear()
    _TA_BENCHMARK_CACHE.clear()


# ---------------------------------------------------------------------------
# Ticker & Listing Resolution (NSE Primary -> BSE Fallback)
# ---------------------------------------------------------------------------

def resolve_ta_listing(symbol: str, market: str = "auto") -> Tuple[str, str, str, Optional[str]]:
    """
    Resolve raw ticker symbol into (base_symbol, primary_listing, resolved_market, redirect_note).

    For Indian equities (`IN`), always prefers `.NS` (NSE primary listing) even if
    a bare symbol or `.BO` was passed, and provides `.BO` as the automatic fallback
    candidate when `.NS` has no data.
    """
    raw = (symbol or "").strip().upper()
    if not raw:
        raise ValueError("Ticker symbol cannot be empty.")

    mkt = (market or "auto").strip().upper()
    if mkt == "AUTO":
        if raw.endswith(".NS") or raw.endswith(".BO"):
            mkt = "IN"
        else:
            mkt = "US"

    resolved_sym, resolved_mkt, redirect_note = resolve_ticker(raw, mkt)
    mkt = resolved_mkt.upper()
    base_sym = resolved_sym.replace(".NS", "").replace(".BO", "").strip().upper()

    if mkt == "IN":
        # If caller explicitly requested a BSE-only code that is numeric or .BO, we still
        # try .NS first unless base_sym is purely numeric BSE scrip code.
        if base_sym.isdigit():
            primary_listing = f"{base_sym}.BO"
        else:
            primary_listing = f"{base_sym}.NS"
    else:
        primary_listing = base_sym

    return base_sym, primary_listing, mkt, redirect_note


# ---------------------------------------------------------------------------
# Exchange Calendar & Timestamp Normalization
# ---------------------------------------------------------------------------

def _normalize_index_to_exchange_dates(
    df: pd.DataFrame, tz_name: str
) -> Tuple[pd.DataFrame, int]:
    """
    Convert a DataFrame's DatetimeIndex to timezone-naive exchange-local dates (`YYYY-MM-DD`),
    sort ascending, and deduplicate timestamps (keeping the last observation per date).

    Returns (cleaned_df, duplicate_or_unsorted_count).
    """
    if df is None or df.empty:
        return pd.DataFrame(), 0

    work = df.copy()
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        try:
            idx = idx.tz_convert(ZoneInfo(tz_name)).tz_localize(None)
        except Exception:
            idx = idx.tz_localize(None)
    work.index = idx.normalize()

    was_unsorted = int(not work.index.is_monotonic_increasing)
    dup_count = int(work.index.duplicated().sum())
    if was_unsorted:
        work = work.sort_index()
    if dup_count > 0:
        work = work[~work.index.duplicated(keep="last")]

    return work, dup_count + was_unsorted


def _is_daily_bar_forming(last_bar_date: pd.Timestamp, mkt: str, now_utc: Optional[datetime.datetime] = None) -> bool:
    """
    Determine whether `last_bar_date` represents an intraday forming session
    (i.e. today's session in exchange-local time before regular market close).
    """
    cfg = EXCHANGE_CONFIG.get(mkt, EXCHANGE_CONFIG["US"])
    tz = ZoneInfo(cfg["timezone"])
    now_dt = (now_utc or datetime.datetime.now(datetime.timezone.utc)).astimezone(tz)

    if last_bar_date.date() != now_dt.date():
        return False
    # Check if weekday (Mon=0 .. Fri=4) and before close
    if now_dt.weekday() >= 5:
        return False
    close_time = datetime.time(cfg["close_hour"], cfg["close_minute"])
    return now_dt.time() < close_time


# ---------------------------------------------------------------------------
# Dual-Basis OHLCV Cleaning, Quality Checks & Resampling
# ---------------------------------------------------------------------------

def clean_and_audit_ohlcv(
    raw_df: pd.DataFrame,
    market: str,
    benchmark_df: Optional[pd.DataFrame] = None,
    now_utc: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """
    Clean raw daily history DataFrame into `ohlc_split` and `ohlc_tr`, extract splits
    and dividends, resample weekly/monthly bars (with forming-bar detection), align
    with benchmark, and run all Phase 0C data-quality and coverage checks.
    """
    cfg = EXCHANGE_CONFIG.get(market.upper(), EXCHANGE_CONFIG["US"])
    tz_name = cfg["timezone"]
    warnings: List[str] = []

    if raw_df is None or raw_df.empty:
        return {
            "quality_status": "degraded",
            "warnings": ["No historical OHLCV bars returned by provider."],
            "quality_metrics": {"observations": 0},
            "ohlc_split": pd.DataFrame(),
            "ohlc_tr": pd.DataFrame(),
            "weekly_split": pd.DataFrame(),
            "weekly_completed": pd.DataFrame(),
            "monthly_split": pd.DataFrame(),
            "monthly_completed": pd.DataFrame(),
            "monthly_tr_returns": pd.Series(dtype=float),
            "benchmark_close": pd.Series(dtype=float),
            "aligned_returns": pd.DataFrame(),
            "splits": [],
            "dividends": [],
            "is_forming_daily_bar": False,
            "last_session": None,
            "history_start": None,
            "history_end": None,
            "observations": 0,
            "weekly_observations": 0,
            "monthly_observations": 0,
            "monthly_return_observations": 0,
            "benchmark_observations": 0,
            "benchmark_dropped_rows": 0,
            "coverage": _evaluate_coverage(0, 0),
        }

    df, index_anomalies = _normalize_index_to_exchange_dates(raw_df, tz_name)
    if index_anomalies > 0:
        warnings.append(
            f"Cleaned {index_anomalies} duplicate or unsorted timestamp(s) in daily history."
        )

    # Ensure core OHLCV columns exist
    for col in ("Open", "High", "Low", "Close"):
        if col not in df.columns:
            if "Close" in df.columns:
                df[col] = df["Close"]
            else:
                raise ValueError(f"Required price column '{col}' missing from OHLCV history.")
    if "Volume" not in df.columns:
        df["Volume"] = 0.0

    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 1. Check and remove non-positive or NaN prices
    valid_price_mask = (
        df["Open"].notna()
        & df["High"].notna()
        & df["Low"].notna()
        & df["Close"].notna()
        & (df["Open"] > 0)
        & (df["High"] > 0)
        & (df["Low"] > 0)
        & (df["Close"] > 0)
    )
    dropped_non_positive = int((~valid_price_mask).sum())
    if dropped_non_positive > 0:
        warnings.append(f"Dropped {dropped_non_positive} bar(s) with missing or non-positive OHLC prices.")
        df = df.loc[valid_price_mask].copy()

    if df.empty:
        return {
            "quality_status": "degraded",
            "warnings": warnings + ["All historical bars had invalid or non-positive prices."],
            "quality_metrics": {"observations": 0},
            "ohlc_split": pd.DataFrame(),
            "ohlc_tr": pd.DataFrame(),
            "weekly_split": pd.DataFrame(),
            "weekly_completed": pd.DataFrame(),
            "monthly_split": pd.DataFrame(),
            "monthly_completed": pd.DataFrame(),
            "monthly_tr_returns": pd.Series(dtype=float),
            "benchmark_close": pd.Series(dtype=float),
            "aligned_returns": pd.DataFrame(),
            "splits": [],
            "dividends": [],
            "is_forming_daily_bar": False,
            "last_session": None,
            "history_start": None,
            "history_end": None,
            "observations": 0,
            "weekly_observations": 0,
            "monthly_observations": 0,
            "monthly_return_observations": 0,
            "benchmark_observations": 0,
            "benchmark_dropped_rows": 0,
            "coverage": _evaluate_coverage(0, 0),
        }

    df["Volume"] = df["Volume"].fillna(0.0).clip(lower=0.0)

    # 2. Enforce OHLC envelope consistency (High >= max(O,L,C), Low <= min(O,H,C))
    row_max = df[["Open", "High", "Low", "Close"]].max(axis=1)
    row_min = df[["Open", "High", "Low", "Close"]].min(axis=1)
    inconsistent_mask = (df["High"] < row_max - 1e-6) | (df["Low"] > row_min + 1e-6)
    ohlc_inconsistencies_fixed = int(inconsistent_mask.sum())
    if ohlc_inconsistencies_fixed > 0:
        df["High"] = row_max
        df["Low"] = row_min
        warnings.append(
            f"Normalized {ohlc_inconsistencies_fixed} bar(s) where High/Low violated Open/Close envelope."
        )

    # 3. Extract Corporate Actions (Splits & Dividends)
    splits_list: List[Dict[str, Any]] = []
    split_dates_set = set()
    if "Stock Splits" in df.columns:
        sp_series = pd.to_numeric(df["Stock Splits"], errors="coerce").fillna(0.0)
        sp_events = sp_series[(sp_series > 0.0) & (sp_series != 1.0)]
        for dt_idx, ratio in sp_events.items():
            dt_str = dt_idx.strftime("%Y-%m-%d")
            split_dates_set.add(dt_idx)
            splits_list.append(
                {
                    "date": dt_str,
                    "ratio": round(float(ratio), 6),
                    "label": f"{ratio:g}:1 Split" if ratio >= 1 else f"1:{1.0/ratio:g} Reverse Split",
                }
            )

    dividends_list: List[Dict[str, Any]] = []
    if "Dividends" in df.columns:
        div_series = pd.to_numeric(df["Dividends"], errors="coerce").fillna(0.0)
        div_events = div_series[div_series > 0.0]
        for dt_idx, amt in div_events.items():
            dividends_list.append(
                {
                    "date": dt_idx.strftime("%Y-%m-%d"),
                    "amount": round(float(amt), 4),
                    "currency": cfg["currency"],
                }
            )

    # 4. Construct Dual Price Bases:
    #    - `ohlc_split`: Split-adjusted OHLCV (for chart, support/resistance, stops, patterns)
    #    - `ohlc_tr`: Total-return adjusted OHLCV (AdjClose/Close factor applied to OHLC)
    ohlc_split = df[["Open", "High", "Low", "Close", "Volume"]].copy()

    if "Adj Close" in df.columns:
        adj_close = pd.to_numeric(df["Adj Close"], errors="coerce")
        tr_factor = (adj_close / df["Close"]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        tr_factor = tr_factor.clip(lower=1e-4, upper=1e4)
    elif "Dividends" in df.columns and (df["Dividends"] > 0).any():
        # Reconstruct total-return adjustment factor from dividends if Adj Close is absent
        div_s = pd.to_numeric(df["Dividends"], errors="coerce").fillna(0.0)
        prev_close = df["Close"].shift(1).bfill()
        daily_div_adj = (1.0 - (div_s / prev_close)).clip(lower=0.5, upper=1.0)
        # Backward cumulative factor so latest bar has factor 1.0 (matching Yahoo Adj Close convention)
        rev_cum = daily_div_adj.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
        tr_factor = rev_cum
    else:
        tr_factor = pd.Series(1.0, index=df.index)

    ohlc_tr = pd.DataFrame(
        {
            "Open": df["Open"] * tr_factor,
            "High": df["High"] * tr_factor,
            "Low": df["Low"] * tr_factor,
            "Close": df["Close"] * tr_factor,
            "Volume": df["Volume"],
        },
        index=df.index,
    )

    # 5. Quality Checks: zero-volume share, stale close runs, session gaps, unrecorded splits
    n_obs = len(ohlc_split)
    zero_vol_count = int((ohlc_split["Volume"] <= 0).sum())
    zero_vol_share = float(zero_vol_count / n_obs) if n_obs > 0 else 0.0
    if zero_vol_share > 0.15:
        warnings.append(
            f"High zero-volume share ({zero_vol_share*100:.1f}% of sessions have 0 volume)."
        )

    # Longest consecutive identical close run (only among positive-volume or all sessions)
    close_vals = ohlc_split["Close"].to_numpy()
    max_stale_run = 1 if n_obs > 0 else 0
    if n_obs > 1:
        cur_run = 1
        for i in range(1, n_obs):
            if abs(close_vals[i] - close_vals[i - 1]) <= 1e-9:
                cur_run += 1
                if cur_run > max_stale_run:
                    max_stale_run = cur_run
            else:
                cur_run = 1
    if max_stale_run >= 5:
        warnings.append(
            f"Detected {max_stale_run} consecutive sessions with identical closing prices (potential trading halt or illiquidity)."
        )

    # Session gap check (business days between consecutive dates)
    max_bday_gap = 0
    gap_events_over_5 = 0
    if n_obs > 1:
        dates_arr = ohlc_split.index
        for i in range(1, n_obs):
            # Approximate business days between sessions (excluding weekends)
            b_days = int(np.busday_count(dates_arr[i - 1].date(), dates_arr[i].date()))
            # Subtract 1 because consecutive business days have busday_count == 1
            missing_sessions = max(0, b_days - 1)
            if missing_sessions > max_bday_gap:
                max_bday_gap = missing_sessions
            if missing_sessions > 5:
                gap_events_over_5 += 1
    if gap_events_over_5 > 0:
        warnings.append(
            f"Detected {gap_events_over_5} gap(s) exceeding 5 trading sessions (max gap: {max_bday_gap} sessions)."
        )

    # 1-day move > 40% with no split recorded within +/- 3 trading sessions
    daily_pct = ohlc_split["Close"].pct_change()
    extreme_moves = daily_pct[daily_pct.abs() > 0.40].dropna()
    unrecorded_split_suspects: List[Dict[str, Any]] = []
    for dt_idx, pct_move in extreme_moves.items():
        has_nearby_split = any(
            abs((dt_idx - sp_dt).days) <= 5 for sp_dt in split_dates_set
        )
        if not has_nearby_split:
            unrecorded_split_suspects.append(
                {
                    "date": dt_idx.strftime("%Y-%m-%d"),
                    "pct_change": round(float(pct_move * 100.0), 2),
                }
            )
    if unrecorded_split_suspects:
        suspect_str = ", ".join(
            f"{item['date']} ({item['pct_change']:+.1f}%)"
            for item in unrecorded_split_suspects[:3]
        )
        warnings.append(
            f"Detected 1-day price move > 40% without a recorded split on {suspect_str}; possible unadjusted corporate action."
        )

    # 6. Weekly & Monthly Resampling (with Forming-Bar Exclusion for W/M indicators)
    last_bar_ts = ohlc_split.index[-1]
    is_forming_daily = _is_daily_bar_forming(last_bar_ts, market, now_utc=now_utc)

    # For daily completed session date: if today's bar is still forming intraday, last completed session is the prior bar
    if is_forming_daily and n_obs >= 2:
        last_completed_session = ohlc_split.index[-2].strftime("%Y-%m-%d")
    else:
        last_completed_session = last_bar_ts.strftime("%Y-%m-%d")

    agg_spec = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    weekly_split = ohlc_split.resample("W-FRI").agg(agg_spec).dropna(subset=["Close"])
    monthly_split = ohlc_split.resample("ME").agg(agg_spec).dropna(subset=["Close"])
    monthly_tr = ohlc_tr.resample("ME").agg(agg_spec).dropna(subset=["Close"])

    # Determine if the final weekly bar is still forming:
    # A weekly bar (W-FRI) is forming if the last daily observation in the series is earlier than that Friday
    is_forming_weekly = bool(
        len(weekly_split) > 0 and (last_bar_ts.weekday() < 4 or is_forming_daily)
    )
    weekly_completed = (
        weekly_split.iloc[:-1].copy()
        if (is_forming_weekly and len(weekly_split) > 1)
        else weekly_split.copy()
    )

    # Determine if the final monthly bar is still forming:
    # A monthly bar (ME) is forming if `last_bar_ts` is earlier than the last business day of its month (by > 2 calendar days) or intraday forming
    if len(monthly_split) > 0:
        month_end_ts = monthly_split.index[-1]
        # Business month end for that month
        bme_ts = pd.date_range(
            start=last_bar_ts.replace(day=1), periods=1, freq="BME"
        )[0]
        is_forming_monthly = bool(last_bar_ts < bme_ts or is_forming_daily)
    else:
        is_forming_monthly = False

    monthly_completed = (
        monthly_split.iloc[:-1].copy()
        if (is_forming_monthly and len(monthly_split) > 1)
        else monthly_split.copy()
    )
    monthly_tr_completed = (
        monthly_tr.iloc[:-1].copy()
        if (is_forming_monthly and len(monthly_tr) > 1)
        else monthly_tr.copy()
    )
    monthly_tr_returns = monthly_tr_completed["Close"].pct_change().dropna()

    # 7. Benchmark Alignment (Inner Join on Exchange Dates)
    benchmark_close = pd.Series(dtype=float)
    aligned_returns = pd.DataFrame()
    benchmark_obs = 0
    benchmark_dropped = 0

    if benchmark_df is not None and not benchmark_df.empty and "Close" in benchmark_df.columns:
        b_df, _ = _normalize_index_to_exchange_dates(benchmark_df, tz_name)
        b_close = pd.to_numeric(b_df["Close"], errors="coerce").dropna()
        b_close = b_close[b_close > 0]
        benchmark_close = b_close
        benchmark_obs = int(len(b_close))

        asset_ret = ohlc_tr["Close"].pct_change().dropna()
        bench_ret = b_close.pct_change().dropna()
        joined = pd.concat(
            [asset_ret.rename("asset"), bench_ret.rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()
        aligned_returns = joined
        benchmark_dropped = max(0, int(len(asset_ret) - len(joined)))
        if len(asset_ret) > 0 and (benchmark_dropped / len(asset_ret)) > 0.10:
            warnings.append(
                f"Benchmark alignment dropped {benchmark_dropped} of {len(asset_ret)} daily return rows."
            )
    else:
        warnings.append("Benchmark history unavailable; relative strength and alpha/beta metrics degraded.")

    # 8. Determine Overall Quality Status (`complete | partial | stale | degraded`)
    if unrecorded_split_suspects or zero_vol_share > 0.30 or max_stale_run >= 10 or n_obs < 60:
        quality_status = "degraded"
    elif (
        warnings
        or benchmark_obs == 0
        or n_obs < 260
    ):
        quality_status = "partial"
    else:
        quality_status = "complete"

    coverage = _evaluate_coverage(n_obs, int(len(monthly_tr_returns)))

    quality_metrics = {
        "observations": n_obs,
        "weekly_observations": int(len(weekly_completed)),
        "monthly_observations": int(len(monthly_completed)),
        "monthly_return_observations": int(len(monthly_tr_returns)),
        "zero_volume_count": zero_vol_count,
        "zero_volume_share": round(zero_vol_share, 4),
        "max_stale_close_run": max_stale_run,
        "max_session_gap_business_days": max_bday_gap,
        "gap_events_over_5_sessions": gap_events_over_5,
        "ohlc_inconsistencies_fixed": ohlc_inconsistencies_fixed,
        "dropped_non_positive_rows": dropped_non_positive,
        "unrecorded_split_suspects": unrecorded_split_suspects,
        "benchmark_observations": benchmark_obs,
        "benchmark_aligned_returns": int(len(aligned_returns)),
        "benchmark_dropped_rows": benchmark_dropped,
        "is_forming_daily_bar": is_forming_daily,
        "is_forming_weekly_bar": is_forming_weekly,
        "is_forming_monthly_bar": is_forming_monthly,
    }

    return {
        "quality_status": quality_status,
        "warnings": warnings,
        "quality_metrics": quality_metrics,
        "ohlc_split": ohlc_split,
        "ohlc_tr": ohlc_tr,
        "weekly_split": weekly_split,
        "weekly_completed": weekly_completed,
        "monthly_split": monthly_split,
        "monthly_completed": monthly_completed,
        "monthly_tr_returns": monthly_tr_returns,
        "benchmark_close": benchmark_close,
        "aligned_returns": aligned_returns,
        "splits": splits_list,
        "dividends": dividends_list,
        "is_forming_daily_bar": is_forming_daily,
        "last_session": last_completed_session,
        "history_start": ohlc_split.index[0].strftime("%Y-%m-%d"),
        "history_end": ohlc_split.index[-1].strftime("%Y-%m-%d"),
        "observations": n_obs,
        "weekly_observations": int(len(weekly_completed)),
        "monthly_observations": int(len(monthly_completed)),
        "monthly_return_observations": int(len(monthly_tr_returns)),
        "benchmark_observations": benchmark_obs,
        "benchmark_dropped_rows": benchmark_dropped,
        "coverage": coverage,
    }


def _evaluate_coverage(daily_bars: int, monthly_returns: int) -> Dict[str, Dict[str, Any]]:
    """Evaluate feature eligibility against the Phase 0C minimum-bars contract."""
    out: Dict[str, Dict[str, Any]] = {}
    for key, spec in COVERAGE_REQUIREMENTS.items():
        unit = spec["unit"]
        min_obs = int(spec["min_obs"])
        avail = monthly_returns if unit == "monthly_returns" else daily_bars
        eligible = avail >= min_obs
        out[key] = {
            "label": spec["label"],
            "eligible": bool(eligible),
            "status": "available" if eligible else "insufficient_history",
            "required": min_obs,
            "available": int(avail),
            "unit": unit,
            "message": (
                None
                if eligible
                else f"Insufficient history ({avail} {unit.replace('_', ' ')} available; requires >= {min_obs})."
            ),
        }
    return out


# ---------------------------------------------------------------------------
# Fetcher with Parallel Benchmark, Retries & Stale-Cache Fallback
# ---------------------------------------------------------------------------

def _fetch_single_history_with_retries(
    ticker_sym: str,
    period: str,
    session: Any,
    max_retries: int = 3,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Fetch `yf.Ticker(ticker_sym).history(...)` with up to `max_retries` attempts."""
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            t_obj = yf.Ticker(ticker_sym, session=session)
            hist = t_obj.history(
                period=period,
                interval="1d",
                auto_adjust=False,
                actions=True,
            )
            if hist is not None and not hist.empty:
                return hist
        except Exception as exc:
            last_err = exc
            logger.warning(
                "TA history fetch attempt %d/%d failed for %s: %s",
                attempt + 1,
                max_retries,
                ticker_sym,
                exc,
            )
        if attempt < max_retries - 1:
            sleep_fn(0.35 * (2 ** attempt))

    if last_err is not None:
        raise RuntimeError(
            f"Failed to fetch OHLCV history for {ticker_sym} after {max_retries} attempts: {last_err}"
        ) from last_err
    return pd.DataFrame()


def _get_key_lock(cache_key: str) -> threading.Lock:
    """Return a per-key lock to coalesce concurrent in-flight requests for the same ticker."""
    with _TA_CACHE_META_LOCK:
        if cache_key not in _TA_INFLIGHT_LOCKS:
            if len(_TA_INFLIGHT_LOCKS) > 256:
                _TA_INFLIGHT_LOCKS.clear()
            _TA_INFLIGHT_LOCKS[cache_key] = threading.Lock()
        return _TA_INFLIGHT_LOCKS[cache_key]


def _fetch_benchmark_history(
    benchmark_sym: str,
    period: str,
    session: Any,
) -> pd.DataFrame:
    """Fetch and cache benchmark daily history (1-hour fresh TTL, single-flight locked)."""
    cache_key = f"{benchmark_sym}:{period}"
    now = time.time()
    if cache_key in _TA_BENCHMARK_CACHE:
        cached_df, ts = _TA_BENCHMARK_CACHE[cache_key]
        if now - ts < _TA_BENCHMARK_TTL_SECONDS:
            return cached_df.copy()

    with _TA_BENCHMARK_LOCK:
        now = time.time()
        if cache_key in _TA_BENCHMARK_CACHE:
            cached_df, ts = _TA_BENCHMARK_CACHE[cache_key]
            if now - ts < _TA_BENCHMARK_TTL_SECONDS:
                return cached_df.copy()
        try:
            df = _fetch_single_history_with_retries(
                benchmark_sym, period=period, session=session, max_retries=2
            )
            if df is not None and not df.empty:
                _TA_BENCHMARK_CACHE[cache_key] = (df.copy(), now)
                return df
        except Exception as exc:
            logger.warning("Benchmark history fetch failed for %s: %s", benchmark_sym, exc)

        if cache_key in _TA_BENCHMARK_CACHE:
            return _TA_BENCHMARK_CACHE[cache_key][0].copy()
        return pd.DataFrame()


def fetch_market_history(
    symbol: str,
    market: str = "auto",
    period: str = "10y",
    force_refresh: bool = False,
) -> MarketHistoryBundle:
    """
    Fetch, clean, audit, and cache daily/weekly/monthly OHLCV + benchmark history
    for `symbol`.

    - Resolves NSE (`.NS`) primary listing first for Indian equities, falling back
      to BSE (`.BO`) automatically when `.NS` has no data.
    - Coalesces concurrent requests per ticker via `_get_key_lock` so duplicate
      bursts never hit Yahoo Finance simultaneously.
    - Fetches asset and benchmark (`^NSEI` or `^GSPC`) in parallel reusing `get_yf_session()`.
    - Falls back to stale cached data (`quality_status="stale"`) if live provider fails.
    """
    t0 = time.perf_counter()
    base_sym, primary_listing, resolved_mkt, redirect_note = resolve_ta_listing(symbol, market)
    cfg = EXCHANGE_CONFIG.get(resolved_mkt, EXCHANGE_CONFIG["US"])
    benchmark_sym = cfg["benchmark"]
    cache_key = f"{primary_listing}:{resolved_mkt}:{period}"
    now = time.time()

    if not force_refresh and cache_key in _TA_HISTORY_CACHE:
        cached_bundle, cached_ts = _TA_HISTORY_CACHE[cache_key]
        if now - cached_ts < _TA_CACHE_FRESH_TTL_SECONDS:
            cp = MarketHistoryBundle(**{**cached_bundle.__dict__, "cached": True})
            return cp

    key_lock = _get_key_lock(cache_key)
    with key_lock:
        now = time.time()
        if not force_refresh and cache_key in _TA_HISTORY_CACHE:
            cached_bundle, cached_ts = _TA_HISTORY_CACHE[cache_key]
            if now - cached_ts < _TA_CACHE_FRESH_TTL_SECONDS:
                cp = MarketHistoryBundle(**{**cached_bundle.__dict__, "cached": True})
                return cp

        session = get_yf_session()
        listing_used = primary_listing
        raw_asset_df = pd.DataFrame()
        raw_bench_df = pd.DataFrame()
        fetch_error: Optional[Exception] = None

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_asset = pool.submit(
                    _fetch_single_history_with_retries, primary_listing, period, session
                )
                fut_bench = pool.submit(
                    _fetch_benchmark_history, benchmark_sym, period, session
                )
                try:
                    raw_asset_df = fut_asset.result()
                except Exception as asset_exc:
                    fetch_error = asset_exc
                    raw_asset_df = pd.DataFrame()
                raw_bench_df = fut_bench.result()

            # Automatic NSE -> BSE fallback when primary .NS listing has no data
            if (raw_asset_df is None or len(raw_asset_df) < 5) and resolved_mkt == "IN" and primary_listing.endswith(".NS"):
                bse_listing = f"{base_sym}.BO"
                logger.info("NSE listing %s returned insufficient bars; attempting BSE fallback %s", primary_listing, bse_listing)
                try:
                    bse_df = _fetch_single_history_with_retries(bse_listing, period, session)
                    if bse_df is not None and len(bse_df) >= 5:
                        raw_asset_df = bse_df
                        listing_used = bse_listing
                        fetch_error = None
                except Exception as bse_exc:
                    fetch_error = fetch_error or bse_exc
        except Exception as outer_exc:
            fetch_error = outer_exc

        # If live fetch failed or returned empty, check stale cache fallback
        if raw_asset_df is None or raw_asset_df.empty:
            if cache_key in _TA_HISTORY_CACHE:
                stale_bundle, stale_ts = _TA_HISTORY_CACHE[cache_key]
                if now - stale_ts <= _TA_CACHE_STALE_MAX_SECONDS:
                    stale_warnings = list(stale_bundle.warnings) + [
                        f"Live provider fetch failed ({fetch_error or 'empty response'}); serving cached snapshot from {stale_bundle.computed_at}."
                    ]
                    return MarketHistoryBundle(
                        **{
                            **stale_bundle.__dict__,
                            "quality_status": "stale",
                            "warnings": stale_warnings,
                            "cached": True,
                        }
                    )
            raise ValueError(
                f"Unable to retrieve historical price data for '{symbol}' ({listing_used}). "
                f"{fetch_error or 'No OHLCV bars returned by Yahoo Finance.'}"
            )

        audit = clean_and_audit_ohlcv(
            raw_df=raw_asset_df,
            market=resolved_mkt,
            benchmark_df=raw_bench_df,
        )
        if redirect_note:
            audit["warnings"].insert(0, redirect_note)
        if listing_used != primary_listing:
            audit["warnings"].insert(
                0,
                f"Primary NSE listing ({primary_listing}) had insufficient history; resolved to BSE listing ({listing_used}).",
            )

        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        bundle = MarketHistoryBundle(
            symbol=base_sym,
            listing_used=listing_used,
            market=resolved_mkt,
            currency=cfg["currency"],
            currency_symbol=cfg["currency_symbol"],
            benchmark=benchmark_sym,
            period_requested=period,
            provider="Yahoo Finance (yfinance)",
            as_of=now_iso,
            computed_at=now_iso,
            last_session=audit["last_session"],
            exchange_timezone=cfg["timezone"],
            is_forming_daily_bar=audit["is_forming_daily_bar"],
            history_start=audit["history_start"],
            history_end=audit["history_end"],
            observations=audit["observations"],
            weekly_observations=audit["weekly_observations"],
            monthly_observations=audit["monthly_observations"],
            monthly_return_observations=audit["monthly_return_observations"],
            benchmark_observations=audit["benchmark_observations"],
            benchmark_dropped_rows=audit["benchmark_dropped_rows"],
            quality_status=audit["quality_status"],
            warnings=audit["warnings"],
            quality_metrics=audit["quality_metrics"],
            coverage=audit["coverage"],
            ohlc_split=audit["ohlc_split"],
            ohlc_tr=audit["ohlc_tr"],
            weekly_split=audit["weekly_split"],
            weekly_completed=audit["weekly_completed"],
            monthly_split=audit["monthly_split"],
            monthly_completed=audit["monthly_completed"],
            monthly_tr_returns=audit["monthly_tr_returns"],
            benchmark_close=audit["benchmark_close"],
            aligned_returns=audit["aligned_returns"],
            splits=audit["splits"],
            dividends=audit["dividends"],
            cached=False,
            fetch_latency_ms=elapsed_ms,
        )

        with _TA_CACHE_META_LOCK:
            if len(_TA_HISTORY_CACHE) >= _TA_CACHE_MAX_ENTRIES and cache_key not in _TA_HISTORY_CACHE:
                oldest_key = min(_TA_HISTORY_CACHE, key=lambda k: _TA_HISTORY_CACHE[k][1])
                _TA_HISTORY_CACHE.pop(oldest_key, None)
            _TA_HISTORY_CACHE[cache_key] = (bundle, now)

        return bundle


# ---------------------------------------------------------------------------
# Standardized `/api/technical/*` Response Envelope Builder
# ---------------------------------------------------------------------------

def compute_param_hash(params: Dict[str, Any]) -> str:
    """Compute a short deterministic SHA-256 hash of indicator/backtest parameters."""
    canonical = json.dumps(params or {}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def build_technical_response_envelope(
    bundle: MarketHistoryBundle,
    payload: Optional[Dict[str, Any]] = None,
    score_model: str = "v1.0-6pillar",
    signal_defs: str = "confirmed-bar-close-next-open",
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the standardized Phase 0C response contract required for every
    `/api/technical/*` endpoint.
    """
    envelope: Dict[str, Any] = {
        "symbol": bundle.symbol,
        "listing_used": bundle.listing_used,
        "market": bundle.market,
        "currency": bundle.currency,
        "currency_symbol": bundle.currency_symbol,
        "benchmark": bundle.benchmark,
        "cached": bundle.cached,
        "computed_at": bundle.computed_at,
        "data": {
            "provider": bundle.provider,
            "as_of": bundle.as_of,
            "last_session": bundle.last_session,
            "exchange_timezone": bundle.exchange_timezone,
            "is_forming_daily_bar": bundle.is_forming_daily_bar,
            "history_start": bundle.history_start,
            "history_end": bundle.history_end,
            "observations": bundle.observations,
            "weekly_observations": bundle.weekly_observations,
            "monthly_observations": bundle.monthly_observations,
            "monthly_return_observations": bundle.monthly_return_observations,
            "benchmark_observations": bundle.benchmark_observations,
            "benchmark_dropped_rows": bundle.benchmark_dropped_rows,
            "price_basis": {
                "levels": "split_adjusted_ohlc",
                "returns": "total_return_adj_ohlc",
            },
            "quality_status": bundle.quality_status,
            "quality_metrics": bundle.quality_metrics,
            "warnings": bundle.warnings,
            "coverage": bundle.coverage,
        },
        "methodology": {
            "ta_engine": TA_ENGINE_VERSION,
            "model_version": MODEL_VERSION,
            "score_model": score_model,
            "signal_defs": signal_defs,
            "param_hash": compute_param_hash(params or {"period": bundle.period_requested}),
        },
    }
    if payload:
        envelope.update(payload)
    return envelope


# ---------------------------------------------------------------------------
# Phase 0C Diagnostic Probe (`GET /api/technical/_probe`)
# ---------------------------------------------------------------------------

def run_technical_probe(
    symbols: Optional[List[Tuple[str, str]]] = None,
    period: str = "10y",
) -> Dict[str, Any]:
    """
    Execute the Phase 0C diagnostic probe across `symbols` (default: 10 golden tickers)
    to measure `period="10y"` success rate, p50/p95 latency, payload size, and coverage.
    """
    target_list = symbols or DEFAULT_PROBE_TICKERS
    results: List[Dict[str, Any]] = []
    latencies: List[float] = []
    payload_Dummy_bytes: List[int] = []
    success_count = 0

    for sym, mkt in target_list:
        t_start = time.perf_counter()
        try:
            bundle = fetch_market_history(symbol=sym, market=mkt, period=period, force_refresh=True)
            elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
            latencies.append(elapsed_ms)
            success_count += 1

            # Estimate JSON payload size of daily OHLCV + envelope
            sample_records = {
                "dates": [d.strftime("%Y-%m-%d") for d in bundle.ohlc_split.index],
                "close": [round(float(x), 2) for x in bundle.ohlc_split["Close"].tolist()],
                "tr_close": [round(float(x), 2) for x in bundle.ohlc_tr["Close"].tolist()],
                "volume": [int(x) for x in bundle.ohlc_split["Volume"].tolist()],
            }
            env = build_technical_response_envelope(bundle, payload={"series_preview_count": len(sample_records["dates"])})
            serialized_kb = round(len(json.dumps({**env, "sample": sample_records}).encode("utf-8")) / 1024.0, 2)
            payload_Dummy_bytes.append(int(serialized_kb * 1024))

            results.append(
                {
                    "symbol": bundle.symbol,
                    "listing_used": bundle.listing_used,
                    "market": bundle.market,
                    "benchmark": bundle.benchmark,
                    "status": "ok",
                    "latency_ms": elapsed_ms,
                    "payload_kb": serialized_kb,
                    "observations": bundle.observations,
                    "weekly_observations": bundle.weekly_observations,
                    "monthly_return_observations": bundle.monthly_return_observations,
                    "history_start": bundle.history_start,
                    "history_end": bundle.history_end,
                    "last_session": bundle.last_session,
                    "splits_count": len(bundle.splits),
                    "dividends_count": len(bundle.dividends),
                    "quality_status": bundle.quality_status,
                    "warnings_count": len(bundle.warnings),
                    "all_6_features_eligible": all(
                        v["eligible"] for v in bundle.coverage.values()
                    ),
                }
            )
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
            results.append(
                {
                    "symbol": sym,
                    "market": mkt,
                    "status": "error",
                    "latency_ms": elapsed_ms,
                    "error": str(exc),
                }
            )

    total = len(target_list)
    success_rate = round((success_count / total) * 100.0, 1) if total > 0 else 0.0
    p50_ms = round(float(np.percentile(latencies, 50)), 2) if latencies else 0.0
    p95_ms = round(float(np.percentile(latencies, 95)), 2) if latencies else 0.0
    avg_payload_kb = round(float(np.mean(payload_Dummy_bytes)) / 1024.0, 2) if payload_Dummy_bytes else 0.0

    recommended_period = "10y" if (success_rate >= 90.0 and p95_ms < 6000.0) else "5y"

    return {
        "probe_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period_tested": period,
        "tickers_tested": total,
        "success_count": success_count,
        "success_rate_pct": success_rate,
        "latency_p50_ms": p50_ms,
        "latency_p95_ms": p95_ms,
        "avg_payload_kb": avg_payload_kb,
        "recommended_default_period": recommended_period,
        "results": results,
    }
