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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def safe_get(df: pd.DataFrame, column: str, default: float = 0) -> np.ndarray:
    """Extract a column from a DataFrame, returning a default-filled array if missing.

    This mirrors the ``safe_get`` helper in notebook Step 3C.  It also tries
    common alternate column names used by Indian stocks so that the same
    pipeline works for both US and Indian equities.

    Args:
        df:       The pandas DataFrame (e.g. income statement).
        column:   The primary column name to look up.
        default:  Value to fill NaNs / missing columns with.

    Returns:
        A numpy array of length ``len(df)``.
    """
    # Alternate name map – Indian stocks and financial companies sometimes use different labels
    _alternates: Dict[str, List[str]] = {
        "Total Revenue": ["Revenue", "Total Revenue From Operations", "Operating Revenue"],
        "Current Debt": ["Current Borrowings", "Short Term Debt"],
        "Net Income": ["Net Income Common Stockholders", "Net Income Continuous Operations", "Net Income Including Noncontrolling Interests", "Normalized Income"],
        "Stockholders Equity": ["Common Stock Equity", "Total Equity Gross Minority Interest", "Tangible Book Value"],
        "Net Interest Income": ["Operating Revenue", "Total Revenue"],
        "Pretax Income": ["Income Before Tax", "Earnings Before Taxes"],
        "Cash Dividends Paid": ["Common Stock Dividend Paid", "Payment Of Dividends"],
    }

    if column in df.columns:
        return df[column].fillna(default).values

    # Try alternates
    for alt in _alternates.get(column, []):
        if alt in df.columns:
            return df[alt].fillna(default).values

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
                        
                        # Only clamp if raw beta is negative or implausibly close to zero (<= 0.15)
                        eff_raw = calc_raw
                        if calc_raw <= 0.15:
                            beta_u = get_industry_unlevered_beta(sector, industry)
                            eff_de = min(2.5, max(0.0, float(de_ratio))) if de_ratio is not None else 0.5
                            eff_raw = beta_u * (1.0 + (1.0 - tax_rate) * eff_de)
                            beta_clamped = True
                            clamp_reason = f"Raw regression beta ({calc_raw:.2f}) was near-zero; substituted bottom-up unlevered beta {beta_u:.2f} (relevered: {eff_raw:.2f})."
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

