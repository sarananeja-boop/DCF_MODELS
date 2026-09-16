"""
Formatted Excel Workbook Generator
====================================
Produces a professional, multi-sheet .xlsx report using openpyxl.
Returns a BytesIO buffer for streaming via FastAPI.
"""

import logging
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    NamedStyle,
    PatternFill,
    Side,
    numbers,
)
from openpyxl.utils import get_column_letter

logger = logging.getLogger("dcf-api.export")

# ═══════════════════════════════════════════════════════════════════════════
# Style Constants
# ═══════════════════════════════════════════════════════════════════════════

NAVY = "0A0E27"
WHITE = "FFFFFF"
LIGHT_GREY = "F2F2F2"
MEDIUM_GREY = "D9D9D9"
ACCENT_BLUE = "2563EB"
GREEN = "22C55E"
RED = "EF4444"

HEADER_FILL = PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid")
ALT_FILL = PatternFill(start_color=LIGHT_GREY, end_color=LIGHT_GREY, fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color=WHITE)
TITLE_FONT = Font(name="Calibri", size=20, bold=True, color=NAVY)
SUBTITLE_FONT = Font(name="Calibri", size=14, bold=False, color=NAVY)
LABEL_FONT = Font(name="Calibri", size=11, bold=True, color=NAVY)
VALUE_FONT = Font(name="Calibri", size=11, bold=False)
SECTION_FONT = Font(name="Calibri", size=12, bold=True, color=ACCENT_BLUE)

THIN_BORDER = Border(
    left=Side(style="thin", color=MEDIUM_GREY),
    right=Side(style="thin", color=MEDIUM_GREY),
    top=Side(style="thin", color=MEDIUM_GREY),
    bottom=Side(style="thin", color=MEDIUM_GREY),
)

ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _safe(d: Any, *keys, default=None):
    """Safely traverse nested dicts."""
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k, default)
        else:
            return default
    return cur


def _get_currency_fmt(market: str) -> str:
    """Return Excel number format string for currency."""
    if market == "IN":
        return '₹#,##0.00'
    return '#,##0.00'


def _get_currency_fmt_large(market: str) -> str:
    if market == "IN":
        return '₹#,##0'
    return '#,##0'


PCT_FMT = "0.00%"
NUM_FMT = "#,##0.00"
INT_FMT = "#,##0"
MULT_FMT = "0.0x"


def _set_header_row(ws, row: int, values: list, start_col: int = 1):
    """Write a styled header row."""
    for i, val in enumerate(values, start=start_col):
        cell = ws.cell(row=row, column=i, value=val)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = ALIGN_CENTER
        cell.border = THIN_BORDER


def _set_data_cell(ws, row: int, col: int, value, fmt: Optional[str] = None,
                   bold: bool = False, fill: Optional[PatternFill] = None):
    """Write a styled data cell."""
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = Font(name="Calibri", size=11, bold=bold)
    cell.alignment = ALIGN_RIGHT if col > 1 else ALIGN_LEFT
    cell.border = THIN_BORDER
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = fill
    return cell


def _set_label_value_row(ws, row: int, label: str, value, fmt: Optional[str] = None,
                         fill: Optional[PatternFill] = None, label_col: int = 1,
                         value_col: int = 2):
    """Write a label-value pair across two columns."""
    lbl = ws.cell(row=row, column=label_col, value=label)
    lbl.font = LABEL_FONT
    lbl.alignment = ALIGN_LEFT
    lbl.border = THIN_BORDER
    if fill:
        lbl.fill = fill

    val = ws.cell(row=row, column=value_col, value=value)
    val.font = VALUE_FONT
    val.alignment = ALIGN_RIGHT
    val.border = THIN_BORDER
    if fmt:
        val.number_format = fmt
    if fill:
        val.fill = fill


def _set_section_title(ws, row: int, title: str, col: int = 1):
    """Write a section heading."""
    cell = ws.cell(row=row, column=col, value=title)
    cell.font = SECTION_FONT
    cell.alignment = ALIGN_LEFT


