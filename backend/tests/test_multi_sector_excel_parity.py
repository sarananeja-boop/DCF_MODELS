"""
Multi-Sector Formula Branch, Interaction, & Real LibreOffice Calc Parity Suite
=============================================================================
Covers all sector archetypes, edge combinations (Negative EBIT, High CapEx,
Extractive ARO Provisions, Cyclical Betas & Blends, NCI + Preferred Stock,
ASC 842 vs Ind AS 116 Leases, Capital-Light Financials, Commercial Bank vs NBFC
separation, Dynamic Schedule III Notes, Fail-Closed Insurance/REIT), AND verifies
100% Python-vs-Excel parity after recalculation through real LibreOffice Calc
(`soffice --headless --convert-to xlsx`) with scale-aware tolerances.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Tuple

import openpyxl
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from engine.canonical_schema import classify_model_suitability
from engine.primary_filings import extract_ind_as_ar_financials
from engine.validators import evaluate_validation_status, run_accounting_reconciliations
from export.excel_export import generate_excel_report
from main import app

LIBREOFFICE_BIN = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")


def _libreoffice_recalc(xlsx_bytes: bytes) -> openpyxl.Workbook:
    """Write `.xlsx`, recalculate every cell via LibreOffice Calc, and reopen with data_only=True."""
    assert LIBREOFFICE_BIN.exists(), f"LibreOffice Calc missing at {LIBREOFFICE_BIN}"
    with tempfile.TemporaryDirectory(prefix="vl_lo_recalc_") as tmp:
        src = Path(tmp) / "input.xlsx"
        out_dir = Path(tmp) / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        src.write_bytes(xlsx_bytes)
        proc = subprocess.run(
            [
                str(LIBREOFFICE_BIN),
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--convert-to",
                "xlsx",
                "--outdir",
                str(out_dir),
                str(src),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, f"LibreOffice conversion failed: {proc.stderr}\n{proc.stdout}"
        out_file = out_dir / "input.xlsx"
        assert out_file.exists(), f"LibreOffice output missing: {out_dir}"
        return openpyxl.load_workbook(out_file, data_only=True)


def _assert_zero_excel_errors(wb_vals: openpyxl.Workbook, wb_forms: openpyxl.Workbook) -> None:
    err_prefixes = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "Err:")
    for name in wb_forms.sheetnames:
        sf, sv = wb_forms[name], wb_vals[name]
        for r in range(1, sf.max_row + 1):
            for c in range(1, sf.max_column + 1):
                fv = sf.cell(r, c).value
                vv = sv.cell(r, c).value
                if isinstance(fv, str) and fv.startswith("="):
                    coord = f"{name}!{openpyxl.utils.get_column_letter(c)}{r}"
                    assert vv is not None, f"Uncached / None formula value at {coord} (formula={fv})"
                    assert not (isinstance(vv, str) and vv.startswith(err_prefixes)), (
                        f"Spreadsheet engine error {vv!r} at {coord} (formula={fv})"
                    )


def _find_cell_by_label(ws: Any, label: str, label_col: int = 2, val_col: int = 4) -> Any:
    for r in range(1, ws.max_row + 1):
        if str(ws.cell(r, label_col).value or "").strip() == label:
            return ws.cell(r, val_col).value
    raise AssertionError(f"Label {label!r} not found on sheet {ws.title}")


def _assert_close_scaled(actual: float, expected: float, kind: str, label: str) -> None:
    """Apply unit-appropriate numerical tolerances rather than a single global constant."""
    assert actual is not None, f"Missing value for {label}"
    a = float(actual)
    e = float(expected)
    if kind == "price":
        tol = 0.01
    elif kind == "rate":
        tol = 1e-5
    elif kind == "currency":
        tol = max(1.0, abs(e) * 1e-4)
    else:
        raise ValueError(f"Unknown kind: {kind}")
    assert abs(a - e) <= tol, f"{label}: Calc={a} vs Python={e} (diff={abs(a-e)}, tol={tol})"


def _build_corporate_stock_data(
    *,
    ticker: str,
    name: str,
    market: str,
    sector: str,
    industry: str,
    is_extractive: bool = False,
    is_cyclical: bool = False,
    cyclical_beta_low_flag: bool = False,
    is_cap_light_fin: bool = False,
    acct_std: str = "US_GAAP",
    beta: float = 1.05,
    raw_beta: float = 1.05,
    sector_bottom_up_beta: float = 1.15,
    price: float = 100.0,
    shares: float = 100_000_000.0,
    revs: Tuple[float, ...] = (8e9, 8.8e9, 9.6e9, 10.5e9),
    ebit_margins: Tuple[float, ...] = (0.18, 0.19, 0.20, 0.21),
    dna_pct: float = 0.04,
    capex_pct: float = 0.05,
    cf_dna_mult: float = 1.0,
    debt: float = 1.5e9,
    leases: float = 2e8,
    cash: float = 1.0e9,
    lt_provisions: float = 0.0,
    cwip: float = 0.0,
    minority: float = 0.0,
    preferred: float = 0.0,
    sec_aro: float | None = None,
    goodwill: float = 1e8,
) -> Dict[str, Any]:
    dates = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])
    rev_desc = list(reversed(revs))
    m_desc = list(reversed(ebit_margins))
    ebit_desc = [r * m for r, m in zip(rev_desc, m_desc)]
    dna_desc = [r * dna_pct for r in rev_desc]
    cf_dna_desc = [d * cf_dna_mult for d in dna_desc]
    capex_desc = [-r * capex_pct for r in rev_desc]
    int_exp_desc = [max(0.0, debt * 0.05)] * 4
    pretax_desc = [e - i for e, i in zip(ebit_desc, int_exp_desc)]
    tax_r = 0.25 if market == "IN" else 0.21
    tax_desc = [max(0.0, p * tax_r) for p in pretax_desc]
    pat_desc = [p - t for p, t in zip(pretax_desc, tax_desc)]
    min_inc_desc = [p * 0.05 if minority > 0 else 0.0 for p in pat_desc]
    ni_desc = [p - m for p, m in zip(pat_desc, min_inc_desc)]
    cogs_desc = [r * 0.55 for r in rev_desc]
    gp_desc = [r - c for r, c in zip(rev_desc, cogs_desc)]
    sga_desc = [g - e for g, e in zip(gp_desc, ebit_desc)]

    inc = pd.DataFrame(
        {
            "Total Revenue": rev_desc,
            "Cost Of Revenue": cogs_desc,
            "Gross Profit": gp_desc,
            "Selling General And Administration": sga_desc,
            "Operating Income": ebit_desc,
            "EBIT": ebit_desc,
            "Depreciation And Amortization In Income Statement": dna_desc,
            "Interest Expense": int_exp_desc,
            "Pretax Income": pretax_desc,
            "Tax Provision": tax_desc,
            "Net Income Continuous Operations": pat_desc,
            "Minority Interests": min_inc_desc,
            "Net Income": ni_desc,
            "EBITDA": [e + d for e, d in zip(ebit_desc, dna_desc)],
            "Normalized EBITDA": [e + d for e, d in zip(ebit_desc, dna_desc)],
            "Basic Average Shares": [shares] * 4,
            "Diluted Average Shares": [shares] * 4,
            "Basic EPS": [ni / shares for ni in ni_desc],
            "Diluted EPS": [ni / shares for ni in ni_desc],
        },
        index=dates,
    )

    eq_base = max(2e9, rev_desc[0] * 0.50)
    ar_desc = [r * 0.14 for r in rev_desc]
    inv_desc = [r * 0.08 for r in rev_desc]
    ca_desc = [cash + ar + inv for ar, inv in zip(ar_desc, inv_desc)]
    ppe_desc = [max(1e8, r * 0.45 - cwip) for r in rev_desc]
    ta_desc = [ca + ppe + cwip + goodwill for ca, ppe in zip(ca_desc, ppe_desc)]
    ap_desc = [r * 0.12 for r in rev_desc]
    st_debt = debt * 0.20
    lt_debt = max(0.0, debt - st_debt - leases)
    cl_desc = [ap + st_debt for ap in ap_desc]
    tot_liab = [cl + lt_debt + leases + lt_provisions for cl in cl_desc]
    # Balance exactly: Assets = Liabilities + Equity Gross MI
    eq_desc = [ta - tl - minority - preferred for ta, tl in zip(ta_desc, tot_liab)]
    common_stk = [e * 0.10 for e in eq_desc]
    ret_earn = [e * 0.90 for e in eq_desc]

    bs = pd.DataFrame(
        {
            "Total Assets": ta_desc,
            "Current Assets": ca_desc,
            "Cash And Cash Equivalents": [cash * 0.8] * 4,
            "Other Short Term Investments": [cash * 0.2] * 4,
            "Cash Cash Equivalents And Short Term Investments": [cash] * 4,
            "Accounts Receivable": ar_desc,
            "Inventory": inv_desc,
            "Net PPE": ppe_desc,
            "Construction In Progress": [cwip] * 4,
            "Goodwill And Other Intangible Assets": [goodwill] * 4,
            "Total Non Current Assets": [ta - ca for ta, ca in zip(ta_desc, ca_desc)],
            "Current Liabilities": cl_desc,
            "Accounts Payable": ap_desc,
            "Current Debt": [st_debt] * 4,
            "Long Term Debt": [lt_debt] * 4,
            "Capital Lease Obligations": [leases] * 4,
            "Total Debt": [debt] * 4,
            "Long Term Provisions": [lt_provisions] * 4,
            "Total Non Current Liabilities Net Minority Interest": [tl - cl for tl, cl in zip(tot_liab, cl_desc)],
            "Total Liabilities Net Minority Interest": tot_liab,
            "Common Stock": common_stk,
            "Retained Earnings": ret_earn,
            "Stockholders Equity": eq_desc,
            "Common Stock Equity": eq_desc,
            "Preferred Stock": [preferred] * 4,
            "Minority Interest": [minority] * 4,
            "Total Equity Gross Minority Interest": [e + minority + preferred for e in eq_desc],
            "Ordinary Shares Number": [shares] * 4,
            "Share Issued": [shares] * 4,
        },
        index=dates,
    )

    cfo_desc = [n + d for n, d in zip(ni_desc, cf_dna_desc)]
    cfi_desc = capex_desc
    cff_desc = [0.0] * 4
    net_chg_desc = [o + i + f for o, i, f in zip(cfo_desc, cfi_desc, cff_desc)]
    beg_cash_desc = [cash * 0.8 - chg for chg in net_chg_desc]
    cf = pd.DataFrame(
        {
            "Net Income": ni_desc,
            "Operating Cash Flow": cfo_desc,
            "Depreciation And Amortization": cf_dna_desc,
            "Capital Expenditure": capex_desc,
            "Investing Cash Flow": cfi_desc,
            "Financing Cash Flow": cff_desc,
            "Changes In Cash": net_chg_desc,
            "Beginning Cash Position": beg_cash_desc,
            "End Cash Position": [cash * 0.8] * 4,
            "Change In Working Capital": [0.0] * 4,
        },
        index=dates,
    )

    suitability = classify_model_suitability(
        sector=sector,
        industry=industry,
        company_name=name,
        is_financial=False,
        is_capital_light_financial=is_cap_light_fin,
        is_non_dcf=False,
        balance_sheet_cols=list(bs.columns),
        is_extractive=is_extractive,
        is_cyclical=is_cyclical,
        accounting_standard=acct_std,
    )

    sec_edgar = None
    if sec_aro is not None:
        sec_edgar = {
            "available": True,
            "source_citation": "SEC EDGAR XBRL Test Fixture",
            "latest_quarter": {
                "aro_obligation": {
                    "value": float(sec_aro),
                    "tag": "us-gaap:AssetRetirementObligationsNoncurrent",
                    "end": "2025-12-31",
                }
            },
        }

    return {
        "ticker": ticker,
        "name": name,
        "market": market,
        "sector": sector,
        "industry": industry,
        "description": f"{name} ({industry})",
        "accounting_standard": acct_std,
        "model_suitability": suitability,
        "sec_edgar": sec_edgar,
        "primary_filing": None,
        "share_reconciliation": {
            "yahoo_shares_outstanding": shares,
            "cover_basic_shares": None,
            "valuation_basic_shares": shares,
            "valuation_diluted_shares": shares,
            "tsm_bridge": None,
        },
        "is_financial": False,
        "is_capital_light_financial": is_cap_light_fin,
        "is_extractive": is_extractive,
        "is_cyclical": is_cyclical,
        "current_price": price,
        "shares_outstanding": shares,
        "diluted_valuation_shares": shares,
        "market_cap": price * shares,
        "beta": beta,
        "raw_beta": raw_beta,
        "raw_blume_beta": (2.0 / 3.0) * raw_beta + (1.0 / 3.0),
        "sector_bottom_up_beta": sector_bottom_up_beta,
        "cyclical_beta_low_flag": cyclical_beta_low_flag,
        "beta_clamped": False,
        "beta_note": f"Test fixture beta {beta:.2f}",
        "is_illiquid": False,
        "income_stmt": inc,
        "balance_sheet": bs,
        "cash_flow": cf,
        "info": {
            "currency": "INR" if market == "IN" else "USD",
            "sector": sector,
            "industry": industry,
            "longName": name,
            "currentPrice": price,
            "sharesOutstanding": shares,
        },
    }


def _analyze_synthetic(monkeypatch, stock_data: Dict[str, Any]) -> Dict[str, Any]:
    monkeypatch.setattr("main.fetch_stock_data", lambda t, m=None: stock_data)
    client = TestClient(app)
    resp = client.post(
        "/api/analyze",
        json={"ticker": stock_data["ticker"], "market": stock_data["market"], "monte_carlo_iterations": 200},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_extractive_aro_disclosure_tv_blend_and_libreoffice_parity(monkeypatch):
    # Case 1: Extractive with unverified LT Provisions (>5% rev) -> NOT blindly added to Base Debt;
    # exposed via aro_provisions_stress scenario + FLAGGED_FOR_INVESTIGATION + VALIDATED_WITH_LIMITATIONS.
    sd = _build_corporate_stock_data(
        ticker="OILTEST.NS",
        name="Indian Upstream Energy Co",
        market="IN",
        sector="Energy",
        industry="Oil & Gas E&P",
        is_extractive=True,
        is_cyclical=True,
        acct_std="IND_AS",
        lt_provisions=1.6e9,
        revs=(8e9, 9e9, 9.5e9, 10e9),
        ebit_margins=(0.24, 0.25, 0.26, 0.26),
        capex_pct=0.14,
        dna_pct=0.07,
        debt=1.2e9,
        cash=8e8,
        price=140.0,
        shares=200_000_000.0,
    )
    res = _analyze_synthetic(monkeypatch, sd)
    wacc = res["wacc"]
    assert wacc["aro_provisions_claim"] == 0.0
    assert "aro_provisions_stress" in res["scenarios"]
    assert res["scenarios"]["aro_provisions_stress"]["implied_price"] < res["dcf_result"]["implied_price"]
    assert any(a["category"] == "aro_provisions" and a["status"] == "FLAGGED_FOR_INVESTIGATION" for a in res["valuation_adjustments"])
    assert res["validation_gate"]["validation_status"] == "VALIDATED_WITH_LIMITATIONS"

    # Case 2: US Extractive where Gordon Growth TV > 8.0x Exit TV -> TV Blend triggers & matches LibreOffice Calc,
    # AND SEC XBRL verified ARO IS added cleanly.
    sd_sec = _build_corporate_stock_data(
        ticker="XOMTEST",
        name="US Upstream Corp",
        market="US",
        sector="Energy",
        industry="Oil & Gas Integrated",
        is_extractive=True,
        is_cyclical=True,
        acct_std="US_GAAP",
        beta=0.70,
        raw_beta=0.70,
        revs=(10e9, 10.5e9, 11e9, 11.5e9),
        ebit_margins=(0.24, 0.25, 0.26, 0.27),
        dna_pct=0.06,
        capex_pct=0.07,
        debt=1.5e9,
        cash=1.0e9,
        lt_provisions=2.0e9,
        sec_aro=1.35e9,
    )
    res_sec = _analyze_synthetic(monkeypatch, sd_sec)
    assert res_sec["wacc"]["aro_provisions_claim"] == pytest.approx(1.35e9)
    assert res_sec["dcf_result"]["tv_blend_applied"] is True
    assert "pure_gordon_tv" in res_sec["scenarios"]
    assert any(a["status"] == "APPLIED_PRIMARY_VERIFIED" for a in res_sec["valuation_adjustments"])

    # Export Excel on blended extractive + LibreOffice Calc verification
    xbytes = generate_excel_report(res_sec).getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)
    wb_lo = _libreoffice_recalc(xbytes)
    _assert_zero_excel_errors(wb_lo, wb_f)

    ws_dcf_lo = wb_lo["DCF Model"]
    lo_ev = _find_cell_by_label(ws_dcf_lo, "Implied Enterprise Value (Operating Assets)")
    lo_eq = _find_cell_by_label(ws_dcf_lo, "Implied Equity Value")
    lo_px = _find_cell_by_label(ws_dcf_lo, "DCF Implied Value per Share")
    lo_roic = _find_cell_by_label(ws_dcf_lo, "Steady-State Return on New Invested Capital (RONIC)")
    _assert_close_scaled(lo_ev, res_sec["dcf_result"]["enterprise_value"], "currency", "Extractive Blended EV")
    _assert_close_scaled(lo_eq, res_sec["dcf_result"]["equity_value"], "currency", "Extractive Blended Equity")
    _assert_close_scaled(lo_px, res_sec["dcf_result"]["implied_price"], "price", "Extractive Blended Price")
    _assert_close_scaled(lo_roic, res_sec["dcf_result"]["sustainable_roic"], "rate", "Extractive Blended RONIC")


def test_cyclical_empirical_beta_retention_and_sector_stress(monkeypatch):
    sd = _build_corporate_stock_data(
        ticker="STEELTEST.NS",
        name="Cyclical Metals Ltd",
        market="IN",
        sector="Basic Materials",
        industry="Steel",
        is_extractive=False,
        is_cyclical=True,
        cyclical_beta_low_flag=True,
        acct_std="IND_AS",
        beta=0.80,
        raw_beta=0.70,
        sector_bottom_up_beta=1.18,
        revs=(10e9, 11e9, 10.2e9, 11.5e9),
        ebit_margins=(0.14, 0.16, 0.11, 0.14),
        capex_pct=0.09,
        dna_pct=0.05,
        price=120.0,
    )
    res = _analyze_synthetic(monkeypatch, sd)
    assert res["market_data"]["beta"] == pytest.approx(0.80)
    assert "bottom_up_sector_beta" in res["scenarios"]
    assert res["scenarios"]["bottom_up_sector_beta"]["implied_price"] < res["dcf_result"]["implied_price"]
    assert res["validation_gate"]["validation_status"] == "VALIDATED_WITH_LIMITATIONS"


def test_negative_ebit_high_capex_greenfield_preferred_nci_and_unverified_da(monkeypatch):
    # Tests simultaneous interactions:
    # 1. Negative base EBIT turnaround -> positive Year 5 margin
    # 2. Greenfield High CapEx (>2.2x D&A) + CWIP > 50% rev -> unadjusted_capex & unadjusted_gross_debt scenarios
    # 3. Minority Interest + Preferred Stock -> deducted cleanly on EV bridge & Excel
    # 4. Ind AS IS D&A < CF D&A WITHOUT primary AR notes -> NOT silently stamped as recoupment; triggers WARN
    sd = _build_corporate_stock_data(
        ticker="TURNTEST.NS",
        name="Greenfield Infra Turnaround Ltd",
        market="IN",
        sector="Industrials",
        industry="Engineering & Construction",
        acct_std="IND_AS",
        revs=(4e9, 5e9, 6e9, 7e9),
        ebit_margins=(-0.05, -0.02, 0.04, 0.08),
        dna_pct=0.04,
        capex_pct=0.22,
        cf_dna_mult=1.30,
        cwip=4.0e9,
        debt=4.0e9,
        cash=5e8,
        minority=6e8,
        preferred=2.5e8,
        price=90.0,
    )
    res = _analyze_synthetic(monkeypatch, sd)
    dr = res["depreciation_reconciliation"]
    assert dr["is_recouped"] is False
    assert dr["recoupment_inferred_unverified"] is True
    assert res["validation_gate"]["validation_status"] == "VALIDATED_WITH_LIMITATIONS"
    assert "unadjusted_capex" in res["scenarios"]
    assert "unadjusted_gross_debt" in res["scenarios"]
    assert res["wacc"]["preferred_stock_claim"] == pytest.approx(2.5e8)
    assert res["wacc"]["minority_interest_claim"] == pytest.approx(6.0e8)

    xbytes = generate_excel_report(res).getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)
    wb_lo = _libreoffice_recalc(xbytes)
    _assert_zero_excel_errors(wb_lo, wb_f)

    ws_dcf_lo = wb_lo["DCF Model"]
    lo_px = _find_cell_by_label(ws_dcf_lo, "DCF Implied Value per Share")
    lo_roic = _find_cell_by_label(ws_dcf_lo, "Steady-State Return on New Invested Capital (RONIC)")
    _assert_close_scaled(lo_px, res["dcf_result"]["implied_price"], "price", "Turnaround Price")
    _assert_close_scaled(lo_roic, res["dcf_result"]["sustainable_roic"], "rate", "Turnaround RONIC")


def test_capital_light_exchange_and_nbfc_vs_bank_and_sector_models():
    # NBFC vs Commercial Bank vs Insurance vs REIT separation
    c_bank = classify_model_suitability("Financial Services", "Banks - Regional", "HDFC Bank", True, False, False, False)
    c_nbfc = classify_model_suitability("Financial Services", "Credit Services", "IREDA Ltd", True, False, False, False)
    c_mfs = classify_model_suitability("Financial Services", "Financial Data & Stock Exchanges", "Max Financial Services Ltd", False, False, False, False)
    c_reit = classify_model_suitability("Real Estate", "REIT - Diversified", "Embassy Office Parks REIT", False, False, False, True)
    c_exch = classify_model_suitability("Financial Services", "Financial Data & Stock Exchanges", "Central Depository Services", False, True, False, False)

    assert c_bank["model_family"] == "BANK_DDM_TIER1" and c_bank["supported"] is True
    assert c_nbfc["model_family"] == "NBFC_LENDER_DDM" and c_nbfc["supported"] is True
    assert c_mfs["model_family"] == "INSURANCE_LIFE_DDM" and c_mfs["supported"] is True
    assert c_mfs["validation_status"] == "VALIDATED_WITH_LIMITATIONS"
    assert c_reit["model_family"] == "REIT_INVIT_AFFO" and c_reit["supported"] is True
    assert c_reit["validation_status"] == "VALIDATED_WITH_LIMITATIONS"
    assert c_exch["driver_profile"]["profile_id"] == "CAPITAL_LIGHT_FINANCIAL"


def test_dynamic_schedule_iii_note_scanner_shifted_notes_and_standalone_rejection(tmp_path):
    ar_text = """
