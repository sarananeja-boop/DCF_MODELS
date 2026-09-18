"""
Formatted Excel Workbook Generator — Institutional Grade
=========================================================
Produces a comprehensive, multi-sheet institutional DCF model in Excel (.xlsx)
matching the Damodaran institutional model format (as in HUL FINAL MODEL.xlsx).

Sheets Included:
  1. Cover: Executive Summary, Verdict & Metadata
  2. Historical Financials: 4+ Years Statements, YoY Growth, Margins, FCFF & Balance Sheet
  3. WACC 2: Live CAPM Cost of Equity, Cost of Debt & Capital Structure
  4. DCF Model: Multi-stage Projections, Live Formulas linking to WACC 2 & Historicals,
                Terminal Value & Enterprise Value to Equity Bridge
  5. Sensitivity: 2D Implied Price Grids (Growth × WACC & Margin × WACC)
  6. Monte Carlo: Statistical Summary, Confidence Bands (VaR), Distribution Table
                  and an Embedded Native Excel Histogram BarChart.
"""

import logging
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
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
# Institutional Style Constants & Palettes
# ═══════════════════════════════════════════════════════════════════════════

# Colors
NAVY_PRIMARY = "002060"       # Institutional Deep Navy (HUL / Damodaran theme)
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
    """Create an institutional navy banner header row."""
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

