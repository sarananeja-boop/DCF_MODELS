"""
Valuation Invariant Suite (Phase 0A Safety Net)
===============================================
Evaluates all 36 golden tickers across Indian (NSE) and US markets offline
using recorded fixtures in normal, cloud_sim, and cloud_blackout modes,
plus synthetic edge-case unit tests for illiquid beta, Excel-API parity,
and MODEL_VERSION consistency.
"""

from __future__ import annotations

import io
import math
import re
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import numpy as np
import openpyxl
import pandas as pd
import pytest

from engine import MODEL_VERSION
from engine.data_layer import compute_clean_beta
from export.excel_export import generate_excel_report
from main import AnalyzeRequest, analyze
from tests.conftest import GOLDEN_UNIVERSE, OfflineFixtureStore


# ---------------------------------------------------------------------------
# Module-scoped cached evaluation of normal & cloud_sim runs for speed
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def evaluated_universe(fixture_store: OfflineFixtureStore) -> Dict[str, Dict[str, Dict[str, Any]]]:
    results: Dict[str, Dict[str, Dict[str, Any]]] = {"normal": {}, "cloud_sim": {}}
    for mode in ("normal", "cloud_sim"):
        with fixture_store.patch_env(mode=mode):
            for ticker, market in GOLDEN_UNIVERSE:
                np.random.seed(42)
                req = AnalyzeRequest(
                    ticker=ticker,
                    market=market,
                    valuation_method="auto",
                    monte_carlo_iterations=2000,
                )
                results[mode][ticker] = analyze(req)
    return results


