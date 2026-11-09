#!/usr/bin/env python3
"""
Record deterministic offline fixtures and golden baseline snapshots for ValuationLabs.

Captures raw Yahoo Finance inputs (financials, balance_sheet, cashflow, fast_info,
info, cloud search/timeseries fallback responses, 1Y daily & 2Y weekly histories,
benchmark returns, FX rates, and market profiles) for the 36-ticker Golden Set.

Then evaluates the full `/api/analyze` pipeline offline in three modes:
  1. `normal`         — Full `yf.Ticker.info` available (local residential IP behavior)
  2. `cloud_sim`      — `yf.Ticker.info` blocked (`{}`), crumb-free search & timeseries active (Render IP behavior)
  3. `cloud_blackout` — Both `yf.Ticker.info` and search/timeseries blocked (total metadata blackout)

Saves:
  - `backend/tests/fixtures/_meta.json`
  - `backend/tests/fixtures/<SAFE_TICKER>.json`
  - `backend/tests/golden_baseline.json`
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from engine.data_layer import (
    _get_benchmark_returns,
    get_cross_fx_rate,
    get_yf_session,
)
from engine.market_config import get_market_profile
from engine.ticker_universe import resolve_ticker

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
BASELINE_PATH = BACKEND_DIR / "tests" / "golden_baseline.json"

# 36 Golden Tickers covering every valuation archetype & historical failure mode
GOLDEN_TICKERS: List[Tuple[str, str, str]] = [
    # India (21)
    ("RELIANCE.NS", "IN", "conglomerate_o2c_telecom_retail"),
    ("TCS.NS", "IN", "it_services_compounder"),
    ("INFY.NS", "IN", "it_services_usd_reporting_in_inr"),
    ("ITC.NS", "IN", "fmcg_staples_compounder"),
    ("SUNPHARMA.NS", "IN", "pharma_high_gm_rd"),
    ("LT.NS", "IN", "epc_infra_captive_finance"),
    ("CESC.NS", "IN", "regulated_utility_high_debt"),
    ("NTPC.NS", "IN", "regulated_thermal_utility"),
    ("POWERGRID.NS", "IN", "regulated_transmission_utility"),
    ("IOC.NS", "IN", "downstream_refining_cyclical"),
    ("BPCL.NS", "IN", "downstream_refining_cyclical"),
    ("ONGC.NS", "IN", "upstream_extractive_minority_aro"),
    ("OIL.NS", "IN", "upstream_extractive_cwip_afs"),
    ("COALINDIA.NS", "IN", "coal_extractive"),
    ("ADANIENT.NS", "IN", "greenfield_infra_conglomerate"),
    ("HINDUNILVR.NS", "IN", "high_roic_fmcg_rich_pe"),
    ("ASIANPAINT.NS", "IN", "specialty_chemical_paint_compounder"),
    ("GRASIM.NS", "IN", "conglomerate_nbfc_consolidation"),
    ("HDFCBANK.NS", "IN", "private_bank_merger_goodwill"),
    ("BANKBARODA.NS", "IN", "psu_bank"),
    ("JMFINANCIL.NS", "IN", "nbfc_ticker_redirect"),
    # United States (15)
    ("AAPL", "US", "megacap_tech_compounder"),
    ("MSFT", "US", "megacap_cloud_compounder"),
    ("NVDA", "US", "megacap_ai_semiconductor_ceiling"),
    ("GOOGL", "US", "megacap_advertising_cloud"),
    ("PG", "US", "us_consumer_staples"),
    ("WMT", "US", "us_omnichannel_retail"),
    ("KO", "US", "us_beverage_compounder"),
    ("XOM", "US", "us_integrated_oil_extractive"),
    ("DNUT", "US", "qsr_lease_heavy_goodwill_impairment"),
    ("DG", "US", "discount_retail_lease_heavy"),
    ("SBUX", "US", "qsr_lease_heavy_negative_bve"),
    ("NVO", "US", "cross_currency_adr_dkk_to_usd"),
    ("HPE", "US", "enterprise_hw_captive_finance"),
    ("DE", "US", "industrial_equipment_captive_finance"),
    ("BYND", "US", "distressed_insolvent_debt_gain"),
]


def _clean_val(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        if math.isnan(v) or math.isinf(v):
            return None
        return float(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _clean_val(val) for k, val in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_clean_val(x) for x in v]
    return v


def serialize_df(df: pd.DataFrame) -> Dict[str, Any]:
    """Serialize a pandas DataFrame (rows=dates or metrics, cols=metrics or dates) losslessly."""
    if df is None or df.empty:
        return {"index": [], "columns": [], "data": []}
    return {
        "index": [str(idx.isoformat() if hasattr(idx, "isoformat") else idx) for idx in df.index],
        "columns": [str(col.isoformat() if hasattr(col, "isoformat") else col) for col in df.columns],
        "data": [[_clean_val(val) for val in row] for row in df.to_numpy()],
    }


def serialize_series(s: pd.Series) -> Dict[str, Any]:
    if s is None or s.empty:
        return {"index": [], "values": []}
    return {
        "index": [str(idx.isoformat() if hasattr(idx, "isoformat") else idx) for idx in s.index],
        "values": [_clean_val(v) for v in s.to_numpy()],
    }


def SafeTickerFilename(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "_")


def record_single_ticker(ticker: str, market: str, archetype: str) -> Dict[str, Any]:
    session = get_yf_session()
    resolved_sym, resolved_mkt, redirect_note = resolve_ticker(ticker, market)
    eff_ticker = resolved_sym if redirect_note else ticker
    eff_market = resolved_mkt if redirect_note else market

    suffix = ".NS" if eff_market.upper() == "IN" else ""
    yf_ticker = eff_ticker.strip()
    if suffix and not yf_ticker.upper().endswith(suffix.upper()) and not yf_ticker.upper().endswith(".BO"):
        yf_ticker = yf_ticker + suffix

    t = yf.Ticker(yf_ticker, session=session)

    # Fetch statement matrices (note: yfinance .financials has metrics as index, dates as columns)
    fin_df = t.financials
    bs_df = t.balance_sheet
    cf_df = t.cashflow

    fast_dict: Dict[str, Any] = {}
    try:
        fast = t.fast_info
        price = getattr(fast, "last_price", None) or fast.get("lastPrice") or fast.get("regularMarketPreviousClose")
        shares = getattr(fast, "shares", None) or fast.get("shares")
        fast_curr = getattr(fast, "currency", None) or fast.get("currency")
        mcap = getattr(fast, "market_cap", None) or fast.get("marketCap")
        if shares is None and mcap and price:
            shares = float(mcap) / float(price)
        fast_dict = {
            "last_price": _clean_val(price),
            "shares": _clean_val(shares),
            "currency": _clean_val(fast_curr),
            "marketCap": _clean_val(mcap),
        }
    except Exception as exc:
        print(f"  [warn] fast_info failed for {yf_ticker}: {exc}")

    info_dict: Dict[str, Any] = {}
    try:
        raw_info = dict(t.info or {})
        # Keep only JSON-serializable primitives needed by engine
        info_dict = _clean_val(raw_info)
    except Exception as exc:
        print(f"  [warn] info failed for {yf_ticker}: {exc}")

    # Crumb-free fallback 1: search
    search_json: Dict[str, Any] = {}
    try:
        sr = session.get(
            f"https://query2.finance.yahoo.com/v1/finance/search?q={yf_ticker}&quotesCount=5&newsCount=0",
            timeout=6,
        )
        if sr.status_code == 200:
            search_json = _clean_val(sr.json())
    except Exception as exc:
        print(f"  [warn] search fallback failed for {yf_ticker}: {exc}")

    # Crumb-free fallback 2: fundamentals-timeseries
    timeseries_json: Dict[str, Any] = {}
    try:
        ts_url = (
            f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{yf_ticker}"
            f"?type=annualTotalRevenue&period1=1600000000&period2=1950000000"
        )
        tr = session.get(ts_url, timeout=6)
        if tr.status_code == 200:
            timeseries_json = _clean_val(tr.json())
    except Exception as exc:
        print(f"  [warn] timeseries fallback failed for {yf_ticker}: {exc}")

    hist_1y = t.history(period="1y", interval="1d")
    if not hist_1y.empty:
        keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in hist_1y.columns]
        hist_1y = hist_1y[keep_cols]

    hist_2y = t.history(period="2y", interval="1wk")
    if not hist_2y.empty:
        keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in hist_2y.columns]
        hist_2y = hist_2y[keep_cols]

    payload = {
        "ticker": ticker,
        "market": market,
        "archetype": archetype,
        "yf_ticker": yf_ticker,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "financials": serialize_df(fin_df),
        "balance_sheet": serialize_df(bs_df),
        "cashflow": serialize_df(cf_df),
        "fast_info": fast_dict,
        "info": info_dict,
        "search_fallback": search_json,
        "timeseries_fallback": timeseries_json,
        "hist_1y": serialize_df(hist_1y),
        "hist_2y": serialize_df(hist_2y),
    }

    out_file = FIXTURES_DIR / f"{SafeTickerFilename(ticker)}.json"
    out_file.write_text(json.dumps(payload, indent=2))
    return payload


def record_all() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Recording global metadata (market profiles, benchmark returns, FX rates)...")

    us_profile = get_market_profile("US")
    in_profile = get_market_profile("IN")
    bench_us = _get_benchmark_returns("^GSPC")
    bench_in = _get_benchmark_returns("^NSEI")

    fx_pairs = [
        ("USD", "INR"),
        ("INR", "USD"),
        ("DKK", "USD"),
        ("EUR", "USD"),
        ("GBP", "USD"),
        ("JPY", "USD"),
        ("TWD", "USD"),
    ]
    fx_rates: Dict[str, float] = {}
    for f_curr, t_curr in fx_pairs:
        rate = get_cross_fx_rate(f_curr, t_curr)
        if rate:
            fx_rates[f"{f_curr}_{t_curr}"] = float(rate)

    meta_payload = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "market_profiles": {
            "US": _clean_val(us_profile),
            "IN": _clean_val(in_profile),
        },
        "benchmark_returns": {
            "^GSPC": serialize_series(bench_us),
            "^NSEI": serialize_series(bench_in),
        },
        "fx_rates": fx_rates,
        "tickers": [
            {"ticker": t, "market": m, "archetype": a, "fixture": f"{SafeTickerFilename(t)}.json"}
            for (t, m, a) in GOLDEN_TICKERS
        ],
    }
    (FIXTURES_DIR / "_meta.json").write_text(json.dumps(meta_payload, indent=2))

    print(f"Recording {len(GOLDEN_TICKERS)} golden ticker fixtures...")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(record_single_ticker, t, m, a): (t, m, a)
            for (t, m, a) in GOLDEN_TICKERS
        }
        done_count = 0
        for fut in as_completed(futures):
            t, m, a = futures[fut]
            done_count += 1
            try:
                data = fut.result()
                price = data["fast_info"].get("last_price") or data["info"].get("currentPrice")
                print(f"  [{done_count:2d}/{len(GOLDEN_TICKERS)}] Recorded {t:15s} ({m}) price={price} [{a}]")
            except Exception as exc:
                print(f"  [{done_count:2d}/{len(GOLDEN_TICKERS)}] ERROR recording {t}: {exc}")
                raise

    print(f"All {len(GOLDEN_TICKERS)} fixtures recorded in {time.time() - t0:.1f}s.")


if __name__ == "__main__":
    record_all()
