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

import logging
import time
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd
import yfinance as yf

from .classification_overrides import (
    CAPTIVE_FINANCE_SYMBOLS,
    DOWNSTREAM_REFINING_SYMBOLS,
    KNOWN_BALANCE_SHEET_FINANCIAL_SYMBOLS,
    KNOWN_CYCLICAL_SYMBOLS,
    KNOWN_EXTRACTIVE_SYMBOLS,
    NBFC_CONSOLIDATING_SYMBOLS,
    NON_CYCLICAL_CONGLOMERATE_SYMBOLS,
    USD_REPORTING_INDIAN_ADR_SYMBOLS,
    get_override_entry,
    resolve_sector_and_industry,
)

logger = logging.getLogger(__name__)


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
                        
                        # Only clamp if raw beta is negative or implausibly close to zero (<= 0.15),
                        # or if an Indian PSU/extractive/cyclical commodity company has an artificially low Nifty correlation
                        eff_raw = calc_raw
                        is_ext_b, is_cyc_b = classify_sector_dynamics(sector, industry, ticker)
                        if calc_raw <= 0.15 or (market.upper() == "IN" and (is_ext_b or is_cyc_b) and calc_raw < 0.85):
                            beta_u = max(0.85 if (is_ext_b or is_cyc_b) else 0.45, get_industry_unlevered_beta(sector, industry))
                            eff_de = min(2.5, max(0.0, float(de_ratio))) if de_ratio is not None else 0.5
                            relev_b = beta_u * (1.0 + (1.0 - tax_rate) * min(1.5, eff_de))
                            if calc_raw <= 0.15:
                                eff_raw = relev_b
                                beta_clamped = True
                                clamp_reason = f"Raw regression beta ({calc_raw:.2f}) was near-zero; substituted bottom-up unlevered beta {beta_u:.2f} (relevered: {eff_raw:.2f})."
                            elif relev_b > calc_raw:
                                eff_raw = relev_b
                                beta_clamped = True
                                clamp_reason = f"Raw regression beta ({calc_raw:.2f}) understated cyclical/commodity risk; anchored to bottom-up industry beta {beta_u:.2f} (relevered: {eff_raw:.2f})."
                        elif calc_raw > 2.80:
                            eff_raw = 2.80
                            beta_clamped = True
                            clamp_reason = f"Raw regression beta ({calc_raw:.2f}) was exceptionally volatile; capped raw beta to 2.80."

                        blume_beta = (2.0 / 3.0) * eff_raw + (1.0 / 3.0) * 1.0

                        note = (
                            f"Blume-adjusted 2Y weekly regression vs {benchmark} "
                            f"(raw: {calc_raw:.2f} → adj: {blume_beta:.2f})"
                        )
                        if clamp_reason:
                            note = f"{clamp_reason} {note}"

                        return {
                            "beta": float(blume_beta),
                            "raw_beta": float(calc_raw),
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
    Classifies company into (is_extractive, is_cyclical).
    - is_extractive: Oil & Gas exploration/drilling/upstream/integrated, Thermal Coal, Mining & Minerals.
      Assets suffer from physical depletion; CapEx is required just to sustain reserves and
      perpetual volume growth cannot exceed physical/transition constraints.
    - is_cyclical: Extractive PLUS Basic Materials (Steel, Aluminum, Metals, Commodity Chemicals, Refining).
      Earnings fluctuate with global commodity pricing; margins must mean-revert to multi-year cycle averages.
    """
    sec = sector or ""
    ind = industry or ""
    sym_clean = (symbol or "").replace(".NS", "").replace(".BO", "").strip().upper()
    comp_name = (name or "").lower()
    text = f"{sec} {ind} {comp_name}".lower()

    if sym_clean in NON_CYCLICAL_CONGLOMERATE_SYMBOLS:
        return False, False
    if "specialty chemicals" in text:
        return False, False

    if sym_clean in KNOWN_EXTRACTIVE_SYMBOLS:
        return True, True
    if sym_clean in KNOWN_CYCLICAL_SYMBOLS:
        return False, True

    extractive_keywords = [
        "oil & gas e&p", "oil & gas exploration", "oil & gas drilling", "oil & gas integrated",
        "thermal coal", "coal india", "coking coal", "integrated oil", "drilling",
        "exploration & production", "upstream", "crude", "mining", "gold", "silver", "copper",
        "other industrial metals & mining", "other precious metals & mining",
        "oil & natural gas", "oil india", "mineral development", "iron ore",
    ]
    is_extractive = any(k in text for k in extractive_keywords)
    if not is_extractive and ("oil & gas" in text or "petroleum" in text or "coal" in text) and "refining & marketing" not in text and "equipment" not in text and "midstream" not in text and "gas distribution" not in text and "utilities" not in text:
        if any(w in text for w in ["exploration", "natural gas corp", "oil india", "integrated", "production", "upstream", "coal"]):
            is_extractive = True

    cyclical_keywords = extractive_keywords + [
        "steel", "aluminum", "aluminium", "metals", "commodity chemicals",
        "agricultural inputs", "iron", "fertilizer", "refining", "petroleum", "paper & forest", "lumber",
        "building materials", "cement"
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

    # Fast pre-check for known ETFs, Commodity ETFs, Mutual Funds, REITs & InvITs
    pre_excl, _, pre_msg = is_non_dcf_instrument(symbol=ticker)
    if pre_excl:
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

    if not info.get("currency"):
        info["currency"] = fast_currency or ("INR" if market.upper() == "IN" else "USD")

    # Gatekeeper: reject ETFs, Commodity Funds, Mutual Funds, Indices, REITs, InvITs with a clear domain message
    is_excl, _, excl_msg = is_non_dcf_instrument(
        symbol=yf_ticker,
        name=info.get("longName") or info.get("shortName"),
        quote_type=info.get("quoteType"),
        sector=info.get("sector"),
        industry=info.get("industry"),
    )
    if is_excl:
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
        # and foreign-currency ADRs trading in USD (e.g. NVO in DKK, TSM in TWD)
        # when cloud IP rate-limiting blocks Yahoo metadata endpoints
        if not fin_currency or fin_currency == trade_currency:
            ovr_entry = get_override_entry(yf_ticker)
            if ovr_entry and ovr_entry.reporting_currency and ovr_entry.reporting_currency != trade_currency:
                fin_currency = ovr_entry.reporting_currency
                info["financialCurrency"] = fin_currency
            elif trade_currency == "INR" and raw_stmt_rev and market_cap > 50e9:
                raw_rev_ratio = raw_stmt_rev / market_cap
                sym_base = yf_ticker.replace(".NS", "").replace(".BO", "").upper()
                if 0.001 <= raw_rev_ratio <= 0.022 and (sym_base in USD_REPORTING_INDIAN_ADR_SYMBOLS or raw_rev_ratio < 0.012):
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
                        income_stmt = income_stmt * fx_rate
                    if not balance_sheet.empty:
                        balance_sheet = balance_sheet * fx_rate
                    if not cash_flow.empty:
                        cash_flow = cash_flow * fx_rate
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
                    income_stmt = income_stmt * scale_multiplier
                    balance_sheet = balance_sheet * scale_multiplier
                    cash_flow = cash_flow * scale_multiplier
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

    is_extractive, is_cyclical = classify_sector_dynamics(sector, industry, yf_ticker, company_name)
    name_lower = (company_name or "").lower()
    clean_sym = yf_ticker.replace(".NS", "").replace(".BO", "").upper()

    sector, industry = resolve_sector_and_industry(
        yf_ticker, company_name, sector, industry, is_extractive, is_cyclical
    )

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

    # Banking & Balance-Sheet Financial Services Detection (Banks, NBFCs, Insurance, Lending Institutions)
    # Note: Capital-light fee-based financial infrastructure (Exchanges like MCX/BSE, Depositories like CDSL,
    # RTAs like CAMS/KFINTECH, Rating Agencies like CRISIL, AMCs, Discount Brokers like GROWW/ANGELONE)
    # are routed to Standard FCFF DCF.
    is_cap_light_fin = is_capital_light_financial(yf_ticker, company_name, sector, industry)
    is_financial = False
    sec_lower = (sector or "").lower()
    ind_lower = (industry or "").lower()

    if is_cap_light_fin:
        is_financial = False
    # 1. Known Balance-Sheet Lender / Bank / Insurer Check
    elif clean_sym in KNOWN_BALANCE_SHEET_FINANCIAL_SYMBOLS:
        is_financial = True
    # 2. Sector / Industry Metadata (only when not explicitly a non-financial operating sector)
    elif any(k in sec_lower for k in ["financial", "banking"]):
        is_financial = True
    elif any(kw in ind_lower for kw in ["bank", "credit services", "insurance", "mortgage finance", "consumer finance", "specialty finance", "capital markets"]):
        is_financial = True
    # 3. Company Name or Symbol Keywords (ONLY when sector is missing or explicitly Financial/Banking)
    # Technology/software companies (e.g. OFSS - Oracle Financial Services Software), healthcare,
    # or industrials must NEVER be classified as banks just because their corporate name contains 'financial'.
    elif (not sector or any(k in sec_lower for k in ["financial", "banking"])) and (
        any(kw in name_lower for kw in [
            "bank", "housing finance", "finance", "financial", "financ", "credit",
            "development agency", "energy development agency", "insurance",
            "finvest", "leasing", "fincorp", "fino"
        ]) or any(kw in clean_sym.lower() for kw in ["financ", "bank", "hsgfin", "fincorp", "finvest"])
    ):
        is_financial = True
    # 4. Financial Statement Structural Signals (ONLY when sector/industry metadata is missing from Yahoo Finance)
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

    result = {
        "ticker": yf_ticker,
        "name": company_name,
        "market": market,
        "sector": sector,
        "industry": industry,
        "is_financial": is_financial,
        "is_capital_light_financial": is_cap_light_fin,
        "redirect_note": redirect_note,
        "is_extractive": is_extractive,
        "is_cyclical": is_cyclical,
        "current_price": float(current_price),
        "shares_outstanding": float(shares_out),
        "market_cap": market_cap,
        "beta": float(beta_info["beta"]),
        "raw_beta": float(beta_info["raw_beta"]),
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
    # 3B – Drop years with missing Revenue or EBIT (or Net Income for Banks)
    # ------------------------------------------------------------------
    is_financial = stock_data.get("is_financial", False)
    cols_to_check = ["Total Revenue"] if is_financial else ["Total Revenue", "EBIT"]

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

    raw_dna = safe_get(cash_flow, "Depreciation And Amortization")[::-1]
    dna = np.where(raw_dna < 0, -raw_dna, raw_dna)  # explicit positive
    if not np.any(dna):
        # Fallback to income statement Reconciled Depreciation (e.g. XOM, FCX)
        inc_dna = safe_get(income_stmt, "Depreciation And Amortization", default=0)[::-1]
        dna = np.where(inc_dna < 0, -inc_dna, inc_dna)

    cfo_arr = safe_get(cash_flow, "Operating Cash Flow", default=0)[::-1]

    ebit = safe_get(income_stmt, "EBIT")[::-1].copy()
    if not is_financial:
        # In Yahoo Finance, 'EBIT' is Pretax Income + Interest Expense, which includes one-off
        # non-operating items, goodwill/asset impairments, restructuring, and divestiture gains/losses
        # (e.g. DNUT -$447.5M goodwill impairment, JACK -$236M impairment, SBUX -$892M restructuring,
        # CVS -$5.24B special charges, or >85% spin-off gains).
        # 'Operating Income' (Gross Profit - Operating Expense) is recurring GAAP Operating Profit.
        # Extract Normalized EBITDA (or recurring Operating Income + D&A)
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

        if "Operating Income" in income_stmt.columns:
            op_inc = safe_get(income_stmt, "Operating Income")[::-1]
            for idx in range(len(ebit)):
                if op_inc[idx] > ebit[idx]:
                    # EBIT was dragged down below Operating Income by non-operating impairments/losses
                    # (e.g. DNUT -$447.5M goodwill impairment, JACK -$236M, SBUX -$892M, CVS -$5.24B)
                    ebit[idx] = op_inc[idx]
                elif op_inc[idx] < 0 and ebit[idx] > 0:
                    # Non-operating gain (e.g. BYND +$466M debt extinguishment gain) flipped negative
                    # operating income into positive GAAP EBIT
                    ebit[idx] = op_inc[idx]
                elif revenue[idx] > 0 and (ebit[idx] / revenue[idx]) > 0.85:
                    # One-off spin-off/divestiture gain (>85% of revenue)
                    ebit[idx] = op_inc[idx]
                elif op_inc[idx] > 0 and ebit[idx] > op_inc[idx] * 1.30:
                    # Large non-operating divestiture gain (>30% above operating income)
                    ebit[idx] = op_inc[idx]
                elif norm_ebitda[idx] != 0 and (ebit[idx] + dna[idx]) > norm_ebitda[idx] * 1.15:
                    # EBIT + D&A exceeds Normalized EBITDA by >15% due to non-operating gains
                    ebit[idx] = op_inc[idx]

        # Build clean EBITDA array: do not let raw_ebitda override norm_ebitda when raw_ebitda is
        # inflated by non-operating gains (e.g. BYND debt-extinguishment gain)
        clean_yf_ebitda = np.where(
            (norm_ebitda != 0) & ((norm_ebitda < 0) | (raw_ebitda > norm_ebitda * 1.15)),
            norm_ebitda,
            np.maximum(norm_ebitda, raw_ebitda),
        )
        ebitda_arr = np.maximum(ebit + dna, clean_yf_ebitda)

        # Check for LBO / acquisition intangible amortization & one-off special charges distorting GAAP EBIT
        # when Normalized EBITDA and Operating Cash Flow are consistently positive (e.g. DNUT)
        gw_intang_arr = (
            safe_get(balance_sheet, "Goodwill And Other Intangible Assets", default=0)[::-1]
            if "Goodwill And Other Intangible Assets" in balance_sheet.columns
            else safe_get(balance_sheet, "Goodwill", default=0)[::-1]
        )
        tot_assets_arr = safe_get(balance_sheet, "Total Assets", default=0)[::-1]

        for idx in range(len(ebit)):
            rev_i = revenue[idx]
            if rev_i <= 0:
                continue
            ebitda_i = ebitda_arr[idx]
            # 1) If Operating Income itself included one-off special charges (making ebit + dna < 75% of Normalized EBITDA)
            if norm_ebitda[idx] > 0 and (ebit[idx] + dna[idx]) < 0.75 * norm_ebitda[idx]:
                ebit[idx] = norm_ebitda[idx] - dna[idx]

            # 2) If heavy non-cash acquisition intangible amortization or store-closure D&A (dna > 6.5% of rev
            #    or Goodwill+Intangibles > 30% of assets) pushes GAAP EBIT <= 2.5% of revenue despite healthy
            #    positive Normalized EBITDA (>= 5.5% of revenue) and positive Operating Cash Flow:
            gw_ratio = (gw_intang_arr[idx] / tot_assets_arr[idx]) if tot_assets_arr[idx] > 0 else 0.0
            if (
                ebitda_i >= 0.055 * rev_i
                and cfo_arr[idx] > 0
                and ebit[idx] < 0.025 * rev_i
                and (dna[idx] > 0.065 * rev_i or gw_ratio > 0.30 or dna[idx] > capex[idx] * 1.10)
            ):
                econ_dna_i = min(dna[idx], rev_i * 0.042)
                ebit[idx] = max(ebit[idx], ebitda_i - econ_dna_i)
                dna[idx] = econ_dna_i
                # Align historical expansion/restructuring CapEx with maintenance D&A when adjusting for
                # non-cash intangible amortization / store restructuring so CapEx - D&A is not double-penalized
                if capex[idx] > econ_dna_i * 1.05:
                    capex[idx] = econ_dna_i * 1.02
    else:
        ebitda_arr = ebit + dna

    # Banking & Financial Services specific metrics
    net_income = safe_get(income_stmt, "Net Income")[::-1]
    net_interest_income = safe_get(income_stmt, "Net Interest Income")[::-1]
    pretax_income = safe_get(income_stmt, "Pretax Income")[::-1]
    book_value = safe_get(balance_sheet, "Stockholders Equity")[::-1]
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

    # Exclude captive finance / consolidated NBFC customer loan receivables above normal trade DSO (22% of rev)
    # from operating Current Assets ONLY for verified industrial conglomerates with captive finance arms
    sym_clean_m = str(stock_data.get("ticker") or "").replace(".NS", "").replace(".BO", "").strip().upper()
    has_captive_arm = (
        sym_clean_m in CAPTIVE_FINANCE_SYMBOLS
        or "Loans Receivable" in balance_sheet.columns
        or "Finance Lease Receivables" in balance_sheet.columns
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
    ebitda_margins = ebitda_arr / np.where(revenue != 0, revenue, 1.0)
    if stock_data.get("is_capital_light_financial", False):
        # Capital-light financial infrastructure (exchanges, AMCs, depositories) often include
        # treasury yield in reported EBIT; cap operating margin at 75% for sustainable FCFF.
        ebit_margins = np.clip(ebit_margins, -0.50, 0.75)

    avg_rev_growth = float(np.mean(rev_growth))
    std_rev_growth = float(np.std(rev_growth, ddof=1)) if len(rev_growth) > 1 else 0.05
    avg_ebit_margin = float(np.mean(ebit_margins))
    std_ebit_margin = float(np.std(ebit_margins, ddof=1)) if len(ebit_margins) > 1 else 0.02
    avg_ebitda_margin = float(np.mean(ebitda_margins))
    if len(ebitda_arr) > 1 and np.all(ebitda_arr > 0):
        avg_ebitda_growth = float(np.mean(np.diff(ebitda_arr) / ebitda_arr[:-1]))
    else:
        avg_ebitda_growth = avg_rev_growth

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

    # Gross Profit, Cash-Flow FCF (CFO - CapEx), and Stock-Based Compensation (SBC) metrics
    gross_profit_arr = safe_get(income_stmt, "Gross Profit", default=0)[::-1]
    if not np.any(gross_profit_arr) and "Cost Of Revenue" in income_stmt.columns:
        cor_arr = safe_get(income_stmt, "Cost Of Revenue", default=0)[::-1]
        gross_profit_arr = np.where(cor_arr > 0, revenue - cor_arr, 0.0)
    gross_margins = gross_profit_arr / np.where(revenue != 0, revenue, 1.0)
    avg_gross_margin = float(np.mean(gross_margins)) if np.any(gross_profit_arr) else 0.0

    fcf_arr = cfo_arr - capex
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
            ttm_fcf_m = float(ttm_fcf) / float(ttm_rev)
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
    
    nwc_to_rev = nwc / np.where(revenue != 0, revenue, 1.0)
    normalized_nwc_to_revenue = float(np.mean(nwc_to_rev))
    if stock_data.get("is_capital_light_financial", False):
        # Exchanges (MCX, BSE, IEX), depositories (CDSL), and brokers (ANGELONE) hold client
        # clearing/settlement margin float in Current Assets & Liabilities. Clamp NWC/Rev to ±5%.
        normalized_nwc_to_revenue = float(np.clip(normalized_nwc_to_revenue, -0.05, 0.05))
    else:
        # Bound steady-state NWC/Revenue within [-8%, +15%] so extreme upfront deferred-revenue
        # float (e.g. -40% in SaaS) or one-off working capital spikes do not distort perpetual UFCF.
        normalized_nwc_to_revenue = float(np.clip(normalized_nwc_to_revenue, -0.08, 0.15))

    # Total debt and cash (most recent year – index [0] is newest before reversal)
    raw_total_debt = float(safe_get(balance_sheet, "Total Debt")[0])  # newest row
    total_debt = raw_total_debt

    # For the EV-to-Equity bridge, cash MUST include marketable securities / short-term investments
    cash_and_equivalents = float(cash_on_bs[-1]) if len(cash_on_bs) > 0 else 0.0

    # 1. Exclude ASC 842 / IFRS 16 / Ind AS 116 Operating Lease Liabilities ('Capital Lease Obligations')
    # from Total Debt in the EV-to-Equity bridge and WACC weights.
    # Because operating lease rent is already expensed inside Operating Expense (reducing EBIT & NOPAT),
    # subtracting capitalized lease liabilities in the EV bridge double-counts lease obligations
    # (e.g. DNUT $447M, DG $11.1B, SBUX $10.5B, CVS $15.4B, JACK $1.42B).
    lease_obligations = 0.0
    if not is_financial and total_debt > 0:
        if "Capital Lease Obligations" in balance_sheet.columns:
            lease_obligations = float(safe_get(balance_sheet, "Capital Lease Obligations", default=0.0)[0])
        else:
            lt_lease = float(safe_get(balance_sheet, "Long Term Capital Lease Obligation", default=0.0)[0]) if "Long Term Capital Lease Obligation" in balance_sheet.columns else 0.0
            st_lease = float(safe_get(balance_sheet, "Current Capital Lease Obligation", default=0.0)[0]) if "Current Capital Lease Obligation" in balance_sheet.columns else 0.0
            lease_obligations = lt_lease + st_lease
        if lease_obligations > 0 and total_debt > lease_obligations:
            total_debt = max(0.0, total_debt - lease_obligations)

    # 2. Captive financing & consolidated NBFC receivables (e.g. John Deere Credit, Caterpillar Financial,
    # HPE Financial Services, Grasim's consolidated Aditya Birla Capital NBFC loan book, L&T Finance)
    # Netting non-operating financial loan/lease receivables against total debt isolates corporate operating debt.
    latest_rev = float(revenue[-1]) if len(revenue) > 0 else 0.0
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
        # Also check if consolidated customer financing loans sit inside total Receivables (above 20% trade DSO)
        latest_excess_rec = float(excess_fin_rec_series[-1]) if len(excess_fin_rec_series) > 0 else 0.0
        total_captive_offset = max(captive_rec, latest_excess_rec)

        # For conglomerates consolidating an NBFC / financial services subsidiary (e.g. Grasim consolidating
        # Aditya Birla Capital's ₹1.21T financial assets + ₹469.5B NBFC receivables alongside ₹1.90T NBFC debt),
        # include 'Investmentin Financial Assets' when Total Debt > 70% of Revenue
        if sym_clean_m in NBFC_CONSOLIDATING_SYMBOLS and total_debt > 0.70 * latest_rev and "Investmentin Financial Assets" in balance_sheet.columns:
            fin_inv_assets = float(safe_get(balance_sheet, "Investmentin Financial Assets", default=0.0)[0])
            if fin_inv_assets > 0.25 * total_debt:
                total_captive_offset += fin_inv_assets

        if total_captive_offset > 0.15 * latest_rev:
            offset_applied = min(total_debt * 0.85, total_captive_offset)
            sym = stock_data.get("ticker", "")
            logger.info(
                "Detected captive/NBFC financing receivables/assets of %.2f. "
                "Netting %.2f against total debt (%.2f -> %.2f) to isolate operating debt for %s.",
                total_captive_offset, offset_applied, total_debt, total_debt - offset_applied, sym
            )
            total_debt = max(0.0, total_debt - offset_applied)

    # 3. Consolidated Minority Interest (Noncontrolling Interest), Extractive ARO, & Uncommissioned CWIP
    # When a parent consolidates 100% of partially-owned subsidiaries' EBIT/Revenue (e.g. ONGC consolidating HPCL/MRPL,
    # Vedanta consolidating Hindustan Zinc), the minority shareholders' claim must be deducted in the EV-to-Equity bridge.
    # For extractive oil/gas/mining firms (ONGC, OIL, COALINDIA, VEDL), statutory Long Term Provisions represent
    # Well Decommissioning / Asset Retirement Obligations (ARO) & Mine Closure liabilities against which cash is earmarked.
    cwip_to_rev = 0.0
    if not is_financial and latest_rev > 0:
        cwip_val = (
            max(0.0, float(safe_get(balance_sheet, "Construction In Progress", default=0.0)[0]))
            if "Construction In Progress" in balance_sheet.columns
            else 0.0
        )
        cwip_to_rev = cwip_val / latest_rev

        bs_minority = (
            max(0.0, float(safe_get(balance_sheet, "Minority Interest", default=0.0)[0]))
            if "Minority Interest" in balance_sheet.columns
            else 0.0
        )
        if bs_minority > 0.02 * latest_rev:
            minority_claim = bs_minority * 0.50 if bs_minority > 0.20 * latest_rev else bs_minority
            total_debt += minority_claim

        if stock_data.get("is_extractive", False) and "Long Term Provisions" in balance_sheet.columns:
            lt_provisions = max(0.0, float(safe_get(balance_sheet, "Long Term Provisions", default=0.0)[0]))
            if lt_provisions > 0.05 * latest_rev:
                total_debt += 0.75 * lt_provisions

        # When a company carries massive uncommissioned greenfield Construction In Progress (CWIP > 50% of revenue,
        # e.g. OIL.NS's ₹38,103 Cr Numaligarh Refinery expansion on ₹33,943 Cr revenue) that generates zero current
        # EBIT, plus liquid Available For Sale Securities (e.g. OIL.NS's ₹11,331 Cr listed IOCL shares), do not
        # penalize Equity Value for the project debt funding uncommissioned CWIP & liquid AFS holdings.
        if cwip_to_rev > 0.50 and total_debt > 0:
            afs_val = (
                max(0.0, float(safe_get(balance_sheet, "Available For Sale Securities", default=0.0)[0]))
                if "Available For Sale Securities" in balance_sheet.columns
                else 0.0
            )
            cwip_offset = 0.65 * max(0.0, cwip_val - 0.20 * latest_rev) + 0.85 * afs_val
            total_debt = max(0.10 * raw_total_debt, total_debt - cwip_offset)
        elif (
            not stock_data.get("is_extractive", False)
            and avg_capex_pct > 2.2 * avg_dna_pct
            and total_debt > 0.45 * latest_rev
        ):
            # Greenfield Infrastructure Project Debt Alignment (e.g. ADANIENT Airports/Solar/Roads, ADANIGREEN Khavda Solar):
            # When a company is in a massive multi-year greenfield CapEx buildout (CapEx > 2.2x D&A) funded by project debt,
            # newly built PPE, CWIP, and concession intangibles are not yet generating steady-state EBIT (<8.5% yield on assets).
            # Netting the project debt associated with pre-ramp greenfield capital isolates debt on commissioned operations.
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
            greenfield_capital = cwip_val + 0.85 * recent_net_capex
            cur_ebit_val = float(ebit[-1]) if len(ebit) > 0 else 0.0
            if (
                infra_asset_base > 0
                and (cur_ebit_val / infra_asset_base) < 0.085
                and greenfield_capital > 0.35 * total_debt
            ):
                gf_offset = min(total_debt * 0.82, greenfield_capital * 0.85)
                total_debt = max(0.15 * raw_total_debt, total_debt - gf_offset)


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
        present = [c for c in col_candidates if c in df.columns]
        if present:
            sub = df[present].apply(pd.to_numeric, errors="coerce")
            series = sub.bfill(axis=1).iloc[:, 0].fillna(default).values[::-1]
            return [float(x) for x in series]
        return [default] * n_years

    # Full structured 3-statements matching HUL FINAL MODEL.xlsx (plus Banking specifics)
    statements = {
        "income_statement": {
            "Revenues / Net Sales": revenue.tolist(),
            "Interest Income": _extract_series(income_stmt, ["Interest Income", "Interest Income Non Operating"]),
            "Net Interest Income (NII)": net_interest_income.tolist(),
            "Cost of Goods Sold (COGS)": _extract_series(income_stmt, ["Cost Of Revenue", "Reconciled Cost Of Revenue"]),
            "Gross Profit": _extract_series(income_stmt, ["Gross Profit"]),
            "Selling, General & Admin (SG&A)": _extract_series(income_stmt, ["Selling General And Administration", "Operating Expense"]),
            "Operating Profit (EBITDA)": ebitda_arr.tolist(),
            "Depreciation & Amortization (D&A)": dna.tolist(),
            "Operating Income (EBIT)": ebit.tolist(),
            "Interest Expense": _extract_series(income_stmt, ["Interest Expense", "Interest Expense Non Operating"]),
            "Earnings Before Tax (EBT)": _extract_series(income_stmt, ["Pretax Income"]),
            "Income Tax Expense": _extract_series(income_stmt, ["Tax Provision"]),
            "Net Profit / Net Income": net_income.tolist(),
            "Diluted Shares Outstanding": _extract_series(income_stmt, ["Diluted Average Shares", "Basic Average Shares"]),
            "Earnings Per Share (EPS)": _extract_series(income_stmt, ["Diluted EPS", "Basic EPS"]),
            "Cash Dividends Paid": dividends_paid.tolist(),
        },
        "balance_sheet": {
            "Equity Share Capital": _extract_series(balance_sheet, ["Common Stock", "Capital Stock", "Ordinary Shares Number"]),
            "Reserves & Retained Earnings": _extract_series(balance_sheet, ["Retained Earnings", "Additional Paid In Capital"]),
            "Total Stockholders' Equity": _extract_series(balance_sheet, ["Stockholders Equity", "Common Stock Equity"]),
            "Short-Term Borrowings": _extract_series(balance_sheet, ["Current Debt", "Current Debt And Capital Lease Obligation"]),
            "Long-Term Borrowings": _extract_series(balance_sheet, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]),
            "Total Debt": _extract_series(balance_sheet, ["Total Debt"]),
            "Other Liabilities": _extract_series(balance_sheet, ["Other Current Liabilities", "Other Non Current Liabilities"]),
            "Total Liabilities & Equity": _extract_series(balance_sheet, ["Total Liabilities Net Minority Interest", "Total Capitalization"]),
            "Fixed Assets (Net PPE)": _extract_series(balance_sheet, ["Net PPE", "Properties"]),
            "Capital Work in Progress (CWIP)": _extract_series(balance_sheet, ["Construction In Progress"]),
            "Investments": _extract_series(balance_sheet, ["Investmentin Financial Assets", "Long Term Equity Investment", "Available For Sale Securities"]),
            "Investments & Financial Assets": _extract_series(balance_sheet, ["Investments And Advances", "Investmentin Financial Assets", "Available For Sale Securities"]),
            "Other Non-Current Assets": _extract_series(balance_sheet, ["Other Non Current Assets"]),
            "Total Non-Current Assets": _extract_series(balance_sheet, ["Total Non Current Assets"]),
            "Receivables": _extract_series(balance_sheet, ["Accounts Receivable", "Gross Accounts Receivable"]),
            "Loans, Advances & Receivables": _extract_series(balance_sheet, ["Receivables", "Accounts Receivable", "Gross Accounts Receivable"]),
            "Intangible Assets & Goodwill": _extract_series(balance_sheet, ["Goodwill And Other Intangible Assets", "Goodwill"]),
            "Inventory": _extract_series(balance_sheet, ["Inventory", "Finished Goods"]),
            "Cash & Bank Balances": _extract_series(balance_sheet, ["Cash And Cash Equivalents", "Cash Financial"]),
            "Cash & Central Bank Balances": _extract_series(balance_sheet, ["Cash Cash Equivalents And Federal Funds Sold", "Cash And Cash Equivalents", "Cash Financial"]),
            "Short-Term Investments": _extract_series(balance_sheet, ["Other Short Term Investments", "Cash Cash Equivalents And Short Term Investments"]),
            "Total Current Assets": _extract_series(balance_sheet, ["Current Assets"]),
            "Total Assets": _extract_series(balance_sheet, ["Total Assets"]),
        },
        "cash_flow": {
            "Net Profit from Operations": net_income.tolist(),
            "Depreciation & Amortization": dna.tolist(),
            "Change in Working Capital": _extract_series(cash_flow, ["Change In Working Capital"]),
            "Direct Taxes Paid": _extract_series(cash_flow, ["Taxes Refund Paid"]),
            "Cash Flow from Operating Activities (CFO)": _extract_series(cash_flow, ["Operating Cash Flow"]),
            "Fixed Assets Purchased (CapEx)": capex.tolist(),
            "Net Investments Cash Flow": _extract_series(cash_flow, ["Net Investment Purchase And Sale"]),
            "Cash Flow from Investing Activities (CFI)": _extract_series(cash_flow, ["Investing Cash Flow"]),
            "Net Debt Flow": _extract_series(cash_flow, ["Net Issuance Payments Of Debt"]),
            "Dividends Paid": dividends_paid.tolist(),
            "Cash Flow from Financing Activities (CFF)": _extract_series(cash_flow, ["Financing Cash Flow"]),
            "Net Change in Cash": _extract_series(cash_flow, ["Changes In Cash"]),
            "Ending Cash Position": _extract_series(cash_flow, ["End Cash Position"]),
            "Free Cash Flow (FCFF)": _extract_series(cash_flow, ["Free Cash Flow"]),
        }
    }

    return {
        "years": [str(d.year) if hasattr(d, 'year') else str(d)[:4] for d in income_stmt.index][::-1],
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
        "avg_dna_pct": avg_dna_pct,
        "avg_dnwc_pct": avg_dnwc_pct,
        "normalized_nwc_to_revenue": normalized_nwc_to_revenue,
        "gross_margins": gross_margins.tolist(),
        "avg_gross_margin": avg_gross_margin,
        "fcf_margins": fcf_margins.tolist(),
        "avg_fcf_margin": avg_fcf_margin,
        "latest_fcf_margin": latest_fcf_margin,
        "sbc_pcts": sbc_margins.tolist(),
        "avg_sbc_pct": avg_sbc_pct,
        "latest_sbc_pct": latest_sbc_pct,
        # Snapshot values
        "n_years": n_years,
        "last_revenue": float(
            info_dict["totalRevenue"]
            if (
                info_dict.get("totalRevenue")
                and float(info_dict["totalRevenue"]) > 0
                and len(revenue) <= 2
                and float(info_dict["totalRevenue"]) > float(revenue[-1]) * 1.10
            )
            else float(revenue[-1])
        ),
        "total_debt": total_debt,
        "raw_total_debt": raw_total_debt,
        "lease_obligations": lease_obligations,
        "cwip_to_rev": float(cwip_to_rev),
        "cash_and_equivalents": cash_and_equivalents,
        "interest_expense": interest_expense,
        "interest_coverage": float(interest_coverage),
        # Full 3-statement models
        "statements": statements,
    }