=== AR PAGE 100 ===
STANDALONE BALANCE SHEET AS AT 31ST MARCH, 2026
Particulars | Note | in crore
Property, Plant and Equipment 100.00 90.00
=== AR PAGE 210 ===
CONSOLIDATED BALANCE SHEET
as at 31st March, 2026
(₹ in crore)
Particulars
Note No.
2025-26
2024-25
ASSETS
Property, Plant and Equipment
5
12,000.00
11,200.00
Cash and cash equivalents
13
900.00
850.00
Bank balances other than cash and cash equivalents
14
400.00
350.00
Investments
7
100.00
90.00
Investments
15
300.00
250.00
Total Assets
13,700.00
12,740.00
EQUITY AND LIABILITIES
Equity Share Capital
18
500.00
500.00
Other Equity
19
8,000.00
7,200.00
Total Equity
8,500.00
7,700.00
Borrowings
22
3,000.00
3,100.00
Lease liabilities
49
400.00
380.00
Borrowings
26
600.00
560.00
Lease liabilities
49
60.00
55.00
Total Equity and Liabilities
13,700.00
12,740.00
=== AR PAGE 215 ===
CONSOLIDATED STATEMENT OF PROFIT AND LOSS
for the year ended 31st March, 2026
(₹ in crore)
Particulars
Note No.
2025-26
2024-25
Revenue from operations
10,000.00
9,200.00
Finance costs
36
350.00
340.00
Depreciation and amortisation expense
39
700.00
650.00
Total Expenses
8,500.00
7,900.00
Profit before tax
1,500.00
1,300.00
Profit for the year
1,100.00
950.00
=== AR PAGE 220 ===
CONSOLIDATED CASH FLOW STATEMENT
for the year ended 31st March, 2026
(₹ in crore)
Particulars
2025-26
2024-25
Profit before tax
1,500.00
1,300.00
Depreciation and amortisation expense
850.00
780.00
Net cash flow from operating activities
1,900.00
1,700.00
Cash and cash equivalents - Closing Balance
900.00
850.00
NOTES FORMING PART OF CONSOLIDATED FINANCIAL STATEMENTS
=== AR PAGE 240 ===
NOTE - 14 BANK BALANCES OTHER THAN CASH AND CASH EQUIVALENTS
Unpaid dividend accounts
12.00
10.00
Escrow accounts
38.00
30.00
=== AR PAGE 265 ===
NOTE - 39 DEPRECIATION AND AMORTISATION EXPENSE
Depreciation/ amortisation of property, plant and equipment
820.00
750.00
Amortisation of intangible assets
30.00
30.00
Recoupment from retained earnings
150.00
130.00
=== AR PAGE 278 ===
NOTE - 49 IND AS 116 LEASES
Total
0.00
0.00
0.00
45.00
390.00
Movement in lease liabilities
Lease liabilities as at April 1, 2025
435.00
Finance cost expense
35.00
Payment during the year
(60.00)
Balance as on 31st March, 2026
460.00
"""
    ar_file = tmp_path / "TESTCO_AR_2025_26.txt"
    ar_file.write_text(ar_text, encoding="utf-8")
    pf = extract_ind_as_ar_financials("TESTCO.NS", extra_dirs=[str(tmp_path)])
    assert pf["available"] is True
    assert pf["consolidation_basis"] == "Consolidated"
    assert pf["statements_provenance"]["balance_sheet"]["source_page"] == "210"
    assert pf["notes"]["note_16_cash_restriction"]["total_restricted_earmarked"] == pytest.approx(50.0)
    assert pf["notes"]["note_38_46_depreciation_reconciliation"]["recoupment_from_retained_earnings_and_adj"]["current"] == pytest.approx(150.0)
    assert pf["notes_provenance"]["cash_restriction"]["note_ref"] == "Note 14"
    assert pf["notes_provenance"]["cash_restriction"]["source_page"] == "240"


@pytest.mark.parametrize("ticker,market", [("DUOL", "US"), ("CESC.NS", "IN"), ("HDFCBANK.NS", "IN")])
def test_real_libreoffice_calc_recalculation_on_offline_workbooks(ticker, market):
    client = TestClient(app)
    res = client.post("/api/analyze", json={"ticker": ticker, "market": market, "monte_carlo_iterations": 500}).json()
    xbytes = generate_excel_report(res).getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)
    wb_lo = _libreoffice_recalc(xbytes)
    _assert_zero_excel_errors(wb_lo, wb_f)

    py_price = float(res["dcf_result"]["implied_price"])
    ws_cov = wb_lo["Cover"]
    if res["company"].get("is_financial"):
        cov_price = next(
            ws_cov.cell(r, 3).value
            for r in range(1, ws_cov.max_row + 1)
            if "Fair Value per Share" in str(ws_cov.cell(r, 2).value or "")
        )
    else:
        cov_price = _find_cell_by_label(ws_cov, "DCF Implied Fair Value (Live Model Formula)", label_col=2, val_col=3)
    _assert_close_scaled(cov_price, py_price, "price", f"{ticker} LibreOffice Cover Price")

    if not res["company"].get("is_financial"):
        ws_dcf = wb_lo["DCF Model"]
        lo_ev = _find_cell_by_label(ws_dcf, "Implied Enterprise Value (Operating Assets)")
        lo_eq = _find_cell_by_label(ws_dcf, "Implied Equity Value")
        lo_px = _find_cell_by_label(ws_dcf, "DCF Implied Value per Share")
        lo_roic = _find_cell_by_label(ws_dcf, "Steady-State Return on New Invested Capital (RONIC)")
        _assert_close_scaled(lo_ev, res["dcf_result"]["enterprise_value"], "currency", f"{ticker} LO EV")
        _assert_close_scaled(lo_eq, res["dcf_result"]["equity_value"], "currency", f"{ticker} LO Equity")
        _assert_close_scaled(lo_px, py_price, "price", f"{ticker} LO DCF Price")
        _assert_close_scaled(lo_roic, res["dcf_result"]["sustainable_roic"], "rate", f"{ticker} LO RONIC")


def test_nbfc_lender_ddm_and_libreoffice_parity(monkeypatch):
    sd = _build_corporate_stock_data(
        ticker="NBFCTEST.NS",
        name="Wholesale Infra Finance NBFC Ltd",
        market="IN",
        sector="Financial Services",
        industry="Credit Services",
        acct_std="IND_AS",
        beta=1.10,
        raw_beta=1.10,
        revs=(1.8e9, 2.2e9, 2.6e9, 3.0e9),
        ebit_margins=(0.38, 0.39, 0.40, 0.41),
        dna_pct=0.01,
        capex_pct=0.01,
        debt=12.0e9,
        cash=1.5e9,
        price=150.0,
        shares=200_000_000.0,
    )
    sd["is_financial"] = True
    sd["model_suitability"] = classify_model_suitability(
        "Financial Services", "Credit Services", "Wholesale Infra Finance NBFC Ltd", True, False, False
    )
    res = _analyze_synthetic(monkeypatch, sd)
    assert res["company"]["model_suitability"]["model_family"] == "NBFC_LENDER_DDM"
    assert res["dcf_result"]["is_nbfc"] is True
    assert res["dcf_result"]["lender_subtype"] == "NBFC_WHOLESALE_LENDER"
    assert res["dcf_result"]["credit_cost_stress_price"] < res["dcf_result"]["implied_price"]

    xbytes = generate_excel_report(res).getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)
    wb_lo = _libreoffice_recalc(xbytes)
    _assert_zero_excel_errors(wb_lo, wb_f)

    py_price = float(res["dcf_result"]["implied_price"])
    ws_cov = wb_lo["Cover"]
    cov_price = next(
        ws_cov.cell(r, 3).value
        for r in range(1, ws_cov.max_row + 1)
        if "Fair Value per Share" in str(ws_cov.cell(r, 2).value or "")
    )
    _assert_close_scaled(cov_price, py_price, "price", "NBFC LibreOffice Cover Price")


def _assert_equity_sensitivity_libreoffice_parity(wb_lo: openpyxl.Workbook, res: Dict[str, Any], label_prefix: str) -> None:
    """Compare all 50 Sensitivity cells (Matrix 1 + Matrix 2) recalculated by LibreOffice Calc vs Python."""
    ws_s = wb_lo["Sensitivity"]
    matrix_blocks = []
    for r in range(1, ws_s.max_row + 1):
        val = str(ws_s.cell(r, 2).value or "")
        if val.startswith("Cost of Equity (Ke) \\"):
            matrix_blocks.append(r + 1)
    assert len(matrix_blocks) >= 2, f"{label_prefix}: Expected 2 Sensitivity matrices, got {matrix_blocks}"

    sens = res["sensitivity"]
    for idx, (grid_key, start_r) in enumerate([("growth_wacc", matrix_blocks[0]), ("margin_wacc", matrix_blocks[1])]):
        py_grid = sens[grid_key].get("price_grid") or sens[grid_key]["grid"]
        for i in range(len(py_grid)):
            for j in range(len(py_grid[i])):
                lo_v = ws_s.cell(start_r + i, 3 + j).value
                _assert_close_scaled(lo_v, py_grid[i][j], "price", f"{label_prefix} {grid_key}[{i},{j}]")


def test_insurance_pnc_and_life_ddm_libreoffice_parity(monkeypatch):
    sd = _build_corporate_stock_data(
        ticker="PGRTEST",
        name="Progressive Test Insurance Corp",
        market="US",
        sector="Financial Services",
        industry="Insurance - Property & Casualty",
        acct_std="US_GAAP",
        beta=0.68,
        raw_beta=0.68,
        revs=(5.2e10, 6.0e10, 7.0e10, 8.2e10),
        ebit_margins=(0.11, 0.12, 0.13, 0.14),
        dna_pct=0.005,
        capex_pct=0.005,
        debt=6.5e9,
        cash=3.0e9,
        price=210.0,
        shares=585_000_000.0,
    )
    bs = sd["balance_sheet"].copy()
    bs["Gains Losses Not Affecting Retained Earnings"] = [-3.2e9, -3.0e9, -2.5e9, -2.0e9]
    bs["Investments And Advances"] = [7.8e10, 7.0e10, 6.2e10, 5.5e10]
    bs["Total Liabilities Net Minority Interest"] = [5.8e10, 5.2e10, 4.6e10, 4.1e10]
    bs["Total Non Current Liabilities Net Minority Interest"] = bs["Total Liabilities Net Minority Interest"] - bs["Current Liabilities"]
    bs["Total Assets"] = bs["Total Liabilities Net Minority Interest"] + bs["Total Equity Gross Minority Interest"]
    bs["Total Non Current Assets"] = bs["Total Assets"] - bs["Current Assets"]
    sd["balance_sheet"] = bs
    inc = sd["income_stmt"].copy()
    inc["Normalized Income"] = [9.2e9, 7.8e9, 6.2e9, 5.0e9]
    inc["Net Policyholder Benefits And Claims"] = [5.5e10, 4.8e10, 4.2e10, 3.7e10]
    sd["income_stmt"] = inc
    sd["is_financial"] = True
    sd["model_suitability"] = classify_model_suitability(
        "Financial Services", "Insurance - Property & Casualty", "Progressive Test Insurance Corp", True, False, False, False
    )

    res = _analyze_synthetic(monkeypatch, sd)
    assert res["company"]["model_type"] == "INSURANCE_PNC_DDM"
    assert res["validation_gate"]["validation_status"] == "VALIDATED_WITH_LIMITATIONS"
    assert res["validation_gate"]["is_blocked"] is False
    dcf = res["dcf_result"]
    assert dcf["is_insurance"] is True
    assert dcf["used_ex_aoci_bv"] is True
    assert dcf["float_to_equity"] > 1.0
    assert dcf["catastrophe_stress_price"] < dcf["implied_price"]

    xbytes = generate_excel_report(res).getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)
    wb_lo = _libreoffice_recalc(xbytes)
    _assert_zero_excel_errors(wb_lo, wb_f)

    ws_ddm = wb_lo["DDM & FCFE Model"]
    lo_px = _find_cell_by_label(ws_ddm, "Actuarial Equity Fair Value per Share")
    _assert_close_scaled(lo_px, dcf["implied_price"], "price", "Insurance LibreOffice DDM Price")
    _assert_equity_sensitivity_libreoffice_parity(wb_lo, res, "Insurance")


def test_reit_invit_affo_and_cap_rate_nav_libreoffice_parity(monkeypatch):
    from engine.ticker_universe import is_non_dcf_instrument

    blocked, kind, reason = is_non_dcf_instrument(
        "EMBASSY.NS", "Embassy Office Parks REIT", "Real Estate", "REIT - Office", "MUTUALFUND"
    )
    assert blocked is False and kind == "REIT_INVIT" and reason == ""

    sd = _build_corporate_stock_data(
        ticker="EMBASSY.NS",
        name="Embassy Office Parks REIT",
        market="IN",
        sector="Real Estate",
        industry="REIT - Office",
        acct_std="IND_AS",
        beta=0.55,
        raw_beta=0.55,
        revs=(3.2e10, 3.5e10, 3.8e10, 4.1e10),
        ebit_margins=(0.55, 0.56, 0.57, 0.58),
        dna_pct=0.30,
        capex_pct=0.0,
        debt=1.6e11,
        cash=1.2e10,
        price=380.0,
        shares=948_000_000.0,
    )
    cf = sd["cash_flow"].copy()
    cf["Capital Expenditure"] = [0.0, 0.0, 0.0, 0.0]
    cf["Cash Dividends Paid"] = [-2.3e10, -2.1e10, -1.9e10, -1.7e10]
    cf["Operating Cash Flow"] = [3.5e10, 3.2e10, 2.9e10, 2.6e10]
    sd["cash_flow"] = cf
    sd["quote_type"] = "MUTUALFUND"
    sd["is_financial"] = False
    sd["model_suitability"] = classify_model_suitability(
        "Real Estate", "REIT - Office", "Embassy Office Parks REIT", False, False, False, True
    )

    res = _analyze_synthetic(monkeypatch, sd)
    assert res["company"]["model_type"] == "REIT_INVIT_AFFO"
    assert res["validation_gate"]["validation_status"] == "VALIDATED_WITH_LIMITATIONS"
    assert res["validation_gate"]["is_blocked"] is False
    dcf = res["dcf_result"]
    assert dcf["is_reit"] is True
    assert dcf["base_affo"] > 0 and dcf["implied_price"] > 0
    assert dcf["cap_rate_nav_per_unit"] > 0
    assert dcf["cap_rate_stress_price"] < dcf["cap_rate_nav_per_unit"]

    xbytes = generate_excel_report(res).getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)
    wb_lo = _libreoffice_recalc(xbytes)
    _assert_zero_excel_errors(wb_lo, wb_f)

    assert "REIT AFFO Model" in wb_f.sheetnames
    ws_reit = wb_lo["REIT AFFO Model"]
    lo_px = _find_cell_by_label(ws_reit, "Distributable AFFO Fair Value per Unit")
    lo_nav = _find_cell_by_label(ws_reit, "Cap-Rate NAV Fair Value per Unit")
    _assert_close_scaled(lo_px, dcf["implied_price"], "price", "REIT LibreOffice AFFO Unit Price")
    _assert_close_scaled(lo_nav, dcf["cap_rate_nav_per_unit"], "price", "REIT LibreOffice Cap-Rate NAV")
    _assert_equity_sensitivity_libreoffice_parity(wb_lo, res, "REIT")


def test_midstream_mlp_common_equity_fallback_and_parity(monkeypatch):
    sd = _build_corporate_stock_data(
        ticker="EPD",
        name="Enterprise Products Partners L.P.",
        market="US",
        sector="Energy",
        industry="Oil & Gas Midstream",
        acct_std="US_GAAP",
        beta=0.72,
        raw_beta=0.72,
        revs=(4.6e10, 4.9e10, 5.2e10, 5.5e10),
        ebit_margins=(0.14, 0.145, 0.15, 0.155),
        dna_pct=0.045,
        capex_pct=0.075,
        debt=2.9e10,
        cash=1.1e9,
        minority=1.1e9,
        preferred=5.0e7,
        price=31.0,
        shares=2_170_000_000.0,
    )
    bs = sd["balance_sheet"].copy()
    bs["Stockholders Equity"] = [0.0, 0.0, 0.0, 0.0]
    bs["Common Stock Equity"] = [2.95e10, 2.85e10, 2.75e10, 2.65e10]
    sd["balance_sheet"] = bs
    sd["model_suitability"] = classify_model_suitability(
        "Energy", "Oil & Gas Midstream", "Enterprise Products Partners L.P.", False, False, False, False
    )

    res = _analyze_synthetic(monkeypatch, sd)
    assert res["company"]["model_type"] == "STANDARD_FCFF"
    assert res["model_suitability"]["driver_profile"]["profile_id"] == "MLP_MIDSTREAM_INFRA"
    assert res["validation_gate"]["is_blocked"] is False
    assert res["dcf_result"]["implied_price"] > 0
    assert res["historicals"]["book_value"][-1] > 2.0e10

    xbytes = generate_excel_report(res).getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)
    wb_lo = _libreoffice_recalc(xbytes)
    _assert_zero_excel_errors(wb_lo, wb_f)
    lo_px = _find_cell_by_label(wb_lo["DCF Model"], "DCF Implied Value per Share")
    _assert_close_scaled(lo_px, res["dcf_result"]["implied_price"], "price", "MLP LibreOffice DCF Price")
