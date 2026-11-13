"""
Adversarial Verification Gate Suite for ValuationLabs Revised Workbooks & Engine
================================================================================
Enforces all 10 verification gates from ValuationLabs_Independent_Remediation_Prompt.md
and verifies every finding from ValuationLabs_Revised_Workbook_Audit_Report.md
across DUOL (US SaaS), CESC.NS (Indian Regulated Utility), and the broader engine.
"""

from io import BytesIO
import numpy as np
import openpyxl
import pytest

from main import analyze, AnalyzeRequest
from export.excel_export import generate_excel_report


@pytest.fixture(scope="module")
def duol_bundle():
    res = analyze(AnalyzeRequest(ticker="DUOL", market="US"))
    xlsx_bytes = generate_excel_report(res)
    if hasattr(xlsx_bytes, "getvalue"):
        xlsx_bytes = xlsx_bytes.getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=False)
    wb_v = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True)
    return {"res": res, "wb_f": wb_f, "wb_v": wb_v}


@pytest.fixture(scope="module")
def cesc_bundle():
    res = analyze(AnalyzeRequest(ticker="CESC.NS", market="IN"))
    xlsx_bytes = generate_excel_report(res)
    if hasattr(xlsx_bytes, "getvalue"):
        xlsx_bytes = xlsx_bytes.getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=False)
    wb_v = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True)
    return {"res": res, "wb_f": wb_f, "wb_v": wb_v}