def _auto_width(ws, min_width: int = 12, max_width: int = 30):
    """Auto-adjust column widths based on content."""
    for col_cells in ws.columns:
        max_len = min_width
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            if cell.value is not None:
                cell_len = len(str(cell.value)) + 2
                max_len = max(max_len, min(cell_len, max_width))
        ws.column_dimensions[col_letter].width = max_len


# ═══════════════════════════════════════════════════════════════════════════
# Sheet Builders
# ═══════════════════════════════════════════════════════════════════════════


def _build_cover(wb: Workbook, data: Dict[str, Any]):
    ws = wb.active
    ws.title = "Cover"
    ws.sheet_properties.tabColor = NAVY

    company = data.get("company", {})
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    verdict = data.get("verdict", {})
    market = company.get("market", "US")
    cfmt = _get_currency_fmt(market)

    # Title
    ws.merge_cells("A2:D2")
    title_cell = ws["A2"]
    title_cell.value = company.get("name", "Company")
    title_cell.font = TITLE_FONT
    title_cell.alignment = ALIGN_LEFT

    ws.merge_cells("A3:D3")
    sub = ws["A3"]
    sub.value = "DCF Valuation Report"
    sub.font = SUBTITLE_FONT

    row = 5
    details = [
        ("Ticker", company.get("ticker")),
        ("Market", market),
        ("Currency", company.get("currency")),
        ("Analysis Date", datetime.now().strftime("%Y-%m-%d")),
    ]
    for label, val in details:
        _set_label_value_row(ws, row, label, val)
        row += 1

    row += 1
    _set_section_title(ws, row, "Valuation Summary")
    row += 1

    current_price = market_data.get("current_price")
    implied_price = dcf.get("implied_price")
    upside = verdict.get("upside_pct")

    valuation_items = [
        ("Current Price", current_price, cfmt),
        ("DCF Implied Value", implied_price, cfmt),
        ("Upside / Downside", upside, PCT_FMT),
        ("Verdict", verdict.get("verdict"), None),
    ]
    for label, val, fmt in valuation_items:
        _set_label_value_row(ws, row, label, val, fmt=fmt)
        row += 1

    # Verdict description
    row += 1
    ws.merge_cells(f"A{row}:D{row}")
    desc_cell = ws.cell(row=row, column=1, value=verdict.get("description", ""))
    desc_cell.font = Font(name="Calibri", size=11, italic=True, color=NAVY)
    desc_cell.alignment = Alignment(wrap_text=True, vertical="top")

    _auto_width(ws)
    ws.freeze_panes = "A5"


