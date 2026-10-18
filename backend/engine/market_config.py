"""
Market Configuration & Live Rate Fetching Module
=================================================

Handles market-aware configuration for US and Indian markets.
Provides live risk-free rate fetching via the FRED API with caching
and graceful fallback to hardcoded defaults.
"""

import os
import time
import logging
from typing import Dict, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load environment variables from the backend/.env file
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_BACKEND_DIR, ".env")
load_dotenv(_ENV_PATH)

# ---------------------------------------------------------------------------
# Market Profile Definitions
# ---------------------------------------------------------------------------
MARKET_PROFILES: Dict[str, dict] = {
    "US": {
        "risk_free_rate": 0.042,           # fallback / default
        "market_return": 0.10,
        "tax_rate": 0.21,
        "terminal_growth": 0.025,          # US long-term real GDP (2%) + inflation (2%) cap
        "gdp_growth": 0.025,
        "currency": "USD",
        "symbol": "$",
        "ticker_suffix": "",
        "benchmark": "^GSPC",
        "fred_series": "DGS10",
        "rfr_fallback": 0.042,
    },
    "IN": {
        "risk_free_rate": 0.071,           # fallback / default
        "market_return": 0.13,
        "tax_rate": 0.2517,                # 22% basic + 10% surcharge + 4% cess
        "terminal_growth": 0.050,          # India long-term sustainable growth (5.0% < Rf 7.1%)
        "gdp_growth": 0.065,               # India real GDP growth trend (~6.5%)
        "currency": "INR",
        "symbol": "₹",
        "ticker_suffix": ".NS",
        "benchmark": "^NSEI",
        "fred_series": "INDIRLTLT01STM",
        "rfr_fallback": 0.071,
    },
}

# ---------------------------------------------------------------------------
# In-memory cache for live risk-free rates  {market: (value, timestamp, ttl)}
# ---------------------------------------------------------------------------
_rfr_cache: Dict[str, tuple] = {}
_CACHE_TTL_SECONDS: int = 3600  # 1 hour
_FAILURE_TTL_SECONDS: int = 600  # 10 minutes negative cache on FRED failure


def get_live_risk_free_rate(market: str) -> float:
    """Fetch the latest risk-free rate from the FRED API.

    Queries the FRED JSON endpoint for the latest observations (limit=10, desc)
    with a strict 3-second timeout instead of downloading the full 60-year XML
    history. Results are cached for 1 hour (or 10 minutes on fallback).

    Args:
        market: ``'US'`` or ``'IN'``.

    Returns:
        Risk-free rate as a decimal (e.g. 0.042 for 4.2 %).
    """
    market = market.upper()
    if market not in MARKET_PROFILES:
        raise ValueError(f"Unknown market '{market}'. Supported: {list(MARKET_PROFILES.keys())}")

    profile = MARKET_PROFILES[market]

    # ---- check cache ----
    if market in _rfr_cache:
        entry = _rfr_cache[market]
        cached_value, cached_ts = entry[0], entry[1]
        ttl = entry[2] if len(entry) > 2 else _CACHE_TTL_SECONDS
        if time.time() - cached_ts < ttl:
            return cached_value

    # ---- attempt lightweight FRED JSON fetch ----
    try:
        import httpx

        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            raise RuntimeError("FRED_API_KEY not set in environment")

        resp = httpx.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": profile["fred_series"],
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 10,
            },
            timeout=3.0,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
        valid_vals = [
            float(o["value"])
            for o in observations
            if o.get("value") not in (None, ".", "")
        ]
        if not valid_vals:
            raise ValueError(f"No valid observations returned for {profile['fred_series']}")

        rfr = float(valid_vals[0]) / 100.0

        # Cache the result for 1 hour
        _rfr_cache[market] = (rfr, time.time(), _CACHE_TTL_SECONDS)
        logger.info("Fetched live RFR for %s from FRED: %.4f", market, rfr)
        return rfr

    except Exception as exc:
        fallback = profile["rfr_fallback"]
        _rfr_cache[market] = (fallback, time.time(), _FAILURE_TTL_SECONDS)
        logger.warning(
            "FRED fetch failed for %s (%s). Caching fallback RFR %.4f for %ds.",
            market,
            exc,
            fallback,
            _FAILURE_TTL_SECONDS,
        )
        return fallback


def get_market_profile(market: str) -> dict:
    """Return the full market profile with a live risk-free rate.

    The returned dict contains all fields from ``MARKET_PROFILES`` with the
    ``risk_free_rate`` key updated to the live FRED value (or fallback).

    Args:
        market: ``'US'`` or ``'IN'``.

    Returns:
        A dict with keys: ``risk_free_rate``, ``market_return``, ``tax_rate``,
        ``currency``, ``symbol``, ``ticker_suffix``, ``benchmark``,
        ``fred_series``, ``rfr_fallback``.
    """
    market = market.upper()
    if market not in MARKET_PROFILES:
        raise ValueError(f"Unknown market '{market}'. Supported: {list(MARKET_PROFILES.keys())}")

    profile = dict(MARKET_PROFILES[market])  # shallow copy
    profile["risk_free_rate"] = get_live_risk_free_rate(market)
    return profile


def detect_market(ticker: str) -> str:
    """Auto-detect the market for a given ticker symbol.

    Logic:
        - If the ticker ends with ``.NS`` or ``.BO`` → ``'IN'`` (India).
        - Otherwise → ``'US'``.

    Args:
        ticker: A stock ticker string (e.g. ``'AAPL'``, ``'RELIANCE.NS'``).

    Returns:
        ``'US'`` or ``'IN'``.
    """
    ticker_upper = ticker.strip().upper()
    if ticker_upper.endswith(".NS") or ticker_upper.endswith(".BO"):
        return "IN"
    return "US"
