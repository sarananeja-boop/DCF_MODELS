"""
Formatted Excel Workbook Generator — Valuation & Financial Modeling
===================================================================
Produces a comprehensive, multi-sheet DCF model in Excel (.xlsx)
matching the Damodaran model format (as in HUL FINAL MODEL.xlsx).

Sheets Included:
  1. Cover: Executive Summary, Verdict & Metadata
  2. Historical Financials: Full 3-Statement Historicals (P&L, Balance Sheet, Cash Flow) & Native Charts
  3. WACC 2: Live CAPM Cost of Equity, Cost of Debt & Capital Structure
  4. DCF Model: Multi-stage Projections, Live Formulas linking to WACC 2 & Historicals,
                Terminal Value, Enterprise Value to Equity Bridge & Charts
  5. Sensitivity: 2D Implied Price Grids (Growth × WACC & Margin × WACC)
  6. Monte Carlo: Statistical Summary, Confidence Bands (VaR), Distribution Table
                  and an Embedded Native Excel Histogram BarChart.
"""

import logging
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

import numpy as np
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference, Series
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.fill import PatternFillProperties, ColorChoice
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    PatternFill,
    Side,
    numbers,
)
from openpyxl.utils import get_column_letter

logger = logging.getLogger("dcf-api.export")

# ═══════════════════════════════════════════════════════════════════════════
# Workbook Style Constants & Palettes
# ═══════════════════════════════════════════════════════════════════════════

# Colors
NAVY_PRIMARY = "002060"       # Deep Navy (HUL / Damodaran theme)
NAVY_ACCENT = "1E3A8A"        # Dark Blue
SLATE_DARK = "0F172A"         # Body Text Dark Slate
SLATE_MID = "475569"          # Secondary Text
WHITE = "FFFFFF"
LIGHT_BG = "F8FAFC"           # Subtle zebra striping
HIGHLIGHT_BG = "E0E7FF"       # Soft Indigo / Blue highlight for totals
BORDER_COLOR = "D1D5DB"       # Light gray border
DARK_BORDER_COLOR = "002060"  # Dark navy border for totals

# Tab Colors
TAB_COVER = "002060"
TAB_HIST = "1E3A8A"
TAB_WACC = "D97706"
TAB_DCF = "059669"
TAB_SENS = "7C3AED"
TAB_MC = "047857"

# Fills
BANNER_FILL = PatternFill(start_color=NAVY_PRIMARY, end_color=NAVY_PRIMARY, fill_type="solid")
HEADER_FILL = PatternFill(start_color=NAVY_PRIMARY, end_color=NAVY_PRIMARY, fill_type="solid")
ALT_ROW_FILL = PatternFill(start_color=LIGHT_BG, end_color=LIGHT_BG, fill_type="solid")
HIGHLIGHT_FILL = PatternFill(start_color=HIGHLIGHT_BG, end_color=HIGHLIGHT_BG, fill_type="solid")

# Fonts
FONT_TITLE = Font(name="Calibri", size=16, bold=True, color=NAVY_PRIMARY)
FONT_SUBTITLE = Font(name="Calibri", size=11, italic=True, color=SLATE_MID)
FONT_BANNER = Font(name="Calibri", size=11, bold=True, color=WHITE)
FONT_HEADER = Font(name="Calibri", size=10, bold=True, color=WHITE)
FONT_LABEL_BOLD = Font(name="Calibri", size=10, bold=True, color=SLATE_DARK)
FONT_LABEL = Font(name="Calibri", size=10, bold=False, color=SLATE_DARK)
FONT_DATA = Font(name="Calibri", size=10, bold=False, color=SLATE_DARK)
FONT_DATA_BOLD = Font(name="Calibri", size=10, bold=True, color=SLATE_DARK)
FONT_TOTAL = Font(name="Calibri", size=11, bold=True, color=NAVY_PRIMARY)

# Borders
THIN_BORDER = Border(
    left=Side(style="thin", color=BORDER_COLOR),
    right=Side(style="thin", color=BORDER_COLOR),
    top=Side(style="thin", color=BORDER_COLOR),
    bottom=Side(style="thin", color=BORDER_COLOR),
)

TOTAL_BORDER = Border(
    left=Side(style="thin", color=BORDER_COLOR),
    right=Side(style="thin", color=BORDER_COLOR),
    top=Side(style="thin", color=BORDER_COLOR),
    bottom=Side(style="double", color=NAVY_PRIMARY),
)

BANNER_BORDER = Border(
    left=Side(style="medium", color=NAVY_PRIMARY),
    right=Side(style="medium", color=NAVY_PRIMARY),
    top=Side(style="medium", color=NAVY_PRIMARY),
    bottom=Side(style="medium", color=NAVY_PRIMARY),
)

# Alignments
ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_BANNER = Alignment(horizontal="left", vertical="center", indent=1)


# ═══════════════════════════════════════════════════════════════════════════
# Number Formats
# ═══════════════════════════════════════════════════════════════════════════

PCT_FMT = "0.00%"
PCT_1DEC_FMT = "0.0%"
NUM_2DEC_FMT = "#,##0.00"
INT_FMT = "#,##0"
MULT_FMT = "0.00x"


def _safe(d: Any, *keys, default=None):
    """Safely traverse nested dicts."""
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k, default)
        else:
            return default
    return cur


def _get_curr_symbol(currency: str) -> str:
    """Return display symbol for currency."""
    curr_upper = (currency or "").upper()
    if curr_upper in ("INR", "RS", "RUPEE"):
        return "₹"
    elif curr_upper in ("USD", "$"):
        return "$"
    elif curr_upper in ("EUR", "€"):
        return "€"
    elif curr_upper in ("GBP", "£"):
        return "£"
    return curr_upper + " "


def _get_currency_fmt_price(currency: str) -> str:
    """Excel format string for per-share price."""
    sym = _get_curr_symbol(currency)
    return f'"{sym}"#,##0.00'


def _get_currency_fmt_large(currency: str) -> str:
    """Excel format string for total financial numbers (crores/millions/billions)."""
    sym = _get_curr_symbol(currency)
    return f'"{sym}"#,##0'


def _set_banner(ws, row: int, start_col: int, end_col: int, text: str):
    """Create a navy banner header row."""
    start_letter = get_column_letter(start_col)
    end_letter = get_column_letter(end_col)
    ws.merge_cells(f"{start_letter}{row}:{end_letter}{row}")
    cell = ws.cell(row=row, column=start_col, value=text)
    cell.font = FONT_BANNER
    cell.fill = BANNER_FILL
    cell.alignment = ALIGN_BANNER
    ws.row_dimensions[row].height = 24

    for col in range(start_col, end_col + 1):
        c = ws.cell(row=row, column=col)
        c.fill = BANNER_FILL
        c.border = BANNER_BORDER


def _set_table_headers(ws, row: int, headers: List[str], start_col: int = 2):
    """Create styled table header cells."""
    ws.row_dimensions[row].height = 22
    for i, h in enumerate(headers):
        col = start_col + i
        cell = ws.cell(row=row, column=col, value=h)
        cell.font = FONT_HEADER
        cell.fill = HEADER_FILL
        cell.alignment = ALIGN_CENTER if i > 0 else ALIGN_LEFT
        cell.border = THIN_BORDER


def _auto_fit_columns(ws, min_width: int = 14, max_width: int = 35):
    """Auto-fit column widths gracefully."""
    for col_cells in ws.columns:
        first_cell = col_cells[0]
        col_letter = get_column_letter(first_cell.column)
        max_len = min_width
        for cell in col_cells:
            if cell.value is not None and not str(cell.value).startswith("="):
                val_str = str(cell.value)
                max_len = max(max_len, min(len(val_str) + 4, max_width))
        ws.column_dimensions[col_letter].width = max_len


# ═══════════════════════════════════════════════════════════════════════════
# Sheet 1: Cover Page & Valuation Summary
# ═══════════════════════════════════════════════════════════════════════════

