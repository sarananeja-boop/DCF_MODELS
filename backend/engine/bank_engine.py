"""
Banking & Financial Institutions Valuation Engine
=================================================

Dedicated valuation framework for Financial Services (Banks, NBFCs, Insurance,
Capital Markets, Consumer Finance).

Financial institutions operate under fundamentally different economic and regulatory
principles than non-financial corporations:
1. Customer deposits and wholesale borrowings are OPERATIONAL INVENTORY, not capital structure debt.
2. Interest expense is direct Cost of Goods Sold (COGS).
3. Working capital adjustments are inapplicable because loans and deposits form the primary asset/liability base.
4. Capital reinvestment is REGULATORY CAPITAL RETENTION (Tier-1 equity needed to maintain
   capital adequacy ratios / CRAR as risk-weighted assets expand), not physical CapEx.
5. Equity is valued directly using the Multi-Stage Free Cash Flow to Equity (FCFE) /
   Dividend Discount Model (DDM) discounted at the Cost of Equity (Ke). WACC is not applicable.
6. A Justified Price-to-Book (P/B) / Residual Income model is provided as an institutional cross-check.

Reference: Professor Aswath Damodaran, "Valuing Financial Services Firms".
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def compute_bank_cost_of_equity(stock_data: dict, market_profile: dict) -> dict:
    """Compute Cost of Equity (Ke) via CAPM for a financial institution.

    For banks, debt is operational, so equity is the entire capital claim being valued.
    WACC is identical to Ke.
    """
    rf = float(market_profile.get("risk_free_rate", 0.071))
    rm = float(market_profile.get("market_return", 0.13))
    erp = rm - rf
    raw_beta = stock_data.get("beta", 1.0)
    beta = float(raw_beta) if raw_beta and not np.isnan(raw_beta) else 1.0

    ke = rf + beta * erp

    op_debt = 0.0
    bs = stock_data.get("balance_sheet")
    if hasattr(bs, "columns") and "Total Debt" in bs.columns and len(bs) > 0:
        val = bs["Total Debt"].iloc[0]
        if not np.isnan(val):
            op_debt = float(val)

    return {
        "cost_of_equity": float(ke),
        "wacc": float(ke),  # Ke represents the discount rate for equity
        "cost_of_debt": 0.0,
        "weight_equity": 1.0,
        "weight_debt": 0.0,
        "total_debt": 0.0,
        "operational_debt": op_debt,
        "risk_free_rate": rf,
        "market_return": rm,
        "equity_risk_premium": erp,
        "beta": beta,
        "is_financial": True,
        "note": "For financial institutions, customer deposits and borrowings are operational inventory rather than capital structure debt. Cost of Equity (Ke) is used directly.",
    }


def run_bank_valuation(
    start_growth: float,
    target_roe: Optional[float],
    cost_of_equity: float,
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float = 0.055,
    projection_years: int = 5,
    current_roe: Optional[float] = None,
    use_mid_year: bool = True,
) -> dict:
    """Execute Damodaran's Multi-Stage Regulatory Capital FCFE / DDM model.

    Args:
        start_growth: Year-1 Net Income growth rate.
        target_roe: Terminal or target Return on Equity (ROE).
        cost_of_equity: CAPM Ke discount rate.
        metrics: Historical metrics from data_layer.
        stock_data: Ticker metadata and statements.
        market_profile: Macro parameters.
        terminal_growth: Long-term nominal GDP growth rate (bounded by Rf).
        projection_years: Number of forecast years (default 5).
        current_roe: Optional override for base ROE.
        use_mid_year: Whether to use institutional mid-year discounting (t = 0.5, 1.5, ...).

    Returns:
        A dict containing implied per share price, equity value, forecast schedules,
        discounting metrics, and justified P/B cross-check.
    """
    shares_out = float(stock_data.get("shares_outstanding", 1.0))
    current_price = float(stock_data.get("current_price", 1.0))
    market = stock_data.get("market", "IN")
    tax_rate = float(stock_data.get("_tax_rate", market_profile.get("tax_rate", 0.2517 if market == "IN" else 0.21)))

    # Determine Base Net Income
    net_income_hist = metrics.get("net_income", [])
    valid_ni = [float(x) for x in net_income_hist if x > 0]
    if valid_ni:
        base_net_income = valid_ni[-1]
    else:
        # Fallback to revenue-based estimate or earnings
        last_rev = metrics.get("last_revenue", 1e9)
        base_net_income = last_rev * 0.15

    # Determine Base Book Value of Equity
    bve_hist = metrics.get("book_value", [])
    valid_bve = [float(x) for x in bve_hist if x > 0]
    if valid_bve:
        base_bve = valid_bve[-1]
    else:
        info_bv = stock_data.get("info", {}).get("bookValue")
        if info_bv and info_bv > 0:
            base_bve = float(info_bv) * shares_out
        else:
            base_bve = base_net_income / 0.14

    bvps = base_bve / shares_out if shares_out > 0 else 0.0

    # Base ROE determination
    calc_roe = base_net_income / base_bve if base_bve > 0 else 0.14
    info_roe = stock_data.get("info", {}).get("returnOnEquity")
    
    if current_roe is not None:
        base_roe = current_roe
    elif info_roe and not np.isnan(info_roe) and info_roe > 0:
        base_roe = float(info_roe)
    else:
        base_roe = calc_roe

    # Bound reasonable base ROE
    base_roe = max(0.05, min(0.35, base_roe))

    # Target ROE (defaults to base ROE if not supplied)
    if target_roe is None:
        target_roe = base_roe
    else:
        target_roe = max(0.05, min(0.35, target_roe))

    # Construct linear schedules
    growth_schedule = np.linspace(start_growth, terminal_growth, projection_years)
    roe_schedule = np.linspace(base_roe, target_roe, projection_years)

    proj_net_income: List[float] = []
    proj_retention_rate: List[float] = []
    proj_reinvestment_equity: List[float] = []
    proj_fcfe: List[float] = []
    proj_bve: List[float] = []

    cur_ni = base_net_income
    cur_bve = base_bve

    for i in range(projection_years):
        g = float(growth_schedule[i])
        roe = float(roe_schedule[i])
        cur_ni = cur_ni * (1.0 + g)

        # Regulatory Capital Retention Rate: b = g / ROE
        # Equity retained to expand regulatory capital base
        if roe > 0:
            retention_b = min(0.95, max(0.05, g / roe))
        else:
            retention_b = 0.50

        reinvested_equity = cur_ni * retention_b
        fcfe = cur_ni * (1.0 - retention_b)
        cur_bve = cur_bve + reinvested_equity

        proj_net_income.append(float(cur_ni))
        proj_retention_rate.append(float(retention_b))
        proj_reinvestment_equity.append(float(reinvested_equity))
        proj_fcfe.append(float(fcfe))
        proj_bve.append(float(cur_bve))

    # Mid-Year Discounting
    if use_mid_year:
        discount_periods = [i + 0.5 for i in range(projection_years)]
    else:
        discount_periods = [float(i + 1) for i in range(projection_years)]

    discount_factors = [(1.0 + cost_of_equity) ** t for t in discount_periods]
    pv_fcfe_list = [f / df for f, df in zip(proj_fcfe, discount_factors)]
    pv_fcfe = sum(pv_fcfe_list)

    # Terminal Value Calculation (Gordon Growth Model with Regulatory Capital)
    terminal_value_valid = True
    terminal_value_note = ""

    if cost_of_equity <= terminal_growth:
        terminal_value = 0.0
        pv_terminal_value = 0.0
        terminal_value_valid = False
        terminal_value_note = "Cost of Equity (Ke) must exceed terminal growth rate for Gordon Growth model."
    else:
        term_roe = roe_schedule[-1]
        term_retention = min(0.95, max(0.05, terminal_growth / term_roe if term_roe > 0 else 0.50))
        term_ni = proj_net_income[-1] * (1.0 + terminal_growth)
        term_fcfe = term_ni * (1.0 - term_retention)

        terminal_value = term_fcfe / (cost_of_equity - terminal_growth)
        # In mid-year convention, TV is discounted using the Year-5 discount factor
        pv_terminal_value = terminal_value / discount_factors[-1]

    # Total Equity Value
    equity_value = pv_fcfe + pv_terminal_value
    implied_price = max(0.0, equity_value / shares_out) if shares_out > 0 else 0.0

    # Institutional Cross-Check: Justified Price-to-Book (P/B) Model
    # Justified P/B = (ROE - g) / (Ke - g)
    if cost_of_equity > terminal_growth:
        justified_pb = max(0.2, (roe_schedule[-1] - terminal_growth) / (cost_of_equity - terminal_growth))
    else:
        justified_pb = 1.0
    justified_price = max(0.0, bvps * justified_pb)

    # Return structure 100% compatible with standard DCF keys so frontend renders seamlessly
    return {
        "implied_price": float(implied_price),
        "enterprise_value": float(equity_value),  # For banks, Equity Value is the valued operational entity
        "equity_value": float(equity_value),
        "projected_revenue": [float(n) for n in proj_net_income],  # Displayed as Net Income in banking mode
        "projected_ufcf": [float(f) for f in proj_fcfe],          # FCFE
        "projected_nopat": [float(n) for n in proj_net_income],
        "projected_dna": [float(r) for r in proj_reinvestment_equity],  # Regulatory Capital Retained
        "projected_capex": [float(r) for r in proj_reinvestment_equity],
        "projected_dnwc": [0.0] * projection_years,
        "growth_schedule": growth_schedule.tolist(),
        "margin_schedule": roe_schedule.tolist(),  # ROE schedule
        "pv_ufcf": float(pv_fcfe),
        "pv_ufcf_list": [float(p) for p in pv_fcfe_list],
        "discount_periods": discount_periods,
        "discount_factors": [float(1.0 / df) for df in discount_factors],
        "terminal_value": float(terminal_value) if terminal_value is not None else None,
        "pv_terminal_value": float(pv_terminal_value),
        "terminal_value_valid": terminal_value_valid,
        "terminal_value_note": terminal_value_note,
        "tax_rate": float(tax_rate),
        "terminal_growth": float(terminal_growth),
        "use_mid_year": use_mid_year,
        # Dedicated Bank-Specific Fields
        "is_financial": True,
        "model_type": "BANKING_DDM",
        "base_net_income": float(base_net_income),
        "base_bve": float(base_bve),
        "bvps": float(bvps),
        "base_roe": float(base_roe),
        "target_roe": float(target_roe),
        "cost_of_equity": float(cost_of_equity),
        "justified_pb": float(justified_pb),
        "justified_price": float(justified_price),
        "projected_net_income": [float(n) for n in proj_net_income],
        "projected_fcfe": [float(f) for f in proj_fcfe],
        "projected_bve": [float(b) for b in proj_bve],
        "retention_schedule": [float(b) for b in proj_retention_rate],
        "payout_schedule": [float(1.0 - b) for b in proj_retention_rate],
        "roe_schedule": [float(r) for r in roe_schedule],
    }


def run_bank_monte_carlo(
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float,
    projection_years: int = 5,
    iterations: int = 1000,
    base_growth: Optional[float] = None,
    base_roe: Optional[float] = None,
    base_ke: Optional[float] = None,
) -> dict:
    """Run Monte Carlo simulation over banking valuation parameters.

    Stochastically samples Net Income growth, Return on Equity (ROE), and Cost of Equity (Ke).
    """
    g_mean = base_growth if base_growth is not None else float(metrics.get("avg_ni_growth", 0.10))
    g_std = float(metrics.get("std_ni_growth", 0.04))

    roe_mean = base_roe if base_roe is not None else float(metrics.get("avg_roe", 0.14))
    roe_std = float(metrics.get("std_roe", 0.02))

    ke_data = compute_bank_cost_of_equity(stock_data, market_profile)
    ke_mean = base_ke if base_ke is not None else float(ke_data["cost_of_equity"])
    ke_std = 0.015

    rng = np.random.default_rng()
    sim_growth = rng.normal(g_mean, max(0.01, g_std), iterations)
    sim_roe = rng.normal(roe_mean, max(0.01, roe_std), iterations)
    sim_ke = rng.normal(ke_mean, ke_std, iterations)

    # Bound distributions
    sim_growth = np.clip(sim_growth, -0.05, 0.35)
    sim_roe = np.clip(sim_roe, 0.05, 0.35)
    sim_ke = np.clip(sim_ke, terminal_growth + 0.005, 0.25)

    sim_prices: List[float] = []
    valid_count = 0

    for i in range(iterations):
        res = run_bank_valuation(
            start_growth=float(sim_growth[i]),
            target_roe=float(sim_roe[i]),
            cost_of_equity=float(sim_ke[i]),
            metrics=metrics,
            stock_data=stock_data,
            market_profile=market_profile,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
            use_mid_year=True,
        )
        p = res.get("implied_price", 0.0)
        if p > 0 and not np.isnan(p):
            sim_prices.append(p)
            valid_count += 1

    sim_arr = np.array(sim_prices) if sim_prices else np.array([0.0])
    current_price = float(stock_data.get("current_price", 1.0))

    stats = {
        "mean": float(np.mean(sim_arr)),
        "median": float(np.median(sim_arr)),
        "std": float(np.std(sim_arr)),
        "p10": float(np.percentile(sim_arr, 10)),
        "p25": float(np.percentile(sim_arr, 25)),
        "p75": float(np.percentile(sim_arr, 75)),
        "p90": float(np.percentile(sim_arr, 90)),
        "prob_undervalued": float(np.mean(sim_arr > current_price)) if len(sim_arr) > 0 else 0.0,
        "zero_price_simulations": iterations - valid_count,
        "positive_price_simulations": valid_count,
    }

    return {
        "stats": stats,
        "simulated_prices": sim_prices,
        "sim_growth": sim_growth.tolist(),
        "sim_margin": sim_roe.tolist(),  # mapped to margin for frontend compatibility
        "sim_wacc": sim_ke.tolist(),     # mapped to wacc for frontend compatibility
        "actual_iterations": len(sim_prices),
        "total_simulations": iterations,
        "valid_simulations": valid_count,
        "invalid_simulations": iterations - valid_count,
    }


def generate_bank_sensitivity_grid(
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float,
    projection_years: int = 5,
    base_growth: Optional[float] = None,
    base_roe: Optional[float] = None,
    base_ke: Optional[float] = None,
) -> dict:
    """Generate 5x5 sensitivity table: Net Income Growth vs Cost of Equity (Ke)."""
    ke_data = compute_bank_cost_of_equity(stock_data, market_profile)
    mid_ke = base_ke if base_ke is not None else float(ke_data["cost_of_equity"])
    mid_growth = base_growth if base_growth is not None else float(metrics.get("avg_ni_growth", 0.10))
    t_roe = base_roe if base_roe is not None else float(metrics.get("avg_roe", 0.14))

    growth_steps = [mid_growth - 0.02, mid_growth - 0.01, mid_growth, mid_growth + 0.01, mid_growth + 0.02]
    ke_steps = [mid_ke - 0.01, mid_ke - 0.005, mid_ke, mid_ke + 0.005, mid_ke + 0.01]

    grid: List[List[float]] = []

    for k in ke_steps:
        row: List[float] = []
        for g in growth_steps:
            if k <= terminal_growth:
                row.append(0.0)
            else:
                res = run_bank_valuation(
                    start_growth=g,
                    target_roe=t_roe,
                    cost_of_equity=k,
                    metrics=metrics,
                    stock_data=stock_data,
                    market_profile=market_profile,
                    terminal_growth=terminal_growth,
                    projection_years=projection_years,
                    use_mid_year=True,
                )
                row.append(res.get("implied_price", 0.0))
        grid.append(row)

    return {
        "wacc_range": ke_steps,          # Ke
        "growth_range": growth_steps,    # Net Income Growth
        "grid": grid,
    }