# ---------------------------------------------------------------------------
# Gate 1: 100% Formula-Driven Workbooks + Zero None Cached Formula Values
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", ["duol_bundle", "cesc_bundle"])
def test_gate1_formula_driven_and_zero_missing_cached_values(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    wb_f = bundle["wb_f"]
    wb_v = bundle["wb_v"]

    formula_count = 0
    missing_cached = []

    for sheet_name in wb_f.sheetnames:
        ws_f = wb_f[sheet_name]
        ws_v = wb_v[sheet_name]
        for r in range(1, ws_f.max_row + 1):
            for c in range(1, ws_f.max_column + 1):
                fv = ws_f.cell(r, c).value
                vv = ws_v.cell(r, c).value
                if isinstance(fv, str) and fv.startswith("="):
                    formula_count += 1
                    if vv is None or (isinstance(vv, str) and vv.startswith("#")):
                        missing_cached.append(f"{sheet_name}!{openpyxl.utils.get_column_letter(c)}{r}: {fv} -> {vv}")

    assert formula_count >= 10500, f"Expected >= 10,500 live formulas, got {formula_count}"
    assert missing_cached == [], f"Found uncached or error formula cells: {missing_cached[:10]}"


# ---------------------------------------------------------------------------
# Gate 2: Historical 3-Statement Disaggregation & Accounting Identities
# ---------------------------------------------------------------------------
def test_gate2_duol_statutory_income_statement_and_balance_sheet(duol_bundle):
    wb_f = duol_bundle["wb_f"]
    wb_v = duol_bundle["wb_v"]
    ws_f = wb_f["Historical Financials"]
    ws_v = wb_v["Historical Financials"]

    # FY2025 statutory GAAP Revenue ($1,037.589M), Gross Profit ($749.457M), SG&A ($307.564M), R&D ($306.323M), EBIT ($135.570M)
    assert abs(ws_v["F6"].value - 1_037_589_000) < 1000
    assert abs(ws_v["F10"].value - 749_457_000) < 1000
    assert abs(ws_v["F12"].value - 307_564_000) < 1000
    assert abs(ws_v["F15"].value - 306_323_000) < 1000
    # Other Operating Expenses (F16) and Regulatory/Normalization Adj (F19) must be 0 (no negative M&A amortization plug for DUOL)
    assert abs(ws_v["F16"].value) < 1.0
    assert abs(ws_v["F19"].value) < 1.0
    assert abs(ws_v["F20"].value - 135_570_000) < 1000
    assert abs(ws_v["F21"].value - (135_570_000 / 1_037_589_000)) < 1e-5
    assert abs(ws_v["F22"].value - 14_391_000) < 1000
    assert abs(ws_v["F24"].value - 149_961_000) < 1000

    # Disaggregated DUOL Balance Sheet items (FY2025, USD):
    # Capital Lease Obligations (F56) = $93.779M, Deferred Revenue (F59) = $496.205M,
    # Non-Current Deferred Tax Assets (F69) = $227.339M, Residual Other NCA (F70) = $12.818M (< 1% of Total Assets)
    assert abs(ws_v["F56"].value - 93_779_000) < 1000
    assert abs(ws_v["F59"].value - 496_205_000) < 1000
    assert abs(ws_v["F69"].value - 227_339_000) < 1000
    assert abs(ws_v["F70"].value - 12_818_000) < 1000
    assert abs(ws_v["F73"].value - 176_894_000) < 1000
    assert abs(ws_v["F78"].value - 102_663_000) < 1000

    # Balance check across all 4 historical years = 0.00 with live formulas
    for col in ("C", "D", "E", "F"):
        assert str(ws_f[f"{col}63"].value).startswith("=")
        assert str(ws_f[f"{col}81"].value).startswith("=")
        assert ws_f[f"{col}82"].value == f"={col}81-{col}63"
        assert abs(ws_v[f"{col}82"].value) < 1.0


def test_gate2_cesc_disaggregated_balance_sheet_and_regulatory_assets(cesc_bundle):
    wb_v = cesc_bundle["wb_v"]
    ws_v = wb_v["Historical Financials"]

    # CESC.NS FY2026 (in raw INR, 1 Cr = 1e7):
    # Trade / Accounts Receivable (Row 73) = ₹2,639.22 Cr (FY26) and ₹2,761.47 Cr (FY25)
    assert abs(ws_v["F73"].value / 1e7 - 2639.22) < 0.1
    assert abs(ws_v["E73"].value / 1e7 - 2761.47) < 0.1

    # Net PPE (Ex-CWIP, Row 65) = ₹21,724.43 Cr, CWIP (Row 66) = ₹4,548.41 Cr
    assert abs(ws_v["F65"].value / 1e7 - 21724.43) < 0.1
    assert abs(ws_v["F66"].value / 1e7 - 4548.41) < 0.1

    # Regulatory Deferral & Non-Current Deferred Assets (Row 69) = ₹8,665.97 Cr (18.6% of Total Assets)
    assert abs(ws_v["F69"].value / 1e7 - 8665.97) < 0.1
    total_assets_fy26 = ws_v["F81"].value / 1e7
    assert abs(total_assets_fy26 - 46470.17) < 0.1
    assert abs((ws_v["F69"].value / ws_v["F81"].value) - 0.18648) < 0.002

    # Residual Other Non-Current Assets (Row 70) is only ₹678.68 Cr (< 1.5% of Total Assets)
    assert abs(ws_v["F70"].value / 1e7 - 678.68) < 0.1
    assert (ws_v["F70"].value / ws_v["F81"].value) < 0.02

    # Accrued Expenses & Current Tax Payable (Row 58) = ₹533.75 Cr, Minority Interest (Row 52) = ₹658.51 Cr
    assert abs(ws_v["F58"].value / 1e7 - 533.75) < 0.1
    assert abs(ws_v["F52"].value / 1e7 - 658.51) < 0.1

    # Balance check across all 4 years == 0.00
    for col in ("C", "D", "E", "F"):
        assert abs(ws_v[f"{col}82"].value) < 1.0


# ---------------------------------------------------------------------------
# Gate 3: Historical Cash Flow Bridge & Working Capital Sign Convention
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", ["duol_bundle", "cesc_bundle"])
def test_gate3_cash_flow_bridge_and_wc_sign_convention(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    wb_f = bundle["wb_f"]
    wb_v = bundle["wb_v"]
    ws_f = wb_f["Historical Financials"]
    ws_v = wb_v["Historical Financials"]

    for col in ("C", "D", "E", "F"):
        # CFO (Row 92), CFI (Row 98), CFF (Row 104), Net Change in Cash (Row 107), Ending Cash (Row 109)
        assert ws_f[f"{col}92"].value == f"={col}85+{col}86+{col}87+{col}88+{col}89+{col}90+{col}91"
        assert ws_f[f"{col}98"].value == f"=-{col}94+{col}95+{col}96+{col}97"
        assert ws_f[f"{col}104"].value == f"={col}100-{col}101+{col}102+{col}103"
        assert ws_f[f"{col}107"].value == f"={col}92+{col}98+{col}104+{col}106"
        assert ws_f[f"{col}109"].value == f"={col}108+{col}107"
        assert abs(ws_v[f"{col}109"].value - (ws_v[f"{col}108"].value + ws_v[f"{col}107"].value)) < 1.0

        # UFCF Bridge on Row 119 = NOPAT (118) + D&A (22) - CapEx (94) - ΔNWC (115)
        assert ws_f[f"{col}119"].value == f"={col}118+{col}22-{col}94-{col}115"


# ---------------------------------------------------------------------------
# Gate 4 & Gate 5: WACC Debt Excludes Minority Interest; EV Bridge Deducts It
# ---------------------------------------------------------------------------
def test_gate4_and_gate5_cesc_wacc_and_ev_bridge_minority_interest(cesc_bundle):
    res = cesc_bundle["res"]
    wb_f = cesc_bundle["wb_f"]
    wb_v = cesc_bundle["wb_v"]

    ws_wacc_f = wb_f["WACC 2"]
    ws_wacc_v = wb_v["WACC 2"]
    ws_dcf_f = wb_f["DCF Model"]
    ws_dcf_v = wb_v["DCF Model"]

    # Total Debt in WACC 2 (E15) links to Historical Financials!F55 (₹21,318.54 Cr, excluding ₹658.51 Cr Minority Interest)
    assert ws_wacc_f["E15"].value == "='Historical Financials'!F55"
    assert abs(ws_wacc_v["E15"].value / 1e7 - 21318.54) < 0.1
    assert abs(res["wacc"]["total_debt"] / 1e7 - 21318.54) < 0.1
    assert abs(res["wacc"]["minority_interest_claim"] / 1e7 - 658.51) < 0.1

    # Wd + We == 1.0
    assert abs((ws_wacc_v["E24"].value + ws_wacc_v["E25"].value) - 1.0) < 1e-6

    # DCF Model EV-to-Equity bridge deducts Minority Interest & Preferred Claims (D33 = 'Historical Financials'!F52 = ₹658.51 Cr)
    assert ws_dcf_f["D33"].value == "='Historical Financials'!F52"
    assert abs(ws_dcf_v["D33"].value / 1e7 - 658.51) < 0.1
    assert ws_dcf_f["D34"].value == "=D30+D31-D32-D33"
    expected_eq = ws_dcf_v["D30"].value + ws_dcf_v["D31"].value - ws_dcf_v["D32"].value - ws_dcf_v["D33"].value
    assert abs(ws_dcf_v["D34"].value - expected_eq) < 1.0


# ---------------------------------------------------------------------------
# Gate 6: Base-Year Revenue Tie-Out, Target Operating Margin & Reinvestment
# ---------------------------------------------------------------------------
def test_gate6_duol_base_revenue_margin_and_capex_convergence(duol_bundle):
    wb_f = duol_bundle["wb_f"]
    wb_v = duol_bundle["wb_v"]
    ws_hist = wb_v["Historical Financials"]
    ws_dcf_f = wb_f["DCF Model"]
    ws_dcf_v = wb_v["DCF Model"]

    # Base-year revenue on DCF Model!C5 links directly to Historical Financials!F6 ($1,037.589M)
    assert ws_dcf_f["C5"].value == "='Historical Financials'!F6"
    assert abs(ws_dcf_v["C5"].value - ws_hist["F6"].value) < 1.0
    assert abs(ws_dcf_v["C6"].value - ws_hist["F21"].value) < 1e-5

    # DUOL target operating margin converges to 30.38% in Year 5 (H6), starting at 20.14% in Year 1 (D6) from 17.58% base
    assert abs(ws_dcf_v["D6"].value - 0.20141) < 0.005
    assert abs(ws_dcf_v["H6"].value - 0.30377) < 0.005

    # Year 5 CapEx (H11) >= Year 5 D&A (H10) (no perpetual negative net PPE)
    assert ws_dcf_v["H11"].value >= ws_dcf_v["H10"].value - 1.0


# ---------------------------------------------------------------------------
# Gate 7: Cross-Tab Valuation Parity Across Cover, DCF Model, Sensitivity, MC
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", ["duol_bundle", "cesc_bundle"])
def test_gate7_cross_tab_valuation_parity(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    res = bundle["res"]
    wb_v = bundle["wb_v"]

    engine_price = res["dcf_result"]["implied_price"]
    cover_price = wb_v["Cover"]["C19"].value
    dcf_price = wb_v["DCF Model"]["D36"].value
    sens_ref_price = wb_v["Sensitivity"]["F4"].value
    sens_m1_base = wb_v["Sensitivity"]["G12"].value
    sens_m2_base = wb_v["Sensitivity"]["G25"].value
    sens_m3_base = wb_v["Sensitivity"]["G38"].value
    mc_base = wb_v["Monte Carlo"]["C6"].value

    for label, val in [
        ("Cover!C19", cover_price),
        ("DCF Model!D36", dcf_price),
        ("Sensitivity!F4", sens_ref_price),
        ("Sensitivity!G12", sens_m1_base),
        ("Sensitivity!G25", sens_m2_base),
        ("Sensitivity!G38", sens_m3_base),
        ("Monte Carlo!C6", mc_base),
    ]:
        assert abs(val - engine_price) < 0.02, f"{label} ({val}) != engine_price ({engine_price})"


# ---------------------------------------------------------------------------
# Gate 8: Sensitivity Grid Endogeneity & Backend Grid Alignment
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", ["duol_bundle", "cesc_bundle"])
def test_gate8_sensitivity_matrices_endogeneity_and_monotonicity(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    res = bundle["res"]
    wb_f = bundle["wb_f"]
    wb_v = bundle["wb_v"]
    ws_f = wb_f["Sensitivity"]
    ws_v = wb_v["Sensitivity"]

    # Every cell in all 3 9x9 matrices (C8:K16, C21:K29, C34:K42) must be a formula referencing 'DCF Model'
    for start_row in (8, 21, 34):
        for r in range(start_row, start_row + 9):
            row_vals = []
            for c in range(3, 12):
                fv = ws_f.cell(r, c).value
                vv = ws_v.cell(r, c).value
                assert isinstance(fv, str) and fv.startswith("=")
                assert "'DCF Model'!" in fv
                assert isinstance(vv, (int, float)) and vv >= 0
                row_vals.append(vv)
            assert row_vals[-1] > row_vals[0], f"Row {r} did not increase across columns: {row_vals}"
            # Monotonically increasing across columns (strictly increasing wherever positive, non-decreasing if floored at 0)
            for i in range(len(row_vals) - 1):
                if row_vals[i] > 0:
                    assert row_vals[i + 1] > row_vals[i], f"Row {r} not increasing across columns: {row_vals}"
                else:
                    assert row_vals[i + 1] >= row_vals[i], f"Row {r} decreased from zero floor: {row_vals}"

        # Monotonically decreasing down rows (higher WACC -> lower share price)
        for c in range(3, 12):
            col_vals = [ws_v.cell(r, c).value for r in range(start_row, start_row + 9)]
            assert col_vals[0] > col_vals[-1], f"Col {c} (start {start_row}) did not decrease with WACC: {col_vals}"
            for i in range(len(col_vals) - 1):
                if col_vals[i + 1] > 0:
                    assert col_vals[i + 1] < col_vals[i], f"Col {c} (start {start_row}) not decreasing with WACC: {col_vals}"
                else:
                    assert col_vals[i + 1] <= col_vals[i], f"Col {c} (start {start_row}) increased at zero floor: {col_vals}"

    # Verify backend JSON sensitivity grids match Excel Sensitivity cells
    tw_grid = res["sensitivity"]["terminal_growth_wacc"]["price_grid"]
    gw_grid = res["sensitivity"]["growth_wacc"]["price_grid"]
    mw_grid = res["sensitivity"]["margin_wacc"]["price_grid"]
    for ri in range(9):
        for ci in range(9):
            assert abs(tw_grid[ri][ci] - ws_v.cell(8 + ri, 3 + ci).value) < 0.05
            assert abs(gw_grid[ri][ci] - ws_v.cell(21 + ri, 3 + ci).value) < 0.05
            assert abs(mw_grid[ri][ci] - ws_v.cell(34 + ri, 3 + ci).value) < 0.05


# ---------------------------------------------------------------------------
# Gate 9: Monte Carlo 10,000 Structural Paths & Exact Empirical Percentiles
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", ["duol_bundle", "cesc_bundle"])
def test_gate9_monte_carlo_structural_paths_and_percentiles(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    wb_f = bundle["wb_f"]
    wb_v = bundle["wb_v"]
    ws_f = wb_f["Monte Carlo"]
    ws_v = wb_v["Monte Carlo"]

    # Summary statistics use live Excel formulas over H27:H10026
    assert "AVERAGE(H27:H10026)" in ws_f["C7"].value
    assert "MEDIAN(H27:H10026)" in ws_f["C8"].value
    assert "STDEV.S(H27:H10026)" in ws_f["C9"].value
    assert "PERCENTILE.INC(H27:H10026,0.05)" in ws_f["C10"].value
    assert "PERCENTILE.INC(H27:H10026,0.95)" in ws_f["C11"].value
    assert "COUNTIF(H27:H10026" in ws_f["C14"].value

    prices = np.array([ws_v.cell(r, 8).value for r in range(27, 10027)], dtype=float)
    assert len(prices) == 10000
    assert np.all(prices >= 0)

    assert abs(ws_v["C7"].value - float(np.mean(prices))) < 1e-3
    assert abs(ws_v["C8"].value - float(np.median(prices))) < 1e-3
    assert abs(ws_v["C9"].value - float(np.std(prices, ddof=1))) < 1e-3
    assert abs(ws_v["C10"].value - float(np.percentile(prices, 5))) < 1e-3
    assert abs(ws_v["C11"].value - float(np.percentile(prices, 95))) < 1e-3

    # Histogram counts (C27:C51) sum to 10,000 in C52
    hist_counts = [ws_v.cell(r, 3).value for r in range(27, 52)]
    assert sum(hist_counts) == 10000
    assert ws_v["C52"].value == 10000


# ---------------------------------------------------------------------------
# Gate 10: Regulated Utility & Domain Guardrail Advisory
# ---------------------------------------------------------------------------
def test_gate10_domain_guardrail_utility_advisory(duol_bundle, cesc_bundle):
    duol_note = duol_bundle["res"]["validation"].get("model_suitability_note")
    cesc_note = cesc_bundle["res"]["validation"].get("model_suitability_note")

    # DUOL must NOT trigger model_suitability_note (its deferred assets are DTA, not regulatory deferral assets)
    assert duol_note is None

    # CESC.NS MUST trigger model_suitability_note citing 18.6% of Total Assets, and surface it on Cover!B53
    assert cesc_note is not None
    assert "18.6% of Total Assets" in cesc_note
    assert "18.6% of Total Assets" in str(cesc_bundle["wb_v"]["Cover"]["B53"].value)
