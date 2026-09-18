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
# WACC
# ---------------------------------------------------------------------------

def compute_wacc(
    stock_data: dict,
    metrics: dict,
    market_profile: dict,
) -> dict:
    """Compute the Weighted Average Cost of Capital (WACC).

    Mirrors notebook Step 4A–4C.

    * **Cost of Equity** via CAPM: ``K_E = R_f + β × (R_m − R_f)``
    * **Cost of Debt**: ``Interest Expense / Total Debt`` (fallback 4 %).
    * **Capital weights**: market-value equity vs book-value debt.
    * **WACC**: ``W_E × K_E + W_D × K_D × (1 − T)``

    Args:
        stock_data:     Dict from :func:`data_layer.fetch_stock_data`.
        metrics:        Dict from :func:`data_layer.compute_historical_metrics`.
        market_profile: Dict from :func:`market_config.get_market_profile`.

    Returns:
        Dict with: ``cost_of_equity``, ``cost_of_debt``, ``weight_equity``,
        ``weight_debt``, ``wacc``, ``total_debt``.
    """
    risk_free_rate: float = market_profile["risk_free_rate"]
    market_return: float = market_profile["market_return"]
    tax_rate: float = market_profile["tax_rate"]

    beta: float = stock_data["beta"]
    market_cap: float = stock_data["market_cap"]
    total_debt: float = metrics["total_debt"]
    interest_expense: float = metrics["interest_expense"]

    # 4A – CAPM → Cost of Equity
    raw_cost_of_equity: float = risk_free_rate + beta * (market_return - risk_free_rate)
    
    # Fundamental economic guard: Cost of equity must reflect an equity risk premium
    # Common equity is strictly riskier than sovereign debt (Rf). Minimum floor Rf + 1.5%
    ke_min = risk_free_rate + 0.015
    ke_floored = False
    ke_note = None
    if raw_cost_of_equity < ke_min:
        cost_of_equity = ke_min
        ke_floored = True
        ke_note = f"Cost of equity floored at {ke_min*100:.1f}% (Rf + 1.5% minimum equity risk premium)."
    else:
        cost_of_equity = raw_cost_of_equity

    # 4B – Cost of Debt
    if total_debt > 0 and interest_expense != 0:
        cost_of_debt = abs(interest_expense / total_debt)
    else:
        cost_of_debt = 0.04  # fallback

    # 4C – Capital structure weights
    total_capital = market_cap + total_debt
    if total_capital > 0:
        weight_equity = market_cap / total_capital
        weight_debt = total_debt / total_capital
    else:
        weight_equity = 1.0
        weight_debt = 0.0

    wacc = (weight_equity * cost_of_equity) + (weight_debt * cost_of_debt * (1 - tax_rate))

    return {
        "cost_of_equity": float(cost_of_equity),
        "raw_cost_of_equity": float(raw_cost_of_equity),
        "ke_floored": ke_floored,
        "ke_note": ke_note,
        "cost_of_debt": float(cost_of_debt),
        "weight_equity": float(weight_equity),
        "weight_debt": float(weight_debt),
        "wacc": float(wacc),
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

    Implements institutional Damodaran DCF modeling (matching HUL FINAL MODEL.xlsx):

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

    for yr in range(projection_years):
        g = growth_schedule[yr]
        next_rev = last_rev * (1 + g)
        margin = margin_schedule[yr]

        nopat = next_rev * margin * (1 - tax_rate)
        dna_add = next_rev * avg_dna_pct
        capex_sub = next_rev * avg_capex_pct
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

    # Terminal Value via Gordon Growth Model
    terminal_value_valid = True
    terminal_value_note = None
    terminal_growth_capped = False
    effective_terminal_growth = terminal_growth
    
    if proj_ufcf[-1] <= 0:
        terminal_value = None
        pv_terminal_value = 0.0
        terminal_value_valid = False
        terminal_value_note = "Terminal UFCF is negative under current assumptions. Gordon Growth terminal value is not supported."
    elif discount_rate <= terminal_growth:
        terminal_value = None
        pv_terminal_value = 0.0
        terminal_value_valid = False
        terminal_value_note = "WACC must exceed terminal growth rate for Gordon Growth model."
    else:
        # Protect against denominator compression (WACC - g < 2.0%) which causes explosive valuations
        spread = discount_rate - terminal_growth
        if spread < 0.020:
            effective_terminal_growth = discount_rate - 0.020
            terminal_growth_capped = True
            terminal_value_note = f"Terminal growth capped at {effective_terminal_growth*100:.1f}% to preserve minimum 2.0% WACC spread."
            terminal_value = (proj_ufcf[-1] * (1.0 + effective_terminal_growth)) / 0.020
        else:
            terminal_value = (proj_ufcf[-1] * (1.0 + terminal_growth)) / spread

        # In HUL FINAL MODEL.xlsx (D29 = D24 * J10), TV is discounted using the final forecast period factor
        pv_terminal_value = terminal_value / discount_factors[-1]

    # EV → Equity bridge
    enterprise_val = pv_ufcf + pv_terminal_value
    equity_value = enterprise_val + cash_equiv - total_debt
    
    # Implied price per share floored at 0.0
    implied_price = max(0.0, equity_value / shares_out) if shares_out > 0 else 0.0

    return {
        "implied_price": float(implied_price),
        "enterprise_value": float(enterprise_val),
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
        "normalized_nwc_to_revenue": float(normalized_nwc_to_revenue),
        "tax_rate": float(tax_rate),
        "terminal_growth": float(terminal_growth),
        "use_mid_year": use_mid_year,
    }