def _build_cover(wb: Workbook, data: Dict[str, Any]):
    ws = wb.active
    ws.title = "Cover"
    ws.sheet_properties.tabColor = TAB_COVER
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    market_data = data.get("market_data", {})
    macro = data.get("macro", {})
    dcf = data.get("dcf_result", {})
    mc = data.get("monte_carlo", {})
    mc_stats = mc.get("stats", {})
    verdict = data.get("verdict", {})
    currency = company.get("currency", "USD")
    curr_sym = _get_curr_symbol(currency)
    cfmt_price = _get_currency_fmt_price(currency)
    cfmt_large = _get_currency_fmt_large(currency)

    # Title Block
    ws["B2"].value = company.get("name", "Corporate Valuation Model")
    ws["B2"].font = FONT_TITLE
    ws["B3"].value = f"Institutional DCF Valuation & Risk Assessment Model — {company.get('ticker', '')}"
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
    upside = verdict.get("upside_pct", 0)
    mc_median = mc_stats.get("median", 0)
    p25 = mc_stats.get("p25", 0)
    p75 = mc_stats.get("p75", 0)

    val_summary_items = [
        ("Current Market Price (CMP)", current_price, cfmt_price, False),
        ("DCF Implied Fair Value (Base Case)", implied_price, cfmt_price, True),
        ("Implied Upside / (Downside)", upside, PCT_FMT, True),
        ("Investment Verdict", verdict.get("verdict", "FAIR VALUE"), None, True),
        ("Monte Carlo Median Implied Price", mc_median, cfmt_price, False),
        ("Monte Carlo 50% Confidence Range (P25 – P75)", f"{curr_sym}{p25:,.2f} – {curr_sym}{p75:,.2f}" if p25 else "N/A", None, False),
    ]

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
        val_cell.alignment = ALIGN_RIGHT
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

    rf = macro.get("risk_free_rate", 0)
    beta = market_data.get("beta", 1.0)
    ke = wacc_data.get("cost_of_equity", 0)
    kd = wacc_data.get("cost_of_debt", 0)
    wacc_val = wacc_data.get("wacc", 0)
    term_g = overrides.get("terminal_growth") if overrides.get("terminal_growth") is not None else macro.get("terminal_growth", 0.055 if company.get("market") == "IN" else 0.025)
    ebit_m = historicals.get("avg_ebit_margin", 0)

    driver_items = [
        ("Risk-Free Rate (Rf)", rf, PCT_FMT),
        ("Beta (Levered)", beta, NUM_2DEC_FMT),
        ("Cost of Equity (Ke via CAPM)", ke, PCT_FMT),
        ("After-Tax Cost of Debt (Kd)", kd, PCT_FMT),
        ("Weighted Average Cost of Capital (WACC)", wacc_val, PCT_FMT),
        ("Terminal Growth Rate (g)", term_g, PCT_FMT),
        ("Normalized Operating Margin (EBIT Margin)", ebit_m, PCT_FMT),
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

    # Verdict Description box
    desc = verdict.get("description", "")
    if desc:
        r += 1
        ws.merge_cells(f"B{r}:E{r+1}")
        desc_cell = ws.cell(row=r, column=2, value=f"Note: {desc}")
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
    historicals = data.get("historicals", {})

    years = historicals.get("years", [])
    if not years:
        years = ["Year 1", "Year 2", "Year 3", "Year 4"]
    n_years = len(years)

    revenues = historicals.get("revenue", [])
    ebit = historicals.get("ebit", [])
    capex = historicals.get("capex", [])
    dna = historicals.get("dna", [])
    dnwc = historicals.get("delta_nwc", [])

    # Banner Header
    r = 2
    end_col = 2 + n_years + 2  # Metric + Years + Average + StdDev
    _set_banner(ws, r, 2, end_col, f"Historical Financial Statements & DCF Calibration Drivers — {company.get('name', '')}")
    r += 2

    # Headers
    headers = ["Financial Statement Item"] + [f"FY {y}" for y in years] + ["Historical Average", "Standard Deviation"]
    _set_table_headers(ws, r, headers, start_col=2)
    header_row = r
    r += 1

    # Helper to write statement row with formula average & std dev
    def _write_statement_row(label: str, values: List[float], fmt: str, is_bold: bool = False,
                             is_growth: bool = False, is_margin: bool = False):
        nonlocal r
        fill = HIGHLIGHT_FILL if is_bold else (ALT_ROW_FILL if r % 2 == 0 else None)
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD if is_bold else FONT_LABEL
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        first_col_letter = get_column_letter(3)
        last_col_letter = get_column_letter(2 + n_years)

        for idx in range(n_years):
            col = 3 + idx
            cell = ws.cell(row=r, column=col)
            cell.font = FONT_DATA_BOLD if is_bold else FONT_DATA
            cell.fill = fill or PatternFill(fill_type=None)
            cell.border = THIN_BORDER
            cell.alignment = ALIGN_RIGHT
            cell.number_format = fmt

            if is_growth:
                if idx == 0:
                    cell.value = "-"
                    cell.alignment = ALIGN_CENTER
                else:
                    prev_col = get_column_letter(col - 1)
                    cur_col = get_column_letter(col)
                    rev_row = header_row + 1
                    cell.value = f"=({cur_col}{rev_row}-{prev_col}{rev_row})/{prev_col}{rev_row}"
            elif is_margin:
                cur_col = get_column_letter(col)
                rev_row = header_row + 1
                ebit_row = header_row + 3
                cell.value = f"={cur_col}{ebit_row}/{cur_col}{rev_row}"
            else:
                val = values[idx] if idx < len(values) else 0.0
                cell.value = val

        # Historical Average Column
        avg_col = 3 + n_years
        avg_cell = ws.cell(row=r, column=avg_col)
        avg_cell.font = FONT_DATA_BOLD
        avg_cell.fill = fill or PatternFill(fill_type=None)
        avg_cell.border = THIN_BORDER
        avg_cell.alignment = ALIGN_RIGHT
        avg_cell.number_format = fmt

        # Historical Std Dev Column
        std_col = avg_col + 1
        std_cell = ws.cell(row=r, column=std_col)
        std_cell.font = FONT_DATA
        std_cell.fill = fill or PatternFill(fill_type=None)
        std_cell.border = THIN_BORDER
        std_cell.alignment = ALIGN_RIGHT
        std_cell.number_format = fmt

        if is_growth:
            # YoY growth starts at column 2 (Col D)
            start_growth_col = get_column_letter(4)
            avg_cell.value = f"=AVERAGE({start_growth_col}{r}:{last_col_letter}{r})"
            std_cell.value = f"=STDEV.S({start_growth_col}{r}:{last_col_letter}{r})"
        else:
            avg_cell.value = f"=AVERAGE({first_col_letter}{r}:{last_col_letter}{r})"
            std_cell.value = f"=STDEV.S({first_col_letter}{r}:{last_col_letter}{r})"

        r += 1

    # Row 1: Revenues
    _write_statement_row("Revenues / Net Sales", revenues, cfmt_large, is_bold=True)
    # Row 2: YoY Growth
    _write_statement_row("YoY Revenue Growth Rate", [], PCT_FMT, is_growth=True)
    # Row 3: Operating Profit (EBIT)
    _write_statement_row("EBIT (Operating Income)", ebit, cfmt_large, is_bold=True)
    # Row 4: EBIT Margin
    _write_statement_row("EBIT Margin (%)", [], PCT_FMT, is_margin=True)
    # Row 5: D&A
    _write_statement_row("Depreciation & Amortization (D&A)", dna, cfmt_large)
    # Row 6: CapEx
    _write_statement_row("Capital Expenditures (CapEx)", capex, cfmt_large)
    # Row 7: ΔNWC
    _write_statement_row("Change in Net Working Capital (ΔNWC)", dnwc, cfmt_large)

    # Balance Sheet Snapshot
    r += 2
    _set_banner(ws, r, 2, end_col, "Balance Sheet & Capitalization Snapshot (Latest Filing)")
    r += 1

    market_data = data.get("market_data", {})
    wacc_data = data.get("wacc", {})
    cash_val = historicals.get("cash_and_equivalents", 0)
    debt_val = wacc_data.get("total_debt", 0)
    shares_val = market_data.get("shares_outstanding", 0)
    mcap_val = market_data.get("market_cap", 0)

    bs_items = [
        ("Cash & Short-Term Investments", cash_val, cfmt_large, "C"),
        ("Total Debt (Short-Term + Long-Term)", debt_val, cfmt_large, "D"),
        ("Net Debt (Debt − Cash)", None, cfmt_large, "ND"),
        ("Shares Outstanding", shares_val, INT_FMT, "S"),
        ("Market Capitalization", mcap_val, cfmt_large, "MC"),
    ]

    cash_cell_coord = ""
    for idx, (label, val, fmt, code) in enumerate(bs_items):
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER
        lbl.alignment = ALIGN_LEFT

        val_cell = ws.cell(row=r, column=3)
        val_cell.font = FONT_DATA_BOLD if code == "ND" else FONT_DATA
        val_cell.fill = fill or PatternFill(fill_type=None)
        val_cell.border = THIN_BORDER
        val_cell.alignment = ALIGN_RIGHT
        val_cell.number_format = fmt

        if code == "C":
            val_cell.value = val
            cash_cell_coord = f"'Historical Financials'!C{r}"
        elif code == "ND":
            val_cell.value = f"=C{r-1}-C{r-2}"
        else:
            val_cell.value = val

        for col in range(4, end_col + 1):
            ec = ws.cell(row=r, column=col)
            ec.fill = fill or PatternFill(fill_type=None)
            ec.border = THIN_BORDER
        r += 1

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=16, max_width=35)
    ws.freeze_panes = "C6"
    return cash_cell_coord


