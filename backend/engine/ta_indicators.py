"""
Technical Analysis v0.1 Indicator, Level, Volume Profile & Sizing Engine
(`backend/engine/ta_indicators.py`)
========================================================================

Implements the mathematical specifications in `docs/TA_Methodology.md` v0.1:
  - SMA(20, 50, 150, 200) and EMA(12, 20, 26, 50) (SMA-seeded recursive EMA)
  - Wilder's RSI(14) and Wilder's ATR(14)
  - MACD(12, 26, 9) and Bollinger Bands(20, 2.0, ddof=0)
  - Anchored VWAP (YTD, 52W High, 52W Low, Last Confirmed Swing Low)
  - Causal 5-bar Fractal Swing Pivots & Clustered S/R Levels (strictly no-repaint:
    a pivot at index p is only confirmed and emitted once bar p + right_bars closes)
  - 24-Bin Daily-Bar Volume Profile (POC, VAH, VAL, labelled "est. from daily bars")
  - Weinstein Stage (1-4) & Minervini 8-Point Trend Template preview
  - Fixed-Risk Position Sizing Calculator with wrong-side stop guardrail
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import MODEL_VERSION
from .market_history import (
    MarketHistoryBundle,
    build_technical_response_envelope,
)


# ---------------------------------------------------------------------------
# 1. Moving Averages (SMA & SMA-Seeded EMA)
# ---------------------------------------------------------------------------

def compute_sma(series: pd.Series, window: int) -> pd.Series:
    """Compute Simple Moving Average of length `window`."""
    if series is None or series.empty or window <= 0:
        return pd.Series(dtype=float, index=series.index if series is not None else None)
    return series.astype(float).rolling(window=window, min_periods=window).mean()


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    """
    Compute Exponential Moving Average of length `span`, seeded with the
    `span`-period SMA at the `span`-th valid observation (matching standard
    institutional & TA reference definitions to 1e-6).
    """
    if series is None or series.empty or span <= 0:
        return pd.Series(dtype=float, index=series.index if series is not None else None)

    vals = series.astype(float).to_numpy()
    n = len(vals)
    out = np.full(n, np.nan, dtype=float)

    valid_idx = np.where(~np.isnan(vals))[0]
    if len(valid_idx) < span:
        return pd.Series(out, index=series.index)

    start_pos = valid_idx[0]
    seed_end = start_pos + span
    if seed_end > n:
        return pd.Series(out, index=series.index)

    window_slice = vals[start_pos:seed_end]
    if np.isnan(window_slice).any():
        # Fallback to pandas ewm if internal NaNs exist
        return series.astype(float).ewm(span=span, adjust=False, min_periods=span).mean()

    alpha = 2.0 / (span + 1.0)
    out[seed_end - 1] = float(np.mean(window_slice))
    for i in range(seed_end, n):
        if np.isnan(vals[i]):
            out[i] = out[i - 1]
        else:
            out[i] = alpha * vals[i] + (1.0 - alpha) * out[i - 1]

    return pd.Series(out, index=series.index)


# ---------------------------------------------------------------------------
# 2. Wilder's RSI(14), MACD(12, 26, 9), Wilder's ATR(14) & Bollinger(20, 2)
# ---------------------------------------------------------------------------

def compute_rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Compute J. Welles Wilder Jr.'s RSI(period) using Wilder's recursive
    smoothing (alpha = 1/period, seeded with simple average over first `period` deltas).
    """
    if close is None or len(close) <= period:
        return pd.Series(np.nan, index=close.index if close is not None else None, dtype=float)

    c = close.astype(float).to_numpy()
    n = len(c)
    rsi = np.full(n, np.nan, dtype=float)

    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    if avg_loss == 0.0:
        rsi[period] = 100.0 if avg_gain > 0 else 50.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(deltas)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        if avg_loss == 0.0:
            rsi[i + 1] = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return pd.Series(rsi, index=close.index)


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Dict[str, pd.Series]:
    """Compute MACD(12, 26, 9): macd_line, signal_line, and histogram."""
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def compute_atr_wilder(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """
    Compute Wilder's Average True Range (ATR) seeded with the arithmetic mean
    of the first `period` True Range values and smoothed recursively with alpha = 1/period.
    """
    if close is None or len(close) < period:
        return pd.Series(np.nan, index=close.index if close is not None else None, dtype=float)

    h = high.astype(float).to_numpy()
    l = low.astype(float).to_numpy()
    c = close.astype(float).to_numpy()
    n = len(c)

    tr = np.zeros(n, dtype=float)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        hl = h[i] - l[i]
        hc = abs(h[i] - c[i - 1])
        lc = abs(l[i] - c[i - 1])
        tr[i] = max(hl, hc, lc)

    atr = np.full(n, np.nan, dtype=float)
    atr[period - 1] = float(np.mean(tr[:period]))
    for i in range(period, n):
        atr[i] = ((atr[i - 1] * (period - 1)) + tr[i]) / period

    return pd.Series(atr, index=close.index)


def compute_bollinger_bands(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> Dict[str, pd.Series]:
    """
    Compute Bollinger Bands(20, 2.0) using population standard deviation (ddof=0),
    returning middle, upper, lower, pct_b, and bandwidth.
    """
    mid = compute_sma(close, window)
    std = close.astype(float).rolling(window=window, min_periods=window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    band_span = (upper - lower).replace(0.0, np.nan)
    pct_b = (close - lower) / band_span
    bandwidth = (upper - lower) / mid.replace(0.0, np.nan)
    return {
        "middle": mid,
        "upper": upper,
        "lower": lower,
        "pct_b": pct_b,
        "bandwidth": bandwidth,
    }


# ---------------------------------------------------------------------------
# 3. Causal Fractal Swing Pivots & Clustered Support/Resistance (Zero Repaint)
# ---------------------------------------------------------------------------

def detect_confirmed_swings_and_sr(
    df: pd.DataFrame,
    atr_series: Optional[pd.Series] = None,
    left_bars: int = 5,
    right_bars: int = 5,
    lookback: int = 252,
    max_levels: int = 6,
) -> Dict[str, Any]:
    """
    Detect causal fractal swing highs and swing lows of order (left_bars, right_bars)
    and cluster them into horizontal Support and Resistance levels.

    Strict No-Repaint Guarantee:
      - A candidate pivot at bar index `p` is evaluated ONLY if `p + right_bars < len(df)`.
      - Its `confirmed_index` is `p + right_bars` and `confirmed_date` is `df.index[p + right_bars]`.
      - Truncating `df` to `df.iloc[:k]` produces the exact same set of pivots with
        `confirmed_index < k`.
    """
    if df is None or len(df) < (left_bars + right_bars + 1):
        return {"swing_highs": [], "swing_lows": [], "levels": [], "nearest_support": None, "nearest_resistance": None}

    highs = df["High"].astype(float).to_numpy()
    lows = df["Low"].astype(float).to_numpy()
    closes = df["Close"].astype(float).to_numpy()
    dates = df.index
    n = len(df)

    swing_highs: List[Dict[str, Any]] = []
    swing_lows: List[Dict[str, Any]] = []

    # Candidate pivot p can only be confirmed if p + right_bars <= n - 1
    max_candidate_p = n - 1 - right_bars
    for p in range(left_bars, max_candidate_p + 1):
        win_h = highs[p - left_bars : p + right_bars + 1]
        win_l = lows[p - left_bars : p + right_bars + 1]
        conf_idx = p + right_bars
        pivot_date_str = dates[p].strftime("%Y-%m-%d")
        conf_date_str = dates[conf_idx].strftime("%Y-%m-%d")

        # Strict local extremum (tie broken by earliest occurrence in window)
        if highs[p] >= np.max(win_h) and np.argmax(win_h) == left_bars:
            swing_highs.append(
                {
                    "type": "swing_high",
                    "pivot_index": int(p),
                    "pivot_date": pivot_date_str,
                    "confirmed_index": int(conf_idx),
                    "confirmed_date": conf_date_str,
                    "price": round(float(highs[p]), 4),
                }
            )
        if lows[p] <= np.min(win_l) and np.argmin(win_l) == left_bars:
            swing_lows.append(
                {
                    "type": "swing_low",
                    "pivot_index": int(p),
                    "pivot_date": pivot_date_str,
                    "confirmed_index": int(conf_idx),
                    "confirmed_date": conf_date_str,
                    "price": round(float(lows[p]), 4),
                }
            )

    # Cluster recent confirmed pivots (within trailing `lookback` bars) using 0.75 * ATR bandwidth
    current_price = float(closes[-1])
    latest_atr = (
        float(atr_series.dropna().iloc[-1])
        if (atr_series is not None and not atr_series.dropna().empty)
        else current_price * 0.02
    )
    cluster_tol = max(latest_atr * 0.75, current_price * 0.0075)

    min_pivot_idx = max(0, n - lookback)
    recent_pivots = [
        p for p in (swing_highs + swing_lows) if p["pivot_index"] >= min_pivot_idx
    ]
    # Sort by price ascending to cluster nearby levels
    recent_pivots_sorted = sorted(recent_pivots, key=lambda x: x["price"])

    clusters: List[List[Dict[str, Any]]] = []
    for piv in recent_pivots_sorted:
        if not clusters:
            clusters.append([piv])
        else:
            prev_cluster_mean = float(np.mean([x["price"] for x in clusters[-1]]))
            if abs(piv["price"] - prev_cluster_mean) <= cluster_tol:
                clusters[-1].append(piv)
            else:
                clusters.append([piv])

    levels: List[Dict[str, Any]] = []
    for cl in clusters:
        mean_price = float(np.mean([x["price"] for x in cl]))
        touches = len(cl)
        first_date = min(x["pivot_date"] for x in cl)
        last_conf_date = max(x["confirmed_date"] for x in cl)
        last_conf_idx = max(x["confirmed_index"] for x in cl)
        dist_pct = ((mean_price - current_price) / current_price) * 100.0
        role = "support" if mean_price <= current_price else "resistance"
        levels.append(
            {
                "price": round(mean_price, 2),
                "role": role,
                "touches": int(touches),
                "first_pivot_date": first_date,
                "confirmed_date": last_conf_date,
                "confirmed_index": int(last_conf_idx),
                "distance_pct": round(float(dist_pct), 2),
                "strength_score": round(float(touches + (last_conf_idx / max(1, n))), 3),
            }
        )

    # Select top levels balanced between support and resistance closest to current price & highest touch count
    supports = sorted(
        [lv for lv in levels if lv["role"] == "support"],
        key=lambda x: (-x["touches"], abs(x["distance_pct"])),
    )[: max_levels // 2]
    resistances = sorted(
        [lv for lv in levels if lv["role"] == "resistance"],
        key=lambda x: (-x["touches"], abs(x["distance_pct"])),
    )[: max_levels // 2]

    selected_levels = sorted(supports + resistances, key=lambda x: x["price"])

    nearest_support = (
        max([lv for lv in levels if lv["role"] == "support"], key=lambda x: x["price"])
        if any(lv["role"] == "support" for lv in levels)
        else None
    )
    nearest_resistance = (
        min([lv for lv in levels if lv["role"] == "resistance"], key=lambda x: x["price"])
        if any(lv["role"] == "resistance" for lv in levels)
        else None
    )

    return {
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
        "levels": selected_levels,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
    }


# ---------------------------------------------------------------------------
# 4. Anchored VWAP (YTD, 52W High, 52W Low, Last Confirmed Swing Low)
# ---------------------------------------------------------------------------

def _compute_single_avwap(df: pd.DataFrame, anchor_pos: int) -> pd.Series:
    """Compute Anchored VWAP starting at integer position `anchor_pos`."""
    n = len(df)
    out = np.full(n, np.nan, dtype=float)
    if anchor_pos < 0 or anchor_pos >= n:
        return pd.Series(out, index=df.index)

    tp = ((df["High"] + df["Low"] + df["Close"]) / 3.0).to_numpy(dtype=float)
    vol = df["Volume"].to_numpy(dtype=float)

    sub_tp = tp[anchor_pos:]
    sub_vol = np.where(vol[anchor_pos:] > 0, vol[anchor_pos:], 1.0)
    cum_pv = np.cumsum(sub_tp * sub_vol)
    cum_v = np.cumsum(sub_vol)
    out[anchor_pos:] = cum_pv / cum_v
    return pd.Series(out, index=df.index)


def compute_anchored_vwaps(
    df: pd.DataFrame,
    swing_lows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute 4 canonical Anchored VWAP series:
      - `ytd`: First trading session of the latest calendar year in `df`
      - `high_52w`: Highest high in trailing 252 trading sessions
      - `low_52w`: Lowest low in trailing 252 trading sessions
      - `swing_low`: Most recent confirmed fractal swing low
    """
    if df is None or df.empty:
        return {}

    n = len(df)
    dates = df.index
    last_year = dates[-1].year

    # 1. YTD anchor
    ytd_candidates = np.where(dates.year == last_year)[0]
    ytd_pos = int(ytd_candidates[0]) if len(ytd_candidates) > 0 else max(0, n - 252)

    # 2. 52W High & Low anchors (trailing 252 bars)
    start_52w = max(0, n - 252)
    high_slice = df["High"].iloc[start_52w:].to_numpy(dtype=float)
    low_slice = df["Low"].iloc[start_52w:].to_numpy(dtype=float)
    high_52w_pos = start_52w + int(np.argmax(high_slice))
    low_52w_pos = start_52w + int(np.argmin(low_slice))

    # 3. Last confirmed swing low anchor
    if swing_lows and len(swing_lows) > 0:
        swing_low_pos = int(swing_lows[-1]["pivot_index"])
    else:
        swing_low_pos = low_52w_pos

    anchors_spec = {
        "ytd": ("YTD Anchor", ytd_pos),
        "high_52w": ("52W High Anchor", high_52w_pos),
        "low_52w": ("52W Low Anchor", low_52w_pos),
        "swing_low": ("Confirmed Swing Low", swing_low_pos),
    }

    result: Dict[str, Dict[str, Any]] = {}
    for key, (label, pos) in anchors_spec.items():
        s = _compute_single_avwap(df, pos)
        curr_val = float(s.iloc[-1]) if not np.isnan(s.iloc[-1]) else None
        result[key] = {
            "label": label,
            "anchor_index": pos,
            "anchor_date": dates[pos].strftime("%Y-%m-%d"),
            "current_value": round(curr_val, 2) if curr_val is not None else None,
            "series": s,
        }
    return result


# ---------------------------------------------------------------------------
# 5. Daily-Bar Volume Profile (24 Bins, POC, VAH, VAL — "est. from daily bars")
# ---------------------------------------------------------------------------

def compute_volume_profile(
    df: pd.DataFrame,
    num_bins: int = 24,
    lookback: int = 252,
    value_area_pct: float = 0.70,
) -> Dict[str, Any]:
    """
    Compute a 24-bin horizontal Volume Profile over the trailing `lookback` daily sessions,
    explicitly labelled `"est. from daily bars"`.
    """
    if df is None or df.empty:
        return {
            "approximation_label": "est. from daily bars",
            "poc_price": None,
            "vah_price": None,
            "val_price": None,
            "bins": [],
        }

    sub = df.iloc[-lookback:].copy()
    low_min = float(sub["Low"].min())
    high_max = float(sub["High"].max())

    if high_max <= low_min or math.isclose(high_max, low_min):
        mid_p = round(low_min, 2)
        return {
            "approximation_label": "est. from daily bars",
            "poc_price": mid_p,
            "vah_price": mid_p,
            "val_price": mid_p,
            "bins": [
                {
                    "price_low": mid_p,
                    "price_high": mid_p,
                    "price_mid": mid_p,
                    "volume": float(sub["Volume"].sum()),
                    "pct_of_max": 100.0,
                    "is_poc": True,
                    "in_value_area": True,
                }
            ],
        }

    edges = np.linspace(low_min, high_max, num_bins + 1)
    bin_lows = edges[:-1]
    bin_highs = edges[1:]
    bin_mids = 0.5 * (bin_lows + bin_highs)
    bin_vols = np.zeros(num_bins, dtype=float)

    lows = sub["Low"].to_numpy(dtype=float)
    highs = sub["High"].to_numpy(dtype=float)
    vols = sub["Volume"].to_numpy(dtype=float)

    for i in range(len(sub)):
        v = max(0.0, vols[i])
        if v == 0.0:
            continue
        # Distribute bar volume across bins overlapped by [Low_i, High_i]
        overlapped = (bin_highs >= lows[i]) & (bin_lows <= highs[i])
        count = int(np.sum(overlapped))
        if count > 0:
            bin_vols[overlapped] += v / count
        else:
            idx = int(np.clip(np.searchsorted(edges, 0.5 * (lows[i] + highs[i])) - 1, 0, num_bins - 1))
            bin_vols[idx] += v

    poc_idx = int(np.argmax(bin_vols))
    poc_price = round(float(bin_mids[poc_idx]), 2)
    total_vol = float(np.sum(bin_vols))
    max_bin_vol = float(bin_vols[poc_idx]) if bin_vols[poc_idx] > 0 else 1.0

    # Expand Value Area around POC until 70% of total volume is captured
    va_indices = {poc_idx}
    accum_vol = float(bin_vols[poc_idx])
    left_ptr = poc_idx - 1
    right_ptr = poc_idx + 1

    while accum_vol < value_area_pct * total_vol and (left_ptr >= 0 or right_ptr < num_bins):
        left_v = bin_vols[left_ptr] if left_ptr >= 0 else -1.0
        right_v = bin_vols[right_ptr] if right_ptr < num_bins else -1.0
        if right_v >= left_v:
            va_indices.add(right_ptr)
            accum_vol += max(0.0, right_v)
            right_ptr += 1
        else:
            va_indices.add(left_ptr)
            accum_vol += max(0.0, left_v)
            left_ptr -= 1

    val_idx = min(va_indices)
    vah_idx = max(va_indices)
    val_price = round(float(bin_lows[val_idx]), 2)
    vah_price = round(float(bin_highs[vah_idx]), 2)

    bins_out: List[Dict[str, Any]] = []
    for b in range(num_bins):
        bins_out.append(
            {
                "price_low": round(float(bin_lows[b]), 2),
                "price_high": round(float(bin_highs[b]), 2),
                "price_mid": round(float(bin_mids[b]), 2),
                "volume": round(float(bin_vols[b]), 1),
                "pct_of_max": round(float((bin_vols[b] / max_bin_vol) * 100.0), 1),
                "is_poc": bool(b == poc_idx),
                "in_value_area": bool(b in va_indices),
            }
        )

    return {
        "approximation_label": "est. from daily bars",
        "lookback_bars": int(len(sub)),
        "poc_price": poc_price,
        "vah_price": vah_price,
        "val_price": val_price,
        "bins": bins_out,
    }


# ---------------------------------------------------------------------------
# 6. Weinstein Stage (1-4) & Minervini Trend Template Preview
# ---------------------------------------------------------------------------

def compute_trend_stage_preview(
    daily_df: pd.DataFrame,
    weekly_completed_df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Compute Weinstein Stage (1-4) from completed weekly bars (30-week SMA & slope)
    and Minervini 8-Point Trend Template checklist on daily bars.
    """
    if daily_df is None or len(daily_df) < 260:
        return {
            "eligible": False,
            "status": "insufficient_history",
            "message": f"Insufficient history ({0 if daily_df is None else len(daily_df)} daily bars; requires >= 260).",
            "weinstein_stage": None,
            "stage_label": "Insufficient History",
            "minervini_passed": None,
            "minervini_total": 8,
        }

    close_d = daily_df["Close"].astype(float)
    sma50 = compute_sma(close_d, 50)
    sma150 = compute_sma(close_d, 150)
    sma200 = compute_sma(close_d, 200)

    c_now = float(close_d.iloc[-1])
    s50 = float(sma50.iloc[-1])
    s150 = float(sma150.iloc[-1])
    s200 = float(sma200.iloc[-1])
    s200_20d_ago = float(sma200.iloc[-21]) if len(sma200.dropna()) >= 21 else s200

    trail_252 = daily_df.iloc[-252:]
    low_52w = float(trail_252["Low"].min())
    high_52w = float(trail_252["High"].max())

    checks = [
        {"id": 1, "label": "Price > 150-DMA", "passed": bool(c_now > s150)},
        {"id": 2, "label": "Price > 200-DMA", "passed": bool(c_now > s200)},
        {"id": 3, "label": "150-DMA > 200-DMA", "passed": bool(s150 > s200)},
        {"id": 4, "label": "200-DMA rising (>= 20 sessions)", "passed": bool(s200 > s200_20d_ago)},
        {"id": 5, "label": "50-DMA > 150-DMA & 200-DMA", "passed": bool(s50 > s150 and s50 > s200)},
        {"id": 6, "label": "Price > 50-DMA", "passed": bool(c_now > s50)},
        {"id": 7, "label": "Price >= 30% above 52W Low", "passed": bool(c_now >= 1.30 * low_52w)},
        {"id": 8, "label": "Price within 25% of 52W High", "passed": bool(c_now >= 0.75 * high_52w)},
    ]
    minervini_passed = sum(1 for ch in checks if ch["passed"])

    # Weinstein 30-week SMA on completed weekly bars
    if weekly_completed_df is not None and len(weekly_completed_df) >= 34:
        w_close = weekly_completed_df["Close"].astype(float)
        sma30w = compute_sma(w_close, 30)
        w_now = float(w_close.iloc[-1])
        ma30_now = float(sma30w.iloc[-1])
        ma30_4w_ago = float(sma30w.iloc[-5]) if len(sma30w.dropna()) >= 5 else ma30_now
        slope_4w_pct = ((ma30_now - ma30_4w_ago) / max(1e-6, ma30_4w_ago)) * 100.0
    else:
        w_now = c_now
        ma30_now = s150
        s150_20d_ago = float(sma150.iloc[-21]) if len(sma150.dropna()) >= 21 else s150
        slope_4w_pct = ((s150 - s150_20d_ago) / max(1e-6, s150_20d_ago)) * 100.0

    if w_now > ma30_now and slope_4w_pct > 0.15:
        stage_num = 2
        stage_label = "Stage 2 · Advancing"
    elif w_now < ma30_now and slope_4w_pct < -0.15:
        stage_num = 4
        stage_label = "Stage 4 · Declining"
    elif w_now < ma30_now and slope_4w_pct >= -0.15:
        stage_num = 3 if c_now >= s200 else 1
        stage_label = "Stage 3 · Topping / Distribution" if stage_num == 3 else "Stage 1 · Basing / Accumulation"
    else:
        stage_num = 1 if slope_4w_pct <= 0.15 and c_now < s200 * 1.05 else 3
        stage_label = "Stage 1 · Basing / Accumulation" if stage_num == 1 else "Stage 3 · Topping / Distribution"

    price_vs_sma200_pct = ((c_now - s200) / max(1e-6, s200)) * 100.0

    return {
        "eligible": True,
        "status": "available",
        "weinstein_stage": stage_num,
        "stage_label": stage_label,
        "sma30w": round(ma30_now, 2),
        "sma30w_slope_4w_pct": round(slope_4w_pct, 2),
        "sma200": round(s200, 2),
        "price_vs_sma200_pct": round(price_vs_sma200_pct, 2),
        "minervini_passed": int(minervini_passed),
        "minervini_total": 8,
        "minervini_checks": checks,
    }


# ---------------------------------------------------------------------------
# 7. Fixed-Risk Position Sizing Calculator (with Wrong-Side Stop Guardrail)
# ---------------------------------------------------------------------------

def compute_position_sizing(
    capital: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
    market: str = "US",
    max_weight_pct: float = 10.0,
    round_trip_cost_bps: Optional[float] = None,
    lot_size: int = 1,
) -> Dict[str, Any]:
    """
    Compute fixed-risk position size with wrong-side stop rejection, round-trip
    transaction cost friction (10 bps US / 30 bps IN default), whole-share/lot
    rounding, and max portfolio weight cap.
    """
    mkt = (market or "US").upper()
    tick_size = 0.05 if mkt == "IN" else 0.01
    default_bps = 30.0 if mkt == "IN" else 10.0
    cost_bps = float(round_trip_cost_bps) if round_trip_cost_bps is not None else default_bps

    def _round_tick(p: float) -> float:
        return round(round(p / tick_size) * tick_size, 2)

    if capital <= 0 or entry_price <= 0:
        return {
            "valid": False,
            "error": "Portfolio capital and entry price must be positive.",
        }

    entry_r = _round_tick(float(entry_price))
    stop_r = _round_tick(float(stop_price))

    if stop_r <= 0:
        return {
            "valid": False,
            "error": "Stop-loss price must be greater than zero.",
        }
    if stop_r >= entry_r:
        return {
            "valid": False,
            "wrong_side_stop": True,
            "error": f"Wrong-side stop: Stop price ({stop_r:.2f}) must be strictly below Entry price ({entry_r:.2f}) for a long position.",
        }

    risk_frac = max(0.0005, min(0.20, float(risk_pct) / 100.0))
    max_wt_frac = max(0.01, min(1.0, float(max_weight_pct) / 100.0))

    # Friction-adjusted effective entry and stop
    half_cost_frac = (cost_bps / 10000.0) / 2.0
    entry_eff = entry_r * (1.0 + half_cost_frac)
    stop_eff = stop_r * (1.0 - half_cost_frac)
    risk_per_share = entry_eff - stop_eff

    risk_budget_amt = capital * risk_frac
    max_position_amt = capital * max_wt_frac

    raw_shares_by_risk = int(math.floor(risk_budget_amt / risk_per_share))
    raw_shares_by_cap = int(math.floor(max_position_amt / entry_eff))

    lot = max(1, int(lot_size))
    shares_risk = (raw_shares_by_risk // lot) * lot
    shares_cap = (raw_shares_by_cap // lot) * lot

    final_shares = max(0, min(shares_risk, shares_cap))
    capped_by_weight = shares_cap < shares_risk

    position_value = round(final_shares * entry_r, 2)
    portfolio_weight_pct = round((position_value / capital) * 100.0, 2)
    estimated_round_trip_cost = round(final_shares * entry_r * (cost_bps / 10000.0), 2)
    max_loss_amt = round(final_shares * risk_per_share, 2)
    max_loss_pct = round((max_loss_amt / capital) * 100.0, 2)

    r_dist = entry_r - stop_r
    return {
        "valid": True,
        "wrong_side_stop": False,
        "market": mkt,
        "tick_size": tick_size,
        "lot_size": lot,
        "entry_price": entry_r,
        "stop_price": stop_r,
        "stop_distance_pct": round(((entry_r - stop_r) / entry_r) * 100.0, 2),
        "round_trip_cost_bps": cost_bps,
        "risk_per_share_net": round(risk_per_share, 4),
        "risk_budget_amount": round(risk_budget_amt, 2),
        "shares": int(final_shares),
        "shares_uncapped_by_weight": int(shares_risk),
        "capped_by_max_weight": bool(capped_by_weight),
        "position_value": position_value,
        "portfolio_weight_pct": portfolio_weight_pct,
        "estimated_round_trip_cost": estimated_round_trip_cost,
        "max_loss_amount": max_loss_amt,
        "max_loss_pct_of_capital": max_loss_pct,
        "targets": {
            "target_1r": _round_tick(entry_r + 1.0 * r_dist),
            "target_2r": _round_tick(entry_r + 2.0 * r_dist),
            "target_3r": _round_tick(entry_r + 3.0 * r_dist),
        },
    }


# ---------------------------------------------------------------------------
# 8. Serialization Helpers & Full Phase 1 `/api/technical/chart` Builder
# ---------------------------------------------------------------------------

def _series_to_nullable_list(s: pd.Series, decimals: int = 2) -> List[Optional[float]]:
    if s is None or s.empty:
        return []
    arr = s.to_numpy(dtype=float)
    return [None if (np.isnan(v) or np.isinf(v)) else round(float(v), decimals) for v in arr]


def build_ta_chart_payload(
    bundle: MarketHistoryBundle,
    timeframe: str = "1D",
    valuation_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the complete Phase 1 (`GET /api/technical/chart`) payload from a
    `MarketHistoryBundle` and optional DCF/DDM `valuation_context`.
    """
    tf = (timeframe or "1D").strip().upper()
    if tf not in ("1D", "1W", "1M"):
        tf = "1D"

    daily_df = bundle.ohlc_split
    if tf == "1W":
        chart_df = bundle.weekly_split
        calc_df = bundle.weekly_completed if not bundle.weekly_completed.empty else bundle.weekly_split
        is_forming_tf = bool(bundle.quality_metrics.get("is_forming_weekly_bar", False))
    elif tf == "1M":
        chart_df = bundle.monthly_split
        calc_df = bundle.monthly_completed if not bundle.monthly_completed.empty else bundle.monthly_split
        is_forming_tf = bool(bundle.quality_metrics.get("is_forming_monthly_bar", False))
    else:
        chart_df = daily_df
        calc_df = daily_df
        is_forming_tf = bool(bundle.is_forming_daily_bar)

    # Always compute daily ATR(14), confirmed daily swings/S/R, Volume Profile, and Trend Stage
    daily_atr14 = compute_atr_wilder(daily_df["High"], daily_df["Low"], daily_df["Close"], 14)
    latest_daily_atr = (
        round(float(daily_atr14.dropna().iloc[-1]), 2)
        if not daily_atr14.dropna().empty
        else None
    )
    latest_close = round(float(daily_df["Close"].iloc[-1]), 2)
    latest_atr_pct = (
        round((latest_daily_atr / latest_close) * 100.0, 2)
        if (latest_daily_atr is not None and latest_close > 0)
        else None
    )

    swings_sr = detect_confirmed_swings_and_sr(daily_df, daily_atr14)
    vp_data = compute_volume_profile(daily_df, num_bins=24, lookback=252)
    trend_stage = compute_trend_stage_preview(daily_df, bundle.weekly_completed)

    # Compute timeframe-specific overlay & pane series on `calc_df` (excluding forming W/M bar for indicators)
    # and align to `chart_df.index` so Lightweight Charts renders every bar cleanly
    c_series = calc_df["Close"].astype(float)
    h_series = calc_df["High"].astype(float)
    l_series = calc_df["Low"].astype(float)

    sma20 = compute_sma(c_series, 20).reindex(chart_df.index)
    sma50 = compute_sma(c_series, 50).reindex(chart_df.index)
    sma150 = compute_sma(c_series, 150).reindex(chart_df.index)
    sma200 = compute_sma(c_series, 200).reindex(chart_df.index)
    ema20 = compute_ema(c_series, 20).reindex(chart_df.index)
    ema50 = compute_ema(c_series, 50).reindex(chart_df.index)

    bb = compute_bollinger_bands(c_series, window=20, num_std=2.0)
    rsi14 = compute_rsi_wilder(c_series, period=14).reindex(chart_df.index)
    macd_dict = compute_macd(c_series, fast=12, slow=26, signal=9)
    atr_tf = compute_atr_wilder(h_series, l_series, c_series, period=14).reindex(chart_df.index)

    avwaps_raw = compute_anchored_vwaps(
        chart_df,
        swing_lows=swings_sr["swing_lows"] if tf == "1D" else None,
    )
    avwaps_out: Dict[str, Any] = {}
    for k, v in avwaps_raw.items():
        avwaps_out[k] = {
            "label": v["label"],
            "anchor_date": v["anchor_date"],
            "current_value": v["current_value"],
            "values": _series_to_nullable_list(v["series"], 2),
        }

    dates_list = [d.strftime("%Y-%m-%d") for d in chart_df.index]
    bars_list = [
        {
            "time": dates_list[i],
            "open": round(float(chart_df["Open"].iloc[i]), 2),
            "high": round(float(chart_df["High"].iloc[i]), 2),
            "low": round(float(chart_df["Low"].iloc[i]), 2),
            "close": round(float(chart_df["Close"].iloc[i]), 2),
            "volume": round(float(chart_df["Volume"].iloc[i]), 0),
        }
        for i in range(len(chart_df))
    ]

    # Headline Card 4: Fundamental Context (Reusing Active Valuation Outlook per R5/R6/D1)
    vc = valuation_context or {}
    fair_val = vc.get("fair_value")
    raw_verdict = vc.get("verdict") or "NEUTRAL"
    active_method = vc.get("active_method") or "Enterprise DCF (FCFF)"
    mc_sim_prices = vc.get("simulated_prices") or []
    mc_stats = vc.get("mc_stats") or {}
    mc_histogram = vc.get("mc_histogram")

    # Phase 2 Two-Stage Composite Score, Indicator Matrix, Regime Diagnostics & Classification Matrix
    from .ta_composite import build_ta_phase2_payload
    phase2_data = build_ta_phase2_payload(
        bundle,
        fair_value=float(fair_val) if fair_val is not None else None,
        verdict=raw_verdict,
    )
    comp_score = phase2_data["composite_score"]

    # Headline Card 1: Technical Condition (v0.2 Live Two-Stage Score + Coverage Gate)
    eligible_count = sum(1 for item in bundle.coverage.values() if item["eligible"])
    total_cov = len(bundle.coverage)
    technical_condition_card = {
        "status": "available" if comp_score["available"] else "unavailable",
        "headline": comp_score["condition_label"],
        "condition_short": comp_score["condition_short"],
        "condition_tone": comp_score["condition_tone"],
        "score_mtf": comp_score["score_mtf"],
        "score_d": comp_score["score_d"],
        "score_w": comp_score["score_w"],
        "score_m": comp_score["score_m"],
        "score_version": comp_score["score_version"],
        "badge": comp_score["score_version"],
        "top_bullish_contributors": comp_score["top_bullish_contributors"],
        "top_bearish_contributors": comp_score["top_bearish_contributors"],
        "eligible_features": eligible_count,
        "total_features": total_cov,
        "coverage_pct": comp_score["coverage_pct"],
        "daily_bars": bundle.observations,
        "weekly_bars": bundle.weekly_observations,
        "monthly_returns": bundle.monthly_return_observations,
    }

    # Headline Card 3: Key Levels (Support / Resistance / POC — "est. from daily bars")
    key_levels_card = {
        "nearest_support": swings_sr["nearest_support"],
        "nearest_resistance": swings_sr["nearest_resistance"],
        "poc_price": vp_data["poc_price"],
        "vah_price": vp_data["vah_price"],
        "val_price": vp_data["val_price"],
        "atr_14": latest_daily_atr,
        "atr_pct": latest_atr_pct,
        "approximation_label": "est. from daily bars",
    }

    if fair_val is not None and fair_val > 0 and latest_close > 0:
        prem_disc_pct = round(((latest_close - float(fair_val)) / float(fair_val)) * 100.0, 1)
        upside_to_fv_pct = round(((float(fair_val) - latest_close) / latest_close) * 100.0, 1)
        dist_atr = (
            round((latest_close - float(fair_val)) / latest_daily_atr, 2)
            if (latest_daily_atr and latest_daily_atr > 0)
            else None
        )
    else:
        prem_disc_pct = None
        upside_to_fv_pct = None
        dist_atr = None

    price_percentile: Optional[int] = None
    if mc_sim_prices and len(mc_sim_prices) > 0:
        arr_sim = np.asarray(mc_sim_prices, dtype=float)
        price_percentile = int(round(float(np.mean(arr_sim <= latest_close) * 100.0)))

    fundamental_context_card = {
        "available": bool(fair_val is not None),
        "active_method": active_method,
        "fair_value": round(float(fair_val), 2) if fair_val is not None else None,
        "current_price": latest_close,
        "premium_discount_pct": prem_disc_pct,
        "upside_to_fair_value_pct": upside_to_fv_pct,
        "distance_in_atr_units": dist_atr,
        "valuation_outlook_label": f"Valuation outlook: {raw_verdict}",
        "raw_verdict": raw_verdict,
        "price_percentile_in_mc": price_percentile,
        "price_percentile_caption": (
            f"Current price is at P{price_percentile} of simulated values"
            if price_percentile is not None
            else None
        ),
        "mc_stats": mc_stats,
        "mc_histogram": mc_histogram,
        "model_version": f"v{MODEL_VERSION}",
        "fair_value_line_label": (
            f"Model fair value ({active_method}, v{MODEL_VERSION}, {bundle.last_session or ''})"
            if fair_val is not None
            else None
        ),
    }

    # Default Position Sizing Preview (1% risk, 2x ATR(14) stop)
    default_stop = (
        round(max(0.05, latest_close - 2.0 * latest_daily_atr), 2)
        if latest_daily_atr
        else round(latest_close * 0.92, 2)
    )
    default_capital = 1_000_000.0 if bundle.market == "IN" else 100_000.0
    default_sizing = compute_position_sizing(
        capital=default_capital,
        risk_pct=1.0,
        entry_price=latest_close,
        stop_price=default_stop,
        market=bundle.market,
        max_weight_pct=10.0,
    )

    payload = {
        "timeframe": tf,
        "is_forming_timeframe_bar": is_forming_tf,
        "headline_cards": {
            "technical_condition": technical_condition_card,
            "trend_stage": trend_stage,
            "key_levels": key_levels_card,
            "fundamental_context": fundamental_context_card,
        },
        "chart": {
            "dates": dates_list,
            "bars": bars_list,
            "overlays": {
                "sma20": _series_to_nullable_list(sma20, 2),
                "sma50": _series_to_nullable_list(sma50, 2),
                "sma150": _series_to_nullable_list(sma150, 2),
                "sma200": _series_to_nullable_list(sma200, 2),
                "ema20": _series_to_nullable_list(ema20, 2),
                "ema50": _series_to_nullable_list(ema50, 2),
                "bollinger": {
                    "upper": _series_to_nullable_list(bb["upper"].reindex(chart_df.index), 2),
                    "middle": _series_to_nullable_list(bb["middle"].reindex(chart_df.index), 2),
                    "lower": _series_to_nullable_list(bb["lower"].reindex(chart_df.index), 2),
                    "pct_b": _series_to_nullable_list(bb["pct_b"].reindex(chart_df.index), 4),
                    "bandwidth": _series_to_nullable_list(bb["bandwidth"].reindex(chart_df.index), 4),
                },
                "avwap": avwaps_out,
            },
            "panes": {
                "rsi14": _series_to_nullable_list(rsi14, 2),
                "macd": {
                    "macd": _series_to_nullable_list(macd_dict["macd"].reindex(chart_df.index), 3),
                    "signal": _series_to_nullable_list(macd_dict["signal"].reindex(chart_df.index), 3),
                    "histogram": _series_to_nullable_list(macd_dict["histogram"].reindex(chart_df.index), 3),
                },
                "atr14": _series_to_nullable_list(atr_tf, 2),
            },
            "support_resistance": {
                "levels": swings_sr["levels"],
                "recent_swing_highs": swings_sr["swing_highs"][-8:],
                "recent_swing_lows": swings_sr["swing_lows"][-8:],
            },
            "volume_profile": vp_data,
            "corporate_actions": {
                "splits": bundle.splits,
                "dividends": bundle.dividends,
            },
        },
        "position_sizing_defaults": {
            "default_capital": default_capital,
            "default_risk_pct": 1.0,
            "default_max_weight_pct": 10.0,
            "default_cost_bps": 30.0 if bundle.market == "IN" else 10.0,
            "latest_close": latest_close,
            "atr_14": latest_daily_atr,
            "last_confirmed_swing_low": (
                swings_sr["swing_lows"][-1]["price"] if swings_sr["swing_lows"] else None
            ),
            "nearest_support_price": (
                swings_sr["nearest_support"]["price"] if swings_sr["nearest_support"] else None
            ),
            "default_calculation": default_sizing,
        },
        "phase2": phase2_data,
    }

    return build_technical_response_envelope(
        bundle,
        payload=payload,
        score_model="ta-score-v0.2",
        signal_defs="confirmed-bar-close-next-open",
        params={"timeframe": tf, "period": bundle.period_requested},
    )
