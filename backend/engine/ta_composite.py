"""
ValuationLabs Technical Analysis v0.2 — Two-Stage Composite Score,
Indicator Matrix, Statistical Regime Diagnostics, Relative Strength,
Wyckoff VSA Tags, and 3x4 Fundamental x Weinstein Classification Matrix.

Design invariants (Phase 2 of implementation_plan_v3.md):
- Stage A maps each indicator j to s_j in [-1.0, +1.0] via documented rules.
  One vote per concept across 6 fixed-weight pillars:
    1. Trend (25%): MA alignment (0.40), SMA200 slope (0.30), ADX +/-DI (0.30)
    2. Momentum (15%): RSI-14 (0.40), MACD-hist slope (0.35), ROC-63 (0.25)
    3. Volatility (10%): Bollinger %B (0.50), TTM Squeeze (0.50)
    4. Volume (20%): OBV slope t-stat (0.40), CMF-20 (0.30), Up/Down vol (0.30)
    5. Relative Strength (15%): Mansfield RS (0.60), 63D alpha t-stat (0.40)
    6. Structure (15%): Weinstein stage (0.40), Minervini template (0.30), VP pos (0.30)
- Stage B aggregates pillar scores P_k in [-1, +1] into S = 100 * sum(W_k * (P_k + 1) / 2).
  Multi-timeframe score S_MTF = 0.50 * S_D + 0.35 * S_W + 0.15 * S_M using
  completed weekly and monthly bars only.
- Coverage gate: each pillar needs >= 60% of its weight available and total
  available weight needs >= 70%. Otherwise returns "Score unavailable (coverage X%)".
- Labels always include Decision D1 prefix:
  "Technical condition: Bullish" (>= 60), "Technical condition: Neutral" (40..60),
  "Technical condition: Bearish" (<= 40).
- Diagnostics are reported separately and never folded into the composite score:
  Hurst DFA-1 (504 bars, scales 10-126, block-bootstrap 95% CI, 10-day hysteresis),
  Lo-MacKinlay VR(2, 5, 10, 20) with heteroskedasticity-robust z* + Chow-Denning joint test,
  Yang-Zhang volatility (20D/60D annualized %) with 1Y/5Y empirical percentiles.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .market_history import MarketHistoryBundle
from .ta_indicators import (
    compute_atr_wilder,
    compute_bollinger_bands,
    compute_ema,
    compute_macd,
    compute_rsi_wilder,
    compute_sma,
    compute_trend_stage_preview,
    compute_volume_profile,
    detect_confirmed_swings_and_sr,
)

TA_SCORE_VERSION = "ta-score-v0.2"

PILLAR_WEIGHTS: Dict[str, float] = {
    "trend": 0.25,
    "momentum": 0.15,
    "volatility": 0.10,
    "volume": 0.20,
    "relative_strength": 0.15,
    "structure": 0.15,
}

PILLAR_LABELS: Dict[str, str] = {
    "trend": "Trend Structure",
    "momentum": "Momentum & Velocity",
    "volatility": "Volatility & Compression",
    "volume": "Institutional Volume Flow",
    "relative_strength": "Benchmark Relative Strength",
    "structure": "Stage & Volume Acceptance",
}


def _clamp(val: float, lo: float = -1.0, hi: float = 1.0) -> float:
    if not np.isfinite(val):
        return 0.0
    return float(max(lo, min(hi, val)))


def _last_valid(arr: Any) -> Optional[float]:
    if arr is None:
        return None
    if isinstance(arr, pd.Series):
        vals = arr.to_numpy(dtype=np.float64)
    else:
        vals = np.asarray(arr, dtype=np.float64)
    if len(vals) == 0:
        return None
    for idx in range(len(vals) - 1, -1, -1):
        v = vals[idx]
        if np.isfinite(v):
            return float(v)
    return None


# ============================================================================
# 1. ADDITIONAL STAGE-A TECHNICAL INDICATORS (ADX, OBV, CMF, UP/DOWN VOL, SQUEEZE)
# ============================================================================

def compute_adx_wilder(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> Dict[str, np.ndarray]:
    """
    Wilder's Directional Movement System: +DI(14), -DI(14), ADX(14).
    """
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)

    plus_di = np.full(n, np.nan, dtype=np.float64)
    minus_di = np.full(n, np.nan, dtype=np.float64)
    adx = np.full(n, np.nan, dtype=np.float64)

    if n < 2 * period + 1:
        return {"plus_di": plus_di, "minus_di": minus_di, "adx": adx}

    tr = np.zeros(n, dtype=np.float64)
    up_move = np.zeros(n, dtype=np.float64)
    down_move = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        hl = h[i] - l[i]
        hc = abs(h[i] - c[i - 1])
        lc = abs(l[i] - c[i - 1])
        tr[i] = max(hl, hc, lc)

        um = h[i] - h[i - 1]
        dm = l[i - 1] - l[i]
        up_move[i] = um if (um > dm and um > 0.0) else 0.0
        down_move[i] = dm if (dm > um and dm > 0.0) else 0.0

    tr_smooth = float(np.sum(tr[1 : period + 1]))
    plus_smooth = float(np.sum(up_move[1 : period + 1]))
    minus_smooth = float(np.sum(down_move[1 : period + 1]))

    dx = np.full(n, np.nan, dtype=np.float64)

    for i in range(period, n):
        if i > period:
            tr_smooth = tr_smooth - (tr_smooth / period) + tr[i]
            plus_smooth = plus_smooth - (plus_smooth / period) + up_move[i]
            minus_smooth = minus_smooth - (minus_smooth / period) + down_move[i]

        p_di = 100.0 * (plus_smooth / tr_smooth) if tr_smooth > 1e-12 else 0.0
        m_di = 100.0 * (minus_smooth / tr_smooth) if tr_smooth > 1e-12 else 0.0
        plus_di[i] = p_di
        minus_di[i] = m_di
        denom = p_di + m_di
        dx[i] = 100.0 * abs(p_di - m_di) / denom if denom > 1e-12 else 0.0

    start_adx = 2 * period - 1
    if start_adx < n:
        adx[start_adx] = float(np.nanmean(dx[period : start_adx + 1]))
        for i in range(start_adx + 1, n):
            adx[i] = ((period - 1) * adx[i - 1] + dx[i]) / period

    return {"plus_di": plus_di, "minus_di": minus_di, "adx": adx}


def compute_obv_slope_tstat(
    close: np.ndarray,
    volume: np.ndarray,
    window: int = 20,
) -> Optional[float]:
    """
    Computes On-Balance Volume (OBV) and returns the OLS slope t-statistic
    over the last `window` bars.
    """
    c = np.asarray(close, dtype=np.float64)
    v = np.asarray(volume, dtype=np.float64)
    n = len(c)
    if n < window + 1 or np.nansum(v[-window:]) <= 0:
        return None

    obv = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        if c[i] > c[i - 1]:
            obv[i] = obv[i - 1] + v[i]
        elif c[i] < c[i - 1]:
            obv[i] = obv[i - 1] - v[i]
        else:
            obv[i] = obv[i - 1]

    y = obv[-window:]
    x = np.arange(window, dtype=np.float64)
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    sxx = float(np.sum((x - x_mean) ** 2))
    if sxx <= 1e-12:
        return 0.0
    slope = float(np.sum((x - x_mean) * (y - y_mean)) / sxx)
    residuals = y - (y_mean + slope * (x - x_mean))
    dof = max(1, window - 2)
    s2 = float(np.sum(residuals ** 2) / dof)
    se_slope = math.sqrt(max(s2 / sxx, 1e-18))
    if se_slope <= 1e-8:
        return 0.0 if abs(slope) <= 1e-8 else float(np.sign(slope) * 5.0)
    return float(slope / se_slope)


def compute_cmf(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    period: int = 20,
) -> Optional[float]:
    """
    Chaikin Money Flow CMF(20) over the last `period` bars.
    """
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    v = np.asarray(volume, dtype=np.float64)
    if len(c) < period:
        return None
    h_w = h[-period:]
    l_w = l[-period:]
    c_w = c[-period:]
    v_w = v[-period:]
    vol_sum = float(np.nansum(v_w))
    if vol_sum <= 0:
        return None
    hl_range = np.where((h_w - l_w) > 1e-12, h_w - l_w, 1.0)
    mf_mult = np.where((h_w - l_w) > 1e-12, ((c_w - l_w) - (h_w - c_w)) / hl_range, 0.0)
    mf_vol = mf_mult * v_w
    return float(np.nansum(mf_vol) / vol_sum)


def compute_up_down_volume_ratio(
    close: np.ndarray,
    volume: np.ndarray,
    period: int = 50,
) -> Optional[float]:
    """
    Up-Volume / Down-Volume ratio over trailing `period` bars.
    """
    c = np.asarray(close, dtype=np.float64)
    v = np.asarray(volume, dtype=np.float64)
    if len(c) < period + 1:
        return None
    diffs = np.diff(c[-(period + 1) :])
    vols = v[-period:]
    if float(np.nansum(vols)) <= 0:
        return None
    up_vol = float(np.nansum(vols[diffs > 0]))
    down_vol = float(np.nansum(vols[diffs < 0]))
    if down_vol <= 1e-9:
        return 2.5 if up_vol > 0 else 1.0
    return float(up_vol / down_vol)


def compute_ttm_squeeze(
    df: pd.DataFrame,
    period: int = 20,
    bb_mult: float = 2.0,
    kc_mult: float = 1.5,
) -> Optional[Dict[str, Any]]:
    """
    TTM / Carter Volatility Squeeze:
    - Bollinger Bands (20, 2.0) vs Keltner Channels (20 EMA +/- 1.5 * ATR(14)).
    - Squeeze ON when BB_upper < KC_upper and BB_lower > KC_lower.
    """
    if df is None or len(df) < period + 5:
        return None
    c_ser = df["Close"].astype(float)
    h_ser = df["High"].astype(float)
    l_ser = df["Low"].astype(float)

    bb = compute_bollinger_bands(c_ser, window=period, num_std=bb_mult)
    ema20 = compute_ema(c_ser, span=period)
    atr14 = compute_atr_wilder(h_ser, l_ser, c_ser, period=14)

    bb_u = _last_valid(bb["upper"])
    bb_l = _last_valid(bb["lower"])
    kc_mid = _last_valid(ema20)
    atr_v = _last_valid(atr14)
    if bb_u is None or bb_l is None or kc_mid is None or atr_v is None or atr_v <= 0:
        return None

    kc_u = kc_mid + kc_mult * atr_v
    kc_l = kc_mid - kc_mult * atr_v
    squeeze_on = bool(bb_u < kc_u and bb_l > kc_l)

    bb_u_arr = bb["upper"].to_numpy(dtype=np.float64)
    bb_l_arr = bb["lower"].to_numpy(dtype=np.float64)
    ema_arr = ema20.to_numpy(dtype=np.float64)
    atr_arr = atr14.to_numpy(dtype=np.float64)

    recent_squeeze_bars = 0
    for idx in range(max(period, len(df) - 6), len(df)):
        if (
            np.isfinite(bb_u_arr[idx])
            and np.isfinite(ema_arr[idx])
            and np.isfinite(atr_arr[idx])
        ):
            ku = ema_arr[idx] + kc_mult * atr_arr[idx]
            kl = ema_arr[idx] - kc_mult * atr_arr[idx]
            if bb_u_arr[idx] < ku and bb_l_arr[idx] > kl:
                recent_squeeze_bars += 1

    squeeze_released = (not squeeze_on) and (recent_squeeze_bars > 0)

    hh = float(h_ser.iloc[-period:].max())
    ll = float(l_ser.iloc[-period:].min())
    mid_anchor = 0.5 * (0.5 * (hh + ll) + kc_mid)
    mom_val = (float(c_ser.iloc[-1]) - mid_anchor) / atr_v

    return {
        "squeeze_on": squeeze_on,
        "squeeze_released": squeeze_released,
        "recent_squeeze_bars": recent_squeeze_bars,
        "momentum_atr": round(float(mom_val), 3),
        "bb_width_pct": round(float((_last_valid(bb["bandwidth"]) or 0.0) * 100.0), 2),
    }


# ============================================================================
# 2. BENCHMARK RELATIVE STRENGTH, MANSFIELD RS & ROLLING ALPHA / BETA
# ============================================================================

def compute_relative_strength_suite(
    stock_df: pd.DataFrame,
    benchmark_close: Optional[pd.Series],
    benchmark_symbol: str = "^GSPC",
    timeframe: str = "1D",
) -> Dict[str, Any]:
    """
    Computes:
    - Mansfield Relative Strength:
        RS_t = Stock_Close_t / Bench_Close_t
        Mansfield_RS_t = 100 * (RS_t / SMA_N(RS)_t - 1)
      where N = 252 (Daily), 52 (Weekly), 12 (Monthly).
    - Rolling 63-day (or timeframe-equivalent) Jensen's alpha, alpha t-stat, and beta
      against benchmark log returns.
    - 1M, 3M, 6M, 1Y excess return vs benchmark.
    """
    bench_label = "NIFTY 50 (^NSEI)" if "NSEI" in str(benchmark_symbol).upper() else "S&P 500 (^GSPC)"
    empty_res: Dict[str, Any] = {
        "available": False,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_label": bench_label,
        "mansfield_rs": None,
        "mansfield_ma_bars": 252 if timeframe == "1D" else (52 if timeframe == "1W" else 12),
        "rs_ratio_norm": [],
        "alpha_63d_annualized_pct": None,
        "alpha_63d_tstat": None,
        "beta_63d": None,
        "beta_252d": None,
        "r_squared_63d": None,
        "excess_returns_pct": {},
    }
    if benchmark_close is None or benchmark_close.empty or stock_df is None or stock_df.empty:
        return empty_res

    s_ser = pd.Series(stock_df["Close"].astype(float).values, index=pd.to_datetime(stock_df.index)).dropna()
    b_raw = pd.Series(benchmark_close.astype(float).values, index=pd.to_datetime(benchmark_close.index)).dropna()

    if timeframe == "1W":
        b_ser = b_raw.resample("W-FRI").last().dropna()
    elif timeframe == "1M":
        try:
            b_ser = b_raw.resample("ME").last().dropna()
        except ValueError:
            b_ser = b_raw.resample("M").last().dropna()
    else:
        b_ser = b_raw

    joined = pd.concat([s_ser.rename("stock"), b_ser.rename("bench")], axis=1, join="inner").dropna()
    joined = joined[(joined["stock"] > 0) & (joined["bench"] > 0)]

    if len(joined) < 15:
        return empty_res

    rs_raw = joined["stock"] / joined["bench"]
    dates = [d.strftime("%Y-%m-%d") for d in joined.index]

    ma_period = 252 if timeframe == "1D" else (52 if timeframe == "1W" else 12)
    rs_sma = compute_sma(rs_raw, ma_period)

    mansfield_ser = 100.0 * ((rs_raw / rs_sma) - 1.0)
    mansfield_latest = _last_valid(mansfield_ser) if len(rs_raw) >= ma_period else None

    lookback_norm = min(len(rs_raw), 252)
    base_rs = float(rs_raw.iloc[-lookback_norm]) if float(rs_raw.iloc[-lookback_norm]) > 0 else float(rs_raw.iloc[0])
    rs_arr = rs_raw.to_numpy(dtype=np.float64)
    mf_arr = mansfield_ser.to_numpy(dtype=np.float64)
    rs_norm_tail = [
        {
            "time": dates[i],
            "rs_indexed": round(float(100.0 * rs_arr[i] / base_rs), 2),
            "mansfield": round(float(mf_arr[i]), 2) if np.isfinite(mf_arr[i]) else None,
        }
        for i in range(max(0, len(rs_arr) - 252), len(rs_arr))
    ]

    s_ret = np.diff(np.log(joined["stock"].to_numpy(dtype=np.float64)))
    b_ret = np.diff(np.log(joined["bench"].to_numpy(dtype=np.float64)))

    reg_win = 63 if timeframe == "1D" else (26 if timeframe == "1W" else 12)
    ann_factor = 252.0 if timeframe == "1D" else (52.0 if timeframe == "1W" else 12.0)

    alpha_ann_pct: Optional[float] = None
    alpha_tstat: Optional[float] = None
    beta_63: Optional[float] = None
    r2_63: Optional[float] = None

    if len(s_ret) >= reg_win:
        y = s_ret[-reg_win:]
        x = b_ret[-reg_win:]
        x_mean = float(np.mean(x))
        y_mean = float(np.mean(y))
        sxx = float(np.sum((x - x_mean) ** 2))
        syy = float(np.sum((y - y_mean) ** 2))
        if sxx > 1e-12:
            beta_hat = float(np.sum((x - x_mean) * (y - y_mean)) / sxx)
            alpha_hat = y_mean - beta_hat * x_mean
            resid = y - (alpha_hat + beta_hat * x)
            dof = max(1, reg_win - 2)
            s2 = float(np.sum(resid ** 2) / dof)
            se_alpha = math.sqrt(max(s2 * (1.0 / reg_win + (x_mean ** 2) / sxx), 1e-18))
            alpha_tstat = float(alpha_hat / se_alpha)
            alpha_ann_pct = float((math.exp(alpha_hat * ann_factor) - 1.0) * 100.0)
            beta_63 = beta_hat
            r2_63 = float(1.0 - np.sum(resid ** 2) / syy) if syy > 1e-12 else 0.0

    beta_252: Optional[float] = None
    if len(s_ret) >= 252:
        y252 = s_ret[-252:]
        x252 = b_ret[-252:]
        xm = float(np.mean(x252))
        ym = float(np.mean(y252))
        sxx252 = float(np.sum((x252 - xm) ** 2))
        if sxx252 > 1e-12:
            beta_252 = float(np.sum((x252 - xm) * (y252 - ym)) / sxx252)

    excess_returns: Dict[str, Dict[str, float]] = {}
    if timeframe == "1D":
        for label, bars in [("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252)]:
            if len(joined) > bars:
                s_r = float((joined["stock"].iloc[-1] / joined["stock"].iloc[-(bars + 1)] - 1.0) * 100.0)
                b_r = float((joined["bench"].iloc[-1] / joined["bench"].iloc[-(bars + 1)] - 1.0) * 100.0)
                excess_returns[label] = {
                    "stock_pct": round(s_r, 2),
                    "benchmark_pct": round(b_r, 2),
                    "excess_pct": round(s_r - b_r, 2),
                }

    return {
        "available": True,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_label": bench_label,
        "mansfield_rs": round(mansfield_latest, 2) if mansfield_latest is not None else None,
        "mansfield_ma_bars": ma_period,
        "rs_ratio_norm": rs_norm_tail,
        "alpha_63d_annualized_pct": round(alpha_ann_pct, 2) if alpha_ann_pct is not None else None,
        "alpha_63d_tstat": round(alpha_tstat, 2) if alpha_tstat is not None else None,
        "beta_63d": round(beta_63, 2) if beta_63 is not None else None,
        "beta_252d": round(beta_252, 2) if beta_252 is not None else None,
        "r_squared_63d": round(r2_63, 3) if r2_63 is not None else None,
        "excess_returns_pct": excess_returns,
    }


# ============================================================================
# 3. STATISTICAL REGIME DIAGNOSTICS (HURST DFA-1, LO-MACKINLAY VR, YANG-ZHANG)
# ============================================================================

def _dfa1_hurst_single(returns: np.ndarray, scales: np.ndarray) -> float:
    """
    Computes the Detrended Fluctuation Analysis (DFA-1) scaling exponent H
    over an array of demeaned log returns for given integer window scales.
    """
    y = np.cumsum(returns - np.mean(returns))
    n = len(y)
    fluct = []
    valid_scales = []

    for s in scales:
        s_int = int(s)
        n_seg = n // s_int
        if n_seg < 2:
            continue
        rms_vals = []
        x = np.arange(s_int, dtype=np.float64)
        xm = 0.5 * (s_int - 1)
        x_centered = x - xm
        sxx = float(np.sum(x_centered ** 2))
        if sxx <= 0:
            continue

        for seg in range(n_seg):
            seg_y = y[seg * s_int : (seg + 1) * s_int]
            ym = float(np.mean(seg_y))
            slope = float(np.dot(x_centered, seg_y - ym) / sxx)
            trend = ym + slope * x_centered
            rms_vals.append(float(np.mean((seg_y - trend) ** 2)))

        for seg in range(n_seg):
            start = n - (seg + 1) * s_int
            seg_y = y[start : start + s_int]
            ym = float(np.mean(seg_y))
            slope = float(np.dot(x_centered, seg_y - ym) / sxx)
            trend = ym + slope * x_centered
            rms_vals.append(float(np.mean((seg_y - trend) ** 2)))

        f_s = math.sqrt(max(float(np.mean(rms_vals)), 1e-18))
        fluct.append(math.log(f_s))
        valid_scales.append(math.log(float(s_int)))

    if len(valid_scales) < 3:
        return 0.5
    lx = np.asarray(valid_scales, dtype=np.float64)
    ly = np.asarray(fluct, dtype=np.float64)
    lxm = float(np.mean(lx))
    lym = float(np.mean(ly))
    denom = float(np.sum((lx - lxm) ** 2))
    if denom <= 1e-12:
        return 0.5
    return float(np.sum((lx - lxm) * (ly - lym)) / denom)


def compute_hurst_dfa1(
    close: np.ndarray,
    window: int = 504,
    min_scale: int = 10,
    max_scale: int = 126,
    n_bootstrap: int = 120,
    block_size: int = 20,
    hysteresis_days: int = 10,
) -> Dict[str, Any]:
    """
    Hurst Exponent via DFA-1 on 504 daily bars:
    - Scales 10..126 (logarithmically spaced).
    - Moving-block bootstrap (B=120, block=20, seeded deterministically) for 95% CI.
    - Reports "Indeterminate" when the 95% CI contains 0.50.
    - Applies 10-day hysteresis check by comparing current H vs 10-bars-ago H.
    """
    c = np.asarray(close, dtype=np.float64)
    c = c[np.isfinite(c) & (c > 0)]
    if len(c) < window + 1:
        return {
            "available": False,
            "reason": f"Requires {window + 1} daily bars (found {len(c)})",
            "hurst": None,
            "ci_95": [None, None],
            "regime": "Unavailable (< 2Y history)",
            "hysteresis_days": hysteresis_days,
        }

    log_ret_all = np.diff(np.log(c))
    ret_win = log_ret_all[-window:]

    scales = np.unique(
        np.round(np.geomspace(min_scale, max_scale, num=12)).astype(int)
    )
    h_est = _dfa1_hurst_single(ret_win, scales)

    rng = np.random.default_rng(42)
    n_blocks = int(math.ceil(window / block_size))
    max_start = window - block_size
    boot_h = np.empty(n_bootstrap, dtype=np.float64)
    for b in range(n_bootstrap):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        sampled = np.concatenate([ret_win[s : s + block_size] for s in starts])[:window]
        boot_h[b] = _dfa1_hurst_single(sampled, scales)

    ci_low = float(np.percentile(boot_h, 2.5))
    ci_high = float(np.percentile(boot_h, 97.5))

    h_prev = h_est
    if len(log_ret_all) >= window + hysteresis_days:
        ret_prev = log_ret_all[-(window + hysteresis_days) : -hysteresis_days]
        h_prev = _dfa1_hurst_single(ret_prev, scales)

    ci_spans_half = bool(ci_low <= 0.50 <= ci_high)
    if ci_spans_half:
        regime = "Indeterminate (95% CI spans 0.50)"
        state_code = "indeterminate"
    elif h_est > 0.50 and h_prev > 0.50:
        regime = "Persistent / Trending (H > 0.50)"
        state_code = "persistent"
    elif h_est < 0.50 and h_prev < 0.50:
        regime = "Mean-Reverting / Anti-Persistent (H < 0.50)"
        state_code = "mean_reverting"
    else:
        regime = "Indeterminate (10D Hysteresis Transition)"
        state_code = "indeterminate"

    return {
        "available": True,
        "hurst": round(float(h_est), 3),
        "hurst_10d_ago": round(float(h_prev), 3),
        "ci_95": [round(ci_low, 3), round(ci_high, 3)],
        "ci_spans_050": ci_spans_half,
        "regime": regime,
        "state_code": state_code,
        "window_bars": window,
        "scales_range": [int(scales[0]), int(scales[-1])],
        "hysteresis_days": hysteresis_days,
    }


def compute_lo_mackinlay_vr(
    close: np.ndarray,
    window: int = 504,
    lags: Tuple[int, ...] = (2, 5, 10, 20),
) -> Dict[str, Any]:
    """
    Lo-MacKinlay (1988) Overlapping Variance Ratio Test VR(q) for q in {2, 5, 10, 20}
    with heteroskedasticity-robust z*(q) statistic and Chow-Denning (1993) joint test.
    """
    c = np.asarray(close, dtype=np.float64)
    c = c[np.isfinite(c) & (c > 0)]
    if len(c) < 126:
        return {
            "available": False,
            "reason": f"Requires >= 126 daily bars (found {len(c)})",
            "profiles": [],
            "chow_denning_stat": None,
            "chow_denning_crit_95": 2.491,
            "joint_verdict": "Unavailable",
        }

    log_p = np.log(c[-(min(len(c), window + 1)) :])
    ret_1 = np.diff(log_p)
    n = len(ret_1)
    mu = float(np.mean(ret_1))
    dev_1 = ret_1 - mu
    sigma2_1 = float(np.sum(dev_1 ** 2) / (n - 1))
    if sigma2_1 <= 1e-18:
        return {
            "available": False,
            "reason": "Zero return variance",
            "profiles": [],
            "chow_denning_stat": None,
            "chow_denning_crit_95": 2.491,
            "joint_verdict": "Unavailable",
        }

    profiles: List[Dict[str, Any]] = []
    max_abs_z = 0.0
    dominant_z = 0.0

    denom_d = float(np.sum(dev_1 ** 2)) ** 2
    for q in lags:
        if n <= q + 2:
            continue
        ret_q = log_p[q:] - log_p[:-q]
        m = q * (n - q + 1) * (1.0 - q / n)
        sigma2_q = float(np.sum((ret_q - q * mu) ** 2) / m)
        vr_q = sigma2_q / sigma2_1

        # Lo-MacKinlay (1988) Eq. (20)-(21):
        # delta_hat(j) = n * sum_{t=j+1}^n dev_t^2 dev_{t-j}^2 / (sum dev_t^2)^2
        # theta(q) = sum_{j=1}^{q-1} [2(q-j)/q]^2 delta_hat(j)
        # z*(q) = sqrt(n) * (VR(q) - 1) / sqrt(theta(q))
        theta_q = 0.0
        for j in range(1, q):
            num_j = float(np.sum((dev_1[j:] ** 2) * (dev_1[:-j] ** 2)))
            delta_j = (n * num_j) / denom_d if denom_d > 1e-18 else 0.0
            weight_j = (2.0 * (q - j) / q) ** 2
            theta_q += weight_j * delta_j

        z_star = math.sqrt(n) * (vr_q - 1.0) / math.sqrt(max(theta_q, 1e-18)) if theta_q > 0 else 0.0
        if abs(z_star) > max_abs_z:
            max_abs_z = abs(z_star)
            dominant_z = z_star

        profiles.append(
            {
                "q": int(q),
                "vr": round(float(vr_q), 3),
                "z_star": round(float(z_star), 2),
                "significant_95": bool(abs(z_star) >= 1.96),
            }
        )

    crit_95 = 2.491
    if max_abs_z >= crit_95:
        if dominant_z > 0:
            joint_verdict = "Rejects Random Walk — Positive Autocorrelation / Momentum (VR > 1)"
        else:
            joint_verdict = "Rejects Random Walk — Mean Reversion (VR < 1)"
    else:
        joint_verdict = "Consistent with Martingale / Random Walk (|z*| < 2.49)"

    return {
        "available": True,
        "window_bars": int(n),
        "profiles": profiles,
        "chow_denning_stat": round(float(max_abs_z), 2),
        "chow_denning_crit_95": crit_95,
        "rejects_random_walk_95": bool(max_abs_z >= crit_95),
        "joint_verdict": joint_verdict,
    }


def compute_yang_zhang_volatility(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
) -> Dict[str, Any]:
    """
    Yang-Zhang (2000) minimum-variance unbiased OHLC volatility estimator
    for 20D and 60D windows (annualized %), with 1Y (252D) and 5Y (1260D)
    empirical percentile ranks.
    """
    o = np.asarray(open_, dtype=np.float64)
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)

    if n < 25:
        return {
            "available": False,
            "units": "% annualized",
            "yz_20d_pct": None,
            "yz_60d_pct": None,
            "pct_rank_1y": None,
            "pct_rank_5y": None,
        }

    prev_c = np.where(c[:-1] > 0, c[:-1], np.nan)
    curr_o = np.where(o[1:] > 0, o[1:], np.nan)
    curr_h = np.where(h[1:] > 0, h[1:], np.nan)
    curr_l = np.where(l[1:] > 0, l[1:], np.nan)
    curr_c = np.where(c[1:] > 0, c[1:], np.nan)

    log_oc_overnight = np.log(curr_o / prev_c)
    log_co_intraday = np.log(curr_c / curr_o)
    log_ho = np.log(curr_h / curr_o)
    log_lo = np.log(curr_l / curr_o)
    log_hc = np.log(curr_h / curr_c)
    log_lc = np.log(curr_l / curr_c)
    rs_var_daily = log_ho * log_hc + log_lo * log_lc

    def _rolling_yz(win: int) -> np.ndarray:
        m = len(log_oc_overnight)
        out = np.full(m, np.nan, dtype=np.float64)
        if m < win:
            return out
        k = 0.34 / (1.34 + (win + 1.0) / (win - 1.0))
        for i in range(win - 1, m):
            vo = float(np.nanvar(log_oc_overnight[i - win + 1 : i + 1], ddof=1))
            vc = float(np.nanvar(log_co_intraday[i - win + 1 : i + 1], ddof=1))
            vrs = float(np.nanmean(rs_var_daily[i - win + 1 : i + 1]))
            yz_var = max(0.0, vo + k * vc + (1.0 - k) * vrs)
            out[i] = math.sqrt(yz_var * 252.0) * 100.0
        return out

    yz20_series = _rolling_yz(20)
    yz60_series = _rolling_yz(60)

    yz20_now = _last_valid(yz20_series)
    yz60_now = _last_valid(yz60_series)

    valid_20 = yz20_series[np.isfinite(yz20_series)]
    pct_1y: Optional[float] = None
    pct_5y: Optional[float] = None
    if yz20_now is not None and len(valid_20) >= 40:
        tail_1y = valid_20[-min(len(valid_20), 252) :]
        pct_1y = float(np.mean(tail_1y <= yz20_now) * 100.0)
    if yz20_now is not None and len(valid_20) >= 504:
        tail_5y = valid_20[-min(len(valid_20), 1260) :]
        pct_5y = float(np.mean(tail_5y <= yz20_now) * 100.0)

    regime_label = "Normal Volatility"
    if pct_1y is not None:
        if pct_1y >= 80.0:
            regime_label = "High Volatility Expansion (>= 80th pct)"
        elif pct_1y <= 20.0:
            regime_label = "Low Volatility Compression (<= 20th pct)"

    return {
        "available": yz20_now is not None,
        "units": "% annualized",
        "yz_20d_pct": round(yz20_now, 2) if yz20_now is not None else None,
        "yz_60d_pct": round(yz60_now, 2) if yz60_now is not None else None,
        "pct_rank_1y": round(pct_1y, 1) if pct_1y is not None else None,
        "pct_rank_5y": round(pct_5y, 1) if pct_5y is not None else None,
        "regime_label": regime_label,
    }


# ============================================================================
# 4. DOW THEORY HH/HL & WYCKOFF VOLUME-SPREAD ANALYSIS (VSA) TAGS
# ============================================================================

def compute_dow_structure_and_wyckoff(
    daily_df: pd.DataFrame,
    atr_series: pd.Series,
) -> Dict[str, Any]:
    """
    Computes:
    1. Causal Dow Theory structure (HH/HL Uptrend, LH/LL Downtrend, Consolidation)
       from confirmed 5-bar fractal swing highs and lows.
    2. Wyckoff Volume-Spread Analysis (VSA) tags on recent bars (last 60 bars).
    """
    swings_sr = detect_confirmed_swings_and_sr(daily_df, atr_series)
    highs = swings_sr["swing_highs"]
    lows = swings_sr["swing_lows"]

    dow_state = "Consolidation / Transition"
    dow_detail = "Awaiting two confirmed swing highs and swing lows."
    last_two_highs: List[Dict[str, Any]] = highs[-2:] if len(highs) >= 2 else highs
    last_two_lows: List[Dict[str, Any]] = lows[-2:] if len(lows) >= 2 else lows

    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1]["price"] > highs[-2]["price"]
        hl = lows[-1]["price"] > lows[-2]["price"]
        lh = highs[-1]["price"] < highs[-2]["price"]
        ll = lows[-1]["price"] < lows[-2]["price"]
        if hh and hl:
            dow_state = "Primary Uptrend (HH + HL)"
            dow_detail = (
                f"Higher High ({highs[-2]['price']:.2f} → {highs[-1]['price']:.2f}) "
                f"& Higher Low ({lows[-2]['price']:.2f} → {lows[-1]['price']:.2f})"
            )
        elif lh and ll:
            dow_state = "Primary Downtrend (LH + LL)"
            dow_detail = (
                f"Lower High ({highs[-2]['price']:.2f} → {highs[-1]['price']:.2f}) "
                f"& Lower Low ({lows[-2]['price']:.2f} → {lows[-1]['price']:.2f})"
            )
        elif hh and ll:
            dow_state = "Broadening / Volatile Expansion (HH + LL)"
            dow_detail = "Expanding swing range across recent confirmed pivots."
        else:
            dow_state = "Coiling / Symmetrical Contraction (LH + HL)"
            dow_detail = "Converging swing highs and higher lows (volatility contraction)."

    n = len(daily_df)
    vsa_events: List[Dict[str, Any]] = []
    if n >= 25:
        vol_ser = daily_df["Volume"].astype(float)
        vol_sma20 = compute_sma(vol_ser, 20).to_numpy(dtype=np.float64)
        high_arr = daily_df["High"].to_numpy(dtype=np.float64)
        low_arr = daily_df["Low"].to_numpy(dtype=np.float64)
        close_arr = daily_df["Close"].to_numpy(dtype=np.float64)
        vol_arr = vol_ser.to_numpy(dtype=np.float64)
        atr_arr = atr_series.to_numpy(dtype=np.float64)
        dates = [d.strftime("%Y-%m-%d") for d in pd.to_datetime(daily_df.index)]

        start_idx = max(20, n - 60)
        for i in range(start_idx, n):
            v_avg = vol_sma20[i]
            atr_i = atr_arr[i]
            if not (np.isfinite(v_avg) and v_avg > 0 and np.isfinite(atr_i) and atr_i > 0):
                continue
            rel_vol = float(vol_arr[i] / v_avg)
            spread = float(high_arr[i] - low_arr[i])
            rel_spread = float(spread / atr_i)
            close_loc = float((close_arr[i] - low_arr[i]) / spread) if spread > 1e-9 else 0.5
            up_bar = close_arr[i] > close_arr[i - 1]

            if rel_vol >= 1.8 and rel_spread >= 1.25 and up_bar and close_loc >= 0.70:
                vsa_events.append(
                    {
                        "date": dates[i],
                        "tag": "Demand Breakout (Sign of Strength)",
                        "bias": "bullish",
                        "rel_volume": round(rel_vol, 2),
                        "rel_spread_atr": round(rel_spread, 2),
                        "detail": "Wide-spread up bar closing in top 30% on >= 1.8x volume.",
                    }
                )
            elif rel_vol >= 1.8 and (not up_bar) and close_loc >= 0.55 and rel_spread >= 0.9:
                vsa_events.append(
                    {
                        "date": dates[i],
                        "tag": "Stopping Volume (Absorption)",
                        "bias": "bullish",
                        "rel_volume": round(rel_vol, 2),
                        "rel_spread_atr": round(rel_spread, 2),
                        "detail": "High-volume down bar closing in upper half (institutional support absorption).",
                    }
                )
            elif rel_vol >= 1.8 and up_bar and close_loc <= 0.35 and rel_spread >= 1.1:
                vsa_events.append(
                    {
                        "date": dates[i],
                        "tag": "Upthrust / Supply Rejection",
                        "bias": "bearish",
                        "rel_volume": round(rel_vol, 2),
                        "rel_spread_atr": round(rel_spread, 2),
                        "detail": "High-volume wide bar rejected into lower third close (overhead supply).",
                    }
                )
            elif rel_vol <= 0.65 and rel_spread <= 0.65 and (not up_bar) and close_loc >= 0.50:
                vsa_events.append(
                    {
                        "date": dates[i],
                        "tag": "No-Supply Test",
                        "bias": "bullish",
                        "rel_volume": round(rel_vol, 2),
                        "rel_spread_atr": round(rel_spread, 2),
                        "detail": "Narrow-spread pullback on dry volume (< 0.65x avg) closing mid/high.",
                    }
                )
            elif rel_vol <= 0.65 and rel_spread <= 0.65 and up_bar and close_loc <= 0.45:
                vsa_events.append(
                    {
                        "date": dates[i],
                        "tag": "No-Demand Up Bar",
                        "bias": "bearish",
                        "rel_volume": round(rel_vol, 2),
                        "rel_spread_atr": round(rel_spread, 2),
                        "detail": "Narrow-spread up bar on weak volume closing below midpoint.",
                    }
                )

    return {
        "dow_state": dow_state,
        "dow_detail": dow_detail,
        "recent_swing_highs": last_two_highs,
        "recent_swing_lows": last_two_lows,
        "wyckoff_vsa_events": vsa_events[-6:][::-1],
    }


# ============================================================================
# 5. STAGE A & STAGE B TWO-STAGE COMPOSITE SCORE + INDICATOR MATRIX
# ============================================================================

def _evaluate_single_timeframe_pillars(
    df: pd.DataFrame,
    benchmark_close: Optional[pd.Series],
    benchmark_symbol: str,
    timeframe: str,
    daily_df: pd.DataFrame,
    weekly_completed_df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Computes all 16 Stage-A indicator values, rules, and scores s_j in [-1, +1]
    on a single timeframe (`1D`, `1W`, or `1M`).
    """
    if df is None or df.empty or len(df) < 15:
        return {
            "indicators": {},
            "pillars": {},
            "total_coverage": 0.0,
            "all_pillars_pass_60": False,
            "passes_coverage_gate": False,
            "score": None,
            "rs_suite": {},
            "stage_info": {},
        }

    c_ser = df["Close"].astype(float)
    h_ser = df["High"].astype(float)
    l_ser = df["Low"].astype(float)
    v_ser = df["Volume"].astype(float)

    high = h_ser.to_numpy(dtype=np.float64)
    low = l_ser.to_numpy(dtype=np.float64)
    close = c_ser.to_numpy(dtype=np.float64)
    volume = v_ser.to_numpy(dtype=np.float64)
    n = len(close)
    last_close = float(close[-1])

    sma_long_len = 200 if timeframe == "1D" else (40 if timeframe == "1W" else 12)
    sma_mid_len = 50 if timeframe == "1D" else (20 if timeframe == "1W" else 6)
    sma_short_len = 20 if timeframe == "1D" else (10 if timeframe == "1W" else 3)
    roc_len = 63 if timeframe == "1D" else (13 if timeframe == "1W" else 6)

    sma_short = compute_sma(c_ser, sma_short_len)
    sma_mid = compute_sma(c_ser, sma_mid_len)
    sma_long = compute_sma(c_ser, sma_long_len)
    atr14 = compute_atr_wilder(h_ser, l_ser, c_ser, 14)

    s_short = _last_valid(sma_short) if n >= sma_short_len else None
    s_mid = _last_valid(sma_mid) if n >= sma_mid_len else None
    s_long = _last_valid(sma_long) if n >= sma_long_len else None
    atr_last = _last_valid(atr14) if n >= 15 else None

    indicators: Dict[str, Dict[str, Any]] = {}

    # --- PILLAR 1: TREND (W = 0.25) ---
    # 1.1 MA Alignment (weight 0.40)
    if s_short is not None and s_mid is not None and s_long is not None:
        pairs = [
            1.0 if last_close > s_short else -1.0,
            1.0 if s_short > s_mid else -1.0,
            1.0 if s_mid > s_long else -1.0,
            1.0 if last_close > s_long else -1.0,
        ]
        s_ma = _clamp(float(np.mean(pairs)))
        indicators["ma_alignment"] = {
            "available": True,
            "raw": f"P {last_close:.1f} vs {s_short:.1f}/{s_mid:.1f}/{s_long:.1f}",
            "s": round(s_ma, 3),
        }
    else:
        indicators["ma_alignment"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # 1.2 Long-MA Slope (weight 0.30)
    slope_lb = 20 if timeframe == "1D" else (4 if timeframe == "1W" else 3)
    sma_long_arr = sma_long.to_numpy(dtype=np.float64)
    if s_long is not None and n >= sma_long_len + slope_lb and np.isfinite(sma_long_arr[-1 - slope_lb]):
        prev_long = float(sma_long_arr[-1 - slope_lb])
        slope_pct = ((s_long / prev_long) - 1.0) * 100.0 if prev_long > 0 else 0.0
        scale = 2.0 if timeframe == "1D" else 1.5
        s_slope = _clamp(math.tanh(slope_pct / scale))
        indicators["sma200_slope"] = {
            "available": True,
            "raw": f"{slope_pct:+.2f}% ({slope_lb}b)",
            "s": round(s_slope, 3),
        }
    else:
        indicators["sma200_slope"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # 1.3 ADX(14) & +/-DI (weight 0.30)
    adx_res = compute_adx_wilder(high, low, close, 14)
    adx_v = _last_valid(adx_res["adx"])
    pdi_v = _last_valid(adx_res["plus_di"])
    mdi_v = _last_valid(adx_res["minus_di"])
    if adx_v is not None and pdi_v is not None and mdi_v is not None:
        di_denom = pdi_v + mdi_v
        di_dir = (pdi_v - mdi_v) / di_denom if di_denom > 1e-9 else 0.0
        strength = min(1.0, max(0.15, adx_v / 30.0))
        s_adx = _clamp(di_dir * strength * 1.6)
        indicators["adx_di"] = {
            "available": True,
            "raw": f"ADX {adx_v:.1f} (+DI {pdi_v:.1f} / -DI {mdi_v:.1f})",
            "s": round(s_adx, 3),
        }
    else:
        indicators["adx_di"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # --- PILLAR 2: MOMENTUM (W = 0.15) ---
    # 2.1 Wilder RSI(14) (weight 0.40)
    rsi14 = compute_rsi_wilder(c_ser, 14)
    rsi_v = _last_valid(rsi14) if n >= 15 else None
    if rsi_v is not None:
        s_rsi = _clamp(math.tanh((rsi_v - 50.0) / 18.0))
        indicators["rsi_14"] = {
            "available": True,
            "raw": f"{rsi_v:.1f}",
            "s": round(s_rsi, 3),
        }
    else:
        indicators["rsi_14"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # 2.2 MACD Histogram & 3-bar Slope (weight 0.35)
    macd_res = compute_macd(c_ser, 12, 26, 9)
    hist_arr = macd_res["histogram"].to_numpy(dtype=np.float64)
    hist_v = _last_valid(hist_arr) if n >= 35 else None
    if hist_v is not None and atr_last is not None and atr_last > 0 and len(hist_arr) >= 4 and np.isfinite(hist_arr[-4]):
        hist_norm = hist_v / atr_last
        slope_norm = (hist_v - float(hist_arr[-4])) / atr_last
        s_macd = _clamp(math.tanh(1.2 * hist_norm + 1.5 * slope_norm))
        indicators["macd_hist_slope"] = {
            "available": True,
            "raw": f"Hist {hist_v:+.2f} (Δ3 {hist_v - float(hist_arr[-4]):+.2f})",
            "s": round(s_macd, 3),
        }
    else:
        indicators["macd_hist_slope"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # 2.3 ROC-63 (or timeframe equivalent) (weight 0.25)
    if n > roc_len and close[-1 - roc_len] > 0:
        roc_pct = ((last_close / float(close[-1 - roc_len])) - 1.0) * 100.0
        s_roc = _clamp(math.tanh(roc_pct / 15.0))
        indicators["roc_63"] = {
            "available": True,
            "raw": f"{roc_pct:+.2f}% ({roc_len}b)",
            "s": round(s_roc, 3),
        }
    else:
        indicators["roc_63"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # --- PILLAR 3: VOLATILITY (W = 0.10) ---
    # 3.1 Bollinger %B (20, 2.0) (weight 0.50)
    bb_res = compute_bollinger_bands(c_ser, window=20, num_std=2.0)
    pct_b = _last_valid(bb_res["pct_b"]) if n >= 20 else None
    if pct_b is not None:
        s_pctb = _clamp((pct_b - 0.5) * 2.0)
        indicators["bb_pct_b"] = {
            "available": True,
            "raw": f"%B = {pct_b:.2f}",
            "s": round(s_pctb, 3),
        }
    else:
        indicators["bb_pct_b"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # 3.2 TTM Volatility Squeeze (weight 0.50)
    sqz = compute_ttm_squeeze(df, 20, 2.0, 1.5)
    if sqz is not None:
        mom_atr = float(sqz["momentum_atr"])
        mult = 1.25 if sqz["squeeze_released"] else (0.75 if sqz["squeeze_on"] else 1.0)
        s_sqz = _clamp(math.tanh(mom_atr * 0.8) * mult)
        state_lbl = "Squeeze ON" if sqz["squeeze_on"] else ("Release!" if sqz["squeeze_released"] else "Normal")
        indicators["ttm_squeeze"] = {
            "available": True,
            "raw": f"{state_lbl} (Mom {mom_atr:+.2f} ATR)",
            "s": round(s_sqz, 3),
        }
    else:
        indicators["ttm_squeeze"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # --- PILLAR 4: VOLUME (W = 0.20) ---
    # 4.1 OBV 20-bar OLS Slope t-stat (weight 0.40)
    obv_win = 20 if timeframe == "1D" else (12 if timeframe == "1W" else 6)
    obv_t = compute_obv_slope_tstat(close, volume, window=obv_win)
    if obv_t is not None:
        s_obv = _clamp(math.tanh(obv_t / 2.5))
        indicators["obv_slope_t"] = {
            "available": True,
            "raw": f"t = {obv_t:+.2f} ({obv_win}b)",
            "s": round(s_obv, 3),
        }
    else:
        indicators["obv_slope_t"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # 4.2 Chaikin Money Flow CMF(20) (weight 0.30)
    cmf_win = 20 if timeframe == "1D" else (12 if timeframe == "1W" else 6)
    cmf_v = compute_cmf(high, low, close, volume, period=cmf_win)
    if cmf_v is not None:
        s_cmf = _clamp(cmf_v / 0.25)
        indicators["cmf_20"] = {
            "available": True,
            "raw": f"{cmf_v:+.3f}",
            "s": round(s_cmf, 3),
        }
    else:
        indicators["cmf_20"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # 4.3 Up/Down Volume Ratio (weight 0.30)
    ud_win = 50 if timeframe == "1D" else (20 if timeframe == "1W" else 12)
    ud_ratio = compute_up_down_volume_ratio(close, volume, period=ud_win)
    if ud_ratio is not None and ud_ratio > 0:
        s_ud = _clamp(math.tanh(math.log(ud_ratio) / 0.45))
        indicators["up_down_vol"] = {
            "available": True,
            "raw": f"{ud_ratio:.2f}x ({ud_win}b)",
            "s": round(s_ud, 3),
        }
    else:
        indicators["up_down_vol"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # --- PILLAR 5: RELATIVE STRENGTH (W = 0.15) ---
    rs_suite = compute_relative_strength_suite(df, benchmark_close, benchmark_symbol, timeframe=timeframe)
    if rs_suite.get("mansfield_rs") is not None:
        m_rs = float(rs_suite["mansfield_rs"])
        s_mrs = _clamp(math.tanh(m_rs / 10.0))
        indicators["mansfield_rs"] = {
            "available": True,
            "raw": f"{m_rs:+.2f}",
            "s": round(s_mrs, 3),
        }
    else:
        indicators["mansfield_rs"] = {"available": False, "raw": "Requires 52W RS", "s": None}

    if rs_suite.get("alpha_63d_tstat") is not None:
        a_t = float(rs_suite["alpha_63d_tstat"])
        s_at = _clamp(math.tanh(a_t / 2.0))
        indicators["alpha_63d_tstat"] = {
            "available": True,
            "raw": f"t = {a_t:+.2f} (α {rs_suite['alpha_63d_annualized_pct']:+.1f}%/yr)",
            "s": round(s_at, 3),
        }
    else:
        indicators["alpha_63d_tstat"] = {"available": False, "raw": "Insufficient bars", "s": None}

    # --- PILLAR 6: STRUCTURE (W = 0.15) ---
    stage_info = compute_trend_stage_preview(daily_df, weekly_completed_df)
    w_stage = stage_info.get("weinstein_stage")
    if stage_info.get("eligible") and w_stage in (1, 2, 3, 4):
        stage_map = {2: 1.0, 1: 0.15, 3: -0.35, 4: -1.0}
        indicators["weinstein_stage"] = {
            "available": True,
            "raw": f"{stage_info.get('stage_label', f'Stage {w_stage}')}",
            "s": round(float(stage_map[w_stage]), 3),
        }
    else:
        indicators["weinstein_stage"] = {"available": False, "raw": "Requires >= 260D", "s": None}

    if stage_info.get("eligible") and stage_info.get("minervini_passed") is not None:
        m_score = int(stage_info["minervini_passed"])
        m_total = int(stage_info.get("minervini_total", 8))
        s_min = _clamp(2.0 * (m_score / max(1, m_total)) - 1.0)
        indicators["minervini_template"] = {
            "available": True,
            "raw": f"{m_score}/{m_total} passed",
            "s": round(s_min, 3),
        }
    else:
        indicators["minervini_template"] = {"available": False, "raw": "Requires >= 260D", "s": None}

    vp = compute_volume_profile(df, num_bins=24, lookback=min(n, 252))
    if vp.get("poc_price") is not None and vp.get("vah_price") is not None and vp.get("val_price") is not None:
        poc = float(vp["poc_price"])
        vah = float(vp["vah_price"])
        val_p = float(vp["val_price"])
        if last_close > vah:
            s_vp = 0.90
            vp_lbl = f"> VAH ({vah:.1f})"
        elif last_close >= poc:
            s_vp = 0.45
            vp_lbl = f"POC..VAH ({poc:.1f}..{vah:.1f})"
        elif last_close >= val_p:
            s_vp = -0.35
            vp_lbl = f"VAL..POC ({val_p:.1f}..{poc:.1f})"
        else:
            s_vp = -0.85
            vp_lbl = f"< VAL ({val_p:.1f})"
        indicators["vp_position"] = {
            "available": True,
            "raw": vp_lbl,
            "s": round(s_vp, 3),
        }
    else:
        indicators["vp_position"] = {"available": False, "raw": "Insufficient volume", "s": None}

    pillar_spec = {
        "trend": [("ma_alignment", 0.40), ("sma200_slope", 0.30), ("adx_di", 0.30)],
        "momentum": [("rsi_14", 0.40), ("macd_hist_slope", 0.35), ("roc_63", 0.25)],
        "volatility": [("bb_pct_b", 0.50), ("ttm_squeeze", 0.50)],
        "volume": [("obv_slope_t", 0.40), ("cmf_20", 0.30), ("up_down_vol", 0.30)],
        "relative_strength": [("mansfield_rs", 0.60), ("alpha_63d_tstat", 0.40)],
        "structure": [("weinstein_stage", 0.40), ("minervini_template", 0.30), ("vp_position", 0.30)],
    }

    pillars_out: Dict[str, Dict[str, Any]] = {}
    total_avail_weight = 0.0
    all_pillars_pass_60 = True

    for p_key, items in pillar_spec.items():
        p_weight = PILLAR_WEIGHTS[p_key]
        avail_w = 0.0
        weighted_sum = 0.0
        for ind_id, ind_w in items:
            ind_obj = indicators.get(ind_id, {})
            if ind_obj.get("available") and ind_obj.get("s") is not None:
                avail_w += ind_w
                weighted_sum += ind_w * float(ind_obj["s"])

        passes_60 = avail_w >= 0.60 - 1e-9
        if not passes_60:
            all_pillars_pass_60 = False
        total_avail_weight += p_weight * avail_w
        p_score = (weighted_sum / avail_w) if avail_w > 0 else None
        p_score_100 = 100.0 * ((p_score + 1.0) / 2.0) if p_score is not None else None

        pillars_out[p_key] = {
            "id": p_key,
            "label": PILLAR_LABELS[p_key],
            "weight": p_weight,
            "coverage": round(avail_w, 3),
            "passes_gate": passes_60,
            "p_k": round(p_score, 3) if p_score is not None else None,
            "score_100": round(p_score_100, 1) if p_score_100 is not None else None,
        }

    passes_coverage_gate = bool(all_pillars_pass_60 and total_avail_weight >= 0.70 - 1e-9)
    tf_score: Optional[float] = None
    if passes_coverage_gate:
        w_sum = 0.0
        s_acc = 0.0
        for p_key, p_obj in pillars_out.items():
            if p_obj["p_k"] is not None:
                w_k = PILLAR_WEIGHTS[p_key]
                w_sum += w_k
                s_acc += w_k * ((float(p_obj["p_k"]) + 1.0) / 2.0)
        if w_sum > 0:
            tf_score = round(100.0 * (s_acc / w_sum), 1)

    return {
        "indicators": indicators,
        "pillars": pillars_out,
        "total_coverage": round(total_avail_weight, 3),
        "all_pillars_pass_60": all_pillars_pass_60,
        "passes_coverage_gate": passes_coverage_gate,
        "score": tf_score,
        "rs_suite": rs_suite,
        "stage_info": stage_info,
    }


INDICATOR_SPEC_METADATA: List[Dict[str, Any]] = [
    {
        "id": "ma_alignment",
        "name": "Moving Average Stack (20 / 50 / 200)",
        "pillar": "trend",
        "pillar_label": "Trend Structure",
        "pillar_weight": 0.25,
        "indicator_weight": 0.40,
        "rule": "Equal-weight vote across Price > SMA20, SMA20 > SMA50, SMA50 > SMA200, Price > SMA200 in [-1, +1]",
    },
    {
        "id": "sma200_slope",
        "name": "Long-Term Trend Slope (SMA 200)",
        "pillar": "trend",
        "pillar_label": "Trend Structure",
        "pillar_weight": 0.25,
        "indicator_weight": 0.30,
        "rule": "tanh(20-bar % change of long SMA / 2.0%) in [-1, +1]",
    },
    {
        "id": "adx_di",
        "name": "Wilder ADX(14) & Directional +/-DI",
        "pillar": "trend",
        "pillar_label": "Trend Structure",
        "pillar_weight": 0.25,
        "indicator_weight": 0.30,
        "rule": "((+DI - -DI)/(+DI + -DI)) * min(1, ADX/30) * 1.6 clamped to [-1, +1]",
    },
    {
        "id": "rsi_14",
        "name": "Wilder RSI (14)",
        "pillar": "momentum",
        "pillar_label": "Momentum & Velocity",
        "pillar_weight": 0.15,
        "indicator_weight": 0.40,
        "rule": "tanh((RSI_14 - 50) / 18) centered at neutral 50 in [-1, +1]",
    },
    {
        "id": "macd_hist_slope",
        "name": "MACD (12,26,9) Histogram & 3-Bar Impulse",
        "pillar": "momentum",
        "pillar_label": "Momentum & Velocity",
        "pillar_weight": 0.15,
        "indicator_weight": 0.35,
        "rule": "tanh(1.2*(Hist/ATR14) + 1.5*(Δ3_Hist/ATR14)) in [-1, +1]",
    },
    {
        "id": "roc_63",
        "name": "Medium-Term Rate of Change (ROC 63D)",
        "pillar": "momentum",
        "pillar_label": "Momentum & Velocity",
        "pillar_weight": 0.15,
        "indicator_weight": 0.25,
        "rule": "tanh(63-bar Return % / 15%) in [-1, +1]",
    },
    {
        "id": "bb_pct_b",
        "name": "Bollinger %B (20, 2.0σ)",
        "pillar": "volatility",
        "pillar_label": "Volatility & Compression",
        "pillar_weight": 0.10,
        "indicator_weight": 0.50,
        "rule": "2 * (%B - 0.50) clamped to [-1, +1]",
    },
    {
        "id": "ttm_squeeze",
        "name": "TTM Volatility Squeeze (BB vs Keltner 1.5×ATR)",
        "pillar": "volatility",
        "pillar_label": "Volatility & Compression",
        "pillar_weight": 0.10,
        "indicator_weight": 0.50,
        "rule": "tanh(0.8 * Mom_ATR) * (1.25 on Squeeze Release, 0.75 in Squeeze, 1.0 normal)",
    },
    {
        "id": "obv_slope_t",
        "name": "On-Balance Volume (OBV) 20D Slope t-stat",
        "pillar": "volume",
        "pillar_label": "Institutional Volume Flow",
        "pillar_weight": 0.20,
        "indicator_weight": 0.40,
        "rule": "tanh(OLS t-statistic of 20-bar OBV / 2.5) in [-1, +1]",
    },
    {
        "id": "cmf_20",
        "name": "Chaikin Money Flow CMF (20)",
        "pillar": "volume",
        "pillar_label": "Institutional Volume Flow",
        "pillar_weight": 0.20,
        "indicator_weight": 0.30,
        "rule": "CMF_20 / 0.25 clamped to [-1, +1]",
    },
    {
        "id": "up_down_vol",
        "name": "Up / Down Volume Ratio (50D)",
        "pillar": "volume",
        "pillar_label": "Institutional Volume Flow",
        "pillar_weight": 0.20,
        "indicator_weight": 0.30,
        "rule": "tanh(ln(UpVol / DownVol) / 0.45) in [-1, +1]",
    },
    {
        "id": "mansfield_rs",
        "name": "Mansfield Relative Strength vs Benchmark",
        "pillar": "relative_strength",
        "pillar_label": "Benchmark Relative Strength",
        "pillar_weight": 0.15,
        "indicator_weight": 0.60,
        "rule": "tanh(Mansfield_RS / 10.0) where Mansfield_RS = 100*(RS / SMA_52W(RS) - 1)",
    },
    {
        "id": "alpha_63d_tstat",
        "name": "63-Day Rolling Jensen's Alpha t-stat",
        "pillar": "relative_strength",
        "pillar_label": "Benchmark Relative Strength",
        "pillar_weight": 0.15,
        "indicator_weight": 0.40,
        "rule": "tanh(OLS alpha t-stat vs benchmark / 2.0) in [-1, +1]",
    },
    {
        "id": "weinstein_stage",
        "name": "Weinstein Stage (30W Completed Bars)",
        "pillar": "structure",
        "pillar_label": "Stage & Volume Acceptance",
        "pillar_weight": 0.15,
        "indicator_weight": 0.40,
        "rule": "Stage 2 Advancing = +1.00, Stage 1 Basing = +0.15, Stage 3 Topping = -0.35, Stage 4 Declining = -1.00",
    },
    {
        "id": "minervini_template",
        "name": "Minervini 8-Point Trend Template",
        "pillar": "structure",
        "pillar_label": "Stage & Volume Acceptance",
        "pillar_weight": 0.15,
        "indicator_weight": 0.30,
        "rule": "Linear mapping 2*(Passed / 8) - 1 in [-1, +1]",
    },
    {
        "id": "vp_position",
        "name": "Volume Profile Value Area Position (POC / VAH / VAL)",
        "pillar": "structure",
        "pillar_label": "Stage & Volume Acceptance",
        "pillar_weight": 0.15,
        "indicator_weight": 0.30,
        "rule": "> VAH = +0.90, POC..VAH = +0.45, VAL..POC = -0.35, < VAL = -0.85",
    },
]


# ============================================================================
# 6. 3x4 FUNDAMENTAL OUTLOOK x WEINSTEIN STAGE CLASSIFICATION MATRIX (R6)
# ============================================================================

CONFLUENCE_CELL_SPEC: Dict[Tuple[str, int], Dict[str, str]] = {
    ("bullish", 1): {
        "title": "Bullish Valuation · Stage 1 Basing",
        "subtitle": "Early Accumulation Candidate",
        "description": "Intrinsic value exceeds market price while weekly price action is flattening into a Stage 1 base around the 30-week SMA.",
        "tone": "emerald",
    },
    ("bullish", 2): {
        "title": "Bullish Valuation · Stage 2 Advancing",
        "subtitle": "Confirmed Fundamental & Trend Alignment",
        "description": "Intrinsic valuation discount aligns with a confirmed Stage 2 uptrend above a rising 30-week SMA.",
        "tone": "emerald",
    },
    ("bullish", 3): {
        "title": "Bullish Valuation · Stage 3 Topping",
        "subtitle": "Undervalued in Overhead Distribution",
        "description": "DCF model indicates upside, but weekly trend momentum has flattened into Stage 3 distribution.",
        "tone": "amber",
    },
    ("bullish", 4): {
        "title": "Bullish Valuation · Stage 4 Declining",
        "subtitle": "Possible Value Trap · Trend Unconfirmed",
        "description": "Trades below estimated fair value, but primary price trend remains in Stage 4 markdown below a falling 30-week SMA.",
        "tone": "amber",
    },
    ("neutral", 1): {
        "title": "Neutral Valuation · Stage 1 Basing",
        "subtitle": "Fairly Valued Equilibrium Base",
        "description": "Price trades within the interquartile Monte Carlo band while consolidating sideways in a Stage 1 base.",
        "tone": "slate",
    },
    ("neutral", 2): {
        "title": "Neutral Valuation · Stage 2 Advancing",
        "subtitle": "Trend-Driven Advance at Fair Value",
        "description": "Price is within the DCF fair-value corridor while exhibiting Stage 2 technical momentum.",
        "tone": "sky",
    },
    ("neutral", 3): {
        "title": "Neutral Valuation · Stage 3 Topping",
        "subtitle": "Fairly Valued · Momentum Stalling",
        "description": "Price sits near fair value and weekly trend structure shows Stage 3 plateauing.",
        "tone": "amber",
    },
    ("neutral", 4): {
        "title": "Neutral Valuation · Stage 4 Declining",
        "subtitle": "Fairly Valued · Primary Downtrend",
        "description": "Valuation is neutral, but weekly price structure remains in Stage 4 decline.",
        "tone": "rose",
    },
    ("bearish", 1): {
        "title": "Bearish Valuation · Stage 1 Basing",
        "subtitle": "Valuation Premium in Sideways Base",
        "description": "Trades above fundamental fair value corridor while consolidating laterally in Stage 1.",
        "tone": "amber",
    },
    ("bearish", 2): {
        "title": "Bearish Valuation · Stage 2 Advancing",
        "subtitle": "Momentum Premium · Extended Above DCF",
        "description": "Stage 2 price uptrend persists despite price trading above the fundamental DCF fair-value range.",
        "tone": "amber",
    },
    ("bearish", 3): {
        "title": "Bearish Valuation · Stage 3 Topping",
        "subtitle": "Overvalued & Distributing",
        "description": "Trades at a premium to intrinsic value while weekly trend structure transitions into Stage 3 topping.",
        "tone": "rose",
    },
    ("bearish", 4): {
        "title": "Bearish Valuation · Stage 4 Declining",
        "subtitle": "Confirmed Valuation & Trend Headwind",
        "description": "Trades above DCF fair value while weekly price action is in a confirmed Stage 4 decline.",
        "tone": "rose",
    },
    ("unreliable", 1): {
        "title": "Valuation Unreliable · Stage 1 Basing",
        "subtitle": "Distressed Cash Flows · Technical Base",
        "description": "Fundamental DCF is flagged unreliable/distressed; technical evaluation relies strictly on Stage 1 price structure.",
        "tone": "slate",
    },
    ("unreliable", 2): {
        "title": "Valuation Unreliable · Stage 2 Advancing",
        "subtitle": "Distressed Cash Flows · Stage 2 Recovery",
        "description": "Fundamental DCF is flagged unreliable/distressed; price action shows Stage 2 technical recovery.",
        "tone": "slate",
    },
    ("unreliable", 3): {
        "title": "Valuation Unreliable · Stage 3 Topping",
        "subtitle": "Distressed Cash Flows · Stage 3 Topping",
        "description": "Fundamental DCF is flagged unreliable/distressed; weekly trend shows Stage 3 distribution.",
        "tone": "slate",
    },
    ("unreliable", 4): {
        "title": "Valuation Unreliable · Stage 4 Declining",
        "subtitle": "Distressed Fundamentals & Stage 4 Decline",
        "description": "Both fundamental cash-flow health and weekly Stage 4 price structure reflect distress.",
        "tone": "rose",
    },
}


def build_classification_matrix(
    verdict_str: Optional[str],
    weinstein_stage: Optional[int],
) -> Dict[str, Any]:
    """
    Constructs the 3x4 (+1 greyed unreliable row) Classification Matrix
    mapping the live Fundamental Valuation Outlook against Weinstein Stage 1-4.
    """
    v_upper = (verdict_str or "NEUTRAL").strip().upper()
    if "UNRELIABLE" in v_upper or "DISTRESSED" in v_upper:
        active_row = "unreliable"
    elif "BULLISH" in v_upper or "BUY" in v_upper:
        active_row = "bullish"
    elif "BEARISH" in v_upper or "SELL" in v_upper:
        active_row = "bearish"
    else:
        active_row = "neutral"

    active_col = weinstein_stage if weinstein_stage in (1, 2, 3, 4) else None

    rows_meta = [
        {
            "id": "bullish",
            "label": "Valuation Outlook: Bullish",
            "sub": "Includes Strongly Bullish & Bullish (< P25)",
            "is_greyed": False,
        },
        {
            "id": "neutral",
            "label": "Valuation Outlook: Neutral",
            "sub": "Interquartile Band (P25–P75)",
            "is_greyed": False,
        },
        {
            "id": "bearish",
            "label": "Valuation Outlook: Bearish",
            "sub": "Includes Bearish & Strongly Bearish (> P75)",
            "is_greyed": False,
        },
        {
            "id": "unreliable",
            "label": "Valuation Unreliable / Distressed",
            "sub": "Negative or distressed operating cash flows",
            "is_greyed": active_row != "unreliable",
        },
    ]

    cols_meta = [
        {"stage": 1, "label": "Stage 1 · Basing"},
        {"stage": 2, "label": "Stage 2 · Advancing"},
        {"stage": 3, "label": "Stage 3 · Topping"},
        {"stage": 4, "label": "Stage 4 · Declining"},
    ]

    grid: List[Dict[str, Any]] = []
    for r in rows_meta:
        r_id = r["id"]
        row_cells = []
        for c in cols_meta:
            stg = c["stage"]
            spec = CONFLUENCE_CELL_SPEC[(r_id, stg)]
            is_active = bool(r_id == active_row and stg == active_col)
            row_cells.append(
                {
                    "row_id": r_id,
                    "stage": stg,
                    "is_active": is_active,
                    "title": spec["title"],
                    "subtitle": spec["subtitle"],
                    "description": spec["description"],
                    "tone": spec["tone"],
                }
            )
        grid.append({**r, "is_active_row": r_id == active_row, "cells": row_cells})

    active_cell = (
        CONFLUENCE_CELL_SPEC.get((active_row, active_col))
        if active_col in (1, 2, 3, 4)
        else {
            "title": f"Valuation Outlook: {v_upper} · Weinstein Stage Unavailable",
            "subtitle": "Insufficient Weekly History (< 260 daily / 34 weekly bars)",
            "description": "Weinstein Stage classification requires at least 260 daily bars and 34 completed weekly bars.",
            "tone": "slate",
        }
    )

    return {
        "live_verdict": v_upper,
        "active_row": active_row,
        "active_stage": active_col,
        "active_cell": active_cell,
        "columns": cols_meta,
        "rows": grid,
    }


# ============================================================================
# 7. MASTER PHASE-2 PAYLOAD BUILDER (/api/technical/score)
# ============================================================================

def build_ta_phase2_payload(
    bundle: MarketHistoryBundle,
    fair_value: Optional[float] = None,
    verdict: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Master builder for Phase 2 (`GET /api/technical/score` and embedded `phase2`
    inside `/api/technical/chart`).
    """
    daily_df: pd.DataFrame = bundle.ohlc_split
    weekly_df: pd.DataFrame = (
        bundle.weekly_completed if not bundle.weekly_completed.empty else bundle.weekly_split
    )
    monthly_df: pd.DataFrame = (
        bundle.monthly_completed if not bundle.monthly_completed.empty else bundle.monthly_split
    )
    bench_close: Optional[pd.Series] = bundle.benchmark_close
    bench_symbol = bundle.benchmark or "^GSPC"

    eval_d = _evaluate_single_timeframe_pillars(
        daily_df, bench_close, bench_symbol, "1D", daily_df, bundle.weekly_completed
    )
    eval_w = _evaluate_single_timeframe_pillars(
        weekly_df, bench_close, bench_symbol, "1W", daily_df, bundle.weekly_completed
    )
    eval_m = _evaluate_single_timeframe_pillars(
        monthly_df, bench_close, bench_symbol, "1M", daily_df, bundle.weekly_completed
    )

    cov_d = float(eval_d["total_coverage"])
    gate_passed = bool(eval_d["passes_coverage_gate"])

    s_d = eval_d["score"]
    s_w = eval_w["score"]
    s_m = eval_m["score"]

    # Multi-timeframe aggregation S_MTF = 0.50*D + 0.35*W + 0.15*M (completed W/M bars only)
    score_mtf: Optional[float] = None
    mtf_weights_used = {"D": 0.50, "W": 0.35, "M": 0.15}
    if gate_passed and s_d is not None:
        w_acc = 0.50
        v_acc = 0.50 * float(s_d)
        if s_w is not None:
            w_acc += 0.35
            v_acc += 0.35 * float(s_w)
        if s_m is not None:
            w_acc += 0.15
            v_acc += 0.15 * float(s_m)
        score_mtf = round(v_acc / w_acc, 1)

    if not gate_passed or score_mtf is None:
        pct_cov = int(round(cov_d * 100.0))
        condition_label = f"Score unavailable (coverage {pct_cov}%)"
        condition_short = "Score unavailable"
        condition_tone = "slate"
    elif score_mtf >= 60.0:
        condition_label = "Technical condition: Bullish"
        condition_short = "Bullish"
        condition_tone = "emerald"
    elif score_mtf <= 40.0:
        condition_label = "Technical condition: Bearish"
        condition_short = "Bearish"
        condition_tone = "rose"
    else:
        condition_label = "Technical condition: Neutral"
        condition_short = "Neutral"
        condition_tone = "amber"

    # Build the 16-row Indicator Matrix across D / W / M
    matrix_rows: List[Dict[str, Any]] = []
    for meta in INDICATOR_SPEC_METADATA:
        ind_id = meta["id"]
        d_item = eval_d["indicators"].get(ind_id, {})
        w_item = eval_w["indicators"].get(ind_id, {})
        m_item = eval_m["indicators"].get(ind_id, {})

        sd = d_item.get("s")
        sw = w_item.get("s")
        sm = m_item.get("s")

        s_mtf_j: Optional[float] = None
        if sd is not None:
            wa = 0.50
            va = 0.50 * float(sd)
            if sw is not None:
                wa += 0.35
                va += 0.35 * float(sw)
            if sm is not None:
                wa += 0.15
                va += 0.15 * float(sm)
            s_mtf_j = round(va / wa, 3)

        eff_w = round(float(meta["pillar_weight"]) * float(meta["indicator_weight"]), 4)
        signed_edge_pts = round(50.0 * eff_w * float(s_mtf_j), 2) if s_mtf_j is not None else 0.0
        points_100 = round(100.0 * eff_w * ((float(s_mtf_j) + 1.0) / 2.0), 2) if s_mtf_j is not None else None

        matrix_rows.append(
            {
                "id": ind_id,
                "name": meta["name"],
                "pillar": meta["pillar"],
                "pillar_label": meta["pillar_label"],
                "pillar_weight": meta["pillar_weight"],
                "indicator_weight": meta["indicator_weight"],
                "effective_weight": eff_w,
                "rule": meta["rule"],
                "raw_d": d_item.get("raw", "—"),
                "raw_w": w_item.get("raw", "—"),
                "raw_m": m_item.get("raw", "—"),
                "s_d": sd,
                "s_w": sw,
                "s_m": sm,
                "s_mtf": s_mtf_j,
                "points_100": points_100,
                "signed_edge_pts": signed_edge_pts,
            }
        )

    bullish_contributors = sorted(
        [r for r in matrix_rows if r["s_mtf"] is not None and r["s_mtf"] > 0],
        key=lambda r: r["signed_edge_pts"],
        reverse=True,
    )[:3]
    bearish_contributors = sorted(
        [r for r in matrix_rows if r["s_mtf"] is not None and r["s_mtf"] < 0],
        key=lambda r: r["signed_edge_pts"],
    )[:3]

    # Statistical & Structure Diagnostics
    tr_df = bundle.ohlc_tr if not bundle.ohlc_tr.empty else daily_df
    tr_open = tr_df["Open"].to_numpy(dtype=np.float64)
    tr_high = tr_df["High"].to_numpy(dtype=np.float64)
    tr_low = tr_df["Low"].to_numpy(dtype=np.float64)
    tr_close = tr_df["Close"].to_numpy(dtype=np.float64)

    d_atr14 = compute_atr_wilder(daily_df["High"], daily_df["Low"], daily_df["Close"], 14)

    hurst_diag = compute_hurst_dfa1(tr_close, window=504)
    vr_diag = compute_lo_mackinlay_vr(tr_close, window=504)
    yz_diag = compute_yang_zhang_volatility(tr_open, tr_high, tr_low, tr_close)
    dow_wyckoff = compute_dow_structure_and_wyckoff(daily_df, d_atr14)

    stage_info = eval_d["stage_info"]
    rs_suite = eval_d["rs_suite"]
    classification_matrix = build_classification_matrix(
        verdict_str=verdict,
        weinstein_stage=stage_info.get("weinstein_stage"),
    )

    return {
        "symbol": bundle.symbol,
        "listing_used": bundle.listing_used,
        "market": bundle.market,
        "currency": bundle.currency,
        "currency_symbol": bundle.currency_symbol,
        "score_version": TA_SCORE_VERSION,
        "composite_score": {
            "available": gate_passed and score_mtf is not None,
            "score_mtf": score_mtf,
            "score_d": s_d,
            "score_w": s_w,
            "score_m": s_m,
            "mtf_weights": mtf_weights_used,
            "total_coverage": round(cov_d, 3),
            "coverage_pct": int(round(cov_d * 100.0)),
            "all_pillars_pass_60": eval_d["all_pillars_pass_60"],
            "condition_label": condition_label,
            "condition_short": condition_short,
            "condition_tone": condition_tone,
            "score_version": TA_SCORE_VERSION,
            "pillars_d": eval_d["pillars"],
            "pillars_w": eval_w["pillars"],
            "pillars_m": eval_m["pillars"],
            "top_bullish_contributors": bullish_contributors,
            "top_bearish_contributors": bearish_contributors,
        },
        "indicator_matrix": matrix_rows,
        "diagnostics": {
            "hurst_dfa1": hurst_diag,
            "lo_mackinlay_vr": vr_diag,
            "yang_zhang_vol": yz_diag,
            "weinstein_minervini": stage_info,
            "dow_wyckoff": dow_wyckoff,
            "relative_strength": rs_suite,
        },
        "classification_matrix": classification_matrix,
    }