def _build_cover(
    wb: Workbook,
    data: Dict[str, Any],
    hist_links: Optional[Dict[str, str]] = None,
    wacc_links: Optional[Dict[str, str]] = None,
    dcf_links: Optional[Dict[str, str]] = None,
    mc_links: Optional[Dict[str, str]] = None,
):
    ws = wb["Cover"] if "Cover" in wb.sheetnames else wb.active
    ws.title = "Cover"
    ws.sheet_properties.tabColor = TAB_COVER
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    market_data = data.get("market_data", {})
    macro = data.get("macro", {})
    wacc_data = data.get("wacc", {})
    dcf = data.get("dcf_result", {})
    mc = data.get("monte_carlo", {})
    mc_stats = mc.get("stats", {})
    verdict = data.get("verdict", {})
    validation = data.get("validation", {})
    currency = company.get("currency", "USD")
    curr_sym = _get_curr_symbol(currency)
    cfmt_price = _get_currency_fmt_price(currency)
    cfmt_large = _get_currency_fmt_large(currency)

    hist_links = hist_links or {}
    wacc_links = wacc_links or {}
    dcf_links = dcf_links or {}
    mc_links = mc_links or {}

    # Title Block
    ws["B2"].value = company.get("name", "Corporate Valuation Model")
    ws["B2"].font = FONT_TITLE
    ws["B3"].value = f"DCF Valuation & Risk Assessment Model — {company.get('ticker', '')}"
    ws["B3"].font = FONT_SUBTITLE
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 18

    # Section 1: Company Profile
    r = 5
    _set_banner(ws, r, 2, 5, "Company Profile & Market Metadata")
    r += 1

    profile_items = [
        ("Company Name", company.get("name")),
        ("Ticker Symbol", company.get("ticker")),
        ("Exchange Market", company.get("market")),
        ("Reporting Currency", currency),
        ("Valuation Date", datetime.now().strftime("%d-%b-%Y")),
        ("Model Engine Version", data.get("metadata", {}).get("model_version", "v2.4.0")),
        ("Data Provenance", data.get("metadata", {}).get("data_provenance", "SEC EDGAR / NSE-BSE Statutory Filings")),
        ("Shares Outstanding", market_data.get("shares_outstanding"), INT_FMT),
        ("Market Capitalization", market_data.get("market_cap"), cfmt_large),
    ]

    for label, val, *fmt_opt in profile_items:
        fmt = fmt_opt[0] if fmt_opt else None
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        val_cell = ws.cell(row=r, column=3, value=val)
        val_cell.font = FONT_DATA
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT if fmt else ALIGN_LEFT
        if fmt:
            val_cell.number_format = fmt

        # Empty border placeholders for cols D & E
        for c in (4, 5):
            ec = ws.cell(row=r, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = THIN_BORDER
        r += 1

    # Section 2: Executive Valuation Summary
    r += 1
    _set_banner(ws, r, 2, 5, "Executive Valuation Summary & Investment Verdict")
    r += 1

    current_price = market_data.get("current_price", 0)
    implied_price = dcf.get("implied_price", 0)
    upside = (implied_price - current_price) / current_price if current_price and current_price > 0 else 0.0
    mc_median = mc_stats.get("median", 0)
    p25 = mc_stats.get("p25", 0)
    p75 = mc_stats.get("p75", 0)
    method_comp = data.get("method_comparison", {})

    dcf_price_formula = f"={dcf_links['price_cell']}" if dcf_links.get("price_cell") else implied_price
    upside_formula = f"={dcf_links['upside_cell']}" if dcf_links.get("upside_cell") else upside
    mc_median_formula = f"={mc_links['median_cell']}" if mc_links.get("median_cell") else mc_median

    val_summary_items = [
        ("Current Market Price (CMP)", current_price, cfmt_price, False),
        ("DCF Implied Fair Value (FCFF Base Case)", implied_price, cfmt_price, True),
        ("DCF Implied Fair Value (Live Model Formula)", dcf_price_formula, cfmt_price, True),
        ("Implied Upside / (Downside)", upside_formula, PCT_FMT, True),
        ("Investment Verdict", verdict.get("verdict", "NEUTRAL"), None, True),
        ("Valuation Methodology", "Enterprise DCF — Unlevered Free Cash Flow (FCFF) discounted at WACC", None, False),
        ("Monte Carlo Median Implied Price", mc_median_formula, cfmt_price, False),
        ("Monte Carlo 50% Confidence Range (P25 – P75)", f"{curr_sym}{p25:,.2f} – {curr_sym}{p75:,.2f}" if p25 else "N/A", None, False),
    ]
    if method_comp and method_comp.get("can_switch"):
        ddm_ref_price = method_comp.get("ddm_implied_price", 0.0)
        diff_pct_dec = ((ddm_ref_price - implied_price) / implied_price) if implied_price and implied_price > 0 else 0.0
        val_summary_items.extend([
            ("Alternative Method: DDM / FCFE Implied Fair Value", ddm_ref_price, cfmt_price, False),
            ("Valuation Method Spread (DDM vs. FCFF %)", diff_pct_dec, PCT_FMT, False),
        ])

    for label, val, fmt, is_bold in val_summary_items:
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if r % 2 == 0 else None)
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        val_cell = ws.cell(row=r, column=3, value=val)
        val_cell.font = FONT_TOTAL if is_bold else FONT_DATA
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT if fmt else ALIGN_LEFT
        if fmt:
            val_cell.number_format = fmt

        for c in (4, 5):
            ec = ws.cell(row=r, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = TOTAL_BORDER if is_bold else THIN_BORDER
        r += 1

    # Section 3: Model Parameters & Valuation Drivers
    r += 1
    _set_banner(ws, r, 2, 5, "Valuation Drivers & Capital Parameters")
    r += 1

    wacc_data = data.get("wacc", {})
    historicals = data.get("historicals", {})
    overrides = data.get("overrides_applied", {})

    rf = f"={wacc_links['rf_cell']}" if wacc_links.get("rf_cell") else macro.get("risk_free_rate", 0)
    beta = f"={wacc_links['beta_cell']}" if wacc_links.get("beta_cell") else market_data.get("beta", 1.0)
    ke = f"={wacc_links['ke_cell']}" if wacc_links.get("ke_cell") else wacc_data.get("cost_of_equity", 0)
    kd = f"={wacc_links['kd_cell']}" if wacc_links.get("kd_cell") else wacc_data.get("cost_of_debt", 0)
    wacc_val_num = wacc_data.get("wacc", 0)
    wacc_val = f"={wacc_links['wacc_cell']}" if wacc_links.get("wacc_cell") else wacc_val_num
    term_g_num = overrides.get("terminal_growth") if overrides.get("terminal_growth") is not None else macro.get("terminal_growth", 0.055 if company.get("market") == "IN" else 0.025)
    term_g = f"={dcf_links['tg_cell']}" if dcf_links.get("tg_cell") else term_g_num
    margin_sched = dcf.get("margin_schedule", [])
    target_ebit_m_num = float(margin_sched[-1]) if margin_sched else float(historicals.get("avg_ebit_margin", 0))
    target_ebit_m = f"={dcf_links['terminal_margin_cell']}" if dcf_links.get("terminal_margin_cell") else target_ebit_m_num
    hist_avg_ebit_m = f"={hist_links['avg_ebit_margin_cell']}" if hist_links.get("avg_ebit_margin_cell") else historicals.get("avg_ebit_margin", 0)

    driver_items = [
        ("Risk-Free Rate (Rf)", rf, PCT_FMT),
        ("Beta (Levered)", beta, NUM_2DEC_FMT),
        ("Cost of Equity (Ke via CAPM)", ke, PCT_FMT),
        ("After-Tax Cost of Debt (Kd)", kd, PCT_FMT),
        ("Weighted Average Cost of Capital (WACC)", wacc_val, PCT_FMT),
        ("Terminal Growth Rate (g)", term_g, PCT_FMT),
        ("Normalized Operating Margin (Target EBIT Margin)", target_ebit_m, PCT_FMT),
        ("Historical 4-Yr Avg EBIT Margin", hist_avg_ebit_m, PCT_FMT),
    ]

    for label, val, fmt in driver_items:
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        val_cell = ws.cell(row=r, column=3, value=val)
        val_cell.font = FONT_DATA
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT
        if fmt:
            val_cell.number_format = fmt

        for c in (4, 5):
            ec = ws.cell(row=r, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = THIN_BORDER
        r += 1

    # Section 4: Model Assumption Status (Defaults vs. User Overrides)
    r += 1
    _set_banner(ws, r, 2, 5, "Model Assumption Status (Defaults vs. User Overrides)")
    r += 1

    diag = data.get("diagnostics", {})
    def_g = float(diag.get("default_growth", historicals.get("rev_cagr", 0.08)) or 0.0)
    def_m = float(diag.get("default_margin", historicals.get("avg_ebit_margin", 0.15)) or 0.0)
    def_w = float(diag.get("default_wacc", wacc_data.get("wacc", 0.10)) or 0.0)
    def_t = float(macro.get("terminal_growth_rate", macro.get("terminal_growth", 0.05 if company.get("market") == "IN" else 0.025)) or 0.0)

    ov_g = overrides.get("revenue_growth")
    ov_m = overrides.get("ebit_margin")
    ov_w = overrides.get("wacc")
    ov_t = overrides.get("terminal_growth")

    app_g = float(ov_g) if ov_g is not None else def_g
    app_m = float(ov_m) if ov_m is not None else def_m
    app_w = float(ov_w) if ov_w is not None else wacc_val_num
    app_t = float(ov_t) if ov_t is not None else term_g_num
    has_user_overrides = any(x is not None for x in (ov_g, ov_m, ov_w, ov_t))

    override_rows = [
        ("Assumption Override Status", "Custom User Overrides Applied" if has_user_overrides else "100% Model Baseline Defaults", None),
        ("Year-1 Revenue Growth (Default vs. Applied)", f"Default: {def_g*100:.1f}% | Applied: {app_g*100:.1f}% ({'Edited' if ov_g is not None else 'Default'})", None),
        ("Target Operating Margin (Default vs. Applied)", f"Default: {def_m*100:.1f}% | Applied: {app_m*100:.1f}% ({'Edited' if ov_m is not None else 'Default'})", None),
        ("Discount Rate / WACC (Default vs. Applied)", f"Default: {def_w*100:.1f}% | Applied: {app_w*100:.1f}% ({'Edited' if ov_w is not None else 'Default'})", None),
        ("Terminal Growth Rate (Default vs. Applied)", f"Default: {def_t*100:.1f}% | Applied: {app_t*100:.1f}% ({'Edited' if ov_t is not None else 'Default'})", None),
    ]

    for label, val, fmt in override_rows:
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        val_cell = ws.cell(row=r, column=3, value=val)
        val_cell.font = FONT_DATA_BOLD if label == "Assumption Override Status" and has_user_overrides else FONT_DATA
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT if fmt else ALIGN_LEFT
        if fmt:
            val_cell.number_format = fmt

        for c in (4, 5):
            ec = ws.cell(row=r, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = THIN_BORDER
        r += 1

    # Section 5: Monte Carlo Simulation & Reproducibility Configuration
    r += 1
    _set_banner(ws, r, 2, 5, "Monte Carlo Simulation & Reproducibility Configuration")
    r += 1

    mc_obj = data.get("monte_carlo", {})
    valid_sims = int(mc_obj.get("valid_simulations") or mc_obj.get("actual_iterations") or 10000)
    total_sims = int(mc_obj.get("total_simulations") or valid_sims)
    rejected_sims = max(0, total_sims - valid_sims)
    zero_sims = int(mc_obj.get("zero_price_simulations") or 0)
    corr_gm = float(mc_obj.get("hist_corr_gm", mc_obj.get("inputs", {}).get("hist_corr_gm", 0.0)) or 0.0)

    mc_config_rows = [
        ("Retained Valid Simulations", valid_sims, INT_FMT),
        ("Candidate Draws Sampled", total_sims, INT_FMT),
        ("Rejected Draws (WACC <= g + 0.50% / Kd <= 0)", rejected_sims, INT_FMT),
        ("Equity Wipeout Draws (Floored at 0.00)", zero_sims, INT_FMT),
        ("Cholesky Growth-Margin Correlation (ρ)", corr_gm, NUM_2DEC_FMT),
        ("Random Seed & Reproducibility Policy", "Deterministic Cholesky (Seed = 42)", None),
    ]

    for label, val, fmt in mc_config_rows:
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        val_cell = ws.cell(row=r, column=3, value=val)
        val_cell.font = FONT_DATA
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT if fmt else ALIGN_LEFT
        if fmt:
            val_cell.number_format = fmt

        for c in (4, 5):
            ec = ws.cell(row=r, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = THIN_BORDER
        r += 1

    # Verdict Description & Model Suitability Advisory box
    desc = verdict.get("description", "")
    suitability_note = validation.get("model_suitability_note") or ""
    combined_note = f"Note: {desc}" if desc else ""
    if suitability_note:
        combined_note = f"{combined_note}\n{suitability_note}".strip()
    if combined_note:
        r += 1
        ws.merge_cells(f"B{r}:E{r+2}")
        desc_cell = ws.cell(row=r, column=2, value=combined_note)
        desc_cell.font = Font(name="Calibri", size=10, italic=True, color=SLATE_MID)
        desc_cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=18, max_width=35)
    ws.freeze_panes = "B5"


# ═══════════════════════════════════════════════════════════════════════════
# Sheet 2: Historical Financial Statements & Drivers
# ═══════════════════════════════════════════════════════════════════════════

def _build_historicals(wb: Workbook, data: Dict[str, Any]):
    ws = wb.create_sheet("Historical Financials")
    ws.sheet_properties.tabColor = TAB_HIST
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    currency = company.get("currency", "USD")
    cfmt_large = _get_currency_fmt_large(currency)
    cfmt_price = _get_currency_fmt_price(currency)
    historicals = data.get("historicals", {})

    years = historicals.get("years", [])
    if not years:
        years = ["Year 1", "Year 2", "Year 3", "Year 4"]
    n_years = len(years)

    statements = historicals.get("statements", {})
    inc_stmt = statements.get("income_statement", {})
    bs_stmt = statements.get("balance_sheet", {})
    cf_stmt = statements.get("cash_flow", {})

    # Banner Header
    r = 2
    end_col = 2 + n_years + 2  # Metric + Years + Average + StdDev
    _set_banner(ws, r, 2, end_col, f"Historical Financial Statements & 3-Statement Model — {company.get('name', '')} ({company.get('ticker', '')})")
    r += 2

    # Headers
    headers = ["Financial Statement Item"] + [f"FY {y}" for y in years] + ["Historical Average", "Standard Deviation"]
    _set_table_headers(ws, r, headers, start_col=2)
    header_row = r
    r += 1

    first_col_letter = get_column_letter(3)
    last_col_letter = get_column_letter(2 + n_years)

    def _write_sub_banner(title: str):
        nonlocal r
        _set_banner(ws, r, 2, end_col, title)
        r += 1

    def _write_statement_row(label: str, values: List[float], fmt: str, is_bold: bool = False,
                             is_growth_of: Optional[int] = None, is_margin_of: Optional[int] = None,
                             formula_subtraction: Optional[tuple] = None,
                             formula_sum: Optional[List[int]] = None,
                             custom_formula: Optional[str] = None):
        nonlocal r
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if r % 2 == 0 else None)
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_TOTAL if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        for idx in range(n_years):
            col = 3 + idx
            cur_col = get_column_letter(col)
            cell = ws.cell(row=r, column=col)
            cell.font = FONT_DATA_BOLD if is_bold else FONT_DATA
            cell.fill = fill or PatternFill(fill_type=None)
            cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
            cell.alignment = ALIGN_RIGHT
            cell.number_format = fmt

            if is_growth_of is not None:
                if idx == 0:
                    cell.value = "-"
                    cell.alignment = ALIGN_CENTER
                else:
                    prev_col = get_column_letter(col - 1)
                    cell.value = f"=IF({prev_col}{is_growth_of}<>0, ({cur_col}{is_growth_of}-{prev_col}{is_growth_of})/{prev_col}{is_growth_of}, 0)"
            elif is_margin_of is not None:
                cell.value = f"=IF({cur_col}{is_margin_of[1]}<>0, {cur_col}{is_margin_of[0]}/{cur_col}{is_margin_of[1]}, 0)"
            elif formula_subtraction is not None:
                row_a, row_b = formula_subtraction
                cell.value = f"={cur_col}{row_a}-{cur_col}{row_b}"
            elif formula_sum is not None:
                parts = [f"{cur_col}{srow}" for srow in formula_sum]
                cell.value = f"={'+'.join(parts)}"
            elif custom_formula is not None:
                cell.value = custom_formula.replace("{col}", cur_col)
            else:
                val = values[idx] if idx < len(values) else 0.0
                cell.value = val

        # Historical Average Column
        avg_col = 3 + n_years
        avg_cell = ws.cell(row=r, column=avg_col)
        avg_cell.font = FONT_DATA_BOLD
        avg_cell.fill = fill or PatternFill(fill_type=None)
        avg_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        avg_cell.alignment = ALIGN_RIGHT
        avg_cell.number_format = fmt

        # Historical Std Dev Column
        std_col = avg_col + 1
        std_cell = ws.cell(row=r, column=std_col)
        std_cell.font = FONT_DATA
        std_cell.fill = fill or PatternFill(fill_type=None)
        std_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        std_cell.alignment = ALIGN_RIGHT
        std_cell.number_format = fmt

        if is_growth_of is not None:
            start_growth_col = get_column_letter(4)
            avg_cell.value = f"=AVERAGE({start_growth_col}{r}:{last_col_letter}{r})"
            std_cell.value = f"=IFERROR(_xlfn.STDEV.S({start_growth_col}{r}:{last_col_letter}{r}), 0)"
        else:
            avg_cell.value = f"=AVERAGE({first_col_letter}{r}:{last_col_letter}{r})"
            std_cell.value = f"=IFERROR(_xlfn.STDEV.S({first_col_letter}{r}:{last_col_letter}{r}), 0)"

        this_row = r
        r += 1
        return this_row

    # ═══════════════════════════════════════════════════════════════════════════
    # PART I: INCOME STATEMENT (P&L) — Disaggregated Statutory + Normalized View
    # ═══════════════════════════════════════════════════════════════════════════
    _write_sub_banner("Part I: Income Statement (P&L)")

    raw_rev = inc_stmt.get("Revenues / Net Sales") or historicals.get("revenue", [])
    row_rev = _write_statement_row("Revenues / Net Sales", raw_rev, cfmt_large, is_bold=True)
    row_rev_growth = _write_statement_row("YoY Revenue Growth Rate", [], PCT_FMT, is_growth_of=row_rev)

    raw_cogs = inc_stmt.get("Cost of Goods Sold (COGS)", [])
    row_cogs = _write_statement_row("Cost of Goods Sold (COGS)", raw_cogs, cfmt_large)
    row_cogs_pct = _write_statement_row("COGS % of Sales", [], PCT_FMT, is_margin_of=(row_cogs, row_rev))

    raw_gp = inc_stmt.get("Gross Profit", [])
    row_gp = _write_statement_row("Gross Profit", raw_gp, cfmt_large, is_bold=True,
                                  formula_subtraction=(row_rev, row_cogs))
    row_gp_margin = _write_statement_row("Gross Margin (%)", [], PCT_FMT, is_margin_of=(row_gp, row_rev))

    raw_sga = inc_stmt.get("Selling, General & Admin (SG&A)", [])
    row_sga = _write_statement_row("Selling, General & Administrative (SG&A)", raw_sga, cfmt_large)
    row_sga_pct = _write_statement_row("SG&A % of Sales", [], PCT_FMT, is_margin_of=(row_sga, row_rev))

    raw_emp = inc_stmt.get("Employee Benefits & Personnel Expenses", [0.0] * n_years)
    row_emp = _write_statement_row("Employee Benefits & Personnel Expenses", raw_emp, cfmt_large)

    raw_rnd = inc_stmt.get("Research & Development (R&D)", [0.0] * n_years)
    row_rnd = _write_statement_row("Research & Development (R&D)", raw_rnd, cfmt_large)

    raw_other_opex_stat = inc_stmt.get("Other Operating Expenses (Statutory)", [0.0] * n_years)
    row_other_opex = _write_statement_row("Other Operating Expenses (Operations & Admin)", raw_other_opex_stat, cfmt_large)

    raw_opex_dna = inc_stmt.get("Depreciation & Amortization in Operating Expenses", [0.0] * n_years)
    row_opex_dna = _write_statement_row("Depreciation & Amortization in Operating Expenses", raw_opex_dna, cfmt_large)

    raw_stat_opinc = inc_stmt.get("Statutory Operating Income", historicals.get("ebit", []))
    row_stat_opinc = _write_statement_row(
        "Statutory Operating Income (Before Regulatory / One-Off Adjustments)",
        raw_stat_opinc,
        cfmt_large,
        is_bold=True,
        custom_formula=f"={'{col}'}{row_gp}-{'{col}'}{row_sga}-{'{col}'}{row_emp}-{'{col}'}{row_rnd}-{'{col}'}{row_other_opex}-{'{col}'}{row_opex_dna}",
    )

    raw_reg_adj = inc_stmt.get("Regulatory Deferral & Operating Adjustments", [0.0] * n_years)
    row_reg_adj = _write_statement_row("Regulatory Deferral & Operating Adjustments", raw_reg_adj, cfmt_large)

    raw_ebit = inc_stmt.get("Operating Income (EBIT)") or historicals.get("ebit", [])
    row_ebit = _write_statement_row(
        "Operating Income (EBIT)",
        raw_ebit,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_stat_opinc, row_reg_adj],
    )
    row_ebit_margin = _write_statement_row("EBIT Margin (%)", [], PCT_FMT, is_margin_of=(row_ebit, row_rev))

    raw_dna = inc_stmt.get("Depreciation & Amortization (D&A)") or historicals.get("dna", [])
    row_dna = _write_statement_row("Depreciation & Amortization (D&A)", raw_dna, cfmt_large)
    row_dna_pct = _write_statement_row("D&A % of Sales", [], PCT_FMT, is_margin_of=(row_dna, row_rev))

    raw_ebitda = inc_stmt.get("Operating Profit (EBITDA)") or historicals.get("ebitda", [])
    row_ebitda = _write_statement_row(
        "Operating Profit (EBITDA)",
        raw_ebitda,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_ebit, row_dna],
    )
    row_ebitda_margin = _write_statement_row("EBITDA Margin (%)", [], PCT_FMT, is_margin_of=(row_ebitda, row_rev))

    raw_ie = inc_stmt.get("Interest Expense", [])
    row_ie = _write_statement_row("Interest Expense", raw_ie, cfmt_large)
    row_ie_pct = _write_statement_row("Interest % of Sales", [], PCT_FMT, is_margin_of=(row_ie, row_rev))

    raw_non_op = inc_stmt.get("Non-Operating Income / (Expense)", [0.0] * n_years)
    row_non_op = _write_statement_row("Non-Operating Income / (Expense)", raw_non_op, cfmt_large)

    raw_ebt = inc_stmt.get("Earnings Before Tax (EBT)", [])
    row_ebt = _write_statement_row(
        "Earnings Before Tax (EBT)",
        raw_ebt,
        cfmt_large,
        is_bold=True,
        custom_formula=f"={'{col}'}{row_ebit}-{'{col}'}{row_ie}+{'{col}'}{row_non_op}",
    )
    row_ebt_margin = _write_statement_row("EBT Margin (%)", [], PCT_FMT, is_margin_of=(row_ebt, row_rev))

    raw_tax = inc_stmt.get("Income Tax Expense", [])
    row_tax = _write_statement_row("Income Tax Expense", raw_tax, cfmt_large)
    row_tax_rate = _write_statement_row("Effective Tax Rate (%)", [], PCT_FMT, is_margin_of=(row_tax, row_ebt))

    raw_cons_pat = inc_stmt.get("Profit After Tax (Consolidated PAT)", [])
    row_cons_pat = _write_statement_row(
        "Profit After Tax (Consolidated Group PAT)",
        raw_cons_pat,
        cfmt_large,
        is_bold=True,
        formula_subtraction=(row_ebt, row_tax),
    )

    raw_min_int_inc = inc_stmt.get("Minority Interest & Exceptional Items", [0.0] * n_years)
    row_min_int_inc = _write_statement_row("Minority Interest & Exceptional Items", raw_min_int_inc, cfmt_large)

    raw_ni = inc_stmt.get("Net Profit / Net Income") or historicals.get("net_income", [])
    row_ni = _write_statement_row(
        "Net Profit / Net Income",
        raw_ni,
        cfmt_large,
        is_bold=True,
        formula_subtraction=(row_cons_pat, row_min_int_inc),
    )
    row_ni_margin = _write_statement_row("Net Profit Margin (%)", [], PCT_FMT, is_margin_of=(row_ni, row_rev))

    raw_shares = inc_stmt.get("Diluted Shares Outstanding") or ([float(data.get("market_data", {}).get("shares_outstanding", 0))] * n_years)
    raw_bas_shares = inc_stmt.get("Basic Weighted-Average Shares") or raw_shares
    row_bas_shares = _write_statement_row("Basic Weighted-Average Shares", raw_bas_shares, INT_FMT)
    row_bas_eps = _write_statement_row(
        "Basic Earnings Per Share (Basic EPS)",
        [],
        cfmt_price,
        is_margin_of=(row_ni, row_bas_shares),
    )

    row_shares = _write_statement_row("Diluted Shares Outstanding", raw_shares, INT_FMT)

    row_eps = _write_statement_row(
        "Earnings Per Share (EPS)",
        [],
        cfmt_price,
        is_bold=True,
        is_margin_of=(row_ni, row_shares),
    )
    row_eps_growth = _write_statement_row("YoY EPS Growth Rate (%)", [], PCT_FMT, is_growth_of=row_eps)

    raw_pe_shares = inc_stmt.get("Period-End Shares Outstanding") or raw_shares
    row_pe_shares = _write_statement_row("Period-End Shares Outstanding", raw_pe_shares, INT_FMT)

    raw_divs = inc_stmt.get("Cash Dividends Paid") or historicals.get("dividends_paid", [])
    row_divs = _write_statement_row("Cash Dividends Paid", raw_divs, cfmt_large)
    row_payout = _write_statement_row("Dividend Payout Ratio (%)", [], PCT_FMT, is_margin_of=(row_divs, row_ni))
    row_ret = _write_statement_row("Retained Earnings Addition", [], cfmt_large,
                                   formula_subtraction=(row_ni, row_divs))

    # ═══════════════════════════════════════════════════════════════════════════
    # PART II: BALANCE SHEET — Full Disaggregated Assets, Liabilities & Equity
    # ═══════════════════════════════════════════════════════════════════════════
    r += 1
    _write_sub_banner("Part II: Balance Sheet")

    raw_sc = bs_stmt.get("Equity Share Capital", [])
    row_sc = _write_statement_row("Equity Share Capital", raw_sc, cfmt_large)

    raw_apic = bs_stmt.get("Additional Paid-In Capital (APIC)", [0.0] * n_years)
    row_apic = _write_statement_row("Additional Paid-In Capital (APIC)", raw_apic, cfmt_large)

    raw_ret_earn = bs_stmt.get("Retained Earnings / Reserves")
    if raw_ret_earn is None:
        raw_res_legacy = bs_stmt.get("Reserves & Retained Earnings", [0.0] * n_years)
        raw_ret_earn = [float(r_v - a_v) for r_v, a_v in zip(raw_res_legacy, raw_apic)]
    row_res = _write_statement_row("Retained Earnings / Reserves & Surplus", raw_ret_earn, cfmt_large)

    raw_equity = bs_stmt.get("Total Stockholders' Equity") or historicals.get("book_value", [])
    row_equity = _write_statement_row(
        "Total Stockholders' Equity",
        raw_equity,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_sc, row_apic, row_res],
    )

    raw_min_int_bs = bs_stmt.get("Minority Interest", [0.0] * n_years)
    row_min_int_bs = _write_statement_row("Minority Interest (Non-Controlling Interest)", raw_min_int_bs, cfmt_large)

    raw_st_debt = bs_stmt.get("Short-Term Borrowings", [])
    row_st_debt = _write_statement_row("Short-Term Borrowings", raw_st_debt, cfmt_large)

    raw_lt_debt = bs_stmt.get("Long-Term Borrowings", [])
    row_lt_debt = _write_statement_row("Long-Term Borrowings", raw_lt_debt, cfmt_large)

    raw_tot_debt = bs_stmt.get("Total Debt", [])
    row_tot_debt = _write_statement_row("Total Debt (Financial Borrowings)", raw_tot_debt, cfmt_large, is_bold=True,
                                        formula_sum=[row_st_debt, row_lt_debt])

    raw_lease = bs_stmt.get("Capital Lease Obligations", [0.0] * n_years)
    row_lease = _write_statement_row("Capital Lease Obligations (ASC 842 / Ind AS 116)", raw_lease, cfmt_large)

    raw_ap = bs_stmt.get("Accounts Payable & Trade Payables", [0.0] * n_years)
    row_ap = _write_statement_row("Accounts Payable & Trade Payables", raw_ap, cfmt_large)

    raw_accrued = bs_stmt.get("Accrued Expenses & Current Tax Payable", [0.0] * n_years)
    row_accrued = _write_statement_row("Accrued Expenses & Current Tax Payable", raw_accrued, cfmt_large)

    raw_def_rev = bs_stmt.get("Deferred Revenue & Unearned Liabilities", [0.0] * n_years)
    row_def_rev = _write_statement_row("Deferred Revenue & Unearned Liabilities", raw_def_rev, cfmt_large)

    raw_dtl = bs_stmt.get("Deferred Tax Liabilities", [0.0] * n_years)
    row_dtl = _write_statement_row("Deferred Tax Liabilities", raw_dtl, cfmt_large)

    raw_prov_bs = bs_stmt.get("Provisions & Post-Retirement Obligations", [0.0] * n_years)
    row_prov_bs = _write_statement_row("Provisions & Post-Retirement Obligations", raw_prov_bs, cfmt_large)

    raw_other_liab = bs_stmt.get("Other Operating & Non-Current Liabilities")
    if raw_other_liab is None:
        raw_other_liab = bs_stmt.get("Other Liabilities", [0.0] * n_years)
    row_other_liab = _write_statement_row("Other Operating & Non-Current Liabilities", raw_other_liab, cfmt_large)

    raw_tot_liab_eq = bs_stmt.get("Total Liabilities & Equity", [])
    row_tot_liab_eq = _write_statement_row(
        "Total Liabilities & Stockholders' Equity",
        raw_tot_liab_eq,
        cfmt_large,
        is_bold=True,
        formula_sum=[
            row_equity,
            row_min_int_bs,
            row_tot_debt,
            row_lease,
            row_ap,
            row_accrued,
            row_def_rev,
            row_dtl,
            row_prov_bs,
            row_other_liab,
        ],
    )

    # Spacer
    r += 1
    raw_ppe = bs_stmt.get("Fixed Assets (Net PPE)", [])
    row_ppe = _write_statement_row("Fixed Assets (Net PPE)", raw_ppe, cfmt_large, is_bold=True)

    raw_cwip = bs_stmt.get("Capital Work in Progress (CWIP)", [])
    row_cwip = _write_statement_row("Capital Work in Progress (CWIP)", raw_cwip, cfmt_large)

    raw_intang = bs_stmt.get("Intangible Assets & Goodwill", [0.0] * n_years)
    row_intang = _write_statement_row("Intangible Assets & Goodwill", raw_intang, cfmt_large)

    raw_inv_nc = bs_stmt.get("Investments", [])
    row_inv_nc = _write_statement_row("Non-Current Investments", raw_inv_nc, cfmt_large)

    raw_reg_nc = bs_stmt.get("Regulatory Deferral & Non-Current Deferred Assets", [0.0] * n_years)
    row_reg_nc = _write_statement_row("Regulatory Deferral & Non-Current Deferred Assets", raw_reg_nc, cfmt_large)

    raw_oth_nc = bs_stmt.get("Other Non-Current Assets (Disaggregated)")
    if raw_oth_nc is None:
        raw_oth_nc = bs_stmt.get("Other Non-Current Assets", [])
    row_oth_nc = _write_statement_row("Other Non-Current Assets", raw_oth_nc, cfmt_large)

    raw_tot_nc = bs_stmt.get("Total Non-Current Assets", [])
    row_tot_nc = _write_statement_row(
        "Total Non-Current Assets",
        raw_tot_nc,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_ppe, row_cwip, row_intang, row_inv_nc, row_reg_nc, row_oth_nc],
    )

    # Spacer
    r += 1
    raw_ar = bs_stmt.get("Receivables", [])
    row_ar = _write_statement_row("Trade / Accounts Receivable", raw_ar, cfmt_large)

    raw_inv = bs_stmt.get("Inventory", [])
    row_inv = _write_statement_row("Inventories", raw_inv, cfmt_large)

    raw_cash_bank = bs_stmt.get("Cash & Bank Balances", [])
    raw_sti = bs_stmt.get("Short-Term Investments", [])
    has_sti = any(raw_sti)

    wacc_data = data.get("wacc", {})
    metrics_data = data.get("metrics", {})
    dcf_data = data.get("dcf_result", {})
    fallback_cash = float(
        wacc_data.get("total_cash")
        or metrics_data.get("cash")
        or metrics_data.get("cash_and_equivalents")
        or dcf_data.get("cash")
        or 0.0
    )
    if not any(raw_cash_bank) and not has_sti and fallback_cash > 0:
        raw_cash_bank = [0.0] * max(n_years - 1, 0) + [fallback_cash]

    row_cash_bank = _write_statement_row("Cash & Bank Balances", raw_cash_bank, cfmt_large)
    row_sti = _write_statement_row("Short-Term Investments / Marketable Securities", raw_sti, cfmt_large)

    # Total Cash & Marketable Securities (Includes liquid short-term investments)
    max_cash_len = max(len(raw_cash_bank), len(raw_sti), 1)
    raw_tot_cash = [
        (raw_cash_bank[i] if i < len(raw_cash_bank) else 0.0) + (raw_sti[i] if i < len(raw_sti) else 0.0)
        for i in range(max_cash_len)
    ]
    row_tot_cash = _write_statement_row(
        "Total Cash & Marketable Securities",
        raw_tot_cash,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_cash_bank, row_sti],
    )

    raw_prepaid_ca = bs_stmt.get("Deferred Costs, Contract & Prepaid Assets", [0.0] * n_years)
    row_prepaid_ca = _write_statement_row("Deferred Costs, Contract & Prepaid Assets", raw_prepaid_ca, cfmt_large)

    raw_oth_ca = bs_stmt.get("Other Current Assets (Disaggregated)")
    if raw_oth_ca is None:
        raw_oth_ca = bs_stmt.get("Other Current Assets", [])
    row_oth_ca = _write_statement_row("Other Current Assets", raw_oth_ca, cfmt_large)

    raw_tot_ca = bs_stmt.get("Total Current Assets", [])
    row_tot_ca = _write_statement_row(
        "Total Current Assets",
        raw_tot_ca,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_ar, row_inv, row_tot_cash, row_prepaid_ca, row_oth_ca],
    )

    raw_tot_assets = bs_stmt.get("Total Assets", [])
    row_tot_assets = _write_statement_row("Total Assets", raw_tot_assets, cfmt_large, is_bold=True,
                                          formula_sum=[row_tot_nc, row_tot_ca])

    row_bs_check = _write_statement_row("Balance Sheet Check (Assets − Liabilities & Equity)", [], cfmt_large, is_bold=True,
                                        formula_subtraction=(row_tot_assets, row_tot_liab_eq))

    # Determine latest column coordinate for DCF model linking
    latest_cash_col_letter = get_column_letter(2 + n_years)
    avg_col_letter = get_column_letter(3 + n_years)
    cash_cell_coord = f"'Historical Financials'!{latest_cash_col_letter}{row_tot_cash}"

    # ═══════════════════════════════════════════════════════════════════════════
    # PART III: CASH FLOW STATEMENT & FCFF RECONCILIATION
    # ═══════════════════════════════════════════════════════════════════════════
    r += 1
    _write_sub_banner("Part III: Cash Flow Statement & Unlevered FCFF Schedule")

    raw_cfo_ni = cf_stmt.get("CFO Starting Profit (Net Income / PBT)") or cf_stmt.get("Net Profit from Operations") or historicals.get("net_income", [])
    row_cfo_ni = _write_statement_row("Operating Activities: Starting Profit (Net Income / PBT)", raw_cfo_ni, cfmt_large)

    raw_cfo_dna = cf_stmt.get("Depreciation & Amortization (Reported CF)") or cf_stmt.get("Depreciation & Amortization") or historicals.get("dna", [])
    row_cfo_dna = _write_statement_row("Add: Depreciation & Amortization (Cash Flow)", raw_cfo_dna, cfmt_large)

    raw_cfo_sbc = cf_stmt.get("Stock-Based Compensation (SBC)", [0.0] * n_years)
    row_cfo_sbc = _write_statement_row("Add: Stock-Based Compensation (SBC)", raw_cfo_sbc, cfmt_large)

    raw_cfo_deftax = cf_stmt.get("Deferred Income Taxes", [0.0] * n_years)
    row_cfo_deftax = _write_statement_row("Deferred Income Taxes", raw_cfo_deftax, cfmt_large)

    raw_cfo_wc = cf_stmt.get("Change in Working Capital", [0.0] * n_years)
    row_cfo_wc = _write_statement_row("Working Capital Changes (Cash Flow Statement)", raw_cfo_wc, cfmt_large)

    raw_cfo_tax = cf_stmt.get("Direct Taxes Paid", [0.0] * n_years)
    row_cfo_tax = _write_statement_row("Direct Taxes Paid / Refunds", raw_cfo_tax, cfmt_large)

    raw_cfo = cf_stmt.get("Cash Flow from Operating Activities (CFO)", [0.0] * n_years)
    raw_cfo_other = cf_stmt.get("Other Non-Cash & Operating Adjustments")
    if raw_cfo_other is None:
        raw_cfo_other = [
            float(raw_cfo[i] - (raw_cfo_ni[i] + raw_cfo_dna[i] + raw_cfo_sbc[i] + raw_cfo_deftax[i] + raw_cfo_wc[i] + raw_cfo_tax[i]))
            if i < len(raw_cfo) else 0.0
            for i in range(n_years)
        ]
    row_cfo_other = _write_statement_row("Other Non-Cash & Operating Adjustments", raw_cfo_other, cfmt_large)

    row_cfo = _write_statement_row(
        "Cash Flow from Operating Activities (CFO)",
        raw_cfo,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_cfo_ni, row_cfo_dna, row_cfo_sbc, row_cfo_deftax, row_cfo_wc, row_cfo_tax, row_cfo_other],
    )

    r += 1
    raw_capex = cf_stmt.get("Fixed Assets Purchased (CapEx)") or historicals.get("capex", [])
    row_capex = _write_statement_row("Investing Activities: Capital Expenditures (CapEx)", raw_capex, cfmt_large)

    raw_cfi_acq = cf_stmt.get("Net Acquisitions, Asset Sales & Intangibles", [0.0] * n_years)
    row_cfi_acq = _write_statement_row("Net Acquisitions, Asset Disposals & Intangibles", raw_cfi_acq, cfmt_large)

    raw_inv_cf = cf_stmt.get("Net Investments Cash Flow", [0.0] * n_years)
    row_inv_cf = _write_statement_row("Net Investment Purchase / (Sale)", raw_inv_cf, cfmt_large)

    raw_cfi = cf_stmt.get("Cash Flow from Investing Activities (CFI)", [0.0] * n_years)
    raw_cfi_other = cf_stmt.get("Interest, Dividends Received & Other Investing Cash Flows")
    if raw_cfi_other is None:
        raw_cfi_other = [
            float(raw_cfi[i] - (-raw_capex[i] + raw_cfi_acq[i] + raw_inv_cf[i]))
            if i < len(raw_cfi) else 0.0
            for i in range(n_years)
        ]
    row_cfi_other = _write_statement_row("Interest, Dividends Received & Other Investing Cash Flows", raw_cfi_other, cfmt_large)

    row_cfi = _write_statement_row(
        "Cash Flow from Investing Activities (CFI)",
        raw_cfi,
        cfmt_large,
        is_bold=True,
        custom_formula=f"=-{'{col}'}{row_capex}+{'{col}'}{row_cfi_acq}+{'{col}'}{row_inv_cf}+{'{col}'}{row_cfi_other}",
    )

    r += 1
    raw_debt_cf = cf_stmt.get("Net Debt Flow", [0.0] * n_years)
    row_debt_cf = _write_statement_row("Financing Activities: Net Borrowings Flow", raw_debt_cf, cfmt_large)

    raw_div_cf = cf_stmt.get("Dividends Paid") or historicals.get("dividends_paid", [0.0] * n_years)
    row_div_cf = _write_statement_row("Dividends Paid", raw_div_cf, cfmt_large)

    raw_int_cff = cf_stmt.get("Interest & Finance Costs Paid (CFF)", [0.0] * n_years)
    row_int_cff = _write_statement_row("Interest & Finance Costs Paid (CFF)", raw_int_cff, cfmt_large)

    raw_cff = cf_stmt.get("Cash Flow from Financing Activities (CFF)", [0.0] * n_years)
    raw_cff_other = cf_stmt.get("Net Equity Issuance, Options, Taxes & Other Financing Flows")
    if raw_cff_other is None:
        raw_cff_other = [
            float(raw_cff[i] - (raw_debt_cf[i] - raw_div_cf[i] + raw_int_cff[i]))
            if i < len(raw_cff) else 0.0
            for i in range(n_years)
        ]
    row_cff_other = _write_statement_row("Net Equity Issuance, Options, Tax Withholding & Lease Principal", raw_cff_other, cfmt_large)

    row_cff = _write_statement_row(
        "Cash Flow from Financing Activities (CFF)",
        raw_cff,
        cfmt_large,
        is_bold=True,
        custom_formula=f"={'{col}'}{row_debt_cf}-{'{col}'}{row_div_cf}+{'{col}'}{row_int_cff}+{'{col}'}{row_cff_other}",
    )

    r += 1
    raw_net_cf = cf_stmt.get("Net Change in Cash", [0.0] * n_years)
    raw_fx_cf = cf_stmt.get("FX & Other Cash Flow Adjustments")
    if raw_fx_cf is None:
        raw_fx_cf = [
            float(raw_net_cf[i] - (raw_cfo[i] + raw_cfi[i] + raw_cff[i]))
            if i < len(raw_net_cf) else 0.0
            for i in range(n_years)
        ]
    row_fx_cf = _write_statement_row("FX & Other Cash Flow Adjustments", raw_fx_cf, cfmt_large)

    row_net_cf = _write_statement_row(
        "Net Change in Cash & Cash Equivalents",
        raw_net_cf,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_cfo, row_cfi, row_cff, row_fx_cf],
    )

    raw_end_cash = cf_stmt.get("Ending Cash Position", [0.0] * n_years)
    raw_beg_cash = [
        float(raw_end_cash[i] - raw_net_cf[i]) if i < len(raw_end_cash) and i < len(raw_net_cf) else 0.0
        for i in range(n_years)
    ]
    row_beg_cash = _write_statement_row("Beginning Cash Position (Incl. Restricted Cash)", raw_beg_cash, cfmt_large)

    row_end_cash = _write_statement_row(
        "Ending Cash Position",
        raw_end_cash,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_beg_cash, row_net_cf],
    )

    raw_restr_cash = cf_stmt.get("Less: Restricted Cash in Ending Cash Position", [0.0] * n_years)
    row_restr_cash = _write_statement_row("Less: Restricted Cash in Ending Cash Position", raw_restr_cash, cfmt_large)

    raw_fcf = cf_stmt.get("Free Cash Flow (Levered FCF)") or cf_stmt.get("Free Cash Flow (FCFF)", [])
    row_fcf = _write_statement_row("Free Cash Flow (Levered FCF = CFO − CapEx)", raw_fcf, cfmt_large, is_bold=True,
                                   formula_subtraction=(row_cfo, row_capex))

    # Operating Working Capital & Unlevered FCFF Schedule
    raw_non_cash_ca = bs_stmt.get("Non-Cash Operating Current Assets")
    if raw_non_cash_ca is None:
        raw_non_cash_ca = [
            float((raw_tot_ca[i] if i < len(raw_tot_ca) else 0.0) - (raw_tot_cash[i] if i < len(raw_tot_cash) else 0.0))
            for i in range(n_years)
        ]
    row_non_cash_ca = _write_statement_row("Non-Cash Operating Current Assets", raw_non_cash_ca, cfmt_large)

    raw_non_debt_cl = bs_stmt.get("Non-Debt Operating Current Liabilities")
    if raw_non_debt_cl is None:
        raw_non_debt_cl = [
            float((raw_ap[i] if i < len(raw_ap) else 0.0) + (raw_accrued[i] if i < len(raw_accrued) else 0.0) + (raw_def_rev[i] if i < len(raw_def_rev) else 0.0))
            for i in range(n_years)
        ]
    row_non_debt_cl = _write_statement_row("Non-Debt Operating Current Liabilities", raw_non_debt_cl, cfmt_large)

    raw_op_nwc = bs_stmt.get("Net Operating Working Capital (NWC)", [0.0] * n_years)
    row_op_nwc = _write_statement_row(
        "Net Operating Working Capital (Operating NWC)",
        raw_op_nwc,
        cfmt_large,
        is_bold=True,
        formula_subtraction=(row_non_cash_ca, row_non_debt_cl),
    )

    raw_dnwc_hist = bs_stmt.get("Change in Operating Working Capital (ΔNWC)") or historicals.get("delta_nwc", [0.0] * n_years)
    row_dnwc_hist = _write_statement_row("Change in Operating Working Capital (ΔNWC)", raw_dnwc_hist, cfmt_large)
    for idx in range(1, n_years):
        col = 3 + idx
        cur_col = get_column_letter(col)
        prev_col = get_column_letter(col - 1)
        ws.cell(row=row_dnwc_hist, column=col, value=f"={cur_col}{row_op_nwc}-{prev_col}{row_op_nwc}")

    norm_nwc_val = float(
        dcf_data.get("normalized_nwc_to_revenue", historicals.get("normalized_nwc_to_revenue", historicals.get("avg_dnwc_pct", 0.01)))
        or 0.0
    )
    row_norm_nwc_pct = _write_statement_row(
        "Operating NWC % of Revenue (Normalized DCF Driver in Avg Col)",
        [],
        PCT_FMT,
        is_margin_of=(row_op_nwc, row_rev),
    )
    ws.cell(row=row_norm_nwc_pct, column=3 + n_years, value=norm_nwc_val)

    eff_tax_fcff = float(data.get("macro", {}).get("tax_rate", 0.2517 if company.get("market") == "IN" else 0.21))
    row_fcff_tax = _write_statement_row("Marginal Operating Tax Rate for NOPAT (%)", [eff_tax_fcff] * n_years, PCT_FMT)

    row_hist_nopat = _write_statement_row(
        "Net Operating Profit After Tax (NOPAT = EBIT × (1 − Tax))",
        [],
        cfmt_large,
        is_bold=True,
        custom_formula=f"={'{col}'}{row_ebit}*(1-{'{col}'}{row_fcff_tax})",
    )

    raw_ufcf = cf_stmt.get("Unlevered Free Cash Flow (FCFF)", [])
    row_ufcf = _write_statement_row(
        "Unlevered Free Cash Flow to Firm (FCFF = NOPAT + D&A − CapEx − ΔNWC)",
        raw_ufcf,
        cfmt_large,
        is_bold=True,
        custom_formula=f"={'{col}'}{row_hist_nopat}+{'{col}'}{row_dna}-{'{col}'}{row_capex}-{'{col}'}{row_dnwc_hist}",
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # PART IV: EQUITY PROFITABILITY, ROE & DIVIDEND PAYOUT RATIOS
    # ═══════════════════════════════════════════════════════════════════════════
    r += 1
    _write_sub_banner("Part IV: Equity Profitability, ROE & Dividend Payout Ratios")

    row_bvps = _write_statement_row("Book Value per Share (BVPS)", [], cfmt_price, is_bold=True,
                                    is_margin_of=(row_equity, row_pe_shares))
    row_roe = _write_statement_row("Return on Equity (ROE % = Net Profit / Average Stockholders' Equity)", [], PCT_FMT, is_bold=True,
                                   is_margin_of=(row_ni, row_equity))
    for idx in range(1, n_years):
        col = 3 + idx
        cur_col = get_column_letter(col)
        prev_col = get_column_letter(col - 1)
        ws.cell(
            row=row_roe,
            column=col,
            value=f"=IF(AVERAGE({prev_col}{row_equity},{cur_col}{row_equity})<>0, {cur_col}{row_ni}/AVERAGE({prev_col}{row_equity},{cur_col}{row_equity}), 0)",
        )
    row_ret_rate = _write_statement_row("Equity Retention Rate (b = 1 − Dividend Payout %)", [], PCT_FMT,
                                        custom_formula=f"=1-{'{col}'}{row_payout}")
    row_sust_growth = _write_statement_row("Sustainable Internal Growth Rate (g = ROE × Retention Rate)", [], PCT_FMT, is_bold=True,
                                           custom_formula=f"={'{col}'}{row_roe}*{'{col}'}{row_ret_rate}")

    # ═══════════════════════════════════════════════════════════════════════════
    # NATIVE EXCEL CHARTS ON HISTORICALS (OpenPyXL)
    # ═══════════════════════════════════════════════════════════════════════════
    chart_col_letter = get_column_letter(end_col + 2)
    cats_ref = Reference(ws, min_col=3, min_row=header_row, max_col=2 + n_years, max_row=header_row)

    # Chart 1: Revenue & EBITDA Growth Trend
    try:
        chart1 = BarChart()
        chart1.type = "col"
        chart1.style = 10
        chart1.title = f"Historical Revenue & EBITDA Performance ({currency})"
        chart1.y_axis.title = f"Amount ({currency})"
        chart1.x_axis.title = "Fiscal Year"
        chart1.width = 17
        chart1.height = 12

        data_rev = Reference(ws, min_col=3, min_row=row_rev, max_col=2 + n_years, max_row=row_rev)
        data_ebitda = Reference(ws, min_col=3, min_row=row_ebitda, max_col=2 + n_years, max_row=row_ebitda)

        s_rev = Series(data_rev, title="Revenues")
        s_ebitda = Series(data_ebitda, title="EBITDA")
        chart1.series.append(s_rev)
        chart1.series.append(s_ebitda)
        chart1.set_categories(cats_ref)

        ws.add_chart(chart1, f"{chart_col_letter}4")
    except Exception as e:
        logger.warning("Could not add Chart 1 to Historical Financials: %s", e)

    # Chart 2: Cash Flow vs CapEx Performance
    try:
        chart2 = BarChart()
        chart2.type = "col"
        chart2.style = 11
        chart2.title = f"Operating Cash Flow, CapEx & Free Cash Flow ({currency})"
        chart2.y_axis.title = f"Amount ({currency})"
        chart2.x_axis.title = "Fiscal Year"
        chart2.width = 17
        chart2.height = 12

        data_cfo_ref = Reference(ws, min_col=3, min_row=row_cfo, max_col=2 + n_years, max_row=row_cfo)
        data_capex_ref = Reference(ws, min_col=3, min_row=row_capex, max_col=2 + n_years, max_row=row_capex)
        data_fcf_ref = Reference(ws, min_col=3, min_row=row_fcf, max_col=2 + n_years, max_row=row_fcf)

        s_cfo_chart = Series(data_cfo_ref, title="Operating CF")
        s_capex_chart = Series(data_capex_ref, title="CapEx")
        s_fcf_chart = Series(data_fcf_ref, title="Free Cash Flow")
        chart2.series.append(s_cfo_chart)
        chart2.series.append(s_capex_chart)
        chart2.series.append(s_fcf_chart)
        chart2.set_categories(cats_ref)

        ws.add_chart(chart2, f"{chart_col_letter}24")
    except Exception as e:
        logger.warning("Could not add Chart 2 to Historical Financials: %s", e)

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=18, max_width=42)
    ws.freeze_panes = "C6"
    return {
        "rev_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_rev}",
        "ebit_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_ebit}",
        "ebit_margin_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_ebit_margin}",
        "avg_ebit_margin_cell": f"'Historical Financials'!{avg_col_letter}{row_ebit_margin}",
        "dna_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_dna}",
        "avg_dna_pct_cell": f"'Historical Financials'!${avg_col_letter}${row_dna_pct}",
        "capex_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_capex}",
        "dnwc_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_dnwc_hist}",
        "norm_nwc_cell": f"'Historical Financials'!${avg_col_letter}${row_norm_nwc_pct}",
        "debt_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_tot_debt}",
        "minority_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_min_int_bs}",
        "cash_cell": cash_cell_coord,
        "net_income_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_ni}",
        "book_value_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_equity}",
        "shares_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_shares}",
        "bvps_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_bvps}",
        "roe_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_roe}",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Sheet 3: WACC 2 (CAPM, Cost of Debt & Capital Weights)
# ═══════════════════════════════════════════════════════════════════════════

def _build_wacc2(wb: Workbook, data: Dict[str, Any], hist_links: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    ws = wb.create_sheet("WACC 2")
    ws.sheet_properties.tabColor = TAB_WACC
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    currency = company.get("currency", "USD")
    macro = data.get("macro", {})
    market_data = data.get("market_data", {})
    wacc_data = data.get("wacc", {})
    overrides = data.get("overrides_applied", {})

    rf = macro.get("risk_free_rate", 0.071 if company.get("market") == "IN" else 0.042)
    market_return = macro.get("market_return", 0.13 if company.get("market") == "IN" else 0.10)
    tax_rate = macro.get("tax_rate", 0.2517 if company.get("market") == "IN" else 0.21)
    beta = market_data.get("beta", 1.0)
    market_cap = market_data.get("market_cap", 0.0)
    total_debt = wacc_data.get("total_debt", 0.0)
    dcf = data.get("dcf_result", {})
    eff_term_g = dcf.get("effective_terminal_growth")
    terminal_growth = eff_term_g if eff_term_g is not None else (overrides.get("terminal_growth") if overrides.get("terminal_growth") is not None else macro.get("terminal_growth", 0.050 if company.get("market") == "IN" else 0.025))

    cfmt_large = _get_currency_fmt_large(currency)

    # Top Section: Economic Data
    _set_banner(ws, 2, 2, 5, "Economic Data & Macro Assumptions")
    ws.cell(row=3, column=2, value="Currency Valuation").font = FONT_LABEL
    ws.cell(row=3, column=4, value=currency).font = FONT_DATA_BOLD
    for c in range(2, 6):
        ws.cell(row=3, column=c).border = THIN_BORDER

    ws.cell(row=4, column=2, value="Risk Free Rate (Rf)").font = FONT_LABEL
    rf_cell = ws.cell(row=4, column=5, value=rf)
    rf_cell.font = FONT_DATA_BOLD
    rf_cell.number_format = PCT_FMT
    rf_cell.alignment = ALIGN_RIGHT
    for c in range(2, 6):
        ws.cell(row=4, column=c).border = THIN_BORDER

    ws.cell(row=5, column=2, value="Long-Term GDP / Terminal Growth Rate (g)").font = FONT_LABEL
    tg_cell = ws.cell(row=5, column=5, value=terminal_growth)
    tg_cell.font = FONT_DATA_BOLD
    tg_cell.number_format = PCT_FMT
    tg_cell.alignment = ALIGN_RIGHT
    for c in range(2, 6):
        ws.cell(row=5, column=c).border = THIN_BORDER

    # Section 2: Cost of Equity (CAPM)
    _set_banner(ws, 7, 2, 5, "Cost of Equity (CAPM Model)")
    ke_formula = "=MAX(E8+0.015, E8+E9*E11)" if wacc_data.get("ke_floored") else "=E8+E9*E11"
    capm_rows = [
        (8, "Risk Free Rate", "=E4", PCT_FMT, False),
        (9, "Beta (Levered)", beta, NUM_2DEC_FMT, False),
        (10, "Expected Market Return (Rm)", market_return, PCT_FMT, False),
        (11, "Equity Risk Premium (Rm − Rf)", "=E10-E8", PCT_FMT, False),
        (12, "Cost of Equity (Ke)", ke_formula, PCT_FMT, True),
    ]
    for row_num, label, val, fmt, is_bold in capm_rows:
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if row_num % 2 == 0 else None)
        lbl = ws.cell(row=row_num, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER

        val_cell = ws.cell(row=row_num, column=5, value=val)
        val_cell.font = FONT_TOTAL if is_bold else FONT_DATA_BOLD
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT
        val_cell.number_format = fmt

        for c in (3, 4):
            ec = ws.cell(row=row_num, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = TOTAL_BORDER if is_bold else THIN_BORDER

    # Section 3: Cost of Debt
    _set_banner(ws, 14, 2, 5, "Cost of Debt (Capital Structure Debt)")
    # wacc_data["pretax_cost_of_debt"] is the true pre-tax cost of debt; cost_of_debt is after-tax
    pre_tax_kd = wacc_data.get("pretax_cost_of_debt")
    after_tax_kd = wacc_data.get("cost_of_debt")
    if pre_tax_kd is None or pre_tax_kd <= 0:
        after_tax_kd = after_tax_kd or 0.04
        pre_tax_kd = after_tax_kd / (1.0 - tax_rate) if tax_rate < 1.0 else after_tax_kd

    # Align debt tax shield with engine
    debt_tax_rate = max(0.0, min(0.99, 1.0 - (after_tax_kd / pre_tax_kd))) if (pre_tax_kd and after_tax_kd and pre_tax_kd > 0) else tax_rate

    bs_debt_list = data.get("historicals", {}).get("statements", {}).get("balance_sheet", {}).get("Total Debt", [])
    bs_fin_debt_latest = float(bs_debt_list[-1]) if bs_debt_list else float(total_debt)
    if hist_links and hist_links.get("debt_cell"):
        debt_diff = float(total_debt) - bs_fin_debt_latest
        if abs(debt_diff) < 1.0:
            debt_val_or_formula = f"={hist_links['debt_cell']}"
        else:
            sign_str = "+" if debt_diff >= 0 else ""
            debt_val_or_formula = f"={hist_links['debt_cell']}{sign_str}{round(debt_diff, 2)}"
    else:
        debt_val_or_formula = total_debt

    debt_rows = [
        (15, "Total Debt (D)", debt_val_or_formula, cfmt_large, False),
        (16, "Pre-Tax Cost of Debt", pre_tax_kd, PCT_FMT, False),
        (17, "Marginal Tax Rate (T)", debt_tax_rate, PCT_FMT, False),
        (18, "After-Tax Cost of Debt (Kd)", "=E16*(1-E17)", PCT_FMT, True),
    ]
    for row_num, label, val, fmt, is_bold in debt_rows:
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if row_num % 2 == 0 else None)
        lbl = ws.cell(row=row_num, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER

        val_cell = ws.cell(row=row_num, column=5, value=val)
        val_cell.font = FONT_TOTAL if is_bold else FONT_DATA_BOLD
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT
        val_cell.number_format = fmt

        for c in (3, 4):
            ec = ws.cell(row=row_num, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = TOTAL_BORDER if is_bold else THIN_BORDER

    # Section 4: Capital Weights & WACC
    _set_banner(ws, 20, 2, 5, "Capital Structure Weights & Weighted Average Cost of Capital (WACC)")
    if overrides.get("wacc") is not None:
        wacc_formula_or_val = float(overrides["wacc"])
        wacc_row_lbl = "Cost of Capital (WACC — User Override)"
    else:
        wacc_formula_or_val = "=MAX(E4+0.015, (E12*E25)+(E18*E24))"
        wacc_row_lbl = "Cost of Capital (WACC)"

    wacc_rows = [
        (21, "Market Capitalization (E)", market_cap, cfmt_large, False),
        (22, "Total Debt (D)", "=E15", cfmt_large, False),
        (23, "Total Capital (V = E + D)", "=E21+E22", cfmt_large, False),
        (24, "Weight of Debt (Wd = D / V)", "=IF(E23>0, E22/E23, 0)", PCT_FMT, False),
        (25, "Weight of Equity (We = 1 − Wd)", "=1-E24", PCT_FMT, False),
        (26, wacc_row_lbl, wacc_formula_or_val, PCT_FMT, True),
    ]
    for row_num, label, val, fmt, is_bold in wacc_rows:
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if row_num % 2 == 0 else None)
        lbl = ws.cell(row=row_num, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER

        val_cell = ws.cell(row=row_num, column=5, value=val)
        val_cell.font = FONT_TOTAL if is_bold else FONT_DATA_BOLD
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT
        val_cell.number_format = fmt

        for c in (3, 4):
            ec = ws.cell(row=row_num, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = TOTAL_BORDER if is_bold else THIN_BORDER

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=18, max_width=40)
    ws.freeze_panes = "B6"

    # Return key coordinates for DCF links
    return {
        "rf_cell": "'WACC 2'!$E$4",
        "beta_cell": "'WACC 2'!$E$9",
        "wacc_cell": "'WACC 2'!$E$26",
        "terminal_g_cell": "'WACC 2'!$E$5",
        "ke_cell": "'WACC 2'!$E$12",
        "kd_cell": "'WACC 2'!$E$18",
        "debt_cell": "'WACC 2'!$E$15",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Sheet 4: DCF Model (Multi-Stage DCF, Terminal Value & Equity Bridge)
# ═══════════════════════════════════════════════════════════════════════════

def _build_dcf_model(wb: Workbook, data: Dict[str, Any], wacc_links: Dict[str, str], cash_cell_ref: Any):
    ws = wb.create_sheet("DCF Model")
    ws.sheet_properties.tabColor = TAB_DCF
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    macro = data.get("macro", {})
    wacc_data = data.get("wacc", {})
    dcf = data.get("dcf_result", {})
    historicals = data.get("historicals", {})
    verdict = data.get("verdict", {})
    hist_refs = cash_cell_ref if isinstance(cash_cell_ref, dict) else {}

    cfmt_price = _get_currency_fmt_price(currency)
    cfmt_large = _get_currency_fmt_large(currency)

    growth_schedule = dcf.get("growth_schedule", [0.05] * 5)
    margin_schedule = dcf.get("margin_schedule", [historicals.get("avg_ebit_margin", 0.15)] * 5)
    proj_rev = dcf.get("projected_revenue", [])
    proj_nopat = dcf.get("projected_nopat", [])
    proj_dna = dcf.get("projected_dna", [])
    proj_capex = dcf.get("projected_capex", [])
    n_proj = len(growth_schedule)

    # Tax rate from macro profile (25.17% for IN, 21.00% for US)
    tax_rate_dcf = macro.get("tax_rate", 0.2517 if company.get("market") == "IN" else 0.21)

    avg_dna_pct = historicals.get("avg_dna_pct", 0.02)
    avg_capex_pct = historicals.get("avg_capex_pct", 0.03)
    norm_nwc_pct = dcf.get("normalized_nwc_to_revenue", historicals.get("normalized_nwc_to_revenue", historicals.get("avg_dnwc_pct", 0.01)))
    last_revenue = historicals.get("last_revenue") or (historicals.get("revenue", [-1])[-1] if historicals.get("revenue") else (proj_rev[0] / (1 + growth_schedule[0]) if proj_rev else 1e9))

    hist_years = historicals.get("years", [])
    base_year_lbl = f"FY {hist_years[-1]}" if hist_years else "Base FY"

    # Banner Header
    r = 2
    end_col = 3 + n_proj  # Col B (Item), Col C (Base), Cols D.. (Forecast Years)
    _set_banner(ws, r, 2, end_col, "Multi-Stage Discounted Cash Flow (DCF) Valuation Model — Free Cash Flow to Firm (FCFF)")
    r += 1

    # Table Headers
    headers = ["Forecast Metric / Valuation Driver", base_year_lbl] + [f"Year {i+1}" for i in range(n_proj)]
    _set_table_headers(ws, r, headers, start_col=2)
    header_row = r
    r += 1

    # 1. Revenue Growth Rate
    lbl1 = ws.cell(row=r, column=2, value="YoY Revenue Growth Rate")
    lbl1.font = FONT_LABEL_BOLD
    lbl1.fill = ALT_ROW_FILL
    lbl1.border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL

    for i in range(n_proj):
        c = ws.cell(row=r, column=4 + i, value=growth_schedule[i])
        c.font = FONT_DATA_BOLD
        c.number_format = PCT_FMT
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
        c.fill = ALT_ROW_FILL
    growth_row = r
    r += 1

    # 2. Revenue Projections (Live Formula: =Prev_Rev * (1 + g); Base Year linked to Historical Financials)
    lbl2 = ws.cell(row=r, column=2, value="Revenue / Turnover")
    lbl2.font = FONT_LABEL_BOLD
    lbl2.border = THIN_BORDER
    hist_rev_list = historicals.get("revenue", [])
    if hist_refs.get("rev_cell") and hist_rev_list and float(hist_rev_list[-1]) > 0:
        if abs(float(last_revenue) - float(hist_rev_list[-1])) < 1.0:
            base_rev_val = f"={hist_refs['rev_cell']}"
        else:
            base_rev_val = f"={hist_refs['rev_cell']}*{float(last_revenue) / float(hist_rev_list[-1]):.8f}"
    else:
        base_rev_val = last_revenue
    base_rev_cell = ws.cell(row=r, column=3, value=base_rev_val)
    base_rev_cell.font = FONT_DATA_BOLD
    base_rev_cell.number_format = cfmt_large
    base_rev_cell.alignment = ALIGN_RIGHT
    base_rev_cell.border = THIN_BORDER

    for i in range(n_proj):
        col = 4 + i
        prev_letter = get_column_letter(col - 1)
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={prev_letter}{r}*(1+{cur_letter}{growth_row})")
        c.font = FONT_DATA_BOLD
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    rev_row = r
    r += 1

    # 3. Operating Margin Schedule (Base Year linked to actual Base Year EBIT / Revenue)
    lbl3 = ws.cell(row=r, column=2, value="Operating Margin (EBIT Margin)")
    lbl3.font = FONT_LABEL
    lbl3.fill = ALT_ROW_FILL
    lbl3.border = THIN_BORDER
    margin_row = r
    ebit_row = r + 1
    ws.cell(row=r, column=3, value=f"=IF(C{rev_row}<>0, C{ebit_row}/C{rev_row}, 0)").number_format = PCT_FMT
    ws.cell(row=r, column=3).font = FONT_DATA
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        c = ws.cell(row=r, column=4 + i, value=margin_schedule[i])
        c.font = FONT_DATA
        c.number_format = PCT_FMT
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
        c.fill = ALT_ROW_FILL
    r += 1

    # 4. EBIT (Base Year linked to Historical Financials; Forecast = Revenue * Margin)
    lbl4 = ws.cell(row=r, column=2, value="EBIT (Operating Income)")
    lbl4.font = FONT_LABEL_BOLD
    lbl4.border = THIN_BORDER
    hist_ebit_list = historicals.get("ebit", [])
    base_ebit_val = (
        f"={hist_refs['ebit_cell']}"
        if hist_refs.get("ebit_cell")
        else (float(hist_ebit_list[-1]) if hist_ebit_list else f"=C{rev_row}*C{margin_row}")
    )
    ws.cell(row=r, column=3, value=base_ebit_val).number_format = cfmt_large
    ws.cell(row=r, column=3).font = FONT_DATA_BOLD
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{rev_row}*{cur_letter}{margin_row}")
        c.font = FONT_DATA_BOLD
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    ebit_row = r
    r += 1

    # 5. Effective Tax Rate
    lbl5 = ws.cell(row=r, column=2, value="Marginal Tax Rate")
    lbl5.font = FONT_LABEL
    lbl5.fill = ALT_ROW_FILL
    lbl5.border = THIN_BORDER
    for i in range(n_proj + 1):
        col = 3 + i
        c = ws.cell(row=r, column=col, value=tax_rate_dcf)
        c.font = FONT_DATA
        c.number_format = PCT_FMT
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
        c.fill = ALT_ROW_FILL
    tax_row = r
    r += 1

    # 6. NOPAT (Live Formula: =EBIT * (1 - Tax))
    lbl6 = ws.cell(row=r, column=2, value="NOPAT (EBIT × (1 − Tax))")
    lbl6.font = FONT_LABEL_BOLD
    lbl6.border = THIN_BORDER
    ws.cell(row=r, column=3, value=f"=C{ebit_row}*(1-C{tax_row})").number_format = cfmt_large
    ws.cell(row=r, column=3).font = FONT_DATA_BOLD
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{ebit_row}*(1-{cur_letter}{tax_row})")
        c.font = FONT_DATA_BOLD
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    nopat_row = r
    r += 1

    # 7. Add: D&A (Base Year linked to Historical Financials; Forecast = Revenue * effective_dna_pct)
    lbl7 = ws.cell(row=r, column=2, value="(+) Depreciation & Amortization")
    lbl7.font = FONT_LABEL
    lbl7.fill = ALT_ROW_FILL
    lbl7.border = THIN_BORDER
    hist_dna_list = historicals.get("dna", [])
    base_dna_val = (
        f"={hist_refs['dna_cell']}"
        if hist_refs.get("dna_cell")
        else (float(hist_dna_list[-1]) if hist_dna_list else f"=C{rev_row}*{avg_dna_pct}")
    )
    ws.cell(row=r, column=3, value=base_dna_val).number_format = cfmt_large
    ws.cell(row=r, column=3).font = FONT_DATA
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        pct_dna = (proj_dna[i] / proj_rev[i]) if (proj_rev and i < len(proj_dna) and proj_rev[i] > 0) else avg_dna_pct
        if hist_refs.get("avg_dna_pct_cell") and abs(float(pct_dna) - float(avg_dna_pct)) < 1e-7:
            dna_formula_i = f"={cur_letter}{rev_row}*{hist_refs['avg_dna_pct_cell']}"
        else:
            dna_formula_i = f"={cur_letter}{rev_row}*{pct_dna}"
        c = ws.cell(row=r, column=col, value=dna_formula_i)
        c.font = FONT_DATA
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
        c.fill = ALT_ROW_FILL
    dna_row = r
    r += 1

    # 8. Less: CapEx (Base Year linked to Historical Financials; Forecast = Revenue * capex_schedule)
    lbl8 = ws.cell(row=r, column=2, value="(−) Capital Expenditures (CapEx)")
    lbl8.font = FONT_LABEL
    lbl8.border = THIN_BORDER
    hist_capex_list = historicals.get("capex", [])
    base_capex_val = (
        f"={hist_refs['capex_cell']}"
        if hist_refs.get("capex_cell")
        else (float(hist_capex_list[-1]) if hist_capex_list else f"=C{rev_row}*{avg_capex_pct}")
    )
    ws.cell(row=r, column=3, value=base_capex_val).number_format = cfmt_large
    ws.cell(row=r, column=3).font = FONT_DATA
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        pct_capex = (proj_capex[i] / proj_rev[i]) if (proj_rev and i < len(proj_capex) and proj_rev[i] > 0) else avg_capex_pct
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{rev_row}*{pct_capex}")
        c.font = FONT_DATA
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    capex_row = r
    r += 1

    # 9. Less: Change in NWC (Base Year linked to Historical Financials; Forecast = NormNWC * (Rev_t - Rev_{t-1}))
    lbl9 = ws.cell(row=r, column=2, value="(−) Change in Net Working Capital (ΔNWC)")
    lbl9.font = FONT_LABEL
    lbl9.fill = ALT_ROW_FILL
    lbl9.border = THIN_BORDER
    hist_dnwc_list = historicals.get("delta_nwc", [])
    base_dnwc_val = (
        f"={hist_refs['dnwc_cell']}"
        if hist_refs.get("dnwc_cell")
        else (float(hist_dnwc_list[-1]) if hist_dnwc_list else 0.0)
    )
    ws.cell(row=r, column=3, value=base_dnwc_val).number_format = cfmt_large
    ws.cell(row=r, column=3).font = FONT_DATA
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    nwc_driver_ref = hist_refs.get("norm_nwc_cell") or str(norm_nwc_pct)
    for i in range(n_proj):
        col = 4 + i
        prev_letter = get_column_letter(col - 1)
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={nwc_driver_ref}*({cur_letter}{rev_row}-{prev_letter}{rev_row})")
        c.font = FONT_DATA
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
        c.fill = ALT_ROW_FILL
    dnwc_row = r
    r += 1

    # 10. Free Cash Flow to Firm (FCFF = NOPAT + D&A - CapEx - ΔNWC)
    lbl10 = ws.cell(row=r, column=2, value="Free Cash Flow to Firm (FCFF / UFCF)")
    lbl10.font = FONT_LABEL_BOLD
    lbl10.fill = HIGHLIGHT_FILL
    lbl10.border = TOTAL_BORDER
    ws.cell(row=r, column=3, value=f"=C{nopat_row}+C{dna_row}-C{capex_row}-C{dnwc_row}").number_format = cfmt_large
    ws.cell(row=r, column=3).font = FONT_DATA_BOLD
    ws.cell(row=r, column=3).border = TOTAL_BORDER
    ws.cell(row=r, column=3).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{nopat_row}+{cur_letter}{dna_row}-{cur_letter}{capex_row}-{cur_letter}{dnwc_row}")
        c.font = FONT_TOTAL
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = TOTAL_BORDER
        c.fill = HIGHLIGHT_FILL
    fcff_row = r
    r += 1

    # 11. Mid-Year Convention (t = 0.5, 1.5, 2.5, 3.5, 4.5)
    lbl11 = ws.cell(row=r, column=2, value="Mid-Year Convention (Years t)")
    lbl11.font = FONT_LABEL
    lbl11.border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).border = THIN_BORDER

    for i in range(n_proj):
        col = 4 + i
        if i == 0:
            c = ws.cell(row=r, column=col, value=0.5)
        else:
            prev_letter = get_column_letter(col - 1)
            c = ws.cell(row=r, column=col, value=f"={prev_letter}{r}+1")
        c.font = FONT_DATA
        c.number_format = "0.0"
        c.alignment = ALIGN_CENTER
        c.border = THIN_BORDER
    period_row = r
    r += 1

    # 12. Discounting Factor (= 1 / (1 + WACC)^t)
    wacc_ref = wacc_links["wacc_cell"]
    lbl12 = ws.cell(row=r, column=2, value=f"Discounting Factor (at WACC = {wacc_ref})")
    lbl12.font = FONT_LABEL
    lbl12.fill = ALT_ROW_FILL
    lbl12.border = THIN_BORDER
    ws.cell(row=r, column=3, value=1.0).alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"=1/(1+{wacc_ref})^{cur_letter}{period_row}")
        c.font = FONT_DATA
        c.number_format = "0.0000"
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
        c.fill = ALT_ROW_FILL
    df_row = r
    r += 1

    # 13. Present Value of FCFF (= FCFF * Discount Factor)
    lbl13 = ws.cell(row=r, column=2, value="Present Value of FCFF")
    lbl13.font = FONT_LABEL_BOLD
    lbl13.border = TOTAL_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).border = TOTAL_BORDER

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{fcff_row}*{cur_letter}{df_row}")
        c.font = FONT_DATA_BOLD
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = TOTAL_BORDER
    pv_fcff_row = r
    r += 2

    # ═══════════════════════════════════════════════════════════════════════════
    # Terminal Value & Enterprise Value to Equity Bridge
    # ═══════════════════════════════════════════════════════════════════════════

    # Section: Terminal Value Calculation
    _set_banner(ws, r, 2, 5, "Calculation of Terminal Value (Gordon Growth Model — Sustainable Reinvestment)")
    r += 1

    last_col_letter = get_column_letter(3 + n_proj)
    term_g_ref = wacc_links["terminal_g_cell"]
    wacc_ref = wacc_links["wacc_cell"]

    # 1. Terminal Growth Rate (g)
    tg_row = r
    wacc_param_row = r + 1
    ws.cell(row=r, column=2, value="Long-Term Terminal Growth Rate (g)").font = FONT_LABEL
    tg_cell = ws.cell(row=r, column=4, value=f"=MIN({term_g_ref}, D{wacc_param_row}-0.025)")
    tg_cell.font = FONT_DATA_BOLD
    tg_cell.number_format = PCT_FMT
    tg_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    r += 1

    # 2. Cost of Capital (WACC)
    ws.cell(row=r, column=2, value="Cost of Capital (WACC)").font = FONT_LABEL
    wacc_cell = ws.cell(row=r, column=4, value=f"={wacc_ref}")
    wacc_cell.font = FONT_DATA_BOLD
    wacc_cell.number_format = PCT_FMT
    wacc_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    wacc_param_row = r
    r += 1

    # 3. Terminal Year NOPAT (Year N+1 = Year N NOPAT * (1 + g))
    ws.cell(row=r, column=2, value="Terminal Year NOPAT (Year N+1 = Year N NOPAT × (1 + g))").font = FONT_LABEL
    term_nopat_cell = ws.cell(row=r, column=4, value=f"={last_col_letter}{nopat_row}*(1+D{tg_row})")
    term_nopat_cell.font = FONT_DATA_BOLD
    term_nopat_cell.number_format = cfmt_large
    term_nopat_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    term_nopat_row = r
    r += 1

    # 4. Steady-State Return on New Invested Capital (RONIC)
    eff_term_g = float(dcf.get("effective_terminal_growth", 0.025) or 0.025)
    sust_roic = float(dcf.get("sustainable_roic", 0.15) or 0.15)
    term_reinv = float(dcf.get("terminal_reinv_rate", eff_term_g / sust_roic if sust_roic > 0 else 0.20) or 0.20)

    ws.cell(row=r, column=2, value="Steady-State Return on New Invested Capital (RONIC)").font = FONT_LABEL
    roic_cell = ws.cell(row=r, column=4, value=sust_roic)
    roic_cell.font = FONT_DATA
    roic_cell.number_format = PCT_FMT
    roic_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    roic_row = r
    r += 1

    # 5. Terminal Reinvestment Rate (b = g / RONIC)
    roic_reinv_raw = eff_term_g / sust_roic if sust_roic > 0 else term_reinv
    if abs(term_reinv - min(0.80, max(0.10, roic_reinv_raw))) < 1e-7:
        reinv_formula = f"=MIN(0.80, MAX(0.10, D{tg_row}/D{roic_row}))"
    elif abs(term_reinv - min(0.80, max(0.06, roic_reinv_raw))) < 1e-7:
        reinv_formula = f"=MIN(0.80, MAX(0.06, D{tg_row}/D{roic_row}))"
    else:
        reinv_scale = (term_reinv / roic_reinv_raw) if roic_reinv_raw > 0 else 1.0
        reinv_formula = f"=MIN(0.80, MAX(0.06, (D{tg_row}/D{roic_row})*{reinv_scale:.10f}))"

    ws.cell(row=r, column=2, value="Terminal Reinvestment Rate (b = g / RONIC)").font = FONT_LABEL
    reinv_cell = ws.cell(row=r, column=4, value=reinv_formula)
    reinv_cell.font = FONT_DATA_BOLD
    reinv_cell.number_format = PCT_FMT
    reinv_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    reinv_row = r
    r += 1

    # 6. Normalized Terminal Year UFCF (Year N+1 = Terminal NOPAT * (1 - b))
    ws.cell(row=r, column=2, value="Normalized Terminal Free Cash Flow (UFCF n+1)").font = FONT_LABEL
    n1_cell = ws.cell(row=r, column=4, value=f"=D{term_nopat_row}*(1-D{reinv_row})")
    n1_cell.font = FONT_DATA_BOLD
    n1_cell.number_format = cfmt_large
    n1_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    n1_row = r
    r += 1

    # 7. Terminal Value at Year N (= UFCF_{n+1} / (WACC - g))
    wacc_rate = float(wacc_data.get("wacc", 0.10) or 0.10)
    terminal_val = float(dcf.get("terminal_value") or 0.0)
    spread = wacc_rate - eff_term_g
    pure_gordon_tv = (
        float(dcf.get("terminal_ufcf", proj_nopat[-1] * (1.0 + eff_term_g) * (1.0 - term_reinv))) / spread
        if (spread > 0 and proj_nopat)
        else terminal_val
    )
    if pure_gordon_tv > 0 and abs(terminal_val - pure_gordon_tv) > 1.0:
        tv_scale = terminal_val / pure_gordon_tv
        tv_formula = f"=IF(D{wacc_param_row}>D{tg_row}, (D{n1_row}/(D{wacc_param_row}-D{tg_row}))*{tv_scale:.10f}, 0)"
    else:
        tv_formula = f"=IF(D{wacc_param_row}>D{tg_row}, D{n1_row}/(D{wacc_param_row}-D{tg_row}), 0)"

    ws.cell(row=r, column=2, value="Terminal Value at Year N").font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    tv_cell = ws.cell(row=r, column=4, value=tv_formula)
    tv_cell.font = FONT_TOTAL
    tv_cell.number_format = cfmt_large
    tv_cell.alignment = ALIGN_RIGHT
    tv_cell.fill = HIGHLIGHT_FILL
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = TOTAL_BORDER
    tv_row = r
    r += 2

    # Section: Enterprise Value to Equity Value Bridge
    _set_banner(ws, r, 2, 5, "Calculation of Enterprise Value & Equity Value per Share")
    r += 1

    first_pv_col = get_column_letter(4)
    bridge_start = r

    # 1. Sum of PV of FCFF
    ws.cell(row=r, column=2, value="Cumulative Present Value of Forecasted FCFFs").font = FONT_LABEL
    ws.cell(row=r, column=4, value=f"=SUM({first_pv_col}{pv_fcff_row}:{last_col_letter}{pv_fcff_row})").font = FONT_DATA_BOLD
    ws.cell(row=r, column=4).number_format = cfmt_large
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    sum_pv_row = r
    r += 1

    # 2. PV of Terminal Value
    ws.cell(row=r, column=2, value="Present Value of Terminal Value").font = FONT_LABEL
    ws.cell(row=r, column=4, value=f"=D{tv_row}*{last_col_letter}{df_row}").font = FONT_DATA_BOLD
    ws.cell(row=r, column=4).number_format = cfmt_large
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    pv_tv_row = r
    r += 1

    # 3. Enterprise Value
    ws.cell(row=r, column=2, value="Implied Enterprise Value (Operating Assets)").font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    ev_cell = ws.cell(row=r, column=4, value=f"=D{sum_pv_row}+D{pv_tv_row}")
    ev_cell.font = FONT_TOTAL
    ev_cell.number_format = cfmt_large
    ev_cell.alignment = ALIGN_RIGHT
    ev_cell.fill = HIGHLIGHT_FILL
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = TOTAL_BORDER
    ev_row = r
    r += 1

    # 4. Add: Cash
    if isinstance(cash_cell_ref, dict):
        cash_ref = cash_cell_ref.get("cash_cell") or str(historicals.get("cash_and_equivalents", 0))
    else:
        cash_ref = cash_cell_ref if cash_cell_ref else str(historicals.get("cash_and_equivalents", 0))
    ws.cell(row=r, column=2, value="(+) Cash & Cash Equivalents").font = FONT_LABEL
    ws.cell(row=r, column=4, value=f"={cash_ref}").font = FONT_DATA
    ws.cell(row=r, column=4).number_format = cfmt_large
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    cash_row = r
    r += 1

    # 5. Less: Debt
    debt_ref = wacc_links["debt_cell"]
    ws.cell(row=r, column=2, value="(−) Total Debt (Borrowings)").font = FONT_LABEL
    ws.cell(row=r, column=4, value=f"={debt_ref}").font = FONT_DATA
    ws.cell(row=r, column=4).number_format = cfmt_large
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    debt_row = r
    r += 1

    # 6. Less: Minority Interest & Preferred Claims
    min_int_val = float(dcf.get("minority_interest", wacc_data.get("minority_interest_claim", 0.0)) or 0.0)
    pref_val = float(dcf.get("preferred_stock", wacc_data.get("preferred_stock_claim", 0.0)) or 0.0)
    bs_min_list = historicals.get("statements", {}).get("balance_sheet", {}).get("Minority Interest", [])
    bs_min_latest = float(bs_min_list[-1]) if bs_min_list else min_int_val
    if hist_refs.get("minority_cell"):
        extra_claim = (min_int_val + pref_val) - bs_min_latest
        if abs(extra_claim) < 1.0:
            min_int_formula = f"={hist_refs['minority_cell']}"
        else:
            sign_s = "+" if extra_claim >= 0 else ""
            min_int_formula = f"={hist_refs['minority_cell']}{sign_s}{round(extra_claim, 2)}"
    else:
        min_int_formula = min_int_val + pref_val

    ws.cell(row=r, column=2, value="(−) Minority Interest & Preferred Claims").font = FONT_LABEL
    ws.cell(row=r, column=4, value=min_int_formula).font = FONT_DATA
    ws.cell(row=r, column=4).number_format = cfmt_large
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    min_int_row = r
    r += 1

    # 7. Implied Equity Value
    ws.cell(row=r, column=2, value="Implied Equity Value").font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    eq_cell = ws.cell(row=r, column=4, value=f"=D{ev_row}+D{cash_row}-D{debt_row}-D{min_int_row}")
    eq_cell.font = FONT_TOTAL
    eq_cell.number_format = cfmt_large
    eq_cell.alignment = ALIGN_RIGHT
    eq_cell.fill = HIGHLIGHT_FILL
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = TOTAL_BORDER
    eq_row = r
    r += 1

    # 8. Shares Outstanding
    shares_cnt = market_data.get("shares_outstanding", 1)
    ws.cell(row=r, column=2, value="(÷) Diluted Shares Outstanding").font = FONT_LABEL
    ws.cell(row=r, column=4, value=shares_cnt).font = FONT_DATA
    ws.cell(row=r, column=4).number_format = INT_FMT
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    shares_row = r
    r += 1

    # 9. Implied Share Price
    ws.cell(row=r, column=2, value="DCF Implied Value per Share").font = Font(name="Calibri", size=12, bold=True, color=NAVY_PRIMARY)
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    price_cell = ws.cell(row=r, column=4, value=f"=MAX(0, D{eq_row}/D{shares_row})")
    price_cell.font = Font(name="Calibri", size=12, bold=True, color=NAVY_PRIMARY)
    price_cell.number_format = cfmt_price
    price_cell.alignment = ALIGN_RIGHT
    price_cell.fill = HIGHLIGHT_FILL
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = TOTAL_BORDER
    price_row = r
    r += 1

    # 10. Current Market Price
    cmp_val = market_data.get("current_price", 0)
    ws.cell(row=r, column=2, value="Current Market Price (CMP)").font = FONT_LABEL
    ws.cell(row=r, column=4, value=cmp_val).font = FONT_DATA
    ws.cell(row=r, column=4).number_format = cfmt_price
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    cmp_row = r
    r += 1

    # 11. Upside / Downside %
    ws.cell(row=r, column=2, value="Implied Upside / (Downside)").font = FONT_LABEL_BOLD
    upside_cell = ws.cell(row=r, column=4, value=f"=IF(D{cmp_row}>0, (D{price_row}-D{cmp_row})/D{cmp_row}, 0)")
    upside_cell.font = FONT_DATA_BOLD
    upside_cell.number_format = PCT_FMT
    upside_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    upside_row = r
    r += 1

    # 11. Verdict
    ws.cell(row=r, column=2, value="Valuation Outlook").font = FONT_LABEL_BOLD
    v_cell = ws.cell(row=r, column=4, value=verdict.get("verdict", "NEUTRAL"))
    v_cell.font = FONT_LABEL_BOLD
    v_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = TOTAL_BORDER

    # ═══════════════════════════════════════════════════════════════════════════
    # NATIVE EXCEL CHARTS ON DCF MODEL (OpenPyXL)
    # ═══════════════════════════════════════════════════════════════════════════
    chart_col_letter = get_column_letter(end_col + 2)
    proj_cats_ref = Reference(ws, min_col=4, min_row=header_row, max_col=3 + n_proj, max_row=header_row)

    # Chart 3: Projected Free Cash Flow (FCFF) Trajectory
    try:
        chart_fcff = BarChart()
        chart_fcff.type = "col"
        chart_fcff.style = 10
        chart_fcff.title = f"Projected Free Cash Flow (FCFF) Trajectory ({currency})"
        chart_fcff.y_axis.title = f"FCFF ({currency})"
        chart_fcff.x_axis.title = "Forecast Period"
        chart_fcff.width = 18
        chart_fcff.height = 12

        data_fcff_ref = Reference(ws, min_col=4, min_row=fcff_row, max_col=3 + n_proj, max_row=fcff_row)
        s_fcff = Series(data_fcff_ref, title="FCFF / UFCF")
        chart_fcff.series.append(s_fcff)
        chart_fcff.set_categories(proj_cats_ref)

        ws.add_chart(chart_fcff, f"{chart_col_letter}4")
    except Exception as e:
        logger.warning("Could not add FCFF chart to DCF Model: %s", e)

    # Chart 4: Projected Revenue & Operating Profit (EBIT)
    try:
        chart_rev_ebit = BarChart()
        chart_rev_ebit.type = "col"
        chart_rev_ebit.style = 11
        chart_rev_ebit.title = f"Projected Revenue & Operating Profit ({currency})"
        chart_rev_ebit.y_axis.title = f"Amount ({currency})"
        chart_rev_ebit.x_axis.title = "Forecast Period"
        chart_rev_ebit.width = 18
        chart_rev_ebit.height = 12

        data_proj_rev = Reference(ws, min_col=4, min_row=rev_row, max_col=3 + n_proj, max_row=rev_row)
        data_proj_ebit = Reference(ws, min_col=4, min_row=ebit_row, max_col=3 + n_proj, max_row=ebit_row)

        s_prev = Series(data_proj_rev, title="Revenue")
        s_pebit = Series(data_proj_ebit, title="EBIT")
        chart_rev_ebit.series.append(s_prev)
        chart_rev_ebit.series.append(s_pebit)
        chart_rev_ebit.set_categories(proj_cats_ref)

        ws.add_chart(chart_rev_ebit, f"{chart_col_letter}24")
    except Exception as e:
        logger.warning("Could not add Revenue & EBIT chart to DCF Model: %s", e)

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=18, max_width=42)
    return {
        "price_cell": f"'DCF Model'!D{price_row}",
        "upside_cell": f"'DCF Model'!D{upside_row}",
        "tg_cell": f"'DCF Model'!D{tg_row}",
        "terminal_margin_cell": f"'DCF Model'!{last_col_letter}{margin_row}",
        "ev_cell": f"'DCF Model'!D{ev_row}",
        "eq_cell": f"'DCF Model'!D{eq_row}",
        "ev_row": ev_row,
        "cash_row": cash_row,
        "debt_row": debt_row,
        "min_int_row": min_int_row,
        "shares_row": shares_row,
        "price_row": price_row,
        "reinv_row": reinv_row,
        "nopat_row": nopat_row,
        "fcff_row": fcff_row,
        "period_row": period_row,
        "n_proj": n_proj,
        "tv_scale": (terminal_val / pure_gordon_tv) if (pure_gordon_tv > 0 and abs(terminal_val - pure_gordon_tv) > 1.0) else 1.0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Sheet 5: Sensitivity Analysis (2D Implied Price Grids)
# ═══════════════════════════════════════════════════════════════════════════

def _build_sensitivity(wb: Workbook, data: Dict[str, Any], dcf_links: Optional[Dict[str, Any]] = None):
    ws = wb.create_sheet("Sensitivity")
    ws.sheet_properties.tabColor = TAB_SENS
    ws.views.sheetView[0].showGridLines = True

    sens = data.get("sensitivity", {})
    tgw = sens.get("terminal_growth_wacc", {}) or {}
    gw = sens.get("growth_wacc", {}) or {}
    mw = sens.get("margin_wacc", {}) or {}
    company = data.get("company", {})
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    wacc_data = data.get("wacc", {})
    dcf_links = dcf_links or {}

    cfmt_price = _get_currency_fmt_price(currency)

    # Title Banner
    _set_banner(ws, 2, 2, 8, "Valuation Sensitivity Analysis (2D Scenario Price Matrix)")

    # Reference Values Block
    ws.cell(row=4, column=2, value="Current Share Price:").font = FONT_LABEL_BOLD
    cmp_cell = ws.cell(row=4, column=3, value=market_data.get("current_price", 0))
    cmp_cell.font = FONT_DATA_BOLD
    cmp_cell.number_format = cfmt_price

    ws.cell(row=4, column=5, value="Base DCF Fair Value:").font = FONT_LABEL_BOLD
    base_fv_ref = f"={dcf_links['price_cell']}" if dcf_links.get("price_cell") else dcf.get("implied_price", 0)
    dcf_cell = ws.cell(row=4, column=6, value=base_fv_ref)
    dcf_cell.font = FONT_DATA_BOLD
    dcf_cell.number_format = cfmt_price

    cash_val = float(dcf.get("cash", wacc_data.get("total_cash", 0.0)) or 0.0)
    debt_val = float(dcf.get("total_debt", wacc_data.get("total_debt", 0.0)) or 0.0)
    min_int_val = float(dcf.get("minority_interest", wacc_data.get("minority_interest_claim", 0.0)) or 0.0) + float(
        dcf.get("preferred_stock", wacc_data.get("preferred_stock_claim", 0.0)) or 0.0
    )
    shares_cnt = float(market_data.get("shares_outstanding", 1.0) or 1.0)
    base_ev = float(dcf.get("enterprise_value", 0.0) or 0.0)

    ev_row = dcf_links.get("ev_row", 30)
    cash_row = dcf_links.get("cash_row", 31)
    debt_row = dcf_links.get("debt_row", 32)
    min_int_row = dcf_links.get("min_int_row", 33)
    shares_row = dcf_links.get("shares_row", 35)
    price_row = dcf_links.get("price_row", 36)
    reinv_row = dcf_links.get("reinv_row", 23)
    nopat_row = dcf_links.get("nopat_row", 9)
    fcff_row = dcf_links.get("fcff_row", 13)
    period_row = dcf_links.get("period_row", 14)
    n_proj = int(dcf_links.get("n_proj", 5) or 5)
    tv_scale = float(dcf_links.get("tv_scale", 1.0) or 1.0)
    last_proj_col = get_column_letter(3 + n_proj)

    r = 6

    # Helper for 2D sensitivity table (WACC on Rows, Second Driver on Columns)
    def _render_sensitivity_table(
        start_row: int,
        title: str,
        row_label: str,
        row_vals: list,
        col_label: str,
        col_vals: list,
        price_grid: list,
        mode: str = "generic",
    ) -> int:
        cur_r = start_row
        num_cols = len(col_vals)
        _set_banner(ws, cur_r, 2, 2 + num_cols, title)
        cur_r += 1

        # Header Row
        ws.row_dimensions[cur_r].height = 22
        corner_cell = ws.cell(row=cur_r, column=2, value=f"{row_label} \\ {col_label}")
        corner_cell.font = FONT_HEADER
        corner_cell.fill = HEADER_FILL
        corner_cell.alignment = ALIGN_CENTER
        corner_cell.border = THIN_BORDER

        for j, c_val in enumerate(col_vals):
            col = 3 + j
            c = ws.cell(row=cur_r, column=col, value=float(c_val))
            c.font = FONT_HEADER
            c.fill = HEADER_FILL
            c.number_format = PCT_FMT
            c.alignment = ALIGN_CENTER
            c.border = THIN_BORDER

        table_header_r = cur_r
        cur_r += 1

        # Data Rows
        grid_start_letter = get_column_letter(3)
        grid_end_letter = get_column_letter(2 + num_cols)
        data_start_r = cur_r

        pv_fcff_terms = [
            f"('DCF Model'!${get_column_letter(4+k)}${fcff_row}/(1+$B{ '{r}' })^'DCF Model'!${get_column_letter(4+k)}${period_row})"
            for k in range(n_proj)
        ]
        pv_fcff_expr_tmpl = "(" + "+".join(pv_fcff_terms) + ")"

        for i, (r_val, row_prices) in enumerate(zip(row_vals, price_grid)):
            r_val_f = float(r_val)
            row_lbl = ws.cell(row=cur_r, column=2, value=r_val_f)
            row_lbl.font = FONT_HEADER
            row_lbl.fill = HEADER_FILL
            row_lbl.number_format = PCT_FMT
            row_lbl.alignment = ALIGN_CENTER
            row_lbl.border = THIN_BORDER

            for j, price in enumerate(row_prices):
                col = 3 + j
                col_letter = get_column_letter(col)
                c_val_f = float(col_vals[j])
                price_f = float(price)

                if dcf_links.get("price_cell"):
                    if mode == "terminal_growth":
                        pv_fcff_expr = pv_fcff_expr_tmpl.replace("{r}", str(cur_r))
                        eff_g_expr = f"MIN({col_letter}${table_header_r},$B{cur_r}-0.015)"
                        term_ufcf_expr = f"('DCF Model'!${last_proj_col}${nopat_row}*(1+{eff_g_expr})*(1-'DCF Model'!$D${reinv_row}))"
                        tv_expr = f"({term_ufcf_expr}/MAX(0.015,$B{cur_r}-{eff_g_expr}))"
                        if abs(tv_scale - 1.0) > 1e-6:
                            tv_expr = f"({tv_expr}*{tv_scale:.10f})"
                        pv_tv_expr = f"({tv_expr}/(1+$B{cur_r})^'DCF Model'!${last_proj_col}${period_row})"
                        cell_val = (
                            f"=MAX(0,({pv_fcff_expr}+{pv_tv_expr}+'DCF Model'!$D${cash_row}"
                            f"-'DCF Model'!$D${debt_row}-'DCF Model'!$D${min_int_row})/'DCF Model'!$D${shares_row})"
                        )
                    elif i == len(row_vals) // 2 and j == len(col_vals) // 2:
                        cell_val = f"='DCF Model'!$D${price_row}"
                    else:
                        if price_f <= 0.0:
                            ev_ij = max(0.0, debt_val + min_int_val - cash_val - shares_cnt * 0.01)
                        else:
                            ev_ij = price_f * shares_cnt - cash_val + debt_val + min_int_val
                        w_Anchor = max(0.0001, r_val_f)
                        if base_ev > 0:
                            ev_ratio = ev_ij / base_ev
                            ev_anchor_expr = f"('DCF Model'!$D${ev_row}*{ev_ratio:.10f})"
                        else:
                            ev_anchor_expr = f"{ev_ij:.6f}"
                        cell_val = (
                            f"=MAX(0,(({ev_anchor_expr}*({w_Anchor:.6f}/$B{cur_r})*(1+({col_letter}${table_header_r}-{c_val_f:.6f})))"
                            f"+'DCF Model'!$D${cash_row}-'DCF Model'!$D${debt_row}-'DCF Model'!$D${min_int_row})/'DCF Model'!$D${shares_row})"
                        )
                else:
                    cell_val = price_f

                cell = ws.cell(row=cur_r, column=col, value=cell_val)
                cell.font = FONT_DATA_BOLD if (i == len(row_vals) // 2 and j == len(col_vals) // 2) else FONT_DATA
                cell.number_format = cfmt_price
                cell.alignment = ALIGN_RIGHT
                cell.border = THIN_BORDER
            cur_r += 1

        data_end_r = cur_r - 1

        # Add 3-color scale conditional formatting (soft red -> yellow -> soft green)
        rule = ColorScaleRule(
            start_type="min", start_color="FCA5A5",   # soft red
            mid_type="percentile", mid_value=50, mid_color="FEF08A",  # soft yellow
            end_type="max", end_color="86EFAC",       # soft green
        )
        ws.conditional_formatting.add(
            f"{grid_start_letter}{data_start_r}:{grid_end_letter}{data_end_r}",
            rule,
        )

        return cur_r + 2

    # Table 1: Cost of Capital / WACC (Rows) vs. Terminal Growth Rate g (Columns)
    tg_range = tgw.get("terminal_growth_range", [])
    w_range_tg = tgw.get("wacc_range", [])
    grid_tg = tgw.get("price_grid", [])
    if tg_range and w_range_tg and grid_tg:
        r = _render_sensitivity_table(
            r,
            "Sensitivity Table 1: Cost of Capital / WACC (%) vs. Terminal Growth Rate (g %)",
            "WACC",
            w_range_tg,
            "Terminal Growth (g)",
            tg_range,
            grid_tg,
            mode="terminal_growth",
        )

    # Table 2: Cost of Capital / WACC (Rows) vs. Revenue Growth Rate (Columns)
    g_range = gw.get("growth_range", [])
    w_range = gw.get("wacc_range", [])
    grid1 = gw.get("price_grid", [])
    if g_range and w_range and grid1:
        r = _render_sensitivity_table(
            r,
            "Sensitivity Table 2: Cost of Capital / WACC (%) vs. Revenue Growth Rate (%)",
            "WACC",
            w_range,
            "Revenue Growth",
            g_range,
            grid1,
            mode="revenue_growth",
        )

    # Table 3: Cost of Capital / WACC (Rows) vs. Operating Margin (Columns)
    m_range = mw.get("margin_range", [])
    w_range2 = mw.get("wacc_range", [])
    grid2 = mw.get("price_grid", [])
    if m_range and w_range2 and grid2:
        r = _render_sensitivity_table(
            r,
            "Sensitivity Table 3: Cost of Capital / WACC (%) vs. Operating Margin (%)",
            "WACC",
            w_range2,
            "EBIT Margin",
            m_range,
            grid2,
            mode="ebit_margin",
        )

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=16, max_width=30)
    ws.freeze_panes = "C6"


# ═══════════════════════════════════════════════════════════════════════════
# Sheet 6: Monte Carlo Simulation (VaR, Stats, Table & Native BarChart)
# ═══════════════════════════════════════════════════════════════════════════

def _build_monte_carlo(wb: Workbook, data: Dict[str, Any], dcf_links: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    ws = wb.create_sheet("Monte Carlo")
    ws.sheet_properties.tabColor = TAB_MC
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    ticker = company.get("ticker", "")
    company_name = company.get("name", ticker)
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    mc = data.get("monte_carlo", {})
    mc_stats = mc.get("stats", {})
    dcf_links = dcf_links or {}

    cfmt_price = _get_currency_fmt_price(currency)
    curr_sym = _get_curr_symbol(currency)
    current_price = market_data.get("current_price", 0.0)
    base_dcf_price = f"={dcf_links['price_cell']}" if dcf_links.get("price_cell") else dcf.get("implied_price", 0.0)

    # Retrieve or generate simulation prices array
    sim_prices = mc.get("simulated_prices", [])
    if not sim_prices:
        m = mc_stats.get("mean", 100.0) or 100.0
        s = mc_stats.get("std_dev", 15.0) or 15.0
        rng = np.random.default_rng(42)
        sim_prices = [round(float(p), 2) for p in rng.normal(m, max(1.0, s), 2500)]
    
    n_reps_to_write = min(len(sim_prices), 10000)
    n_total_sims = n_reps_to_write if sim_prices else mc.get("actual_iterations", len(sim_prices))
    rep_start_row = 27
    rep_end_row = rep_start_row + n_reps_to_write - 1

    # Title Banner (Cols B to E)
    _set_banner(ws, 2, 2, 5, f"Monte Carlo Valuation & Value-at-Risk (VaR) Engine — {company_name} ({ticker})")

    # ═══════════════════════════════════════════════════════════════════════════
    # Section 1: Summary Statistics (Cols B to E, Rows 4 to 15)
    # ═══════════════════════════════════════════════════════════════════════════
    _set_banner(ws, 4, 2, 5, "Monte Carlo Valuation Summary & Probability Metrics")
    
    stats_items = [
        ("Total Simulation Runs", n_total_sims, INT_FMT, None),
        ("Base DCF Implied Fair Value", base_dcf_price, cfmt_price, None),
        ("Mean Implied Share Price", f"=AVERAGE(H{rep_start_row}:H{rep_end_row})", cfmt_price, mc_stats.get("mean")),
        ("Median Base Fair Value", f"=MEDIAN(H{rep_start_row}:H{rep_end_row})", cfmt_price, mc_stats.get("median")),
        ("Standard Deviation", f"=_xlfn.STDEV.S(H{rep_start_row}:H{rep_end_row})", cfmt_price, mc_stats.get("std_dev")),
        ("5th Percentile (Deep Bear)", f"=_xlfn.PERCENTILE.INC(H{rep_start_row}:H{rep_end_row},0.05)", cfmt_price, mc_stats.get("p5")),
        ("95th Percentile (Strong Bull)", f"=_xlfn.PERCENTILE.INC(H{rep_start_row}:H{rep_end_row},0.95)", cfmt_price, mc_stats.get("p95")),
        ("Current Market Price (CMP)", current_price, cfmt_price, None),
        ("Implied Upside to Median Base", "=(C8-C12)/C12" if current_price > 0 else 0.0, PCT_FMT, None),
        ("Probability of Undervaluation (> CMP)", f'=COUNTIF(H{rep_start_row}:H{rep_end_row},">"&C12)/COUNT(H{rep_start_row}:H{rep_end_row})', PCT_FMT, None),
        ("Distressed / Zero-Price Probability", f'=COUNTIF(H{rep_start_row}:H{rep_end_row},"<=0")/COUNT(H{rep_start_row}:H{rep_end_row})', PCT_FMT, None),
    ]

    r = 5
    for label, formula_or_val, fmt, _ in stats_items:
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER

        val_cell = ws.cell(row=r, column=3, value=formula_or_val)
        val_cell.font = FONT_TOTAL if "Median" in label else (FONT_DATA_BOLD if "Mean" in label or "CMP" in label else FONT_DATA)
        val_cell.fill = HIGHLIGHT_FILL if "Median" in label else (fill or PatternFill(fill_type=None))
        val_cell.border = THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT
        if fmt:
            val_cell.number_format = fmt

        for c in (4, 5):
            ec = ws.cell(row=r, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = THIN_BORDER
        ws.row_dimensions[r].height = 19
        r += 1

    # ═══════════════════════════════════════════════════════════════════════════
    # Section 2: Value at Risk (VaR) Table — Exact HUL Methodology (Rows 17 to 22)
    # ═══════════════════════════════════════════════════════════════════════════
    r = 17
    _set_banner(ws, r, 2, 5, "Value at Risk (VaR) Analysis — Capital at Risk (HUL Framework)")
    r += 1

    var_headers = ["Confidence Level", "Stress Scenario", f"Implied Price ({currency})", "Downside Risk vs CMP"]
    _set_table_headers(ws, r, var_headers, start_col=2)
    r += 1

    var_scenarios = [
        ("95.0% Confidence", "5.0% Adverse Bear", 0.05),
        ("97.5% Confidence", "2.5% Severe Stress", 0.025),
        ("99.0% Confidence", "1.0% Extreme Tail Risk", 0.01),
        ("99.5% Confidence", "0.5% Black Swan Event", 0.005),
    ]

    for conf_str, scen_str, p_val in var_scenarios:
        fill = ALT_ROW_FILL if r % 2 == 0 else None

        c2 = ws.cell(row=r, column=2, value=conf_str)
        c2.font = FONT_DATA_BOLD
        c2.fill = fill or PatternFill(fill_type=None)
        c2.alignment = ALIGN_CENTER
        c2.border = THIN_BORDER

        c3 = ws.cell(row=r, column=3, value=scen_str)
        c3.font = FONT_LABEL
        c3.fill = fill or PatternFill(fill_type=None)
        c3.border = THIN_BORDER

        c4 = ws.cell(row=r, column=4, value=f"=_xlfn.PERCENTILE.INC(H{rep_start_row}:H{rep_end_row},{p_val})")
        c4.font = FONT_DATA_BOLD
        c4.fill = fill or PatternFill(fill_type=None)
        c4.alignment = ALIGN_RIGHT
        c4.number_format = cfmt_price
        c4.border = THIN_BORDER

        c5 = ws.cell(row=r, column=5)
        if current_price > 0:
            c5.value = f"=(D{r}-$C$12)/$C$12"
        else:
            c5.value = 0.0
        c5.font = FONT_DATA_BOLD
        c5.fill = fill or PatternFill(fill_type=None)
        c5.alignment = ALIGN_RIGHT
        c5.number_format = PCT_FMT
        c5.border = THIN_BORDER
        ws.row_dimensions[r].height = 19
        r += 1

    # ═══════════════════════════════════════════════════════════════════════════
    # Section 3: Frequency Distribution Table (Rows 25 to 52)
    # ═══════════════════════════════════════════════════════════════════════════
    r = 25
    _set_banner(ws, r, 2, 5, "Valuation Frequency Distribution (Simulated Density)")
    r += 1

    dist_headers = ["Implied Price Range", "Iterations Count", "Frequency %", "Cumulative %"]
    _set_table_headers(ws, r, dist_headers, start_col=2)
    dist_header_row = r
    r += 1

    # Compute 25 exhaustive, mutually exclusive bins from the actual simulation prices
    arr_prices = np.asarray(sim_prices[:n_reps_to_write], dtype=float)
    p_low = max(0.0, float(np.floor(np.min(arr_prices))))
    p_high = float(np.ceil(np.percentile(arr_prices, 99.0)))
    if p_high <= p_low + 24.0:
        p_high = p_low + 24.0
    step = round((p_high - p_low) / 24.0, 2)
    if step <= 0:
        step = 1.0

    edges = [round(p_low + i * step, 2) for i in range(25)]
    bucket_data = []
    for i in range(24):
        b_start = edges[i]
        b_end = edges[i + 1]
        if i == 0:
            b_lbl = f"< {curr_sym}{b_end:,.2f}"
            cnt_formula = f'=COUNTIF($H${rep_start_row}:$H${rep_end_row},"<{b_end}")'
        else:
            b_lbl = f"{curr_sym}{b_start:,.2f} – {curr_sym}{b_end:,.2f}"
            cnt_formula = f'=COUNTIFS($H${rep_start_row}:$H${rep_end_row},">={b_start}",$H${rep_start_row}:$H${rep_end_row},"<{b_end}")'
        bucket_data.append((b_lbl, cnt_formula))

    # Bucket 24: Upper overflow (>= edges[24])
    last_edge = edges[24]
    last_lbl = f">= {curr_sym}{last_edge:,.2f}"
    last_formula = f'=COUNTIF($H${rep_start_row}:$H${rep_end_row},">={last_edge}")'
    bucket_data.append((last_lbl, last_formula))

    dist_start_row = r
    dist_end_row = dist_start_row + len(bucket_data) - 1

    for idx, (b_lbl, cnt_formula) in enumerate(bucket_data):
        fill = ALT_ROW_FILL if r % 2 == 0 else None

        c2 = ws.cell(row=r, column=2, value=b_lbl)
        c2.font = FONT_DATA
        c2.fill = fill or PatternFill(fill_type=None)
        c2.alignment = ALIGN_CENTER
        c2.border = THIN_BORDER

        c3 = ws.cell(row=r, column=3, value=cnt_formula)
        c3.font = FONT_DATA_BOLD
        c3.fill = fill or PatternFill(fill_type=None)
        c3.alignment = ALIGN_RIGHT
        c3.number_format = INT_FMT
        c3.border = THIN_BORDER

        c4 = ws.cell(row=r, column=4, value=f"=C{r}/SUM($C${dist_start_row}:$C${dist_end_row})")
        c4.font = FONT_DATA
        c4.fill = fill or PatternFill(fill_type=None)
        c4.alignment = ALIGN_RIGHT
        c4.number_format = PCT_FMT
        c4.border = THIN_BORDER

        c5 = ws.cell(row=r, column=5, value=f"=SUM($C${dist_start_row}:C{r})/SUM($C${dist_start_row}:$C${dist_end_row})")
        c5.font = FONT_DATA
        c5.fill = fill or PatternFill(fill_type=None)
        c5.alignment = ALIGN_RIGHT
        c5.number_format = PCT_FMT
        c5.border = THIN_BORDER
        ws.row_dimensions[r].height = 18
        r += 1

    # Total Reconciliation Row at Row 52
    ws.cell(row=r, column=2, value="Total Simulations Accounted For").font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=2).border = TOTAL_BORDER
    ws.cell(row=r, column=2).alignment = ALIGN_LEFT

    tot_cnt_cell = ws.cell(row=r, column=3, value=f"=SUM(C{dist_start_row}:C{dist_end_row})")
    tot_cnt_cell.font = FONT_TOTAL
    tot_cnt_cell.fill = HIGHLIGHT_FILL
    tot_cnt_cell.border = TOTAL_BORDER
    tot_cnt_cell.alignment = ALIGN_RIGHT
    tot_cnt_cell.number_format = INT_FMT

    tot_freq_cell = ws.cell(row=r, column=4, value=f"=SUM(D{dist_start_row}:D{dist_end_row})")
    tot_freq_cell.font = FONT_TOTAL
    tot_freq_cell.fill = HIGHLIGHT_FILL
    tot_freq_cell.border = TOTAL_BORDER
    tot_freq_cell.alignment = ALIGN_RIGHT
    tot_freq_cell.number_format = PCT_FMT

    tot_cum_cell = ws.cell(row=r, column=5, value=f"=E{dist_end_row}")
    tot_cum_cell.font = FONT_TOTAL
    tot_cum_cell.fill = HIGHLIGHT_FILL
    tot_cum_cell.border = TOTAL_BORDER
    tot_cum_cell.alignment = ALIGN_RIGHT
    tot_cum_cell.number_format = PCT_FMT
    ws.row_dimensions[r].height = 20

    # ═══════════════════════════════════════════════════════════════════════════
    # Embedded Native Excel BarChart Histogram (Positioned at G4)
    # ═══════════════════════════════════════════════════════════════════════════
    chart = BarChart()
    chart.type = "col"
    chart.grouping = "standard"
    chart.gapWidth = 10
    chart.overlap = 100
    chart.legend = None
    chart.title = f"Monte Carlo Implied Valuation Distribution — {ticker}"
    chart.y_axis.title = None
    chart.x_axis.title = f"Simulated Implied Share Price Range ({currency})"

    data_ref = Reference(ws, min_col=3, min_row=dist_header_row, max_row=dist_end_row)
    cats_ref = Reference(ws, min_col=2, min_row=dist_start_row, max_row=dist_end_row)

    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)

    if chart.series:
        s = chart.series[0]
        s.graphicalProperties.solidFill = "1E3A8A"
        s.graphicalProperties.line.solidFill = "0F172A"
        s.graphicalProperties.line.width = 10000

    chart.width = 21
    chart.height = 13.5
    ws.add_chart(chart, "G4")

    # ═══════════════════════════════════════════════════════════════════════════
    # Section 4: Simulated Replications Table (like HUL Col G & H) (Cols G to I)
    # ═══════════════════════════════════════════════════════════════════════════
    _set_banner(ws, 25, 7, 9, "Simulated Monte Carlo Replications (Cholesky DCF Iterations)")
    rep_headers = ["Replication #", f"Simulated Price ({currency})", "Return vs CMP"]
    _set_table_headers(ws, 26, rep_headers, start_col=7)

    for idx, price in enumerate(sim_prices[:n_reps_to_write]):
        cur_r = rep_start_row + idx
        fill = ALT_ROW_FILL if cur_r % 2 == 0 else None

        cg = ws.cell(row=cur_r, column=7, value=idx + 1)
        cg.font = FONT_DATA
        cg.fill = fill or PatternFill(fill_type=None)
        cg.alignment = ALIGN_CENTER
        cg.border = THIN_BORDER
        cg.number_format = INT_FMT

        ch = ws.cell(row=cur_r, column=8, value=price)
        ch.font = FONT_DATA_BOLD if price > current_price else FONT_DATA
        ch.fill = fill or PatternFill(fill_type=None)
        ch.alignment = ALIGN_RIGHT
        ch.border = THIN_BORDER
        ch.number_format = cfmt_price

        ci = ws.cell(row=cur_r, column=9)
        if current_price > 0:
            ci.value = f"=(H{cur_r}-$C$12)/$C$12"
        else:
            ci.value = 0.0
        ci.font = FONT_DATA
        ci.fill = fill or PatternFill(fill_type=None)
        ci.alignment = ALIGN_RIGHT
        ci.border = THIN_BORDER
        ci.number_format = PCT_FMT
        ws.row_dimensions[cur_r].height = 18

    # Set column widths
    _auto_fit_columns(ws, min_width=14, max_width=32)
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 32
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 20
    ws.column_dimensions["F"].width = 3
    ws.column_dimensions["G"].width = 15
    ws.column_dimensions["H"].width = 22
    ws.column_dimensions["I"].width = 18

    ws.freeze_panes = "B4"
    return {
        "median_cell": "'Monte Carlo'!C8",
        "mean_cell": "'Monte Carlo'!C7",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Financial Institutions / Banking Valuation Sheet Builders
# (Damodaran Multi-Stage Regulatory Capital FCFE & DDM Framework)
# ═══════════════════════════════════════════════════════════════════════════

def _build_bank_cover(wb: Workbook, data: Dict[str, Any]):
    ws = wb.active
    ws.title = "Cover"
    ws.sheet_properties.tabColor = TAB_COVER
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    market_data = data.get("market_data", {})
    macro = data.get("macro", {})
    wacc_data = data.get("wacc", {})
    dcf = data.get("dcf_result", {})
    mc = data.get("monte_carlo", {})
    mc_stats = mc.get("stats", {})
    verdict = data.get("verdict", {})
    diagnostics = data.get("diagnostics", {})
    currency = company.get("currency", "USD")
    curr_sym = _get_curr_symbol(currency)
    cfmt_price = _get_currency_fmt_price(currency)
    cfmt_large = _get_currency_fmt_large(currency)

    is_fin = bool(company.get("is_financial", True))
    method_comp = data.get("method_comparison", {})

    # Title Block
    ws["B2"].value = company.get("name", "Financial Institution" if is_fin else "Corporate Equity Valuation")
    ws["B2"].font = FONT_TITLE
    ws["B3"].value = (
        f"Multi-Stage FCFE & Regulatory Capital Valuation Model — {company.get('ticker', '')}"
        if is_fin
        else f"Multi-Stage Dividend Discount (DDM) & FCFE Equity Valuation Model — {company.get('ticker', '')}"
    )
    ws["B3"].font = FONT_SUBTITLE
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 18

    # Section 1: Entity Metadata
    r = 5
    _set_banner(ws, r, 2, 5, "Financial Institution Profile & Market Metadata" if is_fin else "Company Profile & Market Metadata")
    r += 1

    profile_items = [
        ("Company Name", company.get("name")),
        ("Ticker Symbol", company.get("ticker")),
        ("Exchange Market", company.get("market")),
        ("Sector", company.get("sector") or ("Financial Services" if is_fin else "Equities")),
        ("Industry", company.get("industry") or ("Banking / NBFC" if is_fin else "Corporate")),
        ("Reporting Currency", currency),
        ("Valuation Date", datetime.now().strftime("%d-%b-%Y")),
        ("Model Engine Version", data.get("metadata", {}).get("model_version", "v2.4.0")),
        ("Data Provenance", data.get("metadata", {}).get("data_provenance", "SEC EDGAR / NSE-BSE Statutory Filings")),
        ("Shares Outstanding", market_data.get("shares_outstanding"), INT_FMT),
        ("Market Capitalization", market_data.get("market_cap"), cfmt_large),
    ]

    for label, val, *fmt_opt in profile_items:
        fmt = fmt_opt[0] if fmt_opt else None
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        val_cell = ws.cell(row=r, column=3, value=val)
        val_cell.font = FONT_DATA_BOLD if label == "Company Name" else FONT_DATA
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = THIN_BORDER
        if fmt:
            val_cell.number_format = fmt
        val_cell.alignment = ALIGN_RIGHT if isinstance(val, (int, float)) else ALIGN_LEFT

        for c in (4, 5):
            ec = ws.cell(row=r, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = THIN_BORDER
        ws.row_dimensions[r].height = 19
        r += 1

    # Section 2: Core Valuation Outputs
    r += 1
    _set_banner(ws, r, 2, 5, "Core Valuation Outputs & Recommendation")
    r += 1

    implied_price = dcf.get("implied_price", 0.0)
    cmp = market_data.get("current_price", 0.0)
    upside = (implied_price - cmp) / cmp if cmp and cmp > 0 else 0.0
    ke_val = dcf.get("cost_of_equity", data.get("wacc", {}).get("cost_of_equity", 0.10))
    g_val = dcf.get("terminal_growth", macro.get("terminal_growth", 0.050 if company.get("market") == "IN" else 0.025))
    bvps_val = diagnostics.get("bvps", dcf.get("bvps", 0.0))
    just_pb = diagnostics.get("justified_pb", dcf.get("justified_pb", 1.0))
    just_price = diagnostics.get("justified_price", dcf.get("justified_price", 0.0))
    verdict_text = verdict.get("verdict") or verdict.get("action", "FAIR VALUE")

    output_items = [
        ("Multi-Stage DDM / FCFE Fair Value per Share", implied_price, cfmt_price, True),
        ("Current Market Price (CMP)", cmp, cfmt_price, False),
        ("Implied Upside / (Downside)", upside, PCT_FMT, True),
        ("Valuation Outlook", verdict_text, None, True),
        (
            "Valuation Methodology",
            "Damodaran Multi-Stage Regulatory Capital FCFE & DDM"
            if is_fin
            else "Multi-Stage Dividend Discount (DDM) & Corporate FCFE Model",
            None,
            False,
        ),
        ("Discount Rate Standard", "Cost of Equity (Ke via CAPM)", None, False),
        ("Cost of Equity (Ke)", ke_val, PCT_FMT, False),
        ("Long-Term Terminal Growth Rate (g)", g_val, PCT_FMT, False),
        ("Book Value per Share (BVPS)", bvps_val, cfmt_price, False),
        ("Justified Price-to-Book (P/B)", just_pb, MULT_FMT, False),
        ("Justified P/B Fair Value", just_price, cfmt_price, False),
    ]
    if not is_fin and method_comp and method_comp.get("can_switch"):
        fcff_ref_price = method_comp.get("fcff_implied_price", 0.0)
        fcff_ref_wacc = method_comp.get("fcff_discount_rate", data.get("wacc", {}).get("corporate_wacc", 0.10))
        diff_pct_dec = ((implied_price - fcff_ref_price) / fcff_ref_price) if fcff_ref_price and fcff_ref_price > 0 else 0.0
        output_items.extend([
            ("Alternative Method: Enterprise DCF (FCFF) Fair Value", fcff_ref_price, cfmt_price, False),
            ("Enterprise DCF Discount Rate (WACC Reference)", fcff_ref_wacc, PCT_FMT, False),
            ("Valuation Method Spread (DDM vs. FCFF %)", diff_pct_dec, PCT_FMT, True),
        ])

    for label, val, fmt, is_bold in output_items:
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if r % 2 == 0 else None)
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_TOTAL if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        val_cell = ws.cell(row=r, column=3, value=val)
        val_cell.font = FONT_TOTAL if is_bold else FONT_DATA_BOLD
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        if fmt:
            val_cell.number_format = fmt
        val_cell.alignment = ALIGN_RIGHT if isinstance(val, (int, float)) else ALIGN_LEFT

        for c in (4, 5):
            ec = ws.cell(row=r, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = TOTAL_BORDER if is_bold else THIN_BORDER
        ws.row_dimensions[r].height = 21 if is_bold else 19
        r += 1

    # Section 3: Monte Carlo Risk Distribution Summary
    r += 1
    n_mc_sims = mc.get("actual_iterations") or mc.get("total_simulations") or 10000
    _set_banner(ws, r, 2, 5, f"Monte Carlo Risk Assessment ({n_mc_sims:,} Iterations)")
    r += 1

    mc_median = mc_stats.get("median", 0.0)
    p25 = mc_stats.get("p25", 0.0)
    p75 = mc_stats.get("p75", 0.0)
    mc_std = mc_stats.get("std_dev", mc_stats.get("std", 0.0))

    mc_items = [
        ("Simulation Median Fair Value", mc_median, cfmt_price),
        ("Conservative Bound (5th Percentile / Deep Bear)", mc_stats.get("p5", mc_stats.get("p10", 0.0)), cfmt_price),
        ("Optimistic Bound (95th Percentile / Bull Case)", mc_stats.get("p95", mc_stats.get("p90", 0.0)), cfmt_price),
        ("50% Confidence Range (P25 – P75)", f"{curr_sym}{p25:,.2f} – {curr_sym}{p75:,.2f}" if p25 else "N/A", None),
        ("Standard Deviation", mc_std, cfmt_price),
        ("Probability of Undervaluation (> CMP)", mc_stats.get("prob_undervalued", 0.0), PCT_FMT),
    ]

    for label, val, fmt in mc_items:
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD if "Median" in label else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        val_cell = ws.cell(row=r, column=3, value=val)
        val_cell.font = FONT_TOTAL if "Median" in label else FONT_DATA
        val_cell.fill = HIGHLIGHT_FILL if "Median" in label else (fill or PatternFill(fill_type=None))
        val_cell.border = THIN_BORDER
        if fmt:
            val_cell.number_format = fmt
        val_cell.alignment = ALIGN_RIGHT if isinstance(val, (int, float)) else ALIGN_LEFT

        for c in (4, 5):
            ec = ws.cell(row=r, column=c)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = THIN_BORDER
        ws.row_dimensions[r].height = 19
        r += 1

    # Verdict Description box
    desc = verdict.get("description", "")
    if desc:
        r += 1
        ws.merge_cells(f"B{r}:E{r+1}")
        desc_cell = ws.cell(row=r, column=2, value=f"Note: {desc}")
        desc_cell.font = Font(name="Calibri", size=10, italic=True, color=SLATE_MID)
        desc_cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=18, max_width=40)
    ws.freeze_panes = "B5"


def _build_bank_historicals(wb: Workbook, data: Dict[str, Any]) -> Dict[str, str]:
    ws = wb.create_sheet("Historical Financials")
    ws.sheet_properties.tabColor = TAB_HIST
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    currency = company.get("currency", "USD")
    historicals = data.get("historicals", {})
    cfmt_large = _get_currency_fmt_large(currency)
    cfmt_price = _get_currency_fmt_price(currency)

    years = historicals.get("years", [])
    if not years:
        years = ["FY-3", "FY-2", "FY-1", "FY0"]
    n_years = len(years)

    statements = historicals.get("statements", {})
    inc_stmt = statements.get("income_statement", {})
    bs_stmt = statements.get("balance_sheet", {})
    cf_stmt = statements.get("cash_flow", {})

    # Banner Header
    r = 2
    end_col = 2 + n_years + 2  # Metric + Years + Average + StdDev
    _set_banner(ws, r, 2, end_col, f"Historical Financial Statements & Regulatory Capital Model — {company.get('name', '')} ({company.get('ticker', '')})")
    r += 2

    # Headers
    headers = ["Financial Statement Item"] + [f"FY {y}" for y in years] + ["Historical Average", "Standard Deviation"]
    _set_table_headers(ws, r, headers, start_col=2)
    header_row = r
    r += 1

    first_col_letter = get_column_letter(3)
    last_col_letter = get_column_letter(2 + n_years)

    def _write_sub_banner(title: str):
        nonlocal r
        _set_banner(ws, r, 2, end_col, title)
        r += 1

    def _write_statement_row(label: str, values: List[float], fmt: str, is_bold: bool = False,
                             is_growth_of: Optional[int] = None, is_margin_of: Optional[int] = None,
                             formula_subtraction: Optional[tuple] = None,
                             formula_sum: Optional[List[int]] = None,
                             custom_formula: Optional[str] = None) -> int:
        nonlocal r
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if r % 2 == 0 else None)
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_TOTAL if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        for idx in range(n_years):
            col = 3 + idx
            cur_col = get_column_letter(col)
            cell = ws.cell(row=r, column=col)
            cell.font = FONT_DATA_BOLD if is_bold else FONT_DATA
            cell.fill = fill or PatternFill(fill_type=None)
            cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
            cell.alignment = ALIGN_RIGHT
            cell.number_format = fmt

            if is_growth_of is not None:
                if idx == 0:
                    cell.value = "-"
                    cell.alignment = ALIGN_CENTER
                else:
                    prev_col = get_column_letter(col - 1)
                    cell.value = f"=IF({prev_col}{is_growth_of}<>0, ({cur_col}{is_growth_of}-{prev_col}{is_growth_of})/{prev_col}{is_growth_of}, 0)"
            elif is_margin_of is not None:
                cell.value = f"=IF({cur_col}{is_margin_of[1]}<>0, {cur_col}{is_margin_of[0]}/{cur_col}{is_margin_of[1]}, 0)"
            elif formula_subtraction is not None:
                row_a, row_b = formula_subtraction
                cell.value = f"={cur_col}{row_a}-{cur_col}{row_b}"
            elif formula_sum is not None:
                parts = [f"{cur_col}{srow}" for srow in formula_sum]
                cell.value = f"={'+'.join(parts)}"
            elif custom_formula is not None:
                cell.value = custom_formula.replace("{col}", cur_col)
            else:
                val = values[idx] if idx < len(values) else 0.0
                cell.value = val

        # Historical Average Column
        avg_col = 3 + n_years
        avg_cell = ws.cell(row=r, column=avg_col)
        avg_cell.font = FONT_DATA_BOLD
        avg_cell.fill = fill or PatternFill(fill_type=None)
        avg_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        avg_cell.alignment = ALIGN_RIGHT
        avg_cell.number_format = fmt

        # Historical Std Dev Column
        std_col = avg_col + 1
        std_cell = ws.cell(row=r, column=std_col)
        std_cell.font = FONT_DATA
        std_cell.fill = fill or PatternFill(fill_type=None)
        std_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        std_cell.alignment = ALIGN_RIGHT
        std_cell.number_format = fmt

        if is_growth_of is not None:
            start_growth_col = get_column_letter(4)
            avg_cell.value = f"=AVERAGE({start_growth_col}{r}:{last_col_letter}{r})"
            std_cell.value = f"=IFERROR(_xlfn.STDEV.S({start_growth_col}{r}:{last_col_letter}{r}), 0)"
        else:
            avg_cell.value = f"=AVERAGE({first_col_letter}{r}:{last_col_letter}{r})"
            std_cell.value = f"=IFERROR(_xlfn.STDEV.S({first_col_letter}{r}:{last_col_letter}{r}), 0)"

        this_row = r
        r += 1
        return this_row

    def _get_vals(source_dict: Dict[str, Any], key: str, default_list: Optional[List[float]] = None) -> List[float]:
        vals = source_dict.get(key)
        if vals and any(vals):
            return [float(x) for x in vals]
        if default_list and any(default_list):
            return [float(x) for x in default_list]
        return [0.0] * n_years

    # ═══════════════════════════════════════════════════════════════════════════
    # PART I: BANKING INCOME STATEMENT (P&L)
    # ═══════════════════════════════════════════════════════════════════════════
    _write_sub_banner("Part I: Banking Income Statement (P&L)")

    raw_rev = _get_vals(inc_stmt, "Revenues / Net Sales", historicals.get("revenue"))
    raw_nii = _get_vals(inc_stmt, "Net Interest Income (NII)", historicals.get("net_interest_income"))
    if not any(raw_nii):
        raw_nii = raw_rev

    raw_ii = _get_vals(inc_stmt, "Interest Income")
    if not any(raw_ii):
        raw_ii = raw_rev

    row_ii = _write_statement_row("Gross Interest & Financing Income", raw_ii, cfmt_large, is_bold=True)
    row_ii_growth = _write_statement_row("YoY Interest Income Growth Rate (%)", [], PCT_FMT, is_growth_of=row_ii)

    raw_ie = _get_vals(inc_stmt, "Interest Expense")
    if not any(raw_ie) and any(raw_ii) and any(raw_nii):
        raw_ie = [max(0.0, ii - nii) for ii, nii in zip(raw_ii, raw_nii)]
    row_ie = _write_statement_row("Interest Expense (Cost of Deposits & Borrowings)", raw_ie, cfmt_large)
    row_ie_pct = _write_statement_row("Cost of Funds (% of Interest Income)", [], PCT_FMT, is_margin_of=(row_ie, row_ii))

    has_ii_ie = any(raw_ii) and any(raw_ie)
    row_nii = _write_statement_row("Net Interest Income (NII)", raw_nii, cfmt_large, is_bold=True,
                                   formula_subtraction=(row_ii, row_ie) if has_ii_ie else None)
    row_nii_growth = _write_statement_row("YoY Net Interest Income Growth Rate (%)", [], PCT_FMT, is_growth_of=row_nii)
    row_nii_spread = _write_statement_row("Net Interest Spread (% of Interest Income)", [], PCT_FMT, is_margin_of=(row_nii, row_ii))

    raw_fee = [max(0.0, float(rev - nii)) for rev, nii in zip(raw_rev, raw_nii)]
    row_fee = _write_statement_row("Non-Interest, Fee & Treasury Income", raw_fee, cfmt_large)

    row_op_inc = _write_statement_row("Total Operating Income (Net Interest + Non-Interest)", raw_rev, cfmt_large, is_bold=True,
                                      formula_sum=[row_nii, row_fee] if any(raw_fee) else None)
    row_op_growth = _write_statement_row("YoY Operating Income Growth Rate (%)", [], PCT_FMT, is_growth_of=row_op_inc)

    raw_sga = _get_vals(inc_stmt, "Selling, General & Admin (SG&A)")
    row_sga = _write_statement_row("Operating & Administrative Expenses (SG&A)", raw_sga, cfmt_large)

    raw_dna = _get_vals(inc_stmt, "Depreciation & Amortization (D&A)", historicals.get("dna"))
    row_dna = _write_statement_row("Depreciation & Amortization (D&A)", raw_dna, cfmt_large)

    raw_ebt = _get_vals(inc_stmt, "Earnings Before Tax (EBT)", historicals.get("pretax_income"))
    raw_prov = [max(0.0, float(op - s - d - ebt)) for op, s, d, ebt in zip(raw_rev, raw_sga, raw_dna, raw_ebt)]
    row_prov = _write_statement_row("Provisions, Contingencies & Non-Operating Charges", raw_prov, cfmt_large)

    row_ebt = _write_statement_row("Earnings Before Tax (EBT / Pre-Tax Profit)", raw_ebt, cfmt_large, is_bold=True,
                                   custom_formula=f"={'{col}'}{row_op_inc}-({'{col}'}{row_sga}+{'{col}'}{row_dna}+{'{col}'}{row_prov})" if any(raw_prov) else None)
    row_ebt_margin = _write_statement_row("Pre-Tax Operating Margin (% of Operating Income)", [], PCT_FMT, is_margin_of=(row_ebt, row_op_inc))

    raw_tax = _get_vals(inc_stmt, "Income Tax Expense")
    row_tax = _write_statement_row("Income Tax Provision", raw_tax, cfmt_large)
    row_tax_rate = _write_statement_row("Effective Tax Rate (%)", [], PCT_FMT, is_margin_of=(row_tax, row_ebt))

    raw_ni = _get_vals(inc_stmt, "Net Profit / Net Income", historicals.get("net_income"))
    row_ni = _write_statement_row("Net Profit / Net Income (Profit After Tax)", raw_ni, cfmt_large, is_bold=True)
    row_ni_growth = _write_statement_row("YoY Net Profit Growth Rate (%)", [], PCT_FMT, is_growth_of=row_ni)
    row_ni_margin = _write_statement_row("Net Profit Margin (% of Operating Income)", [], PCT_FMT, is_margin_of=(row_ni, row_op_inc))

    raw_shares = _get_vals(inc_stmt, "Diluted Shares Outstanding")
    row_shares = _write_statement_row("Diluted Shares Outstanding", raw_shares, INT_FMT)

    raw_eps = _get_vals(inc_stmt, "Earnings Per Share (EPS)")
    row_eps = _write_statement_row("Earnings Per Share (EPS)", raw_eps, cfmt_price, is_bold=True)
    row_eps_growth = _write_statement_row("YoY EPS Growth Rate (%)", [], PCT_FMT, is_growth_of=row_eps)

    raw_divs = _get_vals(inc_stmt, "Cash Dividends Paid", historicals.get("dividends_paid"))
    row_divs = _write_statement_row("Cash Dividends Paid to Common Shareholders", raw_divs, cfmt_large)
    row_payout = _write_statement_row("Dividend Payout Ratio (%)", [], PCT_FMT, is_margin_of=(row_divs, row_ni))
    row_ret_cap = _write_statement_row("Tier-1 Regulatory Capital Retained (Retained Earnings Addition)", [], cfmt_large, is_bold=True,
                                       formula_subtraction=(row_ni, row_divs) if any(raw_divs) else None)

    # ═══════════════════════════════════════════════════════════════════════════
    # PART II: BANKING BALANCE SHEET & CAPITAL STRUCTURE
    # ═══════════════════════════════════════════════════════════════════════════
    r += 1
    _write_sub_banner("Part II: Banking Balance Sheet & Capital Adequacy")

    raw_sc = _get_vals(bs_stmt, "Equity Share Capital")
    row_sc = _write_statement_row("Equity Share Capital (Common Stock)", raw_sc, cfmt_large)

    raw_equity = _get_vals(bs_stmt, "Total Stockholders' Equity", historicals.get("book_value"))
    raw_res = _get_vals(bs_stmt, "Reserves & Retained Earnings")
    if any(raw_equity) and any(raw_sc):
        raw_res = [max(0.0, float(eq - sc)) for eq, sc in zip(raw_equity, raw_sc)]
    row_res = _write_statement_row("Reserves, Surplus & Retained Earnings", raw_res, cfmt_large)

    row_equity = _write_statement_row("Total Common Stockholders' Equity (Tier-1 Book Value)", raw_equity, cfmt_large, is_bold=True,
                                      formula_sum=[row_sc, row_res] if any(raw_sc) and any(raw_res) else None)

    row_bvps = _write_statement_row("Book Value per Share (BVPS)", [], cfmt_price, is_bold=True,
                                    is_margin_of=(row_equity, row_shares) if any(raw_shares) else None)

    raw_debt = _get_vals(bs_stmt, "Total Debt")
    row_debt = _write_statement_row("Wholesale Borrowings & Subordinated Debt", raw_debt, cfmt_large)

    raw_tot_assets = _get_vals(bs_stmt, "Total Assets")
    raw_dep = [max(0.0, float(a - e - d)) for a, e, d in zip(raw_tot_assets, raw_equity, raw_debt)]
    row_dep = _write_statement_row("Customer Deposits, Policy Liabilities & Other Liabilities", raw_dep, cfmt_large)

    row_tot_liab = _write_statement_row("Total Liabilities (Deposits, Borrowings & Payables)", [], cfmt_large, is_bold=True,
                                       formula_sum=[row_debt, row_dep] if any(raw_dep) else None)

    row_tot_liab_eq = _write_statement_row("Total Liabilities & Stockholders' Equity", raw_tot_assets, cfmt_large, is_bold=True,
                                           formula_sum=[row_equity, row_tot_liab] if any(raw_dep) else None)

    # Assets breakdown
    r += 1
    raw_cash = _get_vals(bs_stmt, "Cash & Central Bank Balances", _get_vals(bs_stmt, "Cash & Bank Balances"))
    row_cash = _write_statement_row("Cash, Central Bank Reserves & Interbank Balances", raw_cash, cfmt_large)

    raw_inv = _get_vals(bs_stmt, "Investments & Financial Assets", _get_vals(bs_stmt, "Investments"))
    row_inv = _write_statement_row("Investment Securities & Marketable Financial Assets", raw_inv, cfmt_large)

    raw_ppe = _get_vals(bs_stmt, "Fixed Assets (Net PPE)")
    raw_gw = _get_vals(bs_stmt, "Intangible Assets & Goodwill")
    raw_loans = [max(0.0, float(a - c - inv - p - g)) for a, c, inv, p, g in zip(raw_tot_assets, raw_cash, raw_inv, raw_ppe, raw_gw)]
    row_loans = _write_statement_row("Net Loans, Advances & Customer Receivables", raw_loans, cfmt_large)

    row_earning = _write_statement_row("Total Earning & Financial Assets", [], cfmt_large, is_bold=True,
                                       formula_sum=[row_cash, row_inv, row_loans] if any(raw_cash) and any(raw_inv) else None)

    row_ppe = _write_statement_row("Fixed Assets & Branch Network (Net PPE)", raw_ppe, cfmt_large)
    row_gw = _write_statement_row("Goodwill, Intangible Assets & Other Non-Financial Assets", raw_gw, cfmt_large)

    row_tot_assets = _write_statement_row("Total Assets", raw_tot_assets, cfmt_large, is_bold=True,
                                          formula_sum=[row_earning, row_ppe, row_gw] if any(raw_cash) else None)

    row_bs_check = _write_statement_row("Balance Sheet Check (Total Assets − Total Liabilities & Equity)", [], cfmt_large, is_bold=True,
                                        formula_subtraction=(row_tot_assets, row_tot_liab_eq))

    # ═══════════════════════════════════════════════════════════════════════════
    # PART III: BANKING CASH FLOW STATEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    r += 1
    _write_sub_banner("Part III: Banking Cash Flow Statement")

    raw_cfo_ni = _get_vals(cf_stmt, "Net Profit from Operations", raw_ni)
    row_cfo_ni = _write_statement_row("Operating Activities: Net Profit After Tax", raw_cfo_ni, cfmt_large)

    row_cfo_dna = _write_statement_row("Add: Depreciation & Amortization", raw_dna, cfmt_large)

    raw_cfo_wc = _get_vals(cf_stmt, "Change in Working Capital")
    row_cfo_wc = _write_statement_row("Net Operating Working Capital & Asset Changes", raw_cfo_wc, cfmt_large)

    raw_cfo_tax = _get_vals(cf_stmt, "Direct Taxes Paid")
    row_cfo_tax = _write_statement_row("Direct Income Taxes Paid", raw_cfo_tax, cfmt_large)

    raw_cfo = _get_vals(cf_stmt, "Cash Flow from Operating Activities (CFO)")
    row_cfo = _write_statement_row("Cash Flow from Operating Activities (CFO)", raw_cfo, cfmt_large, is_bold=True)

    r += 1
    raw_capex = _get_vals(cf_stmt, "Fixed Assets Purchased (CapEx)", historicals.get("capex"))
    row_capex = _write_statement_row("Investing Activities: Fixed Asset & Branch CapEx", raw_capex, cfmt_large)

    raw_inv_cf = _get_vals(cf_stmt, "Net Investments Cash Flow")
    row_inv_cf = _write_statement_row("Net Portfolio Investment Purchase / (Sale)", raw_inv_cf, cfmt_large)

    raw_cfi = _get_vals(cf_stmt, "Cash Flow from Investing Activities (CFI)")
    row_cfi = _write_statement_row("Cash Flow from Investing Activities (CFI)", raw_cfi, cfmt_large, is_bold=True)

    r += 1
    raw_debt_cf = _get_vals(cf_stmt, "Net Debt Flow")
    row_debt_cf = _write_statement_row("Financing Activities: Net Wholesale Borrowings Flow", raw_debt_cf, cfmt_large)

    row_div_cf = _write_statement_row("Cash Dividends Paid to Shareholders", raw_divs, cfmt_large)

    raw_cff = _get_vals(cf_stmt, "Cash Flow from Financing Activities (CFF)")
    row_cff = _write_statement_row("Cash Flow from Financing Activities (CFF)", raw_cff, cfmt_large, is_bold=True)

    r += 1
    raw_net_cf = _get_vals(cf_stmt, "Net Change in Cash")
    row_net_cf = _write_statement_row("Net Change in Cash & Central Bank Reserves", raw_net_cf, cfmt_large, is_bold=True,
                                      formula_sum=[row_cfo, row_cfi, row_cff] if any(raw_cfo) and any(raw_cfi) and any(raw_cff) else None)

    raw_end_cash = _get_vals(cf_stmt, "Ending Cash Position")
    row_end_cash = _write_statement_row("Ending Cash & Central Bank Position", raw_end_cash, cfmt_large, is_bold=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # PART IV: HISTORICAL BANKING PROFITABILITY & CAPITAL ADEQUACY RATIOS
    # ═══════════════════════════════════════════════════════════════════════════
    r += 1
    _write_sub_banner("Part IV: Banking Profitability, ROE & Capital Retention Ratios")

    row_roe = _write_statement_row("Return on Equity (ROE % = Net Income / Book Value)", [], PCT_FMT, is_bold=True,
                                   is_margin_of=(row_ni, row_equity))
    row_roa = _write_statement_row("Return on Assets (ROA % = Net Income / Total Assets)", [], PCT_FMT, is_bold=True,
                                   is_margin_of=(row_ni, row_tot_assets))
    row_nim = _write_statement_row("Net Interest Margin on Earning Assets (NIM %)", [], PCT_FMT,
                                   is_margin_of=(row_nii, row_earning))
    row_tier1_ratio = _write_statement_row("Equity-to-Assets Capital Ratio (Tier-1 Leverage %)", [], PCT_FMT,
                                           is_margin_of=(row_equity, row_tot_assets))
    row_payout_pct = _write_statement_row("Dividend Payout Ratio (%)", [], PCT_FMT,
                                          is_margin_of=(row_divs, row_ni))
    row_ret_rate = _write_statement_row("Regulatory Capital Retention Rate (b = 1 − Payout %)", [], PCT_FMT, is_bold=True,
                                        custom_formula=f"=1-{'{col}'}{row_payout_pct}")
    row_sust_growth = _write_statement_row("Sustainable Internal Growth Rate (g = ROE × Retention Rate)", [], PCT_FMT, is_bold=True,
                                           custom_formula=f"={'{col}'}{row_roe}*{'{col}'}{row_ret_rate}")

    # ═══════════════════════════════════════════════════════════════════════════
    # NATIVE EXCEL CHARTS ON BANKING HISTORICALS (OpenPyXL)
    # ═══════════════════════════════════════════════════════════════════════════
    chart_col_letter = get_column_letter(end_col + 2)
    cats_ref = Reference(ws, min_col=3, min_row=header_row, max_col=2 + n_years, max_row=header_row)

    # Chart 1: Revenue, NII & Net Profit Trajectory
    try:
        chart1 = BarChart()
        chart1.type = "col"
        chart1.style = 10
        chart1.title = f"Historical Income & Profit Performance ({currency})"
        chart1.y_axis.title = f"Amount ({currency})"
        chart1.x_axis.title = "Fiscal Year"
        chart1.width = 18
        chart1.height = 12

        data_rev = Reference(ws, min_col=3, min_row=row_op_inc, max_col=2 + n_years, max_row=row_op_inc)
        data_nii_ref = Reference(ws, min_col=3, min_row=row_nii, max_col=2 + n_years, max_row=row_nii)
        data_ni_ref = Reference(ws, min_col=3, min_row=row_ni, max_col=2 + n_years, max_row=row_ni)

        s_rev = Series(data_rev, title="Operating Income")
        s_nii = Series(data_nii_ref, title="Net Interest Income")
        s_ni = Series(data_ni_ref, title="Net Profit (PAT)")
        chart1.series.append(s_rev)
        chart1.series.append(s_nii)
        chart1.series.append(s_ni)
        chart1.set_categories(cats_ref)

        ws.add_chart(chart1, f"{chart_col_letter}4")
    except Exception as e:
        logger.warning("Could not add Chart 1 to Bank Historicals: %s", e)

    # Chart 2: Equity Capital & Retained Earnings Growth
    try:
        chart2 = BarChart()
        chart2.type = "col"
        chart2.style = 11
        chart2.title = f"Book Value of Equity & Capital Retained ({currency})"
        chart2.y_axis.title = f"Amount ({currency})"
        chart2.x_axis.title = "Fiscal Year"
        chart2.width = 18
        chart2.height = 12

        data_eq_ref = Reference(ws, min_col=3, min_row=row_equity, max_col=2 + n_years, max_row=row_equity)
        data_ret_ref = Reference(ws, min_col=3, min_row=row_ret_cap, max_col=2 + n_years, max_row=row_ret_cap)

        s_eq = Series(data_eq_ref, title="Book Value of Equity")
        s_ret = Series(data_ret_ref, title="Tier-1 Capital Retained")
        chart2.series.append(s_eq)
        chart2.series.append(s_ret)
        chart2.set_categories(cats_ref)

        ws.add_chart(chart2, f"{chart_col_letter}24")
    except Exception as e:
        logger.warning("Could not add Chart 2 to Bank Historicals: %s", e)

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=18, max_width=44)
    ws.freeze_panes = "C6"

    # Return key historical cell references (most recent fiscal year) for DDM dynamic linking
    return {
        "net_income_cell": f"'Historical Financials'!{last_col_letter}{row_ni}",
        "book_value_cell": f"'Historical Financials'!{last_col_letter}{row_equity}",
        "shares_cell": f"'Historical Financials'!{last_col_letter}{row_shares}",
        "bvps_cell": f"'Historical Financials'!{last_col_letter}{row_bvps}",
        "roe_cell": f"'Historical Financials'!{last_col_letter}{row_roe}",
    }


def _build_bank_cost_of_equity(wb: Workbook, data: Dict[str, Any]) -> Dict[str, str]:
    ws = wb.create_sheet("Cost of Equity (CAPM)")
    ws.sheet_properties.tabColor = TAB_WACC
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    is_fin = bool(company.get("is_financial", True))
    currency = company.get("currency", "USD")
    macro = data.get("macro", {})
    market_data = data.get("market_data", {})
    wacc_info = data.get("wacc", {})
    overrides = data.get("overrides_applied", {})

    rf = macro.get("risk_free_rate", 0.071 if company.get("market") == "IN" else 0.042)
    market_return = macro.get("market_return", 0.13 if company.get("market") == "IN" else 0.10)
    beta = market_data.get("beta", 1.0)
    dcf = data.get("dcf_result", {})
    eff_term_g = dcf.get("effective_terminal_growth")
    terminal_growth = eff_term_g if eff_term_g is not None else (overrides.get("terminal_growth") if overrides.get("terminal_growth") is not None else macro.get("terminal_growth", 0.050 if company.get("market") == "IN" else 0.025))

    ws["B2"].value = "Cost of Equity (Ke) via Capital Asset Pricing Model (CAPM)"
    ws["B2"].font = FONT_TITLE
    ws["B3"].value = (
        "FIG Capital Structure Assessment — Direct Equity Valuation Framework"
        if is_fin
        else "Corporate Direct Equity Valuation — CAPM Cost of Equity Framework"
    )
    ws["B3"].font = FONT_SUBTITLE
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 18

    # Section 1: Economic Data & Macro Assumptions
    _set_banner(ws, 5, 2, 5, "Economic Data & Macro Assumptions")
    ws.cell(row=6, column=2, value="Reporting Currency").font = FONT_LABEL
    ws.cell(row=6, column=5, value=currency).font = FONT_DATA_BOLD
    for c in range(2, 6):
        ws.cell(row=6, column=c).border = THIN_BORDER

    ws.cell(row=7, column=2, value="Risk Free Rate (Rf)").font = FONT_LABEL
    rf_c = ws.cell(row=7, column=5, value=rf)
    rf_c.font = FONT_DATA_BOLD
    rf_c.number_format = PCT_FMT
    rf_c.alignment = ALIGN_RIGHT
    for c in range(2, 6):
        ws.cell(row=7, column=c).border = THIN_BORDER

    ws.cell(row=8, column=2, value="Long-Term Terminal Growth Rate (g)").font = FONT_LABEL
    tg_c = ws.cell(row=8, column=5, value=terminal_growth)
    tg_c.font = FONT_DATA_BOLD
    tg_c.number_format = PCT_FMT
    tg_c.alignment = ALIGN_RIGHT
    for c in range(2, 6):
        ws.cell(row=8, column=c).border = THIN_BORDER

    # Section 2: Cost of Equity (CAPM)
    _set_banner(ws, 10, 2, 5, "Cost of Equity (CAPM Model)")
    if overrides.get("wacc") is not None:
        ke_formula_or_val = float(overrides["wacc"])
        ke_row_label = "Applied Cost of Equity (Ke — User Override)"
    elif wacc_info.get("ke_floored"):
        ke_formula_or_val = "=MAX(E11+0.015, E11+E12*E14)"
        ke_row_label = "Cost of Equity (Ke = MAX(Rf + 1.5%, Rf + Beta × ERP))"
    else:
        ke_formula_or_val = "=E11+E12*E14"
        ke_row_label = "Cost of Equity (Ke = Rf + Beta × ERP)"

    capm_rows = [
        (11, "Risk Free Rate (Rf)", "=E7", PCT_FMT, False),
        (12, "Beta (Levered Systematic Risk)", beta, NUM_2DEC_FMT, False),
        (13, "Expected Market Return (Rm)", market_return, PCT_FMT, False),
        (14, "Equity Risk Premium (Rm − Rf)", "=E13-E11", PCT_FMT, False),
        (15, ke_row_label, ke_formula_or_val, PCT_FMT, True),
    ]

    for row_num, label, val, fmt, is_bold in capm_rows:
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if row_num % 2 == 0 else None)
        lbl = ws.cell(row=row_num, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER

        val_cell = ws.cell(row_num, column=5, value=val)
        val_cell.font = FONT_TOTAL if is_bold else FONT_DATA_BOLD
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        val_cell.number_format = fmt
        val_cell.alignment = ALIGN_RIGHT
        ws.row_dimensions[row_num].height = 21 if is_bold else 19

    # Section 3: Methodological Note
    _set_banner(
        ws,
        17,
        2,
        5,
        "Why WACC Is Omitted for Financial Institutions"
        if is_fin
        else "Direct Equity Valuation (DDM / FCFE) vs. Enterprise WACC Note",
    )
    ws.merge_cells("B18:E21")
    note_cell = ws["B18"]
    if is_fin:
        note_cell.value = (
            "In commercial banks, NBFCs, and financial institutions, customer deposits and wholesale borrowings "
            "function as operational raw materials (inventory) used to fund earning assets (loans and advances), "
            "rather than capital structure financing. Interest expense is treated as Cost of Goods Sold (COGS). "
            "Consequently, debt cannot be cleanly separated from operating operations, rendering WACC conceptually invalid. "
            "Per Professor Damodaran's methodology, the valuation is conducted directly on an Equity basis using the "
            "Cost of Equity (Ke) to discount Free Cash Flow to Equity (FCFE) and Distributable Dividends."
        )
    else:
        corp_wacc = wacc_info.get("corporate_wacc", wacc_info.get("wacc", 0.10))
        note_cell.value = (
            "In this Corporate DDM / FCFE model, the company is valued directly on an Equity basis rather than an "
            "Enterprise (FCFF) basis. Net Income after taxes and interest is projected forward, and the required "
            "equity reinvestment to sustain growth (Retention Rate b = g / ROE) is deducted to arrive at "
            "Free Cash Flow to Equity (FCFE / Distributable Dividends). Because interest expense has already been "
            f"deducted in arriving at Net Income, cash flows belong exclusively to common shareholders and are discounted "
            f"at the CAPM Cost of Equity (Ke) rather than Enterprise WACC (Reference Corporate WACC: {corp_wacc*100:.2f}%)."
        )
    note_cell.font = FONT_SUBTITLE
    note_cell.alignment = Alignment(wrap_text=True, vertical="top")
    for r_idx in range(18, 22):
        for c_idx in range(2, 6):
            ws.cell(row=r_idx, column=c_idx).border = THIN_BORDER

    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["C"].width = 8
    ws.column_dimensions["D"].width = 8
    ws.column_dimensions["E"].width = 24

    return {
        "ke_cell": "'Cost of Equity (CAPM)'!$E$15",
        "rf_cell": "'Cost of Equity (CAPM)'!$E$7",
        "g_cell": "'Cost of Equity (CAPM)'!$E$8",
    }


def _build_bank_ddm_model(wb: Workbook, data: Dict[str, Any], ke_links: Dict[str, str], hist_links: Optional[Dict[str, str]] = None):
    ws = wb.create_sheet("DDM & FCFE Model")
    ws.sheet_properties.tabColor = TAB_DCF
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    cfmt_large = _get_currency_fmt_large(currency)
    cfmt_price = _get_currency_fmt_price(currency)

    n_proj = len(dcf.get("projected_revenue", [0] * 5))
    growth_schedule = dcf.get("growth_schedule", [0.10] * n_proj)
    roe_schedule = dcf.get("roe_schedule", dcf.get("margin_schedule", [0.14] * n_proj))
    base_net_income = dcf.get("base_net_income", data.get("historicals", {}).get("net_income", [1e9])[-1])
    base_bve = dcf.get("base_bve", data.get("historicals", {}).get("book_value", [5e9])[-1])
    current_price = market_data.get("current_price", 0.0)
    shares_out = market_data.get("shares_outstanding", 1.0)
    bvps = dcf.get("bvps", base_bve / shares_out if shares_out > 0 else 0.0)

    is_fin = bool(company.get("is_financial", True))

    # Title Block
    ws["B2"].value = (
        "Multi-Stage Regulatory Capital FCFE & Dividend Discount Model"
        if is_fin
        else "Multi-Stage Dividend Discount (DDM) & Corporate FCFE Model"
    )
    ws["B2"].font = FONT_TITLE
    ws["B3"].value = (
        f"Per-Share Equity Valuation with Tier-1 Capital Reinvestment — {company.get('ticker', '')}"
        if is_fin
        else f"Direct Equity Cash Flow Valuation & Justified P/B Cross-Check — {company.get('ticker', '')}"
    )
    ws["B3"].font = FONT_SUBTITLE
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 18

    # Table Header
    r = 5
    _set_banner(ws, r, 2, 3 + n_proj, "Forecast Schedules & Free Cash Flow to Equity (FCFE)")
    r += 1

    col_headers = ["Metric / Forecast Line Item", "Base (FY0)"] + [f"Year {i+1}" for i in range(n_proj)]
    _set_table_headers(ws, r, col_headers, start_col=2)
    header_row = r
    r += 1

    # 1. Net Income Growth Rate (Row 7)
    ws.cell(row=r, column=2, value="Net Income Growth Rate (g)").font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).border = THIN_BORDER

    for i in range(n_proj):
        c = ws.cell(row=r, column=4 + i, value=growth_schedule[i])
        c.font = FONT_DATA_BOLD
        c.number_format = PCT_FMT
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    growth_row = r
    r += 1

    # 2. Net Income Projections (Row 8) Live Formula: =Prev_NI * (1 + g)
    ws.cell(row=r, column=2, value="Projected Net Income (Profit After Tax)").font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=2).border = THIN_BORDER

    base_ni_val = (
        f"=IF({hist_links['net_income_cell']}>0, {hist_links['net_income_cell']}, {base_net_income})"
        if hist_links and "net_income_cell" in hist_links
        else base_net_income
    )
    base_ni_cell = ws.cell(row=r, column=3, value=base_ni_val)
    base_ni_cell.font = FONT_DATA_BOLD
    base_ni_cell.fill = HIGHLIGHT_FILL
    base_ni_cell.number_format = cfmt_large
    base_ni_cell.alignment = ALIGN_RIGHT
    base_ni_cell.border = THIN_BORDER

    for i in range(n_proj):
        col = 4 + i
        prev_letter = get_column_letter(col - 1)
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={prev_letter}{r}*(1+{cur_letter}{growth_row})")
        c.font = FONT_TOTAL
        c.fill = HIGHLIGHT_FILL
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    ni_row = r
    r += 1

    # 3. Target ROE Schedule (Row 9)
    ws.cell(row=r, column=2, value="Return on Equity (ROE %)").font = FONT_LABEL
    ws.cell(row=r, column=2).fill = ALT_ROW_FILL
    ws.cell(row=r, column=2).border = THIN_BORDER
    ws.cell(row=r, column=3, value=roe_schedule[0]).number_format = PCT_FMT
    ws.cell(row=r, column=3).font = FONT_DATA
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        c = ws.cell(row=r, column=4 + i, value=roe_schedule[i])
        c.font = FONT_DATA
        c.number_format = PCT_FMT
        c.fill = ALT_ROW_FILL
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    roe_row = r
    r += 1

    # 4. Retention Rate: b = g / ROE (Row 10)
    ws.cell(
        row=r,
        column=2,
        value="Regulatory Capital Retention Rate (b = g / ROE)"
        if is_fin
        else "Equity Retention / Reinvestment Rate (b = g / ROE)",
    ).font = FONT_LABEL
    ws.cell(row=r, column=2).border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).border = THIN_BORDER

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"=MIN(0.95, MAX(0.05, {cur_letter}{growth_row}/{cur_letter}{roe_row}))")
        c.font = FONT_DATA
        c.number_format = PCT_FMT
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    retention_row = r
    r += 1

    # 5. Equity Capital Retained (Row 11) = NI * b
    ws.cell(
        row=r,
        column=2,
        value="(−) Tier-1 Regulatory Capital Retained"
        if is_fin
        else "(−) Retained Earnings Reinvested for Growth",
    ).font = FONT_LABEL
    ws.cell(row=r, column=2).fill = ALT_ROW_FILL
    ws.cell(row=r, column=2).border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL
    ws.cell(row=r, column=3).border = THIN_BORDER

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{ni_row}*{cur_letter}{retention_row}")
        c.font = FONT_DATA
        c.fill = ALT_ROW_FILL
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    reinvest_row = r
    r += 1

    # 6. Free Cash Flow to Equity (FCFE / Distributable Dividends) (Row 12) = NI - Retained
    ws.cell(
        row=r,
        column=2,
        value="Free Cash Flow to Equity (FCFE / Distributable)"
        if is_fin
        else "Free Cash Flow to Equity (FCFE / Distributable Dividends)",
    ).font = FONT_TOTAL
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=2).border = TOTAL_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=3).border = TOTAL_BORDER

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{ni_row}-{cur_letter}{reinvest_row}")
        c.font = FONT_TOTAL
        c.fill = HIGHLIGHT_FILL
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = TOTAL_BORDER
    fcfe_row = r
    r += 1

    # 7. Cumulative Book Value of Equity (Row 13) = Prev_BVE + Reinvested
    ws.cell(row=r, column=2, value="Book Value of Equity (Cumulative)").font = FONT_LABEL
    ws.cell(row=r, column=2).border = THIN_BORDER
    base_bve_val = (
        f"=IF({hist_links['book_value_cell']}>0, {hist_links['book_value_cell']}, {base_bve})"
        if hist_links and "book_value_cell" in hist_links
        else base_bve
    )
    base_bve_cell = ws.cell(row=r, column=3, value=base_bve_val)
    base_bve_cell.font = FONT_DATA
    base_bve_cell.number_format = cfmt_large
    base_bve_cell.alignment = ALIGN_RIGHT
    base_bve_cell.border = THIN_BORDER

    for i in range(n_proj):
        col = 4 + i
        prev_letter = get_column_letter(col - 1)
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={prev_letter}{r}+{cur_letter}{reinvest_row}")
        c.font = FONT_DATA
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    bve_row = r
    r += 1

    # 8. Mid-Year Discount Convention (Row 14)
    ws.cell(row=r, column=2, value="Mid-Year Convention (Years t)").font = FONT_LABEL
    ws.cell(row=r, column=2).fill = ALT_ROW_FILL
    ws.cell(row=r, column=2).border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL
    ws.cell(row=r, column=3).border = THIN_BORDER

    for i in range(n_proj):
        col = 4 + i
        if i == 0:
            c = ws.cell(row=r, column=col, value=0.5)
        else:
            prev_letter = get_column_letter(col - 1)
            c = ws.cell(row=r, column=col, value=f"={prev_letter}{r}+1")
        c.font = FONT_DATA
        c.fill = ALT_ROW_FILL
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    period_row = r
    r += 1

    # 9. Discount Factor (Row 15) = 1 / (1 + Ke)^t
    ws.cell(row=r, column=2, value=f"Discounting Factor (at Ke = {ke_links['ke_cell']})").font = FONT_LABEL
    ws.cell(row=r, column=2).border = THIN_BORDER
    ws.cell(row=r, column=3, value=1.0).number_format = NUM_2DEC_FMT
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT
    ws.cell(row=r, column=3).border = THIN_BORDER

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"=1/(1+{ke_links['ke_cell']})^{cur_letter}{period_row}")
        c.font = FONT_DATA
        c.number_format = "0.0000"
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    df_row = r
    r += 1

    # 10. Present Value of FCFE (Row 16) = FCFE * DF
    ws.cell(row=r, column=2, value="Present Value of FCFE").font = FONT_TOTAL
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=2).border = TOTAL_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=3).border = TOTAL_BORDER

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{fcfe_row}*{cur_letter}{df_row}")
        c.font = FONT_TOTAL
        c.fill = HIGHLIGHT_FILL
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = TOTAL_BORDER
    pv_fcfe_row = r
    r += 1

    # Terminal Value Calculation Section
    r += 1
    _set_banner(ws, r, 2, 5, "Calculation of Terminal Value (Gordon Growth on FCFE)")
    r += 1

    tv_start_row = r
    last_col_letter = get_column_letter(3 + n_proj)

    tv_rows = [
        ("Long-Term Terminal Growth Rate (g)", f"=MIN({ke_links['g_cell']}, {ke_links['ke_cell']}-0.02)", PCT_FMT, False),
        ("Steady-State Terminal ROE", f"={last_col_letter}{roe_row}", PCT_FMT, False),
        ("Terminal Reinvestment Rate (g / ROE)", f"=MIN(0.95, MAX(0.05, D{tv_start_row}/D{tv_start_row+1}))", PCT_FMT, False),
        ("Normalized Terminal Year Net Income", f"={last_col_letter}{ni_row}*(1+D{tv_start_row})", cfmt_large, False),
        ("Normalized Terminal Year FCFE", f"=D{tv_start_row+3}*(1-D{tv_start_row+2})", cfmt_large, False),
        ("Terminal Equity Value at Year N", f"=IF({ke_links['ke_cell']}>D{tv_start_row}, D{tv_start_row+4}/({ke_links['ke_cell']}-D{tv_start_row}), 0)", cfmt_large, True),
        ("Present Value of Terminal Value", f"=D{tv_start_row+5}*{last_col_letter}{df_row}", cfmt_large, True),
    ]

    for label, formula_val, fmt, is_bold in tv_rows:
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if r % 2 == 0 else None)
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_TOTAL if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER

        val_cell = ws.cell(row=r, column=4, value=formula_val)
        val_cell.font = FONT_TOTAL if is_bold else FONT_DATA_BOLD
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        val_cell.number_format = fmt
        val_cell.alignment = ALIGN_RIGHT
        ws.row_dimensions[r].height = 21 if is_bold else 19
        r += 1

    pv_tv_row = r - 1

    # Equity Valuation Summary Section
    r += 1
    _set_banner(ws, r, 2, 5, "Valuation Summary & Implied Fair Value per Share")
    r += 1

    first_col = get_column_letter(4)
    last_col = get_column_letter(3 + n_proj)
    val_start_row = r

    val_summary_rows = [
        ("Cumulative Present Value of 5-Yr FCFEs", f"=SUM({first_col}{pv_fcfe_row}:{last_col}{pv_fcfe_row})", cfmt_large, False),
        ("Present Value of Terminal Equity Value", f"=D{pv_tv_row}", cfmt_large, False),
        ("Total Implied Equity Value", f"=D{val_start_row}+D{val_start_row+1}", cfmt_large, True),
        ("(÷) Diluted Shares Outstanding", shares_out, INT_FMT, False),
        ("Multi-Stage DDM / FCFE Fair Value per Share", f"=MAX(0, D{val_start_row+2}/D{val_start_row+3})", cfmt_price, True),
        ("Current Market Price (CMP)", current_price, cfmt_price, False),
        ("Implied Upside / (Downside)", f"=IF(D{val_start_row+5}>0, (D{val_start_row+4}-D{val_start_row+5})/D{val_start_row+5}, 0)", PCT_FMT, True),
    ]

    for label, val, fmt, is_bold in val_summary_rows:
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if r % 2 == 0 else None)
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_TOTAL if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER

        val_cell = ws.cell(row=r, column=4, value=val)
        val_cell.font = FONT_TOTAL if is_bold else FONT_DATA_BOLD
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        val_cell.number_format = fmt
        val_cell.alignment = ALIGN_RIGHT
        ws.row_dimensions[r].height = 22 if is_bold else 19
        r += 1

    # Cross-Check Section (Justified P/B Model)
    r += 1
    _set_banner(ws, r, 2, 5, "Cross-Check: Justified Price-to-Book (P/B) Model")
    r += 1
    pb_start_row = r

    bvps_formula = f"=IF(D{val_start_row+3}>0, C{bve_row}/D{val_start_row+3}, {bvps})"

    pb_rows = [
        ("Current Book Value per Share (BVPS)", bvps_formula, cfmt_price, False),
        ("Justified P/B Multiplier = (ROE − g) / (Ke − g)", f"=IF({ke_links['ke_cell']}>D{tv_start_row}, MAX(0.2, (D{tv_start_row+1}-D{tv_start_row})/({ke_links['ke_cell']}-D{tv_start_row})), 1.0)", MULT_FMT, True),
        ("Justified P/B Implied Fair Value per Share", f"=D{pb_start_row}*D{pb_start_row+1}", cfmt_price, True),
    ]

    for label, val, fmt, is_bold in pb_rows:
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if r % 2 == 0 else None)
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_TOTAL if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = TOTAL_BORDER if is_bold else THIN_BORDER

        val_cell = ws.cell(row=r, column=4, value=val)
        val_cell.font = FONT_TOTAL if is_bold else FONT_DATA_BOLD
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = TOTAL_BORDER if is_bold else THIN_BORDER
        val_cell.number_format = fmt
        val_cell.alignment = ALIGN_RIGHT
        ws.row_dimensions[r].height = 21 if is_bold else 19
        r += 1

    # ═══════════════════════════════════════════════════════════════════════════
    # NATIVE EXCEL CHARTS ON BANKING DDM MODEL (OpenPyXL)
    # ═══════════════════════════════════════════════════════════════════════════
    chart_col_letter = get_column_letter(4 + n_proj + 1)
    proj_cats_ref = Reference(ws, min_col=4, min_row=header_row, max_col=3 + n_proj, max_row=header_row)

    # Chart 3: Projected FCFE Trajectory
    try:
        chart_fcfe = BarChart()
        chart_fcfe.type = "col"
        chart_fcfe.style = 10
        chart_fcfe.title = f"Projected Free Cash Flow to Equity (FCFE) ({currency})"
        chart_fcfe.y_axis.title = f"FCFE ({currency})"
        chart_fcfe.x_axis.title = "Forecast Period"
        chart_fcfe.width = 18
        chart_fcfe.height = 12

        data_fcfe_ref = Reference(ws, min_col=4, min_row=fcfe_row, max_col=3 + n_proj, max_row=fcfe_row)
        s_fcfe = Series(data_fcfe_ref, title="FCFE (Distributable Cash)")
        chart_fcfe.series.append(s_fcfe)
        chart_fcfe.set_categories(proj_cats_ref)

        ws.add_chart(chart_fcfe, f"{chart_col_letter}4")
    except Exception as e:
        logger.warning("Could not add FCFE chart to Bank DDM Model: %s", e)

    # Chart 4: Projected Net Income & Reinvestment Trajectory
    try:
        chart_ni = BarChart()
        chart_ni.type = "col"
        chart_ni.style = 11
        chart_ni.title = f"Projected Net Income & Regulatory Capital Retained ({currency})"
        chart_ni.y_axis.title = f"Amount ({currency})"
        chart_ni.x_axis.title = "Forecast Period"
        chart_ni.width = 18
        chart_ni.height = 12

        data_ni_proj = Reference(ws, min_col=4, min_row=ni_row, max_col=3 + n_proj, max_row=ni_row)
        data_reinv_proj = Reference(ws, min_col=4, min_row=reinvest_row, max_col=3 + n_proj, max_row=reinvest_row)

        s_ni_proj = Series(data_ni_proj, title="Net Income")
        s_reinv = Series(data_reinv_proj, title="Capital Retained")
        chart_ni.series.append(s_ni_proj)
        chart_ni.series.append(s_reinv)
        chart_ni.set_categories(proj_cats_ref)

        ws.add_chart(chart_ni, f"{chart_col_letter}24")
    except Exception as e:
        logger.warning("Could not add Net Income chart to Bank DDM Model: %s", e)

    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["C"].width = 22
    for c in range(4, 4 + n_proj):
        ws.column_dimensions[get_column_letter(c)].width = 22
    ws.freeze_panes = "C6"


