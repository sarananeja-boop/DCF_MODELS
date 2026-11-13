"""
Adversarial Verification Gate Suite for ValuationLabs Revised Workbooks & Engine
================================================================================
Enforces all 10 institutional audit gates across DUOL (US SaaS, SEC 10-K + ASC 842),
CESC.NS (Indian Regulated Utility, Ind AS AR FY26 + Ind AS 116), and HDFCBANK.NS (Bank DDM).
"""

from io import BytesIO
import numpy as np
import openpyxl
import pytest

from main import analyze, AnalyzeRequest
from export.excel_export import generate_excel_report


def _find_row(ws, *needles: str, col: int = 2) -> int:
    """Locate the first worksheet row whose cell in `col` contains any needle."""
    for r in range(1, ws.max_row + 1):
        val = ws.cell(r, col).value
        if isinstance(val, str):
            low = val.lower()
            if all(n.lower() in low for n in needles):
                return r
    raise AssertionError(f"Row matching {needles} in col {col} not found in sheet {ws.title}")


def _find_row_any(ws, *options: tuple[str, ...], col: int = 2) -> int:
    for r in range(1, ws.max_row + 1):
        val = ws.cell(r, col).value
        if isinstance(val, str):
            low = val.lower()
            for needles in options:
                if all(n.lower() in low for n in needles):
                    return r
    raise AssertionError(f"Row matching any of {options} in col {col} not found in sheet {ws.title}")


def _find_year_cols(ws, header_row: int = 4) -> list[str]:
    """Return all column letters with FY/year headers in Historical Financials."""
    cols = []
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if v is not None and any(tag in str(v) for tag in ("FY", "202", "201")):
            cols.append(openpyxl.utils.get_column_letter(c))
    assert len(cols) >= 3, f"Expected >= 3 historical year columns in row {header_row}, found {cols}"
    return cols


@pytest.fixture(scope="module")
def duol_bundle():
    res = analyze(AnalyzeRequest(ticker="DUOL", market="US", monte_carlo_iterations=10000))
    xlsx_bytes = generate_excel_report(res).getvalue()
    return {
        "res": res,
        "wb_f": openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=False),
        "wb_v": openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True),
    }


@pytest.fixture(scope="module")
def cesc_bundle():
    res = analyze(AnalyzeRequest(ticker="CESC.NS", market="IN", monte_carlo_iterations=10000))
    xlsx_bytes = generate_excel_report(res).getvalue()
    return {
        "res": res,
        "wb_f": openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=False),
        "wb_v": openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True),
    }


# ---------------------------------------------------------------------------
# Gate 1: 100% Formula-Driven Workbooks + Zero None/Error Cached Formula Values
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
                        missing_cached.append(
                            f"{sheet_name}!{openpyxl.utils.get_column_letter(c)}{r}: {fv} -> {vv}"
                        )

    assert formula_count >= 10000, f"Expected >= 10,000 live formulas, got {formula_count}"
    assert missing_cached == [], f"Found uncached or error formula cells: {missing_cached[:10]}"


# ---------------------------------------------------------------------------
# Gate 2: Historical 3-Statement Disaggregation & Accounting Identities
# ---------------------------------------------------------------------------
def test_gate2_duol_statutory_income_statement_and_balance_sheet(duol_bundle):
    ws_f = duol_bundle["wb_f"]["Historical Financials"]
    ws_v = duol_bundle["wb_v"]["Historical Financials"]
    cols = _find_year_cols(ws_v)
    last_col = cols[-1]

    r_rev = _find_row(ws_v, "Revenues / Net Sales")
    r_gp = _find_row(ws_v, "Gross Profit")
    r_ebit = _find_row(ws_v, "Operating Income (EBIT)")
    r_dna_is = _find_row(ws_v, "Depreciation & Amortization (D&A)")
    r_tot_assets = _find_row_any(ws_v, ("Total Assets",))
    r_tot_le = _find_row(ws_v, "Total Liabilities & Stockholders' Equity")
    r_bs_chk = _find_row(ws_v, "Balance Sheet Check")

    assert abs(ws_v[f"{last_col}{r_rev}"].value - 1_037_589_000) < 1_000
    assert abs(ws_v[f"{last_col}{r_gp}"].value - 749_457_000) < 1_000
    assert abs(ws_v[f"{last_col}{r_ebit}"].value - 135_570_000) < 1_000
    assert abs(ws_v[f"{last_col}{r_dna_is}"].value - 14_391_000) < 1_000

    for col in cols:
        assert str(ws_f[f"{col}{r_tot_le}"].value).startswith("=")
        assert str(ws_f[f"{col}{r_tot_assets}"].value).startswith("=")
        assert str(ws_f[f"{col}{r_bs_chk}"].value) == f"={col}{r_tot_assets}-{col}{r_tot_le}"
        assert abs(ws_v[f"{col}{r_bs_chk}"].value) < 1.0


