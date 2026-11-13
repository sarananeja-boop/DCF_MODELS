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

import hashlib
import json
import logging
from typing import Any, Dict, Optional

import numpy as np

from .dcf_engine import run_dcf, run_dcf_batch

logger = logging.getLogger(__name__)


def run_monte_carlo(
    metrics: dict,
    wacc_data: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float = 0.025,
    projection_years: int = 5,
    iterations: int = 10_000,
    base_growth: float = None,
    base_margin: float = None,
    base_wacc: float = None,
    current_margin: Optional[float] = None,
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
    corr_sample_size = min(len(rev_growth_arr), len(ebit_margins_aligned))
    is_corr_regularized = False
    raw_corr_gm: Optional[float] = None
    corr_method = "insufficient_sample_zero_fallback"

    if corr_sample_size >= 4:
        g_slice = rev_growth_arr[-corr_sample_size:]
        m_slice = ebit_margins_aligned[-corr_sample_size:]
        if np.std(g_slice) > 1e-6 and np.std(m_slice) > 1e-6:
            raw_corr = float(np.corrcoef(g_slice, m_slice)[0, 1])
            if np.isfinite(raw_corr):
                raw_corr_gm = raw_corr
                shrinkage = corr_sample_size / (corr_sample_size + 4.0)
                hist_corr_gm = float(np.clip(raw_corr * shrinkage, -0.90, 0.90))
                corr_method = "empirical_eb_shrinkage"
                is_corr_regularized = abs(hist_corr_gm - raw_corr) > 0.05
            else:
                hist_corr_gm = 0.0
        else:
            hist_corr_gm = 0.0
    elif corr_sample_size == 3:
        g_slice = rev_growth_arr[-3:]
        m_slice = ebit_margins_aligned[-3:]
        if np.std(g_slice) > 1e-6 and np.std(m_slice) > 1e-6:
            raw_corr = float(np.corrcoef(g_slice, m_slice)[0, 1])
            if np.isfinite(raw_corr):
                raw_corr_gm = raw_corr
                # Strong Empirical Bayes shrinkage toward neutral 0.0 for N=3 small samples
                shrinkage = 3.0 / (3.0 + 6.0)
                hist_corr_gm = float(np.clip(raw_corr * shrinkage, -0.50, 0.50))
                corr_method = "small_sample_shrunk_eb"
                is_corr_regularized = True
            else:
                hist_corr_gm = 0.0
        else:
            hist_corr_gm = 0.0
    else:
        hist_corr_gm = 0.0
        is_corr_regularized = corr_sample_size > 0

    corr_matrix = np.eye(num_vars)
    corr_matrix[0, 1] = hist_corr_gm
    corr_matrix[1, 0] = hist_corr_gm
    # Economic cross-correlations among discount-rate / capital-structure factors:
    # [2: Rf, 3: Beta, 4: ERP, 5: Pre-Tax Kd, 6: Equity Weight]
    corr_matrix[2, 5] = corr_matrix[5, 2] = 0.50   # Sovereign yield vs corporate borrowing rate
    corr_matrix[3, 4] = corr_matrix[4, 3] = 0.20   # Beta vs Equity Risk Premium
    corr_matrix[5, 6] = corr_matrix[6, 5] = -0.30  # Pre-Tax Kd vs Equity Weight (higher debt weight -> higher spread)

    try:
        L = np.linalg.cholesky(corr_matrix)
    except np.linalg.LinAlgError:
        logger.warning("Cholesky decomposition failed. Falling back to growth-margin correlation only.")
        corr_fallback = np.eye(num_vars)
        corr_fallback[0, 1] = corr_fallback[1, 0] = hist_corr_gm
        try:
            L = np.linalg.cholesky(corr_fallback)
        except np.linalg.LinAlgError:
            L = np.eye(num_vars)

    # ------------------------------------------------------------------
    # 5B – Correlated fat-tailed draws (Student-t df=5 normalized to unit variance)
    # ------------------------------------------------------------------
    mc_seed = 42
    rng = np.random.default_rng(mc_seed)
    oversample = iterations * 3

    # Var(t_5) = 5 / (5 - 2) = 5/3; scale by sqrt(3/5) so draws preserve t(5) fat tails with unit variance
    independent_draws = rng.standard_t(5, size=(num_vars, oversample)) * np.sqrt(3.0 / 5.0)
    correlated_draws = L @ independent_draws

    # Means and standard deviations (bounded so 1-year historical outliers do not explode perpetual variance)
    mean_rev_growth = base_growth if base_growth is not None else metrics["avg_rev_growth"]
    std_rev_growth_mc = float(np.clip(metrics["std_rev_growth"], 0.02, 0.12))

    mean_ebit_margin = base_margin if base_margin is not None else metrics["avg_ebit_margin"]
    std_ebit_margin_mc = float(np.clip(metrics["std_ebit_margin"], 0.015, 0.06))

    mean_rf = risk_free_rate
    std_rf = 0.01       # 100 bps assumed volatility for 10Y Treasury

    mean_beta = stock_data["beta"]
    std_beta = 0.15      # assumed estimation error

    mean_erp = market_return - risk_free_rate
    std_erp = 0.015      # 150 bps assumed volatility

    # Use pre-tax cost of debt because sim_at_cod = sim_cod * (1 - tax_rate) applies the tax shield below
    pretax_cod = wacc_data.get("pretax_cost_of_debt")
    if pretax_cod is None or pretax_cod <= 0:
        pretax_cod = wacc_data.get("cost_of_debt", 0.05) / max(0.5, 1.0 - tax_rate)
    mean_cod = float(pretax_cod)
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

    margin_floor = max(0.015, mean_ebit_margin * 0.30) if mean_ebit_margin > 0.02 else -0.15
    margin_ceil = min(0.68, max(mean_ebit_margin + 0.15, mean_ebit_margin + 2.5 * std_ebit_margin_mc))

    sim_growth = np.clip(samples[0, :], -0.20, 0.65)
    sim_margin = np.clip(samples[1, :], margin_floor, margin_ceil)
    sim_rf     = samples[2, :]
    sim_beta   = np.clip(samples[3, :], 0.25, 3.0)
    sim_erp    = samples[4, :]
    sim_cod    = samples[5, :]
    sim_we     = np.clip(samples[6, :], 0.0, 1.0)

    # Derive WACC economically per iteration
    sim_wd = 1.0 - sim_we
    sim_coe = sim_rf + (sim_beta * sim_erp)
    sim_at_cod = sim_cod * (1 - tax_rate)
    sim_wacc = (sim_we * sim_coe) + (sim_wd * sim_at_cod)

    # If a WACC override was provided, shift the distribution to match the overridden mean
    if base_wacc is not None:
        sim_wacc = sim_wacc - np.mean(sim_wacc) + base_wacc

    # ------------------------------------------------------------------
    # 5C – Reject-and-resample (masks computed on exact post-clip/shift candidates)
    # ------------------------------------------------------------------
    mask_wacc_too_low = sim_wacc <= (terminal_growth + 0.005)
    mask_neg_cod = sim_cod <= 0.0
    mask_neg_rf = sim_rf <= 0.0
    mask_neg_erp = sim_erp <= 0.0
    valid_mask = ~(mask_wacc_too_low | mask_neg_cod | mask_neg_rf | mask_neg_erp)

    total_candidate_valid = int(np.sum(valid_mask))
    rejected_filter_draws = int(oversample - total_candidate_valid)

    sim_growth = sim_growth[valid_mask][:iterations]
    sim_margin = sim_margin[valid_mask][:iterations]
    sim_wacc   = sim_wacc[valid_mask][:iterations]

    actual_n = len(sim_growth)
    unused_valid_oversample = max(0, total_candidate_valid - actual_n)

    distribution_specs: Dict[str, Any] = {
        "family": "Student-t",
        "df": 5,
        "variance_scale": float(np.sqrt(3.0 / 5.0)),
        "variables": {
            "rev_growth": {"mean": float(mean_rev_growth), "std": float(std_rev_growth_mc), "clip": [-0.20, 0.65]},
            "ebit_margin": {"mean": float(mean_ebit_margin), "std": float(std_ebit_margin_mc), "clip": [float(margin_floor), float(margin_ceil)]},
            "risk_free_rate": {"mean": float(mean_rf), "std": float(std_rf), "constraint": "> 0"},
            "beta": {"mean": float(mean_beta), "std": float(std_beta), "clip": [0.25, 3.0]},
            "erp": {"mean": float(mean_erp), "std": float(std_erp), "constraint": "> 0"},
            "pretax_cod": {"mean": float(mean_cod), "std": float(std_cod), "constraint": "> 0"},
            "equity_weight": {"mean": float(mean_we), "std": float(std_we), "clip": [0.0, 1.0]},
        },
        "wacc_mean_override": float(base_wacc) if base_wacc is not None else None,
        "min_wacc_condition": f"> {terminal_growth + 0.005:.4f}",
    }
    shares_out = float(stock_data.get("diluted_valuation_shares") or stock_data.get("shares_outstanding") or 1.0)
    snapshot_payload = {
        "ticker": stock_data.get("ticker"),
        "seed": mc_seed,
        "requested_iterations": int(iterations),
        "oversample": int(oversample),
        "terminal_growth": round(float(terminal_growth), 6),
        "projection_years": int(projection_years),
        "tax_rate": round(float(tax_rate), 6),
        "means": [round(float(x), 8) for x in means.tolist()],
        "stds": [round(float(x), 8) for x in stds.tolist()],
        "base_wacc": round(float(base_wacc), 8) if base_wacc is not None else None,
        "shares_used": round(shares_out, 2),
        "total_debt": round(float(wacc_data.get("total_debt", 0.0) or 0.0), 2),
        "cash": round(float(metrics.get("cash_and_equivalents", 0.0) or 0.0), 2),
    }
    input_snapshot_hash = hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    if actual_n == 0:
        logger.warning("No valid Monte Carlo draws after rejection filtering.")
        empty_reasons = {
            "wacc_too_low": int(np.sum(mask_wacc_too_low)),
            "negative_cod": int(np.sum(mask_neg_cod)),
            "negative_rf": int(np.sum(mask_neg_rf)),
            "negative_erp": int(np.sum(mask_neg_erp)),
            "nan_inf_result": 0,
            "total_unique_rejected": int(rejected_filter_draws),
        }
        return {
            "simulated_prices": [],
            "simulated_evs": [],
            "simulated_raw_equity": [],
            "seed": mc_seed,
            "requested_iterations": int(iterations),
            "candidate_draws_sampled": int(oversample),
            "total_candidate_valid": 0,
            "rejected_draws": int(rejected_filter_draws),
            "unused_valid_oversample": 0,
            "total_simulations": int(rejected_filter_draws),
            "valid_simulations": 0,
            "invalid_simulations": int(rejected_filter_draws),
            "invalid_simulation_reasons": empty_reasons,
            "actual_iterations": 0,
            "stats": {},
            "hist_corr_gm": hist_corr_gm,
            "raw_corr_gm": raw_corr_gm,
            "corr_method": corr_method,
            "corr_sample_size": corr_sample_size,
            "is_corr_regularized": is_corr_regularized,
            "correlation_matrix": corr_matrix.tolist(),
            "distribution_specs": distribution_specs,
            "input_snapshot_hash": input_snapshot_hash,
            "sim_growth": [],
            "sim_margin": [],
            "sim_wacc": [],
        }

    if actual_n < iterations:
        logger.warning(
            "Only %d valid draws after rejection (target: %d).", actual_n, iterations
        )

    # ------------------------------------------------------------------
    # 5D – Run DCF across all valid iterations (vectorized)
    # ------------------------------------------------------------------
    stock_data_sim = dict(stock_data)
    stock_data_sim["_tax_rate"] = tax_rate

    simulated_prices, simulated_evs, simulated_raw_equity = run_dcf_batch(
        sim_growth=sim_growth,
        sim_margin=sim_margin,
        sim_wacc=sim_wacc,
        metrics=metrics,
        wacc_data=wacc_data,
        stock_data=stock_data_sim,
        terminal_growth=terminal_growth,
        projection_years=projection_years,
        tax_rate=tax_rate,
        use_mid_year=True,
        current_margin=current_margin,
    )

    # ------------------------------------------------------------------
    # 5E – Statistics
    # ------------------------------------------------------------------
    valid_prices_mask = np.isfinite(simulated_prices) & np.isfinite(simulated_raw_equity)
    final_prices = simulated_prices[valid_prices_mask]
    final_evs = simulated_evs[valid_prices_mask]
    final_raw_equity = simulated_raw_equity[valid_prices_mask]
    
    math_invalid_count = int(actual_n - len(final_prices))
    rejected_draws = int(rejected_filter_draws + math_invalid_count)

    zero_price_sims = int(np.sum(final_prices == 0.0))
    neg_equity_sims = int(np.sum(final_raw_equity < 0.0))
    valid_n = len(final_prices)

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
        "wacc_too_low": int(np.sum(mask_wacc_too_low)),
        "negative_cod": int(np.sum(mask_neg_cod)),
        "negative_rf": int(np.sum(mask_neg_rf)),
        "negative_erp": int(np.sum(mask_neg_erp)),
        "nan_inf_result": int(math_invalid_count),
        "total_unique_rejected": int(rejected_draws),
    }

    return {
        "simulated_prices": final_prices.tolist(),
        "simulated_evs": final_evs.tolist(),
        "simulated_raw_equity": final_raw_equity.tolist(),
        "seed": mc_seed,
        "requested_iterations": int(iterations),
        "candidate_draws_sampled": int(oversample),
        "total_candidate_valid": int(total_candidate_valid),
        "rejected_draws": int(rejected_draws),
        "unused_valid_oversample": int(unused_valid_oversample),
        "total_simulations": int(valid_n + rejected_draws),
        "valid_simulations": int(valid_n),
        "invalid_simulations": int(rejected_draws),
        "invalid_simulation_reasons": invalid_simulation_reasons,
        "actual_iterations": int(valid_n),
        "stats": stats,
        "hist_corr_gm": hist_corr_gm,
        "raw_corr_gm": raw_corr_gm,
        "corr_method": corr_method,
        "corr_sample_size": corr_sample_size,
        "is_corr_regularized": is_corr_regularized,
        "correlation_matrix": corr_matrix.tolist(),
        "distribution_specs": distribution_specs,
        "input_snapshot_hash": input_snapshot_hash,
        "sim_growth": sim_growth[valid_prices_mask].tolist(),
        "sim_margin": sim_margin[valid_prices_mask].tolist(),
        "sim_wacc": sim_wacc[valid_prices_mask].tolist(),
    }