def classify_sector_dynamics(sector: Optional[str] = None, industry: Optional[str] = None) -> Tuple[bool, bool]:
    """
    Classifies company into (is_extractive, is_cyclical).
    - is_extractive: Oil & Gas exploration/drilling/upstream/integrated, Thermal Coal, Mining & Minerals.
      Assets suffer from physical depletion; CapEx is required just to sustain reserves and
      perpetual volume growth cannot exceed physical/transition constraints.
    - is_cyclical: Extractive PLUS Basic Materials (Steel, Aluminum, Metals, Chemicals, Refining).
      Earnings fluctuate with global commodity pricing; margins must mean-revert to multi-year cycle averages.
    """
    sec = sector or ""
    ind = industry or ""
    text = (sec + " " + ind).lower()
    
    extractive_keywords = [
        "oil & gas", "oil and gas", "thermal coal", "coal", "integrated oil", "drilling",
        "exploration & production", "upstream", "crude", "petroleum", "mining"
    ]
    is_extractive = any(k in text for k in extractive_keywords)
    
    cyclical_keywords = extractive_keywords + [
        "basic materials", "steel", "aluminum", "aluminium", "metals", "chemicals", 
        "commodity chemicals", "iron", "fertilizer", "refining", "paper & forest"
    ]
    is_cyclical = any(k in text for k in cyclical_keywords)
    
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
    if suffix and not yf_ticker.upper().endswith(suffix.upper()):
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
        price, shares = None, None
        try:
            fast = yf.Ticker(yf_ticker, session=session).fast_info
            price = getattr(fast, "last_price", None) or fast.get("lastPrice") or fast.get("regularMarketPreviousClose")
            shares = getattr(fast, "shares", None) or fast.get("shares")
            if shares is None and fast.get("marketCap") and price:
                shares = float(fast.get("marketCap")) / float(price)
        except Exception:
            pass
        return price, shares

    def _fetch_info():
        try:
            return yf.Ticker(yf_ticker, session=session).info or {}
        except Exception as e:
            logger.warning("Could not fetch stock.info for %s: %s", yf_ticker, e)
            return {}

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
        current_price, shares_out = fut_fast.result()
        info: dict = fut_info.result()
        hist_1y: pd.DataFrame = fut_h1y.result()
        hist_2y: pd.DataFrame = fut_h2y.result()
        _ = fut_bench.result()

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
        raise ValueError(
            f"Yahoo Finance did not return critical data for {yf_ticker}.\n"
            f"   currentPrice={current_price}, sharesOutstanding={shares_out}\n"
            f"   Cannot build a DCF without these denominators."
        )

    market_cap = float(current_price) * float(shares_out)

    # Estimate debt and D/E ratio for bottom-up beta relevering
    approx_debt = 0.0
    if not balance_sheet.empty:
        for debt_col in ["Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"]:
            if debt_col in balance_sheet.columns:
                d_vals = balance_sheet[debt_col].dropna()
                if len(d_vals) > 0 and float(d_vals.iloc[0]) > 0:
                    approx_debt = float(d_vals.iloc[0])
                    break
    de_ratio = (approx_debt / market_cap) if market_cap > 0 else 0.0

    beta_info = compute_clean_beta(
        stock=stock,
        ticker=yf_ticker,
        market=market,
        raw_info_beta=info.get("beta"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        de_ratio=de_ratio,
        tax_rate=profile.get("tax_rate", 0.2517 if market.upper() == "IN" else 0.21),
        tradeable=info.get("tradeable"),
        hist_1y=hist_1y,
        hist_2y=hist_2y,
    )

    # -----------------------------------------------------------------------
    # Automated Statement Unit Scale Reconciliation
    # Fixes international scraping discrepancies where Yahoo Finance reports
    # statements in units that differ by 10x, 100x, or 1000x from the per-share metrics.
    # E.g. Indian filings in Crores scraped as Tens of Millions or Lakhs (e.g. INDOMIM).
    # -----------------------------------------------------------------------
    scale_multiplier = 1.0
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

    # Cross-Currency Reconciler (e.g. ADR-linked Indian firms like INFY where statements are in USD while trading in INR)
    try:
        fin_currency = str(info.get("financialCurrency") or "").upper()
        trade_currency = str(info.get("currency") or "").upper()
        if fin_currency == "USD" and trade_currency == "INR":
            cached_fx = _FX_CACHE.get("USDINR")
            if cached_fx and (time.time() - cached_fx[1] < _BENCHMARK_CACHE_TTL_SECONDS):
                fx_rate = cached_fx[0]
            else:
                try:
                    usdinr_ticker = yf.Ticker("USDINR=X", session=get_yf_session())
                    fx_rate = float(usdinr_ticker.fast_info.get("last_price") or 86.5)
                    _FX_CACHE["USDINR"] = (fx_rate, time.time())
                except Exception:
                    fx_rate = 86.5

            logger.info(
                "Detected cross-currency mismatch for %s (financialCurrency=%s vs trading currency=%s). "
                "Converting financial statements to %s using FX rate %.2f",
                yf_ticker, fin_currency, trade_currency, trade_currency, fx_rate
            )
            if not income_stmt.empty:
                income_stmt = income_stmt * fx_rate
            if not balance_sheet.empty:
                balance_sheet = balance_sheet * fx_rate
            if not cash_flow.empty:
                cash_flow = cash_flow * fx_rate
    except Exception as e:
        logger.warning("Cross-currency reconciliation skipped for %s: %s", yf_ticker, e)

    company_name = info.get("shortName") or info.get("longName") or yf_ticker
    sector = info.get("sector")
    industry = info.get("industry")

    # Banking & Financial Services Detection (Banks, NBFCs, Insurance, Capital Markets, Lending Institutions)
    is_financial = False
    sec_lower = (sector or "").lower()
    ind_lower = (industry or "").lower()
    name_lower = (company_name or "").lower()
    clean_sym = yf_ticker.replace(".NS", "").replace(".BO", "").upper()

    KNOWN_FINANCIALS = {
        "IREDA", "PFC", "REC", "IRFC", "HUDCO", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", 
        "KOTAKBANK", "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "MUTHOOTFIN", "MANAPPURAM", 
        "SHRIRAMFIN", "M&MFIN", "JIOFIN", "POONAWALLA", "AAVAS", "CANFINHOME", "HOMEFIRST", 
        "CREDITACC", "IDFCFIRSTB", "BANDHANBNK", "FEDERALBNK", "INDUSINDBK", "AUBANK", "PNB", 
        "BANKBARODA", "UNIONBANK", "CANBK", "INDIANB", "MAHABANK", "UCOBANK", "CENTRALBK", 
        "IOB", "J&KBANK", "KARURVYSYA", "SOUTHBANK", "CSBBANK", "DCBBANK", "CITYUNIONB", 
        "EQUITASBNK", "UJJIVANSFB", "SURYODAY", "ESAFSFB", "SBICARD", "ICICIGI", "HDFCLIFE", 
        "SBILIFE", "ICICIPRULI", "LICI", "GICRE", "NIACL", "STARHEALTH", "ISEC", "ANGELONE", 
        "MOTILALOFS", "GEOJITFSL", "5PAISA", "MCX", "BSE", "CDSL", "CAMSLTD", "KFINTECH", 
        "NAM-INDIA", "HDFCAMC", "UTIAMC", "JPM", "BAC", "WFC", "C", "GS", "MS", "AXP", 
        "COF", "USB", "PNC", "TFC", "SCHW", "BK", "BLK", "FITB", "MTB", "KEY", "CFG", 
        "HBAN", "RF", "SYF", "DFS", "SOFI", "AFRM"
    }

    # 1. Known Ticker Check
    if clean_sym in KNOWN_FINANCIALS:
        is_financial = True
    # 2. Sector / Industry Metadata
    elif any(k in sec_lower for k in ["financial", "banking"]):
        is_financial = True
    elif any(kw in ind_lower for kw in ["bank", "credit services", "insurance", "capital markets", "asset management", "consumer finance", "financial", "specialty finance"]):
        is_financial = True
    # 3. Company Name Keywords
    elif any(kw in name_lower for kw in [
        "bank", "finance", "financial", "credit", "housing finance", 
        "development agency", "energy development agency", "capital", "insurance", 
        "securities", "finvest", "leasing", "fincorp", "asset management"
    ]):
        is_financial = True
    # 4. Financial Statement Structural Signals (handles empty info metadata from Yahoo Finance)
    elif "Net Interest Income" in income_stmt.columns or "Interest Income" in income_stmt.columns:
        # Check if interest is primary revenue source or extreme financial leverage exists
        debt_vals = safe_get(balance_sheet, "Total Debt", 0)
        rev_vals = safe_get(income_stmt, "Total Revenue", 0)
        if len(debt_vals) > 0 and len(rev_vals) > 0 and rev_vals[-1] > 0:
            if debt_vals[-1] / rev_vals[-1] > 3.0:
                is_financial = True

    is_extractive, is_cyclical = classify_sector_dynamics(sector, industry)

    result = {
        "ticker": yf_ticker,
        "name": company_name,
        "market": market,
        "sector": sector,
        "industry": industry,
        "is_financial": is_financial,
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
            }
            for alt in _alt_map.get(col, []):
                if alt in income_stmt.columns:
                    resolved_col = alt
                    break

        if resolved_col in income_stmt.columns:
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
    revenue = safe_get(income_stmt, "Total Revenue")[::-1]
    ebit = safe_get(income_stmt, "EBIT")[::-1]
    
    # Banking & Financial Services specific metrics
    net_income = safe_get(income_stmt, "Net Income")[::-1]
    net_interest_income = safe_get(income_stmt, "Net Interest Income")[::-1]
    pretax_income = safe_get(income_stmt, "Pretax Income")[::-1]
    book_value = safe_get(balance_sheet, "Stockholders Equity")[::-1]
    raw_divs = safe_get(cash_flow, "Cash Dividends Paid", default=0)[::-1]
    dividends_paid = np.where(raw_divs < 0, -raw_divs, raw_divs)
    
    raw_capex = safe_get(cash_flow, "Capital Expenditure", default=0)[::-1]
    capex = np.where(raw_capex < 0, -raw_capex, raw_capex)  # explicit positive
    
    raw_dna = safe_get(cash_flow, "Depreciation And Amortization")[::-1]
    dna = np.where(raw_dna < 0, -raw_dna, raw_dna)  # explicit positive

    # ------------------------------------------------------------------
    # 3E – Net Working Capital
    # ------------------------------------------------------------------
    current_assets = safe_get(balance_sheet, "Current Assets")[::-1]
    current_liabs = safe_get(balance_sheet, "Current Liabilities")[::-1]
    cash_on_bs = safe_get(balance_sheet, "Cash And Cash Equivalents")[::-1]
    st_debt = safe_get(balance_sheet, "Current Debt", default=0)[::-1]

    nwc = (current_assets - cash_on_bs) - (current_liabs - st_debt)
    delta_nwc = np.diff(nwc, prepend=nwc[0])

    # ------------------------------------------------------------------
    # 3F – Historical ratio calculations
    # ------------------------------------------------------------------
    rev_growth = np.diff(revenue) / np.where(revenue[:-1] != 0, revenue[:-1], 1.0)
    ebit_margins = ebit / np.where(revenue != 0, revenue, 1.0)

    avg_rev_growth = float(np.mean(rev_growth))
    std_rev_growth = float(np.std(rev_growth, ddof=1)) if len(rev_growth) > 1 else 0.05
    avg_ebit_margin = float(np.mean(ebit_margins))
    std_ebit_margin = float(np.std(ebit_margins, ddof=1)) if len(ebit_margins) > 1 else 0.02

    # Banking specific ratio calculations (ROE, Payout, Net Income growth)
    roes = []
    payouts = []
    for idx in range(len(net_income)):
        bv = book_value[idx - 1] if idx > 0 else book_value[idx]
        ni = net_income[idx]
        div = dividends_paid[idx] if idx < len(dividends_paid) else 0.0
        if bv > 0 and ni != 0:
            roes.append(float(ni / bv))
        if ni > 0 and div > 0:
            payouts.append(float(min(1.0, max(0.0, div / ni))))

    info_roe = stock_data.get("info", {}).get("returnOnEquity")
    if info_roe and not np.isnan(info_roe) and info_roe > 0:
        avg_roe = float(info_roe)
    elif roes:
        avg_roe = float(np.median(roes))
    else:
        avg_roe = 0.14

    std_roe = float(np.std(roes, ddof=1)) if len(roes) > 1 else 0.02
    avg_payout = float(np.mean(payouts)) if payouts else 0.25

    valid_ni = [float(x) for x in net_income if x > 0]
    if len(valid_ni) > 1:
        ni_growth = np.diff(valid_ni) / valid_ni[:-1]
        avg_ni_growth = float(np.mean(ni_growth))
        std_ni_growth = float(np.std(ni_growth, ddof=1)) if len(ni_growth) > 1 else 0.05
    else:
        avg_ni_growth = avg_rev_growth
        std_ni_growth = std_rev_growth

    avg_capex_pct = float(np.mean(capex / np.where(revenue != 0, revenue, 1.0)))
    avg_dna_pct = float(np.mean(dna / np.where(revenue != 0, revenue, 1.0)))
    avg_dnwc_pct = float(np.mean(delta_nwc / np.where(revenue != 0, revenue, 1.0)))
    
    nwc_to_rev = nwc / np.where(revenue != 0, revenue, 1.0)
    normalized_nwc_to_revenue = float(np.mean(nwc_to_rev))

    # Total debt and cash (most recent year – index [0] is newest before reversal,
    # but after [::-1] index [-1] is newest … however the original notebook uses
    # balance_sheet *before* reversal with index [0] for the latest snapshot).
    total_debt = float(safe_get(balance_sheet, "Total Debt")[0])  # newest row
    
    # For the EV-to-Equity bridge, cash MUST include marketable securities / short-term investments
    if "Cash Cash Equivalents And Short Term Investments" in balance_sheet.columns:
        cash_and_equivalents = float(safe_get(balance_sheet, "Cash Cash Equivalents And Short Term Investments")[0])
    else:
        cce = float(safe_get(balance_sheet, "Cash And Cash Equivalents")[0])
        sti = float(safe_get(balance_sheet, "Other Short Term Investments")[0])
        cash_and_equivalents = cce + sti


    # Interest expense (for cost-of-debt calculation)
    interest_expense: float = 0.0
    for ie_col in ["Interest Expense", "Interest Expense Non Operating"]:
        if ie_col in income_stmt.columns:
            ie_vals = income_stmt[ie_col].dropna()
            if len(ie_vals) > 0:
                interest_expense = float(ie_vals.iloc[0])
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
        for col_name in col_candidates:
            if col_name in df.columns:
                series = df[col_name].fillna(default).values[::-1]
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
            "Operating Profit (EBITDA)": _extract_series(income_stmt, ["EBITDA", "Normalized EBITDA"]),
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
        "capex": capex.tolist(),
        "dna": dna.tolist(),
        "nwc": nwc.tolist(),
        "delta_nwc": delta_nwc.tolist(),
        "rev_growth": rev_growth.tolist(),
        "ebit_margins": ebit_margins.tolist(),
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
        "avg_capex_pct": avg_capex_pct,
        "avg_dna_pct": avg_dna_pct,
        "avg_dnwc_pct": avg_dnwc_pct,
        "normalized_nwc_to_revenue": normalized_nwc_to_revenue,
        # Snapshot values
        "n_years": n_years,
        "last_revenue": float(revenue[-1]),
        "total_debt": total_debt,
        "cash_and_equivalents": cash_and_equivalents,
        "interest_expense": interest_expense,
        "interest_coverage": float(interest_coverage),
        # Full 3-statement models
        "statements": statements,
    }
