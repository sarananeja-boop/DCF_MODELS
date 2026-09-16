"""
Monte Carlo Engine – Cholesky-Correlated Simulation
====================================================

Refactored from Step 5 of the Automated DCF Monte Carlo *Refined* notebook.

Key features:
  * 7 risk-factor variables with empirically estimated correlation.
  * Cholesky decomposition for correlated draws.
  * Student's t-distribution (df = 5) for fat tails.
  * 3× oversampling with reject-and-resample (no clamping).
  * WACC is *derived economically* per iteration, not drawn directly.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
from scipy.stats import t as t_dist

from .dcf_engine import run_dcf

logger = logging.getLogger(__name__)


def run_monte_carlo(
    metrics: dict,
    wacc_data: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float = 0.025,
    projection_years: int = 5,
    iterations: int = 10_000,
) -> dict:
    """Run a Cholesky-correlated Monte Carlo DCF simulation.

    Implements the **exact** logic from notebook Step 5 (refined version):

    1. **7 variables**: Rev Growth, EBIT Margin, Risk-Free Rate, Beta,
       ERP, Cost of Debt, Equity Weight.
    2. Empirically estimate correlation between ``rev_growth`` and
       ``ebit_margins`` from historical data.
    3. Build a 7×7 correlation matrix (empirical for growth-margin,
       0 elsewhere).
    4. Cholesky decomposition → ``L``.
    5. Student's t draws (df = 5), oversample 3×.
    6. Apply ``L @ z`` correlation structure.
    7. Scale with means and stds.
    8. Derive WACC per iteration economically.
    9. Reject-and-resample invalid draws.
    10. Run DCF for each valid iteration.

    Args:
        metrics:          Dict from ``compute_historical_metrics``.
        wacc_data:        Dict from ``compute_wacc``.
        stock_data:       Dict from ``fetch_stock_data``.
        market_profile:   Dict from ``get_market_profile``.
        terminal_growth:  Long-run growth rate (default 2.5 %).
        projection_years: Number of projected years (default 5).
        iterations:       Target number of valid draws (default 10 000).

    Returns:
        Dict with: ``simulated_prices`` (list), ``simulated_evs`` (list),
        ``actual_iterations``, ``stats`` (mean, median, p5, p25, p75, p95),
        ``hist_corr_gm``, ``sim_growth`` (list), ``sim_margin`` (list),
        ``sim_wacc`` (list).
    """
    tax_rate: float = market_profile["tax_rate"]
    risk_free_rate: float = market_profile["risk_free_rate"]
    market_return: float = market_profile["market_return"]

    rev_growth_arr = np.array(metrics["rev_growth"])
    ebit_margins_arr = np.array(metrics["ebit_margins"])

    # ------------------------------------------------------------------
    # 5A – Correlation structure
    # ------------------------------------------------------------------
    num_vars = 7

    # Empirical correlation between rev_growth and ebit_margins (aligned)
    ebit_margins_aligned = ebit_margins_arr[1:] if len(ebit_margins_arr) > 1 else np.array([])
    if (
        len(rev_growth_arr) > 1
        and len(ebit_margins_aligned) > 0
        and np.std(rev_growth_arr) > 0
        and np.std(ebit_margins_aligned) > 0
    ):
        hist_corr_gm = float(np.corrcoef(rev_growth_arr, ebit_margins_aligned)[0, 1])
        if np.isnan(hist_corr_gm):
            hist_corr_gm = 0.0
        else:
            # Clip strictly inside (-1, 1) to guarantee positive definite matrix for Cholesky
            hist_corr_gm = np.clip(hist_corr_gm, -0.99, 0.99)
    else:
        hist_corr_gm = 0.0

    corr_matrix = np.eye(num_vars)
    corr_matrix[0, 1] = hist_corr_gm
    corr_matrix[1, 0] = hist_corr_gm

    try:
        L = np.linalg.cholesky(corr_matrix)
    except np.linalg.LinAlgError:
        logger.warning("Cholesky decomposition failed. Falling back to independent variables.")
        L = np.eye(num_vars)

    # ------------------------------------------------------------------
    # 5B – Correlated fat-tailed draws
    # ------------------------------------------------------------------
    np.random.seed(42)
    oversample = iterations * 3

    independent_draws = t_dist.rvs(df=5, size=(num_vars, oversample))
    correlated_draws = L @ independent_draws

    # Means and standard deviations (exact values from the refined notebook)
    mean_rev_growth = metrics["avg_rev_growth"]
    std_rev_growth_mc = max(metrics["std_rev_growth"], 0.02)

    mean_ebit_margin = metrics["avg_ebit_margin"]
    std_ebit_margin_mc = max(metrics["std_ebit_margin"], 0.015)

    mean_rf = risk_free_rate
    std_rf = 0.01       # 100 bps assumed volatility for 10Y Treasury

    mean_beta = stock_data["beta"]
    std_beta = 0.15      # assumed estimation error

    mean_erp = market_return - risk_free_rate
    std_erp = 0.015      # 150 bps assumed volatility

    mean_cod = wacc_data["cost_of_debt"]
    std_cod = 0.01       # 100 bps assumed volatility

    mean_we = wacc_data["weight_equity"]
    std_we = 0.05        # 5 % fluctuation assumed

    means = np.array([
        mean_rev_growth, mean_ebit_margin, mean_rf,
        mean_beta, mean_erp, mean_cod, mean_we,
    ])
    stds = np.array([
        std_rev_growth_mc, std_ebit_margin_mc, std_rf,
        std_beta, std_erp, std_cod, std_we,
    ])

    samples = means[:, None] + correlated_draws * stds[:, None]

    sim_growth = samples[0, :]
    sim_margin = samples[1, :]
    sim_rf     = samples[2, :]
    sim_beta   = samples[3, :]
    sim_erp    = samples[4, :]
    sim_cod    = samples[5, :]
    sim_we     = np.clip(samples[6, :], 0.0, 1.0)

    # Derive WACC economically per iteration
    sim_wd = 1.0 - sim_we
    sim_coe = sim_rf + (sim_beta * sim_erp)
    sim_at_cod = sim_cod * (1 - tax_rate)
    sim_wacc = (sim_we * sim_coe) + (sim_wd * sim_at_cod)

    # ------------------------------------------------------------------
    # 5C – Reject-and-resample
    # ------------------------------------------------------------------
    valid_mask = (
        (sim_wacc > terminal_growth + 0.005)
        & (sim_cod > 0)
        & (sim_rf > 0)
        & (sim_erp > 0)
    )

    sim_growth = sim_growth[valid_mask][:iterations]
    sim_margin = sim_margin[valid_mask][:iterations]
    sim_wacc   = sim_wacc[valid_mask][:iterations]

    actual_n = len(sim_growth)

    if actual_n == 0:
        logger.warning("No valid Monte Carlo draws after rejection filtering.")
        return {
            "simulated_prices": [],
            "simulated_evs": [],
            "actual_iterations": 0,
            "stats": {},
            "hist_corr_gm": hist_corr_gm,
            "sim_growth": [],
            "sim_margin": [],
            "sim_wacc": [],
        }

    if actual_n < iterations:
        logger.warning(
            "Only %d valid draws after rejection (target: %d).", actual_n, iterations
        )

    # ------------------------------------------------------------------
    # 5D – Run DCF for every valid iteration
    # ------------------------------------------------------------------
    # Inject tax_rate into stock_data for run_dcf
    stock_data_sim = dict(stock_data)
    stock_data_sim["_tax_rate"] = tax_rate

    simulated_prices = np.empty(actual_n)
    simulated_evs = np.empty(actual_n)
    simulated_raw_equity = np.empty(actual_n)

    for i in range(actual_n):
        result = run_dcf(
            start_growth=sim_growth[i],
            ebit_margin=sim_margin[i],
            discount_rate=sim_wacc[i],
            metrics=metrics,
            wacc_data=wacc_data,
            stock_data=stock_data_sim,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
        )
        simulated_prices[i] = result["implied_price"]
        simulated_evs[i] = result["enterprise_value"]
        simulated_raw_equity[i] = result["equity_value"]

    # ------------------------------------------------------------------
    # 5E – Statistics
    # ------------------------------------------------------------------
    valid_prices_mask = np.isfinite(simulated_prices) & np.isfinite(simulated_raw_equity)
    final_prices = simulated_prices[valid_prices_mask]
    final_evs = simulated_evs[valid_prices_mask]
    final_raw_equity = simulated_raw_equity[valid_prices_mask]
    
    math_invalid_count = actual_n - len(final_prices)

    zero_price_sims = int(np.sum(final_prices == 0.0))
    neg_equity_sims = int(np.sum(final_raw_equity < 0.0))
    valid_n = len(final_prices)
    shares_out = stock_data.get("shares_outstanding", 1.0)

    if valid_n > 0:
        stats = {
            "mean": float(np.mean(final_prices)),
            "median": float(np.median(final_prices)),
            "std_dev": float(np.std(final_prices, ddof=1)) if valid_n > 1 else 0.0,
            "p5": float(np.percentile(final_prices, 5)),
            "p25": float(np.percentile(final_prices, 25)),
            "p75": float(np.percentile(final_prices, 75)),
            "p95": float(np.percentile(final_prices, 95)),
            
            # Advanced Diagnostics
            "zero_price_simulations": zero_price_sims,
            "negative_equity_simulations": neg_equity_sims,
            "positive_price_simulations": int(np.sum(final_prices > 0.0)),
            "zero_price_pct": float(zero_price_sims / valid_n) if valid_n > 0 else 0.0,
            "min_raw_equity_value": float(np.min(final_raw_equity)),
            "min_raw_share_price": float(np.min(final_raw_equity) / shares_out) if shares_out > 0 else 0.0,
            "max_share_price": float(np.max(final_prices)),
        }
    else:
        stats = {}
        
    invalid_simulation_reasons = {
        "wacc_too_low": int(np.sum(samples[6, :] * (samples[2, :] + samples[3, :] * samples[4, :]) + (1 - samples[6, :]) * samples[5, :] * (1 - tax_rate) <= terminal_growth + 0.005)),
        "negative_cod": int(np.sum(samples[5, :] <= 0)),
        "negative_rf": int(np.sum(samples[2, :] <= 0)),
        "negative_erp": int(np.sum(samples[4, :] <= 0)),
        "nan_inf_result": int(math_invalid_count)
    }

    return {
        "simulated_prices": final_prices.tolist(),
        "simulated_evs": final_evs.tolist(),
        "simulated_raw_equity": final_raw_equity.tolist(),
        "total_simulations": oversample,
        "valid_simulations": valid_n,
        "invalid_simulations": oversample - valid_n,
        "invalid_simulation_reasons": invalid_simulation_reasons,
        "actual_iterations": valid_n,
        "stats": stats,
        "hist_corr_gm": hist_corr_gm,
        "sim_growth": sim_growth.tolist(),
        "sim_margin": sim_margin.tolist(),
        "sim_wacc": sim_wacc.tolist(),
    }
