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
    cost_of_equity: float = risk_free_rate + beta * (market_return - risk_free_rate)

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
) -> dict:
    """Run a single multi-stage DCF valuation with linear growth fade.

    Implements the **exact** logic from notebook Step 4E:

    1. Revenue grows from ``start_growth`` in Year 1 to ``terminal_growth``
       in Year *N* via ``np.linspace``.
    2. UFCF = NOPAT + D&A − CapEx − Δ NWC (all as % of projected revenue).
    3. Discount projected UFCFs.
    4. Terminal Value via Gordon Growth Model.
    5. EV → Equity bridge (add cash, subtract debt, floor at 0).

    Args:
        start_growth:     Year-1 revenue growth rate (decimal).
        ebit_margin:      EBIT / Revenue (decimal).
        discount_rate:    WACC used for discounting (decimal).
        metrics:          Dict from ``compute_historical_metrics``.
        wacc_data:        Dict from ``compute_wacc``.
        stock_data:       Dict from ``fetch_stock_data``.
        terminal_growth:  Long-run growth (default 2.5 %).
        projection_years: Number of projected years (default 5).

    Returns:
        Dict with: ``implied_price``, ``enterprise_value``,
        ``projected_revenue`` (list), ``projected_ufcf`` (list),
        ``growth_schedule`` (list), ``pv_ufcf``, ``terminal_value``,
        ``pv_terminal_value``, ``equity_value``.
    """
    avg_dna_pct: float = metrics["avg_dna_pct"]
    avg_capex_pct: float = metrics["avg_capex_pct"]
    avg_dnwc_pct: float = metrics["avg_dnwc_pct"]
    last_revenue: float = metrics["last_revenue"]
    total_debt: float = wacc_data["total_debt"]
    cash_equiv: float = metrics["cash_and_equivalents"]
    shares_out: float = stock_data["shares_outstanding"]
    tax_rate: float = stock_data.get("_tax_rate", 0.21)

    # Allow callers (e.g. Monte Carlo) to pass tax_rate explicitly via stock_data
    # but fall back to market_profile if available, else default 21 %.
    # The notebook uses the global TAX_RATE constant (0.21).
    # For flexibility we look for a private key first.

    proj_ufcf: List[float] = []
    proj_rev: List[float] = []
    last_rev = last_revenue

    # Linear fade from start_growth → terminal_growth
    growth_schedule = np.linspace(start_growth, terminal_growth, projection_years)

    for yr in range(projection_years):
        g = growth_schedule[yr]
        next_rev = last_rev * (1 + g)

        nopat = next_rev * ebit_margin * (1 - tax_rate)
        ufcf = (
            nopat
            + (next_rev * avg_dna_pct)
            - (next_rev * avg_capex_pct)
            - (next_rev * avg_dnwc_pct)
        )

        proj_ufcf.append(ufcf)
        proj_rev.append(next_rev)
        last_rev = next_rev

    # Discount projected UFCFs
    discount_factors = [(1 + discount_rate) ** (i + 1) for i in range(projection_years)]
    pv_ufcf = sum(cf / df for cf, df in zip(proj_ufcf, discount_factors))

    # Terminal Value via Gordon Growth Model
    terminal_value = (proj_ufcf[-1] * (1 + terminal_growth)) / (discount_rate - terminal_growth)
    pv_terminal_value = terminal_value / ((1 + discount_rate) ** projection_years)

    # EV → Equity bridge
    enterprise_val = pv_ufcf + pv_terminal_value
    equity_value = max(0.0, enterprise_val + cash_equiv - total_debt)
    implied_price = equity_value / shares_out if shares_out > 0 else 0.0

    return {
        "implied_price": float(implied_price),
        "enterprise_value": float(enterprise_val),
        "projected_revenue": [float(r) for r in proj_rev],
        "projected_ufcf": [float(u) for u in proj_ufcf],
        "growth_schedule": growth_schedule.tolist(),
        "pv_ufcf": float(pv_ufcf),
        "terminal_value": float(terminal_value),
        "pv_terminal_value": float(pv_terminal_value),
        "equity_value": float(equity_value),
    }