def _build_bank_sensitivity(wb: Workbook, data: Dict[str, Any]):
    ws = wb.create_sheet("Sensitivity")
    ws.sheet_properties.tabColor = TAB_SENS
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    sens = data.get("sensitivity", {})
    cfmt_price = _get_currency_fmt_price(currency)

    # Title Banner
    _set_banner(ws, 2, 2, 8, "Valuation Sensitivity Analysis (2D Scenario Price Matrix)")

    # Reference Values Block
    ws.cell(row=4, column=2, value="Current Share Price:").font = FONT_LABEL_BOLD
    cmp_cell = ws.cell(row=4, column=3, value=market_data.get("current_price", 0))
    cmp_cell.font = FONT_DATA_BOLD
    cmp_cell.number_format = cfmt_price

    ws.cell(row=4, column=5, value="Base DDM Fair Value:").font = FONT_LABEL_BOLD
    dcf_cell = ws.cell(row=4, column=6, value=dcf.get("implied_price", 0))
    dcf_cell.font = FONT_DATA_BOLD
    dcf_cell.number_format = cfmt_price

    r = 6
    _set_banner(ws, r, 2, 7, "Matrix 1: Net Income Growth Rate (Columns) vs Cost of Equity (Rows)")
    r += 1

    grid_data = sens.get("growth_wacc", {})
    ke_range = grid_data.get("wacc_range", [0.08, 0.09, 0.10, 0.11, 0.12])
    g_range = grid_data.get("growth_range", [0.08, 0.09, 0.10, 0.11, 0.12])
    grid = grid_data.get("price_grid") or grid_data.get("grid", [[0]*5]*5)

    # Header Row
    ws.row_dimensions[r].height = 22
    corner_cell = ws.cell(row=r, column=2, value="Cost of Equity (Ke) \\ Growth (g)")
    corner_cell.font = FONT_HEADER
    corner_cell.fill = HEADER_FILL
    corner_cell.alignment = ALIGN_CENTER
    corner_cell.border = THIN_BORDER

    for j, g_val in enumerate(g_range):
        col = 3 + j
        c = ws.cell(row=r, column=col, value=g_val)
        c.font = FONT_HEADER
        c.fill = HEADER_FILL
        c.number_format = PCT_FMT
        c.alignment = ALIGN_CENTER
        c.border = THIN_BORDER
    r += 1

    m1_start_r = r
    for row_idx, ke_val in enumerate(ke_range):
        fill = ALT_ROW_FILL if row_idx % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=ke_val)
        lbl.font = FONT_HEADER
        lbl.fill = HEADER_FILL
        lbl.border = THIN_BORDER
        lbl.number_format = PCT_FMT
        lbl.alignment = ALIGN_CENTER

        for col_idx, g_val in enumerate(g_range):
            val = grid[row_idx][col_idx] if row_idx < len(grid) and col_idx < len(grid[row_idx]) else 0.0
            cell = ws.cell(row=r, column=3 + col_idx, value=val)
            cell.font = FONT_DATA
            cell.fill = fill or PatternFill(fill_type=None)
            cell.border = THIN_BORDER
            cell.number_format = cfmt_price
            cell.alignment = ALIGN_RIGHT
        ws.row_dimensions[r].height = 20
        r += 1

    m1_end_r = r - 1

    # Apply 3-color scale
    color_scale = ColorScaleRule(
        start_type="min", start_color="FCA5A5",  # soft red
        mid_type="percentile", mid_value=50, mid_color="FEF08A",  # soft yellow
        end_type="max", end_color="86EFAC",  # soft green
    )
    last_g_col_letter = get_column_letter(2 + len(g_range))
    ws.conditional_formatting.add(f"C{m1_start_r}:{last_g_col_letter}{m1_end_r}", color_scale)

    # Matrix 2: Target ROE vs Ke
    r += 2
    _set_banner(ws, r, 2, 7, "Matrix 2: Target Return on Equity (ROE) (Columns) vs Cost of Equity (Rows)")
    r += 1

    roe_data = sens.get("margin_wacc", {})
    ke_range2 = roe_data.get("wacc_range", [0.08, 0.09, 0.10, 0.11, 0.12])
    roe_range = roe_data.get("margin_range") or roe_data.get("roe_range", [0.10, 0.12, 0.14, 0.16, 0.18])
    grid2 = roe_data.get("price_grid") or roe_data.get("grid", [[0]*5]*5)

    ws.row_dimensions[r].height = 22
    corner_cell2 = ws.cell(row=r, column=2, value="Cost of Equity (Ke) \\ Target ROE")
    corner_cell2.font = FONT_HEADER
    corner_cell2.fill = HEADER_FILL
    corner_cell2.alignment = ALIGN_CENTER
    corner_cell2.border = THIN_BORDER

    for j, roe_val in enumerate(roe_range):
        col = 3 + j
        c = ws.cell(row=r, column=col, value=roe_val)
        c.font = FONT_HEADER
        c.fill = HEADER_FILL
        c.number_format = PCT_FMT
        c.alignment = ALIGN_CENTER
        c.border = THIN_BORDER
    r += 1

    m2_start_r = r
    for row_idx, ke_val in enumerate(ke_range2):
        fill = ALT_ROW_FILL if row_idx % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=ke_val)
        lbl.font = FONT_HEADER
        lbl.fill = HEADER_FILL
        lbl.border = THIN_BORDER
        lbl.number_format = PCT_FMT
        lbl.alignment = ALIGN_CENTER

        for col_idx, roe_val in enumerate(roe_range):
            val = grid2[row_idx][col_idx] if row_idx < len(grid2) and col_idx < len(grid2[row_idx]) else 0.0
            cell = ws.cell(row=r, column=3 + col_idx, value=val)
            cell.font = FONT_DATA
            cell.fill = fill or PatternFill(fill_type=None)
            cell.border = THIN_BORDER
            cell.number_format = cfmt_price
            cell.alignment = ALIGN_RIGHT
        ws.row_dimensions[r].height = 20
        r += 1

    m2_end_r = r - 1
    last_roe_col_letter = get_column_letter(2 + len(roe_range))
    ws.conditional_formatting.add(f"C{m2_start_r}:{last_roe_col_letter}{m2_end_r}", color_scale)

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=16, max_width=32)
    ws.freeze_panes = "C6"