def _build_dcf(wb: Workbook, data: Dict[str, Any]):
    ws = wb.create_sheet("DCF Model")
    ws.sheet_properties.tabColor = ACCENT_BLUE

    dcf = data.get("dcf_result", {})
    market = _safe(data, "company", "market", default="US")
    cfmt = _get_currency_fmt_large(market)
    cfmt_full = _get_currency_fmt(market)

    projected_revenue = dcf.get("projected_revenue", [])
    projected_ufcf = dcf.get("projected_ufcf", [])
    growth_schedule = dcf.get("growth_schedule", [])
    pv_ufcf = dcf.get("pv_ufcf", [])
    n = len(projected_revenue)

    historicals = data.get("historicals", {})
    ebit_margin = historicals.get("avg_ebit_margin", 0)
    overrides = data.get("overrides_applied", {})
    tax_rate = _safe(data, "macro", "tax_rate", default=0.25)
    avg_capex_pct = historicals.get("avg_capex_pct", 0)
    avg_dna_pct = historicals.get("avg_dna_pct", 0)
    avg_dnwc_pct = historicals.get("avg_dnwc_pct", 0)

    # Use override margin if provided
    margin_used = overrides.get("ebit_margin") if overrides.get("ebit_margin") is not None else ebit_margin

    # Header row
    headers = ["Metric"] + [f"Year {i+1}" for i in range(n)]
    _set_header_row(ws, 1, headers)

    # Rows definition: (label, values, format)
    rows_data = []

    # Revenue
    rows_data.append(("Revenue", projected_revenue, cfmt))

    # Revenue Growth
    rows_data.append(("Revenue Growth", growth_schedule, PCT_FMT))

    # EBIT (approx)
    ebit_vals = [r * margin_used if r else None for r in projected_revenue]
    rows_data.append(("EBIT", ebit_vals, cfmt))

    # EBIT Margin
    rows_data.append(("EBIT Margin", [margin_used] * n, PCT_FMT))

    # NOPAT
    nopat_vals = [e * (1 - tax_rate) if e else None for e in ebit_vals]
    rows_data.append(("NOPAT", nopat_vals, cfmt))

    # D&A
    dna_vals = [r * avg_dna_pct if r else None for r in projected_revenue]
    rows_data.append(("D&A (add back)", dna_vals, cfmt))

    # CapEx
    capex_vals = [r * avg_capex_pct if r else None for r in projected_revenue]
    rows_data.append(("CapEx", capex_vals, cfmt))

    # ΔNWC
    dnwc_vals = [r * avg_dnwc_pct if r else None for r in projected_revenue]
    rows_data.append(("Change in NWC", dnwc_vals, cfmt))

    # UFCF
    rows_data.append(("Unlevered FCF", projected_ufcf, cfmt))

    wacc_val = _safe(data, "wacc", "wacc", default=0)
    # PV of UFCF array
    pv_ufcf_vals = [cf / ((1 + wacc_val) ** (i + 1)) if cf else 0 for i, cf in enumerate(projected_ufcf)]
    rows_data.append(("PV of UFCF", pv_ufcf_vals, cfmt))

    for idx, (label, values, fmt) in enumerate(rows_data):
        r = idx + 2
        fill = ALT_FILL if idx % 2 == 0 else None
        _set_data_cell(ws, r, 1, label, bold=True, fill=fill)
        for j, v in enumerate(values):
            _set_data_cell(ws, r, j + 2, v, fmt=fmt, fill=fill)

    # --- Terminal Value & Bridge section ---
    bridge_start = len(rows_data) + 3
    _set_section_title(ws, bridge_start, "Enterprise Value Bridge")
    bridge_start += 1

    wacc_val = _safe(data, "wacc", "wacc", default=0)
    bridge_items = [
        ("Terminal Value", dcf.get("terminal_value"), cfmt),
        ("PV of Terminal Value", dcf.get("pv_terminal_value"), cfmt),
        ("Sum of PV(UFCF)", pv_ufcf, cfmt),
        ("Enterprise Value", dcf.get("enterprise_value"), cfmt),
        ("", None, None),  # spacer
        ("(−) Total Debt", _safe(data, "wacc", "total_debt", default=0), cfmt),
        ("(+) Cash & Equivalents", _safe(data, "metrics", "cash_and_equivalents", default=0), cfmt),
        ("Equity Value", dcf.get("equity_value"), cfmt),
        ("÷ Shares Outstanding", _safe(data, "market_data", "shares_outstanding"), INT_FMT),
        ("= Implied Share Price", dcf.get("implied_price"), cfmt_full),
    ]

    for i, (label, val, fmt) in enumerate(bridge_items):
        r = bridge_start + i
        fill = ALT_FILL if i % 2 == 0 else None
        _set_label_value_row(ws, r, label, val, fmt=fmt, fill=fill, value_col=3)

    _auto_width(ws)
    ws.freeze_panes = "B2"