def test_gate2_cesc_disaggregated_balance_sheet_and_regulatory_assets(cesc_bundle):
    ws_v = cesc_bundle["wb_v"]["Historical Financials"]
    cols = _find_year_cols(ws_v)
    last_col, prev_col = cols[-1], cols[-2]

    r_ar = _find_row(ws_v, "Accounts Receivable")
    r_ppe = _find_row(ws_v, "Fixed Assets (Net PPE)")
    r_cwip = _find_row(ws_v, "Capital Work in Progress")
    r_reg = _find_row(ws_v, "Regulatory Deferral & Non-Current Deferred Assets")
    r_oth_nca = _find_row(ws_v, "Other Non-Current Assets")
    r_tot_assets = _find_row(ws_v, "Total Assets")
    r_bs_chk = _find_row(ws_v, "Balance Sheet Check")

    assert abs(ws_v[f"{last_col}{r_ar}"].value / 1e7 - 2415.89) < 0.2
    assert abs(ws_v[f"{prev_col}{r_ar}"].value / 1e7 - 2425.27) < 0.2
    assert abs(ws_v[f"{last_col}{r_ppe}"].value / 1e7 - 21724.43) < 0.2
    assert abs(ws_v[f"{last_col}{r_cwip}"].value / 1e7 - 4548.41) < 0.2
    assert abs(ws_v[f"{last_col}{r_reg}"].value / 1e7 - 8665.97) < 0.5
    assert (ws_v[f"{last_col}{r_oth_nca}"].value / ws_v[f"{last_col}{r_tot_assets}"].value) < 0.02

    for col in cols:
        assert abs(ws_v[f"{col}{r_bs_chk}"].value) < 1.0


