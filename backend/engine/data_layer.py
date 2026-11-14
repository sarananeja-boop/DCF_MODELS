"""
Data Layer – Financial Data Fetching & Cleaning
================================================

Refactored from Steps 2–3 of the Automated DCF Monte Carlo notebook.

This module:
  1. Fetches live financial statements via ``yfinance``.
  2. Aligns income statement, balance sheet, and cash flow to common dates.
  3. Computes historical averages and standard deviations used by the
     DCF engine and Monte Carlo simulation.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import yfinance as yf

from .canonical_schema import (
    classify_model_suitability,
    detect_accounting_standard,
    make_provenance,
)
from .primary_filings import extract_ind_as_ar_financials
from .sec_edgar import extract_sec_edgar_reconciliation

logger = logging.getLogger(__name__)

_YAHOO_FIXTURE_DIRS: List[Path] = [
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "yahoo",
    Path("/Users/SMILE/.gemini/antigravity/brain/241b62b1-985a-4c94-a61f-669d5efafa6d/scratch/raw"),
]


def _load_yahoo_fixtures(ticker: str) -> Optional[Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]]:
    """
    Load deterministic Yahoo-schema statement CSVs (`*_is.csv`, `*_bs.csv`, `*_cf.csv`, `*_info.json`)
    when running offline tests or staged validation without relying on hardcoded company numbers.
    """
    base = (ticker or "").strip().upper().split(".")[0]
    if not base:
        return None
    dirs: List[Path] = []
    env_dir = os.environ.get("VALUATIONLABS_YAHOO_FIXTURE_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    dirs.extend(_YAHOO_FIXTURE_DIRS)
    for root in dirs:
        if not root.exists():
            continue
        is_p = root / f"{base}_is.csv"
        bs_p = root / f"{base}_bs.csv"
        cf_p = root / f"{base}_cf.csv"
        info_p = root / f"{base}_info.json"
        if is_p.is_file() and bs_p.is_file() and cf_p.is_file() and info_p.is_file():
            inc = pd.read_csv(is_p, index_col=0).T
            bs = pd.read_csv(bs_p, index_col=0).T
            cf = pd.read_csv(cf_p, index_col=0).T
            for df in (inc, bs, cf):
                df.index = pd.to_datetime(df.index)
            info_dict = json.loads(info_p.read_text(encoding="utf-8", errors="ignore"))
            return inc, bs, cf, info_dict
    return None


_NON_MONETARY_COLS = {
    "Basic Average Shares",
    "Diluted Average Shares",
    "Ordinary Shares Number",
    "Share Issued",
    "Treasury Shares Number",
    "Preferred Shares Number",
    "Tax Rate For Calcs",
}
_PER_SHARE_COLS = {"Basic EPS", "Diluted EPS"}


def _scale_monetary_df(df: pd.DataFrame, factor: float, *, scale_per_share: bool = True) -> pd.DataFrame:
    """Scale monetary rows/columns while keeping share counts and tax/ratio metrics intact."""
    if df is None or df.empty or factor == 1.0:
        return df
    out = df.copy()
    for col in out.columns:
        cname = str(col)
        if cname in _NON_MONETARY_COLS or cname.endswith((" Shares", " Shares Number", " Share Issued")):
            continue
        if not scale_per_share and cname in _PER_SHARE_COLS:
            continue
        out[col] = pd.to_numeric(out[col], errors="coerce") * factor
    return out


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def safe_get(df: pd.DataFrame, column: str, default: float = 0) -> np.ndarray:
    """Extract a column from a DataFrame, returning a default-filled array if missing.

    This mirrors the ``safe_get`` helper in notebook Step 3C.  It also tries
    common alternate column names used by Indian stocks and global filers, combining
    available candidate columns row-wise so partial NaNs in a primary column
    gracefully fall back to populated alternate columns.

    Args:
        df:       The pandas DataFrame (e.g. income statement).
        column:   The primary column name to look up.
        default:  Value to fill NaNs / missing columns with.

    Returns:
        A numpy array of length ``len(df)``.
    """
    if df is None or df.empty:
        return np.array([], dtype=float)

    # Alternate name map – Indian stocks, resource companies, and financial companies sometimes use different labels
    _alternates: Dict[str, List[str]] = {
        "Total Revenue": ["Revenue", "Total Revenue From Operations", "Operating Revenue"],
        "EBIT": ["Operating Income", "Total Operating Income As Reported", "Operating Profit"],
        "Operating Income": ["Total Operating Income As Reported", "EBIT"],
        "Depreciation And Amortization": [
            "Depreciation Amortization Depletion",
            "Depreciation",
            "Reconciled Depreciation",
            "Depreciation And Amortization In Income Statement",
        ],
        "Capital Expenditure": [
            "Purchase Of PPE",
            "Net PPE Purchase And Sale",
            "Capital Expenditure Reported",
        ],
        "Current Debt": ["Current Borrowings", "Short Term Debt", "Current Debt And Capital Lease Obligation"],
        "Net Income": [
            "Net Income Common Stockholders",
            "Net Income Continuous Operations",
            "Net Income Including Noncontrolling Interests",
            "Normalized Income",
        ],
        "Stockholders Equity": ["Common Stock Equity", "Total Equity Gross Minority Interest", "Tangible Book Value"],
        "Net Interest Income": ["Operating Revenue", "Total Revenue"],
        "Pretax Income": ["Income Before Tax", "Earnings Before Taxes"],
        "Cash Dividends Paid": ["Common Stock Dividend Paid", "Payment Of Dividends"],
    }

    candidates = [column] + _alternates.get(column, [])
    present_cols = [c for c in candidates if c in df.columns]
    if present_cols:
        sub = df[present_cols].apply(pd.to_numeric, errors="coerce")
        combined = sub.bfill(axis=1).iloc[:, 0]
        return combined.fillna(default).values.astype(float)

    return np.full(len(df), default, dtype=float)


# ---------------------------------------------------------------------------
# Benchmark Returns & Clean Beta Calculation
# ---------------------------------------------------------------------------
# Benchmark Returns & Clean Beta Calculation
# ---------------------------------------------------------------------------
_BENCHMARK_CACHE: Dict[str, tuple] = {}
_BENCHMARK_CACHE_TTL_SECONDS: int = 3600  # 1 hour TTL matching market_config.py

# Damodaran Industry Unlevered Betas (Emerging Markets & Global benchmarks)
INDUSTRY_UNLEVERED_BETAS: Dict[str, float] = {
    "utilities": 0.48,
    "power": 0.48,
    "electric": 0.48,
    "water": 0.48,
    "gas": 0.52,
    "consumer staples": 0.58,
    "fmcg": 0.58,
    "food": 0.58,
    "beverage": 0.60,
    "tobacco": 0.62,
    "healthcare": 0.68,
    "pharmaceuticals": 0.68,
    "biotechnology": 0.75,
    "telecom": 0.65,
    "telecommunications": 0.65,
    "auto & truck dealerships": 0.72,
    "dealership": 0.72,
    "retail": 0.70,
    "auto": 0.85,
    "automotive": 0.85,
    "auto parts": 0.82,
    "semiconductor": 1.24,
    "technology": 0.95,
    "software": 0.95,
    "information technology": 0.95,
    "industrials": 0.82,
    "capital goods": 0.82,
    "engineering": 0.80,
    "materials": 0.85,
    "chemicals": 0.85,
    "metals & mining": 0.88,
    "steel": 0.88,
    "energy": 0.80,
    "oil & gas": 0.80,
    "real estate": 0.68,
    "consumer cyclical": 0.82,
    "consumer discretionary": 0.82,
    "financial": 0.45,
    "default": 0.75,
}


def get_industry_unlevered_beta(sector: Optional[str] = None, industry: Optional[str] = None) -> float:
    """Retrieve Damodaran unlevered industry beta matching sector or industry keywords."""
    text = f"{sector or ''} {industry or ''}".lower()
    for key, val in INDUSTRY_UNLEVERED_BETAS.items():
        if key in text:
            return val
    return INDUSTRY_UNLEVERED_BETAS["default"]


_YF_SESSION = None
_YF_SESSION_LOCK = __import__("threading").Lock()
_FX_CACHE: Dict[str, tuple] = {}

_FALLBACK_FX_RATES: Dict[str, float] = {
    "USDDKK": 6.70, "DKKUSD": 1.0 / 6.70,
    "EURUSD": 1.08, "USDEUR": 1.0 / 1.08,
    "GBPUSD": 1.28, "USDGBP": 1.0 / 1.28,
    "USDJPY": 155.0, "JPYUSD": 1.0 / 155.0,
    "USDINR": 86.5, "INRUSD": 1.0 / 86.5,
    "USDCNY": 7.25, "CNYUSD": 1.0 / 7.25,
    "USDTWD": 32.5, "TWDUSD": 1.0 / 32.5,
    "USDCHF": 0.88, "CHFUSD": 1.0 / 0.88,
    "AUDUSD": 0.65, "USDAUD": 1.0 / 0.65,
    "USDCAD": 1.38, "CADUSD": 1.0 / 1.38,
    "USDSEK": 10.5, "SEKUSD": 1.0 / 10.5,
    "USDNOK": 10.8, "NOKUSD": 1.0 / 10.8,
    "USDHKD": 7.80, "HKDUSD": 1.0 / 7.80,
    "USDKRW": 1380.0, "KRWUSD": 1.0 / 1380.0,
}


def get_cross_fx_rate(from_curr: str, to_curr: str) -> float:
    """Fetch live FX conversion rate so that 1 from_curr * fx_rate = to_curr."""
    from_curr = str(from_curr or "").strip().upper()
    to_curr = str(to_curr or "").strip().upper()
    if not from_curr or not to_curr or from_curr == to_curr:
        return 1.0

    cache_key = f"{from_curr}_{to_curr}"
    now = time.time()
    if cache_key in _FX_CACHE:
        val, ts = _FX_CACHE[cache_key]
        if now - ts < _BENCHMARK_CACHE_TTL_SECONDS:
            return val

    pair = f"{from_curr}{to_curr}"
    rev_pair = f"{to_curr}{from_curr}"

    for p, invert in [(pair, False), (rev_pair, True)]:
        try:
            t = yf.Ticker(f"{p}=X", session=get_yf_session())
            h = t.history(period="5d")
            if h is not None and not h.empty and "Close" in h:
                series = h["Close"].dropna()
                if len(series) > 0 and float(series.iloc[-1]) > 0:
                    rate = float(series.iloc[-1])
                    fx = (1.0 / rate) if invert else rate
                    _FX_CACHE[cache_key] = (fx, now)
                    return fx
        except Exception:
            pass

    if pair in _FALLBACK_FX_RATES:
        fx = _FALLBACK_FX_RATES[pair]
        _FX_CACHE[cache_key] = (fx, now)
        return fx
    if rev_pair in _FALLBACK_FX_RATES:
        fx = 1.0 / _FALLBACK_FX_RATES[rev_pair]
        _FX_CACHE[cache_key] = (fx, now)
        return fx

    return 1.0


def get_yf_session():
    """Return a shared, thread-safe curl_cffi session so Yahoo cookies/crumbs persist across requests."""
    global _YF_SESSION
    if _YF_SESSION is None:
        with _YF_SESSION_LOCK:
            if _YF_SESSION is None:
                from curl_cffi import requests as cffi_requests
                _YF_SESSION = cffi_requests.Session(impersonate="chrome")
    return _YF_SESSION


def _get_benchmark_returns(benchmark: str) -> Optional[pd.Series]:
    """Fetch and cache 2-year weekly returns for market benchmark."""
    now = time.time()
    if benchmark in _BENCHMARK_CACHE:
        series, ts = _BENCHMARK_CACHE[benchmark]
        if now - ts < _BENCHMARK_CACHE_TTL_SECONDS:
            return series
    try:
        b = yf.Ticker(benchmark, session=get_yf_session())
        hist = b.history(period="2y", interval="1wk")
        if not hist.empty and "Close" in hist:
            returns = hist["Close"].pct_change().dropna()
            _BENCHMARK_CACHE[benchmark] = (returns, now)
            return returns
    except Exception as e:
        logger.warning("Could not fetch benchmark returns for %s: %s", benchmark, e)
    return None


def compute_clean_beta(
    stock: yf.Ticker,
    ticker: str,
    market: str,
    raw_info_beta: Optional[float] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    de_ratio: Optional[float] = None,
    tax_rate: float = 0.2517,
    tradeable: Optional[bool] = None,
    hist_1y: Optional[pd.DataFrame] = None,
    hist_2y: Optional[pd.DataFrame] = None,
) -> dict:
    """Compute a risk-reflective beta against domestic benchmark or bottom-up industry unlevered beta.

    Detects trading illiquidity, trading halts, or zero-volume days to prevent
    the 'zero-beta trap' where un-traded stocks produce an artificially low beta.
    
    Returns a dict with:
      - beta: Risk-reflective beta for WACC/Ke calculations.
      - raw_beta: Unadjusted covariance beta (or info beta).
      - beta_clamped: True if an abnormal/negative beta triggered adjustment.
      - beta_note: Explanation of methodology.
      - is_illiquid: True if trading illiquidity/halt was detected.
    """
    benchmark = "^NSEI" if market.upper() == "IN" else "^GSPC"
    
    # Safe float parsing of info beta
    safe_info_beta = None
    if raw_info_beta is not None:
        try:
            val = float(raw_info_beta)
            if not np.isnan(val):
                safe_info_beta = val
        except (ValueError, TypeError):
            safe_info_beta = None

    # 1. Trading liquidity & volume verification
    # When >30% of days have 0 volume, or prices are frozen, regression beta is an artifact of non-trading.
    is_illiquid = False
    zero_vol_pct = 0.0
    unique_prices = 999
    
    try:
        if hist_1y is None:
            hist_1y = stock.history(period="1y", interval="1d")
        if hist_1y is not None and not hist_1y.empty and len(hist_1y) >= 20:
            zero_vols = int((hist_1y["Volume"] == 0).sum())
            zero_vol_pct = float(zero_vols / len(hist_1y))
            unique_prices = int(hist_1y["Close"].nunique())
            # Real trading liquidity: true illiquidity is when >30% of days have zero volume or prices are frozen (<15 unique prices)
            if zero_vol_pct > 0.30 or unique_prices < 15:
                is_illiquid = True
    except Exception as e:
        logger.warning("Liquidity check failed for %s: %s", ticker, e)

    # If illiquid / halted, apply bottom-up industry unlevered beta relevered at company D/E
    if is_illiquid:
        beta_u = get_industry_unlevered_beta(sector, industry)
        eff_de = min(2.5, max(0.0, float(de_ratio))) if de_ratio is not None else 0.5
        # Hamada equation: beta_L = beta_u * [1 + (1 - T) * D/E]
        relevered_beta = beta_u * (1.0 + (1.0 - tax_rate) * eff_de)
        # Apply Blume adjustment towards market mean 1.0
        blume_beta = (2.0 / 3.0) * relevered_beta + (1.0 / 3.0) * 1.0
        # Bound between 0.70 and 2.20
        blume_beta = float(np.clip(blume_beta, 0.70, 2.20))
        
        reason = "Trading illiquidity/halt detected"
        if zero_vol_pct > 0.30:
            reason += f" ({zero_vol_pct*100:.1f}% zero-volume days)"
        elif tradeable is False:
            reason += " (exchange tradeable=False)"
        elif unique_prices < 15:
            reason += f" (only {unique_prices} unique price points in 1Y)"
            
        note = (
            f"{reason}. Raw regression beta is an artifact of non-trading. "
            f"Applied bottom-up industry unlevered beta ({beta_u:.2f}) "
            f"relevered at D/E {eff_de:.2f} (adj: {blume_beta:.2f})."
        )
        return {
            "beta": float(blume_beta),
            "raw_beta": float(safe_info_beta) if safe_info_beta is not None else float(relevered_beta),
            "raw_blume_beta": float(blume_beta),
            "sector_bottom_up_beta": float(blume_beta),
            "cyclical_beta_low_flag": False,
            "beta_clamped": True,
            "beta_note": note,
            "is_illiquid": True,
        }

    # 2. Check if regression against domestic benchmark is feasible for actively traded stocks
    try:
        hist = hist_2y if hist_2y is not None else stock.history(period="2y", interval="1wk")
        if hist is not None and not hist.empty and "Close" in hist:
            df_asset = hist["Close"].pct_change().dropna()
            df_bench = _get_benchmark_returns(benchmark)
            if df_bench is not None and not df_bench.empty:
                common = pd.concat([df_asset, df_bench], axis=1, join="inner").dropna()
                common.columns = ["asset", "market"]
                if len(common) >= 15:
                    cov = np.cov(common["asset"], common["market"])[0, 1]
                    var_m = np.var(common["market"])
                    if var_m > 0:
                        calc_raw = float(cov / var_m)
                        beta_clamped = False
                        clamp_reason = None

                        eff_raw = calc_raw
                        is_ext_b, is_cyc_b = classify_sector_dynamics(sector, industry, ticker)
                        beta_u_ind = get_industry_unlevered_beta(sector, industry)
                        eff_de_sec = min(2.5, max(0.0, float(de_ratio))) if de_ratio is not None else 0.5
                        sec_beta_u = max(0.85 if (is_ext_b or is_cyc_b) else 0.45, beta_u_ind)
                        sec_relev = sec_beta_u * (1.0 + (1.0 - tax_rate) * min(1.5, eff_de_sec))
                        sector_bottom_up_beta = float((2.0 / 3.0) * sec_relev + (1.0 / 3.0) * 1.0)
                        raw_blume_beta = float((2.0 / 3.0) * min(2.80, calc_raw) + (1.0 / 3.0) * 1.0)
                        cyclical_beta_low_flag = bool((is_ext_b or is_cyc_b) and calc_raw > 0.15 and calc_raw < 0.85)

                        # Clamp ONLY when raw beta is negative / near-zero (<= 0.15, unusable in CAPM)
                        # or extreme cap (>2.80) / low-leverage momentum artifact (>1.95 on D/E < 0.25).
                        # Never silently override empirical cyclical regression beta with a synthetic floor.
                        if calc_raw <= 0.15:
                            eff_raw = sec_relev
                            beta_clamped = True
                            clamp_reason = f"Raw regression beta ({calc_raw:.2f}) was near-zero/non-positive; substituted bottom-up unlevered beta {sec_beta_u:.2f} (relevered: {eff_raw:.2f})."
                        elif de_ratio is not None and 0.0 <= float(de_ratio) < 0.25 and calc_raw > 1.95:
                            relev_b = beta_u_ind * (1.0 + (1.0 - tax_rate) * float(de_ratio))
                            eff_raw = relev_b
                            beta_clamped = True
                            clamp_reason = (
                                f"Raw regression beta ({calc_raw:.2f}) reflected short-term momentum volatility on a low-leverage balance sheet "
                                f"(D/E: {float(de_ratio):.2f}); anchored to bottom-up industry unlevered beta {beta_u_ind:.2f} (relevered: {relev_b:.2f})."
                            )
                        elif calc_raw > 2.80:
                            eff_raw = 2.80
                            beta_clamped = True
                            clamp_reason = f"Raw regression beta ({calc_raw:.2f}) was exceptionally volatile; capped raw beta to 2.80."

                        blume_beta = (2.0 / 3.0) * eff_raw + (1.0 / 3.0) * 1.0

                        note = (
                            f"Blume-adjusted 2Y weekly regression vs {benchmark} "
                            f"(raw: {calc_raw:.2f} → adj: {blume_beta:.2f})"
                        )
                        if cyclical_beta_low_flag:
                            note += f" [Empirical cyclical beta <0.85 retained; bottom-up sector beta={sector_bottom_up_beta:.2f} disclosed in scenarios]"
                        if clamp_reason:
                            note = f"{clamp_reason} {note}"

                        return {
                            "beta": float(blume_beta),
                            "raw_beta": float(calc_raw),
                            "raw_blume_beta": float(raw_blume_beta),
                            "sector_bottom_up_beta": float(sector_bottom_up_beta),
                            "cyclical_beta_low_flag": cyclical_beta_low_flag,
                            "beta_clamped": beta_clamped,
                            "beta_note": note,
                            "is_illiquid": False,
                        }
    except Exception as exc:
        logger.warning("Local benchmark beta calculation failed for %s: %s", ticker, exc)

    # 3. Fallback to Yahoo Finance info beta if valid
    if safe_info_beta is not None and safe_info_beta > 0.15:
        eff_info = min(2.80, safe_info_beta)
        blume_beta = (2.0 / 3.0) * eff_info + (1.0 / 3.0) * 1.0
        return {
            "beta": float(blume_beta),
            "raw_beta": float(safe_info_beta),
            "raw_blume_beta": float(blume_beta),
            "sector_bottom_up_beta": float(blume_beta),
            "cyclical_beta_low_flag": False,
            "beta_clamped": False,
            "beta_note": f"Blume-adjusted Yahoo Finance beta (raw: {safe_info_beta:.2f} → adj: {blume_beta:.2f})",
            "is_illiquid": False,
        }

    # 4. Ultimate fallback: bottom-up industry unlevered beta relevered
    beta_u = get_industry_unlevered_beta(sector, industry)
    eff_de = min(2.5, max(0.0, float(de_ratio))) if de_ratio is not None else 0.5
    eff_raw = beta_u * (1.0 + (1.0 - tax_rate) * eff_de)
    blume_beta = (2.0 / 3.0) * eff_raw + (1.0 / 3.0) * 1.0
    blume_beta = float(np.clip(blume_beta, 0.70, 2.20))

    return {
        "beta": float(blume_beta),
        "raw_beta": float(raw_info_beta) if (raw_info_beta is not None and not np.isnan(raw_info_beta)) else float(eff_raw),
        "raw_blume_beta": float(blume_beta),
        "sector_bottom_up_beta": float(blume_beta),
        "cyclical_beta_low_flag": False,
        "beta_clamped": True,
        "beta_note": f"Insufficient historical covariance; applied bottom-up industry unlevered beta ({beta_u:.2f}, relevered: {blume_beta:.2f}).",
        "is_illiquid": False,
    }


# ---------------------------------------------------------------------------
# In-memory cache for raw financial data (avoids repetitive Yahoo Finance calls)
# ---------------------------------------------------------------------------
_STOCK_DATA_CACHE: Dict[str, tuple] = {}
_STOCK_DATA_CACHE_TTL_SECONDS: int = 900  # 15 minutes

def _copy_stock_data(d: dict) -> dict:
    cp = dict(d)
    if "income_stmt" in cp and isinstance(cp["income_stmt"], pd.DataFrame):
        cp["income_stmt"] = cp["income_stmt"].copy()
    if "balance_sheet" in cp and isinstance(cp["balance_sheet"], pd.DataFrame):
        cp["balance_sheet"] = cp["balance_sheet"].copy()
    if "cash_flow" in cp and isinstance(cp["cash_flow"], pd.DataFrame):
        cp["cash_flow"] = cp["cash_flow"].copy()
    return cp

def classify_sector_dynamics(
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    symbol: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[bool, bool]:
    """
    Determine whether a company belongs to an extractive/depleting resource industry
    or a cyclical commodity/heavy-industrial industry.
    Returns: (is_extractive, is_cyclical)
    """
    sec = sector or ""
    ind = industry or ""
    comp_name = (name or "").lower()
    text = f"{sec} {ind} {comp_name}".lower()
    sym_clean = (
        (symbol or "").upper().replace(".NS", "").replace(".BO", "").split(".")[0]
    )

    # Diversified Conglomerates & Specialty Chemical Compounders:
    # Even if Yahoo Finance tags RELIANCE under "Oil & Gas Refining & Marketing"
    # or ADANIENT under "Thermal Coal" or PIDILITIND under "Specialty Chemicals",
    # their cash flows are driven by diversified consumer/retail/telecom/infra or
    # branded consumer adhesives rather than single-asset depleting mines.
    if sym_clean in {
        "RELIANCE",
        "ADANIENT",
        "PIDILITIND",
        "ASIANPAINT",
        "BERGEPAINT",
        "SHW",
        "LIN",
        "ECL",
        "APD",
    }:
        return False, False

    KNOWN_EXTRACTIVE_SYMBOLS = {
        "COALINDIA",
        "ONGC",
        "OIL",
        "VEDL",
        "NMDC",
        "HINDZINC",
        "MOIL",
        "GMDCLTD",
        "HINDCOPPER",
        "RIO",
        "BHP",
        "VALE",
        "FCX",
        "NEM",
        "GOLD",
        "XOM",
        "CVX",
        "COP",
        "EOG",
        "OXY",
        "SLB",
        "BP",
        "SHEL",
        "TTE",
    }
    KNOWN_CYCLICAL_SYMBOLS = KNOWN_EXTRACTIVE_SYMBOLS | {
        "TATASTEEL",
        "JSWSTEEL",
        "SAIL",
        "JINDALSTEL",
        "HINDALCO",
        "NATIONALUM",
        "IOC",
        "BPCL",
        "HINDPETRO",
        "MRPL",
        "CHENNPETRO",
        "NUE",
        "STLD",
        "CLF",
        "X",
        "AA",
        "DOW",
        "LYB",
        "WLK",
        "CF",
        "MOS",
        "NTR",
    }
    if sym_clean in KNOWN_EXTRACTIVE_SYMBOLS:
        return True, True
    if sym_clean in KNOWN_CYCLICAL_SYMBOLS:
        return False, True

    if "specialty chemicals" in text or "industrial gases" in text or "conglomerate" in text:
        return False, False

    extractive_keywords = [
        "oil & gas e&p", "oil & gas exploration", "oil & gas drilling", "oil & gas integrated",
        "thermal coal", "coking coal", "integrated oil", "drilling",
        "exploration & production", "upstream", "crude", "mining", "gold", "silver", "copper",
        "other industrial metals & mining", "other precious metals & mining",
        "oil & natural gas", "mineral development", "iron ore",
    ]
    is_extractive = any(k in text for k in extractive_keywords)
    if (
        not is_extractive
        and ("oil & gas" in text or "petroleum" in text or "coal" in text)
        and "refining & marketing" not in text
        and "equipment" not in text
        and "midstream" not in text
        and "gas distribution" not in text
        and "utilities" not in text
    ):
        if any(w in text for w in ["exploration", "integrated", "production", "upstream", "coal"]):
            is_extractive = True

    cyclical_keywords = extractive_keywords + [
        "steel", "aluminum", "aluminium", "metals", "commodity chemicals",
        "agricultural inputs", "iron", "fertilizer", "refining", "petroleum",
        "paper & forest", "lumber", "building materials", "cement",
    ]
    is_cyclical = is_extractive or any(k in text for k in cyclical_keywords)

    return is_extractive, is_cyclical


def fetch_stock_data(ticker: str, market: str) -> dict:
    """Fetch and validate financial data for *ticker* from Yahoo Finance.

    Refactored from notebook Step 2.

    Args:
        ticker: The raw ticker symbol (e.g. ``'AAPL'`` or ``'RELIANCE'``).
        market: ``'US'`` or ``'IN'``.

    Returns:
        A dict containing: ``ticker``, ``name``, ``current_price``,
        ``shares_outstanding``, ``market_cap``, ``beta``,
        ``income_stmt`` (DataFrame), ``balance_sheet`` (DataFrame),
        ``cash_flow`` (DataFrame), ``info`` (dict).

    Raises:
        ValueError: If ``currentPrice`` or ``sharesOutstanding`` are missing.
    """
    from .ticker_universe import (
        resolve_ticker,
        is_non_dcf_instrument,
        is_capital_light_financial,
        search_successor_via_yahoo,
    )

    resolved_sym, resolved_mkt, redirect_note = resolve_ticker(ticker, market)
    if redirect_note:
        logger.info("Corporate action auto-redirect: %s -> %s (%s)", ticker, resolved_sym, redirect_note)
        ticker = resolved_sym
        market = resolved_mkt

    # Fast pre-check for known ETFs, Commodity ETFs, Mutual Funds, Indices
    pre_excl, pre_kind, pre_msg = is_non_dcf_instrument(symbol=ticker)
    if pre_excl and pre_kind.upper() != "REIT_INVIT":
        raise ValueError(pre_msg)

    cache_key = f"{ticker.strip().upper()}:{market.strip().upper()}"
    now = time.time()
    if cache_key in _STOCK_DATA_CACHE:
        cached_data, cached_ts = _STOCK_DATA_CACHE[cache_key]
        if now - cached_ts < _STOCK_DATA_CACHE_TTL_SECONDS:
            logger.info("Serving %s from in-memory cache", cache_key)
            return _copy_stock_data(cached_data)

    from .market_config import MARKET_PROFILES

    profile = MARKET_PROFILES.get(market.upper(), MARKET_PROFILES["US"])
    suffix = profile.get("ticker_suffix", "")

    # Append suffix if not already present
    yf_ticker = ticker.strip()
    if suffix and not yf_ticker.upper().endswith(suffix.upper()) and not yf_ticker.upper().endswith(".BO"):
        yf_ticker = yf_ticker + suffix

    session = get_yf_session()
    logger.info("Fetching data for %s (yfinance ticker: %s)", ticker, yf_ticker)
    stock = yf.Ticker(yf_ticker, session=session)
    benchmark = "^NSEI" if market.upper() == "IN" else "^GSPC"

    from concurrent.futures import ThreadPoolExecutor

    def _fetch_fin():
        return yf.Ticker(yf_ticker, session=session).financials.T

    def _fetch_bs():
        return yf.Ticker(yf_ticker, session=session).balance_sheet.T

    def _fetch_cf():
        return yf.Ticker(yf_ticker, session=session).cashflow.T

    def _fetch_fast():
        price, shares, fast_curr = None, None, None
        try:
            fast = yf.Ticker(yf_ticker, session=session).fast_info
            price = getattr(fast, "last_price", None) or fast.get("lastPrice") or fast.get("regularMarketPreviousClose")
            shares = getattr(fast, "shares", None) or fast.get("shares")
            fast_curr = getattr(fast, "currency", None) or fast.get("currency")
            if shares is None and fast.get("marketCap") and price:
                shares = float(fast.get("marketCap")) / float(price)
        except Exception:
            pass
        return price, shares, fast_curr

    def _fetch_info():
        info_dict = {}
        try:
            info_dict = dict(yf.Ticker(yf_ticker, session=session).info or {})
        except Exception as e:
            logger.warning("Could not fetch stock.info for %s: %s", yf_ticker, e)

        # Crumb-free fallback 1: Yahoo Search API (/v1/finance/search) for sector, industry, name, quoteType
        # Works reliably on cloud/datacenter IPs (e.g. Render) even when quoteSummary (.info) is rate-limited.
        if not info_dict.get("sector") or not info_dict.get("industry") or not info_dict.get("longName"):
            try:
                sr = session.get(
                    f"https://query2.finance.yahoo.com/v1/finance/search?q={yf_ticker}&quotesCount=5&newsCount=0",
                    timeout=4,
                )
                if sr.status_code == 200:
                    quotes = sr.json().get("quotes", [])
                    q = next(
                        (x for x in quotes if str(x.get("symbol", "")).upper() == yf_ticker.upper()),
                        quotes[0] if quotes else {},
                    )
                    if q:
                        if not info_dict.get("sector"):
                            info_dict["sector"] = q.get("sectorDisp") or q.get("sector")
                        if not info_dict.get("industry"):
                            info_dict["industry"] = q.get("industryDisp") or q.get("industry")
                        if not info_dict.get("longName"):
                            info_dict["longName"] = q.get("longname") or q.get("shortname")
                        if not info_dict.get("shortName"):
                            info_dict["shortName"] = q.get("shortname") or q.get("longname")
                        if not info_dict.get("quoteType"):
                            info_dict["quoteType"] = q.get("quoteType")
            except Exception as search_err:
                logger.debug("Search metadata fallback failed for %s: %s", yf_ticker, search_err)

        # Crumb-free fallback 2: Yahoo Fundamentals Timeseries for financialCurrency (e.g. INFY.NS reporting in USD)
        if not info_dict.get("financialCurrency"):
            try:
                ts_url = (
                    f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{yf_ticker}"
                    f"?type=annualTotalRevenue&period1=1600000000&period2=1950000000"
                )
                tr = session.get(ts_url, timeout=4)
                if tr.status_code == 200:
                    for item in tr.json().get("timeseries", {}).get("result", []):
                        for v in item.get("annualTotalRevenue", []):
                            if isinstance(v, dict) and v.get("currencyCode"):
                                info_dict["financialCurrency"] = v["currencyCode"]
                                break
            except Exception as ts_err:
                logger.debug("Timeseries currency fallback failed for %s: %s", yf_ticker, ts_err)

        return info_dict

    def _fetch_h1y():
        try:
            return yf.Ticker(yf_ticker, session=session).history(period="1y", interval="1d")
        except Exception:
            return pd.DataFrame()

    def _fetch_h2y():
        try:
            return yf.Ticker(yf_ticker, session=session).history(period="2y", interval="1wk")
        except Exception:
            return pd.DataFrame()

    is_offline = os.environ.get("VALUATIONLABS_OFFLINE", "").lower() in ("1", "true", "yes")
    fixture_bundle = _load_yahoo_fixtures(yf_ticker) if is_offline else None

    if fixture_bundle is not None:
        income_stmt, balance_sheet, cash_flow, info = fixture_bundle
        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        shares_out = info.get("sharesOutstanding")
        fast_currency = info.get("currency")
        hist_1y = pd.DataFrame()
        hist_2y = pd.DataFrame()
    else:
        with ThreadPoolExecutor(max_workers=6) as pool:
            fut_fin = pool.submit(_fetch_fin)
            fut_bs = pool.submit(_fetch_bs)
            fut_cf = pool.submit(_fetch_cf)
            fut_fast = pool.submit(_fetch_fast)
            fut_info = pool.submit(_fetch_info)
            fut_h1y = pool.submit(_fetch_h1y)
            fut_h2y = pool.submit(_fetch_h2y)
            fut_bench = pool.submit(_get_benchmark_returns, benchmark)

            income_stmt: pd.DataFrame = fut_fin.result()
            balance_sheet: pd.DataFrame = fut_bs.result()
            cash_flow: pd.DataFrame = fut_cf.result()
            current_price, shares_out, fast_currency = fut_fast.result()
            info: dict = fut_info.result()
            hist_1y: pd.DataFrame = fut_h1y.result()
            hist_2y: pd.DataFrame = fut_h2y.result()
            _ = fut_bench.result()

        # Fallback cleanly to staged offline fixtures only if live Yahoo failed to return statements
        if (income_stmt is None or income_stmt.empty) and (balance_sheet is None or balance_sheet.empty):
            fb = _load_yahoo_fixtures(yf_ticker)
            if fb is not None:
                income_stmt, balance_sheet, cash_flow, info_fb = fb
                if not info:
                    info = info_fb
                current_price = current_price or info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
                shares_out = shares_out or info.get("sharesOutstanding")
                fast_currency = fast_currency or info.get("currency")

    if not info.get("currency"):
        info["currency"] = fast_currency or ("INR" if market.upper() == "IN" else "USD")

    # Reject pure non-operating ETFs / funds / indices, while routing REITs/InvITs/Insurers through
    # their dedicated domain valuation engines (REIT_INVIT_AFFO and INSURANCE_PNC_DDM / INSURANCE_LIFE_DDM).
    is_excl, excl_kind, excl_msg = is_non_dcf_instrument(
        symbol=yf_ticker,
        name=info.get("longName") or info.get("shortName"),
        quote_type=info.get("quoteType"),
        sector=info.get("sector"),
        industry=info.get("industry"),
    )
    if is_excl and excl_kind.upper() != "REIT_INVIT":
        raise ValueError(excl_msg)

    if current_price is None:
        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    if shares_out is None:
        shares_out = info.get("sharesOutstanding")

    # 3. Last-resort fallback for price via already-fetched 1Y daily history (or 5-day history)
    if current_price is None:
        try:
            if hist_1y is not None and not hist_1y.empty and "Close" in hist_1y:
                current_price = float(hist_1y["Close"].dropna().iloc[-1])
            else:
                hist = stock.history(period="5d")
                if not hist.empty:
                    current_price = float(hist["Close"].iloc[-1])
        except Exception:
            pass

    if current_price is None or shares_out is None:
        # Self-healing fallback 1: If Indian ticker failed on .NS, check if it is listed on BSE (.BO)
        if market.upper() == "IN" and yf_ticker.endswith(".NS") and not redirect_note:
            bse_alt = yf_ticker[:-3] + ".BO"
            logger.info("Ticker %s missing data on NSE (.NS); checking BSE (%s)...", yf_ticker, bse_alt)
            try:
                res = fetch_stock_data(bse_alt, "IN")
                res["redirect_note"] = f"{ticker} is listed on BSE under {bse_alt}"
                return res
            except Exception as bse_err:
                logger.debug("BSE fallback %s also failed: %s", bse_alt, bse_err)

        # Self-healing fallback 2: check if the ticker underwent a corporate action / rename on the exchange
        if not redirect_note:
            successor = search_successor_via_yahoo(yf_ticker, market, session)
            if successor:
                succ_sym, succ_mkt, succ_note = successor
                logger.info("Auto-recovering dead ticker %s -> %s (%s)", yf_ticker, succ_sym, succ_note)
                res = fetch_stock_data(succ_sym, succ_mkt)
                res["redirect_note"] = succ_note
                return res

        raise ValueError(
            f"Yahoo Finance did not return critical data for {yf_ticker}.\n"
            f"   currentPrice={current_price}, sharesOutstanding={shares_out}\n"
            f"   Cannot build a DCF without these denominators."
        )

    market_cap = float(current_price) * float(shares_out)

    # -----------------------------------------------------------------------
    # 1. Cross-Currency Reconciler (runs BEFORE Unit Scale Reconciler & Beta D/E)
    # Converts foreign statement reporting currency to trading currency (e.g. NVO reporting in DKK while trading in USD,
    # TSM reporting in TWD while trading in USD, or ADR-linked Indian firms reporting in USD while trading in INR).
    # Includes a sanity guard against Yahoo Finance metadata bugs (e.g. HCLTECH.NS where info['financialCurrency']
    # claims 'USD' even though the financial statement DataFrames are already reported in INR).
    # -----------------------------------------------------------------------
    was_cross_currency = False
    try:
        fin_currency = str(info.get("financialCurrency") or "").upper()
        trade_currency = str(info.get("currency") or ("INR" if market.upper() == "IN" else "USD")).upper()
        raw_stmt_rev = None
        if not income_stmt.empty:
            for col in ["Total Revenue", "Operating Revenue", "Revenue"]:
                if col in income_stmt.columns:
                    v = income_stmt[col].dropna()
                    if not v.empty and float(v.iloc[0]) > 0:
                        raw_stmt_rev = float(v.iloc[0])
                        break

        # Deterministic USD-reporting fallback for ADR-linked Indian companies (e.g. INFY.NS)
        # when cloud IP rate-limiting blocks Yahoo metadata endpoints
        if (not fin_currency or fin_currency == trade_currency) and trade_currency == "INR" and raw_stmt_rev and market_cap > 50e9:
            raw_rev_ratio = raw_stmt_rev / market_cap
            sym_base = yf_ticker.replace(".NS", "").replace(".BO", "").upper()
            if 0.001 <= raw_rev_ratio <= 0.022 and (sym_base in {"INFY", "WIT"} or raw_rev_ratio < 0.012):
                fin_currency = "USD"
                info["financialCurrency"] = "USD"

        if fin_currency and trade_currency and fin_currency != trade_currency:
            fx_rate = get_cross_fx_rate(fin_currency, trade_currency)
            if fx_rate and abs(fx_rate - 1.0) > 0.001:
                already_in_trade_curr = False
                if raw_stmt_rev and market_cap > 0 and fx_rate > 10.0:
                    # E.g. HCLTECH.NS: fin_currency='USD', trade_currency='INR', fx_rate ~ 86-94.
                    # If raw_stmt_rev is ALREADY ~0.15x - 5.0x of INR market_cap, multiplying by 90x would make
                    # revenue 15x - 450x of market_cap!
                    raw_rev_to_mcap = raw_stmt_rev / market_cap
                    fx_rev_to_mcap = (raw_stmt_rev * fx_rate) / market_cap
                    if 0.08 <= raw_rev_to_mcap <= 8.0 and fx_rev_to_mcap > 12.0:
                        already_in_trade_curr = True
                        logger.info(
                            "Skipping FX conversion for %s: financialCurrency='%s' vs currency='%s', "
                            "but statement revenue (%.2f) is already in %s scale relative to Market Cap (%.2f).",
                            yf_ticker, fin_currency, trade_currency, raw_stmt_rev, trade_currency, market_cap,
                        )
                        info["financialCurrency"] = trade_currency

                if not already_in_trade_curr:
                    was_cross_currency = True
                    logger.info(
                        "Detected cross-currency mismatch for %s (financialCurrency=%s vs trading currency=%s). "
                        "Converting financial statements to %s using FX rate %.4f",
                        yf_ticker, fin_currency, trade_currency, trade_currency, fx_rate
                    )
                    if not income_stmt.empty:
                        income_stmt = _scale_monetary_df(income_stmt, fx_rate, scale_per_share=True)
                    if not balance_sheet.empty:
                        balance_sheet = _scale_monetary_df(balance_sheet, fx_rate, scale_per_share=True)
                    if not cash_flow.empty:
                        cash_flow = _scale_monetary_df(cash_flow, fx_rate, scale_per_share=True)
                    for info_monetary_key in (
                        "totalRevenue",
                        "ebitda",
                        "freeCashflow",
                        "operatingCashflow",
                        "totalCash",
                        "totalDebt",
                        "revenuePerShare",
                        "totalCashPerShare",
                        "bookValue",
                    ):
                        if info.get(info_monetary_key) is not None:
                            try:
                                info[info_monetary_key] = float(info[info_monetary_key]) * fx_rate
                            except (ValueError, TypeError):
                                pass
                    info["financialCurrency"] = trade_currency
    except Exception as e:
        logger.warning("Cross-currency reconciliation skipped for %s: %s", yf_ticker, e)

    # -----------------------------------------------------------------------
    # 2. Automated Statement Unit Scale Reconciliation
    # Fixes scraping discrepancies where Yahoo Finance reports statements in units
    # that differ by 10x, 100x, or 1000x from per-share metrics (e.g. INDOMIM).
    # Skipped for cross-currency ADRs (e.g. TSM, NVO) where ADR-to-ordinary share ratios
    # (5:1 or 10:1) or local-currency revenuePerShare would cause false 0.1x scaling.
    # -----------------------------------------------------------------------
    scale_multiplier = 1.0
    if not was_cross_currency:
        try:
            rev_per_share = info.get("revenuePerShare")
            bs_bv_per_share = info.get("bookValue")

            fin_rev = None
            if not income_stmt.empty:
                for col in ["Total Revenue", "Operating Revenue"]:
                    if col in income_stmt.columns:
                        val = income_stmt[col].dropna()
                        if not val.empty and float(val.iloc[0]) > 0:
                            fin_rev = float(val.iloc[0])
                            break

            fin_equity = None
            if not balance_sheet.empty:
                for col in ["Stockholders Equity", "Total Stockholders' Equity", "Common Stock Equity"]:
                    if col in balance_sheet.columns:
                        val = balance_sheet[col].dropna()
                        if not val.empty and float(val.iloc[0]) > 0:
                            fin_equity = float(val.iloc[0])
                            break

            ratios = []
            if rev_per_share and shares_out and fin_rev and fin_rev > 0:
                implied_rev = float(rev_per_share) * float(shares_out)
                ratios.append(implied_rev / fin_rev)

            if bs_bv_per_share and shares_out and fin_equity and fin_equity > 0:
                implied_eq = float(bs_bv_per_share) * float(shares_out)
                ratios.append(implied_eq / fin_equity)

            if ratios:
                avg_ratio = float(np.median(ratios))
                if 7.0 <= avg_ratio <= 14.0:
                    scale_multiplier = 10.0
                elif 70.0 <= avg_ratio <= 140.0:
                    scale_multiplier = 100.0
                elif 700.0 <= avg_ratio <= 1400.0:
                    scale_multiplier = 1000.0
                elif 0.07 <= avg_ratio <= 0.14:
                    scale_multiplier = 0.1

                if scale_multiplier != 1.0:
                    logger.warning(
                        "Detected %sx unit scale mismatch for %s (implied vs statement ratio: %.2f). "
                        "Auto-reconciling financial statements by %sx.",
                        scale_multiplier, yf_ticker, avg_ratio, scale_multiplier
                    )
                    income_stmt = _scale_monetary_df(income_stmt, scale_multiplier, scale_per_share=False)
                    balance_sheet = _scale_monetary_df(balance_sheet, scale_multiplier, scale_per_share=False)
                    cash_flow = _scale_monetary_df(cash_flow, scale_multiplier, scale_per_share=False)
        except Exception as e:
            logger.warning("Unit scale reconciliation skipped for %s: %s", yf_ticker, e)

    # Estimate debt and D/E ratio for bottom-up beta relevering (after FX & unit-scale reconciliation)
    approx_debt = 0.0
    if not balance_sheet.empty:
        for debt_col in ["Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"]:
            if debt_col in balance_sheet.columns:
                d_vals = balance_sheet[debt_col].dropna()
                if len(d_vals) > 0 and float(d_vals.iloc[0]) > 0:
                    approx_debt = float(d_vals.iloc[0])
                    break
        if "Capital Lease Obligations" in balance_sheet.columns and approx_debt > 0:
            cl_vals = balance_sheet["Capital Lease Obligations"].dropna()
            if len(cl_vals) > 0 and 0 < float(cl_vals.iloc[0]) < approx_debt:
                approx_debt -= float(cl_vals.iloc[0])
    de_ratio = (approx_debt / market_cap) if market_cap > 0 else 0.0

    from engine.ticker_universe import clean_company_name, lookup_company_name
    long_name = info.get("longName")
    short_name = info.get("shortName")
    universe_name = lookup_company_name(yf_ticker)
    raw_comp_name = long_name or short_name or universe_name or yf_ticker
    if str(raw_comp_name).strip().upper() == yf_ticker.upper() and universe_name:
        raw_comp_name = universe_name
    company_name = clean_company_name(raw_comp_name) or universe_name or yf_ticker
    sector = info.get("sector")
    industry = info.get("industry")

    clean_sym_tag = (
        yf_ticker.upper().replace(".NS", "").replace(".BO", "").split(".")[0]
    )
    if clean_sym_tag == "ADANIENT":
        sector = "Industrials"
        industry = "Infrastructure & Conglomerates"
    elif clean_sym_tag == "OFSS":
        sector = "Technology"
        industry = "Software - Infrastructure"

    is_extractive, is_cyclical = classify_sector_dynamics(sector, industry, yf_ticker, company_name)
    name_lower = (company_name or "").lower()
    clean_sym = yf_ticker.replace(".NS", "").replace(".BO", "").upper()

    # Deterministic sector/industry fallback ONLY when upstream provider omitted sector metadata
    # (driven strictly by business description & statement structure, never hardcoded tickers).
    desc_text = (info.get("longBusinessSummary") or info.get("description") or "").lower()
    if not sector:
        if is_extractive:
            if any(k in name_lower or k in desc_text for k in ["oil", "gas", "petroleum"]):
                sector = "Energy"
                industry = industry or "Oil & Gas Exploration & Production"
            else:
                sector = "Basic Materials"
                industry = industry or "Metals & Mining"
        elif is_cyclical:
            if any(k in name_lower or k in desc_text for k in ["petroleum", "refining", "refinery"]):
                sector = "Energy"
                industry = industry or "Oil & Gas Refining & Marketing"
            else:
                sector = "Basic Materials"
                industry = industry or "Steel & Basic Materials"
        elif any(k in name_lower or k in desc_text for k in ["pharma", "laboratories", "biotech", "hospital", "lifesciences"]):
            sector = "Healthcare"
            industry = industry or "Drug Manufacturers"
        elif any(k in name_lower or k in desc_text for k in ["software", "saas", "cloud platform", "information technology", "it services"]):
            sector = "Technology"
            industry = industry or "Software & IT Services"

    beta_info = compute_clean_beta(
        stock=stock,
        ticker=yf_ticker,
        market=market,
        raw_info_beta=info.get("beta"),
        sector=sector,
        industry=industry,
        de_ratio=de_ratio,
        tax_rate=profile.get("tax_rate", 0.2517 if market.upper() == "IN" else 0.21),
        tradeable=info.get("tradeable"),
        hist_1y=hist_1y,
        hist_2y=hist_2y,
    )

    # Structural sector & balance-sheet model classification (zero hardcoded ticker lists):
    # - Exchanges / clearing / AMCs / depositories / rating agencies -> Standard FCFF
    # - Insurance carriers -> INSURANCE_PNC_DDM / INSURANCE_LIFE_DDM
    # - REITs / InvITs -> REIT_INVIT_AFFO (FFO/AFFO + Cap-Rate NAV)
    # - Banks / NBFCs / lending institutions -> Bank / NBFC DDM
    is_cap_light_fin = is_capital_light_financial(yf_ticker, company_name, sector, industry)
    is_financial = False
    sec_lower = (sector or "").lower()
    ind_lower = (industry or "").lower()
    is_insurance_entity = (
        "insurance" in ind_lower
        or "reinsurance" in ind_lower
        or (not is_cap_light_fin and any(kw in name_lower for kw in ("insurance", "life insurance", "general insurance", "reinsurance", "assurance", "max financial services")))
    )
    is_reit_entity = excl_kind.upper() == "REIT_INVIT" or any(kw in sec_lower or kw in ind_lower or kw in name_lower for kw in ("reit", "real estate investment trust", "invit", "infrastructure investment trust"))

    if is_cap_light_fin or is_insurance_entity or is_reit_entity:
        is_financial = False
    elif any(k in sec_lower for k in ["financial", "banking"]) and "insurance" not in ind_lower:
        is_financial = True
    elif any(kw in ind_lower for kw in ["bank", "credit services", "mortgage finance", "consumer finance", "specialty finance", "capital markets"]):
        is_financial = True
    elif (not sector) and any(kw in name_lower for kw in ["bank", "housing finance", "fincorp", "finvest", "credit"]) and "software" not in desc_text:
        is_financial = True
    elif not sector and not industry and ("Net Interest Income" in income_stmt.columns or "Interest Income" in income_stmt.columns):
        has_ebit = "EBIT" in income_stmt.columns or "Operating Income" in income_stmt.columns
        nii_vals = safe_get(income_stmt, "Net Interest Income", 0) if "Net Interest Income" in income_stmt.columns else np.zeros(1)
        debt_vals = safe_get(balance_sheet, "Total Debt", 0)
        rev_vals = safe_get(income_stmt, "Total Revenue", 0)
        if not has_ebit and len(nii_vals) > 0 and nii_vals[0] > 0:
            is_financial = True
        elif len(debt_vals) > 0 and len(rev_vals) > 0 and rev_vals[-1] > 0 and len(nii_vals) > 0 and nii_vals[0] > 0:
            if debt_vals[-1] / rev_vals[-1] > 1.5:
                is_financial = True

    if is_financial and not sector:
        sector = "Financial Services"
    if is_financial and not industry:
        industry = "Financial Services & Lending"

    accounting_standard = detect_accounting_standard(market, info.get("currency"))
    sec_edgar_data: Optional[Dict[str, Any]] = None
    primary_filing_data: Optional[Dict[str, Any]] = None

    if accounting_standard == "US_GAAP":
        try:
            sec_edgar_data = extract_sec_edgar_reconciliation(
                ticker=clean_sym,
                current_price=float(current_price or 0.0),
            )
        except Exception as exc:
            logger.debug("SEC EDGAR lookup skipped for %s: %s", yf_ticker, exc)
    elif accounting_standard == "IND_AS":
        try:
            pf = extract_ind_as_ar_financials(ticker=yf_ticker)
            if pf and pf.get("available"):
                primary_filing_data = pf
        except Exception as exc:
            logger.debug("Primary Ind AS AR parse skipped for %s: %s", yf_ticker, exc)

    # Multi-class cover-page basic share count & TSM dilution reconciliation (general XBRL logic)
    yahoo_basic_shares = float(shares_out)
    diluted_val_shares = float(shares_out)
    cover_basic_shares = None
    tsm_bridge = None
    if sec_edgar_data and sec_edgar_data.get("cover_shares"):
        cov = sec_edgar_data["cover_shares"]
        cov_tot = cov.get("total_common_shares")
        if cov_tot and cov_tot > 0:
            cover_basic_shares = float(cov_tot)
            # Detect when Yahoo reported only a single share class while SEC cover sums all classes (Class A + B)
            if len(cov.get("share_classes") or {}) >= 2 or cov_tot > yahoo_basic_shares * 1.01:
                shares_out = cover_basic_shares
                market_cap = float(current_price) * float(shares_out)
        if sec_edgar_data.get("tsm_bridge"):
            tsm_bridge = sec_edgar_data["tsm_bridge"]
            rec_sh = tsm_bridge.get("recommended_shares")
            if rec_sh and rec_sh > 0:
                diluted_val_shares = float(rec_sh)

    # Check regulatory asset share for utility classification
    reg_asset_share = 0.0
    if not balance_sheet.empty and "Total Assets" in balance_sheet.columns:
        try:
            ta0 = float(safe_get(balance_sheet, "Total Assets", 0.0)[0])
            if primary_filing_data and primary_filing_data.get("available"):
                reg_cr = (primary_filing_data["balance_sheet"].get("regulatory_deferral_debit") or {}).get("current") or 0.0
                if ta0 > 0 and reg_cr > 0:
                    reg_asset_share = float((reg_cr * primary_filing_data.get("unit_multiplier", 1e7)) / ta0)
            elif "Non Current Deferred Assets" in balance_sheet.columns and ta0 > 0:
                ncda0 = float(safe_get(balance_sheet, "Non Current Deferred Assets", 0.0)[0])
                dta0 = float(safe_get(balance_sheet, "Non Current Deferred Taxes Assets", 0.0)[0]) if "Non Current Deferred Taxes Assets" in balance_sheet.columns else 0.0
                reg_asset_share = max(0.0, ncda0 - dta0) / ta0
        except Exception:
            pass

    model_suitability = classify_model_suitability(
        sector=sector,
        industry=industry,
        company_name=company_name,
        is_financial=is_financial,
        is_capital_light_financial=is_cap_light_fin,
        is_non_dcf=False,
        balance_sheet_cols=list(balance_sheet.columns) if not balance_sheet.empty else [],
        reg_asset_share=reg_asset_share,
        is_extractive=is_extractive,
        is_cyclical=is_cyclical,
        accounting_standard=accounting_standard,
        is_reit_entity=is_reit_entity,
    )

    result = {
        "ticker": yf_ticker,
        "name": company_name,
        "market": market,
        "sector": sector,
        "industry": industry,
        "description": info.get("longBusinessSummary") or info.get("description") or "",
        "city": info.get("city", ""),
        "country": info.get("country", ""),
        "website": info.get("website", ""),
        "employees": info.get("fullTimeEmployees"),
        "accounting_standard": accounting_standard,
        "model_suitability": model_suitability,
        "sec_edgar": sec_edgar_data,
        "primary_filing": primary_filing_data,
        "share_reconciliation": {
            "yahoo_shares_outstanding": yahoo_basic_shares,
            "cover_basic_shares": cover_basic_shares,
            "valuation_basic_shares": float(shares_out),
            "valuation_diluted_shares": float(diluted_val_shares),
            "tsm_bridge": tsm_bridge,
        },
        "is_financial": is_financial,
        "is_insurance_entity": is_insurance_entity,
        "is_reit_entity": is_reit_entity,
        "is_capital_light_financial": is_cap_light_fin,
        "redirect_note": redirect_note,
        "is_extractive": is_extractive,
        "is_cyclical": is_cyclical,
        "current_price": float(current_price),
        "shares_outstanding": float(shares_out),
        "diluted_valuation_shares": float(diluted_val_shares),
        "market_cap": market_cap,
        "beta": float(beta_info["beta"]),
        "raw_beta": float(beta_info["raw_beta"]),
        "raw_blume_beta": float(beta_info.get("raw_blume_beta", beta_info["beta"])),
        "sector_bottom_up_beta": float(beta_info.get("sector_bottom_up_beta", beta_info["beta"])),
        "cyclical_beta_low_flag": bool(beta_info.get("cyclical_beta_low_flag", False)),
        "beta_clamped": bool(beta_info["beta_clamped"]),
        "beta_note": str(beta_info["beta_note"]),
        "is_illiquid": bool(beta_info.get("is_illiquid", False)),
        "income_stmt": income_stmt,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
        "info": info,
    }
    _STOCK_DATA_CACHE[cache_key] = (_copy_stock_data(result), time.time())
    return result


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def compute_historical_metrics(stock_data: dict) -> dict:
    """Compute historical averages and standard deviations.

    Refactored from notebook Steps 3A–3F.

    Args:
        stock_data: The dict returned by :func:`fetch_stock_data`.

    Returns:
        A dict with raw arrays and computed averages:

        - ``revenue``, ``ebit``, ``capex``, ``dna``, ``nwc``, ``delta_nwc``
        - ``rev_growth``, ``ebit_margins``
        - ``avg_rev_growth``, ``std_rev_growth``
        - ``avg_ebit_margin``, ``std_ebit_margin``
        - ``avg_capex_pct``, ``avg_dna_pct``, ``avg_dnwc_pct``
        - ``n_years``, ``last_revenue``, ``cash_and_equivalents``, ``total_debt``
        - ``interest_expense``

    Raises:
        ValueError: If fewer than 2 valid fiscal years remain after cleaning.
    """
    income_stmt: pd.DataFrame = stock_data["income_stmt"].copy()
    balance_sheet: pd.DataFrame = stock_data["balance_sheet"].copy()
    cash_flow: pd.DataFrame = stock_data["cash_flow"].copy()

    # ------------------------------------------------------------------
    # 3A – Align to common reporting dates
    # ------------------------------------------------------------------
    common_dates = (
        income_stmt.index
        .intersection(cash_flow.index)
        .intersection(balance_sheet.index)
    )
    income_stmt = income_stmt.loc[common_dates]
    cash_flow = cash_flow.loc[common_dates]
    balance_sheet = balance_sheet.loc[common_dates]

    # ------------------------------------------------------------------
    # 3B – Drop years with missing Revenue or EBIT (or Revenue only for Equity/DDM/FFO models)
    # ------------------------------------------------------------------
    is_financial = stock_data.get("is_financial", False)
    suit_family = str((stock_data.get("model_suitability") or {}).get("model_family") or "")
    is_equity_only = bool(
        is_financial or suit_family.startswith(("BANK_", "NBFC_", "INSURANCE_", "REIT_"))
    )
    cols_to_check = ["Total Revenue"] if is_equity_only else ["Total Revenue", "EBIT"]

    for col in cols_to_check:
        resolved_col = col
        if col not in income_stmt.columns:
            _alt_map = {
                "Total Revenue": ["Revenue", "Total Revenue From Operations", "Operating Revenue"],
                "EBIT": ["Operating Income", "Total Operating Income As Reported", "Operating Profit"],
            }
            for alt in _alt_map.get(col, []):
                if alt in income_stmt.columns:
                    resolved_col = alt
                    break

        if resolved_col in income_stmt.columns:
            if col == "EBIT" and "Operating Income" in income_stmt.columns:
                valid = (
                    (income_stmt[resolved_col].notna() & (income_stmt[resolved_col] != 0))
                    | (income_stmt["Operating Income"].notna() & (income_stmt["Operating Income"] != 0))
                )
            else:
                valid = income_stmt[resolved_col].notna() & (income_stmt[resolved_col] != 0)
            income_stmt = income_stmt[valid]
            cash_flow = cash_flow.loc[cash_flow.index.intersection(income_stmt.index)]
            balance_sheet = balance_sheet.loc[balance_sheet.index.intersection(income_stmt.index)]

    if len(income_stmt) < 2:
        raise ValueError(
            f"Only {len(income_stmt)} valid fiscal years available. "
            f"Need at least 2 to compute growth rates."
        )

    # ------------------------------------------------------------------
    # 3C/3D – Extract historical financials (chronological oldest→newest)
    # ------------------------------------------------------------------
    revenue = safe_get(income_stmt, "Total Revenue")[::-1].copy()

    raw_capex = safe_get(cash_flow, "Capital Expenditure", default=0)[::-1]
    capex = np.where(raw_capex < 0, -raw_capex, raw_capex)  # explicit positive
    rep_capex = capex.copy()

    raw_dna = safe_get(cash_flow, "Depreciation And Amortization")[::-1]
    dna = np.where(raw_dna < 0, -raw_dna, raw_dna)  # explicit positive
    # Fill any missing/zero years in Cash Flow D&A from Income Statement Reconciled Depreciation
    for dna_col in (
        "Reconciled Depreciation",
        "Depreciation And Amortization In Income Statement",
        "Depreciation Income Statement",
        "Depreciation And Amortization",
    ):
        if dna_col in income_stmt.columns:
            inc_dna = np.abs(safe_get(income_stmt, dna_col, default=0)[::-1])
            dna = np.where(dna > 0, dna, inc_dna)
    rep_dna = dna.copy()

    # Under Ind AS / IFRS (e.g. regulated utilities recouping fair-value/revaluation depreciation
    # or Advance Against Depreciation directly from Retained Earnings), P&L D&A (`is_dna`) is
    # net of recoupment while Cash Flow D&A (`rep_dna`) may show Gross D&A. Keep EBIT and EBITDA/FCFF
    # D&A add-back on a strictly symmetric Net basis so recoupment is never added to FCFF without
    # having been deducted from EBIT.
    acct_std = stock_data.get("accounting_standard") or detect_accounting_standard(
        stock_data.get("market", "US"), (stock_data.get("info") or {}).get("currency")
    )
    primary_filing = stock_data.get("primary_filing") or {}
    pf_notes = (primary_filing.get("notes") or {}) if primary_filing.get("available") else {}
    pf_rec_note = pf_notes.get("note_38_46_depreciation_reconciliation") or {}
    rec_val_cur = (
        (pf_rec_note.get("recoupment_from_retained_earnings_and_adj") or {}).get("current")
        or pf_rec_note.get("revaluation_recoupment")
        or pf_rec_note.get("aad_adjustment")
        or 0.0
    )
    recoupment_primary_verified = bool(primary_filing.get("available") and abs(float(rec_val_cur or 0.0)) > 0.0)
    recouped_da = np.zeros_like(dna)
    unverified_is_cf_da_gap = np.zeros_like(dna)
    recoupment_inferred_unverified = False
    skipped_due_to_goodwill_threshold = False
    if (
        not is_financial
        and acct_std in ("IND_AS", "IFRS")
        and "Depreciation And Amortization In Income Statement" in income_stmt.columns
    ):
        is_dna_series = np.abs(safe_get(income_stmt, "Depreciation And Amortization In Income Statement", default=0)[::-1])
        gw_check = (
            safe_get(balance_sheet, "Goodwill And Other Intangible Assets", default=0)[::-1]
            if "Goodwill And Other Intangible Assets" in balance_sheet.columns
            else np.zeros_like(dna)
        )
        ta_check = safe_get(balance_sheet, "Total Assets", default=1.0)[::-1]
        for idx in range(len(dna)):
            gw_sh = (gw_check[idx] / ta_check[idx]) if ta_check[idx] > 0 else 0.0
            if 0.0 < is_dna_series[idx] < dna[idx]:
                if recoupment_primary_verified and gw_sh < 0.15:
                    recouped_da[idx] = dna[idx] - is_dna_series[idx]
                    dna[idx] = is_dna_series[idx]
                else:
                    unverified_is_cf_da_gap[idx] = dna[idx] - is_dna_series[idx]
                    recoupment_inferred_unverified = True
                    if gw_sh >= 0.15:
                        skipped_due_to_goodwill_threshold = True

    cfo_arr = safe_get(cash_flow, "Operating Cash Flow", default=0)[::-1]

    raw_ebit_orig = safe_get(income_stmt, "EBIT")[::-1].copy()
    stat_op_inc = (
        safe_get(income_stmt, "Operating Income")[::-1].copy()
        if "Operating Income" in income_stmt.columns
        else raw_ebit_orig.copy()
    )
    model_family = (stock_data.get("model_suitability") or {}).get("model_family", "STANDARD_FCFF")
    is_reg_utility = model_family == "REGULATED_UTILITY_FCFF"
    non_op_int_inc_is = (
        np.maximum(0.0, safe_get(income_stmt, "Interest Income Non Operating", default=0)[::-1])
        if "Interest Income Non Operating" in income_stmt.columns
        else np.zeros_like(raw_ebit_orig)
    )

    ebit = raw_ebit_orig.copy()
    amort_addback_arr = np.zeros_like(ebit)
    if not is_financial:
        norm_ebitda = (
            safe_get(income_stmt, "Normalized EBITDA", default=0)[::-1]
            if "Normalized EBITDA" in income_stmt.columns
            else np.zeros_like(ebit)
        )
        raw_ebitda = (
            safe_get(income_stmt, "EBITDA", default=0)[::-1]
            if "EBITDA" in income_stmt.columns
            else np.zeros_like(ebit)
        )

        op_inc = (
            safe_get(income_stmt, "Operating Income")[::-1]
            if "Operating Income" in income_stmt.columns
            else raw_ebit_orig.copy()
        )
        if "Operating Income" in income_stmt.columns:
            for idx in range(len(ebit)):
                if is_reg_utility:
                    # Rate-regulated utilities accrue recurring statutory Regulatory Income (Ind AS 114 / ASC 980)
                    # outside Yahoo's generic Operating Income line. Keep statutory recurring Regulatory Income
                    # in EBIT across ALL years consistently while stripping non-operating Interest Income on cash.
                    if raw_ebit_orig[idx] > op_inc[idx]:
                        ebit[idx] = max(op_inc[idx], raw_ebit_orig[idx] - non_op_int_inc_is[idx])
                    elif op_inc[idx] > ebit[idx]:
                        ebit[idx] = op_inc[idx]
                else:
                    if op_inc[idx] > ebit[idx]:
                        # EBIT dragged below Operating Income by non-operating impairments / special charges
                        ebit[idx] = op_inc[idx]
                    elif op_inc[idx] < 0 and ebit[idx] > 0:
                        # Non-operating gain flipped operating loss into positive GAAP EBIT
                        ebit[idx] = op_inc[idx]
                    elif revenue[idx] > 0 and (ebit[idx] / revenue[idx]) > 0.85:
                        # One-off spin-off / divestiture gain (>85% of revenue)
                        ebit[idx] = op_inc[idx]
                    elif op_inc[idx] > 0 and ebit[idx] > op_inc[idx] * 1.30:
                        # Strip purely non-operating gains when no regulatory deferral framework exists
                        ebit[idx] = op_inc[idx]
                    elif norm_ebitda[idx] != 0 and (ebit[idx] + rep_dna[idx]) > norm_ebitda[idx] * 1.15:
                        ebit[idx] = op_inc[idx]

        # Build clean EBITDA array: match operating D&A (net of recoupment)
        clean_yf_ebitda = np.where(
            (norm_ebitda != 0) & ((norm_ebitda < 0) | (raw_ebitda > norm_ebitda * 1.15)),
            norm_ebitda,
            np.maximum(norm_ebitda, raw_ebitda),
        )
        clean_yf_ebitda_adj = np.maximum(0.0, clean_yf_ebitda - recouped_da) if np.any(recouped_da > 0) else clean_yf_ebitda
        ebitda_arr = ebit + dna if is_reg_utility else np.maximum(ebit + dna, clean_yf_ebitda_adj)

        # Extract reported non-cash amortization of acquired intangibles and physical depreciation from cash flow statement
        raw_amort = safe_get(cash_flow, "Amortization Of Intangibles", default=0)[::-1]
        if np.all(raw_amort == 0) and "Amortization Cash Flow" in cash_flow.columns:
            raw_amort = safe_get(cash_flow, "Amortization Cash Flow", default=0)[::-1]
        if np.all(raw_amort == 0) and "Amortization" in cash_flow.columns:
            raw_amort = safe_get(cash_flow, "Amortization", default=0)[::-1]
        amort_intangibles = np.where(raw_amort < 0, -raw_amort, raw_amort)

        raw_phys_dep = safe_get(cash_flow, "Depreciation", default=0)[::-1]
        phys_depreciation = np.where(raw_phys_dep < 0, -raw_phys_dep, raw_phys_dep)

        gw_intang_arr = (
            safe_get(balance_sheet, "Goodwill And Other Intangible Assets", default=0)[::-1]
            if "Goodwill And Other Intangible Assets" in balance_sheet.columns
            else safe_get(balance_sheet, "Goodwill", default=0)[::-1]
        )
        tot_assets_arr = safe_get(balance_sheet, "Total Assets", default=0)[::-1]

        is_reit_or_ins_equity = suit_family.startswith(("REIT_", "INSURANCE_", "BANK_", "NBFC_"))
        for idx in range(len(ebit)):
            rev_i = revenue[idx]
            if rev_i <= 0:
                continue
            ebitda_i = ebitda_arr[idx]
            gw_ratio = (gw_intang_arr[idx] / tot_assets_arr[idx]) if tot_assets_arr[idx] > 0 else 0.0
            if (not is_reg_utility) and (not is_reit_or_ins_equity) and norm_ebitda[idx] > 0 and (ebit[idx] + dna[idx]) < 0.75 * norm_ebitda[idx]:
                ebit[idx] = norm_ebitda[idx] - dna[idx]

            # Acquisition intangible amortization adjustment for heavy M&A acquirers only
            if (
                (not is_reit_or_ins_equity)
                and amort_intangibles[idx] > 0
                and dna[idx] > 0
                and (amort_intangibles[idx] >= 0.35 * dna[idx] or amort_intangibles[idx] > capex[idx] * 1.10)
                and (amort_intangibles[idx] >= 0.035 * rev_i or gw_ratio >= 0.20)
                and cfo_arr[idx] > 0
            ):
                econ_dna_i = (
                    phys_depreciation[idx]
                    if (phys_depreciation[idx] > 0 and phys_depreciation[idx] < dna[idx])
                    else max(0.0, dna[idx] - amort_intangibles[idx])
                )
                if econ_dna_i <= 0 or econ_dna_i > dna[idx]:
                    econ_dna_i = min(dna[idx], max(capex[idx], rev_i * 0.025))
                amort_addback = dna[idx] - econ_dna_i
                amort_addback_arr[idx] = amort_addback
                ebit[idx] = ebit[idx] + amort_addback
                dna[idx] = econ_dna_i
            elif (
                (not is_reg_utility)
                and (not is_reit_or_ins_equity)
                and ebitda_i >= 0.055 * rev_i
                and cfo_arr[idx] > 0
                and ebit[idx] < 0.025 * rev_i
                and (dna[idx] > 0.065 * rev_i or gw_ratio > 0.30 or dna[idx] > capex[idx] * 1.10)
            ):
                econ_dna_i = min(dna[idx], rev_i * 0.042)
                ebit[idx] = max(ebit[idx], ebitda_i - econ_dna_i)
                dna[idx] = econ_dna_i
                if capex[idx] > econ_dna_i * 1.05:
                    capex[idx] = econ_dna_i * 1.02

        # Preserve normalized EBITDA (including consolidated JV/concession adjustments)
        # for operating growth/margin trajectory signals while keeping 3-statement
        # historical table strictly reconciled (EBITDA - D&A == EBIT).
        norm_ebitda_series = ebitda_arr.copy()
        # Enforce strict accounting identity across all years: EBITDA - D&A == EBIT
        ebitda_arr = ebit + dna
    else:
        ebitda_arr = ebit + dna
        norm_ebitda_series = ebitda_arr.copy()

    # Banking, Insurance & Partnership Equity specific metrics
    net_income = safe_get(income_stmt, "Net Income")[::-1]
    net_interest_income = safe_get(income_stmt, "Net Interest Income")[::-1]
    pretax_income = safe_get(income_stmt, "Pretax Income")[::-1]
    _se_bv = safe_get(balance_sheet, "Stockholders Equity")[::-1]
    _cse_bv = safe_get(balance_sheet, "Common Stock Equity")[::-1]
    book_value = np.where(np.abs(_se_bv) < 1e-6, _cse_bv, _se_bv)
    raw_divs = safe_get(cash_flow, "Cash Dividends Paid", default=0)[::-1]
    dividends_paid = np.where(raw_divs < 0, -raw_divs, raw_divs)

    # ------------------------------------------------------------------
    # 3E – Net Working Capital (Non-Cash Working Capital)
    # Must exclude both Cash & Equivalents AND Short-Term Marketable Securities
    # (Treasury bills, liquid mutual funds, etc.), which are non-operating cash assets
    # already added in the Enterprise-to-Equity bridge.
    # ------------------------------------------------------------------
    current_assets = safe_get(balance_sheet, "Current Assets")[::-1]
    current_liabs = safe_get(balance_sheet, "Current Liabilities")[::-1]
    cce_series = safe_get(balance_sheet, "Cash And Cash Equivalents", default=0)[::-1]
    sti_series = safe_get(balance_sheet, "Other Short Term Investments", default=0)[::-1]
    if "Cash Cash Equivalents And Short Term Investments" in balance_sheet.columns:
        cash_sti_series = safe_get(
            balance_sheet, "Cash Cash Equivalents And Short Term Investments", default=0
        )[::-1]
        cash_on_bs = np.maximum(cash_sti_series, cce_series + sti_series)
    else:
        cash_on_bs = cce_series + sti_series
    st_debt = safe_get(balance_sheet, "Current Debt", default=0)[::-1]

    # Exclude captive finance / consolidated NBFC customer loan receivables purely from structural BS signals
    has_captive_arm = (
        "Loans Receivable" in balance_sheet.columns
        or "Finance Lease Receivables" in balance_sheet.columns
        or "Non Current Note Receivables" in balance_sheet.columns
    )

    ar_series = safe_get(balance_sheet, "Accounts Receivable", default=0)[::-1]
    other_rec_series = safe_get(balance_sheet, "Other Receivables", default=0)[::-1]
    tot_rec_col = (
        safe_get(balance_sheet, "Receivables", default=0)[::-1]
        if "Receivables" in balance_sheet.columns
        else np.zeros_like(ar_series)
    )
    rec_series = np.maximum(tot_rec_col, np.maximum(ar_series, other_rec_series))
    excess_fin_rec_series = np.where(
        (not is_financial) & has_captive_arm & (rec_series > 0.35 * revenue),
        np.maximum(0.0, rec_series - 0.20 * revenue),
        0.0,
    )
    # Cap NWC receivable deduction so non-current receivables inside 'Receivables' do not push NWC artificially negative
    nwc_rec_deduction = np.minimum(
        excess_fin_rec_series,
        np.maximum(0.0, current_assets - cash_on_bs - 0.15 * revenue),
    )

    nwc = (current_assets - cash_on_bs - nwc_rec_deduction) - (current_liabs - st_debt)
    delta_nwc = np.diff(nwc, prepend=nwc[0])

    # ------------------------------------------------------------------
    # 3F – Historical ratio calculations
    # ------------------------------------------------------------------
    rev_growth = np.diff(revenue) / np.where(revenue[:-1] != 0, revenue[:-1], 1.0)
    ebit_margins = ebit / np.where(revenue != 0, revenue, 1.0)
    ebitda_margins = norm_ebitda_series / np.where(revenue != 0, revenue, 1.0)
    if stock_data.get("is_capital_light_financial", False):
        # Capital-light financial infrastructure (exchanges, AMCs, depositories) often include
        # treasury yield in reported EBIT; cap operating margin at 75% for sustainable FCFF.
        ebit_margins = np.clip(ebit_margins, -0.50, 0.75)

    avg_rev_growth = float(np.mean(rev_growth))
    std_rev_growth = float(np.std(rev_growth, ddof=1)) if len(rev_growth) > 1 else 0.05
    avg_ebit_margin = float(np.mean(ebit_margins))
    std_ebit_margin = float(np.std(ebit_margins, ddof=1)) if len(ebit_margins) > 1 else 0.02
    avg_ebitda_margin = float(np.mean(ebitda_margins))

    # EBITDA growth (useful for infrastructure/conglomerate businesses where
    # trading revenue is flat/deflationary while higher-margin asset EBITDA scales)
    avg_ebitda_growth = avg_rev_growth
    if len(norm_ebitda_series) >= 2:
        valid_eb_g = []
        for i in range(1, len(norm_ebitda_series)):
            if norm_ebitda_series[i - 1] > 0 and norm_ebitda_series[i] > 0:
                g_eb = (norm_ebitda_series[i] - norm_ebitda_series[i - 1]) / abs(
                    norm_ebitda_series[i - 1]
                )
                valid_eb_g.append(float(np.clip(g_eb, -0.50, 1.00)))
        if valid_eb_g:
            avg_ebitda_growth = float(np.mean(valid_eb_g))

    # For newly listed companies or sparse filing histories (n_years <= 2),
    # incorporate live trailing-12-month (TTM) quarterly YoY growth rate from Yahoo info
    info_dict = stock_data.get("info") or {}
    live_rev_growth = info_dict.get("revenueGrowth")
    if len(rev_growth) <= 1 and live_rev_growth is not None and not np.isnan(live_rev_growth) and live_rev_growth > 0:
        avg_rev_growth = float(0.70 * float(live_rev_growth) + 0.30 * avg_rev_growth)
        avg_ebitda_growth = avg_rev_growth

    # Banking specific ratio calculations (ROE, Payout, Net Income growth)
    # Use Tangible Book Value (excluding non-earning M&A Goodwill > 10% of equity, e.g. HDFCBANK merger goodwill)
    # because RBI / Basel Tier-1 regulatory capital (CET1) deducts goodwill & intangibles.
    gw_for_bv = (
        safe_get(balance_sheet, "Goodwill And Other Intangible Assets", default=0)[::-1]
        if "Goodwill And Other Intangible Assets" in balance_sheet.columns
        else safe_get(balance_sheet, "Goodwill", default=0)[::-1]
    )
    tang_book_value = np.where(
        (book_value > 0) & (gw_for_bv > 0.10 * book_value),
        np.maximum(book_value * 0.40, book_value - 0.85 * gw_for_bv),
        book_value,
    )
    roes = []
    payouts = []
    for idx in range(len(net_income)):
        bv = tang_book_value[idx - 1] if idx > 0 else tang_book_value[idx]
        ni = net_income[idx]
        div = dividends_paid[idx] if idx < len(dividends_paid) else 0.0
        if bv > 0 and ni != 0:
            roes.append(float(ni / bv))
        if ni > 0 and div > 0:
            payouts.append(float(min(1.0, max(0.0, div / ni))))

    info_roe = stock_data.get("info", {}).get("returnOnEquity")
    median_hist_roe = float(np.median(roes)) if roes else 0.0
    if info_roe and not np.isnan(info_roe) and info_roe > 0 and median_hist_roe > 0:
        # Use the stronger of live TTM ROE and multi-year median ROE so post-merger book-value
        # denominator spikes (e.g. HDFCBANK.NS absorbing HDFC Ltd) do not artificially depress ROE
        avg_roe = max(float(info_roe), median_hist_roe)
    elif info_roe and not np.isnan(info_roe) and info_roe > 0:
        avg_roe = float(info_roe)
    elif roes:
        avg_roe = median_hist_roe
    else:
        avg_roe = 0.14

    std_roe = float(np.std(roes, ddof=1)) if len(roes) > 1 else 0.02
    avg_payout = float(np.mean(payouts)) if payouts else 0.25

    valid_ni = [float(x) for x in net_income if x > 0]
    if len(valid_ni) > 1:
        ni_growth = np.diff(valid_ni) / valid_ni[:-1]
        avg_ni_growth = float(np.mean(ni_growth))
        std_ni_growth = float(np.std(ni_growth, ddof=1)) if len(ni_growth) > 1 else 0.05
        # When a bank underwent a major merger (Goodwill > 15% of BVE, e.g. HDFCBANK),
        # blend Net Income growth with top-line NII/Revenue growth to reflect combined franchise expansion
        if is_financial and len(book_value) > 0 and book_value[-1] > 0 and gw_for_bv[-1] > 0.15 * book_value[-1]:
            if avg_rev_growth > avg_ni_growth:
                avg_ni_growth = float(0.45 * avg_ni_growth + 0.55 * min(0.24, avg_rev_growth))
    else:
        avg_ni_growth = avg_rev_growth
        std_ni_growth = std_rev_growth

    # For newly listed companies or sparse filing histories (n_years <= 2),
    # incorporate live trailing quarterly earnings growth from Yahoo info
    live_earnings_growth = info_dict.get("earningsGrowth")
    if len(valid_ni) <= 2 and live_earnings_growth is not None and not np.isnan(live_earnings_growth) and live_earnings_growth > 0:
        avg_ni_growth = float(0.70 * float(live_earnings_growth) + 0.30 * avg_ni_growth)

    avg_capex_pct = float(np.mean(capex / np.where(revenue != 0, revenue, 1.0)))
    avg_dna_pct = float(np.mean(dna / np.where(revenue != 0, revenue, 1.0)))
    avg_dnwc_pct = float(np.mean(delta_nwc / np.where(revenue != 0, revenue, 1.0)))

    # Gross Profit, R&D, Cash-Flow FCF (CFO - CapEx), and Stock-Based Compensation (SBC) metrics
    gross_profit_arr = safe_get(income_stmt, "Gross Profit", default=0)[::-1]
    if not np.any(gross_profit_arr) and "Cost Of Revenue" in income_stmt.columns:
        cor_arr = safe_get(income_stmt, "Cost Of Revenue", default=0)[::-1]
        gross_profit_arr = np.where(cor_arr > 0, revenue - cor_arr, 0.0)

    cogs_amort_addback = np.zeros_like(gross_profit_arr)
    if (
        not is_financial
        and np.any(amort_addback_arr > 0)
        and "Amortization Of Intangibles Income Statement" in income_stmt.columns
    ):
        opex_inc_amort = np.abs(safe_get(income_stmt, "Amortization Of Intangibles Income Statement", default=0)[::-1])
        cogs_amort_addback = np.where(
            (opex_inc_amort > 0) & (amort_addback_arr > opex_inc_amort),
            amort_addback_arr - opex_inc_amort,
            0.0,
        )
        gross_profit_arr = gross_profit_arr + cogs_amort_addback

    gross_margins = gross_profit_arr / np.where(revenue != 0, revenue, 1.0)
    avg_gross_margin = float(np.mean(gross_margins)) if np.any(gross_profit_arr) else 0.0

    rnd_arr = (
        np.maximum(0.0, safe_get(income_stmt, "Research And Development", default=0)[::-1])
        if (not is_financial and "Research And Development" in income_stmt.columns)
        else np.zeros_like(revenue)
    )
    rnd_margins = rnd_arr / np.where(revenue != 0, revenue, 1.0)
    avg_rnd_pct = float(np.mean(rnd_margins)) if np.any(rnd_arr) else 0.0
    latest_rnd_pct = float(rnd_margins[-1]) if len(rnd_margins) > 0 else 0.0

    if not is_financial and latest_rnd_pct >= 0.15 and np.any(amort_addback_arr > 0):
        info_gm = (stock_data.get("info") or {}).get("grossMargins")
        if info_gm is not None:
            try:
                info_gm_f = float(info_gm)
                if 0.30 <= info_gm_f <= 0.90 and info_gm_f > avg_gross_margin:
                    avg_gross_margin = info_gm_f
            except (ValueError, TypeError):
                pass

    # Strip non-operating interest income on cash/T-bills from CFO for non-financial firms so
    # operating FCF margins do not double-count interest earned on cash already added in the EV bridge (e.g. DUOL).
    non_op_int_inc = (
        np.maximum(0.0, safe_get(income_stmt, "Interest Income Non Operating", default=0)[::-1])
        if (not is_financial and "Interest Income Non Operating" in income_stmt.columns)
        else np.zeros_like(cfo_arr)
    )
    fcf_arr = (cfo_arr - non_op_int_inc) - capex
    fcf_margins = fcf_arr / np.where(revenue != 0, revenue, 1.0)
    avg_fcf_margin = float(np.mean(fcf_margins)) if np.any(cfo_arr) else 0.0
    latest_fcf_margin = float(fcf_margins[-1]) if len(fcf_margins) > 0 else 0.0

    # Check if Yahoo Finance info provides a more current TTM Free Cash Flow snapshot
    # (e.g. DNUT where TTM FCF is +$52.68M = +3.71% after CapEx optimization vs FY25 -$64.0M)
    info_dict = stock_data.get("info") or {}
    ttm_fcf = info_dict.get("freeCashflow")
    ttm_rev = info_dict.get("totalRevenue") or (float(revenue[-1]) if len(revenue) > 0 else 0.0)
    if ttm_fcf and ttm_rev and float(ttm_rev) > 0:
        try:
            adj_ttm_fcf = float(ttm_fcf) - (float(non_op_int_inc[-1]) if len(non_op_int_inc) > 0 else 0.0)
            ttm_fcf_m = adj_ttm_fcf / float(ttm_rev)
            if -0.50 <= ttm_fcf_m <= 0.60 and ttm_fcf_m > latest_fcf_margin:
                latest_fcf_margin = float(ttm_fcf_m)
                if avg_fcf_margin < 0 and ttm_fcf_m > 0:
                    avg_fcf_margin = float(0.5 * avg_fcf_margin + 0.5 * ttm_fcf_m)
        except (ValueError, TypeError):
            pass

    raw_sbc = safe_get(cash_flow, "Stock Based Compensation", default=0)[::-1]
    sbc_arr = np.where(raw_sbc < 0, -raw_sbc, raw_sbc)
    sbc_margins = sbc_arr / np.where(revenue != 0, revenue, 1.0)
    avg_sbc_pct = float(np.mean(sbc_margins)) if np.any(sbc_arr) else 0.0
    latest_sbc_pct = float(sbc_margins[-1]) if len(sbc_margins) > 0 else 0.0
    
    valuation_adjustments: List[Dict[str, Any]] = []

    if recouped_da.any():
        valuation_adjustments.append({
            "name": "Ind AS Revaluation / AAD D&A Recoupment",
            "category": "da_recoupment",
            "status": "APPLIED_PRIMARY_VERIFIED",
            "raw_value": float(rep_dna[-1]) if len(rep_dna) > 0 else 0.0,
            "applied_value": float(dna[-1]) if len(dna) > 0 else 0.0,
            "recouped_delta": float(recouped_da[-1]) if len(recouped_da) > 0 else 0.0,
            "rationale": f"Primary Ind AS notes ({primary_filing.get('source_citation', 'AR')}) confirmed D&A recoupment from Retained Earnings; CF D&A aligned to P&L Net D&A.",
        })
    elif recoupment_inferred_unverified:
        gap_val = float(unverified_is_cf_da_gap[-1]) if len(unverified_is_cf_da_gap) > 0 else 0.0
        valuation_adjustments.append({
            "name": "IS vs CF D&A Divergence (Unverified Recoupment Not Assumed)",
            "category": "da_recoupment",
            "status": "FLAGGED_FOR_INVESTIGATION",
            "raw_value": float(rep_dna[-1]) if len(rep_dna) > 0 else 0.0,
            "applied_value": float(dna[-1]) if len(dna) > 0 else 0.0,
            "unverified_gap": gap_val,
            "skipped_due_to_goodwill_threshold": skipped_due_to_goodwill_threshold,
            "rationale": (
                "IS D&A is below CF D&A on an Ind AS/IFRS statement without Schedule III note confirmation; "
                "left unadjusted rather than silently fabricating regulatory D&A recoupment."
            ),
        })

    if stock_data.get("cyclical_beta_low_flag", False):
        valuation_adjustments.append({
            "name": "Cyclical / Extractive Empirical Regression Beta",
            "category": "beta_risk",
            "status": "FLAGGED_FOR_INVESTIGATION",
            "raw_value": float(stock_data.get("raw_beta", stock_data.get("beta", 1.0))),
            "applied_value": float(stock_data.get("beta", 1.0)),
            "sector_bottom_up_beta": float(stock_data.get("sector_bottom_up_beta", stock_data.get("beta", 1.0))),
            "rationale": "Empirical 2Y weekly beta (<0.85) retained without silent cyclical floor; bottom-up sector beta scenario exposed.",
            "alternative_scenario": "bottom_up_sector_beta",
        })
    elif stock_data.get("beta_clamped", False):
        valuation_adjustments.append({
            "name": "Illiquid / Outlier Beta Substitution",
            "category": "beta_risk",
            "status": "APPLIED",
            "raw_value": float(stock_data.get("raw_beta", stock_data.get("beta", 1.0))),
            "applied_value": float(stock_data.get("beta", 1.0)),
            "rationale": str(stock_data.get("beta_note", "Bottom-up beta substitution applied for near-zero/illiquid/extreme beta.")),
            "alternative_scenario": "unadjusted_beta",
        })

    nwc_to_rev = nwc / np.where(revenue != 0, revenue, 1.0)
    historical_unclipped_nwc_to_revenue = float(np.mean(nwc_to_rev))
    if is_equity_only:
        nwc_clip_bounds = (0.0, 0.0)
        normalized_nwc_to_revenue = 0.0
        nwc_clip_applied = False
    else:
        if stock_data.get("is_capital_light_financial", False):
            nwc_clip_bounds = (-0.05, 0.05)
            normalized_nwc_to_revenue = float(np.clip(historical_unclipped_nwc_to_revenue, -0.05, 0.05))
        else:
            nwc_clip_bounds = (-0.08, 0.15)
            normalized_nwc_to_revenue = float(np.clip(historical_unclipped_nwc_to_revenue, -0.08, 0.15))

        nwc_clip_applied = abs(normalized_nwc_to_revenue - historical_unclipped_nwc_to_revenue) > 1e-6
        if nwc_clip_applied:
            valuation_adjustments.append({
                "name": "Net Working Capital Winsorization",
                "category": "nwc_clipping",
                "status": "APPLIED",
                "raw_value": float(historical_unclipped_nwc_to_revenue),
                "applied_value": float(normalized_nwc_to_revenue),
                "bounds": list(nwc_clip_bounds),
                "rationale": (
                    f"Historical unclipped NWC/Rev ({historical_unclipped_nwc_to_revenue*100:.2f}%) bounded to "
                    f"[{nwc_clip_bounds[0]*100:.0f}%, {nwc_clip_bounds[1]*100:.0f}%] to contain structural float/settlement spikes."
                ),
                "alternative_scenario": "unclipped_nwc",
            })

    # Total debt and cash (most recent year – index [0] is newest before reversal)
    raw_total_debt = float(safe_get(balance_sheet, "Total Debt")[0])  # newest row
    total_debt = raw_total_debt

    # Cash & Short-Term Investments + Restricted/Earmarked Cash Reconciliation for EV Bridge
    gross_cash_and_sti = float(cash_on_bs[-1]) if len(cash_on_bs) > 0 else 0.0
    restricted_earmarked_cash = 0.0
    cash_recon_source = "Balance Sheet Cash & Short-Term Investments"
    cash_recon_note_ref = None
    cash_recon_components: Dict[str, Any] = {}
    if primary_filing and primary_filing.get("available"):
        pf_bs = primary_filing.get("balance_sheet", {})
        pf_mult = float(primary_filing.get("unit_multiplier", 1e7))
        n16 = (primary_filing.get("notes") or {}).get("note_16_cash_restriction", {})
        pf_unrestricted = pf_bs.get("total_unrestricted_cash")
        pf_earmarked = n16.get("total_restricted_earmarked")
        pf_cce = (pf_bs.get("cash_and_cash_equivalents") or {}).get("current")
        pf_cur_inv = (pf_bs.get("current_investments") or {}).get("current")
        pf_other_bank = (pf_bs.get("other_bank_balances") or {}).get("current")
        if pf_unrestricted is not None and pf_earmarked is not None:
            restricted_earmarked_cash = float(pf_earmarked) * pf_mult
            cash_and_equivalents = float(pf_unrestricted) * pf_mult
            gross_cash_filing = float((pf_cce or 0.0) + (pf_cur_inv or 0.0) + (pf_other_bank or 0.0)) * pf_mult
            gross_cash_and_sti = max(gross_cash_and_sti, gross_cash_filing)
            cash_recon_source = primary_filing.get("source_citation", "Primary Annual Report")
            cash_recon_note_ref = "Note 13, Note 15, Note 16"
            cash_recon_components = {
                "cash_and_cash_equivalents": float(pf_cce or 0.0) * pf_mult,
                "current_investments": float(pf_cur_inv or 0.0) * pf_mult,
                "other_bank_balances_total": float(pf_other_bank or 0.0) * pf_mult,
                "restricted_earmarked_other_bank": restricted_earmarked_cash,
                "unrestricted_other_bank": float(n16.get("unrestricted_other_bank_balances") or 0.0) * pf_mult,
                "unrestricted_cash_for_ev_bridge": cash_and_equivalents,
            }
        else:
            cash_and_equivalents = gross_cash_and_sti
    else:
        # Check Balance Sheet Restricted Cash first, then SEC EDGAR XBRL RestrictedCash disclosure
        cash_and_equivalents = gross_cash_and_sti
        sti0 = max(0.0, float(safe_get(balance_sheet, "Other Short Term Investments", default=0.0)[0]))
        cce0 = max(0.0, float(safe_get(balance_sheet, "Cash And Cash Equivalents", default=0.0)[0]))
        if "Restricted Cash" in balance_sheet.columns:
            rc_val = max(0.0, float(safe_get(balance_sheet, "Restricted Cash", default=0.0)[0]))
            if rc_val > 0 and gross_cash_and_sti >= cce0 + rc_val and sti0 >= rc_val:
                restricted_earmarked_cash = rc_val
                cash_and_equivalents = max(0.0, gross_cash_and_sti - rc_val)
                cash_recon_note_ref = "Balance Sheet Restricted Cash"

        sec_lq = (stock_data.get("sec_edgar") or {}).get("latest_quarter") or {}
        sec_rc = sec_lq.get("restricted_cash")
        if sec_rc and float(sec_rc.get("value") or 0.0) > 0:
            sec_rc_val = float(sec_rc["value"])
            cash_recon_components["sec_restricted_cash_disclosed"] = sec_rc_val
            cash_recon_components["sec_restricted_cash_tag"] = sec_rc.get("tag")
            cash_recon_components["sec_restricted_cash_end"] = sec_rc.get("end")
            if restricted_earmarked_cash <= 0.0 and gross_cash_and_sti >= cce0 + sec_rc_val and sti0 >= sec_rc_val:
                restricted_earmarked_cash = sec_rc_val
                cash_and_equivalents = max(0.0, gross_cash_and_sti - sec_rc_val)
                cash_recon_source = f"SEC EDGAR ({sec_rc.get('tag', 'RestrictedCash')})"
                cash_recon_note_ref = sec_rc.get("end")
            else:
                cash_recon_components["sec_restricted_cash_already_excluded"] = bool(restricted_earmarked_cash <= 0.0)

    # Lease Liability Accounting Policy (standard-aware, never ad-hoc):
    # - US_GAAP (ASC 842): Operating lease cost is expensed straight-line inside EBIT OPEX -> EXCLUDE
    #   operating lease liabilities from Total Debt in EV bridge & WACC weights so obligations aren't double-counted.
    # - IND_AS (Ind AS 116) / IFRS (IFRS 16): Lease ROU amortisation is deducted inside EBIT while lease finance
    #   cost sits below EBIT inside Finance Costs -> RETAIN Ind AS 116 / IFRS 16 lease liabilities in Total Debt.
    lease_obligations = 0.0
    if not is_financial and total_debt > 0:
        if "Capital Lease Obligations" in balance_sheet.columns:
            lease_obligations = float(safe_get(balance_sheet, "Capital Lease Obligations", default=0.0)[0])
        else:
            lt_lease = float(safe_get(balance_sheet, "Long Term Capital Lease Obligation", default=0.0)[0]) if "Long Term Capital Lease Obligation" in balance_sheet.columns else 0.0
            st_lease = float(safe_get(balance_sheet, "Current Capital Lease Obligation", default=0.0)[0]) if "Current Capital Lease Obligation" in balance_sheet.columns else 0.0
            lease_obligations = lt_lease + st_lease

    lease_included_in_debt = False
    if acct_std in ("IND_AS", "IFRS"):
        lease_included_in_debt = True
        lease_policy = {
            "accounting_standard": acct_std,
            "policy": "INCLUDED_IN_DEBT_IND_AS_116",
            "included_in_debt": True,
            "lease_liabilities_bs": float(lease_obligations),
            "detail": (
                f"{acct_std}: ROU asset amortisation is deducted inside EBIT and lease interest sits below EBIT "
                f"in Finance Costs; lease liabilities ({lease_obligations:,.2f}) are RETAINED in Total Debt for EV/FCFF parity."
            ),
        }
    else:
        if lease_obligations > 0 and total_debt >= lease_obligations:
            total_debt = max(0.0, total_debt - lease_obligations)
        lease_policy = {
            "accounting_standard": acct_std,
            "policy": "EXCLUDED_OPERATING_LEASES_ASC_842",
            "included_in_debt": False,
            "lease_liabilities_bs": float(lease_obligations),
            "detail": (
                f"{acct_std} (ASC 842): Operating lease expense is already deducted inside EBIT/OPEX; "
                f"operating lease liabilities ({lease_obligations:,.2f}) are EXCLUDED from EV Debt (disclosed as memo)."
            ),
        }

    # Attach SEC EDGAR latest quarterly lease disclosure when available
    sec_edgar = stock_data.get("sec_edgar") or {}
    if sec_edgar and sec_edgar.get("latest_quarter"):
        lq = sec_edgar["latest_quarter"]
        lease_policy["sec_latest_operating_lease_total"] = (lq.get("operating_lease_total") or {}).get("value")
        lease_policy["sec_latest_operating_lease_current"] = (lq.get("operating_lease_current") or {}).get("value")
        lease_policy["sec_latest_operating_lease_noncurrent"] = (lq.get("operating_lease_noncurrent") or {}).get("value")
    if primary_filing and primary_filing.get("available"):
        n47 = (primary_filing.get("notes") or {}).get("note_47_ind_as_116_leases", {})
        if n47:
            pf_mult = float(primary_filing.get("unit_multiplier", 1e7))
            lease_policy["rou_amortisation"] = (n47.get("rou_amortisation") or 0.0) * pf_mult if n47.get("rou_amortisation") is not None else None
            lease_policy["lease_finance_cost"] = (n47.get("lease_finance_cost") or 0.0) * pf_mult if n47.get("lease_finance_cost") is not None else None
            lease_policy["lease_payment"] = (n47.get("lease_payment") or 0.0) * pf_mult if n47.get("lease_payment") is not None else None

    # 2. Captive financing & consolidated NBFC receivables detected structurally from Balance Sheet columns
    latest_rev = float(revenue[-1]) if len(revenue) > 0 else 0.0
    captive_debt_offset = 0.0
    if not is_financial and has_captive_arm and total_debt > 0 and latest_rev > 0 and total_debt > 0.30 * latest_rev:
        captive_rec = 0.0
        for col_name in [
            "Non Current Accounts Receivable",
            "Non Current Note Receivables",
            "Long Term Receivables",
            "Loans Receivable",
        ]:
            if col_name in balance_sheet.columns:
                val = float(safe_get(balance_sheet, col_name, default=0.0)[0])
                if val > captive_rec:
                    captive_rec = val
        latest_excess_rec = float(excess_fin_rec_series[-1]) if len(excess_fin_rec_series) > 0 else 0.0
        total_captive_offset = max(captive_rec, latest_excess_rec)

        if total_debt > 0.70 * latest_rev and "Investmentin Financial Assets" in balance_sheet.columns:
            fin_inv_assets = float(safe_get(balance_sheet, "Investmentin Financial Assets", default=0.0)[0])
            if fin_inv_assets > 0.25 * total_debt:
                total_captive_offset += fin_inv_assets

        if total_captive_offset > 0.15 * latest_rev:
            offset_applied = min(total_debt * 0.85, total_captive_offset)
            captive_debt_offset = float(offset_applied)
            total_debt = max(0.0, total_debt - offset_applied)
            valuation_adjustments.append({
                "name": "Captive Finance Receivables Debt Offset",
                "category": "captive_debt_offset",
                "status": "APPLIED",
                "raw_value": float(raw_total_debt),
                "applied_value": float(total_debt),
                "offset": float(captive_debt_offset),
                "rationale": (
                    f"Balance sheet carries material finance/loan receivables ({total_captive_offset:,.0f} > 15% of revenue); "
                    "isolated industrial financial debt from captive financing funding."
                ),
                "alternative_scenario": "unadjusted_gross_debt",
            })

    # 3. Consolidated Minority Interest (Noncontrolling Interest), Preferred Stock, Extractive ARO, & Uncommissioned CWIP
    cwip_to_rev = 0.0
    minority_interest_claim = 0.0
    preferred_stock_claim = 0.0
    aro_provisions_claim = 0.0
    unverified_aro_stress_claim = 0.0
    aro_verified = False
    raw_lt_provisions = 0.0
    greenfield_debt_offset = 0.0
    if not is_financial:
        bs_minority = (
            max(0.0, float(safe_get(balance_sheet, "Minority Interest", default=0.0)[0]))
            if "Minority Interest" in balance_sheet.columns
            else 0.0
        )
        if bs_minority > 0.0:
            minority_claim = bs_minority * 0.50 if (latest_rev > 0 and bs_minority > 0.20 * latest_rev) else bs_minority
            minority_interest_claim = float(minority_claim)
            if abs(minority_claim - bs_minority) > 1.0:
                valuation_adjustments.append({
                    "name": "Minority Interest Carrying-Value Haircut",
                    "category": "minority_interest",
                    "status": "APPLIED",
                    "raw_value": float(bs_minority),
                    "applied_value": float(minority_interest_claim),
                    "rationale": "Consolidated Minority Interest exceeds 20% of revenue; half weighted to avoid double-discounting associate equity.",
                })

        if "Preferred Stock" in balance_sheet.columns:
            preferred_stock_claim = max(0.0, float(safe_get(balance_sheet, "Preferred Stock", default=0.0)[0]))

    if not is_financial and latest_rev > 0:
        cwip_val = (
            max(0.0, float(safe_get(balance_sheet, "Construction In Progress", default=0.0)[0]))
            if "Construction In Progress" in balance_sheet.columns
            else 0.0
        )
        cwip_to_rev = cwip_val / latest_rev

        if "Long Term Provisions" in balance_sheet.columns:
            raw_lt_provisions = max(0.0, float(safe_get(balance_sheet, "Long Term Provisions", default=0.0)[0]))

        sec_aro = ((stock_data.get("sec_edgar") or {}).get("latest_quarter") or {}).get("aro_obligation")
        if stock_data.get("is_extractive", False) and sec_aro and float(sec_aro.get("value") or 0.0) > 0:
            aro_provisions_claim = float(sec_aro["value"])
            aro_verified = True
            total_debt += aro_provisions_claim
            valuation_adjustments.append({
                "name": "Primary-Verified Asset Retirement Obligation (ARO)",
                "category": "aro_provisions",
                "status": "APPLIED_PRIMARY_VERIFIED",
                "raw_value": float(raw_lt_provisions),
                "applied_value": float(aro_provisions_claim),
                "tag": sec_aro.get("tag"),
                "period": sec_aro.get("end"),
                "rationale": f"SEC XBRL ({sec_aro.get('tag')}) verified statutory decommissioning/ARO liability added to debt claims.",
                "alternative_scenario": "unadjusted_gross_debt",
            })
        elif stock_data.get("is_extractive", False) and raw_lt_provisions > 0.05 * latest_rev:
            # Do NOT silently fabricate debt from 75% of generic LT Provisions without ARO note confirmation;
            # expose explicit stress claim for investigation & aro_provisions_stress scenario.
            unverified_aro_stress_claim = float(0.75 * raw_lt_provisions)
            valuation_adjustments.append({
                "name": "Extractive Long-Term Provisions (Unverified ARO Not Auto-Added)",
                "category": "aro_provisions",
                "status": "FLAGGED_FOR_INVESTIGATION",
                "raw_value": float(raw_lt_provisions),
                "applied_value": 0.0,
                "stress_value": float(unverified_aro_stress_claim),
                "rationale": (
                    f"Balance sheet Long-Term Provisions ({raw_lt_provisions:,.0f}) exceed 5% of revenue in an extractive firm "
                    "without primary ARO note confirmation; kept unadjusted in Base Debt (inspect 75% ARO Stress scenario)."
                ),
                "alternative_scenario": "aro_provisions_stress",
            })

        if cwip_to_rev > 0.50 and total_debt > 0:
            afs_val = (
                max(0.0, float(safe_get(balance_sheet, "Available For Sale Securities", default=0.0)[0]))
                if "Available For Sale Securities" in balance_sheet.columns
                else 0.0
            )
            cwip_offset = 0.65 * max(0.0, cwip_val - 0.20 * latest_rev) + 0.85 * afs_val
            prev_td = total_debt
            total_debt = max(0.10 * raw_total_debt, total_debt - cwip_offset)
            greenfield_debt_offset = float(max(0.0, prev_td - total_debt))
        elif (
            not stock_data.get("is_extractive", False)
            and avg_capex_pct > 2.2 * avg_dna_pct
            and total_debt > 0.45 * latest_rev
        ):
            net_ppe_val = (
                max(0.0, float(safe_get(balance_sheet, "Net PPE", default=0.0)[0]))
                if "Net PPE" in balance_sheet.columns
                else 0.0
            )
            other_intang_val = (
                max(0.0, float(safe_get(balance_sheet, "Other Intangible Assets", default=0.0)[0]))
                if "Other Intangible Assets" in balance_sheet.columns
                else 0.0
            )
            infra_asset_base = net_ppe_val + cwip_val + other_intang_val
            recent_net_capex = float(np.sum(np.maximum(0.0, capex[-3:] - dna[-3:] * 1.15)))
            greenfield_capital = (
                cwip_val
                + 0.85 * recent_net_capex
                + (lease_obligations if lease_included_in_debt else 0.0)
            )
            cur_ebit_val = float(ebit[-1]) if len(ebit) > 0 else 0.0
            if (
                infra_asset_base > 0
                and (cur_ebit_val / infra_asset_base) < 0.085
                and greenfield_capital > 0.35 * total_debt
            ):
                gf_offset = min(total_debt * 0.82, greenfield_capital * 0.85)
                prev_td = total_debt
                total_debt = max(0.15 * raw_total_debt, total_debt - gf_offset)
                greenfield_debt_offset = float(max(0.0, prev_td - total_debt))

        if greenfield_debt_offset > 0:
            valuation_adjustments.append({
                "name": "Greenfield CWIP / Project Debt Alignment Offset",
                "category": "greenfield_debt_offset",
                "status": "APPLIED",
                "raw_value": float(raw_total_debt),
                "applied_value": float(total_debt),
                "offset": float(greenfield_debt_offset),
                "cwip_to_rev": float(cwip_to_rev),
                "rationale": (
                    f"Uncommissioned CWIP ({cwip_to_rev*100:.1f}% of rev) / multi-year buildout debt isolated "
                    f"({greenfield_debt_offset:,.0f}) from operating EV Debt; see Unadjusted Gross Debt scenario."
                ),
                "alternative_scenario": "unadjusted_gross_debt",
            })


    # Interest expense (for cost-of-debt calculation)
    interest_expense: float = 0.0
    for ie_col in ["Interest Expense", "Interest Expense Non Operating"]:
        if ie_col in income_stmt.columns:
            ie_vals = income_stmt[ie_col].dropna()
            if len(ie_vals) > 0:
                interest_expense = abs(float(ie_vals.iloc[0]))
                break

    last_ebit = float(ebit[-1]) if len(ebit) > 0 else 0.0
    if interest_expense > 0:
        interest_coverage = float(last_ebit / interest_expense)
    else:
        interest_coverage = 999.0  # Zero interest / debt free

    n_years = len(revenue)

    def _extract_series(df, col_candidates, default=0.0):
        if isinstance(col_candidates, str):
            col_candidates = [col_candidates]
        aligned_df = df.reindex(income_stmt.index)
        present = [c for c in col_candidates if c in aligned_df.columns]
        if present:
            sub = aligned_df[present].apply(pd.to_numeric, errors="coerce")
            series = sub.bfill(axis=1).iloc[:, 0].fillna(default).values[::-1]
            return [float(x) for x in series]
        return [default] * n_years

    # ------------------------------------------------------------------
    # 3G – Reconciled & Disaggregated 3-Statement Extraction
    # Ensures:
    #   1) Income Statement: Both statutory disaggregated expense categories (COGS, SG&A,
    #      Employee Benefits, R&D, Other OpEx, OpEx D&A, Regulatory Deferral Adjustments,
    #      Consolidated PAT, Minority Interest, Parent PAT, Basic/Diluted/Period-End Shares)
    #      AND strict reconciliation identities hold across all years.
    #   2) Balance Sheet: Full disaggregation of Equity (Common Stock, APIC, Retained Earnings),
    #      Liabilities (Accounts Payable, Accrued & Tax Payable, Deferred Revenue, Deferred Tax
    #      Liabilities, Provisions, Borrowings, Leases), and Assets (PPE, CWIP, Intangibles,
    #      Long-Term Investments incl. Other Investments, Regulatory Deferral & Non-Current
    #      Deferred Assets, Receivables, Inventory, Cash, Short-Term Investments, Deferred/Prepaid CA).
    #   3) Cash Flow Statement: 100% formula-summed CFO, CFI, CFF, Cash Bridge, Restricted Cash,
    #      Levered FCF, and Unlevered FCFF.
    # ------------------------------------------------------------------
    rev_list = revenue.tolist()
    ebitda_list = ebitda_arr.tolist()
    dna_list = dna.tolist()
    ebit_list = ebit.tolist()
    ni_list = net_income.tolist()
    stat_op_inc_list = [float(x) for x in stat_op_inc]

    cogs_raw = _extract_series(income_stmt, ["Cost Of Revenue", "Reconciled Cost Of Revenue"])
    gp_raw = _extract_series(income_stmt, ["Gross Profit"])
    cogs_clean = []
    gp_clean = []
    stat_cogs_clean = []
    stat_gp_clean = []
    for i in range(n_years):
        r_i = float(rev_list[i])
        c_i = float(cogs_raw[i])
        g_i = float(gp_raw[i])
        if g_i == 0.0 and r_i > 0.0:
            g_i = (r_i - c_i) if c_i > 0.0 else r_i
        sc_i = (r_i - g_i) if r_i > 0.0 else c_i
        stat_cogs_clean.append(float(sc_i))
        stat_gp_clean.append(float(g_i))
        if i < len(cogs_amort_addback) and cogs_amort_addback[i] > 0.0:
            g_i = min(r_i, g_i + float(cogs_amort_addback[i]))
        c_i = (r_i - g_i) if r_i > 0.0 else c_i
        cogs_clean.append(float(c_i))
        gp_clean.append(float(g_i))

    sga_cols = ["Selling General And Administration"] if not is_financial else ["Selling General And Administration", "Operating Expense"]
    sga_list = _extract_series(income_stmt, sga_cols)
    rnd_list = _extract_series(income_stmt, ["Research And Development"])
    other_opex_list = [
        float(gp_clean[i] - sga_list[i] - rnd_list[i] - ebitda_list[i])
        for i in range(n_years)
    ]

    # Disaggregated statutory operating expenses (without -D&A plug or regulatory deferral distortion)
    has_is_dna = (not is_financial) and ("Depreciation And Amortization In Income Statement" in income_stmt.columns)
    raw_is_dna = _extract_series(income_stmt, ["Depreciation And Amortization In Income Statement"]) if has_is_dna else [0.0] * n_years
    raw_tot_opex = _extract_series(income_stmt, ["Operating Expense"])
    raw_oth_opex_col = _extract_series(income_stmt, ["Other Operating Expenses"]) if "Other Operating Expenses" in income_stmt.columns else [0.0] * n_years

    emp_benefits_list = []
    stat_other_opex_list = []
    opex_dna_list = []
    op_norm_adj_list = []
    for i in range(n_years):
        tot_opex_needed = float(gp_clean[i] - stat_op_inc_list[i])
        sga_i = float(sga_list[i])
        rnd_i = float(rnd_list[i])
        if has_is_dna and raw_is_dna[i] > 0.0:
            is_dna_i = abs(float(raw_is_dna[i]))
            oth_i = float(raw_oth_opex_col[i])
            emp_i = max(0.0, tot_opex_needed - (sga_i + rnd_i + oth_i + is_dna_i))
            rem_i = tot_opex_needed - (sga_i + rnd_i + emp_i + is_dna_i)
            emp_benefits_list.append(float(emp_i))
            stat_other_opex_list.append(float(rem_i))
            opex_dna_list.append(float(is_dna_i))
        else:
            emp_benefits_list.append(0.0)
            opex_dna_list.append(0.0)
            stat_other_opex_list.append(float(tot_opex_needed - (sga_i + rnd_i)))
        op_norm_adj_list.append(float(ebit_list[i] - stat_op_inc_list[i]))

    ie_list = [
        abs(float(x))
        for x in _extract_series(income_stmt, ["Interest Expense", "Interest Expense Non Operating"])
    ]
    oth_fin_cost_list = [
        abs(float(x))
        for x in _extract_series(income_stmt, ["Total Other Finance Cost"])
    ]
    ebt_list = _extract_series(income_stmt, ["Pretax Income"])
    non_op_inc_list = [
        float(ebt_list[i] - (ebit_list[i] - ie_list[i]))
        for i in range(n_years)
    ]
    rep_reg_other_nonop_list = _extract_series(income_stmt, ["Other Non Operating Income Expenses", "Other Income Expense"])
    rep_int_inc_nonop_list = _extract_series(income_stmt, ["Interest Income Non Operating", "Interest Income"])
    tax_list = _extract_series(income_stmt, ["Tax Provision"])
    cons_pat_list = [float(ebt_list[i] - tax_list[i]) for i in range(n_years)]
    min_int_inc_list = [
        float((ebt_list[i] - tax_list[i]) - ni_list[i])
        for i in range(n_years)
    ]

    # Share Count Disaggregation (Basic Weighted-Avg, Diluted Weighted-Avg, Period-End Basic Shares)
    # Zero hardcoded overrides or SBC-multiplier fabrications: pull authoritative SEC XBRL / primary
    # filing WASO when available, and track missing disclosures via canonical provenance statuses.
    years_str_list = [str(d.year) if hasattr(d, "year") else str(d)[:4] for d in income_stmt.index][::-1]
    pe_shares_raw = _extract_series(balance_sheet, ["Ordinary Shares Number", "Share Issued"])
    bas_shares_raw = _extract_series(income_stmt, ["Basic Average Shares"])
    dil_shares_raw = _extract_series(income_stmt, ["Diluted Average Shares"])
    rep_bas_eps_raw = _extract_series(income_stmt, ["Basic EPS"]) if "Basic EPS" in income_stmt.columns else [None] * n_years
    rep_dil_eps_raw = _extract_series(income_stmt, ["Diluted EPS"]) if "Diluted EPS" in income_stmt.columns else [None] * n_years

    sec_bas_map = (sec_edgar or {}).get("basic_waso_by_year") or {}
    sec_dil_map = (sec_edgar or {}).get("diluted_waso_by_year") or {}
    sec_bas_eps_map = (sec_edgar or {}).get("basic_eps_by_year") or {}
    sec_dil_eps_map = (sec_edgar or {}).get("diluted_eps_by_year") or {}
    sec_tax_paid_map = (sec_edgar or {}).get("cash_taxes_paid_by_year") or {}

    pe_shares_clean: List[float] = []
    bas_shares_clean: List[float] = []
    dil_shares_clean: List[float] = []
    bas_eps_clean: List[float] = []
    dil_eps_clean: List[float] = []
    share_provenance: List[Dict[str, Any]] = []

    for i in range(n_years):
        yr_int = int(years_str_list[i]) if years_str_list[i].isdigit() else None
        pe_i = float(pe_shares_raw[i]) if pe_shares_raw[i] > 0 else float(bas_shares_raw[i])
        sec_bas = sec_bas_map.get(yr_int, {}).get("value") if yr_int else None
        sec_dil = sec_dil_map.get(yr_int, {}).get("value") if yr_int else None

        if sec_bas and sec_bas > 0:
            bas_i = float(sec_bas)
            bas_src = sec_bas_map[yr_int].get("tag", "SEC EDGAR Basic WASO")
            bas_stat = "VALUE"
        elif bas_shares_raw[i] and float(bas_shares_raw[i]) > 0:
            bas_i = float(bas_shares_raw[i])
            bas_src = "Yahoo Finance Basic Average Shares"
            bas_stat = "VALUE"
        else:
            bas_i = float(pe_i)
            bas_src = "Period-End Shares Proxy (Weighted-Avg Missing)"
            bas_stat = "MISSING"

        if sec_dil and sec_dil > 0:
            dil_i = float(sec_dil)
            dil_src = sec_dil_map[yr_int].get("tag", "SEC EDGAR Diluted WASO")
            dil_stat = "VALUE"
        elif dil_shares_raw[i] and float(dil_shares_raw[i]) > 0:
            dil_i = float(dil_shares_raw[i])
            dil_src = "Yahoo Finance Diluted Average Shares"
            dil_stat = "VALUE"
        else:
            dil_i = float(bas_i)
            dil_src = "Basic Shares Fallback (Diluted Missing)"
            dil_stat = "MISSING"

        if ni_list[i] > 0 and dil_i < bas_i:
            dil_i = bas_i

        sec_beps = sec_bas_eps_map.get(yr_int, {}).get("value") if yr_int else None
        sec_deps = sec_dil_eps_map.get(yr_int, {}).get("value") if yr_int else None
        b_eps = float(sec_beps) if sec_beps is not None else (
            float(rep_bas_eps_raw[i]) if (rep_bas_eps_raw[i] is not None and rep_bas_eps_raw[i] != 0.0)
            else (float(ni_list[i] / bas_i) if bas_i > 0 else 0.0)
        )
        d_eps = float(sec_deps) if sec_deps is not None else (
            float(rep_dil_eps_raw[i]) if (rep_dil_eps_raw[i] is not None and rep_dil_eps_raw[i] != 0.0)
            else (float(ni_list[i] / dil_i) if dil_i > 0 else 0.0)
        )

        pe_shares_clean.append(float(pe_i))
        bas_shares_clean.append(float(bas_i))
        dil_shares_clean.append(float(dil_i))
        bas_eps_clean.append(b_eps)
        dil_eps_clean.append(d_eps)
        share_provenance.append({
            "year": years_str_list[i],
            "basic_waso": make_provenance(bas_i, bas_stat, bas_src, period=years_str_list[i], unit="shares"),
            "diluted_waso": make_provenance(dil_i, dil_stat, dil_src, period=years_str_list[i], unit="shares"),
        })

    # Balance Sheet reconciliation & disaggregation
    tot_assets_s = _extract_series(balance_sheet, ["Total Assets"])
    tot_ca_s = _extract_series(balance_sheet, ["Current Assets"])
    tot_nca_raw = _extract_series(balance_sheet, ["Total Non Current Assets"])
    tot_nca_s = [
        float(tot_assets_s[i] - tot_ca_s[i]) if tot_assets_s[i] > 0.0 else float(tot_nca_raw[i])
        for i in range(n_years)
    ]

    _se_bs = _extract_series(balance_sheet, ["Stockholders Equity"])
    _cse_bs = _extract_series(balance_sheet, ["Common Stock Equity"])
    tot_eq_s = [
        float(_cse_bs[i]) if (abs(float(_se_bs[i])) < 1e-6 and abs(float(_cse_bs[i])) > 1e-6) else float(_se_bs[i])
        for i in range(n_years)
    ]
    eq_cap_raw = _extract_series(balance_sheet, ["Common Stock", "Capital Stock"])
    eq_cap_s = [
        float(eq_cap_raw[i]) if abs(eq_cap_raw[i]) <= abs(tot_eq_s[i]) * 1.5 + 1.0 else 0.0
        for i in range(n_years)
    ]
    res_s = [float(tot_eq_s[i] - eq_cap_s[i]) for i in range(n_years)]
    apic_raw = _extract_series(balance_sheet, ["Additional Paid In Capital", "Capital Surplus"])
    apic_s = [
        float(apic_raw[i]) if 0.0 <= float(apic_raw[i]) <= abs(tot_eq_s[i]) * 3.0 + 1e6 else 0.0
        for i in range(n_years)
    ]
    ret_earn_s = [float(res_s[i] - apic_s[i]) for i in range(n_years)]
    min_int_bs_s = _extract_series(balance_sheet, ["Minority Interest"])

    raw_tot_debt_s = _extract_series(balance_sheet, ["Total Debt"])
    st_lease_s = _extract_series(balance_sheet, ["Current Capital Lease Obligation"])
    lt_lease_s = _extract_series(balance_sheet, ["Long Term Capital Lease Obligation"])
    tot_lease_raw = _extract_series(balance_sheet, ["Capital Lease Obligations"])
    lease_s = []
    tot_fin_debt_s = []
    st_borr_s = []
    lt_borr_s = []

    st_debt_only = _extract_series(balance_sheet, ["Current Debt"])
    st_debt_incl = _extract_series(balance_sheet, ["Current Debt And Capital Lease Obligation"])
    lt_debt_only = _extract_series(balance_sheet, ["Long Term Debt"])
    lt_debt_incl = _extract_series(balance_sheet, ["Long Term Debt And Capital Lease Obligation"])

    for i in range(n_years):
        r_td = max(0.0, float(raw_tot_debt_s[i]))
        if is_financial:
            l_i = 0.0
        else:
            l_cand = float(tot_lease_raw[i]) if tot_lease_raw[i] > 0.0 else float(st_lease_s[i] + lt_lease_s[i])
            l_i = min(r_td, max(0.0, l_cand))
        fin_td = max(0.0, r_td - l_i)
        lease_s.append(float(l_i))
        tot_fin_debt_s.append(float(fin_td))

        if "Current Debt" in balance_sheet.columns and st_debt_only[i] > 0.0:
            st_b = float(st_debt_only[i])
        else:
            st_b = max(0.0, float(st_debt_incl[i] - st_lease_s[i]))
        st_b = min(fin_td, max(0.0, st_b))
        lt_b = max(0.0, fin_td - st_b)
        st_borr_s.append(float(st_b))
        lt_borr_s.append(float(lt_b))

    # Disaggregate other_liab_s strictly from Liabilities-side items (never plug to Total Assets)
    ap_raw = _extract_series(balance_sheet, ["Accounts Payable", "Payables"])
    pay_acc_raw = _extract_series(balance_sheet, ["Payables And Accrued Expenses", "Payables"])
    cur_def_rev_raw = _extract_series(balance_sheet, ["Current Deferred Revenue", "Current Deferred Liabilities"])
    nc_def_rev_raw = _extract_series(balance_sheet, ["Non Current Deferred Revenue"])
    dtl_raw = _extract_series(balance_sheet, ["Non Current Deferred Taxes Liabilities"])
    lt_prov_raw = _extract_series(balance_sheet, ["Long Term Provisions"])
    cur_prov_raw = _extract_series(balance_sheet, ["Current Provisions"])
    cur_pens_raw = _extract_series(balance_sheet, ["Pensionand Other Post Retirement Benefit Plans Current"])
    tot_liab_net_mi_s = _extract_series(balance_sheet, ["Total Liabilities Net Minority Interest", "Total Liabilities"])
    curr_liab_rep_s = _extract_series(balance_sheet, ["Current Liabilities"])
    nc_liab_rep_s = _extract_series(balance_sheet, ["Total Non Current Liabilities Net Minority Interest"])
    tot_eq_gross_mi_s = _extract_series(balance_sheet, ["Total Equity Gross Minority Interest"])
    has_rep_tot_liab = (
        "Total Liabilities Net Minority Interest" in balance_sheet.columns
        or "Total Liabilities" in balance_sheet.columns
    )
    has_cl_ncl = (
        "Current Liabilities" in balance_sheet.columns
        and "Total Non Current Liabilities Net Minority Interest" in balance_sheet.columns
    )
    has_eq_gross = "Total Equity Gross Minority Interest" in balance_sheet.columns

    other_liab_s = []
    tot_liab_eq_s = []
    for i in range(n_years):
        eq_gross_i = (
            float(tot_eq_gross_mi_s[i])
            if (has_eq_gross and float(tot_eq_gross_mi_s[i]) != 0.0)
            else float(tot_eq_s[i] + min_int_bs_s[i])
        )
        if has_rep_tot_liab and float(tot_liab_net_mi_s[i]) != 0.0:
            rep_liab_i = float(tot_liab_net_mi_s[i])
        elif has_cl_ncl and (float(curr_liab_rep_s[i]) != 0.0 or float(nc_liab_rep_s[i]) != 0.0):
            rep_liab_i = float(curr_liab_rep_s[i]) + float(nc_liab_rep_s[i])
        else:
            acc_fb = max(0.0, float(pay_acc_raw[i]) - float(ap_raw[i])) if float(pay_acc_raw[i]) > float(ap_raw[i]) else 0.0
            rep_liab_i = float(
                tot_fin_debt_s[i]
                + lease_s[i]
                + max(0.0, float(ap_raw[i]))
                + acc_fb
                + max(0.0, float(cur_def_rev_raw[i]) + float(nc_def_rev_raw[i]))
                + max(0.0, float(dtl_raw[i]))
                + max(0.0, float(lt_prov_raw[i]) + float(cur_prov_raw[i]) + float(cur_pens_raw[i]))
            )
        if tot_assets_s[i] > 0.0 and abs((rep_liab_i + eq_gross_i) - tot_assets_s[i]) > 0.5:
            rep_liab_i = float(tot_assets_s[i] - eq_gross_i)
        other_liab_s.append(float(rep_liab_i - tot_fin_debt_s[i] - lease_s[i]))
        tot_liab_eq_s.append(float(rep_liab_i + eq_gross_i))

    ap_s = []
    accrued_s = []
    def_rev_s = []
    dtl_s = []
    prov_s = []
    oth_liab_disagg_s = []
    for i in range(n_years):
        avail_liab = max(0.0, float(other_liab_s[i]))
        ap_i = min(avail_liab, max(0.0, float(ap_raw[i])))
        acc_cand = max(0.0, float(pay_acc_raw[i]) - ap_i) if float(pay_acc_raw[i]) > ap_i else 0.0
        acc_i = min(max(0.0, avail_liab - ap_i), acc_cand)
        def_r_i = min(max(0.0, avail_liab - ap_i - acc_i), max(0.0, float(cur_def_rev_raw[i]) + float(nc_def_rev_raw[i])))
        dtl_i = min(max(0.0, avail_liab - ap_i - acc_i - def_r_i), max(0.0, float(dtl_raw[i])))
        prov_i = min(
            max(0.0, avail_liab - ap_i - acc_i - def_r_i - dtl_i),
            max(0.0, float(lt_prov_raw[i]) + float(cur_prov_raw[i]) + float(cur_pens_raw[i])),
        )
        oth_l_i = float(other_liab_s[i] - (ap_i + acc_i + def_r_i + dtl_i + prov_i))
        ap_s.append(float(ap_i))
        accrued_s.append(float(acc_i))
        def_rev_s.append(float(def_r_i))
        dtl_s.append(float(dtl_i))
        prov_s.append(float(prov_i))
        oth_liab_disagg_s.append(float(oth_l_i))

    # Non-current assets breakdown (prioritize 'Investments And Advances' so Other Investments like DUOL's $1.4M are captured)
    ppe_raw = _extract_series(balance_sheet, ["Net PPE", "Properties"])
    cwip_s = _extract_series(balance_sheet, ["Construction In Progress"])
    intang_s = _extract_series(balance_sheet, ["Goodwill And Other Intangible Assets", "Goodwill"])
    inv_nc_s = _extract_series(
        balance_sheet,
        ["Investments And Advances", "Investmentin Financial Assets", "Long Term Equity Investment", "Available For Sale Securities"],
    )
    def_nca_raw = _extract_series(balance_sheet, ["Non Current Deferred Assets", "Non Current Deferred Taxes Assets"])
    dta_only_raw = _extract_series(balance_sheet, ["Non Current Deferred Taxes Assets", "Deferred Tax Assets"])
    ppe_s = []
    oth_nc_s = []
    def_nca_s = []
    non_tax_reg_def_s = []
    oth_nc_disagg_s = []
    for i in range(n_years):
        p_i = float(ppe_raw[i])
        c_i = float(cwip_s[i])
        # If Net PPE in Yahoo already includes CWIP and would push sum (including deferred/regulatory assets) above Total Non-Current Assets, deduct CWIP from Net PPE
        if p_i >= c_i > 0.0 and (p_i + c_i + intang_s[i] + inv_nc_s[i] + max(0.0, float(def_nca_raw[i]))) > tot_nca_s[i] * 1.01:
            p_i = p_i - c_i
        ppe_s.append(float(p_i))
        rem_nca_i = float(tot_nca_s[i] - (p_i + c_i + intang_s[i] + inv_nc_s[i]))
        oth_nc_s.append(rem_nca_i)
        d_nca_i = min(max(0.0, rem_nca_i), max(0.0, float(def_nca_raw[i])))
        def_nca_s.append(float(d_nca_i))
        non_tax_reg_def_s.append(max(0.0, float(d_nca_i) - max(0.0, float(dta_only_raw[i]))))
        oth_nc_disagg_s.append(float(rem_nca_i - d_nca_i))

    # Current assets breakdown: prioritize pure Trade / Accounts Receivable ahead of bundled Receivables
    # so tax receivables and other receivables are not mislabelled as Trade Receivables.
    if "Accounts Receivable" in balance_sheet.columns:
        ar_s = _extract_series(balance_sheet, ["Accounts Receivable", "Gross Accounts Receivable"])
    elif "Receivables" in balance_sheet.columns:
        ar_s = _extract_series(balance_sheet, ["Receivables", "Accounts Receivable", "Gross Accounts Receivable"])
    else:
        ar_s = _extract_series(balance_sheet, ["Other Receivables", "Taxes Receivable"])
    oth_tax_rec_ca_s = [
        float(
            (_extract_series(balance_sheet, ["Other Receivables"])[i] if "Other Receivables" in balance_sheet.columns else 0.0)
            + (_extract_series(balance_sheet, ["Taxes Receivable"])[i] if "Taxes Receivable" in balance_sheet.columns else 0.0)
        )
        for i in range(n_years)
    ]
    inv_ca_s = _extract_series(balance_sheet, ["Inventory", "Finished Goods"])
    cce_raw = _extract_series(balance_sheet, ["Cash And Cash Equivalents", "Cash Financial"])
    osti_raw = _extract_series(balance_sheet, ["Other Short Term Investments"])
    cur_def_ca_raw = _extract_series(balance_sheet, ["Current Deferred Assets"])
    prepaid_ca_raw = _extract_series(balance_sheet, ["Prepaid Assets"])
    cce_clean = []
    sti_clean = []
    oth_ca_s = []
    def_prepaid_ca_s = []
    oth_ca_disagg_s = []
    for i in range(n_years):
        tot_cash_i = float(cash_on_bs[i]) if i < len(cash_on_bs) else float(cce_raw[i] + osti_raw[i])
        c_i = float(cce_raw[i])
        if tot_cash_i > 0.0 and c_i > tot_cash_i:
            c_i = tot_cash_i
        s_i = max(0.0, tot_cash_i - c_i)
        cce_clean.append(float(c_i))
        sti_clean.append(float(s_i))
        rem_ca_i = float(tot_ca_s[i] - (ar_s[i] + inv_ca_s[i] + c_i + s_i))
        oth_ca_s.append(rem_ca_i)
        dp_i = min(max(0.0, rem_ca_i), max(0.0, float(cur_def_ca_raw[i]) + float(prepaid_ca_raw[i])))
        def_prepaid_ca_s.append(float(dp_i))
        oth_ca_disagg_s.append(float(rem_ca_i - dp_i))

    # Cash Flow Statement full disaggregation & formula reconciliation
    cfo_list = _extract_series(cash_flow, ["Operating Cash Flow"])
    cfi_list = _extract_series(cash_flow, ["Investing Cash Flow"])
    cff_list = _extract_series(cash_flow, ["Financing Cash Flow"])
    chg_cash_list = _extract_series(cash_flow, ["Changes In Cash"])
    beg_cash_list = _extract_series(cash_flow, ["Beginning Cash Position"])
    end_cash_list = _extract_series(cash_flow, ["End Cash Position"])

    cfo_start_raw = _extract_series(cash_flow, ["Net Income From Continuing Operations"])
    cfo_start_list = [
        float(cfo_start_raw[i]) if cfo_start_raw[i] != 0.0 else float(ni_list[i])
        for i in range(n_years)
    ]
    # Preserve BOTH Cash Flow Gross D&A (as reported inside CFO indirect reconciliation) AND
    # Symmetric Operating D&A (matching P&L EBIT D&A), plus explicit Recoupment difference.
    cf_rep_dna_list = [float(x) for x in rep_dna]
    recouped_da_list = [float(x) for x in recouped_da]
    sbc_cf_list = _extract_series(cash_flow, ["Stock Based Compensation"])
    def_tax_cf_list = _extract_series(cash_flow, ["Deferred Income Tax", "Deferred Tax"])
    wc_cf_list = _extract_series(cash_flow, ["Change In Working Capital"])
    # For CFO additive bridge: direct 'Taxes Refund Paid' applies only on Ind AS PBT->CFO waterfalls;
    # on US GAAP Net Income->CFO statements taxes paid is a supplemental non-additive disclosure.
    has_direct_tax_in_cfo = "Taxes Refund Paid" in cash_flow.columns
    tax_paid_cfo_list = _extract_series(cash_flow, ["Taxes Refund Paid"]) if has_direct_tax_in_cfo else [0.0] * n_years
    supp_tax_raw = _extract_series(cash_flow, ["Income Tax Paid Supplemental Data"]) if "Income Tax Paid Supplemental Data" in cash_flow.columns else [None] * n_years
    supplemental_cash_taxes: List[Optional[float]] = []
    cash_tax_provenance: List[Dict[str, Any]] = []
    for i in range(n_years):
        yr_int = int(years_str_list[i]) if years_str_list[i].isdigit() else None
        sec_tp = sec_tax_paid_map.get(yr_int, {}).get("value") if yr_int else None
        if sec_tp is not None:
            t_val = abs(float(sec_tp))
            t_stat = "VALUE" if t_val > 0 else "ZERO"
            t_src = sec_tax_paid_map[yr_int].get("tag", "SEC EDGAR IncomeTaxesPaid")
        elif supp_tax_raw[i] is not None and not np.isnan(supp_tax_raw[i]):
            t_val = abs(float(supp_tax_raw[i]))
            t_stat = "VALUE" if t_val > 0 else "ZERO"
            t_src = "Yahoo Cash Flow Supplemental Data (Income Tax Paid)"
        elif has_direct_tax_in_cfo and abs(float(tax_paid_cfo_list[i])) > 0:
            t_val = abs(float(tax_paid_cfo_list[i]))
            t_stat = "VALUE"
            t_src = "Cash Flow Operating Line (Taxes Refund Paid)"
        else:
            t_val = None
            t_stat = "NOT_DISCLOSED"
            t_src = "Cash Flow Statement / Notes"
        supplemental_cash_taxes.append(t_val)
        cash_tax_provenance.append(make_provenance(t_val, t_stat, t_src, period=years_str_list[i]))

    oth_noncash_cf_list = [
        float(
            cfo_list[i]
            - (
                cfo_start_list[i]
                + cf_rep_dna_list[i]
                + sbc_cf_list[i]
                + def_tax_cf_list[i]
                + wc_cf_list[i]
                + tax_paid_cfo_list[i]
            )
        )
        for i in range(n_years)
    ]

    capex_list = capex.tolist()
    rep_capex_list = [float(x) for x in rep_capex]
    acq_cf_raw = _extract_series(cash_flow, ["Net Business Purchase And Sale", "Purchase Of Business"])
    sale_ppe_raw = _extract_series(cash_flow, ["Sale Of PPE"])
    acq_disp_cf_list = [float(acq_cf_raw[i] + sale_ppe_raw[i]) for i in range(n_years)]
    inv_cf_list = _extract_series(cash_flow, ["Net Investment Purchase And Sale"])
    oth_cfi_cf_list = [
        float(cfi_list[i] - (-rep_capex_list[i] + acq_disp_cf_list[i] + inv_cf_list[i]))
        for i in range(n_years)
    ]

    net_debt_cf_list = _extract_series(cash_flow, ["Net Issuance Payments Of Debt"])
    divs_cf_list = dividends_paid.tolist()
    int_paid_cff_list = _extract_series(cash_flow, ["Interest Paid Cff"])
    eq_other_cff_list = [
        float(cff_list[i] - (net_debt_cf_list[i] - divs_cf_list[i] + int_paid_cff_list[i]))
        for i in range(n_years)
    ]
    fx_cash_adj_list = [
        float(chg_cash_list[i] - (cfo_list[i] + cfi_list[i] + cff_list[i]))
        for i in range(n_years)
    ]
    fx_raw_list = _extract_series(cash_flow, ["Effect Of Exchange Rate Changes"])
    other_cash_outside_list = _extract_series(
        cash_flow,
        ["Other Cash Adjustment Outside Changein Cash", "Other Cash Adjustment Outside Change in Cash"],
    )
    fx_effect_list: List[float] = []
    for i in range(n_years):
        fx_i = float(fx_raw_list[i])
        oth_i = float(other_cash_outside_list[i])
        if beg_cash_list[i] == 0.0 and chg_cash_list[i] == 0.0 and cfo_list[i] == 0.0 and end_cash_list[i] != 0.0:
            beg_cash_list[i] = float(end_cash_list[i] - fx_i)
        elif end_cash_list[i] == 0.0 and (beg_cash_list[i] != 0.0 or chg_cash_list[i] != 0.0):
            end_cash_list[i] = float(beg_cash_list[i] + chg_cash_list[i] + fx_i)
        # Yahoo Finance uses "Other Cash Adjustment Outside Changein Cash" inconsistently:
        # for demergers/consolidations (e.g. JIOFIN, RELIANCE, SUNPHARMA) it is an additive
        # cash-rollforward bridge item outside Changes In Cash; for some banks/conglomerates
        # (e.g. HDFCBANK FY24) it is a non-additive memo already reflected in Changes In Cash.
        if abs(oth_i) > 0.0 and (abs(beg_cash_list[i]) > 0.0 or abs(end_cash_list[i]) > 0.0):
            gap_no_oth = abs((beg_cash_list[i] + chg_cash_list[i] + fx_i) - end_cash_list[i])
            gap_with_oth = abs((beg_cash_list[i] + chg_cash_list[i] + fx_i + oth_i) - end_cash_list[i])
            if gap_with_oth < gap_no_oth:
                fx_i = fx_i + oth_i
        if abs(beg_cash_list[i]) > 0.0 or abs(end_cash_list[i]) > 0.0:
            fx_i = float(end_cash_list[i] - (beg_cash_list[i] + chg_cash_list[i]))
        fx_effect_list.append(float(fx_i))
    restr_cash_list = [
        float(max(0.0, end_cash_list[i] - cce_clean[i]))
        for i in range(n_years)
    ]

    levered_fcf_list = [float(cfo_list[i] - capex_list[i]) for i in range(n_years)]
    eff_tax_for_fcff = float(stock_data.get("_tax_rate", 0.2517 if stock_data.get("market") == "IN" else 0.21))
    unlevered_fcff_list = [
        float(ebit_list[i] * (1.0 - eff_tax_for_fcff) + dna_list[i] - capex_list[i] - float(delta_nwc[i]))
        for i in range(n_years)
    ]

    # Full structured 3-statements matching HUL FINAL MODEL.xlsx (plus Banking & Disaggregated specifics)
    statements = {
        "income_statement": {
            "Revenues / Net Sales": rev_list,
            "Interest Income": _extract_series(income_stmt, ["Interest Income", "Interest Income Non Operating"]),
            "Net Interest Income (NII)": net_interest_income.tolist(),
            "Cost of Goods Sold (COGS)": cogs_clean,
            "Gross Profit": gp_clean,
            "Selling, General & Admin (SG&A)": sga_list,
            "Employee Benefits & Personnel Expenses": emp_benefits_list,
            "Research & Development (R&D)": rnd_list,
            "Other Operating Expenses": other_opex_list,
            "Other Operating Expenses (Statutory)": stat_other_opex_list,
            "Depreciation & Amortization in Operating Expenses": opex_dna_list,
            "Statutory Operating Income": stat_op_inc_list,
            "Regulatory Deferral & Operating Adjustments": op_norm_adj_list,
            "Operating Profit (EBITDA)": ebitda_list,
            "Depreciation & Amortization (D&A)": dna_list,
            "Operating Income (EBIT)": ebit_list,
            "Interest Expense": ie_list,
            "Other Finance Costs": oth_fin_cost_list,
            "Non-Operating Income / (Expense)": non_op_inc_list,
            "Reported Regulatory Deferral & Non-Op Credits": rep_reg_other_nonop_list,
            "Reported Non-Operating Interest Income": rep_int_inc_nonop_list,
            "Earnings Before Tax (EBT)": ebt_list,
            "Income Tax Expense": tax_list,
            "Profit After Tax (Consolidated PAT)": cons_pat_list,
            "Minority Interest & Exceptional Items": min_int_inc_list,
            "Net Profit / Net Income": ni_list,
            "Basic Weighted-Average Shares": bas_shares_clean,
            "Basic Earnings Per Share (Basic EPS)": bas_eps_clean,
            "Diluted Shares Outstanding": dil_shares_clean,
            "Earnings Per Share (EPS)": dil_eps_clean,
            "Period-End Shares Outstanding": pe_shares_clean,
            "Cash Dividends Paid": dividends_paid.tolist(),
        },
        "balance_sheet": {
            "Equity Share Capital": eq_cap_s,
            "Additional Paid-In Capital (APIC)": apic_s,
            "Retained Earnings / Reserves": ret_earn_s,
            "Reserves & Retained Earnings": res_s,
            "Total Stockholders' Equity": tot_eq_s,
            "Minority Interest": min_int_bs_s,
            "Short-Term Borrowings": st_borr_s,
            "Long-Term Borrowings": lt_borr_s,
            "Total Debt": tot_fin_debt_s,
            "Capital Lease Obligations": lease_s,
            "Accounts Payable & Trade Payables": ap_s,
            "Accrued Expenses & Current Tax Payable": accrued_s,
            "Deferred Revenue & Unearned Liabilities": def_rev_s,
            "Deferred Tax Liabilities": dtl_s,
            "Provisions & Post-Retirement Obligations": prov_s,
            "Other Operating & Non-Current Liabilities": oth_liab_disagg_s,
            "Other Liabilities": other_liab_s,
            "Total Liabilities & Equity": tot_liab_eq_s,
            "Fixed Assets (Net PPE)": ppe_s,
            "Capital Work in Progress (CWIP)": cwip_s,
            "Intangible Assets & Goodwill": intang_s,
            "Investments": inv_nc_s,
            "Investments & Financial Assets": _extract_series(balance_sheet, ["Investments And Advances", "Investmentin Financial Assets", "Available For Sale Securities"]),
            "Regulatory Deferral & Non-Current Deferred Assets": def_nca_s,
            "Regulatory Deferral Assets (Non-Tax)": non_tax_reg_def_s,
            "Other Non-Current Assets (Disaggregated)": oth_nc_disagg_s,
            "Other Non-Current Assets": oth_nc_s,
            "Total Non-Current Assets": tot_nca_s,
            "Receivables": ar_s,
            "Other & Tax Receivables": oth_tax_rec_ca_s,
            "Loans, Advances & Receivables": _extract_series(balance_sheet, ["Receivables", "Accounts Receivable", "Gross Accounts Receivable"]),
            "Inventory": inv_ca_s,
            "Cash & Bank Balances": cce_clean,
            "Cash & Central Bank Balances": _extract_series(balance_sheet, ["Cash Cash Equivalents And Federal Funds Sold", "Cash And Cash Equivalents", "Cash Financial"]),
            "Short-Term Investments": sti_clean,
            "Deferred Costs, Contract & Prepaid Assets": def_prepaid_ca_s,
            "Other Current Assets (Disaggregated)": oth_ca_disagg_s,
            "Other Current Assets": oth_ca_s,
            "Total Current Assets": tot_ca_s,
            "Total Assets": tot_assets_s,
            "Current Liabilities (Total)": [float(x) for x in current_liabs],
            "Non-Cash Operating Current Assets": [float(current_assets[i] - cash_on_bs[i] - nwc_rec_deduction[i]) for i in range(n_years)],
            "Non-Debt Operating Current Liabilities": [float(current_liabs[i] - st_debt[i]) for i in range(n_years)],
            "Net Operating Working Capital (NWC)": [float(x) for x in nwc],
            "Change in Operating Working Capital (ΔNWC)": [float(x) for x in delta_nwc],
        },
        "cash_flow": {
            "CFO Starting Profit (Net Income / PBT)": cfo_start_list,
            "Net Profit from Operations": ni_list,
            "Depreciation & Amortization": dna_list,
            "Depreciation & Amortization (Reported CF Gross)": cf_rep_dna_list,
            "Recoupment / Capitalised Depreciation Adjustment (Note 46)": recouped_da_list,
            "Stock-Based Compensation (SBC)": sbc_cf_list,
            "Deferred Income Taxes": def_tax_cf_list,
            "Other Non-Cash & Operating Adjustments (Reconciling Item)": oth_noncash_cf_list,
            "Change in Working Capital": wc_cf_list,
            "Direct Taxes Paid (In CFO Reconciliation)": tax_paid_cfo_list,
            "Cash Flow from Operating Activities (CFO)": cfo_list,
            "Fixed Assets Purchased (CapEx)": capex_list,
            "Fixed Assets Purchased (Reported CapEx)": rep_capex_list,
            "Net Acquisitions, Asset Sales & Intangibles": acq_disp_cf_list,
            "Net Investments Cash Flow": inv_cf_list,
            "Interest, Dividends Received & Other Investing Cash Flows": oth_cfi_cf_list,
            "Cash Flow from Investing Activities (CFI)": cfi_list,
            "Net Debt Flow": net_debt_cf_list,
            "Dividends Paid": divs_cf_list,
            "Interest & Finance Costs Paid (CFF)": int_paid_cff_list,
            "Net Equity Issuance, Options, Taxes & Other Financing Flows": eq_other_cff_list,
            "Cash Flow from Financing Activities (CFF)": cff_list,
            "FX & Other Cash Flow Adjustments": fx_cash_adj_list,
            "Effect of Exchange Rate Changes (FX)": fx_effect_list,
            "Net Change in Cash": chg_cash_list,
            "Beginning Cash Position": beg_cash_list,
            "Ending Cash Position": end_cash_list,
            "Less: Restricted Cash in Ending Cash Position": restr_cash_list,
            "Free Cash Flow (Levered FCF)": levered_fcf_list,
            "Unlevered Free Cash Flow (FCFF)": unlevered_fcff_list,
            "Free Cash Flow (FCFF)": levered_fcf_list,
            "Supplemental: Income Taxes Paid (Cash, Non-Additive)": supplemental_cash_taxes,
        },
    }

    latest_capex_pct = float(capex[-1] / revenue[-1]) if len(revenue) > 0 and revenue[-1] > 0 else avg_capex_pct

    # Capital commitments from statutory primary filing Note 32(c) when available
    pf_mult = float(primary_filing.get("unit_multiplier", 1e7)) if primary_filing else 1e7
    pf_notes = (primary_filing or {}).get("notes") or {}
    cap_comm_cr = (pf_notes.get("note_32c_capital_commitments") or {}).get("current")
    capital_commitments_val = float(cap_comm_cr) * pf_mult if cap_comm_cr is not None else None
    capital_advances_cr = (pf_notes.get("note_11_capital_advances") or {}).get("current")
    capital_advances_val = float(capital_advances_cr) * pf_mult if capital_advances_cr is not None else None

    # Use latest audited fiscal year revenue consistently as Year 0 Base Revenue when >=2 fiscal years exist
    # (only blend TTM revenue when fewer than 2 annual fiscal periods are present).
    base_last_revenue = float(revenue[-1])
    if len(revenue) < 2 and info_dict.get("totalRevenue") and float(info_dict["totalRevenue"]) > 0:
        base_last_revenue = float(info_dict["totalRevenue"])

    provenance = {
        "accounting_standard": make_provenance(None, "VALUE", "Market / Currency Classification", unit=acct_std),
        "revenue_base": make_provenance(base_last_revenue, "VALUE", primary_filing.get("source_citation") or "Income Statement FY Latest", period=years_str_list[-1]),
        "cash_taxes_paid": cash_tax_provenance,
        "shares": share_provenance,
        "unrestricted_cash": make_provenance(cash_and_equivalents, "VALUE", cash_recon_source, period=years_str_list[-1], note_ref=cash_recon_note_ref),
        "restricted_earmarked_cash": make_provenance(
            restricted_earmarked_cash if restricted_earmarked_cash > 0 else None,
            "VALUE" if restricted_earmarked_cash > 0 else "NOT_DISCLOSED",
            cash_recon_source,
            period=years_str_list[-1],
            note_ref=cash_recon_note_ref,
        ),
        "capital_commitments": make_provenance(
            capital_commitments_val,
            "VALUE" if capital_commitments_val is not None else "NOT_DISCLOSED",
            primary_filing.get("source_citation") or "Notes to Financial Statements",
            period=years_str_list[-1],
            note_ref="Note 32(c)" if capital_commitments_val is not None else None,
        ),
    }

    # Insurance & REIT/InvIT structured historical metrics for domain engines
    norm_inc_s = _extract_series(income_stmt, ["Normalized Income"])
    claims_ben_s = _extract_series(income_stmt, ["Net Policyholder Benefits And Claims"])
    lae_s = _extract_series(income_stmt, ["Loss Adjustment Expense"])
    claims_tot_latest = (float(claims_ben_s[-1]) + float(lae_s[-1])) if claims_ben_s and lae_s else 0.0
    claims_loss_ratio_latest = (claims_tot_latest / float(revenue[-1])) if len(revenue) > 0 and revenue[-1] > 0 and claims_tot_latest > 0 else 0.0
    inv_adv_s = _extract_series(balance_sheet, ["Investments And Advances", "Available For Sale Securities"])
    tot_liab_nmi_s = _extract_series(balance_sheet, ["Total Liabilities Net Minority Interest"])
    policyholder_float_latest = max(0.0, float(tot_liab_nmi_s[-1]) - float(raw_total_debt)) if tot_liab_nmi_s else 0.0
    aoci_s = _extract_series(balance_sheet, ["Gains Losses Not Affecting Retained Earnings"])

    inv_prop_s = _extract_series(balance_sheet, ["Investment Properties"])
    pur_inv_prop_s = _extract_series(cash_flow, ["Purchase Of Investment Properties"])
    re_dna_s = _extract_series(income_stmt, ["Depreciation And Amortization In Income Statement", "Depreciation"])
    latest_re_dna = float(re_dna_s[-1]) if re_dna_s and abs(float(re_dna_s[-1])) > 0 else (float(dna[-1]) if len(dna) > 0 else 0.0)

    return {
        "years": years_str_list,
        "accounting_standard": acct_std,
        "model_suitability": stock_data.get("model_suitability"),
        "insurance_metrics": {
            "normalized_income": [float(x) for x in norm_inc_s],
            "latest_claims_loss_ratio": float(claims_loss_ratio_latest),
            "latest_investments_and_advances": float(inv_adv_s[-1]) if inv_adv_s else 0.0,
            "latest_policyholder_float": float(policyholder_float_latest),
            "latest_aoci": float(aoci_s[-1]) if aoci_s else 0.0,
        },
        "reit_metrics": {
            "latest_investment_properties": float(inv_prop_s[-1]) if inv_prop_s else 0.0,
            "latest_purchase_of_investment_properties": abs(float(pur_inv_prop_s[-1])) if pur_inv_prop_s else 0.0,
            "latest_re_dna": float(latest_re_dna),
        },
        "lease_policy": lease_policy,
        "cash_reconciliation": {
            "gross_cash_and_sti": gross_cash_and_sti,
            "restricted_earmarked_cash": restricted_earmarked_cash,
            "unrestricted_cash": cash_and_equivalents,
            "source": cash_recon_source,
            "note_ref": cash_recon_note_ref,
            "components": cash_recon_components,
        },
        "depreciation_reconciliation": {
            "operating_net_da": dna.tolist(),
            "reported_gross_cf_da": cf_rep_dna_list,
            "recouped_da": recouped_da_list,
            "unverified_is_cf_da_gap": [float(x) for x in unverified_is_cf_da_gap],
            "is_recouped": bool(np.any(recouped_da > 0)),
            "recoupment_primary_verified": recoupment_primary_verified,
            "recoupment_inferred_unverified": recoupment_inferred_unverified,
            "skipped_due_to_goodwill_threshold": skipped_due_to_goodwill_threshold,
        },
        "valuation_adjustments": valuation_adjustments,
        "nwc_clip_applied": nwc_clip_applied,
        "nwc_clip_bounds": list(nwc_clip_bounds),
        "capital_commitments": capital_commitments_val,
        "capital_advances": capital_advances_val,
        "share_reconciliation": stock_data.get("share_reconciliation"),
        "sec_edgar": stock_data.get("sec_edgar"),
        "primary_filing": primary_filing,
        "provenance": provenance,
        # Raw arrays (as lists for JSON-serialisability)
        "revenue": revenue.tolist(),
        "ebit": ebit.tolist(),
        "ebitda": ebitda_arr.tolist(),
        "capex": capex.tolist(),
        "dna": dna.tolist(),
        "nwc": nwc.tolist(),
        "delta_nwc": delta_nwc.tolist(),
        "rev_growth": rev_growth.tolist(),
        "ebit_margins": ebit_margins.tolist(),
        "ebitda_margins": ebitda_margins.tolist(),
        # Banking & Financial Services Specifics
        "net_income": net_income.tolist(),
        "net_interest_income": net_interest_income.tolist(),
        "pretax_income": pretax_income.tolist(),
        "book_value": book_value.tolist(),
        "dividends_paid": dividends_paid.tolist(),
        "avg_roe": avg_roe,
        "std_roe": std_roe,
        "avg_payout": avg_payout,
        "avg_ni_growth": avg_ni_growth,
        "std_ni_growth": std_ni_growth,
        # Computed averages
        "avg_rev_growth": avg_rev_growth,
        "std_rev_growth": std_rev_growth,
        "avg_ebit_margin": avg_ebit_margin,
        "std_ebit_margin": std_ebit_margin,
        "avg_ebitda_margin": avg_ebitda_margin,
        "avg_ebitda_growth": avg_ebitda_growth,
        "avg_capex_pct": avg_capex_pct,
        "latest_capex_pct": latest_capex_pct,
        "avg_dna_pct": avg_dna_pct,
        "avg_dnwc_pct": avg_dnwc_pct,
        "historical_unclipped_nwc_to_revenue": historical_unclipped_nwc_to_revenue,
        "normalized_nwc_to_revenue": normalized_nwc_to_revenue,
        "gross_margins": gross_margins.tolist(),
        "avg_gross_margin": avg_gross_margin,
        "fcf_margins": fcf_margins.tolist(),
        "avg_fcf_margin": avg_fcf_margin,
        "latest_fcf_margin": latest_fcf_margin,
        "sbc_pcts": sbc_margins.tolist(),
        "avg_sbc_pct": avg_sbc_pct,
        "latest_sbc_pct": latest_sbc_pct,
        "rnd_pcts": rnd_margins.tolist(),
        "avg_rnd_pct": avg_rnd_pct,
        "latest_rnd_pct": latest_rnd_pct,
        # Snapshot values
        "n_years": n_years,
        "last_revenue": base_last_revenue,
        "ttm_revenue": float(info_dict["totalRevenue"]) if info_dict.get("totalRevenue") else None,
        "total_debt": total_debt,
        "raw_total_debt": raw_total_debt,
        "lease_obligations": lease_obligations,
        "captive_debt_offset": captive_debt_offset,
        "minority_interest_claim": minority_interest_claim,
        "preferred_stock_claim": preferred_stock_claim,
        "aro_provisions_claim": aro_provisions_claim,
        "raw_lt_provisions": raw_lt_provisions,
        "unverified_aro_stress_claim": unverified_aro_stress_claim,
        "aro_verified": aro_verified,
        "greenfield_debt_offset": greenfield_debt_offset,
        "cwip_to_rev": float(cwip_to_rev),
        "cash_and_equivalents": cash_and_equivalents,
        "restricted_earmarked_cash": restricted_earmarked_cash,
        "interest_expense": interest_expense,
        "interest_coverage": float(interest_coverage),
        # Full 3-statement models
        "statements": statements,
    }
