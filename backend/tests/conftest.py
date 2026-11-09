"""
Pytest configuration and offline fixture replay harness for ValuationLabs.

Provides deterministic, zero-network replay of the 36-ticker Golden Set across
three environment modes:
  - `normal`:         Full `yf.Ticker.info` available (local residential IP)
  - `cloud_sim`:      `yf.Ticker.info` returns `{}` (HTTP 429/401 on quoteSummary),
                      while crumb-free `/v1/finance/search` & `/ws/fundamentals-timeseries`
                      remain available (Render shared cloud IP behavior)
  - `cloud_blackout`: Total metadata blackout (`yf.Ticker.info = {}` AND fallback
                      HTTP endpoints return 429), testing deterministic engine fallbacks.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
BASELINE_PATH = Path(__file__).resolve().parent / "golden_baseline.json"

GOLDEN_UNIVERSE: List[Tuple[str, str]] = [
    ("RELIANCE.NS", "IN"),
    ("TCS.NS", "IN"),
    ("INFY.NS", "IN"),
    ("ITC.NS", "IN"),
    ("SUNPHARMA.NS", "IN"),
    ("LT.NS", "IN"),
    ("CESC.NS", "IN"),
    ("NTPC.NS", "IN"),
    ("POWERGRID.NS", "IN"),
    ("IOC.NS", "IN"),
    ("BPCL.NS", "IN"),
    ("ONGC.NS", "IN"),
    ("OIL.NS", "IN"),
    ("COALINDIA.NS", "IN"),
    ("ADANIENT.NS", "IN"),
    ("HINDUNILVR.NS", "IN"),
    ("ASIANPAINT.NS", "IN"),
    ("GRASIM.NS", "IN"),
    ("HDFCBANK.NS", "IN"),
    ("BANKBARODA.NS", "IN"),
    ("JMFINANCIL.NS", "IN"),
    ("AAPL", "US"),
    ("MSFT", "US"),
    ("NVDA", "US"),
    ("GOOGL", "US"),
    ("PG", "US"),
    ("WMT", "US"),
    ("KO", "US"),
    ("XOM", "US"),
    ("DNUT", "US"),
    ("DG", "US"),
    ("SBUX", "US"),
    ("NVO", "US"),
    ("HPE", "US"),
    ("DE", "US"),
    ("BYND", "US"),
]


def deserialize_df(obj: Dict[str, Any], parse_dates_index: bool = False, parse_dates_cols: bool = False) -> pd.DataFrame:
    if not obj or not obj.get("index") and not obj.get("columns"):
        return pd.DataFrame()
    idx = obj["index"]
    cols = obj["columns"]
    if parse_dates_index:
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            pass
    if parse_dates_cols:
        try:
            cols = pd.to_datetime(cols)
        except Exception:
            pass
    df = pd.DataFrame(obj["data"], index=idx, columns=cols)
    return df


def deserialize_series(obj: Dict[str, Any]) -> pd.Series:
    if not obj or not obj.get("index"):
        return pd.Series(dtype=float)
    try:
        idx = pd.to_datetime(obj["index"])
    except Exception:
        idx = obj["index"]
    return pd.Series(obj["values"], index=idx, dtype=float)


class _MockFastInfo:
    def __init__(self, d: Dict[str, Any]):
        self._d = d or {}
        self.last_price = self._d.get("last_price")
        self.shares = self._d.get("shares")
        self.currency = self._d.get("currency")
        self.market_cap = self._d.get("marketCap")

    def get(self, key: str, default: Any = None) -> Any:
        if key == "lastPrice":
            return self._d.get("last_price", default)
        if key == "regularMarketPreviousClose":
            return self._d.get("last_price", default)
        return self._d.get(key, default)


class _MockResponse:
    def __init__(self, status_code: int, payload: Dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


class _MockSession:
    def __init__(self, fixtures_by_yf_ticker: Dict[str, Dict[str, Any]], mode: str):
        self._fixtures = fixtures_by_yf_ticker
        self._mode = mode

    def get(self, url: str, timeout: int = 4, **kwargs: Any) -> _MockResponse:
        if self._mode == "cloud_blackout":
            return _MockResponse(429, {})

        # Match ticker in URL
        for yf_sym, fx_data in self._fixtures.items():
            if f"q={yf_sym}" in url or f"/timeseries/{yf_sym}" in url:
                if "/v1/finance/search" in url:
                    return _MockResponse(200, fx_data.get("search_fallback") or {})
                if "/ws/fundamentals-timeseries" in url:
                    return _MockResponse(200, fx_data.get("timeseries_fallback") or {})
        return _MockResponse(404, {})


class _MockYFTicker:
    def __init__(self, ticker_str: str, fixture_data: Dict[str, Any], mode: str):
        self.ticker = ticker_str
        self._fx = fixture_data
        self._mode = mode

    @property
    def financials(self) -> pd.DataFrame:
        return deserialize_df(self._fx.get("financials", {}), parse_dates_cols=True)

    @property
    def balance_sheet(self) -> pd.DataFrame:
        return deserialize_df(self._fx.get("balance_sheet", {}), parse_dates_cols=True)

    @property
    def cashflow(self) -> pd.DataFrame:
        return deserialize_df(self._fx.get("cashflow", {}), parse_dates_cols=True)

    @property
    def fast_info(self) -> _MockFastInfo:
        return _MockFastInfo(self._fx.get("fast_info", {}))

    @property
    def info(self) -> Dict[str, Any]:
        if self._mode in ("cloud_sim", "cloud_blackout"):
            # Simulate Render shared cloud IP where /v10/finance/quoteSummary is blocked
            return {}
        return dict(self._fx.get("info") or {})

    def history(self, period: str = "1y", interval: str = "1d", **kwargs: Any) -> pd.DataFrame:
        if period == "2y" and interval == "1wk":
            return deserialize_df(self._fx.get("hist_2y", {}), parse_dates_index=True)
        h1y = deserialize_df(self._fx.get("hist_1y", {}), parse_dates_index=True)
        if period == "5d" and not h1y.empty:
            return h1y.tail(5)
        return h1y


class OfflineFixtureStore:
    """Loads recorded fixtures once per test process for fast in-memory access."""

    def __init__(self) -> None:
        meta_file = FIXTURES_DIR / "_meta.json"
        if not meta_file.exists():
            raise RuntimeError(f"Missing fixture metadata at {meta_file}. Run record_fixtures.py first.")
        self.meta: Dict[str, Any] = json.loads(meta_file.read_text())
        self.by_ticker: Dict[str, Dict[str, Any]] = {}
        self.by_yf_ticker: Dict[str, Dict[str, Any]] = {}

        for entry in self.meta.get("tickers", []):
            fpath = FIXTURES_DIR / entry["fixture"]
            if fpath.exists():
                data = json.loads(fpath.read_text())
                t_upper = data["ticker"].strip().upper()
                yf_upper = data["yf_ticker"].strip().upper()
                self.by_ticker[t_upper] = data
                self.by_yf_ticker[yf_upper] = data
                # Also index without suffix for auto-fallback lookups
                base_sym = yf_upper.replace(".NS", "").replace(".BO", "")
                if base_sym not in self.by_yf_ticker:
                    self.by_yf_ticker[base_sym] = data

    def get_ticker_list(self) -> List[Dict[str, str]]:
        return list(self.meta.get("tickers", []))

    @contextmanager
    def patch_env(self, mode: str = "normal") -> Iterator[None]:
        """Context manager that patches all network calls in data_layer and main."""
        import engine.data_layer as dl
        import engine.market_config as mc
        import main as app_main

        dl._STOCK_DATA_CACHE.clear()
        app_main._ANALYZE_RESPONSE_CACHE.clear()

        mock_session = _MockSession(self.by_yf_ticker, mode=mode)

        def _fake_yf_ticker(sym: str, session: Any = None) -> _MockYFTicker:
            key = sym.strip().upper()
            fx = self.by_yf_ticker.get(key) or self.by_ticker.get(key)
            if fx is None:
                raise ValueError(f"Ticker {sym} not found in offline fixtures")
            return _MockYFTicker(sym, fx, mode=mode)

        def _fake_bench(benchmark: str) -> pd.Series:
            ser_obj = self.meta.get("benchmark_returns", {}).get(benchmark, {})
            return deserialize_series(ser_obj)

        def _fake_fx(from_curr: str, to_curr: str) -> Optional[float]:
            fc = from_curr.strip().upper()
            tc = to_curr.strip().upper()
            if fc == tc:
                return 1.0
            key = f"{fc}_{tc}"
            rates = self.meta.get("fx_rates", {})
            if key in rates:
                return float(rates[key])
            inv_key = f"{tc}_{fc}"
            if inv_key in rates and rates[inv_key] > 0:
                return 1.0 / float(rates[inv_key])
            return None

        def _fake_market_profile(market: str) -> Dict[str, Any]:
            m_key = "IN" if market.strip().upper() == "IN" else "US"
            return dict(self.meta["market_profiles"][m_key])

        def _fake_live_rfr(market: str) -> float:
            prof = _fake_market_profile(market)
            return float(prof["risk_free_rate"])

        with (
            patch.object(dl.yf, "Ticker", side_effect=_fake_yf_ticker),
            patch.object(dl, "get_yf_session", return_value=mock_session),
            patch.object(dl, "_get_benchmark_returns", side_effect=_fake_bench),
            patch.object(dl, "get_cross_fx_rate", side_effect=_fake_fx),
            patch.object(mc, "get_live_risk_free_rate", side_effect=_fake_live_rfr),
            patch.object(mc, "get_market_profile", side_effect=_fake_market_profile),
            patch.object(app_main, "get_market_profile", side_effect=_fake_market_profile),
        ):
            yield

        dl._STOCK_DATA_CACHE.clear()
        app_main._ANALYZE_RESPONSE_CACHE.clear()


_STORE_SINGLETON: Optional[OfflineFixtureStore] = None


def get_fixture_store() -> OfflineFixtureStore:
    global _STORE_SINGLETON
    if _STORE_SINGLETON is None:
        _STORE_SINGLETON = OfflineFixtureStore()
    return _STORE_SINGLETON


@pytest.fixture(scope="session")
def fixture_store() -> OfflineFixtureStore:
    return get_fixture_store()
