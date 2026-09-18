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
# Data fetching
# ---------------------------------------------------------------------------

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
    from .market_config import MARKET_PROFILES

    profile = MARKET_PROFILES.get(market.upper(), MARKET_PROFILES["US"])
    suffix = profile.get("ticker_suffix", "")

    # Append suffix if not already present
    yf_ticker = ticker.strip()
    if suffix and not yf_ticker.upper().endswith(suffix.upper()):
        yf_ticker = yf_ticker + suffix

    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome")
    
    logger.info("Fetching data for %s (yfinance ticker: %s)", ticker, yf_ticker)
    stock = yf.Ticker(yf_ticker, session=session)

    # Financial statements – .T transposes columns-as-years to rows-as-years
    income_stmt: pd.DataFrame = stock.financials.T
    balance_sheet: pd.DataFrame = stock.balance_sheet.T
    cash_flow: pd.DataFrame = stock.cashflow.T

    # 1. Retrieve price & shares via fast_info (fast, direct chart API, no crumb required)
    current_price = None
    shares_out = None
    try:
        fast = stock.fast_info
        current_price = getattr(fast, "last_price", None) or fast.get("lastPrice") or fast.get("regularMarketPreviousClose")
        shares_out = getattr(fast, "shares", None) or fast.get("shares")
        if shares_out is None and fast.get("marketCap") and current_price:
            shares_out = float(fast.get("marketCap")) / float(current_price)
    except Exception:
        pass

    # 2. Query stock.info for sector, industry, denominators and metadata
    info: dict = {}
    try:
        info = stock.info or {}
    except Exception as e:
        logger.warning("Could not fetch stock.info for %s: %s", yf_ticker, e)

    if current_price is None:
        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    if shares_out is None:
        shares_out = info.get("sharesOutstanding")

    # 3. Last-resort fallback for price via 5-day history
    if current_price is None:
        try:
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

    beta = info.get("beta", 1.0)
    if beta is None or np.isnan(beta):
        beta = 1.0
    market_cap = float(current_price) * float(shares_out)

    company_name = info.get("shortName") or info.get("longName") or yf_ticker
    sector = info.get("sector")
    industry = info.get("industry")

    # Financial Institution Detection (Banks, NBFCs, Insurance, Capital Markets)
    is_financial = False
    sec_lower = (sector or "").lower()
    ind_lower = (industry or "").lower()
    if any(k in sec_lower for k in ["financial", "banking"]):
        is_financial = True
    elif any(kw in ind_lower for kw in ["bank", "credit services", "insurance", "capital markets", "asset management", "consumer finance"]):
        is_financial = True

    return {
        "ticker": yf_ticker,
        "name": company_name,
        "sector": sector,
        "industry": industry,
        "is_financial": is_financial,
        "current_price": float(current_price),
        "shares_outstanding": float(shares_out),
        "market_cap": market_cap,
        "beta": float(beta),
        "income_stmt": income_stmt,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
        "info": info,
    }


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
    
    # Financial institutions specific metrics
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

    n_years = len(revenue)

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
        # Bank & Financial Institutions Specifics
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
    }