def _build_wacc(wb: Workbook, data: Dict[str, Any]):
    ws = wb.create_sheet("WACC")
    ws.sheet_properties.tabColor = "F59E0B"

    wacc = data.get("wacc", {})
    macro = data.get("macro", {})
    market_data = data.get("market_data", {})
    market = _safe(data, "company", "market", default="US")
    cfmt = _get_currency_fmt_large(market)

    row = 1
    _set_header_row(ws, row, ["Component", "Value"])

    row = 2
    _set_section_title(ws, row, "CAPM — Cost of Equity")
    row += 1

    capm_items = [
        ("Risk-Free Rate", macro.get("risk_free_rate"), PCT_FMT),
        ("Source", macro.get("risk_free_source"), None),
        ("Beta (Levered)", market_data.get("beta"), NUM_FMT),
        ("Expected Market Return", macro.get("market_return"), PCT_FMT),
        ("Equity Risk Premium", None, PCT_FMT),  # computed
        ("Cost of Equity", wacc.get("cost_of_equity"), PCT_FMT),
    ]
    # Compute ERP if data available
    rfr = macro.get("risk_free_rate")
    mr = macro.get("market_return")
    if rfr is not None and mr is not None:
        try:
            capm_items[4] = ("Equity Risk Premium", float(mr) - float(rfr), PCT_FMT)
        except (TypeError, ValueError):
            pass

    for label, val, fmt in capm_items:
        fill = ALT_FILL if (row % 2 == 0) else None
        _set_label_value_row(ws, row, label, val, fmt=fmt, fill=fill)
        row += 1

    row += 1
    _set_section_title(ws, row, "Cost of Debt")
    row += 1

    debt_items = [
        ("Total Debt", wacc.get("total_debt"), cfmt),
        ("Tax Rate", macro.get("tax_rate"), PCT_FMT),
        ("After-Tax Cost of Debt", wacc.get("cost_of_debt"), PCT_FMT),
    ]
    for label, val, fmt in debt_items:
        fill = ALT_FILL if (row % 2 == 0) else None
        _set_label_value_row(ws, row, label, val, fmt=fmt, fill=fill)
        row += 1

    row += 1
    _set_section_title(ws, row, "Capital Structure")
    row += 1

    cap_items = [
        ("Market Capitalisation", market_data.get("market_cap"), cfmt),
        ("Total Debt", wacc.get("total_debt"), cfmt),
        ("Equity Weight", wacc.get("weight_equity"), PCT_FMT),
        ("Debt Weight", wacc.get("weight_debt"), PCT_FMT),
    ]
    for label, val, fmt in cap_items:
        fill = ALT_FILL if (row % 2 == 0) else None
        _set_label_value_row(ws, row, label, val, fmt=fmt, fill=fill)
        row += 1

    row += 1
    _set_section_title(ws, row, "Weighted Average Cost of Capital")
    row += 1
    wacc_cell_label = ws.cell(row=row, column=1, value="WACC")
    wacc_cell_label.font = Font(name="Calibri", size=14, bold=True, color=NAVY)
    wacc_cell_label.border = THIN_BORDER
    wacc_cell_val = ws.cell(row=row, column=2, value=wacc.get("wacc"))
    wacc_cell_val.font = Font(name="Calibri", size=14, bold=True, color=NAVY)
    wacc_cell_val.number_format = PCT_FMT
    wacc_cell_val.alignment = ALIGN_RIGHT
    wacc_cell_val.border = THIN_BORDER

    _auto_width(ws)
    ws.freeze_panes = "A2"


def _build_monte_carlo(wb: Workbook, data: Dict[str, Any]):
    ws = wb.create_sheet("Monte Carlo")
    ws.sheet_properties.tabColor = GREEN

    mc = data.get("monte_carlo", {})
    mc_stats = mc.get("stats", {})
    verdict = data.get("verdict", {})
    market = _safe(data, "company", "market", default="US")
    cfmt = _get_currency_fmt(market)

    row = 1
    _set_header_row(ws, row, ["Statistic", "Value"])

    row = 2
    _set_section_title(ws, row, "Monte Carlo Simulation Results")
    row += 1

    stats_items = [
        ("Iterations", mc.get("actual_iterations"), INT_FMT),
        ("", None, None),
        ("Mean Price", mc_stats.get("mean"), cfmt),
        ("Median Price", mc_stats.get("median"), cfmt),
        ("5th Percentile (Bear)", mc_stats.get("p5"), cfmt),
        ("25th Percentile", mc_stats.get("p25"), cfmt),
        ("75th Percentile", mc_stats.get("p75"), cfmt),
        ("95th Percentile (Bull)", mc_stats.get("p95"), cfmt),
    ]

    for label, val, fmt in stats_items:
        fill = ALT_FILL if (row % 2 == 0) else None
        _set_label_value_row(ws, row, label, val, fmt=fmt, fill=fill)
        row += 1

    row += 1
    _set_section_title(ws, row, "Current Price vs MC Range")
    row += 1

    current_price = _safe(data, "market_data", "current_price")
    comparison_items = [
        ("Current Market Price", current_price, cfmt),
        ("MC Valuation Range (P25–P75)", f"{mc_stats.get('p25', 'N/A')} – {mc_stats.get('p75', 'N/A')}", None),
        ("Verdict", verdict.get("verdict"), None),
        ("Upside / Downside", verdict.get("upside_pct"), PCT_FMT),
        ("Description", verdict.get("description"), None),
    ]
    for label, val, fmt in comparison_items:
        fill = ALT_FILL if (row % 2 == 0) else None
        _set_label_value_row(ws, row, label, val, fmt=fmt, fill=fill)
        row += 1

    _auto_width(ws)
    ws.freeze_panes = "A2"


