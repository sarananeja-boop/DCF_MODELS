#!/usr/bin/env python3
"""
Generate `frontend/src/data/previewData.json` directly from the ValuationLabs
deterministic golden engine (`CESC.NS`, `HINDUNILVR.NS`, `AAPL`).

Guarantees that the landing-page Live Engine Showcase never drifts from actual
engine outputs and carries an explicit model version + snapshot date stamp.
"""

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from engine import MODEL_VERSION
from main import AnalyzeRequest, analyze
from tests.conftest import get_fixture_store


SHOWCASE_SPEC = [
    ("CESC", "CESC.NS", "IN", "🇮🇳 CESC (NSE)"),
    ("HINDUNILVR", "HINDUNILVR.NS", "IN", "🇮🇳 HUL (NSE)"),
    ("AAPL", "AAPL", "US", "🇺🇸 Apple (NASDAQ)"),
]


def _format_currency(val: float, sym: str, decimals: int = 2) -> str:
    if decimals == 0:
        return f"{sym}{val:,.0f}"
    return f"{sym}{val:,.{decimals}f}"


def generate_preview_payload() -> dict:
    store = get_fixture_store()
    payload = {}

    with store.patch_env(mode="normal"):
        for key, ticker, market, tab_label in SHOWCASE_SPEC:
            req = AnalyzeRequest(ticker=ticker, market=market, monte_carlo_iterations=2000)
            res = analyze(req)

            sym = "₹" if market == "IN" else "$"
            fair_val = float(res["dcf_result"]["implied_price"])
            curr_price = float(res["market_data"]["current_price"])
            upside_pct = round(((fair_val / curr_price) - 1.0) * 100.0, 1)

            if upside_pct >= 0:
                upside_badge = f"▲ {abs(upside_pct):.1f}% Undervalued"
                upside_note = f"Market Price is {abs(upside_pct):.1f}% below DCF Base Case"
            else:
                upside_badge = f"▼ {abs(upside_pct):.1f}% Overvalued"
                upside_note = f"Market Price is {abs(upside_pct):.1f}% above DCF Base Case"

            wacc_info = res["wacc"]
            wacc_pct = round(float(wacc_info["wacc"]) * 100.0, 1)
            ke_pct = round(float(wacc_info["cost_of_equity"]) * 100.0, 1)
            wd_pct = round(float(wacc_info.get("weight_debt", 0.0)) * 100.0)

            mc_stats = res["monte_carlo"]["stats"]
            p5_num = round(float(mc_stats["p5"]))
            p95_num = round(float(mc_stats["p95"]))

            payload[key] = {
                "ticker": ticker,
                "tabLabel": tab_label,
                "name": res["company"]["name"],
                "market": market,
                "currency": sym,
                "fairValue": _format_currency(fair_val, sym, 2),
                "fairValueNum": round(fair_val, 2),
                "currentPrice": _format_currency(curr_price, sym, 2),
                "currentPriceNum": round(curr_price, 2),
                "upsidePct": upside_pct,
                "upsideBadge": upside_badge,
                "upsideNote": upside_note,
                "wacc": f"{wacc_pct:.1f}%",
                "waccNum": round(float(wacc_info["wacc"]), 4),
                "waccNote": f"Ke: {ke_pct:.1f}% · Debt: {wd_pct}%",
                "mcRange": f"{_format_currency(p5_num, sym, 0)} – {_format_currency(p95_num, sym, 0)}",
                "p5Num": p5_num,
                "p95Num": p95_num,
                "verdict": res["verdict"]["verdict"],
                "modelVersion": f"v{MODEL_VERSION}",
                "snapshotDate": "2026-11-08",
            }

    return payload


def main():
    data = generate_preview_payload()
    out_path = ROOT_DIR / "frontend" / "src" / "data" / "previewData.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} with {len(data)} entries (Model v{MODEL_VERSION}).")


if __name__ == "__main__":
    main()
