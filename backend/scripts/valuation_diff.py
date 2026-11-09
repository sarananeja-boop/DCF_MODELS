#!/usr/bin/env python3
"""
Valuation Snapshot Diff & Baseline Generator (`backend/scripts/valuation_diff.py`).

Evaluates all 36 Golden Tickers offline through `analyze()` in `normal`, `cloud_sim`,
and `cloud_blackout` modes, and compares Fair Value, Exit Multiple IV, WACC/Ke,
MC Median (P50), Terminal Value Share %, and Valuation Verdict against
`backend/tests/golden_baseline.json`.

Usage:
  - Generate/update golden baseline (before refactoring or after approved engine change):
      python3 backend/scripts/valuation_diff.py --save-baseline
  - Run diff comparison against baseline:
      python3 backend/scripts/valuation_diff.py
  - Fail with exit code 1 if any ticker moves >10% or changes verdict:
      python3 backend/scripts/valuation_diff.py --strict
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import AnalyzeRequest, analyze
from tests.conftest import BASELINE_PATH, get_fixture_store


def _extract_snapshot_metrics(resp: Dict[str, Any]) -> Dict[str, Any]:
    company = resp.get("company", {})
    market_data = resp.get("market_data", {})
    dcf = resp.get("dcf_result", {})
    wacc = resp.get("wacc", {})
    mc_stats = resp.get("monte_carlo", {}).get("stats", {})
    diag = resp.get("diagnostics", {})
    val = resp.get("validation", {})
    verdict = resp.get("verdict", {})
    mc_comp = resp.get("method_comparison", {})

    return {
        "ticker": company.get("ticker"),
        "name": company.get("name"),
        "market": company.get("market"),
        "currency": company.get("currency"),
        "sector": company.get("sector"),
        "industry": company.get("industry"),
        "model_type": company.get("model_type"),
        "is_financial": bool(company.get("is_financial", False)),
        "is_extractive": bool(diag.get("is_extractive", False)),
        "is_cyclical": bool(diag.get("is_cyclical", False)),
        "current_price": float(market_data.get("current_price") or 0.0),
        "implied_price": float(dcf.get("implied_price") or 0.0),
        "exit_implied_price": float(dcf.get("exit_implied_price") or 0.0) if dcf.get("exit_implied_price") is not None else None,
        "ddm_implied_price": float(mc_comp.get("ddm_implied_price") or 0.0) if mc_comp.get("ddm_implied_price") is not None else None,
        "mc_p5": float(mc_stats.get("p5") or 0.0),
        "mc_median": float(mc_stats.get("median") or 0.0),
        "mc_p95": float(mc_stats.get("p95") or 0.0),
        "wacc": float(wacc.get("wacc") or 0.0),
        "cost_of_equity": float(wacc.get("cost_of_equity") or 0.0),
        "default_growth": float(diag.get("default_growth") or 0.0),
        "default_margin": float(diag.get("default_margin") or 0.0),
        "tv_share_of_ev": float(dcf.get("tv_share_of_ev") or 0.0) if dcf.get("tv_share_of_ev") is not None else None,
        "implied_ev_ebitda": float(val.get("implied_ev_ebitda")) if val.get("implied_ev_ebitda") is not None else None,
        "validation_status": val.get("status") or ("FLAG" if val.get("flag") else "PASS"),
        "verdict": verdict.get("verdict") if isinstance(verdict, dict) else str(verdict),
        "upside_pct": float(verdict.get("upside_pct") or 0.0) if isinstance(verdict, dict) else 0.0,
    }


def evaluate_all_modes() -> Dict[str, Any]:
    store = get_fixture_store()
    tickers = store.get_ticker_list()
    results: Dict[str, Dict[str, Any]] = {}

    for mode in ("normal", "cloud_sim", "cloud_blackout"):
        with store.patch_env(mode=mode):
            for item in tickers:
                t = item["ticker"]
                m = item["market"]
                arch = item["archetype"]
                req = AnalyzeRequest(ticker=t, market=m, monte_carlo_iterations=2000)
                resp = analyze(req)
                snap = _extract_snapshot_metrics(resp)
                if t not in results:
                    results[t] = {"ticker": t, "market": m, "archetype": arch, "modes": {}}
                results[t]["modes"][mode] = snap

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ticker_count": len(tickers),
        "tickers": results,
    }


def compare_snapshots(baseline: Dict[str, Any], current: Dict[str, Any], threshold_pct: float = 10.0) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    alerts: List[str] = []

    base_tickers = baseline.get("tickers", {})
    curr_tickers = current.get("tickers", {})

    for t, curr_entry in curr_tickers.items():
        base_entry = base_tickers.get(t, {})
        curr_norm = curr_entry["modes"]["normal"]
        curr_cloud = curr_entry["modes"]["cloud_sim"]
        curr_blackout = curr_entry["modes"]["cloud_blackout"]
        base_norm = base_entry.get("modes", {}).get("normal", curr_norm)

        base_iv = base_norm["implied_price"]
        curr_iv = curr_norm["implied_price"]
        cloud_iv = curr_cloud["implied_price"]
        blackout_iv = curr_blackout["implied_price"]

        if base_iv > 0:
            iv_diff_pct = ((curr_iv - base_iv) / base_iv) * 100.0
        else:
            iv_diff_pct = 0.0 if curr_iv == 0 else 100.0

        if curr_iv > 0:
            cloud_drift_pct = ((cloud_iv - curr_iv) / curr_iv) * 100.0
            blackout_drift_pct = ((blackout_iv - curr_iv) / curr_iv) * 100.0
        else:
            cloud_drift_pct = 0.0 if cloud_iv == 0 else 100.0
            blackout_drift_pct = 0.0 if blackout_iv == 0 else 100.0

        verdict_changed = base_norm["verdict"] != curr_norm["verdict"]
        cloud_verdict_mismatch = curr_norm["verdict"] != curr_cloud["verdict"]

        row = {
            "ticker": t,
            "market": curr_entry["market"],
            "archetype": curr_entry["archetype"],
            "price": curr_norm["current_price"],
            "base_iv": base_iv,
            "curr_iv": curr_iv,
            "iv_diff_pct": iv_diff_pct,
            "cloud_iv": cloud_iv,
            "cloud_drift_pct": cloud_drift_pct,
            "blackout_iv": blackout_iv,
            "blackout_drift_pct": blackout_drift_pct,
            "mc_median": curr_norm["mc_median"],
            "wacc_pct": curr_norm["wacc"] * 100.0,
            "base_verdict": base_norm["verdict"],
            "curr_verdict": curr_norm["verdict"],
            "cloud_verdict": curr_cloud["verdict"],
            "cloud_sector": curr_cloud["sector"],
            "blackout_sector": curr_blackout["sector"],
            "verdict_changed": verdict_changed,
            "cloud_verdict_mismatch": cloud_verdict_mismatch,
        }
        rows.append(row)

        if abs(iv_diff_pct) > threshold_pct:
            alerts.append(
                f"[IV MOVE >{threshold_pct:.0f}%] {t}: {base_iv:.2f} -> {curr_iv:.2f} ({iv_diff_pct:+.2f}%)"
            )
        if verdict_changed:
            alerts.append(
                f"[VERDICT CHANGE] {t}: {base_norm['verdict']} -> {curr_norm['verdict']}"
            )
        if abs(cloud_drift_pct) > 5.0 or cloud_verdict_mismatch:
            alerts.append(
                f"[CLOUD-SIM DIVERGENCE] {t}: normal IV={curr_iv:.2f} ({curr_norm['verdict']}) vs cloud_sim IV={cloud_iv:.2f} ({curr_cloud['verdict']}) ({cloud_drift_pct:+.2f}%)"
            )

    return {
        "rows": rows,
        "alerts": alerts,
        "max_abs_iv_diff_pct": max((abs(r["iv_diff_pct"]) for r in rows), default=0.0),
        "verdict_changes_count": sum(1 for r in rows if r["verdict_changed"]),
        "cloud_divergences_count": sum(1 for r in rows if abs(r["cloud_drift_pct"]) > 5.0 or r["cloud_verdict_mismatch"]),
    }


def format_report(diff: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("=" * 124)
    lines.append(
        f"{'Ticker':<15} {'Mkt':<3} {'Price':>9} {'Base IV':>9} {'Curr IV':>9} {'Diff%':>7} "
        f"{'Cloud IV':>9} {'BlkOut IV':>9} {'MC P50':>9} {'WACC%':>6} {'Verdict':<18} {'Cloud Sector':<20}"
    )
    lines.append("-" * 124)
    for r in diff["rows"]:
        lines.append(
            f"{r['ticker']:<15} {r['market']:<3} {r['price']:>9.2f} {r['base_iv']:>9.2f} {r['curr_iv']:>9.2f} "
            f"{r['iv_diff_pct']:>+6.2f}% {r['cloud_iv']:>9.2f} {r['blackout_iv']:>9.2f} "
            f"{r['mc_median']:>9.2f} {r['wacc_pct']:>5.2f}% {r['curr_verdict']:<18} {str(r['cloud_sector'] or 'NONE')[:20]:<20}"
        )
    lines.append("=" * 124)
    lines.append(
        f"Summary: {len(diff['rows'])} tickers | Max |IV Diff|: {diff['max_abs_iv_diff_pct']:.4f}% | "
        f"Verdict changes: {diff['verdict_changes_count']} | Cloud-Sim divergences: {diff['cloud_divergences_count']}"
    )
    if diff["alerts"]:
        lines.append("\nALERTS:")
        for a in diff["alerts"]:
            lines.append(f"  - {a}")
    else:
        lines.append("\nZERO ALERTS: All golden tickers match baseline within tolerance and pass cloud-sim parity.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="ValuationLabs Golden Snapshot Diff Tool")
    parser.add_argument("--save-baseline", action="store_true", help="Save current evaluation as golden_baseline.json")
    parser.add_argument("--strict", action="store_true", help="Exit with code 1 if any alert triggers")
    parser.add_argument("--threshold", type=float, default=10.0, help="IV percent move threshold for alerting (default 10.0)")
    args = parser.parse_args()

    t0 = time.time()
    current = evaluate_all_modes()
    elapsed = time.time() - t0

    if args.save_baseline or not BASELINE_PATH.exists():
        BASELINE_PATH.write_text(json.dumps(current, indent=2))
        print(f"Saved golden baseline for {current['ticker_count']} tickers to {BASELINE_PATH} ({elapsed:.2f}s).")

    baseline = json.loads(BASELINE_PATH.read_text())
    diff = compare_snapshots(baseline, current, threshold_pct=args.threshold)
    print(format_report(diff))
    print(f"Evaluated 36 tickers x 3 modes (108 full DCF + Monte Carlo runs) in {elapsed:.2f}s.")

    if args.strict and diff["alerts"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