def _build_sensitivity(wb: Workbook, data: Dict[str, Any]):
    ws = wb.create_sheet("Sensitivity")
    ws.sheet_properties.tabColor = "8B5CF6"

    sens = data.get("sensitivity", {})
    gw = sens.get("growth_wacc", {})
    market = _safe(data, "company", "market", default="US")
    cfmt = _get_currency_fmt(market)

    growth_range = gw.get("growth_range", [])
    wacc_range = gw.get("wacc_range", [])
    price_grid = gw.get("price_grid", [])

    if not price_grid or not growth_range or not wacc_range:
        ws.cell(row=1, column=1, value="Sensitivity data not available.")
        return

    # Title
    _set_section_title(ws, 1, "Implied Price: Revenue Growth × WACC")

    # Column headers (WACC values)
    header_row = 3
    ws.cell(row=header_row, column=1, value="Growth \\ WACC").font = HEADER_FONT
    ws.cell(row=header_row, column=1).fill = HEADER_FILL
    ws.cell(row=header_row, column=1).border = THIN_BORDER
    ws.cell(row=header_row, column=1).alignment = ALIGN_CENTER

    for j, w in enumerate(wacc_range):
        cell = ws.cell(row=header_row, column=j + 2, value=w)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.number_format = PCT_FMT
        cell.alignment = ALIGN_CENTER
        cell.border = THIN_BORDER

    # Data rows
    for i, (g, row_vals) in enumerate(zip(growth_range, price_grid)):
        r = header_row + 1 + i
        label_cell = ws.cell(row=r, column=1, value=g)
        label_cell.font = LABEL_FONT
        label_cell.number_format = PCT_FMT
        label_cell.alignment = ALIGN_CENTER
        label_cell.border = THIN_BORDER
        label_cell.fill = PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid")
        label_cell.font = HEADER_FONT

        for j, price in enumerate(row_vals):
            cell = ws.cell(row=r, column=j + 2, value=price)
            cell.number_format = cfmt
            cell.alignment = ALIGN_RIGHT
            cell.border = THIN_BORDER
            cell.font = VALUE_FONT

    # Conditional formatting (green-yellow-red color scale)
    n_rows = len(growth_range)
    n_cols = len(wacc_range)
    data_start = f"B{header_row + 1}"
    data_end = f"{get_column_letter(n_cols + 1)}{header_row + n_rows}"

    ws.conditional_formatting.add(
        f"{data_start}:{data_end}",
        ColorScaleRule(
            start_type="min", start_color="EF4444",  # red
            mid_type="percentile", mid_value=50, mid_color="FDE68A",  # yellow
            end_type="max", end_color="22C55E",  # green
        ),
    )

    _auto_width(ws)
    ws.freeze_panes = f"B{header_row + 1}"


