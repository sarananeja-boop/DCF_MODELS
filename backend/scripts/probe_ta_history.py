#!/usr/bin/env python3
"""
Phase 0C Diagnostic Spike (`backend/scripts/probe_ta_history.py`).

Measures `period="10y"` daily OHLCV + benchmark fetch across 10 representative
golden tickers (5 IN, 5 US):
  - Success rate (%)
  - Latency p50 / p95 (ms)
  - Payload size (KB)
  - Daily / weekly / monthly return bar counts & 6-feature coverage eligibility
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from engine.market_history import run_technical_probe


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 0C TA History 10Y Probe")
    parser.add_argument("--period", default="10y", help="History period to test ('10y' or '5y')")
    parser.add_argument("--json-out", default=None, help="Optional JSON output path")
    args = parser.parse_args()

    report = run_technical_probe(period=args.period)

    print("=" * 105)
    print(
        f"PHASE 0C TA HISTORY PROBE | Period: {report['period_tested']} | "
        f"Success: {report['success_count']}/{report['tickers_tested']} ({report['success_rate_pct']:.1f}%) | "
        f"p50: {report['latency_p50_ms']:.0f}ms | p95: {report['latency_p95_ms']:.0f}ms | "
        f"Avg Payload: {report['avg_payload_kb']:.1f} KB"
    )
    print("=" * 105)
    header = (
        f"{'Symbol':<13} {'Listing':<13} {'Mkt':<3} {'Bench':<6} "
        f"{'Bars(D/W/M)':<15} {'Splits':>6} {'Divs':>5} {'Qual':<9} "
        f"{'6/6 Cov':<7} {'Lat(ms)':>8} {'Size(KB)':>8}"
    )
    print(header)
    print("-" * 105)
    for r in report["results"]:
        if r.get("status") == "ok":
            bars_str = f"{r['observations']}/{r['weekly_observations']}/{r['monthly_return_observations']}"
            cov_str = "YES" if r["all_6_features_eligible"] else "NO"
            print(
                f"{r['symbol']:<13} {r['listing_used']:<13} {r['market']:<3} {r['benchmark']:<6} "
                f"{bars_str:<15} {r['splits_count']:>6} {r['dividends_count']:>5} "
                f"{r['quality_status']:<9} {cov_str:<7} {r['latency_ms']:>8.1f} {r['payload_kb']:>8.1f}"
            )
        else:
            print(f"{r['symbol']:<13} {'ERROR':<13} {r.get('market', ''):<3} {r.get('error', '')}")
    print("=" * 105)
    print(f"Recommended Default Period: {report['recommended_default_period']}")

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Saved probe report to {out_path}")

    return 0 if report["success_rate_pct"] >= 90.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