@pytest.mark.parametrize("ticker,market", GOLDEN_UNIVERSE)
def test_invariant_1_finite_and_plausible_implied_price(
    ticker: str, market: str, evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    res = evaluated_universe["normal"][ticker]
    iv = float(res["dcf_result"]["implied_price"])
    curr_p = float(res["market_data"]["current_price"])
    verdict = str(res["verdict"]["verdict"])

    assert math.isfinite(iv), f"{ticker}: implied_price is not finite"
    assert iv >= 0.0, f"{ticker}: implied_price {iv} is negative"

    if ticker == "BYND":
        # Structural negative-EBIT distressed issuer
        assert iv == 0.0
        assert "DISTRESSED" in verdict or "UNRELIABLE" in verdict
    else:
        assert iv > 0.0, f"{ticker}: healthy issuer produced 0 implied_price"
        ratio = iv / curr_p
        assert 0.10 <= ratio <= 4.0, (
            f"{ticker}: IV/Price ratio {ratio:.2f}x outside plausible [0.10x, 4.0x] band (IV={iv}, Price={curr_p})"
        )


@pytest.mark.parametrize("ticker,market", GOLDEN_UNIVERSE)
def test_invariant_2_currency_scale_ratio(
    ticker: str, market: str, evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    res = evaluated_universe["normal"][ticker]
    mcap = float(res["market_data"]["market_cap"])
    hist_rev = res["historicals"]["revenue"]
    assert len(hist_rev) > 0 and mcap > 0
    latest_rev = float(hist_rev[-1])
    rev_to_mcap = latest_rev / mcap
    assert 0.015 <= rev_to_mcap <= 15.0, (
        f"{ticker}: revenue/market_cap ratio {rev_to_mcap:.4f} indicates unscaled currency or unit mismatch"
    )


@pytest.mark.parametrize("ticker,market", GOLDEN_UNIVERSE)
def test_invariant_3_ev_ebitda_plausibility(
    ticker: str, market: str, evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    res = evaluated_universe["normal"][ticker]
    if res["diagnostics"]["is_financial"] or ticker == "BYND":
        return
    val = res["validation"]
    imp_mult = val.get("model_multiple")
    assert imp_mult is not None and math.isfinite(float(imp_mult))
    # Must either be within [1.0, 80.0] or explicitly flagged by validation status
    assert (1.0 <= float(imp_mult) <= 80.0) or val.get("status") in ("WARNING", "FLAG"), (
        f"{ticker}: implied multiple {imp_mult} outside [1, 80] without validation warning/flag"
    )


@pytest.mark.parametrize("ticker,market", GOLDEN_UNIVERSE)
def test_invariant_4_terminal_reinvestment_law(
    ticker: str, market: str, evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    res = evaluated_universe["normal"][ticker]
    if res["diagnostics"]["is_equity_model"] or ticker == "BYND":
        return

    dcf_res = res["dcf_result"]
    reinv = float(dcf_res["terminal_reinv_rate"])
    roic_reinv = float(dcf_res["roic_reinv"])
    is_high_roic = bool(dcf_res["is_high_roic"])
    is_extractive = bool(dcf_res["is_extractive"])
    is_cyclical = bool(dcf_res["is_cyclical"])

    assert 0.06 <= reinv <= 0.80, f"{ticker}: terminal_reinv_rate {reinv:.4f} outside [0.06, 0.80]"

    # Regulated utilities and standard non-high-ROIC, non-extractive, non-cyclical firms
    # MUST strictly follow g / sustainable_roic (clamped to [0.10, 0.80]) without CapEx/NWC dilution
    if not is_high_roic and not is_extractive and not is_cyclical:
        expected = min(0.80, max(0.10, roic_reinv))
        assert reinv == pytest.approx(expected, abs=1e-6), (
            f"{ticker}: non-compounder terminal_reinv_rate {reinv:.4f} != clamped g/ROIC {expected:.4f}"
        )


@pytest.mark.parametrize("ticker,market", GOLDEN_UNIVERSE)
def test_invariant_5_monte_carlo_ordering_and_median_alignment(
    ticker: str, market: str, evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    res = evaluated_universe["normal"][ticker]
    mc = res["monte_carlo"]
    stats = mc["stats"]

    p5 = float(stats["p5"])
    p25 = float(stats["p25"])
    med = float(stats["median"])
    p75 = float(stats["p75"])
    p95 = float(stats["p95"])

    assert p5 <= p25 <= med <= p75 <= p95, (
        f"{ticker}: MC quantiles out of order: p5={p5}, p25={p25}, med={med}, p75={p75}, p95={p95}"
    )

    actual_iters = int(mc["actual_iterations"])
    valid_sims = int(mc["valid_simulations"])
    assert actual_iters >= 1500
    assert valid_sims >= 1500

    iv = float(res["dcf_result"]["implied_price"])
    if iv > 0:
        rel_gap = abs(med - iv) / iv
        assert rel_gap <= 0.15, (
            f"{ticker}: MC median ({med:.2f}) diverges from Base IV ({iv:.2f}) by {rel_gap*100:.1f}% (>15%)"
        )


@pytest.mark.parametrize("ticker,market", GOLDEN_UNIVERSE)
def test_invariant_6_sensitivity_center_cell_matches_iv(
    ticker: str, market: str, evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    res = evaluated_universe["normal"][ticker]
    iv = float(res["dcf_result"]["implied_price"])
    if iv <= 0:
        return

    gw_grid = res["sensitivity"]["growth_wacc"]["price_grid"]
    mw_grid = res["sensitivity"]["margin_wacc"]["price_grid"]

    center_gw = float(gw_grid[len(gw_grid) // 2][len(gw_grid[0]) // 2])
    center_mw = float(mw_grid[len(mw_grid) // 2][len(mw_grid[0]) // 2])

    assert abs(center_gw - iv) / iv <= 0.005, (
        f"{ticker}: growth_wacc center cell {center_gw} != implied_price {iv}"
    )
    assert abs(center_mw - iv) / iv <= 0.005, (
        f"{ticker}: margin_wacc center cell {center_mw} != implied_price {iv}"
    )


@pytest.mark.parametrize("ticker,market", GOLDEN_UNIVERSE)
def test_invariant_7_cross_model_reconciliation_present(
    ticker: str, market: str, evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    res = evaluated_universe["normal"][ticker]
    if res["diagnostics"]["is_financial"]:
        # Balance-sheet financial institutions use BANKING_DDM + Justified P/B cross-check
        assert res["dcf_result"].get("justified_pb") is not None
        assert res["dcf_result"].get("justified_price") is not None
        return
    recon = res.get("method_comparison")
    assert isinstance(recon, dict), f"{ticker}: missing method_comparison"
    assert "fcff_implied_price" in recon
    assert "ddm_implied_price" in recon
    assert "ddm_justified_price" in recon
    assert math.isfinite(float(recon["fcff_implied_price"]))
    assert math.isfinite(float(recon["ddm_implied_price"]))


@pytest.mark.parametrize("ticker,market", GOLDEN_UNIVERSE)
def test_invariant_8_cloud_sim_parity(
    ticker: str, market: str, evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    norm_res = evaluated_universe["normal"][ticker]
    cloud_res = evaluated_universe["cloud_sim"][ticker]

    norm_iv = float(norm_res["dcf_result"]["implied_price"])
    cloud_iv = float(cloud_res["dcf_result"]["implied_price"])

    assert cloud_res["company"]["sector"] is not None, (
        f"{ticker}: sector became None in cloud_sim mode"
    )
    assert cloud_res["verdict"]["verdict"] == norm_res["verdict"]["verdict"], (
        f"{ticker}: verdict flipped from {norm_res['verdict']['verdict']} to {cloud_res['verdict']['verdict']} in cloud_sim"
    )
    if norm_iv > 0:
        rel_diff = abs(cloud_iv - norm_iv) / norm_iv
        assert rel_diff <= 0.05, (
            f"{ticker}: cloud_sim IV ({cloud_iv:.2f}) diverged {rel_diff*100:.2f}% from normal IV ({norm_iv:.2f})"
        )


def test_cloud_blackout_foreign_adr_nvo(fixture_store: OfflineFixtureStore) -> None:
    with fixture_store.patch_env(mode="normal"):
        norm_res = analyze(AnalyzeRequest(ticker="NVO", market="US", monte_carlo_iterations=1000))
    with fixture_store.patch_env(mode="cloud_blackout"):
        blk_res = analyze(AnalyzeRequest(ticker="NVO", market="US", monte_carlo_iterations=1000))

    norm_iv = float(norm_res["dcf_result"]["implied_price"])
    blk_iv = float(blk_res["dcf_result"]["implied_price"])
    assert abs(blk_iv - norm_iv) / norm_iv <= 0.15


def test_illiquid_and_thin_trading_beta_fallbacks(fixture_store: OfflineFixtureStore) -> None:
    """Verify flat-price (<15 unique prices), high zero-volume (>30%), and short history (<15 weekly bars)
    trigger bottom-up Hamada + Blume beta."""
    mock_stock = MagicMock()
    dates_2y = pd.date_range("2024-01-01", periods=500, freq="B")

    # Case 1: Flat-price series (<15 unique prices) -> is_illiquid=True
    flat_df = pd.DataFrame(
        {"Close": np.full(500, 100.0), "Volume": np.full(500, 50000.0)},
        index=dates_2y,
    )
    res_flat = compute_clean_beta(
        stock=mock_stock,
        ticker="FLAT.BO",
        market="IN",
        raw_info_beta=0.12,
        sector="Industrials",
        industry="Building Products",
        de_ratio=0.5,
        tax_rate=0.2517,
        tradeable=True,
        hist_1y=flat_df.iloc[-252:],
        hist_2y=flat_df,
    )
    assert res_flat["is_illiquid"] is True
    assert res_flat["beta"] > 0.70

    # Case 2: Thin small-cap (>30% zero-volume days) -> is_illiquid=True
    vols = np.where(np.arange(500) % 2 == 0, 0.0, 1000.0)
    thin_df = pd.DataFrame(
        {"Close": np.linspace(100.0, 150.0, 500), "Volume": vols},
        index=dates_2y,
    )
    res_thin = compute_clean_beta(
        stock=mock_stock,
        ticker="THIN.NS",
        market="IN",
        raw_info_beta=0.20,
        sector="Technology",
        industry="Software",
        de_ratio=0.1,
        tax_rate=0.2517,
        tradeable=True,
        hist_1y=thin_df.iloc[-252:],
        hist_2y=thin_df,
    )
    assert res_thin["is_illiquid"] is True
    assert res_thin["beta"] > 0.80

    # Case 3: Recent IPO (<15 weekly bars, no info beta) -> falls back to bottom-up Hamada + Blume beta
    ipo_dates = pd.date_range("2026-01-01", periods=10, freq="W")
    ipo_df = pd.DataFrame(
        {"Close": np.linspace(200.0, 240.0, 10), "Volume": np.full(10, 100000.0)},
        index=ipo_dates,
    )
    with fixture_store.patch_env(mode="normal"):
        res_ipo = compute_clean_beta(
            stock=mock_stock,
            ticker="NEWIPO.NS",
            market="IN",
            raw_info_beta=None,
            sector="Consumer Defensive",
            industry="Packaged Foods",
            de_ratio=0.2,
            tax_rate=0.2517,
            tradeable=True,
            hist_1y=ipo_df,
            hist_2y=ipo_df,
        )
    assert res_ipo["beta_clamped"] is True
    assert "bottom-up industry unlevered beta" in res_ipo["beta_note"]
    assert 0.70 <= res_ipo["beta"] <= 1.50


@pytest.mark.parametrize("ticker", ["RELIANCE.NS", "AAPL", "HDFCBANK.NS"])
def test_excel_export_reconciles_with_api_payload(
    ticker: str, evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    data = evaluated_universe["normal"][ticker]
    buf = generate_excel_report(data)
    wb = openpyxl.load_workbook(io.BytesIO(buf.getvalue()), data_only=False)

    assert "Cover" in wb.sheetnames
    cover = wb["Cover"]

    cover_values = []
    for row in cover.iter_rows(values_only=True):
        for cell in row:
            if cell is not None:
                cover_values.append(str(cell))
    joined_cover = " | ".join(cover_values)

    assert data["company"]["ticker"] in joined_cover
    assert data["verdict"]["verdict"] in joined_cover
    assert MODEL_VERSION in joined_cover


def test_single_model_version_policy_consistency(
    evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    sample = evaluated_universe["normal"]["AAPL"]
    assert sample["metadata"]["model_version"] == MODEL_VERSION

    fe_version_path = (
        Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "version.js"
    )
    fe_text = fe_version_path.read_text(encoding="utf-8")
    m = re.search(r"MODEL_VERSION\s*=\s*['\"]([^'\"]+)['\"]", fe_text)
    assert m is not None, "MODEL_VERSION not found in frontend/src/version.js"
    assert m.group(1) == MODEL_VERSION


def test_landing_preview_matches_golden_engine(
    evaluated_universe: Dict[str, Dict[str, Dict[str, Any]]]
) -> None:
    import json

    preview_path = (
        Path(__file__).resolve().parent.parent.parent
        / "frontend"
        / "src"
        / "data"
        / "previewData.json"
    )
    assert preview_path.exists(), "frontend/src/data/previewData.json must exist"
    preview_data = json.loads(preview_path.read_text(encoding="utf-8"))

    mapping = {
        "CESC": "CESC.NS",
        "HINDUNILVR": "HINDUNILVR.NS",
        "AAPL": "AAPL",
    }
    for key, ticker in mapping.items():
        assert key in preview_data, f"{key} missing from previewData.json"
        item = preview_data[key]
        golden = evaluated_universe["normal"][ticker]

        assert item["modelVersion"] == f"v{MODEL_VERSION}"
        assert item["fairValueNum"] == pytest.approx(golden["dcf_result"]["implied_price"], abs=0.02)
        assert item["currentPriceNum"] == pytest.approx(golden["market_data"]["current_price"], abs=0.02)
        assert item["waccNum"] == pytest.approx(golden["wacc"]["wacc"], abs=0.0005)
        assert item["p5Num"] == round(float(golden["monte_carlo"]["stats"]["p5"]))
        assert item["p95Num"] == round(float(golden["monte_carlo"]["stats"]["p95"]))
        assert item["verdict"] == golden["verdict"]["verdict"]


def test_excel_reconciles_api_with_overrides(fixture_store: Any) -> None:
    from main import AnalyzeRequest, Overrides, analyze

    with fixture_store.patch_env(mode="normal"):
        req = AnalyzeRequest(
            ticker="AAPL",
            market="US",
            overrides=Overrides(
                revenue_growth=0.125,
                ebit_margin=0.335,
                wacc=0.095,
                terminal_growth=0.028,
            ),
            monte_carlo_iterations=2000,
        )
        res = analyze(req)

    buf = generate_excel_report(res)
    wb = openpyxl.load_workbook(io.BytesIO(buf.getvalue()), data_only=False)
    cover = wb["Cover"]

    kv_pairs = {}
    for row in cover.iter_rows(values_only=True):
        if row and len(row) >= 3 and row[1] is not None:
            kv_pairs[str(row[1]).strip()] = row[2]

    assert kv_pairs.get("Assumption Override Status") == "Custom User Overrides Applied"
    assert "Applied: 12.5% (Edited)" in str(kv_pairs.get("Year-1 Revenue Growth (Default vs. Applied)"))
    assert "Applied: 33.5% (Edited)" in str(kv_pairs.get("Target Operating Margin (Default vs. Applied)"))
    assert "Applied: 9.5% (Edited)" in str(kv_pairs.get("Discount Rate / WACC (Default vs. Applied)"))
    assert "Applied: 2.8% (Edited)" in str(kv_pairs.get("Terminal Growth Rate (Default vs. Applied)"))
    assert kv_pairs.get("DCF Implied Fair Value (FCFF Base Case)") == pytest.approx(
        res["dcf_result"]["implied_price"], abs=0.01
    )
    assert kv_pairs.get("Retained Valid Simulations") == res["monte_carlo"]["valid_simulations"]
    assert kv_pairs.get("Random Seed & Reproducibility Policy") == "Deterministic Cholesky (Seed = 42)"