def _build_assumptions(wb: Workbook, data: Dict[str, Any]):
    ws = wb.create_sheet("Assumptions")
    ws.sheet_properties.tabColor = "64748B"

    macro = data.get("macro", {})
    historicals = data.get("historicals", {})
    overrides = data.get("overrides_applied", {})
    market = _safe(data, "company", "market", default="US")

    row = 1
    _set_header_row(ws, row, ["Assumption", "Value", "Source"])

    row = 2
    _set_section_title(ws, row, "Macro / Market Assumptions")
    row += 1

    macro_items = [
        ("Risk-Free Rate", macro.get("risk_free_rate"), PCT_FMT,
         f"Live Data — {macro.get('risk_free_source', 'N/A')}"),
        ("Expected Market Return", macro.get("market_return"), PCT_FMT, "Assumed"),
        ("Tax Rate", macro.get("tax_rate"), PCT_FMT, "Assumed"),
        ("Benchmark Index", macro.get("benchmark_index"), None, "Assumed"),
    ]

    for label, val, fmt, source in macro_items:
        fill = ALT_FILL if (row % 2 == 0) else None
        _set_label_value_row(ws, row, label, val, fmt=fmt, fill=fill)
        src_cell = ws.cell(row=row, column=3, value=source)
        src_cell.font = Font(name="Calibri", size=11, italic=True)
        src_cell.alignment = ALIGN_LEFT
        src_cell.border = THIN_BORDER
        if fill:
            src_cell.fill = fill
        row += 1

    row += 1
    _set_section_title(ws, row, "Historical Averages (Computed)")
    row += 1

    hist_items = [
        ("Avg Revenue Growth", historicals.get("avg_rev_growth"), PCT_FMT),
        ("Std Dev Revenue Growth", historicals.get("std_rev_growth"), PCT_FMT),
        ("Avg EBIT Margin", historicals.get("avg_ebit_margin"), PCT_FMT),
        ("Std Dev EBIT Margin", historicals.get("std_ebit_margin"), PCT_FMT),
        ("Avg CapEx (% of Revenue)", historicals.get("avg_capex_pct"), PCT_FMT),
        ("Avg D&A (% of Revenue)", historicals.get("avg_dna_pct"), PCT_FMT),
        ("Avg ΔNWC (% of Revenue)", historicals.get("avg_dnwc_pct"), PCT_FMT),
        ("Historical Years Used", historicals.get("n_years"), INT_FMT),
    ]

    for label, val, fmt in hist_items:
        fill = ALT_FILL if (row % 2 == 0) else None
        _set_label_value_row(ws, row, label, val, fmt=fmt, fill=fill)
        src_cell = ws.cell(row=row, column=3, value="Computed")
        src_cell.font = Font(name="Calibri", size=11, italic=True)
        src_cell.alignment = ALIGN_LEFT
        src_cell.border = THIN_BORDER
        if fill:
            src_cell.fill = fill
        row += 1

    # Overrides
    active_overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    if active_overrides:
        row += 1
        _set_section_title(ws, row, "User Overrides Applied")
        row += 1

        override_labels = {
            "revenue_growth": ("Revenue Growth Override", PCT_FMT),
            "ebit_margin": ("EBIT Margin Override", PCT_FMT),
            "wacc": ("WACC Override", PCT_FMT),
            "terminal_growth": ("Terminal Growth Override", PCT_FMT),
            "projection_years": ("Projection Years Override", INT_FMT),
        }

        for key, val in active_overrides.items():
            label, fmt = override_labels.get(key, (key, None))
            fill = ALT_FILL if (row % 2 == 0) else None
            _set_label_value_row(ws, row, label, val, fmt=fmt, fill=fill)
            src_cell = ws.cell(row=row, column=3, value="User Override")
            src_cell.font = Font(name="Calibri", size=11, bold=True, color=ACCENT_BLUE)
            src_cell.alignment = ALIGN_LEFT
            src_cell.border = THIN_BORDER
            if fill:
                src_cell.fill = fill
            row += 1

    _auto_width(ws, min_width=14)
    ws.freeze_panes = "A2"


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════


def generate_excel_report(analysis_data: Dict[str, Any]) -> BytesIO:
    """
    Generate a professionally formatted Excel workbook from the analysis data.

    Parameters
    ----------
    analysis_data : dict
        The full response dict from the /api/analyze endpoint.

    Returns
    -------
    BytesIO
        In-memory buffer containing the .xlsx file.
    """
    wb = Workbook()

    try:
        _build_cover(wb, analysis_data)
        _build_dcf(wb, analysis_data)
        _build_wacc(wb, analysis_data)
        _build_monte_carlo(wb, analysis_data)
        _build_sensitivity(wb, analysis_data)
        _build_assumptions(wb, analysis_data)
    except Exception:
        logger.exception("Error building Excel sheets")
        raise

    # Set print areas for all sheets
    for ws in wb.worksheets:
        max_row = ws.max_row or 1
        max_col = ws.max_column or 1
        ws.print_area = f"A1:{get_column_letter(max_col)}{max_row}"

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
