"""
DCF Engine – WACC Calculation & Multi-Stage DCF
================================================

Refactored from Step 4 of the Automated DCF Monte Carlo notebook.

Provides:
  * ``compute_wacc`` – CAPM-based WACC with market-value capital weights.
  * ``run_dcf``      – Multi-stage DCF with linear growth fade and full
                       UFCF build (including Δ NWC).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Damodaran Synthetic Credit Rating Tables (Continuous Interpolation)
# ---------------------------------------------------------------------------

# Smaller firms: Market Cap < $5 Billion (~40,000 Cr INR)
DAMODARAN_SMALL_FIRM_RATINGS = [
    (12.50, "AAA", 0.0067),
    (9.50,  "AA",  0.0082),
    (7.50,  "A+",  0.0103),
    (6.00,  "A",   0.0114),
    (4.50,  "A-",  0.0129),
    (4.00,  "BBB", 0.0159),
    (3.50,  "BB+", 0.0193),
    (3.00,  "BB",  0.0232),
    (2.50,  "BB-", 0.0281),
    (2.00,  "B+",  0.0347),
    (1.50,  "B",   0.0446),
    (1.25,  "B-",  0.0540),
    (0.80,  "CCC", 0.0716),
    (0.50,  "CC",  0.0918),
    (0.00,  "D",   0.1150),
    (-999.0,"D",   0.1150),
]

# Large firms: Market Cap >= $5 Billion (~40,000 Cr INR)
DAMODARAN_LARGE_FIRM_RATINGS = [
    (8.50,  "AAA", 0.0067),
    (6.50,  "AA",  0.0082),
    (5.50,  "A+",  0.0103),
    (4.25,  "A",   0.0114),
    (3.00,  "A-",  0.0129),
    (2.50,  "BBB", 0.0159),
    (2.25,  "BB+", 0.0193),
    (2.00,  "BB",  0.0232),
    (1.75,  "BB-", 0.0281),
    (1.50,  "B+",  0.0347),
    (1.25,  "B",   0.0446),
    (0.80,  "B-",  0.0540),
    (0.65,  "CCC", 0.0716),
    (0.20,  "CC",  0.0918),
    (0.00,  "D",   0.1150),
    (-999.0,"D",   0.1150),
]


def get_synthetic_rating_and_spread(
    interest_coverage: float,
    market_cap: float,
    currency: str = "USD"
) -> tuple[str, float]:
    """Computes Damodaran synthetic credit rating and continuous default spread over Rf.
    
    Uses piecewise linear interpolation (np.interp) to eliminate step-function cliff jumps.
    """
    is_large = (market_cap >= 400000000000.0) if currency == "INR" else (market_cap >= 5000000000.0)
    table = DAMODARAN_LARGE_FIRM_RATINGS if is_large else DAMODARAN_SMALL_FIRM_RATINGS
    
    # Strictly increasing x for np.interp
    xp = [r[0] for r in reversed(table)]
    yp = [r[2] for r in reversed(table)]
    
    spread = float(np.interp(interest_coverage, xp, yp))
    
    rating = "D"
    for thresh, label, _ in table:
        if interest_coverage >= thresh:
            rating = label
            break
            
    return rating, spread


# ---------------------------------------------------------------------------
# WACC
# ---------------------------------------------------------------------------

def compute_wacc(
    stock_data: dict,
    metrics: dict,
    market_profile: dict,
) -> dict:
    """Compute the Weighted Average Cost of Capital (WACC).

    Features:
      * Excludes financials from leverage and credit gates (routes to FCFE/DDM).
      * Continuous Damodaran Synthetic Credit Rating (small vs large firms) based on ICR.
      * No country spread double counting: Rf is local 10Y sovereign yield.
      * Marginal interest tax shield capped at EBIT (tax shield = 0 if EBIT <= 0).
      * Safety Net Floor: minimum 1.5% spread over sovereign 10Y yield with full diagnostic flagging.
    """
    risk_free_rate: float = market_profile["risk_free_rate"]
    market_return: float = market_profile["market_return"]
    tax_rate: float = market_profile["tax_rate"]
    currency: str = market_profile.get("currency", "USD")

    # Point 1: Exclude financials from non-financial leverage and credit gates
    if stock_data.get("is_financial", False):
        beta: float = stock_data.get("beta", 1.0)
        ke: float = risk_free_rate + beta * (market_return - risk_free_rate)
        return {
            "cost_of_equity": float(ke),
            "raw_cost_of_equity": float(ke),
            "ke_floored": False,
            "ke_note": None,
            "cost_of_debt": 0.0,
            "pretax_cost_of_debt": 0.0,
            "synthetic_rating": "N/A (Financial)",
            "default_spread": 0.0,
            "interest_coverage": 999.0,
            "weight_equity": 1.0,
            "weight_debt": 0.0,
            "wacc": float(ke),
            "raw_wacc": float(ke),
            "min_wacc": float(risk_free_rate + 0.015),
            "wacc_floored": False,
            "wacc_note": None,
            "total_debt": 0.0,
            "is_financial": True,
        }

    beta: float = stock_data["beta"]
    market_cap: float = stock_data["market_cap"]
    total_debt: float = metrics["total_debt"]
    interest_expense: float = metrics["interest_expense"]

    hist_ebit = metrics.get("ebit", [])
    last_ebit = float(hist_ebit[-1]) if len(hist_ebit) > 0 else 0.0

    # 4A – CAPM → Cost of Equity
    raw_cost_of_equity: float = risk_free_rate + beta * (market_return - risk_free_rate)
    
    ke_min = risk_free_rate + 0.015
    ke_floored = False
    ke_note = None
    if raw_cost_of_equity < ke_min:
        cost_of_equity = ke_min
        ke_floored = True
        ke_note = f"Cost of equity floored at {ke_min*100:.1f}% (Rf + 1.5% minimum equity risk premium)."
    else:
        cost_of_equity = raw_cost_of_equity

    # 4B – Cost of Debt with Damodaran Synthetic Rating & Continuous Spreads
    if interest_expense > 0:
        interest_coverage = float(last_ebit / interest_expense)
    else:
        interest_coverage = 999.0

    synthetic_rating, default_spread = get_synthetic_rating_and_spread(
        interest_coverage, market_cap, currency=currency
    )

    # Point 2: Rf already embeds sovereign default spread (G-Sec/Treasury). Kd = Rf + Company Default Spread.
    synthetic_kd = risk_free_rate + default_spread

    if total_debt > 0 and interest_expense > 0:
        hist_kd = abs(interest_expense / total_debt)
        if interest_coverage < 3.0:
            cost_of_debt = max(hist_kd, synthetic_kd)
        else:
            cost_of_debt = min(hist_kd, synthetic_kd) if hist_kd >= 0.04 else synthetic_kd
    else:
        cost_of_debt = synthetic_kd if total_debt > 0 else 0.04

    # Point 6: Cap interest tax shield at usable EBIT (using marginal statutory rate)
    marginal_tax_rate = tax_rate
    if total_debt > 0:
        usable_interest = max(0.0, min(interest_expense, max(0.0, last_ebit)))
        usable_tax_shield = marginal_tax_rate * usable_interest
        effective_kd_after_tax = cost_of_debt - (usable_tax_shield / total_debt)
        effective_kd_after_tax = float(np.clip(effective_kd_after_tax, 0.02, cost_of_debt))
    else:
        effective_kd_after_tax = cost_of_debt * (1.0 - marginal_tax_rate)

    # 4C – Capital structure weights
    total_capital = market_cap + total_debt
    if total_capital > 0:
        weight_equity = market_cap / total_capital
        weight_debt = total_debt / total_capital
    else:
        weight_equity = 1.0
        weight_debt = 0.0

    raw_wacc = (weight_equity * cost_of_equity) + (weight_debt * effective_kd_after_tax)

    # Point 5 / Safety Net Floor: minimum 1.5% spread over sovereign 10Y yield
    min_wacc_spread = 0.015
    min_wacc = risk_free_rate + min_wacc_spread
    wacc_floored = False
    wacc_note = None

    if raw_wacc < min_wacc:
        wacc = min_wacc
        wacc_floored = True
        market_label = "10Y G-Sec" if currency == "INR" else "10Y Treasury"
        wacc_note = (
            f"WACC safety floor applied at {min_wacc*100:.1f}% (minimum 1.5% spread over sovereign {market_label} yield). "
            f"Raw unconstrained WACC was {raw_wacc*100:.1f}%. Inputs may warrant review."
        )
    else:
        wacc = raw_wacc

    return {
        "cost_of_equity": float(cost_of_equity),
        "raw_cost_of_equity": float(raw_cost_of_equity),
        "ke_floored": ke_floored,
        "ke_note": ke_note,
        "cost_of_debt": float(effective_kd_after_tax),
        "pretax_cost_of_debt": float(cost_of_debt),
        "synthetic_rating": synthetic_rating,
        "default_spread": float(default_spread),
        "interest_coverage": float(interest_coverage),
        "weight_equity": float(weight_equity),
        "weight_debt": float(weight_debt),
        "wacc": float(wacc),
        "raw_wacc": float(raw_wacc),
        "min_wacc": float(min_wacc),
        "wacc_floored": wacc_floored,
        "wacc_note": wacc_note,
        "total_debt": float(total_debt),
    }


# ---------------------------------------------------------------------------
# Multi-Stage DCF
# ---------------------------------------------------------------------------

def run_dcf(
    start_growth: float,
    ebit_margin: float,
    discount_rate: float,
    metrics: dict,
    wacc_data: dict,
    stock_data: dict,
    terminal_growth: float = 0.025,
    projection_years: int = 5,
    current_margin: Optional[float] = None,
    tax_rate: Optional[float] = None,
    use_mid_year: bool = True,
) -> dict:
    """Run a single multi-stage DCF valuation with linear growth fade and Mid-Year convention.

    Implements Damodaran DCF modeling (matching HUL FINAL MODEL.xlsx):

    1. Revenue grows from ``start_growth`` in Year 1 to ``terminal_growth``
       in Year *N* via ``np.linspace``.
    2. UFCF = NOPAT + D&A − CapEx − Δ NWC (all as % of projected revenue).
    3. Discount projected UFCFs using Mid-Year Convention (t = 0.5, 1.5, 2.5, 3.5, 4.5).
    4. Terminal Value via Gordon Growth Model, discounted via the terminal period factor.
    5. EV → Equity bridge (add cash, subtract debt, floor at 0).
    """
    avg_dna_pct: float = metrics["avg_dna_pct"]
    avg_capex_pct: float = metrics["avg_capex_pct"]
    # Fallback for backward compatibility if normalized_nwc_to_revenue isn't present
    normalized_nwc_to_revenue: float = metrics.get("normalized_nwc_to_revenue", metrics.get("avg_dnwc_pct", 0.0))
    last_revenue: float = metrics["last_revenue"]
    total_debt: float = wacc_data["total_debt"]
    cash_equiv: float = metrics["cash_and_equivalents"]
    shares_out: float = stock_data["shares_outstanding"]

    is_extractive = stock_data.get("is_extractive", False)
    is_cyclical = stock_data.get("is_cyclical", False)
    if not is_extractive and not is_cyclical:
        from engine.data_layer import classify_sector_dynamics
        is_extractive, is_cyclical = classify_sector_dynamics(stock_data.get("sector"), stock_data.get("industry"))

    # Explicit tax rate priority: passed arg -> stock_data._tax_rate -> market fallback
    if tax_rate is None:
        tax_rate = stock_data.get("_tax_rate", 0.2517 if stock_data.get("market") == "IN" else 0.21)

    proj_ufcf: List[float] = []
    proj_rev: List[float] = []
    proj_nopat: List[float] = []
    proj_dna: List[float] = []
    proj_capex: List[float] = []
    proj_dnwc: List[float] = []
    last_rev = last_revenue

    # Linear fade from start_growth → terminal_growth
    growth_schedule = np.linspace(start_growth, terminal_growth, projection_years)
    
    # Margin schedule
    if current_margin is not None:
        margin_schedule = np.linspace(current_margin, ebit_margin, projection_years)
    else:
        margin_schedule = np.array([ebit_margin] * projection_years)

    # In corporate finance / Damodaran framework, CapEx% converges towards steady-state
    # maintenance CapEx: D&A * (1 + terminal_growth).
    # However, for extractive / depleting sectors (oil & gas upstream, thermal coal, mining),
    # physical reserves deplete continuously. Sustaining production requires real exploration and drilling CapEx,
    # which cannot drop below historical sustaining CapEx (avg_capex_pct).
    base_steady_state = avg_dna_pct * (1.0 + terminal_growth)
    if is_extractive:
        steady_state_capex_pct = max(base_steady_state, avg_capex_pct)
    elif is_cyclical:
        steady_state_capex_pct = max(base_steady_state, avg_capex_pct * 0.85)
    else:
        steady_state_capex_pct = base_steady_state

    capex_schedule = np.linspace(avg_capex_pct, steady_state_capex_pct, projection_years)

    for yr in range(projection_years):
        g = growth_schedule[yr]
        next_rev = last_rev * (1 + g)
        margin = margin_schedule[yr]

        nopat = next_rev * margin * (1 - tax_rate)
        dna_add = next_rev * avg_dna_pct
        capex_sub = next_rev * capex_schedule[yr]
        delta_nwc = normalized_nwc_to_revenue * (next_rev - last_rev)
        
        ufcf = nopat + dna_add - capex_sub - delta_nwc

        proj_ufcf.append(ufcf)
        proj_rev.append(next_rev)
        proj_nopat.append(nopat)
        proj_dna.append(dna_add)
        proj_capex.append(capex_sub)
        proj_dnwc.append(delta_nwc)
        
        last_rev = next_rev

    # Discount projected UFCFs using Mid-Year Convention (t = 0.5, 1.5, 2.5, ...)
    if use_mid_year:
        discount_periods = [float(i + 0.5) for i in range(projection_years)]
    else:
        discount_periods = [float(i + 1.0) for i in range(projection_years)]

    discount_factors = [(1.0 + discount_rate) ** t for t in discount_periods]
    pv_ufcf_list = [cf / df for cf, df in zip(proj_ufcf, discount_factors)]
    pv_ufcf = sum(pv_ufcf_list)

    # ------------------------------------------------------------------
    # Terminal Value via Damodaran Sustainable Reinvestment Model
    # (Matches HUL FINAL MODEL.xlsx: Reinvestment Rate = g / ROIC)
    # ------------------------------------------------------------------
    terminal_value_valid = True
    terminal_value_note = None
    terminal_growth_capped = False
    effective_terminal_growth = terminal_growth
    
    # Calculate Sustainable Terminal ROIC & Reinvestment Rate
    bs = metrics.get("statements", {}).get("balance_sheet", {}) if isinstance(metrics.get("statements"), dict) else {}
    equity_series = bs.get("Total Stockholders' Equity", [0]) if isinstance(bs, dict) else [0]
    equity_bv = equity_series[-1] if equity_series else 0.0
    invested_capital = max(1.0, equity_bv + total_debt - cash_equiv)
    
    hist_ebit = metrics.get("ebit", [])
    last_ebit = hist_ebit[-1] if hist_ebit else (last_rev * ebit_margin)
    hist_nopat = last_ebit * (1 - tax_rate)
    hist_roic = (hist_nopat / invested_capital) if (invested_capital > 0 and hist_nopat > 0) else discount_rate
    
    # Economic competition bounds sustainable long-term ROIC
    sustainable_roic = max(discount_rate, min(hist_roic, 0.25))
    terminal_reinv_rate = min(0.85, max(0.15, terminal_growth / sustainable_roic))

    # For extractive/capital-intensive firms, terminal reinvestment rate must also fund sustaining net CapEx
    if is_extractive and margin_schedule[-1] > 0:
        net_capex_reinv = max(0.0, (steady_state_capex_pct - avg_dna_pct) / margin_schedule[-1])
        terminal_reinv_rate = min(0.85, max(terminal_reinv_rate, net_capex_reinv))
    elif is_cyclical and margin_schedule[-1] > 0:
        net_capex_reinv = max(0.0, (steady_state_capex_pct - avg_dna_pct) / margin_schedule[-1])
        terminal_reinv_rate = min(0.85, max(terminal_reinv_rate, net_capex_reinv * 0.85))

    # Point 5: Tighten terminal growth rule.
    # Cap terminal growth at long-term GDP/inflation cap (5.0% for India, 2.5% for US)
    # Extractive / finite commodity constraint:
    # Perpetual growth for depleting fossil reserves (crude oil, coal) cannot assume macro GDP growth.
    # Cap at long-term volume/inflation ceiling (2.5% max)
    if is_extractive:
        max_g_allowed = 0.025
    else:
        is_india = (stock_data.get("market") == "IN")
        max_g_allowed = 0.050 if is_india else 0.025
    clamped_terminal_growth = min(terminal_growth, max_g_allowed)

    # Terminal NOPAT in Year N+1
    terminal_nopat = proj_rev[-1] * (1 + clamped_terminal_growth) * margin_schedule[-1] * (1 - tax_rate)
    terminal_ufcf = terminal_nopat * (1 - terminal_reinv_rate)
    
    # Enforce minimum spread: WACC - g >= 0.025 (2.5% minimum spread)
    min_spread = 0.025
    if discount_rate - clamped_terminal_growth < min_spread:
        effective_terminal_growth = max(0.01, discount_rate - min_spread)
        terminal_growth_capped = True
        terminal_value_note = (
            f"Terminal growth capped at {effective_terminal_growth*100:.1f}% to preserve minimum "
            f"{min_spread*100:.1f}% spread below WACC ({discount_rate*100:.1f}%)."
        )
    else:
        effective_terminal_growth = clamped_terminal_growth

    if discount_rate <= effective_terminal_growth:
        terminal_value = None
        pv_terminal_value = 0.0
        terminal_value_valid = False
        terminal_value_note = "WACC must exceed terminal growth rate for Gordon Growth model."
    elif terminal_ufcf <= 0:
        terminal_value = None
        pv_terminal_value = 0.0
        terminal_value_valid = False
        terminal_value_note = "Terminal UFCF is negative under current assumptions."
    else:
        spread = discount_rate - effective_terminal_growth
        terminal_value = (terminal_ufcf * (1.0 + effective_terminal_growth)) / spread
        pv_terminal_value = terminal_value / discount_factors[-1]

    # EV → Equity bridge
    enterprise_val = pv_ufcf + pv_terminal_value
    equity_value = enterprise_val + cash_equiv - total_debt
    
    # Implied price per share floored at 0.0
    implied_price = max(0.0, equity_value / shares_out) if shares_out > 0 else 0.0

    # ------------------------------------------------------------------
    # Exit Multiple Valuation Cross-Check (Damodaran & Institutional standard)
    # ------------------------------------------------------------------
    terminal_ebitda = proj_rev[-1] * (1.0 + effective_terminal_growth) * (margin_schedule[-1] + avg_dna_pct)
    implied_exit_multiple = (terminal_value / terminal_ebitda) if (terminal_value and terminal_ebitda > 0) else None

    # Benchmark exit multiples by sector profile
    if is_extractive:
        benchmark_exit_mult = 4.5
    elif is_cyclical:
        benchmark_exit_mult = 5.5
    elif stock_data.get("is_financial", False):
        benchmark_exit_mult = 8.0
    else:
        benchmark_exit_mult = 10.0

    exit_terminal_value = terminal_ebitda * benchmark_exit_mult if terminal_ebitda > 0 else 0.0
    pv_exit_tv = exit_terminal_value / discount_factors[-1] if len(discount_factors) > 0 else 0.0
    exit_ev = pv_ufcf + pv_exit_tv
    exit_equity = exit_ev + cash_equiv - total_debt
    exit_implied_price = max(0.0, exit_equity / shares_out) if shares_out > 0 else 0.0

    # Point 5: Terminal Value Share of Enterprise Value (>75% flagged)
    tv_share_of_ev = float(pv_terminal_value / enterprise_val) if enterprise_val > 0 else 0.0
    tv_share_flag = bool(tv_share_of_ev > 0.75)
    tv_share_note = None
    if tv_share_flag:
        tv_share_note = (
            f"Terminal Value accounts for {tv_share_of_ev*100:.1f}% of Enterprise Value (>75% threshold). "
            f"Model valuation is heavily dependent on perpetual assumptions."
        )

    return {
        "implied_price": float(implied_price),
        "enterprise_value": float(enterprise_val),
        "exit_implied_price": float(exit_implied_price),
        "benchmark_exit_multiple": float(benchmark_exit_mult),
        "implied_exit_multiple": float(implied_exit_multiple) if implied_exit_multiple is not None else None,
        "is_extractive": is_extractive,
        "is_cyclical": is_cyclical,
        "projected_revenue": [float(r) for r in proj_rev],
        "projected_ufcf": [float(u) for u in proj_ufcf],
        "projected_nopat": [float(n) for n in proj_nopat],
        "projected_dna": [float(d) for d in proj_dna],
        "projected_capex": [float(c) for c in proj_capex],
        "projected_dnwc": [float(dw) for dw in proj_dnwc],
        "growth_schedule": growth_schedule.tolist(),
        "margin_schedule": margin_schedule.tolist(),
        "pv_ufcf": float(pv_ufcf),
        "pv_ufcf_list": [float(p) for p in pv_ufcf_list],
        "discount_periods": discount_periods,
        "discount_factors": [float(1.0 / df) for df in discount_factors],
        "terminal_value": float(terminal_value) if terminal_value is not None else None,
        "pv_terminal_value": float(pv_terminal_value),
        "equity_value": float(equity_value),
        "terminal_value_valid": terminal_value_valid,
        "terminal_value_note": terminal_value_note,
        "terminal_growth_capped": terminal_growth_capped,
        "effective_terminal_growth": float(effective_terminal_growth),
        "tv_share_of_ev": float(tv_share_of_ev),
        "tv_share_flag": tv_share_flag,
        "tv_share_note": tv_share_note,
        "normalized_nwc_to_revenue": float(normalized_nwc_to_revenue),
        "tax_rate": float(tax_rate),
        "terminal_growth": float(terminal_growth),
        "use_mid_year": use_mid_year,
    }
