#!/usr/bin/env python3
"""
Standalone CLI utility to synchronize `frontend/src/data/stocks.json`
with the live NSE Equity Master (`EQUITY_L.csv`) and SEC EDGAR (`company_tickers.json`).

Note: The FastAPI backend also runs this synchronization automatically in the
background and serves the live universe at `GET /api/universe`.
"""

import logging
from engine.ticker_universe import sync_live_universe

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    stocks = sync_live_universe(persist_to_disk=True)
    in_count = sum(1 for s in stocks if s.get("m") == "IN")
    us_count = sum(1 for s in stocks if s.get("m") == "US")
    print(f"Successfully synchronized {len(stocks)} active equities ({in_count} IN, {us_count} US).")