# ---------------------------------------------------------------------------
# Gate 3: Historical Cash Flow Bridge & Working Capital Sign Convention
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", ["duol_bundle", "cesc_bundle"])
def test_gate3_cash_flow_bridge_and_wc_sign_convention(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    ws_f = bundle["wb_f"]["Historical Financials"]
    ws_v = bundle["wb_v"]["Historical Financials"]
    cols = _find_year_cols(ws_v)

    r_cfo = _find_row(ws_v, "Cash Flow from Operating Activities (CFO)")
    r_cfi = _find_row(ws_v, "Cash Flow from Investing Activities (CFI)")
    r_cff = _find_row(ws_v, "Cash Flow from Financing Activities (CFF)")
    r_net_cf = _find_row(ws_v, "Net Change in Cash")
    r_beg_cash = _find_row(ws_v, "Beginning Cash Position")
    r_fx_roll = _find_row(ws_v, "Effect of Exchange Rate Changes on Cash")
    r_end_cash = _find_row(ws_v, "Ending Cash Position")
    r_ufcf = _find_row_any(ws_v, ("Unlevered Free Cash Flow",))

    for col in cols:
        assert str(ws_f[f"{col}{r_cfo}"].value).startswith("=")
        assert str(ws_f[f"{col}{r_cfi}"].value).startswith("=")
        assert str(ws_f[f"{col}{r_cff}"].value).startswith("=")
        assert str(ws_f[f"{col}{r_net_cf}"].value).startswith("=")
        assert str(ws_f[f"{col}{r_end_cash}"].value) == f"={col}{r_beg_cash}+{col}{r_net_cf}+{col}{r_fx_roll}"
        assert abs(
            ws_v[f"{col}{r_end_cash}"].value
            - (ws_v[f"{col}{r_beg_cash}"].value + ws_v[f"{col}{r_net_cf}"].value + ws_v[f"{col}{r_fx_roll}"].value)
        ) < 1.0
        assert str(ws_f[f"{col}{r_ufcf}"].value).startswith("=")


# ---------------------------------------------------------------------------
# Gate 4 & Gate 5: WACC Debt Excludes Minority Interest; EV Bridge Deducts It
# ---------------------------------------------------------------------------
def test_gate4_and_gate5_cesc_wacc_and_ev_bridge_minority_interest(cesc_bundle):
    res = cesc_bundle["res"]
    ws_wacc_f = cesc_bundle["wb_f"]["WACC 2"]
    ws_wacc_v = cesc_bundle["wb_v"]["WACC 2"]
    ws_dcf_f = cesc_bundle["wb_f"]["DCF Model"]
    ws_dcf_v = cesc_bundle["wb_v"]["DCF Model"]

    r_debt = _find_row(ws_wacc_v, "Total Debt (D)")
    assert str(ws_wacc_f.cell(r_debt, 5).value).startswith("='Historical Financials'!")
    assert abs(res["wacc"]["total_debt"] / 1e7 - 21670.57) < 1.0
    assert abs(res["wacc"]["minority_interest_claim"] / 1e7 - 658.51) < 0.2

    r_we = _find_row(ws_wacc_v, "Weight of Equity")
    r_wd = _find_row(ws_wacc_v, "Weight of Debt")
    assert abs((ws_wacc_v.cell(r_we, 5).value + ws_wacc_v.cell(r_wd, 5).value) - 1.0) < 1e-6

    r_ev = _find_row(ws_dcf_v, "Implied Enterprise Value")
    r_cash = _find_row(ws_dcf_v, "(+) Cash & Cash Equivalents")
    r_less_debt = _find_row(ws_dcf_v, "(−) Total Debt (Borrowings)")
    r_min = _find_row(ws_dcf_v, "Minority")
    r_eq = _find_row(ws_dcf_v, "Implied Equity Value")

    assert str(ws_dcf_f.cell(r_min, 4).value).startswith("='Historical Financials'!")
    assert abs(ws_dcf_v.cell(r_min, 4).value / 1e7 - 658.51) < 0.2
    expected_eq = (
        ws_dcf_v.cell(r_ev, 4).value
        + ws_dcf_v.cell(r_cash, 4).value
        - ws_dcf_v.cell(r_less_debt, 4).value
        - ws_dcf_v.cell(r_min, 4).value
    )
    assert abs(ws_dcf_v.cell(r_eq, 4).value - expected_eq) < 1.0


# ---------------------------------------------------------------------------
# Gate 6: Base Revenue Link, Continuous Growth Fade & Reinvestment Discipline
# ---------------------------------------------------------------------------
def test_gate6_duol_base_revenue_margin_and_capex_convergence(duol_bundle):
    ws_hist = duol_bundle["wb_v"]["Historical Financials"]
    ws_dcf_f = duol_bundle["wb_f"]["DCF Model"]
    ws_dcf_v = duol_bundle["wb_v"]["DCF Model"]
    cols = _find_year_cols(ws_hist)

    r_hist_rev = _find_row(ws_hist, "Revenues / Net Sales")
    r_dcf_rev = _find_row(ws_dcf_v, "Revenue / Turnover")
    r_dcf_g = _find_row(ws_dcf_v, "YoY Revenue Growth Rate")
    r_dcf_m = _find_row(ws_dcf_v, "Operating Margin (EBIT Margin)")
    r_dcf_dna = _find_row(ws_dcf_v, "(+) Depreciation & Amortization")
    r_dcf_capex = _find_row(ws_dcf_v, "(−) Capital Expenditures (CapEx)")

    assert ws_dcf_f.cell(r_dcf_rev, 3).value == f"='Historical Financials'!{cols[-1]}{r_hist_rev}"
    assert abs(ws_dcf_v.cell(r_dcf_rev, 3).value - ws_hist[f"{cols[-1]}{r_hist_rev}"].value) < 1.0
    # Continuous growth fade formulas across Years 2..5 (cols 5..8)
    for col_i in (5, 6, 7, 8):
        assert str(ws_dcf_f.cell(r_dcf_g, col_i).value).startswith("=")
    # Year-5 target EBIT margin converges toward 30.4%, CapEx >= D&A in Year 5
    assert abs(ws_dcf_v.cell(r_dcf_m, 8).value - 0.30377) < 0.01
    assert ws_dcf_v.cell(r_dcf_capex, 8).value >= ws_dcf_v.cell(r_dcf_dna, 8).value - 1.0


# ---------------------------------------------------------------------------
# Gate 7: Cross-Tab Valuation Parity Across Cover, DCF Model, Sensitivity, MC
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", ["duol_bundle", "cesc_bundle"])
def test_gate7_cross_tab_valuation_parity(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    res = bundle["res"]
    wb_v = bundle["wb_v"]

    engine_price = res["dcf_result"]["implied_price"]
    r_cov_iv = _find_row(wb_v["Cover"], "DCF Implied Fair Value (Live Model Formula)", col=2)
    r_dcf_iv = _find_row(wb_v["DCF Model"], "DCF Implied Value per Share")

    cover_price = wb_v["Cover"].cell(r_cov_iv, 3).value
    dcf_price = wb_v["DCF Model"].cell(r_dcf_iv, 4).value
    sens_ref_price = wb_v["Sensitivity"]["F4"].value

    ws_mc = wb_v["Monte Carlo"]
    r_mc_base = _find_row(ws_mc, "Base DCF Implied Fair Value", col=2)
    mc_base = ws_mc.cell(r_mc_base, 3).value

    for label, val in [
        ("Cover live formula", cover_price),
        ("DCF Model implied share price", dcf_price),
        ("Sensitivity reference price", sens_ref_price),
        ("Monte Carlo Base DCF reference", mc_base),
    ]:
        assert abs(val - engine_price) <= 0.01, f"{label} ({val}) != engine_price ({engine_price})"


# ---------------------------------------------------------------------------
# Gate 8: Full Live Sensitivity Audit Engine & Backend Parity (<= 0.01)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", ["duol_bundle", "cesc_bundle"])
def test_gate8_sensitivity_matrices_endogeneity_and_monotonicity(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    res = bundle["res"]
    ws_f = bundle["wb_f"]["Sensitivity"]
    ws_v = bundle["wb_v"]["Sensitivity"]

    grids = [
        res["sensitivity"]["terminal_growth_wacc"]["price_grid"],
        res["sensitivity"]["growth_wacc"]["price_grid"],
        res["sensitivity"]["margin_wacc"]["price_grid"],
    ]
    for idx, start_row in enumerate((8, 21, 34)):
        py_mat = grids[idx]
        for r_off in range(9):
            row_vals = []
            for c_off in range(9):
                fv = ws_f.cell(start_row + r_off, 3 + c_off).value
                vv = ws_v.cell(start_row + r_off, 3 + c_off).value
                assert isinstance(fv, str) and fv.startswith("="), "Static number found in Sensitivity grid"
                assert "$D$23" not in fv, "Forbidden frozen reinvestment shortcut found"
                assert isinstance(vv, (int, float)) and vv >= 0
                row_vals.append(vv)
            assert row_vals[-1] > row_vals[0]

        for c in range(3, 12):
            col_vals = [ws_v.cell(r, c).value for r in range(start_row, start_row + 9)]
            assert col_vals[0] > col_vals[-1]

        # Exact parity check against Python sensitivity engine (checking orientation)
        norm_diff = max(
            abs(py_mat[ri][ci] - ws_v.cell(start_row + ri, 3 + ci).value)
            for ri in range(9) for ci in range(9)
        )
        tr_diff = max(
            abs(py_mat[ci][ri] - ws_v.cell(start_row + ri, 3 + ci).value)
            for ri in range(9) for ci in range(9)
        )
        assert min(norm_diff, tr_diff) <= 0.01, (
            f"Sensitivity table starting row {start_row} parity failed: diff={min(norm_diff, tr_diff)}"
        )


# ---------------------------------------------------------------------------
# Gate 9: Monte Carlo 10,000 Structural Paths, Draw Accounting & Percentiles
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", ["duol_bundle", "cesc_bundle"])
def test_gate9_monte_carlo_structural_paths_and_percentiles(fixture_name, request):
    ws_f = request.getfixturevalue(fixture_name)["wb_f"]["Monte Carlo"]
    ws_v = request.getfixturevalue(fixture_name)["wb_v"]["Monte Carlo"]
    mc = request.getfixturevalue(fixture_name)["res"]["monte_carlo"]

    r_mean = _find_row(ws_v, "Mean Implied Share Price", col=2)
    r_med = _find_row(ws_v, "Median Base Fair Value", col=2)
    r_std = _find_row(ws_v, "Standard Deviation", col=2)
    r_p5 = _find_row(ws_v, "5th Percentile", col=2)
    r_p95 = _find_row(ws_v, "95th Percentile", col=2)

    assert "AVERAGE(" in ws_f.cell(r_mean, 3).value
    assert "MEDIAN(" in ws_f.cell(r_med, 3).value
    assert "STDEV.S(" in ws_f.cell(r_std, 3).value
    assert "PERCENTILE.INC(" in ws_f.cell(r_p5, 3).value
    assert "PERCENTILE.INC(" in ws_f.cell(r_p95, 3).value

    # Find simulation detail table header dynamically
    rep_header = _find_row(ws_v, "Replication #", col=7)
    start_r = rep_header + 1
    prices = np.array([ws_v.cell(r, 8).value for r in range(start_r, start_r + 10000)], dtype=float)
    assert len(prices) == 10000
    assert np.all(prices >= 0)

    assert abs(ws_v.cell(r_mean, 3).value - float(np.mean(prices))) < 1e-3
    assert abs(ws_v.cell(r_med, 3).value - float(np.median(prices))) < 1e-3
    assert abs(ws_v.cell(r_std, 3).value - float(np.std(prices, ddof=1))) < 1e-3
    assert abs(ws_v.cell(r_p5, 3).value - float(np.percentile(prices, 5))) < 1e-3
    assert abs(ws_v.cell(r_p95, 3).value - float(np.percentile(prices, 95))) < 1e-3

    # Verify draw accounting conservation identity
    assert mc["candidate_draws_sampled"] == (
        mc["valid_simulations"] + mc["rejected_draws"] + mc["unused_valid_oversample"]
    )


# ---------------------------------------------------------------------------
# Gate 10: Regulated Utility & Domain Guardrail Advisory
# ---------------------------------------------------------------------------
def test_gate10_domain_guardrail_utility_advisory(duol_bundle, cesc_bundle):
    duol_note = duol_bundle["res"]["validation"].get("model_suitability_note")
    cesc_note = cesc_bundle["res"]["validation"].get("model_suitability_note")

    assert duol_note is None
    assert cesc_note is not None
    assert "18.6% of Total Assets" in cesc_note
    ws_cov = cesc_bundle["wb_v"]["Cover"]
    found = any(
        isinstance(ws_cov.cell(r, c).value, str) and "18.6% of Total Assets" in ws_cov.cell(r, c).value
        for r in range(1, ws_cov.max_row + 1)
        for c in range(1, ws_cov.max_column + 1)
    )
    assert found, "Expected utility regulatory asset advisory on CESC Cover sheet"