# ═══════════════════════════════════════════════════════════════════════════
# Sheet 3: WACC 2 (CAPM, Cost of Debt & Capital Weights)
# ═══════════════════════════════════════════════════════════════════════════

def _build_wacc2(wb: Workbook, data: Dict[str, Any]) -> Dict[str, str]:
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
    terminal_growth = overrides.get("terminal_growth") if overrides.get("terminal_growth") is not None else macro.get("terminal_growth", 0.055 if company.get("market") == "IN" else 0.025)

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
    capm_rows = [
        (8, "Risk Free Rate", "=E4", PCT_FMT, False),
        (9, "Beta (Levered)", beta, NUM_2DEC_FMT, False),
        (10, "Expected Market Return (Rm)", market_return, PCT_FMT, False),
        (11, "Equity Risk Premium (Rm − Rf)", "=E10-E8", PCT_FMT, False),
        (12, "Cost of Equity (Ke)", "=E8+E9*E11", PCT_FMT, True),
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
    # wacc_data["cost_of_debt"] is the pre-tax cost of debt from compute_wacc
    pre_tax_kd = wacc_data.get("cost_of_debt", 0.04)

    debt_rows = [
        (15, "Total Debt (D)", total_debt, cfmt_large, False),
        (16, "Pre-Tax Cost of Debt", pre_tax_kd, PCT_FMT, False),
        (17, "Marginal Tax Rate (T)", tax_rate, PCT_FMT, False),
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
    wacc_rows = [
        (21, "Market Capitalization (E)", market_cap, cfmt_large, False),
        (22, "Total Debt (D)", "=E15", cfmt_large, False),
        (23, "Total Capital (V = E + D)", "=E21+E22", cfmt_large, False),
        (24, "Weight of Debt (Wd = D / V)", "=IF(E23>0, E22/E23, 0)", PCT_FMT, False),
        (25, "Weight of Equity (We = 1 − Wd)", "=1-E24", PCT_FMT, False),
        (26, "Cost of Capital (WACC)", "=(E12*E25)+(E18*E24)", PCT_FMT, True),
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
        "wacc_cell": "'WACC 2'!$E$26",
        "terminal_g_cell": "'WACC 2'!$E$5",
        "ke_cell": "'WACC 2'!$E$12",
        "kd_cell": "'WACC 2'!$E$18",
        "debt_cell": "'WACC 2'!$E$15",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Sheet 4: DCF Model (Multi-Stage DCF, Terminal Value & Equity Bridge)
# ═══════════════════════════════════════════════════════════════════════════

def _build_dcf_model(wb: Workbook, data: Dict[str, Any], wacc_links: Dict[str, str], cash_cell_ref: str):
    ws = wb.create_sheet("DCF Model")
    ws.sheet_properties.tabColor = TAB_DCF
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    macro = data.get("macro", {})
    dcf = data.get("dcf_result", {})
    historicals = data.get("historicals", {})
    verdict = data.get("verdict", {})

    cfmt_price = _get_currency_fmt_price(currency)
    cfmt_large = _get_currency_fmt_large(currency)

    growth_schedule = dcf.get("growth_schedule", [0.05] * 5)
    margin_schedule = dcf.get("margin_schedule", [historicals.get("avg_ebit_margin", 0.15)] * 5)
    proj_rev = dcf.get("projected_revenue", [])
    proj_nopat = dcf.get("projected_nopat", [])
    n_proj = len(growth_schedule)

    # Tax rate from macro profile (25.17% for IN, 21.00% for US)
    tax_rate_dcf = macro.get("tax_rate", 0.2517 if company.get("market") == "IN" else 0.21)

    avg_dna_pct = historicals.get("avg_dna_pct", 0.02)
    avg_capex_pct = historicals.get("avg_capex_pct", 0.03)
    norm_nwc_pct = dcf.get("normalized_nwc_to_revenue", historicals.get("normalized_nwc_to_revenue", historicals.get("avg_dnwc_pct", 0.01)))
    last_revenue = historicals.get("revenue", [-1])[-1] if historicals.get("revenue") else (proj_rev[0] / (1 + growth_schedule[0]) if proj_rev else 1e9)

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

    # 2. Revenue Projections (Live Formula: =Prev_Rev * (1 + g))
    lbl2 = ws.cell(row=r, column=2, value="Revenue / Turnover")
    lbl2.font = FONT_LABEL_BOLD
    lbl2.border = THIN_BORDER
    base_rev_cell = ws.cell(row=r, column=3, value=last_revenue)
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

    # 3. Operating Margin Schedule
    lbl3 = ws.cell(row=r, column=2, value="Operating Margin (EBIT Margin)")
    lbl3.font = FONT_LABEL
    lbl3.fill = ALT_ROW_FILL
    lbl3.border = THIN_BORDER
    ws.cell(row=r, column=3, value=historicals.get("avg_ebit_margin", 0.15)).number_format = PCT_FMT
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
    margin_row = r
    r += 1

    # 4. EBIT (Live Formula: =Revenue * Margin)
    lbl4 = ws.cell(row=r, column=2, value="EBIT (Operating Income)")
    lbl4.font = FONT_LABEL_BOLD
    lbl4.border = THIN_BORDER
    ws.cell(row=r, column=3, value=f"=C{rev_row}*C{margin_row}").number_format = cfmt_large
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

    # 7. Add: D&A (=Revenue * avg_dna_pct)
    lbl7 = ws.cell(row=r, column=2, value="(+) Depreciation & Amortization")
    lbl7.font = FONT_LABEL
    lbl7.fill = ALT_ROW_FILL
    lbl7.border = THIN_BORDER
    ws.cell(row=r, column=3, value=f"=C{rev_row}*{avg_dna_pct}").number_format = cfmt_large
    ws.cell(row=r, column=3).font = FONT_DATA
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{rev_row}*{avg_dna_pct}")
        c.font = FONT_DATA
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
        c.fill = ALT_ROW_FILL
    dna_row = r
    r += 1

    # 8. Less: CapEx (=Revenue * avg_capex_pct)
    lbl8 = ws.cell(row=r, column=2, value="(−) Capital Expenditures (CapEx)")
    lbl8.font = FONT_LABEL
    lbl8.border = THIN_BORDER
    ws.cell(row=r, column=3, value=f"=C{rev_row}*{avg_capex_pct}").number_format = cfmt_large
    ws.cell(row=r, column=3).font = FONT_DATA
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        col = 4 + i
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={cur_letter}{rev_row}*{avg_capex_pct}")
        c.font = FONT_DATA
        c.number_format = cfmt_large
        c.alignment = ALIGN_RIGHT
        c.border = THIN_BORDER
    capex_row = r
    r += 1

    # 9. Less: Change in NWC (=norm_nwc_pct * (Rev_t - Rev_{t-1}))
    lbl9 = ws.cell(row=r, column=2, value="(−) Change in Net Working Capital (ΔNWC)")
    lbl9.font = FONT_LABEL
    lbl9.fill = ALT_ROW_FILL
    lbl9.border = THIN_BORDER
    ws.cell(row=r, column=3, value=0.0).number_format = cfmt_large
    ws.cell(row=r, column=3).font = FONT_DATA
    ws.cell(row=r, column=3).border = THIN_BORDER
    ws.cell(row=r, column=3).fill = ALT_ROW_FILL
    ws.cell(row=r, column=3).alignment = ALIGN_RIGHT

    for i in range(n_proj):
        col = 4 + i
        prev_letter = get_column_letter(col - 1)
        cur_letter = get_column_letter(col)
        c = ws.cell(row=r, column=col, value=f"={norm_nwc_pct}*({cur_letter}{rev_row}-{prev_letter}{rev_row})")
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
    _set_banner(ws, r, 2, 5, "Calculation of Terminal Value (Gordon Growth Model)")
    r += 1

    last_col_letter = get_column_letter(3 + n_proj)
    term_g_ref = wacc_links["terminal_g_cell"]

    tv_start_row = r
    ws.cell(row=r, column=2, value="Final Forecast Year FCFF (Year N)").font = FONT_LABEL
    ws.cell(row=r, column=4, value=f"={last_col_letter}{fcff_row}").font = FONT_DATA_BOLD
    ws.cell(row=r, column=4).number_format = cfmt_large
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    r += 1

    ws.cell(row=r, column=2, value="Long-Term Terminal Growth Rate (g)").font = FONT_LABEL
    ws.cell(row=r, column=4, value=f"={term_g_ref}").font = FONT_DATA_BOLD
    ws.cell(row=r, column=4).number_format = PCT_FMT
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    tg_row = r
    r += 1

    ws.cell(row=r, column=2, value="Cost of Capital (WACC)").font = FONT_LABEL
    ws.cell(row=r, column=4, value=f"={wacc_ref}").font = FONT_DATA_BOLD
    ws.cell(row=r, column=4).number_format = PCT_FMT
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    wacc_param_row = r
    r += 1

    ws.cell(row=r, column=2, value="Normalized Terminal Year FCFF (n+1)").font = FONT_LABEL
    ws.cell(row=r, column=4, value=f"=D{tv_start_row}*(1+D{tg_row})").font = FONT_DATA_BOLD
    ws.cell(row=r, column=4).number_format = cfmt_large
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    n1_row = r
    r += 1

    ws.cell(row=r, column=2, value="Terminal Value at Year N").font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    tv_cell = ws.cell(row=r, column=4, value=f"=IF(D{wacc_param_row}>D{tg_row}, D{n1_row}/(D{wacc_param_row}-D{tg_row}), 0)")
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

    # 6. Implied Equity Value
    ws.cell(row=r, column=2, value="Implied Equity Value").font = FONT_LABEL_BOLD
    ws.cell(row=r, column=2).fill = HIGHLIGHT_FILL
    eq_cell = ws.cell(row=r, column=4, value=f"=D{ev_row}+D{cash_row}-D{debt_row}")
    eq_cell.font = FONT_TOTAL
    eq_cell.number_format = cfmt_large
    eq_cell.alignment = ALIGN_RIGHT
    eq_cell.fill = HIGHLIGHT_FILL
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = TOTAL_BORDER
    eq_row = r
    r += 1

    # 7. Shares Outstanding
    shares_cnt = market_data.get("shares_outstanding", 1)
    ws.cell(row=r, column=2, value="(÷) Diluted Shares Outstanding").font = FONT_LABEL
    ws.cell(row=r, column=4, value=shares_cnt).font = FONT_DATA
    ws.cell(row=r, column=4).number_format = INT_FMT
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    shares_row = r
    r += 1

    # 8. Implied Share Price
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

    # 9. Current Market Price
    cmp_val = market_data.get("current_price", 0)
    ws.cell(row=r, column=2, value="Current Market Price (CMP)").font = FONT_LABEL
    ws.cell(row=r, column=4, value=cmp_val).font = FONT_DATA
    ws.cell(row=r, column=4).number_format = cfmt_price
    ws.cell(row=r, column=4).alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    cmp_row = r
    r += 1

    # 10. Upside / Downside %
    ws.cell(row=r, column=2, value="Implied Upside / (Downside)").font = FONT_LABEL_BOLD
    upside_cell = ws.cell(row=r, column=4, value=f"=IF(D{cmp_row}>0, (D{price_row}-D{cmp_row})/D{cmp_row}, 0)")
    upside_cell.font = FONT_DATA_BOLD
    upside_cell.number_format = PCT_FMT
    upside_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = THIN_BORDER
    r += 1

    # 11. Verdict
    ws.cell(row=r, column=2, value="Valuation Verdict").font = FONT_LABEL_BOLD
    v_cell = ws.cell(row=r, column=4, value=verdict.get("verdict", "FAIR VALUE"))
    v_cell.font = FONT_LABEL_BOLD
    v_cell.alignment = ALIGN_RIGHT
    for c in (2, 3, 4, 5):
        ws.cell(row=r, column=c).border = TOTAL_BORDER

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=18, max_width=42)



# ═══════════════════════════════════════════════════════════════════════════
# Sheet 5: Sensitivity Analysis (2D Implied Price Grids)
# ═══════════════════════════════════════════════════════════════════════════

def _build_sensitivity(wb: Workbook, data: Dict[str, Any]):
    ws = wb.create_sheet("Sensitivity")
    ws.sheet_properties.tabColor = TAB_SENS
    ws.views.sheetView[0].showGridLines = True

    sens = data.get("sensitivity", {})
    gw = sens.get("growth_wacc", {})
    mw = sens.get("margin_wacc", {})
    company = data.get("company", {})
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})

    cfmt_price = _get_currency_fmt_price(currency)

    # Title Banner
    _set_banner(ws, 2, 2, 8, "Valuation Sensitivity Analysis (2D Scenario Price Matrix)")

    # Reference Values Block
    ws.cell(row=4, column=2, value="Current Share Price:").font = FONT_LABEL_BOLD
    cmp_cell = ws.cell(row=4, column=3, value=market_data.get("current_price", 0))
    cmp_cell.font = FONT_DATA_BOLD
    cmp_cell.number_format = cfmt_price

    ws.cell(row=4, column=5, value="Base DCF Fair Value:").font = FONT_LABEL_BOLD
    dcf_cell = ws.cell(row=4, column=6, value=dcf.get("implied_price", 0))
    dcf_cell.font = FONT_DATA_BOLD
    dcf_cell.number_format = cfmt_price

    r = 6
    # Helper for 2D sensitivity table
    def _render_sensitivity_table(start_row: int, title: str, row_label: str, row_vals: list,
                                  col_label: str, col_vals: list, price_grid: list) -> int:
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
            c = ws.cell(row=cur_r, column=col, value=c_val)
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

        for i, (r_val, row_prices) in enumerate(zip(row_vals, price_grid)):
            row_lbl = ws.cell(row=cur_r, column=2, value=r_val)
            row_lbl.font = FONT_HEADER
            row_lbl.fill = HEADER_FILL
            row_lbl.number_format = PCT_FMT
            row_lbl.alignment = ALIGN_CENTER
            row_lbl.border = THIN_BORDER

            for j, price in enumerate(row_prices):
                col = 3 + j
                cell = ws.cell(row=cur_r, column=col, value=price)
                cell.font = FONT_DATA
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

    # Table 1: Revenue Growth vs. WACC
    g_range = gw.get("growth_range", [])
    w_range = gw.get("wacc_range", [])
    grid1 = gw.get("price_grid", [])
    if g_range and w_range and grid1:
        r = _render_sensitivity_table(
            r,
            "Sensitivity Table 1: Revenue Growth Rate (%) vs. Cost of Capital / WACC (%)",
            "Revenue Growth",
            g_range,
            "WACC",
            w_range,
            grid1,
        )

    # Table 2: Operating Margin vs. WACC
    m_range = mw.get("margin_range", [])
    w_range2 = mw.get("wacc_range", [])
    grid2 = mw.get("price_grid", [])
    if m_range and w_range2 and grid2:
        r = _render_sensitivity_table(
            r,
            "Sensitivity Table 2: Operating Margin (%) vs. Cost of Capital / WACC (%)",
            "EBIT Margin",
            m_range,
            "WACC",
            w_range2,
            grid2,
        )

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=16, max_width=30)
    ws.freeze_panes = "C6"