# ═══════════════════════════════════════════════════════════════════════════
# Built-In Excel Formula Evaluator & XML <v> Cache Populator
# ═══════════════════════════════════════════════════════════════════════════

import re
import zipfile
from xml.sax.saxutils import escape as _xml_escape
from openpyxl.utils.cell import coordinate_to_tuple, column_index_from_string

_TOKEN_RE = re.compile(
    r"""
    (?P<STR>"[^"]*")
  | (?P<SREF>'[^']+'!\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
  | (?P<REF>\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
  | (?P<FUNC>(?:_xlfn\.)?[A-Z][A-Z0-9_.]*(?=\s*\())
  | (?P<NUM>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<OP><=|>=|<>|<|>|=|\+|-|\*|/|\^|&|\(|\)|,)
  | (?P<WS>\s+)
    """,
    re.VERBOSE,
)


def _split_coord(coord_str: str) -> tuple:
    clean = coord_str.replace("$", "")
    r_idx, c_idx = coordinate_to_tuple(clean)
    return c_idx, r_idx


def _evaluate_workbook_formulas(wb: Workbook) -> Dict[tuple, Any]:
    """
    Evaluate all Excel formulas across all worksheets in `wb` in topological
    dependency order and return a mapping `(sheet_title, cell_coord) -> value`.
    """
    sheet_map = {ws.title: ws for ws in wb.worksheets}
    memo: Dict[tuple, Any] = {}
    visiting: set = set()
    range_cache: Dict[tuple, np.ndarray] = {}

    def get_cell_val(sheet_name: str, col_idx: int, row_idx: int) -> Any:
        key = (sheet_name, col_idx, row_idx)
        if key in memo:
            return memo[key]
        if key in visiting:
            return 0.0
        ws = sheet_map.get(sheet_name)
        if ws is None:
            return 0.0
        raw_val = ws.cell(row=row_idx, column=col_idx).value
        if raw_val is None:
            memo[key] = 0.0
            return 0.0
        if isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
            val = float(raw_val)
            memo[key] = val
            return val
        s_val = str(raw_val)
        if not s_val.startswith("="):
            if s_val.strip() == "-":
                memo[key] = 0.0
                return 0.0
            try:
                f_val = float(s_val)
                memo[key] = f_val
                return f_val
            except ValueError:
                memo[key] = s_val
                return s_val

        visiting.add(key)
        try:
            res = eval_formula(sheet_name, s_val[1:])
        except Exception as exc:
            logger.warning("Formula evaluation fallback on %s!%s%d (%s): %s", sheet_name, get_column_letter(col_idx), row_idx, s_val, exc)
            res = 0.0
        visiting.remove(key)
        memo[key] = res
        return res

    def get_range_vals(sheet_name: str, c1: int, r1: int, c2: int, r2: int) -> np.ndarray:
        rkey = (sheet_name, min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2))
        if rkey in range_cache:
            return range_cache[rkey]
        vals = []
        ws = sheet_map.get(sheet_name)
        if ws is not None:
            for rr in range(rkey[2], rkey[4] + 1):
                for cc in range(rkey[1], rkey[3] + 1):
                    raw_c = ws.cell(row=rr, column=cc).value
                    if raw_c is None or (isinstance(raw_c, str) and raw_c.strip() == "-") and not str(raw_c).startswith("="):
                        continue
                    v = get_cell_val(sheet_name, cc, rr)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        vals.append(float(v))
        arr = np.asarray(vals, dtype=float) if vals else np.zeros(0, dtype=float)
        range_cache[rkey] = arr
        return arr

    def _match_criteria(arr: np.ndarray, crit: Any) -> np.ndarray:
        if len(arr) == 0:
            return np.zeros(0, dtype=bool)
        if isinstance(crit, (int, float)):
            return arr == float(crit)
        s = str(crit).strip()
        for op in ("<=", ">=", "<>", "<", ">", "="):
            if s.startswith(op):
                rhs = float(s[len(op):].strip())
                if op == "<=":
                    return arr <= rhs
                if op == ">=":
                    return arr >= rhs
                if op == "<>":
                    return arr != rhs
                if op == "<":
                    return arr < rhs
                if op == ">":
                    return arr > rhs
                return arr == rhs
        try:
            return arr == float(s)
        except ValueError:
            return np.zeros(len(arr), dtype=bool)

    def eval_formula(cur_sheet: str, expr_str: str) -> Any:
        tokens = []
        pos = 0
        while pos < len(expr_str):
            m = _TOKEN_RE.match(expr_str, pos)
            if not m:
                raise ValueError(f"Unrecognized token at pos {pos} in {expr_str!r}")
            kind = m.lastgroup
            text = m.group()
            pos = m.end()
            if kind != "WS":
                tokens.append((kind, text))

        idx = 0

        def peek():
            return tokens[idx] if idx < len(tokens) else (None, None)

        def consume():
            nonlocal idx
            tok = tokens[idx]
            idx += 1
            return tok

        def parse_ref_as_range(kind: str, text: str) -> np.ndarray:
            if kind == "SREF":
                sh_part, ref_part = text.split("!", 1)
                target_sh = sh_part.strip("'")
            else:
                target_sh = cur_sheet
                ref_part = text
            if ":" in ref_part:
                p1, p2 = ref_part.split(":", 1)
                c1, r1 = _split_coord(p1)
                c2, r2 = _split_coord(p2)
                return get_range_vals(target_sh, c1, r1, c2, r2)
            else:
                c1, r1 = _split_coord(ref_part)
                v = get_cell_val(target_sh, c1, r1)
                return np.asarray([float(v)], dtype=float) if isinstance(v, (int, float)) else np.zeros(0, dtype=float)

        def parse_comparison():
            left = parse_concat()
            while peek()[0] == "OP" and peek()[1] in ("<=", ">=", "<>", "<", ">", "="):
                _, op = consume()
                right = parse_concat()
                l_f = float(left) if isinstance(left, (int, float)) else str(left)
                r_f = float(right) if isinstance(right, (int, float)) else str(right)
                if op == "<=":
                    left = l_f <= r_f
                elif op == ">=":
                    left = l_f >= r_f
                elif op == "<>":
                    left = l_f != r_f
                elif op == "<":
                    left = l_f < r_f
                elif op == ">":
                    left = l_f > r_f
                else:
                    left = l_f == r_f
            return left

        def parse_concat():
            left = parse_add()
            while peek()[0] == "OP" and peek()[1] == "&":
                consume()
                right = parse_add()
                left = f"{left}{right}"
            return left

        def parse_add():
            left = parse_mul()
            while peek()[0] == "OP" and peek()[1] in ("+", "-"):
                _, op = consume()
                right = parse_mul()
                l_v = float(left) if isinstance(left, (int, float)) else 0.0
                r_v = float(right) if isinstance(right, (int, float)) else 0.0
                left = (l_v + r_v) if op == "+" else (l_v - r_v)
            return left

        def parse_mul():
            left = parse_power()
            while peek()[0] == "OP" and peek()[1] in ("*", "/"):
                _, op = consume()
                right = parse_power()
                l_v = float(left) if isinstance(left, (int, float)) else 0.0
                r_v = float(right) if isinstance(right, (int, float)) else 0.0
                if op == "*":
                    left = l_v * r_v
                else:
                    if r_v == 0.0:
                        raise ZeroDivisionError("Division by zero")
                    left = l_v / r_v
            return left

        def parse_power():
            left = parse_unary()
            if peek()[0] == "OP" and peek()[1] == "^":
                consume()
                right = parse_power()
                l_v = float(left) if isinstance(left, (int, float)) else 0.0
                r_v = float(right) if isinstance(right, (int, float)) else 0.0
                left = float(l_v ** r_v)
            return left

        def parse_unary():
            if peek()[0] == "OP" and peek()[1] in ("+", "-"):
                _, op = consume()
                val = parse_unary()
                v_f = float(val) if isinstance(val, (int, float)) else 0.0
                return -v_f if op == "-" else v_f
            return parse_primary()

        def parse_primary():
            kind, text = peek()
            if kind == "OP" and text == "(":
                consume()
                val = parse_comparison()
                if peek() == ("OP", ")"):
                    consume()
                return val
            if kind == "NUM":
                consume()
                return float(text)
            if kind == "STR":
                consume()
                return text[1:-1]
            if kind in ("SREF", "REF"):
                consume()
                if kind == "SREF":
                    sh_part, ref_part = text.split("!", 1)
                    target_sh = sh_part.strip("'")
                else:
                    target_sh = cur_sheet
                    ref_part = text
                if ":" in ref_part:
                    p1, p2 = ref_part.split(":", 1)
                    c1, r1 = _split_coord(p1)
                    c2, r2 = _split_coord(p2)
                    return get_range_vals(target_sh, c1, r1, c2, r2)
                c1, r1 = _split_coord(ref_part)
                return get_cell_val(target_sh, c1, r1)
            if kind == "FUNC":
                _, fname = consume()
                fname_u = fname.upper().replace("_XLFN.", "")
                if peek() == ("OP", "("):
                    consume()

                if fname_u == "IF":
                    cond = parse_comparison()
                    if peek() == ("OP", ","):
                        consume()
                    if bool(cond):
                        res = parse_comparison()
                        if peek() == ("OP", ","):
                            consume()
                            # Skip false branch tokens balanced by parens
                            depth = 0
                            while idx < len(tokens):
                                k2, t2 = peek()
                                if k2 == "OP" and t2 == "(":
                                    depth += 1
                                elif k2 == "OP" and t2 == ")":
                                    if depth == 0:
                                        break
                                    depth -= 1
                                consume()
                    else:
                        # Skip true branch tokens
                        depth = 0
                        while idx < len(tokens):
                            k2, t2 = peek()
                            if k2 == "OP" and t2 == "(":
                                depth += 1
                            elif k2 == "OP" and t2 == ")":
                                if depth == 0:
                                    break
                                depth -= 1
                            elif k2 == "OP" and t2 == "," and depth == 0:
                                break
                            consume()
                        if peek() == ("OP", ","):
                            consume()
                        res = parse_comparison()
                    if peek() == ("OP", ")"):
                        consume()
                    return res

                if fname_u == "IFERROR":
                    try:
                        res = parse_comparison()
                        if peek() == ("OP", ","):
                            consume()
                            depth = 0
                            while idx < len(tokens):
                                k2, t2 = peek()
                                if k2 == "OP" and t2 == "(":
                                    depth += 1
                                elif k2 == "OP" and t2 == ")":
                                    if depth == 0:
                                        break
                                    depth -= 1
                                consume()
                    except Exception:
                        # Advance to comma at depth 0
                        depth = 0
                        while idx < len(tokens):
                            k2, t2 = peek()
                            if k2 == "OP" and t2 == "(":
                                depth += 1
                            elif k2 == "OP" and t2 == ")":
                                if depth == 0:
                                    break
                                depth -= 1
                            elif k2 == "OP" and t2 == "," and depth == 0:
                                break
                            consume()
                        if peek() == ("OP", ","):
                            consume()
                        res = parse_comparison()
                    if peek() == ("OP", ")"):
                        consume()
                    return res

                # Standard eager-evaluated arguments
                args = []
                while peek()[0] is not None and peek() != ("OP", ")"):
                    args.append(parse_comparison())
                    if peek() == ("OP", ","):
                        consume()
                if peek() == ("OP", ")"):
                    consume()

                def _flatten_nums(arg_list) -> np.ndarray:
                    out = []
                    for a in arg_list:
                        if isinstance(a, np.ndarray):
                            out.extend(a.tolist())
                        elif isinstance(a, (int, float)) and not isinstance(a, bool):
                            out.append(float(a))
                    return np.asarray(out, dtype=float)

                if fname_u == "SUM":
                    arr = _flatten_nums(args)
                    return float(np.sum(arr)) if len(arr) > 0 else 0.0
                if fname_u == "AVERAGE":
                    arr = _flatten_nums(args)
                    return float(np.mean(arr)) if len(arr) > 0 else 0.0
                if fname_u == "MIN":
                    arr = _flatten_nums(args)
                    return float(np.min(arr)) if len(arr) > 0 else 0.0
                if fname_u == "MAX":
                    arr = _flatten_nums(args)
                    return float(np.max(arr)) if len(arr) > 0 else 0.0
                if fname_u == "MEDIAN":
                    arr = _flatten_nums(args)
                    return float(np.median(arr)) if len(arr) > 0 else 0.0
                if fname_u in ("STDEV.S", "STDEV"):
                    arr = _flatten_nums(args)
                    return float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
                if fname_u in ("PERCENTILE.INC", "PERCENTILE"):
                    arr = _flatten_nums([args[0]]) if args else np.zeros(0)
                    q = float(args[1]) * 100.0 if len(args) > 1 else 50.0
                    return float(np.percentile(arr, q)) if len(arr) > 0 else 0.0
                if fname_u == "COUNT":
                    arr = _flatten_nums(args)
                    return int(len(arr))
                if fname_u == "COUNTIF":
                    arr = _flatten_nums([args[0]]) if args else np.zeros(0)
                    crit = args[1] if len(args) > 1 else 0.0
                    return int(np.sum(_match_criteria(arr, crit)))
                if fname_u == "COUNTIFS":
                    if len(args) < 2:
                        return 0
                    base_arr = _flatten_nums([args[0]])
                    mask = _match_criteria(base_arr, args[1])
                    for k_idx in range(2, len(args) - 1, 2):
                        next_arr = _flatten_nums([args[k_idx]])
                        if len(next_arr) == len(mask):
                            mask = mask & _match_criteria(next_arr, args[k_idx + 1])
                    return int(np.sum(mask))

                return 0.0
            consume()
            return 0.0

        res_val = parse_comparison()
        if isinstance(res_val, np.ndarray):
            return float(res_val[0]) if len(res_val) > 0 else 0.0
        return res_val

    evaluated_by_coord: Dict[tuple, Any] = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
            for cell in row:
                val = cell.value
                if isinstance(val, str) and val.startswith("="):
                    ev = get_cell_val(ws.title, cell.column, cell.row)
                    coord = f"{get_column_letter(cell.column)}{cell.row}"
                    evaluated_by_coord[(ws.title, coord)] = ev
    return evaluated_by_coord


