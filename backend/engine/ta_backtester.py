"""
ValuationLabs Technical Analysis v0.3 — Per-Stock Signal Backtester
(`backend/engine/ta_backtester.py`)
===================================================================

Implements Phase 3 of `implementation_plan_v3.md`:
- Strict Zero Look-Ahead Execution Contract:
    Signal evaluated at confirmed daily bar close `t`, entry filled at
    next-session total-return open `Open_tr[t + 1]`, exit at `Close_tr[t + h]`
    for horizons `h in {5, 10, 20, 60}` trading days.
- Transaction Costs:
    Default round-trip friction of `10 bps` (`US`) / `30 bps` (`IN`), editable
    via request parameter. Both Gross and Net returns are reported.
- 20-Bar Causal De-Clustering:
    Suppresses overlapping triggers within a 20-trading-day cooldown window
    (`t_next - t_last_accepted >= 20`). Reports both raw and de-clustered counts.
- 70 / 30 Chronological Sample Split:
    First 70% of daily bars = In-Sample (`IS`), final 30% = Out-of-Sample (`OOS`).
    Signal parameters are canonical and frozen (no parameter optimization).
- 10 Frozen Signal Definitions x 4 Horizons = 40 Hypothesis Tests:
    1. `rsi_oversold_recovery`: Wilder RSI(14) crosses up above 30
    2. `rsi_70_continuation`: Wilder RSI(14) crosses up into >= 70 (long continuation)
    3. `rsi_70_reversal`: Wilder RSI(14) hooks down below 70 from >= 70 (mean-reversion)
    4. `macd_bull_cross_below_zero`: MACD(12,26,9) crosses above signal below zero
    5. `golden_cross_50_200`: SMA(50) crosses above SMA(200)
    6. `supertrend_bull_flip`: Causal Supertrend(10, 3.0) flips from bearish to bullish
    7. `ttm_squeeze_bull_release`: TTM Squeeze(20, 2.0, 1.5) releases with positive momentum
    8. `dma_50_200_pullback`: Pullback & bounce off rising 50-DMA above 200-DMA
    9. `breakout_52w_high_vol`: 252-day high breakout on >= 1.5x 20D average volume
    10. `bollinger_lower_reentry`: Close re-enters above lower Bollinger Band(20, 2.0)
- Statistical Inference & Multiple-Testing Control:
    - Excess return vs unconditional `h`-day stock drift and vs matched benchmark (`^NSEI` / `^GSPC`)
    - Win rate with Wilson 95% confidence interval
    - Event-block bootstrap 95% confidence interval + two-sided p-value
    - Benjamini-Hochberg False Discovery Rate (`BH-FDR`) q-values across all 40 tests
    - Maximum Adverse Excursion (`MAE`) and Maximum Favorable Excursion (`MFE`)
- Non-Promotional Labeling Rules:
    - `N_IS < 15` -> `"Insufficient evidence"`
    - `net_excess_is > 0`, 95% CI excludes `0`, `q < 0.10`, and `net_excess_oos > 0`
      -> `"Historically favourable"`
    - Otherwise -> `"No reliable edge"`
    - Never uses promotional terms (`"buy"`, `"sell"`, `"profitable"`).
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .market_history import COVERAGE_REQUIREMENTS, MarketHistoryBundle
from .ta_indicators import (
    compute_atr_wilder,
    compute_bollinger_bands,
    compute_ema,
    compute_macd,
    compute_rsi_wilder,
    compute_sma,
)

TA_BACKTEST_VERSION = "ta-backtest-v0.3"
BACKTEST_HORIZONS: Tuple[int, ...] = (5, 10, 20, 60)
DECLUSTER_COOLDOWN_BARS: int = 20
IS_SPLIT_RATIO: float = 0.70
MIN_IS_EVENTS_REQUIRED: int = 15
FDR_Q_THRESHOLD: float = 0.10
DEFAULT_US_COST_BPS: float = 10.0
DEFAULT_IN_COST_BPS: float = 30.0
BOOTSTRAP_ITERATIONS: int = 1000

SURVIVORSHIP_AND_LOOKBACK_DISCLOSURE = (
    "Historical signal backtest results are computed on a single-security look-back sample "
    "conditioned on the company surviving to the present day (survivorship bias). "
    "In-sample (first 70%) and out-of-sample (final 30%) splits use frozen canonical rules "
    "with next-bar open execution and Benjamini–Hochberg false-discovery-rate adjustment across "
    "all 40 signal-horizon tests. Historical statistical frequencies do not guarantee future performance."
)


# ---------------------------------------------------------------------------
# Frozen Canonical Signal Catalog (10 Signals)
# ---------------------------------------------------------------------------

FROZEN_SIGNAL_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "rsi_oversold_recovery",
        "name": "RSI(14) Oversold Recovery (> 30)",
        "category": "Mean Reversion",
        "direction": 1,
        "direction_label": "Long (+1)",
        "rule_summary": "Wilder RSI(14) crosses up from <= 30 at bar t-1 to > 30 at bar t.",
        "parameters": {"period": 14, "threshold": 30.0},
    },
    {
        "id": "rsi_70_continuation",
        "name": "RSI(14) Overbought Continuation (>= 70)",
        "category": "Momentum Continuation",
        "direction": 1,
        "direction_label": "Long (+1)",
        "rule_summary": "Wilder RSI(14) crosses up from < 70 at bar t-1 to >= 70 at bar t (momentum breakout hypothesis).",
        "parameters": {"period": 14, "threshold": 70.0},
    },
    {
        "id": "rsi_70_reversal",
        "name": "RSI(14) Overbought Reversal (< 70)",
        "category": "Overbought Reversal",
        "direction": -1,
        "direction_label": "Inverse / Mean-Reversion (-1)",
        "rule_summary": "Wilder RSI(14) hooks down from >= 70 at bar t-1 to < 70 at bar t (mean-reversion downside hypothesis).",
        "parameters": {"period": 14, "threshold": 70.0},
    },
    {
        "id": "macd_bull_cross_below_zero",
        "name": "MACD(12,26,9) Bullish Cross Below Zero",
        "category": "Momentum Inflection",
        "direction": 1,
        "direction_label": "Long (+1)",
        "rule_summary": "MACD line crosses above Signal line at bar t while MACD line remains below 0.",
        "parameters": {"fast": 12, "slow": 26, "signal": 9},
    },
    {
        "id": "golden_cross_50_200",
        "name": "Golden Cross (SMA 50 > SMA 200)",
        "category": "Secular Trend",
        "direction": 1,
        "direction_label": "Long (+1)",
        "rule_summary": "SMA(50) crosses above SMA(200) at bar t (SMA50[t-1] <= SMA200[t-1] and SMA50[t] > SMA200[t]).",
        "parameters": {"fast_sma": 50, "slow_sma": 200},
    },
    {
        "id": "supertrend_bull_flip",
        "name": "Supertrend(10, 3.0) Bullish Flip",
        "category": "Volatility Trend",
        "direction": 1,
        "direction_label": "Long (+1)",
        "rule_summary": "Causal Supertrend(ATR 10, 3.0x) regime flips from -1 (bearish) at bar t-1 to +1 (bullish) at bar t.",
        "parameters": {"atr_period": 10, "multiplier": 3.0},
    },
    {
        "id": "ttm_squeeze_bull_release",
        "name": "TTM Squeeze Bullish Release (20, 2.0, 1.5)",
        "category": "Volatility Expansion",
        "direction": 1,
        "direction_label": "Long (+1)",
        "rule_summary": "Bollinger(20, 2.0) exits Keltner(EMA 20, 1.5*ATR14) compression at bar t with positive midline momentum.",
        "parameters": {"period": 20, "bb_mult": 2.0, "kc_mult": 1.5},
    },
    {
        "id": "dma_50_200_pullback",
        "name": "50/200-DMA Trend Pullback & Bounce",
        "category": "Trend Pullback",
        "direction": 1,
        "direction_label": "Long (+1)",
        "rule_summary": "In an established uptrend (Close > SMA200, SMA50 > SMA200), Low[t] tests within 1% of SMA50 (or SMA200) and Close[t] finishes above the tested moving average.",
        "parameters": {"fast_sma": 50, "slow_sma": 200, "touch_tolerance_pct": 1.0},
    },
    {
        "id": "breakout_52w_high_vol",
        "name": "52-Week Breakout on 1.5x Volume",
        "category": "Breakout / Volume",
        "direction": 1,
        "direction_label": "Long (+1)",
        "rule_summary": "Close[t] exceeds the prior 252-bar High maximum on Volume[t] >= 1.5x SMA(Volume, 20)[t].",
        "parameters": {"lookback_bars": 252, "volume_mult": 1.5, "vol_sma": 20},
    },
    {
        "id": "bollinger_lower_reentry",
        "name": "Bollinger Lower-Band Re-Entry (20, 2.0)",
        "category": "Mean Reversion",
        "direction": 1,
        "direction_label": "Long (+1)",
        "rule_summary": "Close[t-1] closes below Lower Bollinger Band(20, 2.0) and Close[t] closes back on or above Lower Band.",
        "parameters": {"period": 20, "num_std": 2.0},
    },
]


# ---------------------------------------------------------------------------
# 1. Causal Indicator Helpers for Signal Generation
# ---------------------------------------------------------------------------

def compute_supertrend_causal(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 10,
    multiplier: float = 3.0,
) -> Dict[str, np.ndarray]:
    """
    Compute strictly causal Supertrend(period, multiplier) using Wilder's ATR(period).
    Returns dict with:
      - `direction`: +1 (bullish) or -1 (bearish), NaN before warmup
      - `supertrend`: active band level
      - `upper_band`: final recursive upper band
      - `lower_band`: final recursive lower band
    """
    n = len(close)
    direction = np.full(n, np.nan, dtype=np.float64)
    st_line = np.full(n, np.nan, dtype=np.float64)
    final_upper = np.full(n, np.nan, dtype=np.float64)
    final_lower = np.full(n, np.nan, dtype=np.float64)

    if n <= period:
        return {
            "direction": direction,
            "supertrend": st_line,
            "upper_band": final_upper,
            "lower_band": final_lower,
        }

    atr_ser = compute_atr_wilder(high, low, close, period=period)
    h = high.astype(float).to_numpy()
    l = low.astype(float).to_numpy()
    c = close.astype(float).to_numpy()
    atr = atr_ser.to_numpy(dtype=np.float64)

    hl2 = 0.5 * (h + l)
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    valid_indices = np.where(np.isfinite(atr))[0]
    if len(valid_indices) == 0:
        return {
            "direction": direction,
            "supertrend": st_line,
            "upper_band": final_upper,
            "lower_band": final_lower,
        }

    start = int(valid_indices[0])
    final_upper[start] = basic_upper[start]
    final_lower[start] = basic_lower[start]
    direction[start] = 1.0 if c[start] >= hl2[start] else -1.0
    st_line[start] = final_lower[start] if direction[start] > 0 else final_upper[start]

    for i in range(start + 1, n):
        if not np.isfinite(atr[i]):
            final_upper[i] = final_upper[i - 1]
            final_lower[i] = final_lower[i - 1]
            direction[i] = direction[i - 1]
            st_line[i] = st_line[i - 1]
            continue

        # Final Upper Band recursion (strictly causal: uses basic_upper[i], final_upper[i-1], c[i-1])
        if basic_upper[i] < final_upper[i - 1] or c[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # Final Lower Band recursion (strictly causal: uses basic_lower[i], final_lower[i-1], c[i-1])
        if basic_lower[i] > final_lower[i - 1] or c[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        prev_dir = direction[i - 1]
        if prev_dir < 0 and c[i] > final_upper[i - 1]:
            direction[i] = 1.0
        elif prev_dir > 0 and c[i] < final_lower[i - 1]:
            direction[i] = -1.0
        else:
            direction[i] = prev_dir

        st_line[i] = final_lower[i] if direction[i] > 0 else final_upper[i]

    return {
        "direction": direction,
        "supertrend": st_line,
        "upper_band": final_upper,
        "lower_band": final_lower,
    }


def generate_frozen_signal_masks(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """
    Evaluate all 10 frozen canonical signal definitions across the daily OHLCV DataFrame.
    Returns a dictionary mapping `signal_id -> boolean numpy array of length N`,
    where `mask[t] == True` means the signal triggered on the close of bar `t`.

    Invariant: `mask[t]` depends ONLY on `df.iloc[:t+1]` (zero look-ahead).
    """
    n = len(df)
    empty_masks = {sig["id"]: np.zeros(n, dtype=bool) for sig in FROZEN_SIGNAL_CATALOG}
    if df is None or n < 25:
        return empty_masks

    close_ser = df["Close"].astype(float)
    high_ser = df["High"].astype(float)
    low_ser = df["Low"].astype(float)
    vol_ser = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(0.0, index=df.index)

    c = close_ser.to_numpy(dtype=np.float64)
    h = high_ser.to_numpy(dtype=np.float64)
    l = low_ser.to_numpy(dtype=np.float64)
    v = vol_ser.to_numpy(dtype=np.float64)

    # Pre-compute causal indicator arrays
    rsi14 = compute_rsi_wilder(close_ser, period=14).to_numpy(dtype=np.float64)
    macd_dict = compute_macd(close_ser, fast=12, slow=26, signal=9)
    macd_line = macd_dict["macd"].to_numpy(dtype=np.float64)
    macd_sig = macd_dict["signal"].to_numpy(dtype=np.float64)

    sma20 = compute_sma(close_ser, 20).to_numpy(dtype=np.float64)
    sma50 = compute_sma(close_ser, 50).to_numpy(dtype=np.float64)
    sma200 = compute_sma(close_ser, 200).to_numpy(dtype=np.float64)
    ema20 = compute_ema(close_ser, 20).to_numpy(dtype=np.float64)
    atr14 = compute_atr_wilder(high_ser, low_ser, close_ser, period=14).to_numpy(dtype=np.float64)
    vol_sma20 = compute_sma(vol_ser, 20).to_numpy(dtype=np.float64)

    bb = compute_bollinger_bands(close_ser, window=20, num_std=2.0)
    bb_upper = bb["upper"].to_numpy(dtype=np.float64)
    bb_lower = bb["lower"].to_numpy(dtype=np.float64)

    st = compute_supertrend_causal(high_ser, low_ser, close_ser, period=10, multiplier=3.0)
    st_dir = st["direction"]

    # Trailing 20-bar highest high / lowest low for TTM Squeeze momentum midline
    hh20 = high_ser.rolling(window=20, min_periods=20).max().to_numpy(dtype=np.float64)
    ll20 = low_ser.rolling(window=20, min_periods=20).min().to_numpy(dtype=np.float64)

    # Prior 252-bar high (shifted by 1 so bar t compares against High[t-252 : t])
    prior_252_high = (
        high_ser.shift(1).rolling(window=252, min_periods=252).max().to_numpy(dtype=np.float64)
    )

    masks: Dict[str, np.ndarray] = {sig["id"]: np.zeros(n, dtype=bool) for sig in FROZEN_SIGNAL_CATALOG}

    # Precompute TTM squeeze state at each bar t
    kc_upper = ema20 + 1.5 * atr14
    kc_lower = ema20 - 1.5 * atr14
    squeeze_on = (
        np.isfinite(bb_upper)
        & np.isfinite(bb_lower)
        & np.isfinite(kc_upper)
        & np.isfinite(kc_lower)
        & (bb_upper < kc_upper)
        & (bb_lower > kc_lower)
    )
    mid_anchor = 0.5 * (0.5 * (hh20 + ll20) + ema20)
    squeeze_mom_pos = np.isfinite(mid_anchor) & (c > mid_anchor)

    for t in range(1, n):
        # 1. RSI(14) Oversold Recovery (> 30)
        if np.isfinite(rsi14[t - 1]) and np.isfinite(rsi14[t]):
            if rsi14[t - 1] <= 30.0 and rsi14[t] > 30.0:
                masks["rsi_oversold_recovery"][t] = True

            # 2. RSI(14) Overbought Continuation (>= 70)
            if rsi14[t - 1] < 70.0 and rsi14[t] >= 70.0:
                masks["rsi_70_continuation"][t] = True

            # 3. RSI(14) Overbought Reversal (< 70 from >= 70)
            if rsi14[t - 1] >= 70.0 and rsi14[t] < 70.0:
                masks["rsi_70_reversal"][t] = True

        # 4. MACD(12,26,9) Bullish Cross Below Zero
        if (
            np.isfinite(macd_line[t - 1])
            and np.isfinite(macd_sig[t - 1])
            and np.isfinite(macd_line[t])
            and np.isfinite(macd_sig[t])
        ):
            if (
                macd_line[t - 1] <= macd_sig[t - 1]
                and macd_line[t] > macd_sig[t]
                and macd_line[t] < 0.0
            ):
                masks["macd_bull_cross_below_zero"][t] = True

        # 5. Golden Cross (SMA 50 > SMA 200)
        if (
            np.isfinite(sma50[t - 1])
            and np.isfinite(sma200[t - 1])
            and np.isfinite(sma50[t])
            and np.isfinite(sma200[t])
        ):
            if sma50[t - 1] <= sma200[t - 1] and sma50[t] > sma200[t]:
                masks["golden_cross_50_200"][t] = True

        # 6. Supertrend(10, 3.0) Bullish Flip
        if np.isfinite(st_dir[t - 1]) and np.isfinite(st_dir[t]):
            if st_dir[t - 1] < 0.0 and st_dir[t] > 0.0:
                masks["supertrend_bull_flip"][t] = True

        # 7. TTM Squeeze Bullish Release
        if squeeze_on[t - 1] and (not squeeze_on[t]) and squeeze_mom_pos[t]:
            masks["ttm_squeeze_bull_release"][t] = True

        # 8. 50/200-DMA Trend Pullback & Bounce
        if (
            np.isfinite(sma50[t])
            and np.isfinite(sma200[t])
            and np.isfinite(sma50[t - 1])
            and sma50[t] > sma200[t]
            and c[t] > sma200[t]
        ):
            touched_50dma = (
                l[t] <= sma50[t] * 1.01
                and c[t] >= sma50[t]
                and c[t - 1] > sma50[t - 1]
                and l[t - 1] > sma50[t - 1] * 1.01
            )
            touched_200dma = (
                l[t] <= sma200[t] * 1.01
                and c[t] >= sma200[t]
                and c[t - 1] > sma200[t] * 1.01
            )
            if touched_50dma or touched_200dma:
                masks["dma_50_200_pullback"][t] = True

        # 9. 52-Week Breakout on 1.5x Volume
        if np.isfinite(prior_252_high[t]) and np.isfinite(vol_sma20[t]) and vol_sma20[t] > 0:
            if c[t] > prior_252_high[t] and c[t - 1] <= prior_252_high[t] and v[t] >= 1.5 * vol_sma20[t]:
                masks["breakout_52w_high_vol"][t] = True

        # 10. Bollinger Lower-Band Re-Entry (20, 2.0)
        if np.isfinite(bb_lower[t - 1]) and np.isfinite(bb_lower[t]):
            if c[t - 1] < bb_lower[t - 1] and c[t] >= bb_lower[t]:
                masks["bollinger_lower_reentry"][t] = True

    return masks


# ---------------------------------------------------------------------------
# 2. De-Clustering, Statistical Inference & BH-FDR Utilities
# ---------------------------------------------------------------------------

def decluster_event_indices(
    raw_indices: Sequence[int],
    cooldown_bars: int = DECLUSTER_COOLDOWN_BARS,
) -> List[int]:
    """
    Greedy causal de-clustering: accepts the first event index `t_0`, and then
    accepts subsequent `t_i` only when `t_i - t_last_accepted >= cooldown_bars`.
    """
    accepted: List[int] = []
    last_t: Optional[int] = None
    for idx in raw_indices:
        t = int(idx)
        if last_t is None or (t - last_t) >= cooldown_bars:
            accepted.append(t)
            last_t = t
    return accepted


def wilson_confidence_interval(
    wins: int,
    n: int,
    z: float = 1.959963984540054,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute Wilson score 95% confidence interval `(ci_low_pct, ci_high_pct)`
    for a binomial proportion `wins / n`, returned in percentage points `[0, 100]`.
    """
    if n <= 0:
        return None, None
    p_hat = float(wins) / float(n)
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    radicand = (p_hat * (1.0 - p_hat) / n) + (z2 / (4.0 * n * n))
    half_width = (z * math.sqrt(max(0.0, radicand))) / denom
    lo = max(0.0, min(1.0, center - half_width)) * 100.0
    hi = max(0.0, min(1.0, center + half_width)) * 100.0
    return round(lo, 2), round(hi, 2)


