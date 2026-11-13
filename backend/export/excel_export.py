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
import math
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
PASS_FILL = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
WARN_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
BLOCKED_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")

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


def _format_accounting_standard(raw_std: Any, market: Any = "US") -> str:
    """Format accounting standard identifiers into clean display labels."""
    raw = str(raw_std or ("IND_AS" if str(market or "").upper() == "IN" else "US_GAAP"))
    return {"IND_AS": "Ind AS", "US_GAAP": "US GAAP", "IFRS": "IFRS"}.get(
        raw.upper(), raw.replace("_", " ").title()
    )


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
    ws.merge_cells(f"B2:E2")
    ws.merge_cells(f"B3:E3")
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 18

    acct_std_label = _format_accounting_standard(
        data.get("accounting_standard") or company.get("accounting_standard"),
        company.get("market", "US"),
    )
    sector_prof = data.get("sector_driver_profile") or company.get("sector_driver_profile") or ((data.get("model_suitability") or {}).get("driver_profile")) or {}

    # Section 1: Company Profile
    r = 5
    _set_banner(ws, r, 2, 5, "Company Profile & Market Metadata")
    r += 1

    dil_shares_cover = float(dcf.get("shares_used") or market_data.get("diluted_valuation_shares") or market_data.get("shares_outstanding") or 0)

    profile_items = [
        ("Company Name", company.get("name")),
        ("Ticker Symbol", company.get("ticker")),
        ("Exchange Market", company.get("market")),
        ("Sector", str(company.get("sector") or sector_prof.get("label") or "Corporate")),
        ("Reporting Currency", currency),
        ("Accounting Standard", acct_std_label),
        ("Valuation Date", datetime.now().strftime("%d-%b-%Y")),
        ("Diluted Shares Outstanding", dil_shares_cover, INT_FMT),
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

    # Verdict Description box
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

    # Non-additive EV Cash Bridge (separating restricted/earmarked balances from Gross Cash & STI)
    cash_recon = data.get("cash_reconciliation") or historicals.get("cash_reconciliation") or {}
    bs_tot_cash_last = float(raw_tot_cash[-1]) if raw_tot_cash else 0.0
    ev_cash_target = float(
        historicals.get("cash_and_equivalents")
        or cash_recon.get("unrestricted_cash")
        or wacc_data.get("total_cash")
        or 0.0
    )
    gross_ev_cash = float(cash_recon.get("gross_cash_and_sti") or bs_tot_cash_last or 0.0)
    restr_ev_val = float(
        historicals.get("restricted_cash")
        or cash_recon.get("restricted_earmarked_cash")
        or (bs_stmt.get("Restricted Cash Excluded from EV", [0.0])[-1] if bs_stmt.get("Restricted Cash Excluded from EV") else 0.0)
        or 0.0
    )
    if restr_ev_val <= 0.0 and gross_ev_cash > ev_cash_target + 0.01:
        restr_ev_val = gross_ev_cash - ev_cash_target
    raw_gross_ev = raw_tot_cash[:-1] + [gross_ev_cash] if n_years > 0 else []
    row_ev_gross = _write_statement_row(
        "Non-Additive Memo: Reconciled Gross Cash & STI Base (per Note)",
        raw_gross_ev,
        cfmt_large,
        formula_sum=[row_tot_cash] if (n_years > 0 and abs(gross_ev_cash - bs_tot_cash_last) < 0.01) else None,
    )
    raw_restr_ev = [0.0] * max(n_years - 1, 0) + ([restr_ev_val] if n_years > 0 else [])
    row_restr_ev = _write_statement_row(
        "Non-Additive Memo: Less Restricted / Earmarked Cash Excluded from EV Bridge",
        raw_restr_ev,
        cfmt_large,
    )
    row_ev_cash = _write_statement_row(
        "Non-Additive Memo: EV-Eligible Unrestricted Cash & Marketable Securities",
        raw_tot_cash[:-1] + [ev_cash_target] if n_years > 0 else [],
        cfmt_large,
        is_bold=True,
        formula_subtraction=(row_ev_gross, row_restr_ev),
    )

    # Determine latest column coordinate for DCF model linking
    latest_cash_col_letter = get_column_letter(2 + n_years)
    avg_col_letter = get_column_letter(3 + n_years)
    cash_cell_coord = f"'Historical Financials'!{latest_cash_col_letter}{row_ev_cash}"

    # ═══════════════════════════════════════════════════════════════════════════
    # PART III: CASH FLOW STATEMENT & FCFF RECONCILIATION
    # ═══════════════════════════════════════════════════════════════════════════
    r += 1
    _write_sub_banner("Part III: Cash Flow Statement & Unlevered FCFF Schedule")

    raw_cfo_ni = cf_stmt.get("CFO Starting Profit (Net Income / PBT)") or cf_stmt.get("Net Profit from Operations") or historicals.get("net_income", [])
    row_cfo_ni = _write_statement_row("Operating Activities: Starting Profit (Net Income / PBT)", raw_cfo_ni, cfmt_large)

    raw_cfo_dna = cf_stmt.get("Depreciation & Amortization") or cf_stmt.get("Depreciation & Amortization (Reported CF Gross)") or historicals.get("dna", [])
    row_cfo_dna = _write_statement_row("Add: Depreciation & Amortization (Normalized Symmetric with IS)", raw_cfo_dna, cfmt_large)

    raw_cfo_sbc = cf_stmt.get("Stock-Based Compensation (SBC)", [0.0] * n_years)
    row_cfo_sbc = _write_statement_row("Add: Stock-Based Compensation (SBC)", raw_cfo_sbc, cfmt_large)

    raw_cfo_deftax = cf_stmt.get("Deferred Income Taxes", [0.0] * n_years)
    row_cfo_deftax = _write_statement_row("Deferred Income Taxes", raw_cfo_deftax, cfmt_large)

    raw_cfo_wc = cf_stmt.get("Change in Working Capital", [0.0] * n_years)
    row_cfo_wc = _write_statement_row("Working Capital Changes (Cash Flow Statement)", raw_cfo_wc, cfmt_large)

    raw_cfo_tax = (
        cf_stmt.get("Direct Taxes Paid (In CFO Reconciliation)")
        if cf_stmt.get("Direct Taxes Paid (In CFO Reconciliation)") is not None
        else cf_stmt.get("Direct Taxes Paid", [0.0] * n_years)
    )
    row_cfo_tax = _write_statement_row("Direct Taxes Paid / Refunds (In CFO Reconciliation)", raw_cfo_tax, cfmt_large)

    raw_cfo = cf_stmt.get("Cash Flow from Operating Activities (CFO)", [0.0] * n_years)
    raw_cfo_other = (
        cf_stmt.get("Other Non-Cash & Operating Adjustments (Reconciling Item)")
        if cf_stmt.get("Other Non-Cash & Operating Adjustments (Reconciling Item)") is not None
        else cf_stmt.get("Other Non-Cash & Operating Adjustments")
    )
    if raw_cfo_other is None:
        _at_cf = lambda seq, idx: float(seq[idx]) if seq and idx < len(seq) and seq[idx] is not None else 0.0
        raw_cfo_other = [
            float(_at_cf(raw_cfo, i) - (_at_cf(raw_cfo_ni, i) + _at_cf(raw_cfo_dna, i) + _at_cf(raw_cfo_sbc, i) + _at_cf(raw_cfo_deftax, i) + _at_cf(raw_cfo_wc, i) + _at_cf(raw_cfo_tax, i)))
            if i < len(raw_cfo) else 0.0
            for i in range(n_years)
        ]
    row_cfo_other = _write_statement_row("Other Non-Cash & Operating Adjustments (Reconciling Item)", raw_cfo_other, cfmt_large)

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
    raw_fx_roll = cf_stmt.get("Effect of Exchange Rate Changes (FX)", [0.0] * n_years)
    raw_beg_cash_rep = cf_stmt.get("Beginning Cash Position")
    if raw_beg_cash_rep and len(raw_beg_cash_rep) == n_years and any(abs(float(x or 0)) > 0 for x in raw_beg_cash_rep):
        raw_beg_cash = [float(x or 0.0) for x in raw_beg_cash_rep]
    else:
        raw_beg_cash = [
            float(raw_end_cash[i] - raw_net_cf[i] - (raw_fx_roll[i] if i < len(raw_fx_roll) else 0.0))
            if i < len(raw_end_cash) and i < len(raw_net_cf) else 0.0
            for i in range(n_years)
        ]
    row_beg_cash = _write_statement_row("Beginning Cash Position (Incl. Restricted Cash)", raw_beg_cash, cfmt_large)
    row_fx_roll = _write_statement_row("Effect of Exchange Rate Changes on Cash (FX)", raw_fx_roll, cfmt_large)

    row_end_cash = _write_statement_row(
        "Ending Cash Position",
        raw_end_cash,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_beg_cash, row_net_cf, row_fx_roll],
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

    # Supplemental Cash Flow & Statutory Reconciling Memos (Non-Additive)
    raw_cf_rep_dna = cf_stmt.get("Depreciation & Amortization (Reported CF Gross)", raw_cfo_dna)
    raw_recoup_da = cf_stmt.get("Recoupment / Capitalised Depreciation Adjustment (Note 46)", [0.0] * n_years)
    raw_rep_capex = cf_stmt.get("Fixed Assets Purchased (Reported CapEx)", raw_capex)
    raw_supp_cash_tax = cf_stmt.get("Supplemental: Income Taxes Paid (Cash, Non-Additive)", [0.0] * n_years)
    if any(raw_recoup_da) or any(raw_supp_cash_tax) or raw_rep_capex != raw_capex:
        r += 1
        _write_statement_row(
            "Supplemental Memo: Reported Cash Flow Gross D&A (Before Note 46 Recoupment)",
            raw_cf_rep_dna,
            cfmt_large,
        )
        _write_statement_row(
            "Supplemental Memo: Less Recoupment / Capitalised D&A (Note 46)",
            raw_recoup_da,
            cfmt_large,
        )
        _write_statement_row(
            "Supplemental Memo: Reported Gross CapEx (Incl. CWIP / Advances)",
            raw_rep_capex,
            cfmt_large,
        )
        _write_statement_row(
            "Supplemental Memo: Cash Income Taxes Paid (IAS 7 / Ind AS 7 Disclosure)",
            raw_supp_cash_tax,
            cfmt_large,
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
    # PART V: STATUTORY DISCLOSURES, COMMITMENTS, LEASE POLICY & TSM SHARE BRIDGE
    # ═══════════════════════════════════════════════════════════════════════════
    r += 1
    _write_sub_banner("Part V: Statutory Disclosures, Commitments, Lease Policy & TSM Share Bridge")

    lease_pol = data.get("lease_policy") or historicals.get("lease_policy") or {}
    share_recon = data.get("share_reconciliation") or historicals.get("share_reconciliation") or {}
    cap_comm_val = historicals.get("capital_commitments")
    cap_adv_val = historicals.get("capital_advances")

    if cap_comm_val is not None:
        _write_statement_row(
            "Contracted Capital Commitments (Note 32c — Off-BS Disclosure)",
            [0.0] * max(n_years - 1, 0) + ([float(cap_comm_val)] if n_years > 0 else []),
            cfmt_large,
        )
    if cap_adv_val is not None:
        _write_statement_row(
            "Capital Advances Outstanding (Note 11)",
            [0.0] * max(n_years - 1, 0) + ([float(cap_adv_val)] if n_years > 0 else []),
            cfmt_large,
        )

    basic_pe_sh = float(share_recon.get("basic_period_end_shares") or (raw_pe_shares[-1] if raw_pe_shares else 0.0) or 0.0)
    rsu_unvested_sh = float(share_recon.get("unvested_rsu_shares") or 0.0)
    opt_gross_sh = float(share_recon.get("option_gross_shares") or 0.0)
    tsm_repurch_sh = float(share_recon.get("tsm_treasury_repurchase_shares") or 0.0)
    tsm_inc_opt_sh = float(share_recon.get("tsm_incremental_option_shares") or max(0.0, opt_gross_sh - tsm_repurch_sh))
    val_dil_target = float(
        share_recon.get("diluted_valuation_shares")
        or data.get("dcf_result", {}).get("shares_used")
        or data.get("market_data", {}).get("diluted_valuation_shares")
        or (raw_pe_shares[-1] if raw_pe_shares else 0.0)
        or (raw_shares[-1] if raw_shares else 0.0)
    )

    row_tsm_pe = _write_statement_row(
        "TSM Bridge: Period-End Basic Common Shares Outstanding",
        [0.0] * max(n_years - 1, 0) + ([basic_pe_sh] if n_years > 0 else []),
        INT_FMT,
    )
    row_tsm_rsu = _write_statement_row(
        "TSM Bridge: (+) Unvested RSUs / PSUs Included in Valuation Dilution",
        [0.0] * max(n_years - 1, 0) + ([rsu_unvested_sh] if n_years > 0 else []),
        INT_FMT,
    )
    row_tsm_opt = _write_statement_row(
        "TSM Bridge: (+) TSM Incremental In-the-Money Option Shares",
        [0.0] * max(n_years - 1, 0) + ([tsm_inc_opt_sh] if n_years > 0 else []),
        INT_FMT,
    )
    row_val_shares = _write_statement_row(
        "TSM Bridge: Total Diluted Shares for DCF Per-Share Valuation",
        [0.0] * max(n_years - 1, 0) + ([val_dil_target] if n_years > 0 else []),
        INT_FMT,
        is_bold=True,
        formula_sum=[row_tsm_pe, row_tsm_rsu, row_tsm_opt] if abs((basic_pe_sh + rsu_unvested_sh + tsm_inc_opt_sh) - val_dil_target) <= max(1.0, val_dil_target * 1e-4) else None,
    )

    # Textual policy disclosures (Accounting standard, Lease policy, Cash policy)
    hist_acct_std = _format_accounting_standard(
        historicals.get("accounting_standard") or data.get("accounting_standard"),
        company.get("market", "US"),
    )
    for pol_lbl, pol_txt in [
        ("Accounting Standard & Jurisdiction", f"{hist_acct_std} | Market: {company.get('market', 'US')}"),
        ("Lease & EV Bridge Policy", str(lease_pol.get("treatment") or lease_pol.get("note") or "Debt-inclusive EV bridge consistent with WACC capital weights")),
        ("Cash Bridge Classification Note", f"{cash_recon.get('source', 'Balance Sheet')} ({cash_recon.get('note_ref', 'Note')})"),
    ]:
        ws.cell(row=r, column=2, value=pol_lbl).font = FONT_LABEL_BOLD
        ws.cell(row=r, column=2).border = THIN_BORDER
        pol_c = ws.cell(row=r, column=3, value=pol_txt)
        pol_c.font = FONT_DATA
        pol_c.alignment = ALIGN_LEFT
        for cc in range(3, 4 + n_years):
            ws.cell(row=r, column=cc).border = THIN_BORDER
        ws.row_dimensions[r].height = 18
        r += 1

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
        "eq_bv_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_equity}",
        "intang_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_intang}",
        "shares_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_shares}",
        "val_shares_cell": f"'Historical Financials'!{latest_cash_col_letter}{row_val_shares}",
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
    tax_rate_dcf = float(dcf.get("tax_rate", macro.get("tax_rate", 0.2517 if company.get("market") == "IN" else 0.21)) or 0.21)

    avg_dna_pct = float(historicals.get("avg_dna_pct", 0.02) or 0.02)
    avg_capex_pct = float(historicals.get("avg_capex_pct", 0.03) or 0.03)
    norm_nwc_pct = float(dcf.get("normalized_nwc_to_revenue", historicals.get("normalized_nwc_to_revenue", historicals.get("avg_dnwc_pct", 0.01))) or 0.0)
    last_revenue = float(historicals.get("last_revenue") or (historicals.get("revenue", [-1])[-1] if historicals.get("revenue") else (proj_rev[0] / (1 + growth_schedule[0]) if proj_rev else 1e9)) or 1.0)
    effective_dna_pct = float(
        dcf.get("effective_dna_pct")
        or (min(avg_dna_pct, max(avg_capex_pct * 1.05, 0.025)) if avg_dna_pct > avg_capex_pct * 1.15 else avg_dna_pct)
    )
    start_growth_val = float(growth_schedule[0]) if growth_schedule else 0.05
    raw_term_g_val = float(dcf.get("terminal_growth", macro.get("terminal_growth", 0.050 if company.get("market") == "IN" else 0.025)) or 0.025)
    fade_exp_val = float(dcf.get("growth_fade_exponent", 1.0) or 1.0)
    is_extractive_flag = bool(dcf.get("is_extractive", company.get("is_extractive", False)))
    is_cyclical_flag = bool(dcf.get("is_cyclical", company.get("is_cyclical", False)))
    is_india_flag = (company.get("market") == "IN")
    use_mid_year_flag = bool(dcf.get("use_mid_year", True))

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

    # Reserve exact row coordinates for Projection Fade Driver parameters written below TV bridge
    growth_row = r
    rev_row = r + 1
    margin_row = r + 2
    ebit_row = r + 3
    tax_row = r + 4
    nopat_row = r + 5
    dna_row = r + 6
    capex_row = r + 7
    dnwc_row = r + 8
    fcff_row = r + 9
    period_row = r + 10
    df_row = r + 11
    pv_fcff_row = r + 12

    # 1. Revenue Growth Rate (Formula-driven smooth fade when horizon > 1)
    lbl1 = ws.cell(row=r, column=2, value="YoY Revenue Growth Rate")
    lbl1.font = FONT_LABEL_BOLD
    lbl1.fill = ALT_ROW_FILL
    lbl1.border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL

    # Driver block sits right below DCF bridge; compute exact row offsets deterministically
    # Pre-declare fade exponent cell coordinate referenced in growth formulas (populated in Calibration block)
    # Using fixed-offset section tracking: we write exact row number after TV & Bridge rows are laid out
    #Wait: we know exact row count from period_row -> tv_row -> bridge -> calibration, so track placeholders and populate values cleanly after laying out rows!
    for i in range(n_proj):
        c = ws.cell(row=r, column=4 + i, value=float(growth_schedule[i]))
        c.font = FONT_DATA_BOLD
        c.number_format = PCT_FMT
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
        c.fill = ALT_ROW_FILL
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

    # 11. Discounting Period Convention (Mid-Year t = 0.5, 1.5, ... or Year-End t = 1.0, 2.0, ...)
    lbl11 = ws.cell(row=r, column=2, value="Mid-Year Convention (Years t)" if use_mid_year_flag else "End-of-Year Convention (Years t)")
    lbl11.font = FONT_LABEL
    lbl11.border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).border = THIN_BORDER

    first_t = 0.5 if use_mid_year_flag else 1.0
    for i in range(n_proj):
        col = 4 + i
        if i == 0:
            c = ws.cell(row=r, column=col, value=first_t)
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

    # Section: Terminal Value Calculation (4-row HUL layout; g/RONIC drivers linked below)
    _set_banner(ws, r, 2, 5, "Calculation of Terminal Value")
    r += 1

    last_col_letter = get_column_letter(3 + n_proj)
    term_g_ref = wacc_links["terminal_g_cell"]
    wacc_ref = wacc_links["wacc_cell"]

    # 1. FCFF (n+1) (placeholder formula wired after supporting reinvestment schedule below)
    n1_row = r
    ws.cell(row=r, column=2, value="FCFF (n+1)").font = FONT_LABEL
    n1_cell = ws.cell(row=r, column=4)
    n1_cell.font = FONT_DATA_BOLD
    n1_cell.number_format = cfmt_large
    n1_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    r += 1

    # 2. Cost of Capital (WACC)
    wacc_param_row = r
    ws.cell(row=r, column=2, value="WACC").font = FONT_LABEL
    wacc_cell = ws.cell(row=r, column=4, value=f"={wacc_ref}")
    wacc_cell.font = FONT_DATA_BOLD
    wacc_cell.number_format = PCT_FMT
    wacc_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    r += 1

    # 3. Terminal Growth Rate (g)
    tg_row = r
    ws.cell(row=r, column=2, value="Terminal Growth Rate (g)").font = FONT_LABEL
    tg_cell = ws.cell(row=r, column=4, value=f"=MIN({term_g_ref}, D{wacc_param_row}-0.025)")
    tg_cell.font = FONT_DATA_BOLD
    tg_cell.number_format = PCT_FMT
    tg_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    r += 1

    # 4. Terminal Value (placeholder formula wired after supporting reinvestment & exit check)
    tv_row = r
    ws.cell(row=r, column=2, value="Terminal Value").font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    tv_cell = ws.cell(row=r, column=4)
    tv_cell.font = FONT_TOTAL
    tv_cell.number_format = cfmt_large
    tv_cell.alignment = ALIGN_RIGHT
    tv_cell.fill = HIGHLIGHT_FILL
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = TOTAL_BORDER
    r += 2

    eff_term_g = float(dcf.get("effective_terminal_growth", 0.025) or 0.025)
    sust_roic = float(dcf.get("sustainable_roic", 0.15) or 0.15)
    min_reinv_floor = float(dcf.get("min_reinv_floor", 0.06 if bool(dcf.get("is_high_roic", False)) else 0.10) or 0.10)
    is_high_roic_flag = bool(dcf.get("is_high_roic", False))
    capex_floor_abs = float(dcf.get("capex_floor_abs") or 0.0)
    raw_exit_mult = dcf.get("benchmark_exit_multiple")
    if raw_exit_mult is None:
        raw_exit_mult = dcf.get("benchmark_exit_mult")
    benchmark_exit_mult = float(raw_exit_mult if raw_exit_mult is not None else 10.0)

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

    # 8. Shares Outstanding (TSM Valuation Diluted Shares)
    val_shares_cnt = float(
        dcf.get("shares_used")
        or market_data.get("diluted_valuation_shares")
        or market_data.get("shares_outstanding", 1)
        or 1
    )
    shares_formula_or_val = f"={hist_refs['val_shares_cell']}" if hist_refs.get("val_shares_cell") else val_shares_cnt
    ws.cell(row=r, column=2, value="(÷) Diluted Valuation Shares (TSM Bridge)").font = FONT_LABEL
    ws.cell(row=r, column=4, value=shares_formula_or_val).font = FONT_DATA
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

    # 12. Verdict
    ws.cell(row=r, column=2, value="Valuation Outlook").font = FONT_LABEL_BOLD
    v_cell = ws.cell(row=r, column=4, value=verdict.get("verdict", "NEUTRAL"))
    v_cell.font = FONT_LABEL_BOLD
    v_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = TOTAL_BORDER

    # Section: Projection Fade Calibration Drivers & Live Growth Formula Wiring
    r += 2
    _set_banner(ws, r, 2, 5, "Continuous Revenue Growth Fade Calibration Drivers")
    r += 1

    start_g_driver_row = r
    ws.cell(row=r, column=2, value="Year 1 Starting Revenue Growth Rate").font = FONT_LABEL
    cg1 = ws.cell(row=r, column=4, value=start_growth_val)
    cg1.font = FONT_DATA_BOLD
    cg1.number_format = PCT_FMT
    cg1.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    r += 1

    fade_target_g_driver_row = r
    ws.cell(row=r, column=2, value="Fade Horizon Target Terminal Growth (g)").font = FONT_LABEL
    cg2 = ws.cell(row=r, column=4, value=raw_term_g_val)
    cg2.font = FONT_DATA
    cg2.number_format = PCT_FMT
    cg2.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    r += 1

    fade_exp_driver_row = r
    ws.cell(row=r, column=2, value="Continuous Growth Fade Exponent").font = FONT_LABEL
    if not is_extractive_flag and not is_cyclical_flag:
        fade_exp_formula = f"=1+0.35*MIN(1, MAX(0, (D{start_g_driver_row}-D{fade_target_g_driver_row}-0.05)/0.10))"
    else:
        fade_exp_formula = 1.0
    cg3 = ws.cell(row=r, column=4, value=fade_exp_formula)
    cg3.font = FONT_DATA_BOLD
    cg3.number_format = NUM_2DEC_FMT
    cg3.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    r += 1

    # Wire live continuous fade formulas into growth_row columns D..{last_col_letter}
    for i in range(n_proj):
        c = ws.cell(row=growth_row, column=4 + i)
        if i == 0:
            c.value = f"=D{start_g_driver_row}"
        else:
            step_den = max(1, n_proj - 1)
            c.value = (
                f"=D{start_g_driver_row}-(D{start_g_driver_row}-D{fade_target_g_driver_row})"
                f"*(({i}/{step_den})^D{fade_exp_driver_row})"
            )

    # Section: Terminal Value Reinvestment Drivers (Supporting Schedule for 4-row TV block)
    r += 1
    _set_banner(ws, r, 2, 5, "Terminal Value Reinvestment Drivers (Supporting Schedule)")
    r += 1

    ws.cell(row=r, column=2, value="Terminal Year NOPAT (Year N+1)").font = FONT_LABEL
    term_nopat_cell = ws.cell(row=r, column=4, value=f"={last_col_letter}{nopat_row}*(1+D{tg_row})")
    term_nopat_cell.font = FONT_DATA_BOLD
    term_nopat_cell.number_format = cfmt_large
    term_nopat_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    term_nopat_row = r
    r += 1

    ws.cell(row=r, column=2, value="Steady-State Return on New Invested Capital (RONIC)").font = FONT_LABEL
    if dcf.get("tangible_ic") is not None and float(dcf.get("tangible_ic") or 0.0) > 0.0:
        tangible_ic_val = float(dcf["tangible_ic"])
        hist_roic_val = float(dcf.get("hist_roic", 0.0) or 0.0)
        avg_gm_val = float(historicals.get("avg_gross_margin", 0.0) or 0.0)
        ext_int = 1 if is_extractive_flag else 0
        cyc_int = 1 if is_cyclical_flag else 0
        has_cur_m = dcf.get("current_margin") is not None
        min_r_add = 0.045 if (not is_extractive_flag and not is_cyclical_flag and avg_capex_pct > effective_dna_pct * 2.20) else 0.0
        yrN_tic_expr = f"({tangible_ic_val:.6f}*MAX(1, IF({last_revenue:.6f}>0, {last_col_letter}{rev_row}/{last_revenue:.6f}, 1)))"
        proj_roic_expr = f"IF(AND({yrN_tic_expr}>0, {last_col_letter}{nopat_row}>0), {last_col_letter}{nopat_row}/{yrN_tic_expr}, D{wacc_param_row})"
        eff_roic_expr = (
            f"IF({hist_roic_val:.10f}<=0.02, MAX({hist_roic_val:.10f}, {proj_roic_expr}), 0.5*{hist_roic_val:.10f}+0.5*({proj_roic_expr}))"
            if has_cur_m
            else f"IF({hist_roic_val:.10f}<=0.02, MAX({hist_roic_val:.10f}, {proj_roic_expr}), {hist_roic_val:.10f})"
        )
        is_hi_expr = f"AND({ext_int}=0, {cyc_int}=0, ({eff_roic_expr})>=0.22, OR({avg_gm_val:.6f}>=0.45, ({eff_roic_expr})>=0.28))"
        roic_formula = f"=MAX(D{wacc_param_row}+{min_r_add:.6f}, MIN({eff_roic_expr}, IF({is_hi_expr}, 0.45, 0.30)))"
    else:
        roic_formula = sust_roic
    roic_cell = ws.cell(row=r, column=4, value=roic_formula)
    roic_cell.font = FONT_DATA
    roic_cell.number_format = PCT_FMT
    roic_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    roic_row = r
    r += 1

    ws.cell(row=r, column=2, value="ROIC-Implied Reinvestment Rate (g / RONIC)").font = FONT_LABEL
    roic_reinv_cell = ws.cell(row=r, column=4, value=f"=D{tg_row}/D{roic_row}")
    roic_reinv_cell.font = FONT_DATA
    roic_reinv_cell.number_format = PCT_FMT
    roic_reinv_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    roic_reinv_row = r
    r += 1

    yr5_capex_pct_expr = f"({last_col_letter}{capex_row}/{last_col_letter}{rev_row})"
    yr5_nopat_m_expr = f"IF({last_col_letter}{margin_row}>0, MAX(0.01, {last_col_letter}{margin_row}*(1-{last_col_letter}{tax_row})), 0.01)"
    yr5_reinv_formula = (
        f"=MAX(0, (({yr5_capex_pct_expr}-{effective_dna_pct:.10f})+MAX(0, {norm_nwc_pct:.10f}*D{tg_row}))/{yr5_nopat_m_expr})"
    )
    ws.cell(row=r, column=2, value="Year-5 Physical & NWC Reinvestment Rate").font = FONT_LABEL
    yr5_reinv_cell = ws.cell(row=r, column=4, value=yr5_reinv_formula)
    yr5_reinv_cell.font = FONT_DATA
    yr5_reinv_cell.number_format = PCT_FMT
    yr5_reinv_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    yr5_reinv_row = r
    r += 1

    if is_high_roic_flag and margin_schedule and margin_schedule[-1] > 0:
        reinv_base_expr = f"MIN(0.80, MAX({min_reinv_floor:.6f}, MIN(D{roic_reinv_row}, 0.45*D{roic_reinv_row}+0.55*D{yr5_reinv_row})))"
    else:
        reinv_base_expr = f"MIN(0.80, MAX({min_reinv_floor:.6f}, D{roic_reinv_row}))"

    if is_extractive_flag and margin_schedule and margin_schedule[-1] > 0:
        reinv_formula = f"=MIN(0.80, MAX({reinv_base_expr}, MAX(0, ({yr5_capex_pct_expr}-{effective_dna_pct:.10f})/{yr5_nopat_m_expr})))"
    elif is_cyclical_flag and margin_schedule and margin_schedule[-1] > 0:
        reinv_formula = f"=MIN(0.80, MAX({reinv_base_expr}, MAX(0, ({yr5_capex_pct_expr}-{effective_dna_pct:.10f})/{yr5_nopat_m_expr})*0.85))"
    else:
        reinv_formula = f"={reinv_base_expr}"

    ws.cell(row=r, column=2, value="Terminal Reinvestment Rate Applied").font = FONT_LABEL
    reinv_cell = ws.cell(row=r, column=4, value=reinv_formula)
    reinv_cell.font = FONT_DATA_BOLD
    reinv_cell.number_format = PCT_FMT
    reinv_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    reinv_row = r
    r += 1

    ws.cell(row=r, column=2, value=f"Exit Multiple Benchmark TV (Terminal EBITDA × {benchmark_exit_mult:.1f}x)").font = FONT_LABEL
    exit_tv_formula = f"=MAX(0, {last_col_letter}{rev_row}*(1+D{tg_row})*({last_col_letter}{margin_row}+{effective_dna_pct:.10f})*{benchmark_exit_mult:.6f})"
    exit_tv_cell = ws.cell(row=r, column=4, value=exit_tv_formula)
    exit_tv_cell.font = FONT_DATA
    exit_tv_cell.number_format = cfmt_large
    exit_tv_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    exit_tv_row = r
    r += 1

    # Wire live HUL-style Terminal Value cells cleanly back to Supporting Schedule
    n1_cell.value = f"=D{term_nopat_row}*(1-D{reinv_row})"
    gordon_tv_expr = f"D{n1_row}/(D{wacc_param_row}-D{tg_row})"
    if is_extractive_flag:
        tv_cell.value = f"=IF(AND(D{wacc_param_row}>D{tg_row}, D{n1_row}>0), IF(AND(D{exit_tv_row}>0, ({gordon_tv_expr})>D{exit_tv_row}), 0.35*({gordon_tv_expr})+0.65*D{exit_tv_row}, ({gordon_tv_expr})), 0)"
    elif is_cyclical_flag:
        tv_cell.value = f"=IF(AND(D{wacc_param_row}>D{tg_row}, D{n1_row}>0), IF(AND(D{exit_tv_row}>0, ({gordon_tv_expr})>D{exit_tv_row}), 0.45*({gordon_tv_expr})+0.55*D{exit_tv_row}, ({gordon_tv_expr})), 0)"
    else:
        tv_cell.value = f"=IF(AND(D{wacc_param_row}>D{tg_row}, D{n1_row}>0), {gordon_tv_expr}, 0)"

    # Section: Scenario & Cross-Check Valuation Summary
    scenarios = data.get("scenarios", {}) or {}
    r += 1
    _set_banner(ws, r, 2, 6, "Scenario & Methodology Cross-Check Valuation Summary")
    r += 1
    _set_table_headers(
        ws,
        r,
        ["Valuation Case / Sensitivity Stress", f"Enterprise Value ({currency})", f"Equity Value ({currency})", f"Implied Price ({currency})", "Delta vs Base (%)"],
        start_col=2,
    )
    r += 1

    exit_ev_formula = f"=D{sum_pv_row}+D{exit_tv_row}*{last_col_letter}{df_row}"
    exit_eq_formula = f"=D{r+1}+D{cash_row}-D{debt_row}-D{min_int_row}"  # row ref adjusted dynamically below

    gordon_only_ev_formula = (
        f"=D{sum_pv_row}+IF(AND(D{wacc_param_row}>D{tg_row}, D{n1_row}>0), "
        f"D{n1_row}/(D{wacc_param_row}-D{tg_row}), 0)*{last_col_letter}{df_row}"
    )
    scen_rows_spec = [
        ("base", "Base Case (Gordon Growth Model)", f"=D{ev_row}", f"=D{eq_row}", f"=D{price_row}"),
        ("exit_multiple", f"Exit Multiple Cross-Check ({benchmark_exit_mult:.1f}x Term. EBITDA)", exit_ev_formula, None, None),
        ("unclipped_nwc", "Unclipped Operating NWC Sensitivity", None, None, None),
        ("committed_capex", "Contracted Capital Commitments / CapEx Floor", None, None, None),
        ("full_rsu_dilution", "Full Unvested RSU Dilution Test (Max Share Count)", None, None, None),
    ]
    for opt_k, opt_lbl in [
        ("pure_gordon_tv", "Pure Gordon Growth TV (Unblended)"),
        ("unadjusted_capex", "Unadjusted Historical Avg CapEx"),
        ("aro_provisions_stress", "75% LT-Provisions ARO Debt Stress"),
        ("unadjusted_gross_debt", "Unadjusted Gross Debt (No CWIP/Captive Offset)"),
        ("bottom_up_sector_beta", "Bottom-Up Cyclical Sector Beta"),
        ("unadjusted_beta", "Unclamped Raw Regression Beta"),
    ]:
        if isinstance(scenarios.get(opt_k), dict) and scenarios[opt_k].get("applicable"):
            ev_f = gordon_only_ev_formula if opt_k == "pure_gordon_tv" else None
            scen_rows_spec.append((opt_k, opt_lbl, ev_f, None, None))

    for s_key, s_label, s_ev_f, s_eq_f, s_px_f in scen_rows_spec:
        s_obj = scenarios.get(s_key) or {}
        if not s_obj and s_key not in ("base", "exit_multiple"):
            continue
        ev_cell_val = s_ev_f if s_ev_f is not None else float(s_obj.get("enterprise_value") or 0.0)
        if s_key in ("exit_multiple", "pure_gordon_tv"):
            eq_cell_val = f"=C{r}+D{cash_row}-D{debt_row}-D{min_int_row}"
            px_cell_val = f"=MAX(0, D{r}/D{shares_row})"
        elif s_eq_f is not None and s_px_f is not None:
            eq_cell_val = s_eq_f
            px_cell_val = s_px_f
        else:
            eq_cell_val = float(s_obj.get("equity_value") or 0.0)
            px_cell_val = float(s_obj.get("implied_price") or 0.0)

        fill = HIGHLIGHT_FILL if s_key == "base" else (ALT_ROW_FILL if r % 2 == 0 else None)
        c_lbl = ws.cell(row=r, column=2, value=s_obj.get("label") or s_label)
        c_lbl.font = FONT_LABEL_BOLD if s_key == "base" else FONT_LABEL
        c_lbl.fill = fill or PatternFill(fill_type=None)
        c_lbl.border = THIN_BORDER

        c_ev = ws.cell(row=r, column=3, value=ev_cell_val)
        c_ev.font = FONT_DATA_BOLD if s_key == "base" else FONT_DATA
        c_ev.fill = fill or PatternFill(fill_type=None)
        c_ev.border = THIN_BORDER
        c_ev.number_format = cfmt_large
        c_ev.alignment = ALIGN_RIGHT

        c_eq = ws.cell(row=r, column=4, value=eq_cell_val)
        c_eq.font = FONT_DATA_BOLD if s_key == "base" else FONT_DATA
        c_eq.fill = fill or PatternFill(fill_type=None)
        c_eq.border = THIN_BORDER
        c_eq.number_format = cfmt_large
        c_eq.alignment = ALIGN_RIGHT

        c_px = ws.cell(row=r, column=5, value=px_cell_val)
        c_px.font = FONT_DATA_BOLD if s_key == "base" else FONT_DATA
        c_px.fill = fill or PatternFill(fill_type=None)
        c_px.border = THIN_BORDER
        c_px.number_format = cfmt_price
        c_px.alignment = ALIGN_RIGHT

        c_dl = ws.cell(row=r, column=6, value=f"=IF($D${price_row}>0, (E{r}-$D${price_row})/$D${price_row}, 0)")
        c_dl.font = FONT_DATA
        c_dl.fill = fill or PatternFill(fill_type=None)
        c_dl.border = THIN_BORDER
        c_dl.number_format = PCT_FMT
        c_dl.alignment = ALIGN_RIGHT
        ws.row_dimensions[r].height = 19
        r += 1

    # ═══════════════════════════════════════════════════════════════════════════
    # NATIVE EXCEL CHARTS ON DCF MODEL (OpenPyXL)
    # ═══════════════════════════════════════════════════════════════════════════
    chart_col_letter = get_column_letter(max(end_col + 2, 9))
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
        "sum_pv_row": sum_pv_row,
        "pv_tv_row": pv_tv_row,
        "cash_row": cash_row,
        "debt_row": debt_row,
        "min_int_row": min_int_row,
        "shares_row": shares_row,
        "price_row": price_row,
        "reinv_row": reinv_row,
        "roic_row": roic_row,
        "nopat_row": nopat_row,
        "fcff_row": fcff_row,
        "rev_row": rev_row,
        "margin_row": margin_row,
        "ebit_row": ebit_row,
        "tax_row": tax_row,
        "period_row": period_row,
        "tg_row": tg_row,
        "wacc_param_row": wacc_param_row,
        "start_g_driver_row": start_g_driver_row,
        "fade_target_g_driver_row": fade_target_g_driver_row,
        "fade_exp_driver_row": fade_exp_driver_row,
        "n_proj": n_proj,
        "start_growth": start_growth_val,
        "raw_term_g": raw_term_g_val,
        "eff_term_g": eff_term_g,
        "target_margin": float(margin_schedule[-1]) if margin_schedule else 0.15,
        "current_margin": dcf.get("current_margin"),
        "last_revenue": last_revenue,
        "effective_dna_pct": effective_dna_pct,
        "avg_capex_pct": avg_capex_pct,
        "norm_nwc_pct": norm_nwc_pct,
        "cwip_to_rev": float(historicals.get("cwip_to_rev", 0.0) or 0.0),
        "avg_gross_margin": float(historicals.get("avg_gross_margin", 0.0) or 0.0),
        "latest_rnd_pct": float(historicals.get("latest_rnd_pct", 0.0) or 0.0),
        "benchmark_exit_mult": benchmark_exit_mult,
        "capex_floor_abs": capex_floor_abs,
        "tax_rate": tax_rate_dcf,
        "use_mid_year": use_mid_year_flag,
        "is_extractive": is_extractive_flag,
        "is_cyclical": is_cyclical_flag,
        "is_india": is_india_flag,
        "is_financial": bool(company.get("is_financial", False)),
        "sector": str(company.get("sector") or ""),
        "tangible_ic": float(dcf.get("tangible_ic") or 1.0),
        "hist_roic": float(dcf.get("hist_roic") or 0.0),
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
    historicals = data.get("historicals", {})
    macro = data.get("macro", {})
    dcf_links = dcf_links or {}

    cfmt_price = _get_currency_fmt_price(currency)
    cfmt_large = _get_currency_fmt_large(currency)

    # Title Banner
    _set_banner(ws, 2, 2, 11, "Valuation Sensitivity Analysis (2D Dynamic Formula Scenario Price Matrices)")

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

    # Extract exact model parameters (prefer live dcf_links, fallback cleanly to dcf/historicals)
    n_proj = int(dcf_links.get("n_proj") or len(dcf.get("growth_schedule", [0.05] * 5)) or 5)
    rev_row = int(dcf_links.get("rev_row") or 4)
    period_row = int(dcf_links.get("period_row") or 13)
    cash_row = int(dcf_links.get("cash_row") or 30)
    debt_row = int(dcf_links.get("debt_row") or 31)
    min_int_row = int(dcf_links.get("min_int_row") or 32)
    shares_row = int(dcf_links.get("shares_row") or 34)
    start_g_driver_row = dcf_links.get("start_g_driver_row")
    fade_target_g_driver_row = dcf_links.get("fade_target_g_driver_row")
    margin_row = int(dcf_links.get("margin_row") or 5)
    tax_row = int(dcf_links.get("tax_row") or 7)
    last_proj_col = get_column_letter(3 + n_proj)

    last_rev = float(dcf_links.get("last_revenue") or historicals.get("last_revenue") or 1.0)
    start_g_val = float(dcf_links.get("start_growth") if dcf_links.get("start_growth") is not None else (dcf.get("growth_schedule", [0.05])[0]))
    raw_tg_val = float(dcf_links.get("raw_term_g") if dcf_links.get("raw_term_g") is not None else (dcf.get("terminal_growth") or macro.get("terminal_growth", 0.025)))
    target_m_val = float(dcf_links.get("target_margin") if dcf_links.get("target_margin") is not None else (dcf.get("margin_schedule", [0.15])[-1]))
    cur_m_val = dcf_links.get("current_margin") if "current_margin" in dcf_links else dcf.get("current_margin")
    eff_dna_pct = float(dcf_links.get("effective_dna_pct") if dcf_links.get("effective_dna_pct") is not None else (dcf.get("effective_dna_pct") or historicals.get("avg_dna_pct", 0.02)))
    avg_capex_pct = float(dcf_links.get("avg_capex_pct") if dcf_links.get("avg_capex_pct") is not None else (historicals.get("avg_capex_pct", 0.03)))
    norm_nwc_pct = float(dcf_links.get("norm_nwc_pct") if dcf_links.get("norm_nwc_pct") is not None else (dcf.get("normalized_nwc_to_revenue", 0.0)))
    cwip_to_rev = float(dcf_links.get("cwip_to_rev") or historicals.get("cwip_to_rev", 0.0) or 0.0)
    avg_gm = float(dcf_links.get("avg_gross_margin") or historicals.get("avg_gross_margin", 0.0) or 0.0)
    tax_rate = float(dcf_links.get("tax_rate") if dcf_links.get("tax_rate") is not None else (dcf.get("tax_rate") or macro.get("tax_rate", 0.21)))
    is_ext_int = 1 if dcf_links.get("is_extractive", company.get("is_extractive", False)) else 0
    is_cyc_int = 1 if dcf_links.get("is_cyclical", company.get("is_cyclical", False)) else 0
    is_in_int = 1 if dcf_links.get("is_india", company.get("market") == "IN") else 0
    tangible_ic = float(dcf_links.get("tangible_ic") or dcf.get("tangible_ic") or 1.0)
    hist_roic = float(dcf_links.get("hist_roic") or dcf.get("hist_roic") or 0.0)
    capex_floor_abs = float(dcf_links.get("capex_floor_abs") or dcf.get("capex_floor_abs") or 0.0)
    raw_sens_exit_mult = dcf_links.get("benchmark_exit_mult")
    if raw_sens_exit_mult is None:
        raw_sens_exit_mult = dcf.get("benchmark_exit_multiple")
    if raw_sens_exit_mult is None:
        raw_sens_exit_mult = dcf.get("benchmark_exit_mult")
    exit_mult_val = float(raw_sens_exit_mult if raw_sens_exit_mult is not None else 10.0)
    use_mid_year_flag = bool(dcf_links.get("use_mid_year", dcf.get("use_mid_year", True)))

    r = 6
    table_specs = []

    def _render_table_shell(
        start_row: int,
        title: str,
        row_label: str,
        row_vals: list,
        col_label: str,
        col_vals: list,
        price_grid: list,
        mode: str,
    ) -> int:
        cur_r = start_row
        num_cols = len(col_vals)
        _set_banner(ws, cur_r, 2, 2 + num_cols, title)
        cur_r += 1

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
        data_start_r = cur_r

        for i, (r_val, row_prices) in enumerate(zip(row_vals, price_grid)):
            row_lbl = ws.cell(row=cur_r, column=2, value=float(r_val))
            row_lbl.font = FONT_HEADER
            row_lbl.fill = HEADER_FILL
            row_lbl.number_format = PCT_FMT
            row_lbl.alignment = ALIGN_CENTER
            row_lbl.border = THIN_BORDER

            for j, price in enumerate(row_prices):
                col = 3 + j
                cell = ws.cell(row=cur_r, column=col, value=float(price))
                cell.font = FONT_DATA_BOLD if (i == len(row_vals) // 2 and j == len(col_vals) // 2) else FONT_DATA
                cell.number_format = cfmt_price
                cell.alignment = ALIGN_RIGHT
                cell.border = THIN_BORDER
            cur_r += 1

        data_end_r = cur_r - 1
        grid_start_letter = get_column_letter(3)
        grid_end_letter = get_column_letter(2 + num_cols)
        rule = ColorScaleRule(
            start_type="min", start_color="FCA5A5",
            mid_type="percentile", mid_value=50, mid_color="FEF08A",
            end_type="max", end_color="86EFAC",
        )
        ws.conditional_formatting.add(f"{grid_start_letter}{data_start_r}:{grid_end_letter}{data_end_r}", rule)
        table_specs.append({
            "mode": mode,
            "row_vals": row_vals,
            "col_vals": col_vals,
            "table_header_r": table_header_r,
            "data_start_r": data_start_r,
        })
        return cur_r + 2

    # Table 1: Cost of Capital / WACC (Rows) vs. Terminal Growth Rate g (Columns)
    tg_range = tgw.get("terminal_growth_range", [])
    w_range_tg = tgw.get("wacc_range", [])
    grid_tg = tgw.get("price_grid", [])
    if tg_range and w_range_tg and grid_tg:
        r = _render_table_shell(
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
        r = _render_table_shell(
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
        r = _render_table_shell(
            r,
            "Sensitivity Table 3: Cost of Capital / WACC (%) vs. Operating Margin (%)",
            "WACC",
            w_range2,
            "EBIT Margin",
            m_range,
            grid2,
            mode="ebit_margin",
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # Multi-Year Live Calculation Audit Engine (eliminates shortcuts / static grid cells)
    # ═══════════════════════════════════════════════════════════════════════════
    if table_specs and dcf_links.get("price_cell"):
        _set_banner(ws, r, 2, 5, "Sensitivity Calibration Parameters (Linked to Base DCF Model)")
        r += 1

        param_rows: Dict[str, int] = {}
        has_cur_m = cur_m_val is not None
        last_rev_val_or_f = f"='DCF Model'!C{rev_row}" if dcf_links.get("rev_row") else last_rev
        start_g_val_or_f = f"='DCF Model'!D{start_g_driver_row}" if start_g_driver_row else start_g_val
        raw_tg_val_or_f = f"='DCF Model'!D{fade_target_g_driver_row}" if fade_target_g_driver_row else raw_tg_val
        target_m_val_or_f = f"='DCF Model'!{last_proj_col}{margin_row}" if dcf_links.get("margin_row") else target_m_val
        tax_val_or_f = f"='DCF Model'!D{tax_row}" if dcf_links.get("tax_row") else tax_rate

        param_defs = [
            ("last_rev", "Base FY Revenue (Year 0)", last_rev_val_or_f, cfmt_large),
            ("start_g", "Base Year-1 Starting Revenue Growth", start_g_val_or_f, PCT_FMT),
            ("raw_tg", "Base Input Terminal Growth Rate (g)", raw_tg_val_or_f, PCT_FMT),
            ("target_m", "Target Operating Margin (Year N)", target_m_val_or_f, PCT_FMT),
            ("cur_m", "Year 0 Base Operating Margin (Step Start)", float(cur_m_val) if has_cur_m else 0.0, PCT_FMT),
            ("eff_dna", "Effective D&A % of Revenue", eff_dna_pct, PCT_FMT),
            ("avg_capex", "Historical CapEx % of Revenue", avg_capex_pct, PCT_FMT),
            ("norm_nwc", "Normalized NWC % of Revenue", norm_nwc_pct, PCT_FMT),
            ("cwip_rev", "CWIP % of Revenue", cwip_to_rev, PCT_FMT),
            ("avg_gm", "Average Gross Margin %", avg_gm, PCT_FMT),
            ("tax_rate", "Marginal Operating Tax Rate", tax_val_or_f, PCT_FMT),
            ("tangible_ic", "Base Tangible Invested Capital", tangible_ic, cfmt_large),
            ("hist_roic", "Base Year Historical ROIC", hist_roic, PCT_FMT),
            ("capex_floor", "Contracted CapEx Floor (Absolute)", capex_floor_abs, cfmt_large),
            ("exit_mult", "Sector Exit EV/EBITDA Benchmark Multiple", exit_mult_val, MULT_FMT),
            ("is_ext", "Extractive Commodity Flag (1/0)", is_ext_int, INT_FMT),
            ("is_cyc", "Cyclical Capital-Intensive Flag (1/0)", is_cyc_int, INT_FMT),
            ("is_in", "India Market Jurisdiction Flag (1/0)", is_in_int, INT_FMT),
        ]
        for p_key, p_lbl, p_val, p_fmt in param_defs:
            ws.cell(row=r, column=2, value=p_lbl).font = FONT_LABEL
            ws.cell(row=r, column=2).border = THIN_BORDER
            pc = ws.cell(row=r, column=3, value=p_val)
            pc.font = FONT_DATA_BOLD
            pc.number_format = p_fmt
            pc.alignment = ALIGN_RIGHT
            pc.border = THIN_BORDER
            param_rows[p_key] = r
            r += 1

        r += 1
        # Audit Schedule Columns:
        # B(2): Scenario ID | C(3): WACC | D(4): tg_in | E(5): start_g | F(6): target_m
        # G(7): clamped_tg | H(8): eff_tg | I(9): fade_exp | J(10): capex_steady | K(11): capex_start
        # 12..11+N: Rev_1..Rev_N | 12+N..11+2N: PV_UFCF_1..PV_UFCF_N
        # next: Sum_PV_UFCF | Eff_ROIC | Sust_ROIC | Term_Reinv | Term_Val | PV_TV | EV | Implied_Price
        c_last_rev = f"$C${param_rows['last_rev']}"
        c_start_g = f"$C${param_rows['start_g']}"
        c_raw_tg = f"$C${param_rows['raw_tg']}"
        c_target_m = f"$C${param_rows['target_m']}"
        c_cur_m = f"$C${param_rows['cur_m']}"
        c_dna = f"$C${param_rows['eff_dna']}"
        c_capex = f"$C${param_rows['avg_capex']}"
        c_nwc = f"$C${param_rows['norm_nwc']}"
        c_cwip = f"$C${param_rows['cwip_rev']}"
        c_gm = f"$C${param_rows['avg_gm']}"
        c_tax = f"$C${param_rows['tax_rate']}"
        c_tic = f"$C${param_rows['tangible_ic']}"
        c_hroic = f"$C${param_rows['hist_roic']}"
        c_cfloor = f"$C${param_rows['capex_floor']}"
        c_emult = f"$C${param_rows['exit_mult']}"
        c_ext = f"$C${param_rows['is_ext']}"
        c_cyc = f"$C${param_rows['is_cyc']}"
        c_in = f"$C${param_rows['is_in']}"

        rev_cols = [get_column_letter(12 + k) for k in range(n_proj)]
        pv_cols = [get_column_letter(12 + n_proj + k) for k in range(n_proj)]
        col_sum_pv = get_column_letter(12 + 2 * n_proj)
        col_eff_roic = get_column_letter(13 + 2 * n_proj)
        col_sust_roic = get_column_letter(14 + 2 * n_proj)
        col_reinv = get_column_letter(15 + 2 * n_proj)
        col_tv = get_column_letter(16 + 2 * n_proj)
        col_pv_tv = get_column_letter(17 + 2 * n_proj)
        col_ev = get_column_letter(18 + 2 * n_proj)
        col_price_out = get_column_letter(19 + 2 * n_proj)

        audit_headers = (
            ["Scenario ID", "WACC", "Input g", "Start g", "Target EBIT %", "Clamped g", "Eff. g", "Fade Exp", "CapEx Steady %", "CapEx Start %"]
            + [f"Rev Yr{k+1}" for k in range(n_proj)]
            + [f"PV(UFCF) Yr{k+1}" for k in range(n_proj)]
            + ["Sum PV(UFCF)", "Eff. ROIC", "Sust. ROIC", "Term. Reinv %", "Terminal Value", "PV(TV)", "Enterprise Value", "Implied Price"]
        )
        _set_banner(ws, r, 2, 1 + len(audit_headers), "Multi-Year Sensitivity Calculation Engine")
        r += 1
        _set_table_headers(ws, r, audit_headers, start_col=2)
        r += 1

        step_den = max(1, n_proj - 1)
        for t_idx, spec in enumerate(table_specs, start=1):
            mode = spec["mode"]
            t_hdr_r = spec["table_header_r"]
            d_start_r = spec["data_start_r"]
            min_spread = 0.015 if mode == "terminal_growth" else 0.025

            for i in range(len(spec["row_vals"])):
                grid_r = d_start_r + i
                for j in range(len(spec["col_vals"])):
                    grid_col = 3 + j
                    grid_col_l = get_column_letter(grid_col)
                    aud_r = r

                    w_ref = f"$B{grid_r}"
                    col_ref = f"{grid_col_l}${t_hdr_r}"

                    tg_in_f = f"={col_ref}" if mode == "terminal_growth" else f"={c_raw_tg}"
                    sg_in_f = f"={col_ref}" if mode == "revenue_growth" else f"={c_start_g}"
                    tm_in_f = f"={col_ref}" if mode == "ebit_margin" else f"={c_target_m}"

                    if mode == "terminal_growth":
                        clamped_tg_f = f"=MIN(D{aud_r}, MAX(0.01, C{aud_r}-0.015))"
                    else:
                        clamped_tg_f = f"=MIN(D{aud_r}, IF({c_ext}=1, 0.025, IF({c_in}=1, 0.05, 0.025)))"
                    eff_tg_f = f"=IF((C{aud_r}-G{aud_r})<{min_spread}, MAX(0.01, C{aud_r}-{min_spread}), G{aud_r})"
                    fade_exp_f = f"=IF(OR({c_ext}=1, {c_cyc}=1), 1, 1+0.35*MIN(1, MAX(0, (E{aud_r}-D{aud_r}-0.05)/0.10)))"

                    max_ext_expr = f"IF({c_cwip}>0.50, {c_dna}*1.45, MAX({c_dna}*2.5, MAX(0.05, F{aud_r})*(1-{c_tax})*0.72))"
                    base_ss_expr = f"({c_dna}*(1+D{aud_r}))"
                    capex_ss_f = (
                        f"=IF({c_ext}=1, MAX({base_ss_expr}, MIN({c_capex}, {max_ext_expr})), "
                        f"IF({c_cyc}=1, MAX({base_ss_expr}, MIN({c_capex}*0.90, {c_dna}*1.35)), {base_ss_expr}))"
                    )
                    std_start_cap_expr = (
                        f"IF(AND({c_capex}>{c_dna}*2.20, {c_capex}>0.15), {c_dna}*(1+MAX(0.10, D{aud_r})), "
                        f"IF(AND({c_capex}>{c_dna}*1.40, {c_capex}>0.12), MIN({c_capex}, {c_dna}*(1+MAX(0.15, E{aud_r}*1.8))), {c_capex}))"
                    )
                    capex_start_f = f"=IF({c_ext}=1, MIN({c_capex}, {max_ext_expr}*1.10), IF({c_cyc}=1, {c_capex}, {std_start_cap_expr}))"

                    ws.cell(row=aud_r, column=2, value=f"T{t_idx}-R{i+1}C{j+1}").font = FONT_DATA
                    ws.cell(row=aud_r, column=3, value=f"={w_ref}").number_format = PCT_FMT
                    ws.cell(row=aud_r, column=4, value=tg_in_f).number_format = PCT_FMT
                    ws.cell(row=aud_r, column=5, value=sg_in_f).number_format = PCT_FMT
                    ws.cell(row=aud_r, column=6, value=tm_in_f).number_format = PCT_FMT
                    ws.cell(row=aud_r, column=7, value=clamped_tg_f).number_format = PCT_FMT
                    ws.cell(row=aud_r, column=8, value=eff_tg_f).number_format = PCT_FMT
                    ws.cell(row=aud_r, column=9, value=fade_exp_f).number_format = NUM_2DEC_FMT
                    ws.cell(row=aud_r, column=10, value=capex_ss_f).number_format = PCT_FMT
                    ws.cell(row=aud_r, column=11, value=capex_start_f).number_format = PCT_FMT

                    for k in range(n_proj):
                        if k == 0:
                            g_k_expr = f"E{aud_r}"
                            prev_rev_ref = c_last_rev
                        else:
                            g_k_expr = f"(E{aud_r}-(E{aud_r}-D{aud_r})*(({k}/{step_den})^I{aud_r}))"
                            prev_rev_ref = f"{rev_cols[k-1]}{aud_r}"
                        c_rev = ws.cell(row=aud_r, column=12 + k, value=f"={prev_rev_ref}*(1+{g_k_expr})")
                        c_rev.number_format = cfmt_large

                        m_k_expr = (
                            f"({c_cur_m}+(F{aud_r}-{c_cur_m})*(({k+1})/{n_proj}))"
                            if has_cur_m
                            else f"F{aud_r}"
                        )
                        capex_k_expr = f"(K{aud_r}+(J{aud_r}-K{aud_r})*({k}/{step_den}))" if n_proj > 1 else f"K{aud_r}"
                        capex_amt_expr = (
                            f"MAX({c_cfloor}, {rev_cols[k]}{aud_r}*{capex_k_expr})"
                            if capex_floor_abs > 0
                            else f"({rev_cols[k]}{aud_r}*{capex_k_expr})"
                        )
                        ufcf_k_expr = (
                            f"({rev_cols[k]}{aud_r}*({m_k_expr}*(1-{c_tax})+{c_dna})-{capex_amt_expr}-{c_nwc}*({rev_cols[k]}{aud_r}-{prev_rev_ref}))"
                        )
                        period_ref = f"'DCF Model'!${get_column_letter(4+k)}${period_row}"
                        c_pv = ws.cell(row=aud_r, column=12 + n_proj + k, value=f"={ufcf_k_expr}/((1+C{aud_r})^{period_ref})")
                        c_pv.number_format = cfmt_large

                    sum_pv_f = f"=SUM({pv_cols[0]}{aud_r}:{pv_cols[-1]}{aud_r})"
                    ws.cell(row=aud_r, column=12 + 2 * n_proj, value=sum_pv_f).number_format = cfmt_large

                    mN_expr = f"({c_cur_m}+(F{aud_r}-{c_cur_m})*({n_proj}/{n_proj}))" if has_cur_m else f"F{aud_r}"
                    revN_ref = f"{rev_cols[-1]}{aud_r}"
                    yr5_nopat_expr = f"({revN_ref}*{mN_expr}*(1-{c_tax}))"
                    yr5_tic_expr = f"({c_tic}*MAX(1, IF({c_last_rev}>0, {revN_ref}/{c_last_rev}, 1)))"
                    proj_roic_expr = f"IF(AND({yr5_tic_expr}>0, {yr5_nopat_expr}>0), {yr5_nopat_expr}/{yr5_tic_expr}, C{aud_r})"
                    if has_cur_m:
                        eff_roic_f = f"=IF({c_hroic}<=0.02, MAX({c_hroic}, {proj_roic_expr}), 0.5*{c_hroic}+0.5*({proj_roic_expr}))"
                    else:
                        eff_roic_f = f"=IF({c_hroic}<=0.02, MAX({c_hroic}, {proj_roic_expr}), {c_hroic})"
                    ws.cell(row=aud_r, column=13 + 2 * n_proj, value=eff_roic_f).number_format = PCT_FMT

                    is_hi_expr = f"AND({c_ext}=0, {c_cyc}=0, {col_eff_roic}{aud_r}>=0.22, OR({c_gm}>=0.45, {col_eff_roic}{aud_r}>=0.28))"
                    min_r_floor_expr = f"(C{aud_r}+IF(AND({c_ext}=0, {c_cyc}=0, {c_capex}>{c_dna}*2.20), 0.045, 0))"
                    sust_roic_f = f"=MAX({min_r_floor_expr}, MIN({col_eff_roic}{aud_r}, IF({is_hi_expr}, 0.45, 0.30)))"
                    ws.cell(row=aud_r, column=14 + 2 * n_proj, value=sust_roic_f).number_format = PCT_FMT

                    roic_b_expr = f"(H{aud_r}/{col_sust_roic}{aud_r})"
                    yr5_nm_expr = f"IF({mN_expr}>0, MAX(0.01, {mN_expr}*(1-{c_tax})), 0.01)"
                    mod_b_expr = f"MAX(0, ((J{aud_r}-{c_dna})+MAX(0, {c_nwc}*H{aud_r}))/{yr5_nm_expr})"
                    min_bf_expr = f"IF({is_hi_expr}, 0.06, 0.10)"
                    blend_b_expr = f"IF(AND({is_hi_expr}, {mN_expr}>0), MIN({roic_b_expr}, 0.45*{roic_b_expr}+0.55*{mod_b_expr}), {roic_b_expr})"
                    base_reinv_expr = f"MIN(0.80, MAX({min_bf_expr}, {blend_b_expr}))"
                    capex_reinv_expr = f"MAX(0, (J{aud_r}-{c_dna})/{yr5_nm_expr})"
                    reinv_f = (
                        f"=IF(AND({c_ext}=1, {mN_expr}>0), MIN(0.80, MAX({base_reinv_expr}, {capex_reinv_expr})), "
                        f"IF(AND({c_cyc}=1, {mN_expr}>0), MIN(0.80, MAX({base_reinv_expr}, {capex_reinv_expr}*0.85)), {base_reinv_expr}))"
                    )
                    ws.cell(row=aud_r, column=15 + 2 * n_proj, value=reinv_f).number_format = PCT_FMT

                    term_nopat_expr = f"({revN_ref}*(1+H{aud_r})*{mN_expr}*(1-{c_tax}))"
                    term_ufcf_expr = f"({term_nopat_expr}*(1-{col_reinv}{aud_r}))"
                    gordon_tv_expr = f"(({term_ufcf_expr})/(C{aud_r}-H{aud_r}))"
                    term_ebitda_expr = f"({revN_ref}*(1+H{aud_r})*({mN_expr}+{c_dna}))"
                    exit_tv_expr = f"({term_ebitda_expr}*{c_emult})"
                    tv_f = (
                        f"=IF(AND(C{aud_r}>H{aud_r}, ({term_ufcf_expr})>0), "
                        f"IF(AND({c_ext}=1, {exit_tv_expr}>0, ({gordon_tv_expr})>{exit_tv_expr}), 0.35*({gordon_tv_expr})+0.65*({exit_tv_expr}), "
                        f"IF(AND({c_cyc}=1, {exit_tv_expr}>0, ({gordon_tv_expr})>{exit_tv_expr}), 0.45*({gordon_tv_expr})+0.55*({exit_tv_expr}), {gordon_tv_expr})), 0)"
                    )
                    ws.cell(row=aud_r, column=16 + 2 * n_proj, value=tv_f).number_format = cfmt_large

                    pv_tv_f = f"={col_tv}{aud_r}/((1+C{aud_r})^'DCF Model'!${last_proj_col}${period_row})"
                    ws.cell(row=aud_r, column=17 + 2 * n_proj, value=pv_tv_f).number_format = cfmt_large

                    ev_f = f"={col_sum_pv}{aud_r}+{col_pv_tv}{aud_r}"
                    ws.cell(row=aud_r, column=18 + 2 * n_proj, value=ev_f).number_format = cfmt_large

                    px_f = (
                        f"=MAX(0, ({col_ev}{aud_r}+'DCF Model'!$D${cash_row}-'DCF Model'!$D${debt_row}-'DCF Model'!$D${min_int_row})"
                        f"/'DCF Model'!$D${shares_row})"
                    )
                    ws.cell(row=aud_r, column=19 + 2 * n_proj, value=px_f).number_format = cfmt_price

                    # Wire the 2D visible table cell directly to this live audit row!
                    ws.cell(row=grid_r, column=grid_col).value = f"={col_price_out}{aud_r}"
                    r += 1

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=15, max_width=28)
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
    n_valid_sims = int(mc.get("valid_simulations") or mc.get("actual_iterations") or n_reps_to_write)
    rep_start_row = 36
    rep_end_row = rep_start_row + n_reps_to_write - 1

    # Title Banner (Cols B to E)
    _set_banner(ws, 2, 2, 5, f"Monte Carlo Valuation & Value-at-Risk (VaR) Engine — {company_name} ({ticker})")

    # ═══════════════════════════════════════════════════════════════════════════
    # Section 1: Summary Statistics (Cols B to E, Rows 4 to 15 — keeps C7/C8/C12 fixed!)
    # ═══════════════════════════════════════════════════════════════════════════
    _set_banner(ws, 4, 2, 5, "Monte Carlo Valuation Summary & Probability Metrics")

    stats_items = [
        ("Simulation Iterations", n_valid_sims, INT_FMT, None),
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
    # Section 3: Frequency Distribution Table (Rows 34+, leaves rows 24-33 clear beside G4 chart)
    # ═══════════════════════════════════════════════════════════════════════════
    r = 34
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
    _set_banner(ws, 34, 7, 9, "Simulated Monte Carlo Replications (Cholesky DCF Iterations)")
    rep_headers = ["Replication #", f"Simulated Price ({currency})", "Return vs CMP"]
    _set_table_headers(ws, 35, rep_headers, start_col=7)

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
    model_type = str(
        company.get("model_type")
        or dcf.get("model_type")
        or ("BANKING_DDM" if is_fin else "STANDARD_FCFF")
    )
    is_ins = model_type in ("INSURANCE_PNC_DDM", "INSURANCE_LIFE_DDM") or bool(dcf.get("is_insurance"))
    is_life_ins = model_type == "INSURANCE_LIFE_DDM" or str(dcf.get("insurer_subtype") or "") == "LIFE_ANNUITY"
    is_reit = model_type == "REIT_INVIT_AFFO" or bool(dcf.get("is_reit"))
    method_comp = data.get("method_comparison", {})

    # Title Block
    ws["B2"].value = company.get(
        "name",
        "Insurance Carrier"
        if is_ins
        else ("REIT / Infrastructure Trust" if is_reit else ("Financial Institution" if is_fin else "Corporate Equity Valuation")),
    )
    ws["B2"].font = FONT_TITLE
    if is_ins:
        ws["B3"].value = f"Multi-Stage Actuarial Excess-Return & Policyholder Float Valuation — {company.get('ticker', '')}"
    elif is_reit:
        ws["B3"].value = f"Multi-Stage REIT / InvIT Distributable AFFO (NDCF) & Cap-Rate NAV Model — {company.get('ticker', '')}"
    elif is_fin:
        ws["B3"].value = f"Multi-Stage FCFE & Regulatory Capital Valuation Model — {company.get('ticker', '')}"
    else:
        ws["B3"].value = f"Multi-Stage Dividend Discount (DDM) & FCFE Equity Valuation Model — {company.get('ticker', '')}"
    ws["B3"].font = FONT_SUBTITLE
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 18

    # Section 1: Entity Metadata
    r = 5
    sec1_title = (
        "Insurer Actuarial Profile & Market Metadata"
        if is_ins
        else ("REIT / InvIT Portfolio Profile & Market Metadata" if is_reit else ("Financial Institution Profile & Market Metadata" if is_fin else "Company Profile & Market Metadata"))
    )
    _set_banner(ws, r, 2, 5, sec1_title)
    r += 1

    val_shares_cover = float(
        dcf.get("shares_used")
        or market_data.get("diluted_valuation_shares")
        or market_data.get("shares_outstanding", 0)
        or 0
    )
    acct_std_label = _format_accounting_standard(
        data.get("accounting_standard") or company.get("accounting_standard"),
        company.get("market", "US"),
    )
    profile_items = [
        ("Company Name", company.get("name")),
        ("Ticker Symbol", company.get("ticker")),
        ("Exchange Market", company.get("market")),
        ("Sector", company.get("sector") or ("Real Estate / InvIT" if is_reit else ("Financial Services" if is_fin else "Equities"))),
        ("Industry", company.get("industry") or ("Insurance" if is_ins else ("REIT / InvIT" if is_reit else ("Banking / NBFC" if is_fin else "Corporate")))),
        ("Reporting Currency", currency),
        ("Accounting Standard", acct_std_label),
        ("Valuation Date", datetime.now().strftime("%d-%b-%Y")),
        ("Diluted Shares Outstanding" if not is_reit else "Diluted Units Outstanding", val_shares_cover, INT_FMT),
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

    is_nbfc = bool(dcf.get("is_nbfc") or company.get("is_nbfc") or (data.get("model_suitability") or {}).get("model_family") == "NBFC_LENDER_DDM")
    lender_sub_raw = dcf.get("lender_subtype") or company.get("lender_subtype") or ("NBFC_WHOLESALE_LENDER" if is_nbfc else "COMMERCIAL_DEPOSIT_BANK")
    lender_sub_label = {
        "NBFC_WHOLESALE_LENDER": "Wholesale / Specialized Lender",
        "COMMERCIAL_DEPOSIT_BANK": "Commercial Deposit Bank",
    }.get(str(lender_sub_raw), str(lender_sub_raw).replace("_", " ").title())
    if is_ins:
        method_label = (
            "Actuarial Life & Annuity Equity DDM (Normalized New-Business Strain)"
            if is_life_ins
            else "Actuarial P&C Insurer Equity DDM (Ex-AOCI Book Value & Float)"
        )
        ins_sub_raw = str(dcf.get("insurer_subtype") or ("LIFE_ANNUITY" if is_life_ins else "PNC_REINSURANCE"))
        ins_sub_label = {"LIFE_ANNUITY": "Life & Annuity", "PNC_REINSURANCE": "Property & Casualty"}.get(
            ins_sub_raw, ins_sub_raw.replace("_", " ").title()
        )
        std_label = f"Cost of Equity (Ke via CAPM) — {ins_sub_label}"
        bv_lbl = "Ex-AOCI Common BVPS (Ex-NCI)" if bool(dcf.get("used_ex_aoci_bv")) else "Common Book Value per Share (Ex-NCI)"
        mult_lbl = "Justified P / Ex-AOCI Book Multiple" if bool(dcf.get("used_ex_aoci_bv")) else "Justified Price-to-Book (P/B)"
        output_items = [
            ("Actuarial Excess-Return Fair Value per Share", implied_price, cfmt_price, True),
            ("Current Market Price (CMP)", cmp, cfmt_price, False),
            ("Implied Upside / (Downside)", upside, PCT_FMT, True),
            ("Valuation Outlook", verdict_text, None, True),
            ("Valuation Methodology", method_label, None, False),
            ("Discount Rate Standard", std_label, None, False),
            ("Cost of Equity (Ke)", ke_val, PCT_FMT, False),
            ("Long-Term Terminal Growth Rate (g)", g_val, PCT_FMT, False),
            (bv_lbl, bvps_val, cfmt_price, False),
            (mult_lbl, just_pb, MULT_FMT, False),
            ("Justified P/B Fair Value", just_price, cfmt_price, False),
            ("Policyholder Float-to-Equity Ratio", float(dcf.get("float_to_equity") or 0.0), MULT_FMT, False),
        ]
        if float(dcf.get("claims_loss_ratio") or 0.0) > 0:
            output_items.append(("Historical Claims & Loss Adjustment Ratio", float(dcf.get("claims_loss_ratio") or 0.0), PCT_FMT, False))
        if dcf.get("catastrophe_stress_price") is not None:
            output_items.append((
                "Catastrophe (+250 bps Claims / +50 bps Ke) Stress Value",
                float(dcf.get("catastrophe_stress_price") or 0.0),
                cfmt_price,
                False,
            ))
    elif is_reit:
        output_items = [
            ("Distributable AFFO / NDCF Fair Value per Unit", implied_price, cfmt_price, True),
            ("Current Market Unit Price (CMP)", cmp, cfmt_price, False),
            ("Implied Upside / (Downside)", upside, PCT_FMT, True),
            ("Valuation Outlook", verdict_text, None, True),
            ("Valuation Methodology", "REIT / InvIT Distributable AFFO (NDCF) & Cap-Rate GAV/NAV", None, False),
            ("Discount Rate Standard", "Cost of Equity (Ke via CAPM) — Real Asset Equity", None, False),
            ("Cost of Equity (Ke)", ke_val, PCT_FMT, False),
            ("Long-Term Terminal Growth Rate (g)", g_val, PCT_FMT, False),
            ("Current FFO per Unit", float(dcf.get("ffo_per_unit") or 0.0), cfmt_price, False),
            ("Current AFFO per Unit", float(dcf.get("affo_per_unit") or 0.0), cfmt_price, False),
            ("Implied Price / AFFO Multiple", just_pb, MULT_FMT, False),
            ("Cap-Rate NAV per Unit (Real-Asset Cross-Check)", float(dcf.get("cap_rate_nav_per_unit") or just_price), cfmt_price, True),
            ("Benchmark Real-Asset Cap Rate", float(dcf.get("benchmark_cap_rate") or 0.0), PCT_FMT, False),
            ("+75 bps Cap-Rate Stress NAV per Unit", float(dcf.get("cap_rate_stress_price") or 0.0), cfmt_price, False),
        ]
    else:
        output_items = [
            ("Multi-Stage DDM / FCFE Fair Value per Share", implied_price, cfmt_price, True),
            ("Current Market Price (CMP)", cmp, cfmt_price, False),
            ("Implied Upside / (Downside)", upside, PCT_FMT, True),
            ("Valuation Outlook", verdict_text, None, True),
            (
                "Valuation Methodology",
                "Damodaran Multi-Stage Wholesale NBFC FCFE & DDM"
                if (is_fin and is_nbfc)
                else (
                    "Damodaran Multi-Stage Regulatory Capital FCFE & DDM"
                    if is_fin
                    else "Multi-Stage Dividend Discount (DDM) & Corporate FCFE Model"
                ),
                None,
                False,
            ),
            ("Discount Rate Standard", f"Cost of Equity (Ke via CAPM) — {lender_sub_label}" if is_fin else "Cost of Equity (Ke via CAPM)", None, False),
            ("Cost of Equity (Ke)", ke_val, PCT_FMT, False),
            ("Long-Term Terminal Growth Rate (g)", g_val, PCT_FMT, False),
            ("Book Value per Share (BVPS)", bvps_val, cfmt_price, False),
            ("Justified Price-to-Book (P/B)", just_pb, MULT_FMT, False),
            ("Justified P/B Fair Value", just_price, cfmt_price, False),
        ]
        if is_fin and is_nbfc and dcf.get("credit_cost_stress_price") is not None:
            output_items.append((
                "NBFC Wholesale Leverage & Credit-Cost Stress Fair Value",
                float(dcf.get("credit_cost_stress_price") or 0.0),
                cfmt_price,
                False,
            ))
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
    _set_banner(ws, r, 2, 5, "Monte Carlo Risk Assessment")
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
    dcf_meta = data.get("dcf_result", {})
    is_ins_hist = (
        str(company.get("model_type") or dcf_meta.get("model_type") or "") in ("INSURANCE_PNC_DDM", "INSURANCE_LIFE_DDM")
        or bool(dcf_meta.get("is_insurance"))
    )
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
    row_ret_cap = _write_statement_row(
        "Solvency Capital Retained (Net Income − Dividends)" if is_ins_hist else "Tier-1 Regulatory Capital Retained (Retained Earnings Addition)",
        [],
        cfmt_large,
        is_bold=True,
        formula_subtraction=(row_ni, row_divs) if any(raw_divs) else None,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # PART II: BANKING BALANCE SHEET & CAPITAL STRUCTURE
    # ═══════════════════════════════════════════════════════════════════════════
    r += 1
    _write_sub_banner("Part II: Insurance Balance Sheet, Float & Solvency Capital" if is_ins_hist else "Part II: Banking Balance Sheet & Capital Adequacy")

    raw_sc = _get_vals(bs_stmt, "Equity Share Capital")
    row_sc = _write_statement_row("Equity Share Capital (Common Stock)", raw_sc, cfmt_large)

    raw_equity = _get_vals(bs_stmt, "Total Stockholders' Equity", historicals.get("book_value"))
    raw_res = _get_vals(bs_stmt, "Reserves & Retained Earnings")
    if any(raw_equity) and any(raw_sc):
        raw_res = [max(0.0, float(eq - sc)) for eq, sc in zip(raw_equity, raw_sc)]
    row_res = _write_statement_row("Reserves, Surplus & Retained Earnings", raw_res, cfmt_large)

    row_equity = _write_statement_row(
        "Common Stockholders' Equity (GAAP Book Value Ex-NCI)" if is_ins_hist else "Total Common Stockholders' Equity (Tier-1 Book Value)",
        raw_equity,
        cfmt_large,
        is_bold=True,
        formula_sum=[row_sc, row_res] if any(raw_sc) and any(raw_res) else None,
    )

    row_bvps = _write_statement_row("Book Value per Share (BVPS)", [], cfmt_price, is_bold=True,
                                    is_margin_of=(row_equity, row_shares) if any(raw_shares) else None)

    raw_debt = _get_vals(bs_stmt, "Total Debt")
    row_debt = _write_statement_row("Surplus Notes & Financial Borrowings" if is_ins_hist else "Wholesale Borrowings & Subordinated Debt", raw_debt, cfmt_large)

    raw_tot_assets = _get_vals(bs_stmt, "Total Assets")
    raw_dep = [max(0.0, float(a - e - d)) for a, e, d in zip(raw_tot_assets, raw_equity, raw_debt)]
    row_dep = _write_statement_row(
        "Technical Reserves, Unearned Premiums & Policyholder Float" if is_ins_hist else "Customer Deposits, Policy Liabilities & Other Liabilities",
        raw_dep,
        cfmt_large,
    )

    row_tot_liab = _write_statement_row("Total Liabilities (Deposits, Borrowings & Payables)", [], cfmt_large, is_bold=True,
                                       formula_sum=[row_debt, row_dep] if any(raw_dep) else None)

    row_tot_liab_eq = _write_statement_row("Total Liabilities & Stockholders' Equity", raw_tot_assets, cfmt_large, is_bold=True,
                                           formula_sum=[row_equity, row_tot_liab] if any(raw_dep) else None)

    # Assets breakdown
    r += 1
    raw_cash = _get_vals(bs_stmt, "Cash & Central Bank Balances", _get_vals(bs_stmt, "Cash & Bank Balances"))
    row_cash = _write_statement_row("Cash, Central Bank Reserves & Interbank Balances", raw_cash, cfmt_large)

    raw_inv = _get_vals(bs_stmt, "Investments & Financial Assets", _get_vals(bs_stmt, "Investments"))
    row_inv = _write_statement_row(
        "Investable Float Securities & Fixed-Income Portfolio" if is_ins_hist else "Investment Securities & Marketable Financial Assets",
        raw_inv,
        cfmt_large,
    )

    raw_ppe = _get_vals(bs_stmt, "Fixed Assets (Net PPE)")
    raw_gw = _get_vals(bs_stmt, "Intangible Assets & Goodwill")
    raw_loans = [max(0.0, float(a - c - inv - p - g)) for a, c, inv, p, g in zip(raw_tot_assets, raw_cash, raw_inv, raw_ppe, raw_gw)]
    row_loans = _write_statement_row(
        "Premiums Receivable, Reinsurance & Other Policy Assets" if is_ins_hist else "Net Loans, Advances & Customer Receivables",
        raw_loans,
        cfmt_large,
    )

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
    model_type = str(company.get("model_type") or dcf.get("model_type") or ("BANKING_DDM" if is_fin else "STANDARD_FCFF"))
    is_ins = model_type in ("INSURANCE_PNC_DDM", "INSURANCE_LIFE_DDM") or bool(dcf.get("is_insurance"))
    is_reit = model_type == "REIT_INVIT_AFFO" or bool(dcf.get("is_reit"))
    eff_term_g = dcf.get("effective_terminal_growth")
    terminal_growth = eff_term_g if eff_term_g is not None else (overrides.get("terminal_growth") if overrides.get("terminal_growth") is not None else macro.get("terminal_growth", 0.050 if company.get("market") == "IN" else 0.025))

    ws["B2"].value = "Cost of Equity (Ke) via Capital Asset Pricing Model (CAPM)"
    ws["B2"].font = FONT_TITLE
    if is_ins:
        ws["B3"].value = "Insurance Solvency & Policyholder Float — Direct Equity CAPM Framework"
    elif is_reit:
        ws["B3"].value = "REIT / InvIT Distributable Cash Flow (AFFO / NDCF) — Direct Equity CAPM Framework"
    elif is_fin:
        ws["B3"].value = "FIG Capital Structure Assessment — Direct Equity Valuation Framework"
    else:
        ws["B3"].value = "Corporate Direct Equity Valuation — CAPM Cost of Equity Framework"
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
        "Why Policyholder Reserves Are Treated Separately from Financial Debt"
        if is_ins
        else (
            "Why Distributable AFFO / NDCF Is Discounted at Equity Cost of Capital (Ke)"
            if is_reit
            else (
                "Why WACC Is Omitted for Financial Institutions"
                if is_fin
                else "Direct Equity Valuation (DDM / FCFE) vs. Enterprise WACC Note"
            )
        ),
    )
    ws.merge_cells("B18:E21")
    note_cell = ws["B18"]
    if is_ins:
        note_cell.value = (
            "In P&C and Life insurers, unearned premiums, claims reserves, and policyholder liabilities constitute "
            "investable float rather than corporate financing debt. Valuation is conducted on an Ex-AOCI Common "
            "Equity basis using the CAPM Cost of Equity (Ke) to discount distributable equity earnings after solvency "
            "capital retention, capturing underwriting float and stripping mark-to-market bond AOCI volatility."
        )
    elif is_reit:
        note_cell.value = (
            "In REITs and InvITs, high non-cash real estate depreciation depresses accounting EBIT and GAAP Net Income, "
            "while mandatory 90%+ NDCF payout rules govern unitholder returns. Distributable AFFO (FFO less recurring "
            "maintenance CapEx) after acquisition retention is discounted directly at CAPM Cost of Equity (Ke) and "
            "cross-checked against institutional Cap-Rate Gross Asset Value (NOI / Cap Rate) less Net Debt."
        )
    elif is_fin:
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
    company = data.get("company", {})
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    is_fin = bool(company.get("is_financial", True))
    model_type = str(
        company.get("model_type")
        or dcf.get("model_type")
        or ("BANKING_DDM" if is_fin else "STANDARD_FCFF")
    )
    is_ins = model_type in ("INSURANCE_PNC_DDM", "INSURANCE_LIFE_DDM") or bool(dcf.get("is_insurance"))
    is_reit = model_type == "REIT_INVIT_AFFO" or bool(dcf.get("is_reit"))

    sheet_name = "REIT AFFO Model" if is_reit else "DDM & FCFE Model"
    ws = wb.create_sheet(sheet_name)
    ws.sheet_properties.tabColor = TAB_DCF
    ws.views.sheetView[0].showGridLines = True

    cfmt_large = _get_currency_fmt_large(currency)
    cfmt_price = _get_currency_fmt_price(currency)

    n_proj = len(dcf.get("projected_revenue", [0] * 5))
    growth_schedule = dcf.get("growth_schedule", [0.10] * n_proj)
    roe_schedule = dcf.get("roe_schedule", dcf.get("margin_schedule", [0.14] * n_proj))
    base_net_income = float(
        (dcf.get("base_revenue") if is_reit else dcf.get("base_net_income"))
        or data.get("historicals", {}).get("revenue" if is_reit else "net_income", [1e9])[-1]
        or 0.0
    )
    base_bve = float(dcf.get("base_bve", data.get("historicals", {}).get("book_value", [5e9])[-1]) or 0.0)
    current_price = float(market_data.get("current_price", 0.0) or 0.0)
    shares_out = float(dcf.get("shares_used") or market_data.get("diluted_valuation_shares") or market_data.get("shares_outstanding", 1.0) or 1.0)
    bvps = float(dcf.get("bvps", base_bve / shares_out if shares_out > 0 else 0.0) or 0.0)
    use_mid_year_flag = bool(dcf.get("use_mid_year", True))
    term_g_val = float(dcf.get("terminal_growth", data.get("macro", {}).get("terminal_growth", 0.050 if company.get("market") == "IN" else 0.025)) or 0.025)
    start_g_val = float(growth_schedule[0]) if growth_schedule else 0.10
    base_roe_val = float(dcf.get("base_roe", roe_schedule[0] if roe_schedule else 0.14) or 0.14)
    target_roe_val = float(dcf.get("target_roe", roe_schedule[-1] if roe_schedule else 0.14) or 0.14)

    # Title Block
    if is_ins:
        ws["B2"].value = "Multi-Stage Insurance Actuarial Excess-Return & Float DDM"
        ws["B3"].value = f"Ex-AOCI Equity Valuation with Policyholder Float & Solvency Retention — {company.get('ticker', '')}"
    elif is_reit:
        ws["B2"].value = "Multi-Stage REIT / InvIT Distributable AFFO (NDCF) Valuation Model"
        ws["B3"].value = f"Property AFFO Cash Flow Valuation & Institutional Cap-Rate GAV/NAV Cross-Check — {company.get('ticker', '')}"
    else:
        ws["B2"].value = (
            "Multi-Stage Regulatory Capital FCFE & Dividend Discount Model"
            if is_fin
            else "Multi-Stage Dividend Discount (DDM) & Corporate FCFE Model"
        )
        ws["B3"].value = (
            f"Per-Share Equity Valuation with Tier-1 Capital Reinvestment — {company.get('ticker', '')}"
            if is_fin
            else f"Direct Equity Cash Flow Valuation & Justified P/B Cross-Check — {company.get('ticker', '')}"
        )
    ws["B2"].font = FONT_TITLE
    ws["B3"].font = FONT_SUBTITLE
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 18

    # Table Header
    r = 5
    banner_title = (
        "Forecast Schedules & Distributable AFFO / NDCF Cash Flows"
        if is_reit
        else ("Forecast Schedules & Solvency Distributable Earnings (FCFE)" if is_ins else "Forecast Schedules & Free Cash Flow to Equity (FCFE)")
    )
    _set_banner(ws, r, 2, 3 + n_proj, banner_title)
    r += 1

    col_headers = ["Metric / Forecast Line Item", "Base (FY0)"] + [f"Year {i+1}" for i in range(n_proj)]
    _set_table_headers(ws, r, col_headers, start_col=2)
    header_row = r
    r += 1

    # 1. Growth Rate (Row 7)
    ws.cell(row=r, column=2, value="Property Revenue / FFO Growth Rate (g)" if is_reit else "Net Income Growth Rate (g)").font = FONT_LABEL_BOLD
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

    # 2. Base Flow Projections (NI for Bank/Ins/Corp; Rental Revenue for REIT)
    ws.cell(
        row=r,
        column=2,
        value="Projected Rental / Property Revenue" if is_reit else ("Normalized Operating Net Income" if is_ins else "Projected Net Income (Profit After Tax)"),
    ).font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=2).border = THIN_BORDER

    base_ni_val = (
        f"=IF({hist_links['net_income_cell']}>0, {hist_links['net_income_cell']}, {base_net_income})"
        if (not is_ins and not is_reit and hist_links and "net_income_cell" in hist_links)
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

    # 3. ROE / AFFO Margin Schedule
    ws.cell(
        row=r,
        column=2,
        value="Distributable AFFO Margin (% of Revenue)" if is_reit else ("Ex-AOCI Return on Equity (ROE %)" if is_ins else "Return on Equity (ROE %)"),
    ).font = FONT_LABEL
    ws.cell(row=r, column=2).fill = ALT_ROW_FILL
    ws.cell(row=r, column=2).border = THIN_BORDER
    ws.cell(row=r, column=3, value=base_roe_val).number_format = PCT_FMT
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

    # Optional REIT row: Projected Adjusted FFO (AFFO = Revenue * AFFO Margin)
    affo_row = ni_row
    if is_reit:
        ws.cell(row=r, column=2, value="Projected Adjusted FFO (AFFO = Revenue × Margin)").font = FONT_LABEL_BOLD
        ws.cell(row=r, column=2).border = THIN_BORDER
        ws.cell(row=r, column=3, value=float(dcf.get("base_affo") or (base_net_income * base_roe_val))).number_format = cfmt_large
        ws.cell(row=r, column=3).font = FONT_DATA_BOLD
        ws.cell(row=r, column=3).alignment = ALIGN_RIGHT
        ws.cell(row=r, column=3).border = THIN_BORDER
        for i in range(n_proj):
            col = 4 + i
            cur_letter = get_column_letter(col)
            c = ws.cell(row=r, column=col, value=f"={cur_letter}{ni_row}*{cur_letter}{roe_row}")
            c.font = FONT_DATA_BOLD
            c.number_format = cfmt_large
            c.alignment = ALIGN_RIGHT
            c.border = THIN_BORDER
        affo_row = r
        r += 1

    # 4. Retention Rate
    ret_lbl = (
        "Growth & Portfolio Reinvestment Retention (b)"
        if is_reit
        else (
            "Solvency Reserve & Growth Retention (b = g / ROE)"
            if is_ins
            else ("Regulatory Capital Retention Rate (b = g / ROE)" if is_fin else "Equity Retention / Reinvestment Rate (b = g / ROE)")
        )
    )
    ws.cell(row=r, column=2, value=ret_lbl).font = FONT_LABEL
    ws.cell(row=r, column=2).border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).border = THIN_BORDER

    last_bank_col = get_column_letter(3 + n_proj)
    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        next_g_ref = f"{get_column_letter(col + 1)}{growth_row}" if i < n_proj - 1 else ke_links["g_cell"]
        if is_reit:
            ret_formula = f"=MIN(0.25, MAX(0.05, MAX(0, {next_g_ref}-0.70*{ke_links['g_cell']})/0.12))"
        else:
            ret_formula = f"=MIN(0.85, MAX(0.05, {next_g_ref}/MAX({cur_letter}{roe_row}, ${last_bank_col}${roe_row}, 0.95*{cur_letter}{growth_row})))"
        c = ws.cell(row=r, column=col, value=ret_formula)
        c.font = FONT_DATA
        c.number_format = PCT_FMT
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    retention_row = r
    r += 1

    # 5. Equity Capital / AFFO Retained
    ws.cell(
        row=r,
        column=2,
        value="(−) Acquisition & Property Maintenance Retention"
        if is_reit
        else ("(−) Policyholder & Solvency Capital Retained" if is_ins else ("(−) Tier-1 Regulatory Capital Retained" if is_fin else "(−) Retained Earnings Reinvested for Growth")),
    ).font = FONT_LABEL
    ws.cell(row=r, column=2).fill = ALT_ROW_FILL
    ws.cell(row=r, column=2).border = THIN_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL
    ws.cell(row=r, column=3).border = THIN_BORDER

    flow_source_row = affo_row if is_reit else ni_row
    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{flow_source_row}*{cur_letter}{retention_row}")
        c.font = FONT_DATA
        c.fill = ALT_ROW_FILL
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    reinvest_row = r
    r += 1

    # 6. Distributable Cash Flow (FCFE / NDCF)
    ws.cell(
        row=r,
        column=2,
        value="Distributable Unitholder AFFO (NDCF)"
        if is_reit
        else ("Free Cash Flow to Equity (FCFE / Distributable)" if is_fin else "Free Cash Flow to Equity (FCFE / Distributable Dividends)"),
    ).font = FONT_TOTAL
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=2).border = TOTAL_BORDER
    ws.cell(row=r, column=3, value="-").alignment = ALIGN_CENTER
    ws.cell(row=r, column=3).fill = HIGHLIGHT_FILL
    ws.cell(row=r, column=3).border = TOTAL_BORDER

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{flow_source_row}-{cur_letter}{reinvest_row}")
        c.font = FONT_TOTAL
        c.fill = HIGHLIGHT_FILL
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = TOTAL_BORDER
    fcfe_row = r
    r += 1

    # 7. Cumulative Equity / Real-Asset NAV Base
    ws.cell(
        row=r,
        column=2,
        value="Cap-Rate Net Asset Value + Retained AFFO (Memo)" if is_reit else ("Ex-AOCI Book Value of Equity (Cumulative)" if is_ins else "Book Value of Equity (Cumulative)"),
    ).font = FONT_LABEL
    ws.cell(row=r, column=2).border = THIN_BORDER
    base_bve_val = (
        f"=IF({hist_links['book_value_cell']}>0, {hist_links['book_value_cell']}, {base_bve})"
        if (not is_ins and not is_reit and hist_links and "book_value_cell" in hist_links)
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

    first_bank_t = 0.5 if use_mid_year_flag else 1.0
    for i in range(n_proj):
        col = 4 + i
        if i == 0:
            c = ws.cell(row=r, column=col, value=first_bank_t)
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
    _set_banner(
        ws,
        r,
        2,
        5,
        "Calculation of Terminal Value (Gordon Growth on Distributable AFFO / NDCF)"
        if is_reit
        else "Calculation of Terminal Value (Gordon Growth on FCFE)",
    )
    r += 1

    tv_start_row = r
    last_col_letter = get_column_letter(3 + n_proj)

    if is_reit:
        tv_rows = [
            ("Long-Term Terminal Growth Rate (g)", f"=MIN({ke_links['g_cell']}, {ke_links['ke_cell']}-0.02)", PCT_FMT, False),
            ("Steady-State Terminal AFFO Margin (%)", f"={last_col_letter}{roe_row}", PCT_FMT, False),
            ("Terminal Portfolio Growth Retention Rate (b)", f"=MIN(0.25, MAX(0.05, MAX(0, D{tv_start_row}-0.70*D{tv_start_row})/0.12))", PCT_FMT, False),
            ("Normalized Terminal Year AFFO", f"={last_col_letter}{flow_source_row}*(1+D{tv_start_row})", cfmt_large, False),
            ("Normalized Terminal Year Distributable AFFO (NDCF)", f"=D{tv_start_row+3}*(1-D{tv_start_row+2})", cfmt_large, False),
            ("Terminal Equity Value at Year N", f"=IF({ke_links['ke_cell']}>D{tv_start_row}, D{tv_start_row+4}/({ke_links['ke_cell']}-D{tv_start_row}), 0)", cfmt_large, True),
            ("Present Value of Terminal Value", f"=D{tv_start_row+5}*{last_col_letter}{df_row}", cfmt_large, True),
        ]
    else:
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
    _set_banner(ws, r, 2, 5, "Valuation Summary & Implied Fair Value per Unit" if is_reit else "Valuation Summary & Implied Fair Value per Share")
    r += 1

    first_col = get_column_letter(4)
    last_col = get_column_letter(3 + n_proj)
    val_start_row = r

    val_shares_ref_or_num = (
        f"={hist_links['val_shares_cell']}"
        if (not is_reit and not is_ins and hist_links and "val_shares_cell" in hist_links)
        else shares_out
    )
    val_summary_rows = [
        (
            f"Cumulative Present Value of {n_proj}-Yr Distributable AFFO" if is_reit else f"Cumulative Present Value of {n_proj}-Yr FCFEs",
            f"=SUM({first_col}{pv_fcfe_row}:{last_col}{pv_fcfe_row})",
            cfmt_large,
            False,
        ),
        ("Present Value of Terminal Equity Value", f"=D{pv_tv_row}", cfmt_large, False),
        ("Total Implied Equity Value", f"=D{val_start_row}+D{val_start_row+1}", cfmt_large, True),
        ("(÷) Diluted Units Outstanding" if is_reit else "(÷) Diluted Shares Outstanding", val_shares_ref_or_num, INT_FMT, False),
        (
            "Distributable AFFO Fair Value per Unit" if is_reit else ("Actuarial Equity Fair Value per Share" if is_ins else "Multi-Stage DDM / FCFE Fair Value per Share"),
            f"=MAX(0, D{val_start_row+2}/D{val_start_row+3})",
            cfmt_price,
            True,
        ),
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

    # Cross-Check Section (Cap-Rate NAV for REITs; Justified P/B for Banks/Insurers/Corp)
    r += 1
    _set_banner(
        ws,
        r,
        2,
        5,
        "Cross-Check: Institutional Cap-Rate GAV & Net Asset Value (NAV)"
        if is_reit
        else ("Cross-Check: Justified Price-to-Ex-AOCI Book (P/B) Model" if is_ins else "Cross-Check: Justified Price-to-Book (P/B) Model"),
    )
    r += 1
    pb_start_row = r

    if is_reit:
        noi_val = float(dcf.get("noi") or 0.0)
        cap_rate_val = float(dcf.get("benchmark_cap_rate") or 0.06)
        gav_val = float(dcf.get("gav") or (noi_val / cap_rate_val if cap_rate_val > 0 else 0.0))
        nav_eq_val = float(dcf.get("base_bve") or 0.0)
        net_bridge_val = max(0.0, gav_val - nav_eq_val)
        pb_rows = [
            ("Estimated Annual Property NOI", noi_val, cfmt_large, False),
            ("Benchmark Real-Asset Cap Rate (%)", cap_rate_val, PCT_FMT, False),
            ("Implied Gross Asset Value (GAV = NOI / Cap Rate)", f"=D{pb_start_row}/D{pb_start_row+1}", cfmt_large, False),
            ("(−) Net Debt, Preferred & Minority Interest Bridge", net_bridge_val, cfmt_large, False),
            ("Cap-Rate Implied Net Asset Value (NAV)", f"=MAX(0, D{pb_start_row+2}-D{pb_start_row+3})", cfmt_large, True),
            ("Cap-Rate NAV Fair Value per Unit", f"=IF(D{val_start_row+3}>0, D{pb_start_row+4}/D{val_start_row+3}, 0)", cfmt_price, True),
        ]
    else:
        bvps_formula = f"=IF(D{val_start_row+3}>0, C{bve_row}/D{val_start_row+3}, {bvps})"
        pb_rows = [
            ("Ex-AOCI Book Value per Share (BVPS)" if is_ins else "Current Book Value per Share (BVPS)", bvps_formula, cfmt_price, False),
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

    # Chart 3: Projected Distributable Cash Trajectory
    try:
        chart_fcfe = BarChart()
        chart_fcfe.type = "col"
        chart_fcfe.style = 10
        chart_fcfe.title = (
            f"Projected Distributable Unitholder AFFO / NDCF ({currency})"
            if is_reit
            else f"Projected Free Cash Flow to Equity (FCFE) ({currency})"
        )
        chart_fcfe.y_axis.title = f"NDCF ({currency})" if is_reit else f"FCFE ({currency})"
        chart_fcfe.x_axis.title = "Forecast Period"
        chart_fcfe.width = 18
        chart_fcfe.height = 12

        data_fcfe_ref = Reference(ws, min_col=4, min_row=fcfe_row, max_col=3 + n_proj, max_row=fcfe_row)
        s_fcfe = Series(data_fcfe_ref, title="Distributable AFFO (NDCF)" if is_reit else "FCFE (Distributable Cash)")
        chart_fcfe.series.append(s_fcfe)
        chart_fcfe.set_categories(proj_cats_ref)

        ws.add_chart(chart_fcfe, f"{chart_col_letter}4")
    except Exception as e:
        logger.warning("Could not add FCFE chart to Bank DDM Model: %s", e)

    # Chart 4: Projected Earnings / AFFO & Reinvestment Trajectory
    try:
        chart_ni = BarChart()
        chart_ni.type = "col"
        chart_ni.style = 11
        chart_ni.title = (
            f"Projected Adjusted FFO & Portfolio Growth Retained ({currency})"
            if is_reit
            else f"Projected Net Income & Capital Retained ({currency})"
        )
        chart_ni.y_axis.title = f"Amount ({currency})"
        chart_ni.x_axis.title = "Forecast Period"
        chart_ni.width = 18
        chart_ni.height = 12

        data_ni_proj = Reference(ws, min_col=4, min_row=flow_source_row, max_col=3 + n_proj, max_row=flow_source_row)
        data_reinv_proj = Reference(ws, min_col=4, min_row=reinvest_row, max_col=3 + n_proj, max_row=reinvest_row)

        s_ni_proj = Series(data_ni_proj, title="Projected AFFO" if is_reit else "Net Income")
        s_reinv = Series(data_reinv_proj, title="Growth Retained" if is_reit else "Capital Retained")
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

    return {
        "sheet_name": sheet_name,
        "is_ins": is_ins,
        "is_reit": is_reit,
        "price_cell": f"'{sheet_name}'!D{val_start_row+4}",
        "upside_cell": f"'{sheet_name}'!D{val_start_row+6}",
        "eq_cell": f"'{sheet_name}'!D{val_start_row+2}",
        "tg_cell": f"'{sheet_name}'!D{tv_start_row}",
        "ke_cell": ke_links["ke_cell"],
        "g_cell": ke_links["g_cell"],
        "ni_row": ni_row,
        "roe_row": roe_row,
        "affo_row": affo_row,
        "bve_row": bve_row,
        "period_row": period_row,
        "shares_row": val_start_row + 3,
        "price_row": val_start_row + 4,
        "n_proj": n_proj,
        "start_growth": start_g_val,
        "base_roe": base_roe_val,
        "target_roe": target_roe_val,
        "terminal_growth": term_g_val,
        "base_ni": base_net_income,
        "shares_out": shares_out,
        "use_mid_year": use_mid_year_flag,
    }


def _build_bank_sensitivity(wb: Workbook, data: Dict[str, Any], ddm_links: Optional[Dict[str, Any]] = None):
    ws = wb.create_sheet("Sensitivity")
    ws.sheet_properties.tabColor = TAB_SENS
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    sens = data.get("sensitivity", {})
    ddm_links = ddm_links or {}
    model_type = str(company.get("model_type") or dcf.get("model_type") or "BANKING_DDM")
    is_ins = bool(ddm_links.get("is_ins")) or model_type in ("INSURANCE_PNC_DDM", "INSURANCE_LIFE_DDM") or bool(dcf.get("is_insurance"))
    is_reit = bool(ddm_links.get("is_reit")) or model_type == "REIT_INVIT_AFFO" or bool(dcf.get("is_reit"))
    model_sheet = str(ddm_links.get("sheet_name") or ("REIT AFFO Model" if is_reit else "DDM & FCFE Model"))
    cfmt_price = _get_currency_fmt_price(currency)
    cfmt_large = _get_currency_fmt_large(currency)

    # Title Banner
    _set_banner(ws, 2, 2, 8, "Valuation Sensitivity Analysis (2D Dynamic Formula Scenario Matrices)")

    # Reference Values Block
    ws.cell(row=4, column=2, value="Current Unit Price:" if is_reit else "Current Share Price:").font = FONT_LABEL_BOLD
    cmp_cell = ws.cell(row=4, column=3, value=market_data.get("current_price", 0))
    cmp_cell.font = FONT_DATA_BOLD
    cmp_cell.number_format = cfmt_price

    ws.cell(row=4, column=5, value="Base AFFO Fair Value:" if is_reit else ("Base Actuarial Fair Value:" if is_ins else "Base DDM Fair Value:")).font = FONT_LABEL_BOLD
    base_fv_val = f"={ddm_links['price_cell']}" if ddm_links.get("price_cell") else dcf.get("implied_price", 0)
    dcf_cell = ws.cell(row=4, column=6, value=base_fv_val)
    dcf_cell.font = FONT_DATA_BOLD
    dcf_cell.number_format = cfmt_price

    r = 6
    bank_tables = []

    def _render_bank_matrix_shell(title: str, corner_lbl: str, ke_vals: list, col_vals: list, grid_vals: list, mode: str) -> int:
        nonlocal r
        _set_banner(ws, r, 2, 2 + len(col_vals), title)
        r += 1
        ws.row_dimensions[r].height = 22
        corner_cell = ws.cell(row=r, column=2, value=corner_lbl)
        corner_cell.font = FONT_HEADER
        corner_cell.fill = HEADER_FILL
        corner_cell.alignment = ALIGN_CENTER
        corner_cell.border = THIN_BORDER

        for j, c_val in enumerate(col_vals):
            col = 3 + j
            c = ws.cell(row=r, column=col, value=float(c_val))
            c.font = FONT_HEADER
            c.fill = HEADER_FILL
            c.number_format = PCT_FMT
            c.alignment = ALIGN_CENTER
            c.border = THIN_BORDER
        hdr_r = r
        r += 1
        d_start_r = r

        for row_idx, ke_val in enumerate(ke_vals):
            fill = ALT_ROW_FILL if row_idx % 2 == 0 else None
            lbl = ws.cell(row=r, column=2, value=float(ke_val))
            lbl.font = FONT_HEADER
            lbl.fill = HEADER_FILL
            lbl.border = THIN_BORDER
            lbl.number_format = PCT_FMT
            lbl.alignment = ALIGN_CENTER

            for col_idx, _ in enumerate(col_vals):
                val = grid_vals[row_idx][col_idx] if row_idx < len(grid_vals) and col_idx < len(grid_vals[row_idx]) else 0.0
                cell = ws.cell(row=r, column=3 + col_idx, value=float(val))
                cell.font = FONT_DATA_BOLD if (row_idx == len(ke_vals) // 2 and col_idx == len(col_vals) // 2) else FONT_DATA
                cell.fill = fill or PatternFill(fill_type=None)
                cell.border = THIN_BORDER
                cell.number_format = cfmt_price
                cell.alignment = ALIGN_RIGHT
            ws.row_dimensions[r].height = 20
            r += 1

        d_end_r = r - 1
        color_scale = ColorScaleRule(
            start_type="min", start_color="FCA5A5",
            mid_type="percentile", mid_value=50, mid_color="FEF08A",
            end_type="max", end_color="86EFAC",
        )
        last_col_l = get_column_letter(2 + len(col_vals))
        ws.conditional_formatting.add(f"C{d_start_r}:{last_col_l}{d_end_r}", color_scale)
        bank_tables.append({
            "mode": mode,
            "ke_vals": ke_vals,
            "col_vals": col_vals,
            "hdr_r": hdr_r,
            "data_start_r": d_start_r,
        })
        r += 2
        return r

    # Matrix 1: Growth Rate vs Ke
    grid_data = sens.get("growth_wacc", {}) or {}
    ke_range = grid_data.get("wacc_range", [0.08, 0.09, 0.10, 0.11, 0.12])
    g_range = grid_data.get("growth_range", [0.08, 0.09, 0.10, 0.11, 0.12])
    grid = grid_data.get("price_grid") or grid_data.get("grid", [[0] * 5] * 5)
    _render_bank_matrix_shell(
        "Matrix 1: Property Revenue / AFFO Growth (Columns) vs Cost of Equity (Rows)"
        if is_reit
        else "Matrix 1: Net Income Growth Rate (Columns) vs Cost of Equity (Rows)",
        "Cost of Equity (Ke) \\ Growth (g)",
        ke_range,
        g_range,
        grid,
        mode="ni_growth",
    )

    # Matrix 2: Target ROE / AFFO Margin vs Ke
    roe_data = sens.get("margin_wacc", {}) or {}
    ke_range2 = roe_data.get("wacc_range", [0.08, 0.09, 0.10, 0.11, 0.12])
    roe_range = roe_data.get("margin_range") or roe_data.get("roe_range", [0.10, 0.12, 0.14, 0.16, 0.18])
    grid2 = roe_data.get("price_grid") or roe_data.get("grid", [[0] * 5] * 5)
    _render_bank_matrix_shell(
        "Matrix 2: Target AFFO Margin (%) (Columns) vs Cost of Equity (Rows)"
        if is_reit
        else ("Matrix 2: Target Ex-AOCI ROE (%) (Columns) vs Cost of Equity (Rows)" if is_ins else "Matrix 2: Target Return on Equity (ROE) (Columns) vs Cost of Equity (Rows)"),
        "Cost of Equity (Ke) \\ Target AFFO Margin" if is_reit else "Cost of Equity (Ke) \\ Target ROE",
        ke_range2,
        roe_range,
        grid2,
        mode="target_roe",
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # Multi-Year Equity Sensitivity Calculation Audit Engine
    # ═══════════════════════════════════════════════════════════════════════════
    if bank_tables and ddm_links.get("price_cell"):
        n_proj = int(ddm_links.get("n_proj") or 5)
        ni_row = int(ddm_links.get("ni_row") or 8)
        period_row = int(ddm_links.get("period_row") or 14)
        shares_row = int(ddm_links.get("shares_row") or 29)
        last_bank_col = get_column_letter(3 + n_proj)

        _set_banner(ws, r, 2, 5, f"Sensitivity Calibration Parameters (Linked to {model_sheet})")
        r += 1
        p_rows: Dict[str, int] = {}
        bank_params = [
            ("base_ni", "Base Year Property Revenue (FY0)" if is_reit else "Base Year Net Income (FY0)", f"='{model_sheet}'!C{ni_row}", cfmt_large),
            ("start_g", "Base Starting Growth Rate", float(ddm_links.get("start_growth") or 0.10), PCT_FMT),
            ("base_roe", "Base Year AFFO Margin (%)" if is_reit else "Base Year Return on Equity", float(ddm_links.get("base_roe") or 0.14), PCT_FMT),
            ("target_roe", "Target AFFO Margin (%)" if is_reit else "Base Target Return on Equity", float(ddm_links.get("target_roe") or 0.14), PCT_FMT),
            ("term_g", "Terminal Growth Rate (g)", f"={ddm_links['g_cell']}", PCT_FMT),
        ]
        for pk, plbl, pval, pfmt in bank_params:
            ws.cell(row=r, column=2, value=plbl).font = FONT_LABEL
            ws.cell(row=r, column=2).border = THIN_BORDER
            pc = ws.cell(row=r, column=3, value=pval)
            pc.font = FONT_DATA_BOLD
            pc.number_format = pfmt
            pc.alignment = ALIGN_RIGHT
            pc.border = THIN_BORDER
            p_rows[pk] = r
            r += 1

        r += 1
        c_bni = f"$C${p_rows['base_ni']}"
        c_bsg = f"$C${p_rows['start_g']}"
        c_broe = f"$C${p_rows['base_roe']}"
        c_troe = f"$C${p_rows['target_roe']}"
        c_tg = f"$C${p_rows['term_g']}"
        c_sh = f"'{model_sheet}'!$D${shares_row}"

        ni_cols = [get_column_letter(9 + k) for k in range(n_proj)]
        pv_cols = [get_column_letter(9 + n_proj + k) for k in range(n_proj)]
        col_sum_pv = get_column_letter(9 + 2 * n_proj)
        col_pv_tv = get_column_letter(10 + 2 * n_proj)
        col_px_out = get_column_letter(11 + 2 * n_proj)

        hdrs = (
            [
                "Scenario ID",
                "Ke",
                "Start g",
                "Target Margin" if is_reit else "Target ROE",
                "Eff. Start g" if (is_ins or is_reit) else "Clamped Start g",
                "Fade Exp",
                "Eff. Base Margin" if is_reit else "Eff. Base ROE",
            ]
            + [f"{'Rev' if is_reit else 'NI'} Yr{k+1}" for k in range(n_proj)]
            + [f"PV({'NDCF' if is_reit else 'FCFE'}) Yr{k+1}" for k in range(n_proj)]
            + [f"Sum PV({'NDCF' if is_reit else 'FCFE'})", "PV(Terminal Equity)", "Implied Price"]
        )
        _set_banner(
            ws,
            r,
            2,
            1 + len(hdrs),
            f"Multi-Year {'REIT AFFO' if is_reit else ('Insurance DDM' if is_ins else 'Bank DDM / FCFE')} Sensitivity Audit Engine (Live Formulas)",
        )
        r += 1
        _set_table_headers(ws, r, hdrs, start_col=2)
        r += 1

        step_den = max(1, n_proj - 1)
        for t_idx, spec in enumerate(bank_tables, start=1):
            mode = spec["mode"]
            hdr_r = spec["hdr_r"]
            d_start = spec["data_start_r"]
            for i in range(len(spec["ke_vals"])):
                grid_r = d_start + i
                for j in range(len(spec["col_vals"])):
                    grid_col = 3 + j
                    grid_col_l = get_column_letter(grid_col)
                    aud_r = r

                    ke_ref = f"$B{grid_r}"
                    col_ref = f"{grid_col_l}${hdr_r}"

                    sg_in_f = f"={col_ref}" if mode == "ni_growth" else f"={c_bsg}"
                    if is_reit:
                        troe_in_f = f"=MAX(0.08, MIN(0.85, {col_ref}))" if mode == "target_roe" else f"=MAX(0.08, MIN(0.85, {c_troe}))"
                        clamped_sg_f = f"=D{aud_r}"
                        eff_broe_f = f"={c_broe}"
                    elif is_ins:
                        troe_in_f = f"=MAX(0.05, MIN(0.35, {col_ref}))" if mode == "target_roe" else f"=MAX(0.05, MIN(0.35, {c_troe}))"
                        clamped_sg_f = f"=D{aud_r}"
                        eff_broe_f = f"={c_broe}"
                    else:
                        troe_in_f = f"=MAX(0.05, MIN(0.35, {col_ref}))" if mode == "target_roe" else f"=MAX(0.05, MIN(0.35, {c_troe}))"
                        clamped_sg_f = f"=MAX(-0.05, MIN(0.35, D{aud_r}))"
                        eff_broe_f = f"=IF(MAX(0.05, MIN(0.35, {c_broe})) < E{aud_r}*0.90, E{aud_r}, MAX(0.05, MIN(0.35, {c_broe})))"
                    fade_exp_f = f"=1+0.35*MIN(1, MAX(0, (F{aud_r}-{c_tg}-0.03)/0.06))"

                    ws.cell(row=aud_r, column=2, value=f"BM{t_idx}-R{i+1}C{j+1}").font = FONT_DATA
                    ws.cell(row=aud_r, column=3, value=f"={ke_ref}").number_format = PCT_FMT
                    ws.cell(row=aud_r, column=4, value=sg_in_f).number_format = PCT_FMT
                    ws.cell(row=aud_r, column=5, value=troe_in_f).number_format = PCT_FMT
                    ws.cell(row=aud_r, column=6, value=clamped_sg_f).number_format = PCT_FMT
                    ws.cell(row=aud_r, column=7, value=fade_exp_f).number_format = NUM_2DEC_FMT
                    ws.cell(row=aud_r, column=8, value=eff_broe_f).number_format = PCT_FMT

                    for k in range(n_proj):
                        if k == 0:
                            g_k_expr = f"F{aud_r}"
                            prev_ni_ref = c_bni
                        else:
                            g_k_expr = f"(F{aud_r}-(F{aud_r}-{c_tg})*(({k}/{step_den})^G{aud_r}))"
                            prev_ni_ref = f"{ni_cols[k-1]}{aud_r}"
                        ws.cell(row=aud_r, column=9 + k, value=f"={prev_ni_ref}*(1+{g_k_expr})").number_format = cfmt_large

                        if k + 1 < n_proj:
                            g_next_expr = f"(F{aud_r}-(F{aud_r}-{c_tg})*(({k+1}/{step_den})^G{aud_r}))"
                        else:
                            g_next_expr = c_tg
                        roe_k_expr = f"(H{aud_r}+(E{aud_r}-H{aud_r})*({k}/{step_den}))" if n_proj > 1 else f"H{aud_r}"
                        t_ref = f"'{model_sheet}'!${get_column_letter(4+k)}${period_row}"
                        if is_reit:
                            ret_k_expr = f"MIN(0.25, MAX(0.05, MAX(0, ({g_next_expr})-0.70*{c_tg})/0.12))"
                            pv_k_f = f"=({ni_cols[k]}{aud_r}*{roe_k_expr}*(1-{ret_k_expr}))/((1+C{aud_r})^{t_ref})"
                        else:
                            ret_k_expr = f"MIN(0.85, MAX(0.05, ({g_next_expr})/MAX({roe_k_expr}, E{aud_r}, 0.95*({g_k_expr}))))"
                            pv_k_f = f"=({ni_cols[k]}{aud_r}*(1-{ret_k_expr}))/((1+C{aud_r})^{t_ref})"
                        ws.cell(row=aud_r, column=9 + n_proj + k, value=pv_k_f).number_format = cfmt_large

                    ws.cell(row=aud_r, column=9 + 2 * n_proj, value=f"=SUM({pv_cols[0]}{aud_r}:{pv_cols[-1]}{aud_r})").number_format = cfmt_large

                    eff_tg_expr = f"IF((C{aud_r}-{c_tg})<0.020, C{aud_r}-0.020, {c_tg})"
                    last_t_ref = f"'{model_sheet}'!${last_bank_col}${period_row}"
                    if is_reit:
                        term_ret_expr = f"MIN(0.25, MAX(0.05, MAX(0, 0.30*({eff_tg_expr}))/0.12))"
                        term_fcfe_expr = f"({ni_cols[-1]}{aud_r}*E{aud_r}*(1+{eff_tg_expr})*(1-{term_ret_expr}))"
                    else:
                        term_ret_expr = f"MIN(0.95, MAX(0.05, ({eff_tg_expr})/MAX(E{aud_r}, 0.0001)))"
                        term_fcfe_expr = f"({ni_cols[-1]}{aud_r}*(1+{eff_tg_expr})*(1-{term_ret_expr}))"
                    tv_expr = f"IF(C{aud_r}>{c_tg}, ({term_fcfe_expr})/MAX(0.020, C{aud_r}-{c_tg}), 0)"
                    ws.cell(row=aud_r, column=10 + 2 * n_proj, value=f"={tv_expr}/((1+C{aud_r})^{last_t_ref})").number_format = cfmt_large

                    px_out_f = f"=IF(C{aud_r}<={c_tg}, 0, MAX(0, ({col_sum_pv}{aud_r}+{col_pv_tv}{aud_r})/{c_sh}))"
                    ws.cell(row=aud_r, column=11 + 2 * n_proj, value=px_out_f).number_format = cfmt_price

                    ws.cell(row=grid_r, column=grid_col).value = f"={col_px_out}{aud_r}"
                    r += 1

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

                if fname_u == "AND":
                    return all(bool(a) for a in args)
                if fname_u == "OR":
                    return any(bool(a) for a in args)
                if fname_u == "NOT":
                    return not bool(args[0]) if args else False
                if fname_u == "ABS":
                    v = float(args[0]) if args and isinstance(args[0], (int, float)) else 0.0
                    return abs(v)
                if fname_u == "POWER":
                    b = float(args[0]) if args and isinstance(args[0], (int, float)) else 0.0
                    e = float(args[1]) if len(args) > 1 and isinstance(args[1], (int, float)) else 1.0
                    return float(b ** e)

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
                        if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val)):
                            clean_attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
                            v_str = str(int(val)) if isinstance(val, int) else f"{float(val):.12g}"
                            return f'<c r="{coord}"{clean_attrs}><f{fattrs}>{formula}</f><v>{v_str}</v></c>'
                        else:
                            clean_attrs = re.sub(r'\s+t="[^"]*"', "", attrs) + ' t="str"'
                            v_str = "#NUM!" if isinstance(val, float) and not math.isfinite(val) else _xml_escape(str(val))
                            return f'<c r="{coord}"{clean_attrs}><f{fattrs}>{formula}</f><v>{v_str}</v></c>'

                    xml_str = _CELL_FORMULA_XML_RE.sub(_replace_cell, xml_str)
                    data_bytes = xml_str.encode("utf-8")
            zout.writestr(item, data_bytes)

    out_buffer.seek(0)
    return out_buffer


def _build_unsupported_cover(wb: Workbook, data: Dict[str, Any]):
    """Build a fail-closed Cover notice workbook when a security/sector is UNSUPPORTED_MODEL."""
    ws = wb.active
    ws.title = "Cover"
    ws.sheet_properties.tabColor = TAB_COVER
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    validation = data.get("validation_gate") or data.get("validation") or {}
    suitability = data.get("model_suitability") or company.get("model_suitability") or validation.get("model_suitability") or {}

    ws["B2"].value = f"{company.get('name', company.get('ticker', 'Security'))} ({company.get('ticker', '')})"
    ws["B2"].font = FONT_TITLE
    ws["B3"].value = "Valuation Gate Notice — Unsupported Sector / Model Methodology Blocked (Fail-Closed)"
    ws["B3"].font = FONT_SUBTITLE

    _set_banner(ws, 5, 2, 5, "Validation Gate & Model Suitability Decision")
    rows = [
        ("Validation Status", str(validation.get("validation_status") or "UNSUPPORTED_MODEL")),
        ("Detected Model Family", str(suitability.get("model_family") or "UNSUPPORTED_MODEL")),
        ("Sector / Industry", f"{company.get('sector', 'Unknown')} / {company.get('industry', 'Unknown')}"),
        ("Block / Routing Reason", str(suitability.get("reason") or validation.get("model_suitability_note") or "Corporate FCFF DCF and Bank DDM are economically invalid for this sector.")),
        ("Required Valuation Methodology", str(suitability.get("recommended_methodology") or "Sector-Specific Valuation (Embedded Value for Insurance; NAV / P-AFFO for REIT/InvIT)")),
        ("Valuation Export Status", "DCF Model, Sensitivity, and Monte Carlo sheets omitted cleanly (fail-closed gate active)."),
    ]
    r = 6
    for lbl, val in rows:
        lc = ws.cell(row=r, column=2, value=lbl)
        lc.font = FONT_LABEL_BOLD
        lc.fill = BLOCKED_FILL if "Status" in lbl or "Blocked" in val else ALT_ROW_FILL
        lc.border = THIN_BORDER
        vc = ws.cell(row=r, column=3, value=val)
        row_fill = BLOCKED_FILL if r == 6 else (ALT_ROW_FILL if r % 2 == 0 else PatternFill(fill_type=None))
        vc.font = FONT_DATA_BOLD if r == 6 else FONT_DATA
        vc.fill = row_fill
        vc.border = THIN_BORDER
        vc.alignment = ALIGN_LEFT
        for c in (4, 5):
            ws.cell(row=r, column=c).border = THIN_BORDER
            ws.cell(row=r, column=c).fill = row_fill
        ws.row_dimensions[r].height = 22
        r += 1

    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 76
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 14


# ═══════════════════════════════════════════════════════════════════════════
# Public API Entrypoint
# ═══════════════════════════════════════════════════════════════════════════

def generate_excel_report(analysis_data: Dict[str, Any]) -> BytesIO:
    """
    Generate a professional Damodaran-grade Excel workbook (.xlsx)
    from the valuation analysis data.

    Supports dual routing and fail-closed validation gating:
      - UNSUPPORTED_MODEL (Insurance / REIT / InvIT): Fail-closed Gate Notice Cover only
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
        validation = analysis_data.get("validation_gate") or analysis_data.get("validation") or {}
        val_status = str(validation.get("validation_status") or "")
        suitability = analysis_data.get("model_suitability") or analysis_data.get("company", {}).get("model_suitability") or {}
        if val_status == "UNSUPPORTED_MODEL" or suitability.get("supported") is False or suitability.get("validation_status") == "UNSUPPORTED_MODEL":
            logger.info("Generating fail-closed UNSUPPORTED_MODEL Gate Notice Excel Workbook")
            _build_unsupported_cover(wb, analysis_data)
        else:
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

            if is_financial or model_type in ("BANKING_DDM", "NBFC_LENDER_DDM", "INSURANCE_PNC_DDM", "INSURANCE_LIFE_DDM"):
                logger.info("Generating dedicated %s Equity Excel Workbook", model_type)
                _build_bank_cover(wb, analysis_data)
                hist_links = _build_bank_historicals(wb, analysis_data)
                ke_links = _build_bank_cost_of_equity(wb, analysis_data)
                ddm_links = _build_bank_ddm_model(wb, analysis_data, ke_links, hist_links)
                _build_bank_sensitivity(wb, analysis_data, ddm_links)
                _build_monte_carlo(wb, analysis_data, ddm_links)
            elif model_type in ("CORPORATE_DDM", "REIT_INVIT_AFFO"):
                logger.info("Generating dedicated %s Equity Excel Workbook", model_type)
                _build_bank_cover(wb, analysis_data)
                hist_links = _build_historicals(wb, analysis_data)
                ke_links = _build_bank_cost_of_equity(wb, analysis_data)
                ddm_links = _build_bank_ddm_model(wb, analysis_data, ke_links, hist_links if isinstance(hist_links, dict) else None)
                _build_bank_sensitivity(wb, analysis_data, ddm_links)
                _build_monte_carlo(wb, analysis_data, ddm_links)
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