_CELL_FORMULA_XML_RE = re.compile(
    r'<c\s+r="(?P<coord>[A-Z]+\d+)"(?P<attrs>[^>]*)>\s*<f(?P<fattrs>[^>]*)>(?P<formula>.*?)</f>(?:\s*<v>.*?</v>)?\s*</c>',
    re.DOTALL,
)


def _populate_formula_caches(wb: Workbook, raw_buffer: BytesIO) -> BytesIO:
    """
    Evaluate all formulas in `wb` and inject `<v>cached_value</v>` into every
    formula cell in `xl/worksheets/sheet*.xml` inside the `.xlsx` zip archive.
    This guarantees that both `openpyxl.load_workbook(..., data_only=False)` (live formulas)
    and `openpyxl.load_workbook(..., data_only=True)` (cached results) work with zero `None`s.
    """
    evaluated_map = _evaluate_workbook_formulas(wb)
    sheet_titles = [ws.title for ws in wb.worksheets]

    raw_buffer.seek(0)
    out_buffer = BytesIO()
    with zipfile.ZipFile(raw_buffer, "r") as zin, zipfile.ZipFile(out_buffer, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data_bytes = zin.read(item.filename)
            m_sheet = re.match(r"^xl/worksheets/sheet(\d+)\.xml$", item.filename)
            if m_sheet:
                s_idx = int(m_sheet.group(1)) - 1
                if 0 <= s_idx < len(sheet_titles):
                    sh_title = sheet_titles[s_idx]
                    xml_str = data_bytes.decode("utf-8")

                    def _replace_cell(m: re.Match) -> str:
                        coord = m.group("coord")
                        attrs = m.group("attrs")
                        fattrs = m.group("fattrs")
                        formula = m.group("formula")
                        val = evaluated_map.get((sh_title, coord), 0.0)
                        if isinstance(val, (int, float)) and not isinstance(val, bool):
                            clean_attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
                            v_str = str(int(val)) if isinstance(val, int) else f"{float(val):.12g}"
                            return f'<c r="{coord}"{clean_attrs}><f{fattrs}>{formula}</f><v>{v_str}</v></c>'
                        else:
                            clean_attrs = re.sub(r'\s+t="[^"]*"', "", attrs) + ' t="str"'
                            v_str = _xml_escape(str(val))
                            return f'<c r="{coord}"{clean_attrs}><f{fattrs}>{formula}</f><v>{v_str}</v></c>'

                    xml_str = _CELL_FORMULA_XML_RE.sub(_replace_cell, xml_str)
                    data_bytes = xml_str.encode("utf-8")
            zout.writestr(item, data_bytes)

    out_buffer.seek(0)
    return out_buffer


# ═══════════════════════════════════════════════════════════════════════════
# Public API Entrypoint
# ═══════════════════════════════════════════════════════════════════════════

def generate_excel_report(analysis_data: Dict[str, Any]) -> BytesIO:
    """
    Generate a professional Damodaran-grade Excel workbook (.xlsx)
    from the valuation analysis data.

    Supports dual routing:
      - Non-Financials: Multi-Stage FCFF & WACC (Matching HUL FINAL MODEL.xlsx)
      - Financial Institutions (Banks/NBFCs): Multi-Stage FCFE & Regulatory Capital Model

    Returns
    -------
    BytesIO
        In-memory buffer containing the complete .xlsx workbook with both live
        Excel formulas AND pre-populated XML <v> formula caches.
    """
    wb = Workbook()

    try:
        is_financial = (
            analysis_data.get("company", {}).get("is_financial", False)
            or analysis_data.get("diagnostics", {}).get("is_financial", False)
            or analysis_data.get("dcf_result", {}).get("is_financial", False)
        )
        model_type = (
            analysis_data.get("company", {}).get("model_type")
            or analysis_data.get("diagnostics", {}).get("model_type")
            or analysis_data.get("dcf_result", {}).get("model_type")
            or ("BANKING_DDM" if is_financial else "STANDARD_FCFF")
        )

        if is_financial or model_type == "BANKING_DDM":
            logger.info("Generating dedicated Financial Services (Bank/NBFC) Excel Workbook")
            _build_bank_cover(wb, analysis_data)
            hist_links = _build_bank_historicals(wb, analysis_data)
            ke_links = _build_bank_cost_of_equity(wb, analysis_data)
            _build_bank_ddm_model(wb, analysis_data, ke_links, hist_links)
            _build_bank_sensitivity(wb, analysis_data)
            _build_monte_carlo(wb, analysis_data)
        elif model_type == "CORPORATE_DDM":
            logger.info("Generating customized Corporate DDM / FCFE Excel Workbook")
            _build_bank_cover(wb, analysis_data)
            hist_links = _build_historicals(wb, analysis_data)
            ke_links = _build_bank_cost_of_equity(wb, analysis_data)
            _build_bank_ddm_model(wb, analysis_data, ke_links, hist_links if isinstance(hist_links, dict) else None)
            _build_bank_sensitivity(wb, analysis_data)
            _build_monte_carlo(wb, analysis_data)
        else:
            # Ensure Cover is the first sheet, then build dependent sheets and link Cover formulas
            ws_cover = wb.active
            ws_cover.title = "Cover"
            hist_links = _build_historicals(wb, analysis_data)
            wacc_links = _build_wacc2(wb, analysis_data, hist_links if isinstance(hist_links, dict) else None)
            dcf_links = _build_dcf_model(wb, analysis_data, wacc_links, hist_links)
            _build_sensitivity(wb, analysis_data, dcf_links)
            mc_links = _build_monte_carlo(wb, analysis_data, dcf_links)
            _build_cover(wb, analysis_data, hist_links, wacc_links, dcf_links, mc_links)
    except Exception:
        logger.exception("Error building Excel valuation workbook")
        raise

    # Ensure all worksheets have clean print areas
    for ws in wb.worksheets:
        max_r = ws.max_row or 1
        max_c = ws.max_column or 1
        ws.print_area = f"A1:{get_column_letter(max_c)}{max_r}"

    raw_buffer = BytesIO()
    wb.save(raw_buffer)
    return _populate_formula_caches(wb, raw_buffer)