def _deterministic_seed(symbol: str, signal_id: str, horizon: int) -> int:
    digest = hashlib.sha256(f"{symbol}:{signal_id}:{horizon}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], byteorder="little") & 0x7FFFFFFF


def event_block_bootstrap_ci_and_pvalue(
    values: np.ndarray,
    horizon: int,
    seed: int,
    n_boot: int = BOOTSTRAP_ITERATIONS,
) -> Tuple[Optional[float], Optional[float], float]:
    """
    Compute event-block bootstrap 95% confidence interval `(ci_low, ci_high)`
    and two-sided p-value testing `H0: mean(values) == 0`.

    Block size in event space is `max(1, ceil(horizon / 20))` so any remaining
    horizon overlap after 20-bar de-clustering (e.g., h=60 -> block_len=3) is
    preserved during resampling.
    """
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    if n < 2:
        return None, None, 1.0

    obs_mean = float(np.mean(arr))
    obs_std = float(np.std(arr, ddof=1))
    if obs_std <= 1e-12:
        if abs(obs_mean) <= 1e-12:
            return round(obs_mean, 4), round(obs_mean, 4), 1.0
        return round(obs_mean, 4), round(obs_mean, 4), 1e-6

    block_len = max(1, int(math.ceil(float(horizon) / float(DECLUSTER_COOLDOWN_BARS))))
    rng = np.random.default_rng(seed)

    if block_len == 1 or n <= block_len:
        idx_matrix = rng.integers(0, n, size=(n_boot, n))
        boot_means = np.mean(arr[idx_matrix], axis=1)
    else:
        n_blocks = int(math.ceil(float(n) / float(block_len)))
        starts = rng.integers(0, n, size=(n_boot, n_blocks))
        offsets = np.arange(block_len, dtype=np.int64)[None, None, :]
        idx_matrix = (starts[:, :, None] + offsets).reshape(n_boot, n_blocks * block_len)[:, :n] % n
        boot_means = np.mean(arr[idx_matrix], axis=1)

    ci_low = float(np.percentile(boot_means, 2.5))
    ci_high = float(np.percentile(boot_means, 97.5))

    # Shift bootstrap distribution to H0 (mean = 0) and combine empirical + bootstrap-SE tail
    boot_se = float(np.std(boot_means, ddof=1))
    shifted = boot_means - obs_mean
    emp_extreme = float(np.sum(np.abs(shifted) >= abs(obs_mean)) + 1.0) / float(n_boot + 1.0)

    if boot_se > 1e-12:
        z_stat = abs(obs_mean) / boot_se
        norm_p = float(math.erfc(z_stat / math.sqrt(2.0)))
        # Combine bootstrap-t normal tail with empirical floor so extreme t-stats can pass BH-FDR
        p_val = min(emp_extreme, max(1e-8, norm_p)) if z_stat > 2.5 else 0.5 * (emp_extreme + norm_p)
    else:
        p_val = emp_extreme

    p_val = max(1e-8, min(1.0, p_val))
    return round(ci_low, 4), round(ci_high, 4), float(p_val)


def compute_benjamini_hochberg_qvalues(p_values: Sequence[float]) -> List[float]:
    """
    Compute Benjamini-Hochberg False Discovery Rate (BH-FDR) adjusted q-values
    across all `M` hypothesis tests (here `M = 40`).
    Guarantees `0 <= p_i <= q_i <= 1` and rank monotonicity.
    """
    m = len(p_values)
    if m == 0:
        return []

    p_arr = np.clip(np.asarray(p_values, dtype=np.float64), 0.0, 1.0)
    order = np.argsort(p_arr, kind="mergesort")
    ranked_p = p_arr[order]

    q_ranked = np.empty(m, dtype=np.float64)
    prev_q = 1.0
    for idx in range(m - 1, -1, -1):
        rank = idx + 1
        raw_q = (float(m) / float(rank)) * float(ranked_p[idx])
        prev_q = min(prev_q, raw_q, 1.0)
        q_ranked[idx] = max(float(ranked_p[idx]), prev_q)

    q_out = np.empty(m, dtype=np.float64)
    q_out[order] = q_ranked
    return [round(float(v), 6) for v in q_out]


def classify_backtest_cell(
    n_is: int,
    net_excess_is_pct: Optional[float],
    ci_low_is_pct: Optional[float],
    q_value: Optional[float],
    n_oos: int,
    net_excess_oos_pct: Optional[float],
    min_is_events: int = MIN_IS_EVENTS_REQUIRED,
) -> Tuple[str, str]:
    """
    Strict Phase 3 non-promotional classification rules:
      - If `n_is < 15`: `"Insufficient evidence"`
      - If `net_excess_is > 0`, 95% bootstrap CI excludes 0 (`ci_low_is > 0`),
        `q_value < 0.10`, AND `net_excess_oos > 0` (same positive sign in OOS):
        `"Historically favourable"`
      - Otherwise: `"No reliable edge"`
    """
    if (
        n_is < min_is_events
        or net_excess_is_pct is None
        or ci_low_is_pct is None
        or q_value is None
    ):
        return (
            "Insufficient evidence",
            f"In-sample de-clustered event count ({n_is}) is below the minimum requirement of {min_is_events} events.",
        )

    pos_is = net_excess_is_pct > 0.0
    ci_ex_zero = ci_low_is_pct > 0.0
    fdr_ok = q_value < FDR_Q_THRESHOLD
    oos_same_sign = (n_oos >= 1) and (net_excess_oos_pct is not None) and (net_excess_oos_pct > 0.0)

    if pos_is and ci_ex_zero and fdr_ok and oos_same_sign:
        return (
            "Historically favourable",
            "Net in-sample excess > 0, 95% bootstrap CI excludes 0, BH-FDR q < 0.10, and out-of-sample net excess has matching positive sign.",
        )

    reasons: List[str] = []
    if not pos_is:
        reasons.append("in-sample net excess <= 0%")
    elif not ci_ex_zero:
        reasons.append("95% bootstrap CI includes 0%")
    if not fdr_ok:
        reasons.append(f"BH-FDR q ({q_value:.3f}) >= {FDR_Q_THRESHOLD:.2f}")
    if not oos_same_sign:
        if n_oos == 0:
            reasons.append("0 out-of-sample events available for sign confirmation")
        else:
            reasons.append("out-of-sample net excess did not confirm positive sign")

    return (
        "No reliable edge",
        "Statistical gate not satisfied: " + "; ".join(reasons) + ".",
    )


# ---------------------------------------------------------------------------
# 3. Core Per-Stock Signal Backtester Engine
# ---------------------------------------------------------------------------

def _summarize_sample_slice(
    trades: List[Dict[str, Any]],
    uncond_mean_gross_pct: float,
    horizon: int,
    seed: int,
    compute_bootstrap: bool = True,
) -> Dict[str, Any]:
    """Aggregate trade-level statistics for a sample slice (IS, OOS, or Full)."""
    n = len(trades)
    if n == 0:
        return {
            "n_events": 0,
            "win_rate_net_pct": None,
            "win_rate_gross_pct": None,
            "wilson_95_ci_pct": [None, None],
            "mean_gross_return_pct": None,
            "mean_net_return_pct": None,
            "median_net_return_pct": None,
            "unconditional_drift_pct": round(float(uncond_mean_gross_pct), 4),
            "gross_excess_vs_drift_pct": None,
            "net_excess_vs_drift_pct": None,
            "net_excess_vs_benchmark_pct": None,
            "bootstrap_95_ci_pct": [None, None],
            "p_value": 1.0,
            "median_mae_pct": None,
            "p90_mae_pct": None,
            "median_mfe_pct": None,
            "p90_mfe_pct": None,
        }

    gross_arr = np.array([t["gross_return_pct"] for t in trades], dtype=np.float64)
    net_arr = np.array([t["net_return_pct"] for t in trades], dtype=np.float64)
    bench_ex_arr = np.array([t["net_excess_vs_benchmark_pct"] for t in trades], dtype=np.float64)
    mae_arr = np.array([t["mae_pct"] for t in trades], dtype=np.float64)
    mfe_arr = np.array([t["mfe_pct"] for t in trades], dtype=np.float64)

    gross_excess_arr = gross_arr - float(uncond_mean_gross_pct)
    net_excess_arr = net_arr - float(uncond_mean_gross_pct)

    wins_net = int(np.sum(net_arr > 0.0))
    wins_gross = int(np.sum(gross_arr > 0.0))
    w_lo, w_hi = wilson_confidence_interval(wins_net, n)

    if compute_bootstrap and n >= 2:
        ci_lo, ci_hi, p_val = event_block_bootstrap_ci_and_pvalue(
            values=net_excess_arr,
            horizon=horizon,
            seed=seed,
            n_boot=BOOTSTRAP_ITERATIONS,
        )
    else:
        ci_lo, ci_hi, p_val = None, None, 1.0

    return {
        "n_events": n,
        "win_rate_net_pct": round(100.0 * wins_net / n, 2),
        "win_rate_gross_pct": round(100.0 * wins_gross / n, 2),
        "wilson_95_ci_pct": [w_lo, w_hi],
        "mean_gross_return_pct": round(float(np.mean(gross_arr)), 4),
        "mean_net_return_pct": round(float(np.mean(net_arr)), 4),
        "median_net_return_pct": round(float(np.median(net_arr)), 4),
        "unconditional_drift_pct": round(float(uncond_mean_gross_pct), 4),
        "gross_excess_vs_drift_pct": round(float(np.mean(gross_excess_arr)), 4),
        "net_excess_vs_drift_pct": round(float(np.mean(net_excess_arr)), 4),
        "net_excess_vs_benchmark_pct": round(float(np.mean(bench_ex_arr)), 4),
        "bootstrap_95_ci_pct": [ci_lo, ci_hi],
        "p_value": round(float(p_val), 6),
        "median_mae_pct": round(float(np.median(mae_arr)), 3),
        "p90_mae_pct": round(float(np.percentile(mae_arr, 10.0)), 3),
        "median_mfe_pct": round(float(np.median(mfe_arr)), 3),
        "p90_mfe_pct": round(float(np.percentile(mfe_arr, 90.0)), 3),
    }


def run_per_stock_backtest(
    bundle: MarketHistoryBundle,
    round_trip_cost_bps: Optional[float] = None,
    horizons: Sequence[int] = BACKTEST_HORIZONS,
) -> Dict[str, Any]:
    """
    Execute the Phase 3 Per-Stock Signal Backtester across all 10 frozen signal
    definitions and 4 horizons (40 tests total) on `bundle.ohlc_tr`.
    """
    market = (bundle.market or "US").upper()
    default_cost_bps = DEFAULT_IN_COST_BPS if market == "IN" else DEFAULT_US_COST_BPS
    cost_bps = float(default_cost_bps if round_trip_cost_bps is None else max(0.0, float(round_trip_cost_bps)))
    cost_pct = cost_bps / 100.0  # in percentage points (e.g., 10 bps = 0.10%)

    df = bundle.ohlc_tr if (bundle.ohlc_tr is not None and not bundle.ohlc_tr.empty) else bundle.ohlc_split
    n = len(df) if df is not None else 0

    min_req_bars = COVERAGE_REQUIREMENTS["backtester"]["min_obs"]
    coverage_eligible = n >= min_req_bars

    if df is None or n < 30:
        return {
            "symbol": bundle.symbol,
            "market": market,
            "currency": bundle.currency,
            "currency_symbol": bundle.currency_symbol,
            "version": TA_BACKTEST_VERSION,
            "available": False,
            "coverage_eligible_5y": False,
            "observations": n,
            "min_recommended_observations": min_req_bars,
            "round_trip_cost_bps": cost_bps,
            "default_round_trip_cost_bps": default_cost_bps,
            "decluster_cooldown_bars": DECLUSTER_COOLDOWN_BARS,
            "horizons": list(horizons),
            "sample_split": None,
            "summary_counts": {
                "total_tests": len(FROZEN_SIGNAL_CATALOG) * len(horizons),
                "historically_favourable": 0,
                "no_reliable_edge": 0,
                "insufficient_evidence": len(FROZEN_SIGNAL_CATALOG) * len(horizons),
            },
            "signals": [],
            "tests": [],
            "pending_signals": [],
            "disclosure": SURVIVORSHIP_AND_LOOKBACK_DISCLOSURE,
        }

    dates = [str(idx)[:10] for idx in df.index]
    open_tr = df["Open"].astype(float).to_numpy(dtype=np.float64)
    high_tr = df["High"].astype(float).to_numpy(dtype=np.float64)
    low_tr = df["Low"].astype(float).to_numpy(dtype=np.float64)
    close_tr = df["Close"].astype(float).to_numpy(dtype=np.float64)

    # Align benchmark close to stock dates via causal forward-fill
    if bundle.benchmark_close is not None and not bundle.benchmark_close.empty:
        bench_aligned = (
            bundle.benchmark_close.reindex(df.index).ffill().bfill().astype(float).to_numpy(dtype=np.float64)
        )
    else:
        bench_aligned = close_tr.copy()

    # Chronological 70 / 30 split index
    split_idx = max(1, min(n - 1, int(math.floor(IS_SPLIT_RATIO * n))))
    sample_split_meta = {
        "is_ratio": IS_SPLIT_RATIO,
        "oos_ratio": round(1.0 - IS_SPLIT_RATIO, 2),
        "split_bar_index": split_idx,
        "is_observations": split_idx,
        "oos_observations": n - split_idx,
        "is_start_date": dates[0],
        "is_end_date": dates[split_idx - 1],
        "oos_start_date": dates[split_idx],
        "oos_end_date": dates[-1],
    }

    # Pre-compute unconditional open[t+1] -> close[t+h] percentage returns for each horizon
    uncond_by_horizon: Dict[int, Dict[str, float]] = {}
    for h in horizons:
        max_t = n - h
        if max_t <= 1:
            uncond_by_horizon[h] = {"is": 0.0, "oos": 0.0, "full": 0.0}
            continue
        valid_t = np.arange(0, max_t, dtype=np.int64)
        entry_p = open_tr[valid_t + 1]
        exit_p = close_tr[valid_t + h]
        valid_mask = (entry_p > 0) & np.isfinite(entry_p) & np.isfinite(exit_p)
        valid_t = valid_t[valid_mask]
        rets_pct = ((close_tr[valid_t + h] / open_tr[valid_t + 1]) - 1.0) * 100.0

        is_mask = valid_t < split_idx
        oos_mask = valid_t >= split_idx
        uncond_by_horizon[h] = {
            "is": float(np.mean(rets_pct[is_mask])) if np.any(is_mask) else 0.0,
            "oos": float(np.mean(rets_pct[oos_mask])) if np.any(oos_mask) else 0.0,
            "full": float(np.mean(rets_pct)) if len(rets_pct) > 0 else 0.0,
        }

    # Generate all 10 frozen signal masks
    signal_masks = generate_frozen_signal_masks(df)

    raw_cells: List[Dict[str, Any]] = []
    signals_overview: List[Dict[str, Any]] = []
    pending_signals: List[Dict[str, Any]] = []

    for sig in FROZEN_SIGNAL_CATALOG:
        sig_id = sig["id"]
        direction = int(sig["direction"])
        mask = signal_masks.get(sig_id, np.zeros(n, dtype=bool))
        raw_indices = np.where(mask)[0].tolist()
        declustered_indices = decluster_event_indices(raw_indices, cooldown_bars=DECLUSTER_COOLDOWN_BARS)

        raw_is_count = sum(1 for t in raw_indices if t < split_idx)
        raw_oos_count = sum(1 for t in raw_indices if t >= split_idx)
        dec_is_count = sum(1 for t in declustered_indices if t < split_idx)
        dec_oos_count = sum(1 for t in declustered_indices if t >= split_idx)

        # Record any active/pending signal triggered within the last max(horizons) bars
        max_h = max(horizons) if horizons else 60
        for t in declustered_indices:
            if t >= n - max_h:
                pending_horizons = [h for h in horizons if (t + h) >= n]
                if pending_horizons:
                    pending_signals.append(
                        {
                            "signal_id": sig_id,
                            "signal_name": sig["name"],
                            "direction_label": sig["direction_label"],
                            "signal_date": dates[t],
                            "signal_bar_index": int(t),
                            "bars_elapsed": int((n - 1) - t),
                            "entry_date": dates[t + 1] if (t + 1) < n else "Next Session Open",
                            "entry_price_tr": round(float(open_tr[t + 1]), 4) if (t + 1) < n else None,
                            "pending_horizons": pending_horizons,
                        }
                    )

        for h in horizons:
            # Completed trades require t + h < n (both entry t+1 and exit t+h exist in history)
            completed_raw = [t for t in raw_indices if (t + h) < n and open_tr[t + 1] > 0]
            completed_dec = [t for t in declustered_indices if (t + h) < n and open_tr[t + 1] > 0]

            trades_is: List[Dict[str, Any]] = []
            trades_oos: List[Dict[str, Any]] = []
            trades_full: List[Dict[str, Any]] = []

            for t in completed_dec:
                entry_idx = t + 1
                exit_idx = t + h
                ep = float(open_tr[entry_idx])
                xp = float(close_tr[exit_idx])
                if ep <= 0 or not np.isfinite(ep) or not np.isfinite(xp):
                    continue

                raw_ret_pct = ((xp / ep) - 1.0) * 100.0
                gross_ret_pct = float(direction) * raw_ret_pct
                net_ret_pct = gross_ret_pct - cost_pct

                # Benchmark return over matched [t+1, t+h] window
                b_start = float(bench_aligned[entry_idx])
                b_end = float(bench_aligned[exit_idx])
                if b_start > 0 and np.isfinite(b_start) and np.isfinite(b_end):
                    bench_ret_pct = ((b_end / b_start) - 1.0) * 100.0
                else:
                    bench_ret_pct = 0.0
                net_excess_bench_pct = net_ret_pct - (float(direction) * bench_ret_pct)

                # Path excursion over [t+1 .. t+h] inclusive
                win_high = float(np.max(high_tr[entry_idx : exit_idx + 1]))
                win_low = float(np.min(low_tr[entry_idx : exit_idx + 1]))
                if direction > 0:
                    mfe_pct = max(0.0, ((win_high / ep) - 1.0) * 100.0)
                    mae_pct = min(0.0, ((win_low / ep) - 1.0) * 100.0)
                else:
                    mfe_pct = max(0.0, (1.0 - (win_low / ep)) * 100.0)
                    mae_pct = min(0.0, (1.0 - (win_high / ep)) * 100.0)

                sample_tag = "IS" if t < split_idx else "OOS"
                trade_record = {
                    "signal_bar_index": int(t),
                    "signal_date": dates[t],
                    "entry_date": dates[entry_idx],
                    "exit_date": dates[exit_idx],
                    "sample": sample_tag,
                    "entry_price_tr": round(ep, 4),
                    "exit_price_tr": round(xp, 4),
                    "gross_return_pct": round(gross_ret_pct, 4),
                    "net_return_pct": round(net_ret_pct, 4),
                    "benchmark_return_pct": round(bench_ret_pct, 4),
                    "net_excess_vs_benchmark_pct": round(net_excess_bench_pct, 4),
                    "mae_pct": round(mae_pct, 3),
                    "mfe_pct": round(mfe_pct, 3),
                }
                trades_full.append(trade_record)
                if sample_tag == "IS":
                    trades_is.append(trade_record)
                else:
                    trades_oos.append(trade_record)

            uncond_is = float(direction) * uncond_by_horizon[h]["is"]
            uncond_oos = float(direction) * uncond_by_horizon[h]["oos"]
            uncond_full = float(direction) * uncond_by_horizon[h]["full"]

            seed = _deterministic_seed(bundle.symbol, sig_id, h)
            stats_is = _summarize_sample_slice(
                trades=trades_is,
                uncond_mean_gross_pct=uncond_is,
                horizon=h,
                seed=seed,
                compute_bootstrap=True,
            )
            stats_oos = _summarize_sample_slice(
                trades=trades_oos,
                uncond_mean_gross_pct=uncond_oos,
                horizon=h,
                seed=seed + 1,
                compute_bootstrap=(len(trades_oos) >= 2),
            )
            stats_full = _summarize_sample_slice(
                trades=trades_full,
                uncond_mean_gross_pct=uncond_full,
                horizon=h,
                seed=seed + 2,
                compute_bootstrap=(len(trades_full) >= 2),
            )

            raw_cells.append(
                {
                    "test_id": f"{sig_id}_{h}d",
                    "signal_id": sig_id,
                    "signal_name": sig["name"],
                    "category": sig["category"],
                    "direction": direction,
                    "direction_label": sig["direction_label"],
                    "rule_summary": sig["rule_summary"],
                    "parameters": sig["parameters"],
                    "horizon_days": int(h),
                    "counts": {
                        "n_raw_total": len(completed_raw),
                        "n_declustered_total": len(trades_full),
                        "n_raw_is": sum(1 for t in completed_raw if t < split_idx),
                        "n_is": len(trades_is),
                        "n_raw_oos": sum(1 for t in completed_raw if t >= split_idx),
                        "n_oos": len(trades_oos),
                    },
                    "in_sample": stats_is,
                    "out_of_sample": stats_oos,
                    "full_sample": stats_full,
                    "p_value_is": stats_is["p_value"],
                    "recent_events": trades_full[-25:],
                    "all_event_dates": [tr["signal_date"] for tr in trades_full],
                }
            )

        signals_overview.append(
            {
                "id": sig_id,
                "name": sig["name"],
                "category": sig["category"],
                "direction": direction,
                "direction_label": sig["direction_label"],
                "rule_summary": sig["rule_summary"],
                "parameters": sig["parameters"],
                "n_raw_triggers": len(raw_indices),
                "n_declustered_triggers": len(declustered_indices),
                "n_raw_is": raw_is_count,
                "n_declustered_is": dec_is_count,
                "n_raw_oos": raw_oos_count,
                "n_declustered_oos": dec_oos_count,
                "last_triggered_date": dates[declustered_indices[-1]] if declustered_indices else None,
            }
        )

    # Apply Benjamini-Hochberg FDR across all 40 tests jointly
    p_values_40 = [float(cell["p_value_is"]) for cell in raw_cells]
    q_values_40 = compute_benjamini_hochberg_qvalues(p_values_40)

    count_fav = 0
    count_no_edge = 0
    count_insuff = 0

    for cell, q_val in zip(raw_cells, q_values_40):
        cell["q_value_fdr"] = q_val
        cell["in_sample"]["q_value_fdr"] = q_val

        n_is = cell["counts"]["n_is"]
        n_oos = cell["counts"]["n_oos"]
        net_ex_is = cell["in_sample"]["net_excess_vs_drift_pct"]
        ci_lo_is = cell["in_sample"]["bootstrap_95_ci_pct"][0]
        net_ex_oos = cell["out_of_sample"]["net_excess_vs_drift_pct"]

        label, reason = classify_backtest_cell(
            n_is=n_is,
            net_excess_is_pct=net_ex_is,
            ci_low_is_pct=ci_lo_is,
            q_value=q_val,
            n_oos=n_oos,
            net_excess_oos_pct=net_ex_oos,
            min_is_events=MIN_IS_EVENTS_REQUIRED,
        )
        cell["label"] = label
        cell["label_reason"] = reason

        if label == "Historically favourable":
            count_fav += 1
        elif label == "Insufficient evidence":
            count_insuff += 1
        else:
            count_no_edge += 1

    # Attach per-signal horizon summary onto `signals_overview`
    cells_by_signal: Dict[str, List[Dict[str, Any]]] = {}
    for cell in raw_cells:
        cells_by_signal.setdefault(cell["signal_id"], []).append(cell)

    for sig_entry in signals_overview:
        sig_cells = cells_by_signal.get(sig_entry["id"], [])
        sig_entry["horizon_labels"] = {str(c["horizon_days"]): c["label"] for c in sig_cells}
        sig_entry["favourable_horizons"] = [
            c["horizon_days"] for c in sig_cells if c["label"] == "Historically favourable"
        ]

    return {
        "symbol": bundle.symbol,
        "market": market,
        "currency": bundle.currency,
        "currency_symbol": bundle.currency_symbol,
        "benchmark": bundle.benchmark,
        "version": TA_BACKTEST_VERSION,
        "available": True,
        "coverage_eligible_5y": coverage_eligible,
        "coverage_note": (
            None
            if coverage_eligible
            else f"History length ({n} bars) is below the 5-year ({min_req_bars} bars) walk-forward benchmark; sparse signals are gated as 'Insufficient evidence'."
        ),
        "observations": n,
        "min_recommended_observations": min_req_bars,
        "execution_contract": {
            "signal_observation": "Confirmed daily bar close t",
            "entry_fill": "Next trading session open Open_tr[t + 1]",
            "exit_fill": "Trading session close Close_tr[t + h]",
            "price_basis": "Total-Return Adjusted (ohlc_tr)",
            "decluster_cooldown_bars": DECLUSTER_COOLDOWN_BARS,
            "is_oos_split": "70% Chronological In-Sample / 30% Out-of-Sample",
            "min_is_events": MIN_IS_EVENTS_REQUIRED,
            "fdr_method": "Benjamini-Hochberg (BH-FDR) across M = 40 tests",
            "fdr_q_threshold": FDR_Q_THRESHOLD,
        },
        "round_trip_cost_bps": cost_bps,
        "default_round_trip_cost_bps": default_cost_bps,
        "decluster_cooldown_bars": DECLUSTER_COOLDOWN_BARS,
        "horizons": list(horizons),
        "sample_split": sample_split_meta,
        "summary_counts": {
            "total_tests": len(raw_cells),
            "historically_favourable": count_fav,
            "no_reliable_edge": count_no_edge,
            "insufficient_evidence": count_insuff,
        },
        "signals": signals_overview,
        "tests": raw_cells,
        "pending_signals": pending_signals,
        "disclosure": SURVIVORSHIP_AND_LOOKBACK_DISCLOSURE,
    }
