#!/usr/bin/env python3
"""
Weekly Live Yahoo Finance Smoke & Cloud-Sim Parity Benchmark
============================================================
Hits live Yahoo Finance across the 36-ticker Golden Set (or `--quick` 8-ticker
smoke subset) in both:
  1. `normal` mode (full `yf.Ticker.info`)
  2. `cloud_sim` mode (`yf.Ticker.info` monkeypatched to `{}` to simulate Render IP)

Checks:
  - No crashes, NaNs, or negative implied prices
  - Live implied price within ±25% of `golden_baseline.json` (allowing for market price/quarter updates)
  - Cloud-sim parity within ±5% of live normal mode
  - Writes a dated JSON report to `backend/tests/live_reports/YYYY-MM-DD.json`
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import PropertyMock, patch

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import engine.data_layer as dl
import main as app_main
from main import AnalyzeRequest, analyze
from tests.conftest import BASELINE_PATH, GOLDEN_UNIVERSE

REPORTS_DIR = BACKEND_DIR / "tests" / "live_reports"

QUICK_SUBSET: List[Tuple[str, str]] = [
    ("RELIANCE.NS", "IN"),
    ("INFY.NS", "IN"),
    ("CESC.NS", "IN"),
    ("ONGC.NS", "IN"),
    ("HDFCBANK.NS", "IN"),
    ("AAPL", "US"),
    ("XOM", "US"),
    ("BYND", "US"),
]


def run_live_benchmark(quick: bool = False) -> Tuple[int, Dict[str, Any]]:
    universe = QUICK_SUBSET if quick else GOLDEN_UNIVERSE
    baseline = {}
    if BASELINE_PATH.exists():
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("modes", {}).get("normal", {})

    report: Dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "quick_mode": quick,
        "tickers": {},
        "alerts": [],
    }

    for idx, (ticker, market) in enumerate(universe, 1):
        print(f"[{idx:02d}/{len(universe):02d}] Live smoke: {ticker} ({market}) ...", flush=True)
        entry: Dict[str, Any] = {"market": market}
        try:
            dl._STOCK_DATA_CACHE.clear()
            app_main._ANALYZE_RESPONSE_CACHE.clear()
            np.random.seed(42)
            res_norm = analyze(AnalyzeRequest(ticker=ticker, market=market, monte_carlo_iterations=2000))
            iv_norm = float(res_norm["dcf_result"]["implied_price"])
            entry["normal_iv"] = iv_norm
            entry["current_price"] = float(res_norm["market_data"]["current_price"])
            entry["verdict"] = res_norm["verdict"]["verdict"]
            entry["sector"] = res_norm["company"].get("sector")

            # Cloud-sim run (patch yf.Ticker.info -> {})
            dl._STOCK_DATA_CACHE.clear()
            app_main._ANALYZE_RESPONSE_CACHE.clear()
            np.random.seed(42)
            with patch.object(dl.yf.Ticker, "info", new_callable=PropertyMock, return_value={}):
                res_cloud = analyze(AnalyzeRequest(ticker=ticker, market=market, monte_carlo_iterations=2000))
            iv_cloud = float(res_cloud["dcf_result"]["implied_price"])
            entry["cloud_sim_iv"] = iv_cloud
            entry["cloud_sim_sector"] = res_cloud["company"].get("sector")

            if not math.isfinite(iv_norm) or iv_norm < 0:
                report["alerts"].append(f"[INVALID IV] {ticker}: normal IV={iv_norm}")

            if iv_norm > 0:
                cloud_gap = abs(iv_cloud - iv_norm) / iv_norm
                entry["cloud_sim_gap_pct"] = round(cloud_gap * 100.0, 2)
                if cloud_gap > 0.05:
                    report["alerts"].append(
                        f"[CLOUD-SIM DRIFT] {ticker}: normal={iv_norm:.2f} vs cloud_sim={iv_cloud:.2f} ({cloud_gap*100:.1f}%)"
                    )

            base_rec = baseline.get(ticker)
            if base_rec and base_rec.get("implied_price", 0) > 0 and iv_norm > 0:
                b_iv = float(base_rec["implied_price"])
                drift = (iv_norm - b_iv) / b_iv
                entry["baseline_drift_pct"] = round(drift * 100.0, 2)
                if abs(drift) > 0.25:
                    report["alerts"].append(
                        f"[BASELINE DRIFT >25%] {ticker}: baseline={b_iv:.2f} vs live={iv_norm:.2f} ({drift*100:+.1f}%)"
                    )
        except Exception as exc:
            entry["error"] = str(exc)
            report["alerts"].append(f"[ERROR] {ticker}: {exc}")

        report["tickers"][ticker] = entry
        time.sleep(0.35)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.date.today().isoformat()
    out_file = REPORTS_DIR / f"{today_str}.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved live report -> {out_file}")
    if report["alerts"]:
        print("Alerts:")
        for a in report["alerts"]:
            print(f"  - {a}")
    return (1 if any(a.startswith("[ERROR]") or a.startswith("[INVALID") for a in report["alerts"]) else 0), report


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Yahoo Finance valuation smoke benchmark.")
    parser.add_argument("--quick", action="store_true", help="Run 8-ticker smoke subset instead of all 36.")
    args = parser.parse_args()
    code, _ = run_live_benchmark(quick=args.quick)
    return code


if __name__ == "__main__":
    sys.exit(main())