# ═══════════════════════════════════════════════════════════════════════════
# Sheet 6: Monte Carlo Simulation (VaR, Stats, Table & Native BarChart)
# ═══════════════════════════════════════════════════════════════════════════

def _build_monte_carlo(wb: Workbook, data: Dict[str, Any]):
    ws = wb.create_sheet("Monte Carlo")
    ws.sheet_properties.tabColor = TAB_MC
    ws.views.sheetView[0].showGridLines = True

    company = data.get("company", {})
    currency = company.get("currency", "USD")
    market_data = data.get("market_data", {})
    mc = data.get("monte_carlo", {})
    mc_stats = mc.get("stats", {})

    cfmt_price = _get_currency_fmt_price(currency)
    curr_sym = _get_curr_symbol(currency)
    current_price = market_data.get("current_price", 0)

    # Title Banner
    _set_banner(ws, 2, 2, 5, "Monte Carlo Risk Simulation & Probabilistic Fair Value Distribution")

    # Section 1: Summary Statistics (Left Column)
    r = 4
    _set_banner(ws, r, 2, 5, "Monte Carlo Simulation Summary & Statistics")
    r += 1

    stats_items = [
        ("Total Simulation Runs", mc.get("actual_iterations", 10000), INT_FMT),
        ("Mean Implied Share Price", mc_stats.get("mean"), cfmt_price),
        ("Median Implied Share Price", mc_stats.get("median"), cfmt_price),
        ("Standard Deviation", mc_stats.get("std_dev"), cfmt_price),
        ("Minimum Simulated Price", mc_stats.get("min_raw_share_price"), cfmt_price),
        ("Maximum Simulated Price", mc_stats.get("max_share_price"), cfmt_price),
        ("Distressed / Zero-Price Runs %", mc_stats.get("zero_price_pct", 0.0) / 100.0 if mc_stats.get("zero_price_pct", 0) > 1 else mc_stats.get("zero_price_pct", 0.0), PCT_FMT),
        ("Current Market Price (CMP)", current_price, cfmt_price),
    ]

    for label, val, fmt in stats_items:
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        lbl = ws.cell(row=r, column=2, value=label)
        lbl.font = FONT_LABEL_BOLD
        lbl.fill = fill or PatternFill(fill_type=None)
        lbl.border = THIN_BORDER

        val_cell = ws.cell(row=r, column=3, value=val)
        val_cell.font = FONT_DATA_BOLD if "Median" in label or "Mean" in label else FONT_DATA
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

    # Section 2: Valuation Confidence Bands & Percentiles (Damodaran VaR style)
    r += 1
    _set_banner(ws, r, 2, 5, "Valuation Confidence Intervals (Damodaran Risk / VaR Approach)")
    r += 1

    var_headers = ["Percentile Scenario", "Confidence", "Implied Share Price", "Upside vs CMP"]
    _set_table_headers(ws, r, var_headers, start_col=2)
    var_header_row = r
    r += 1

    p5 = mc_stats.get("p5", 0)
    p25 = mc_stats.get("p25", 0)
    p50 = mc_stats.get("median", 0)
    p75 = mc_stats.get("p75", 0)
    p95 = mc_stats.get("p95", 0)

    var_items = [
        ("5th Percentile (Deep Bear)", "95.0%", p5),
        ("25th Percentile (Conservative)", "75.0%", p25),
        ("50th Percentile (Median Base)", "50.0%", p50),
        ("75th Percentile (Optimistic)", "25.0%", p75),
        ("95th Percentile (Strong Bull)", "5.0%", p95),
    ]

    for label, conf_str, price in var_items:
        fill = HIGHLIGHT_FILL if "50th" in label else (ALT_ROW_FILL if r % 2 == 0 else None)
        is_bold = "50th" in label

        # Col 2: Scenario
        c2 = ws.cell(row=r, column=2, value=label)
        c2.font = FONT_LABEL_BOLD if is_bold else FONT_LABEL
        c2.fill = fill or PatternFill(fill_type=None)
        c2.border = TOTAL_BORDER if is_bold else THIN_BORDER

        # Col 3: Confidence
        c3 = ws.cell(row=r, column=3, value=conf_str)
        c3.font = FONT_DATA
        c3.fill = fill or PatternFill(fill_type=None)
        c3.alignment = ALIGN_CENTER
        c3.border = TOTAL_BORDER if is_bold else THIN_BORDER

        # Col 4: Price
        c4 = ws.cell(row=r, column=4, value=price)
        c4.font = FONT_TOTAL if is_bold else FONT_DATA_BOLD
        c4.fill = fill or PatternFill(fill_type=None)
        c4.alignment = ALIGN_RIGHT
        c4.number_format = cfmt_price
        c4.border = TOTAL_BORDER if is_bold else THIN_BORDER

        # Col 5: Upside formula
        cmp_cell_ref = f"$C${stats_items[-1][0]}" # we can use direct CMP value or cell reference
        c5 = ws.cell(row=r, column=5)
        if current_price > 0:
            c5.value = f"=(D{r}-{current_price})/{current_price}"
        else:
            c5.value = 0.0
        c5.font = FONT_DATA_BOLD
        c5.fill = fill or PatternFill(fill_type=None)
        c5.alignment = ALIGN_RIGHT
        c5.number_format = PCT_FMT
        c5.border = TOTAL_BORDER if is_bold else THIN_BORDER
        r += 1

    # Section 3: Distribution Frequency Table (For Chart & Histogram Inspection)
    r += 1
    _set_banner(ws, r, 2, 5, "Valuation Frequency Distribution (Simulated Iteration Density)")
    r += 1

    dist_headers = ["Implied Share Price Range", "Iterations Count", "Frequency %", "Cumulative %"]
    _set_table_headers(ws, r, dist_headers, start_col=2)
    dist_header_row = r
    r += 1

    hist = mc.get("histogram", {})
    bins = hist.get("bins", [])
    counts = hist.get("counts", [])

    total_sims = sum(counts) if counts else 1
    running_cum = 0

    # Condense into ~25 representative buckets if bins are too granular (e.g. 100 bins)
    bucket_size = max(1, len(bins) // 25)
    grouped_data = []

    if bins and counts:
        for idx in range(0, len(bins), bucket_size):
            chunk_bins = bins[idx : idx + bucket_size]
            chunk_counts = counts[idx : idx + bucket_size]
            if not chunk_bins:
                continue
            mid_price = chunk_bins[len(chunk_bins) // 2]
            sum_count = sum(chunk_counts)
            grouped_data.append((mid_price, sum_count))
    else:
        # Fallback dummy distribution
        grouped_data = [
            (p25 * 0.8, 500),
            (p25, 2000),
            (p50, 5000),
            (p75, 2000),
            (p95, 500),
        ]

    dist_start_row = r
    for mid_price, count in grouped_data:
        fill = ALT_ROW_FILL if r % 2 == 0 else None
        running_cum += count

        # Col 2: Price Bin
        c2 = ws.cell(row=r, column=2, value=mid_price)
        c2.font = FONT_DATA
        c2.fill = fill or PatternFill(fill_type=None)
        c2.alignment = ALIGN_RIGHT
        c2.number_format = cfmt_price
        c2.border = THIN_BORDER

        # Col 3: Count
        c3 = ws.cell(row=r, column=3, value=count)
        c3.font = FONT_DATA_BOLD
        c3.fill = fill or PatternFill(fill_type=None)
        c3.alignment = ALIGN_RIGHT
        c3.number_format = INT_FMT
        c3.border = THIN_BORDER

        # Col 4: Frequency %
        c4 = ws.cell(row=r, column=4, value=count / total_sims)
        c4.font = FONT_DATA
        c4.fill = fill or PatternFill(fill_type=None)
        c4.alignment = ALIGN_RIGHT
        c4.number_format = PCT_FMT
        c4.border = THIN_BORDER

        # Col 5: Cumulative %
        c5 = ws.cell(row=r, column=5, value=running_cum / total_sims)
        c5.font = FONT_DATA
        c5.fill = fill or PatternFill(fill_type=None)
        c5.alignment = ALIGN_RIGHT
        c5.number_format = PCT_FMT
        c5.border = THIN_BORDER
        r += 1

    dist_end_row = r - 1

    # ═══════════════════════════════════════════════════════════════════════════
    # Embedded Native Excel BarChart Histogram
    # ═══════════════════════════════════════════════════════════════════════════
    chart = BarChart()
    chart.type = "col"
    chart.style = 10
    chart.title = f"Monte Carlo Implied Price Distribution — {company.get('ticker', '')}"
    chart.y_axis.title = "Number of Simulation Iterations"
    chart.x_axis.title = f"Simulated Implied Share Price ({currency})"

    # Reference data: Count column (Col C / col 3)
    data_ref = Reference(ws, min_col=3, min_row=dist_header_row, max_row=dist_end_row)
    # Reference categories: Price Bin column (Col B / col 2)
    cats_ref = Reference(ws, min_col=2, min_row=dist_start_row, max_row=dist_end_row)

    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)
    chart.legend = None
    chart.width = 19
    chart.height = 13

    # Position chart neatly to the right of the summary tables (starting at G4)
    ws.add_chart(chart, "G4")

    ws.column_dimensions["A"].width = 3
    _auto_fit_columns(ws, min_width=16, max_width=32)
    ws.freeze_panes = "B4"


# ═══════════════════════════════════════════════════════════════════════════
# Public API Entrypoint
# ═══════════════════════════════════════════════════════════════════════════

def generate_excel_report(analysis_data: Dict[str, Any]) -> BytesIO:
    """
    Generate an institutional Damodaran-grade Excel workbook (.xlsx)
    from the valuation analysis data.

    Matches the structure and precision of HUL FINAL MODEL.xlsx:
      - Cover Page & Investment Summary
      - Historical Financials & Statement Ratios
      - WACC 2 with Live CAPM Formulas
      - DCF Model with Live Links to WACC 2 & Historicals
      - 2D Sensitivity Tables (Growth vs WACC & Margin vs WACC)
      - Monte Carlo Risk Distribution with Native Embedded Excel Histogram

    Returns
    -------
    BytesIO
        In-memory buffer containing the complete .xlsx workbook.
    """
    wb = Workbook()

    try:
        _build_cover(wb, analysis_data)
        cash_ref = _build_historicals(wb, analysis_data)
        wacc_links = _build_wacc2(wb, analysis_data)
        _build_dcf_model(wb, analysis_data, wacc_links, cash_ref)
        _build_sensitivity(wb, analysis_data)
        _build_monte_carlo(wb, analysis_data)
    except Exception:
        logger.exception("Error building institutional Excel workbook")
        raise

    # Ensure all worksheets have clean print areas
    for ws in wb.worksheets:
        max_r = ws.max_row or 1
        max_c = ws.max_column or 1
        ws.print_area = f"A1:{get_column_letter(max_c)}{max_r}"

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
