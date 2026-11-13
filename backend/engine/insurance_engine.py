"""
Insurance Sector Actuarial Excess Return & Float Valuation Engine
================================================================

Supports two distinct insurance business models without touching Bank Tier-1 logic:
  - ``INSURANCE_PNC_DDM``: Property & Casualty / Reinsurance carriers
      * Uses Ex-AOCI Common Book Value of Equity (stripping unrealized fixed-income
        mark-to-market AOCI swings so bond-yield fluctuations do not distort ROE).
      * Extracts Claims & Loss Adjustment Ratio and Investable Policyholder Float
        (Technical Reserves / Liabilities ex Financial Debt & NCI).
      * Includes a +250 bps Claims Loss / Catastrophe ROE & +50 bps Ke Stress Test.
  - ``INSURANCE_LIFE_DDM``: Life & Annuity Insurers / HoldCos
      * Normalizes GAAP Net Income / ROE for upfront policyholder acquisition costs
        (new-business strain) when reported ROE falls below sustainable life levels.
      * Excludes Minority Interest (Common Stock Equity base) cleanly for HoldCos.
      * Discloses EV / Value of New Business (VNB) & Reserve Triangle limitations.

Reuses ``compute_bank_cost_of_equity`` for CAPM Cost of Equity (Ke) and produces
response keys 100% compatible with the Equity / DDM frontend tabs and Excel generator.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import numpy as np

from .bank_engine import compute_bank_cost_of_equity


def _safe_latest_bs_value(balance_sheet: Any, columns: List[str], default: float = 0.0) -> float:
    """Return newest non-NaN value from the first matching Balance Sheet column."""
    if balance_sheet is None or not hasattr(balance_sheet, "columns"):
        return default
    for col in columns:
        if col in balance_sheet.columns:
            series = balance_sheet[col].dropna()
            if len(series) > 0:
                val = float(series.iloc[0])
                if np.isfinite(val):
                    return val
    return default


def _extract_insurance_profile(
    metrics: dict,
    stock_data: dict,
    model_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract normalized ex-AOCI Equity, Operating NI, Claims Loss Ratio, and Policyholder Float."""
    suit = stock_data.get("model_suitability") or {}
    resolved_model = model_type or suit.get("model_family") or "INSURANCE_PNC_DDM"
    is_life = resolved_model == "INSURANCE_LIFE_DDM" or suit.get("insurer_subtype") == "LIFE_ANNUITY"

    shares_out = float(stock_data.get("shares_outstanding", 1.0) or 1.0)
    if shares_out <= 0:
        shares_out = 1.0

    # 1. Common Equity (excluding Minority Interest) + Ex-AOCI adjustment
    bve_hist = [float(x) for x in (metrics.get("book_value") or []) if x is not None and np.isfinite(x)]
    valid_pos_bve = [x for x in bve_hist if x > 0]
    if valid_pos_bve:
        reported_bve = float(valid_pos_bve[-1])
    else:
        info_bv = (stock_data.get("info") or {}).get("bookValue")
        reported_bve = float(info_bv) * shares_out if (info_bv and info_bv > 0) else 0.0

    bs = stock_data.get("balance_sheet")
    aoci_val = _safe_latest_bs_value(bs, ["Gains Losses Not Affecting Retained Earnings"], 0.0)
    minority_interest = max(0.0, _safe_latest_bs_value(bs, ["Minority Interest"], 0.0))

    # Strip fixed-income AOCI distortions for P&C carriers when AOCI is significant vs Equity,
    # keeping reported_bve visible and guarding against tiny/negative adjusted equity.
    ex_aoci_candidate = reported_bve - aoci_val
    used_ex_aoci = bool(abs(aoci_val) > 0.01 * max(reported_bve, 1.0) and ex_aoci_candidate > 0.25 * max(reported_bve, 1.0))
    base_bve = float(ex_aoci_candidate) if used_ex_aoci else float(reported_bve)

    # 2. Operating Earnings (prefer Normalized Income / multi-year median when available)
    ni_hist = [float(x) for x in (metrics.get("net_income") or []) if x is not None and np.isfinite(x)]
    norm_ni_hist = [
        float(x)
        for x in ((metrics.get("insurance_metrics") or {}).get("normalized_income") or [])
        if x is not None and np.isfinite(x) and x > 0
    ]
    valid_ni = [x for x in ni_hist if x > 0]
    if norm_ni_hist and valid_ni:
        # Blend normalized income with latest GAAP NI to avoid one-off mark-to-market spikes
        base_net_income = 0.60 * float(norm_ni_hist[-1]) + 0.40 * float(valid_ni[-1])
    elif valid_ni:
        base_net_income = float(valid_ni[-1])
    else:
        last_rev = float(metrics.get("last_revenue", 1e9) or 1e9)
        base_net_income = last_rev * 0.08

    if base_bve <= 0:
        base_bve = max(base_net_income / 0.14, 1.0)

    # 3. Historical Ex-AOCI ROE & Life New-Business-Strain Normalization
    calc_roe = base_net_income / base_bve if base_bve > 0 else 0.14
    hist_avg_roe = float(metrics.get("avg_roe", 0.0) or 0.0)
    info_roe = (stock_data.get("info") or {}).get("returnOnEquity")
    candidates = [calc_roe]
    if hist_avg_roe > 0:
        candidates.append(hist_avg_roe)
    if info_roe is not None and np.isfinite(info_roe) and info_roe > 0:
        candidates.append(float(info_roe))

    raw_roe = float(np.median(candidates)) if candidates else 0.14
    # If Life insurer has artificially depressed GAAP ROE (<10%) from upfront acquisition cost strain,
    # normalize sustainable target ROE toward mature Life capital returns [12% floor] with explicit note.
    life_strain_normalized = False
    if is_life and raw_roe < 0.10:
        norm_roe = max(0.12, min(0.22, raw_roe + 0.06))
        life_strain_normalized = True
    else:
        norm_roe = raw_roe

    base_roe = max(0.05, min(0.35, raw_roe))
    default_target_roe = max(0.06, min(0.35, norm_roe))

    # 4. Claims Loss Ratio, Investments & Policyholder Float
    ins_meta = metrics.get("insurance_metrics") or {}
    claims_ratio = float(ins_meta.get("latest_claims_loss_ratio", 0.0) or 0.0)
    investments_and_advances = float(ins_meta.get("latest_investments_and_advances", 0.0) or 0.0)
    policyholder_float = float(ins_meta.get("latest_policyholder_float", 0.0) or 0.0)
    op_debt = max(0.0, _safe_latest_bs_value(bs, ["Total Debt"], 0.0))

    if policyholder_float <= 0:
        tot_liab = _safe_latest_bs_value(bs, ["Total Liabilities Net Minority Interest"], 0.0)
        policyholder_float = max(0.0, tot_liab - op_debt)
    if investments_and_advances <= 0:
        investments_and_advances = _safe_latest_bs_value(bs, ["Investments And Advances", "Available For Sale Securities"], 0.0)

    float_to_equity = float(policyholder_float / base_bve) if base_bve > 0 else 0.0
    solvency_debt_to_equity = float(op_debt / base_bve) if base_bve > 0 else 0.0

    # 5. Growth defaults
    raw_ni_g = float(metrics.get("avg_ni_growth", 0.08) or 0.08)
    raw_rev_g = float(metrics.get("avg_rev_growth", 0.08) or 0.08)
    default_start_growth = max(-0.02, min(0.25, 0.50 * raw_rev_g + 0.50 * raw_ni_g))

    return {
        "model_type": resolved_model,
        "insurer_subtype": "LIFE_ANNUITY" if is_life else "PNC_REINSURANCE",
        "is_life": is_life,
        "shares_out": shares_out,
        "reported_bve": float(reported_bve),
        "aoci_adjustment": float(aoci_val),
        "used_ex_aoci_bv": used_ex_aoci,
        "minority_interest_excluded": float(minority_interest),
        "base_bve": float(base_bve),
        "bvps": float(base_bve / shares_out) if shares_out > 0 else 0.0,
        "base_net_income": float(base_net_income),
        "base_roe": float(base_roe),
        "default_target_roe": float(default_target_roe),
        "life_strain_normalized": life_strain_normalized,
        "default_start_growth": float(default_start_growth),
        "claims_loss_ratio": float(claims_ratio),
        "investments_and_advances": float(investments_and_advances),
        "policyholder_float": float(policyholder_float),
        "float_to_equity": float(float_to_equity),
        "solvency_debt_to_equity": float(solvency_debt_to_equity),
    }


def run_insurance_valuation(
    start_growth: float,
    target_roe: float,
    cost_of_equity: float,
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float = 0.055,
    projection_years: int = 5,
    current_roe: Optional[float] = None,
    use_mid_year: bool = True,
    model_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Run Multi-Stage Insurance Equity Excess-Return / Solvency Capital DDM Valuation."""
    prof = _extract_insurance_profile(metrics, stock_data, model_type=model_type)
    shares_out = prof["shares_out"]
    base_bve = prof["base_bve"]
    bvps = prof["bvps"]
    base_net_income = prof["base_net_income"]
    base_roe = float(current_roe) if current_roe is not None else prof["base_roe"]
    resolved_model_type = prof["model_type"]
    is_life = prof["is_life"]

    target_roe = max(0.05, min(0.35, float(target_roe)))
    roe_schedule = np.linspace(base_roe, target_roe, projection_years)

    if projection_years > 1:
        step_fractions = np.linspace(0.0, 1.0, projection_years)
    else:
        step_fractions = np.array([0.0])
    growth_excess = max(0.0, start_growth - terminal_growth)
    fade_blend = min(1.0, max(0.0, (growth_excess - 0.03) / 0.06))
    growth_fade_exponent = 1.0 + 0.35 * fade_blend
    growth_schedule = start_growth - (start_growth - terminal_growth) * (step_fractions ** growth_fade_exponent)

    proj_net_income: List[float] = []
    proj_retention_rate: List[float] = []
    proj_reinvestment_equity: List[float] = []
    proj_fcfe: List[float] = []
    proj_bve: List[float] = []

    cur_ni = base_net_income
    cur_bve = base_bve

    for yr in range(projection_years):
        g = float(growth_schedule[yr])
        roe = float(roe_schedule[yr])
        cur_ni = cur_ni * (1.0 + g)

        g_next = float(growth_schedule[yr + 1]) if (yr + 1) < projection_years else terminal_growth
        marg_roe = max(roe, target_roe, g * 0.95)
        retention_b = min(0.85, max(0.05, g_next / marg_roe)) if marg_roe > 0 else 0.50

        reinvested_equity = cur_ni * retention_b
        fcfe = cur_ni * (1.0 - retention_b)
        cur_bve = cur_bve + reinvested_equity

        proj_net_income.append(float(cur_ni))
        proj_retention_rate.append(float(retention_b))
        proj_reinvestment_equity.append(float(reinvested_equity))
        proj_fcfe.append(float(fcfe))
        proj_bve.append(float(cur_bve))

    discount_periods = [i + 0.5 if use_mid_year else float(i + 1) for i in range(projection_years)]
    discount_factors = [(1.0 + cost_of_equity) ** t for t in discount_periods]
    pv_fcfe_list = [f / df for f, df in zip(proj_fcfe, discount_factors)]
    pv_fcfe = sum(pv_fcfe_list)

    terminal_value_valid = True
    terminal_value_note = ""
    terminal_growth_capped = False
    effective_terminal_growth = terminal_growth

    if cost_of_equity <= terminal_growth:
        terminal_value = 0.0
        pv_terminal_value = 0.0
        terminal_value_valid = False
        terminal_value_note = "Cost of Equity (Ke) must exceed terminal growth rate for Gordon Growth model."
    else:
        spread = cost_of_equity - terminal_growth
        if spread < 0.020:
            effective_terminal_growth = cost_of_equity - 0.020
            terminal_growth_capped = True
            terminal_value_note = (
                f"Terminal growth capped at {effective_terminal_growth*100:.1f}% to preserve minimum 2.0% Ke spread."
            )
            eff_spread = 0.020
        else:
            eff_spread = spread
        term_roe = float(roe_schedule[-1])
        term_retention = min(0.95, max(0.05, effective_terminal_growth / term_roe if term_roe > 0 else 0.50))
        term_ni = proj_net_income[-1] * (1.0 + effective_terminal_growth)
        term_fcfe = term_ni * (1.0 - term_retention)
        terminal_value = term_fcfe / eff_spread
        pv_terminal_value = terminal_value / discount_factors[-1]

    equity_value = pv_fcfe + pv_terminal_value
    implied_price = max(0.0, equity_value / shares_out) if shares_out > 0 else 0.0

    # Justified P/Ex-AOCI Book & Catastrophe / New-Business-Strain Stress Test
    term_roe_val = float(roe_schedule[-1])
    if cost_of_equity > effective_terminal_growth:
        justified_pb = max(0.2, (term_roe_val - effective_terminal_growth) / (cost_of_equity - effective_terminal_growth))
    else:
        justified_pb = 1.0
    justified_price = max(0.0, bvps * justified_pb)

    stressed_roe = max(0.04, term_roe_val - 0.025)
    stressed_ke = float(cost_of_equity) + 0.0050
    if stressed_ke > effective_terminal_growth:
        stressed_pb = max(0.2, (stressed_roe - effective_terminal_growth) / (stressed_ke - effective_terminal_growth))
    else:
        stressed_pb = 0.8
    catastrophe_stress_price = max(0.0, bvps * stressed_pb)

    tv_share_of_ev = float(pv_terminal_value / equity_value) if equity_value > 0 else 0.0
    tv_share_flag = bool(tv_share_of_ev > 0.78)
    tv_share_note = (
        f"Terminal Equity Value accounts for {tv_share_of_ev*100:.1f}% of Total Implied Equity Value."
        if tv_share_flag
        else None
    )

    if is_life:
        funding_note = (
            f"Life & Annuity Insurer (Ex-NCI BV={base_bve:,.0f}, Float/Equity={prof['float_to_equity']:.2f}x). "
            f"{'Normalized ROE applied for Life new-business strain. ' if prof['life_strain_normalized'] else ''}"
            f"Actuarial EV/VNB remains uncaptured from statement-only feeds; stress ROE ({stressed_roe*100:.1f}%) / Ke ({stressed_ke*100:.2f}%) implies {catastrophe_stress_price:,.2f}."
        )
    else:
        funding_note = (
            f"P&C Insurer (Ex-AOCI BV={base_bve:,.0f}, Float/Equity={prof['float_to_equity']:.2f}x, Claims Loss Ratio={prof['claims_loss_ratio']*100:.1f}%). "
            f"Catastrophe +250 bps claims stress ROE ({stressed_roe*100:.1f}%) / Ke ({stressed_ke*100:.2f}%) implies {catastrophe_stress_price:,.2f}."
        )

    return {
        "implied_price": float(implied_price),
        "enterprise_value": float(equity_value),
        "equity_value": float(equity_value),
        "projected_revenue": [float(n) for n in proj_net_income],
        "projected_ufcf": [float(f) for f in proj_fcfe],
        "projected_nopat": [float(n) for n in proj_net_income],
        "projected_dna": [float(r) for r in proj_reinvestment_equity],
        "projected_capex": [float(r) for r in proj_reinvestment_equity],
        "projected_dnwc": [0.0] * projection_years,
        "growth_schedule": growth_schedule.tolist(),
        "margin_schedule": roe_schedule.tolist(),
        "pv_ufcf": float(pv_fcfe),
        "pv_ufcf_list": [float(p) for p in pv_fcfe_list],
        "discount_periods": discount_periods,
        "discount_factors": [float(1.0 / df) for df in discount_factors],
        "terminal_value": float(terminal_value),
        "pv_terminal_value": float(pv_terminal_value),
        "terminal_value_valid": terminal_value_valid,
        "terminal_value_note": terminal_value_note,
        "terminal_growth_capped": terminal_growth_capped,
        "effective_terminal_growth": float(effective_terminal_growth),
        "tv_share_of_ev": tv_share_of_ev,
        "tv_share_flag": tv_share_flag,
        "tv_share_note": tv_share_note,
        "tax_rate": float(market_profile.get("tax_rate", 0.21)),
        "terminal_growth": float(terminal_growth),
        "use_mid_year": use_mid_year,
        # Dedicated Insurance Equity DDM fields
        "is_financial": True,
        "is_insurance": True,
        "is_equity_model": True,
        "model_type": resolved_model_type,
        "insurer_subtype": prof["insurer_subtype"],
        "base_net_income": float(base_net_income),
        "reported_bve": prof["reported_bve"],
        "aoci_adjustment": prof["aoci_adjustment"],
        "used_ex_aoci_bv": prof["used_ex_aoci_bv"],
        "minority_interest_excluded": prof["minority_interest_excluded"],
        "base_bve": float(base_bve),
        "bvps": float(bvps),
        "base_roe": float(base_roe),
        "target_roe": float(target_roe),
        "growth_fade_exponent": float(growth_fade_exponent),
        "cost_of_equity": float(cost_of_equity),
        "justified_pb": float(justified_pb),
        "justified_price": float(justified_price),
        "claims_loss_ratio": prof["claims_loss_ratio"],
        "investments_and_advances": prof["investments_and_advances"],
        "policyholder_float": prof["policyholder_float"],
        "float_to_equity": prof["float_to_equity"],
        "solvency_debt_to_equity": prof["solvency_debt_to_equity"],
        "wholesale_leverage_ratio": prof["solvency_debt_to_equity"],
        "credit_cost_stress_price": float(catastrophe_stress_price),
        "catastrophe_stress_price": float(catastrophe_stress_price),
        "funding_model_note": funding_note,
        "projected_net_income": [float(n) for n in proj_net_income],
        "projected_fcfe": [float(f) for f in proj_fcfe],
        "projected_bve": [float(b) for b in proj_bve],
        "retention_schedule": [float(b) for b in proj_retention_rate],
        "payout_schedule": [float(1.0 - b) for b in proj_retention_rate],
        "roe_schedule": [float(r) for r in roe_schedule],
    }


def run_insurance_monte_carlo(
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float,
    projection_years: int = 5,
    iterations: int = 1000,
    base_growth: Optional[float] = None,
    base_roe: Optional[float] = None,
    base_ke: Optional[float] = None,
    model_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Run vectorized 10k-compatible Monte Carlo over Insurance Growth, Ex-AOCI ROE, and Ke."""
    prof = _extract_insurance_profile(metrics, stock_data, model_type=model_type)
    g_mean = float(base_growth) if base_growth is not None else prof["default_start_growth"]
    g_std = max(0.015, float(metrics.get("std_ni_growth", 0.04) or 0.04))

    roe_mean = float(base_roe) if base_roe is not None else prof["default_target_roe"]
    roe_std = max(0.015, float(metrics.get("std_roe", 0.025) or 0.025))

    ke_data = compute_bank_cost_of_equity(stock_data, market_profile)
    ke_mean = float(base_ke) if base_ke is not None else float(ke_data["cost_of_equity"])
    ke_std = 0.015

    rng = np.random.default_rng(42)
    sim_growth = np.clip(rng.normal(g_mean, g_std, iterations), -0.05, 0.30)
    sim_roe = np.clip(rng.normal(roe_mean, roe_std, iterations), 0.05, 0.35)
    sim_ke = np.clip(rng.normal(ke_mean, ke_std, iterations), terminal_growth + 0.005, 0.25)

    n = len(sim_growth)
    shares_out = prof["shares_out"]
    base_net_income = prof["base_net_income"]
    b_roe = prof["base_roe"]

    steps = np.arange(projection_years, dtype=float) / float(projection_years - 1) if projection_years > 1 else np.zeros(1)
    fade_blend = np.clip((sim_growth - terminal_growth - 0.03) / 0.06, 0.0, 1.0)
    fade_exponents = 1.0 + 0.35 * fade_blend
    growth_schedule = sim_growth[:, None] - (sim_growth[:, None] - terminal_growth) * (steps[None, :] ** fade_exponents[:, None])
    roe_schedule = np.linspace(b_roe, sim_roe, projection_years, axis=1)

    discount_periods = np.arange(projection_years, dtype=float) + 0.5
    discount_factors = (1.0 + sim_ke[:, None]) ** discount_periods[None, :]

    cur_ni = np.full(n, base_net_income, dtype=float)
    pv_fcfe = np.zeros(n, dtype=float)
    for yr in range(projection_years):
        g = growth_schedule[:, yr]
        g_next = growth_schedule[:, yr + 1] if (yr + 1) < projection_years else np.full(n, terminal_growth, dtype=float)
        roe = roe_schedule[:, yr]
        cur_ni = cur_ni * (1.0 + g)
        marg_roe = np.maximum(np.maximum(roe, sim_roe), g * 0.95)
        retention_b = np.where(marg_roe > 0, np.clip(g_next / np.where(marg_roe > 0, marg_roe, 1.0), 0.05, 0.85), 0.50)
        pv_fcfe += (cur_ni * (1.0 - retention_b)) / discount_factors[:, yr]

    term_roe = roe_schedule[:, -1]
    valid_tv = sim_ke > terminal_growth
    spread = sim_ke - terminal_growth
    narrow = valid_tv & (spread < 0.020)
    eff_g = np.where(narrow, sim_ke - 0.020, terminal_growth)
    eff_spread = np.where(narrow, 0.020, np.where(valid_tv, spread, 1.0))
    term_retention = np.where(term_roe > 0, np.clip(eff_g / np.where(term_roe > 0, term_roe, 1.0), 0.05, 0.95), 0.50)
    term_ni = cur_ni * (1.0 + eff_g)
    pv_terminal = np.where(valid_tv, (term_ni * (1.0 - term_retention)) / eff_spread, 0.0) / discount_factors[:, -1]

    all_prices = np.maximum(0.0, (pv_fcfe + pv_terminal) / shares_out) if shares_out > 0 else np.zeros(n)
    valid_mask = (all_prices > 0) & np.isfinite(all_prices)
    sim_arr = all_prices[valid_mask]
    valid_count = int(len(sim_arr))
    if valid_count == 0:
        sim_arr = np.array([0.0])

    current_price = float(stock_data.get("current_price", 1.0) or 1.0)
    stats = {
        "mean": float(np.mean(sim_arr)),
        "median": float(np.median(sim_arr)),
        "std": float(np.std(sim_arr)),
        "std_dev": float(np.std(sim_arr)),
        "p5": float(np.percentile(sim_arr, 5)),
        "p10": float(np.percentile(sim_arr, 10)),
        "p25": float(np.percentile(sim_arr, 25)),
        "p75": float(np.percentile(sim_arr, 75)),
        "p90": float(np.percentile(sim_arr, 90)),
        "p95": float(np.percentile(sim_arr, 95)),
        "prob_undervalued": float(np.mean(sim_arr > current_price)) if len(sim_arr) > 0 else 0.0,
        "zero_price_simulations": int(iterations - valid_count),
        "positive_price_simulations": valid_count,
    }
    return {
        "stats": stats,
        "simulated_prices": sim_arr.tolist(),
        "sim_growth": sim_growth.tolist(),
        "sim_margin": sim_roe.tolist(),
        "sim_wacc": sim_ke.tolist(),
        "seed": 42,
        "requested_iterations": int(iterations),
        "candidate_draws_sampled": int(iterations),
        "total_candidate_valid": valid_count,
        "rejected_draws": int(iterations - valid_count),
        "unused_valid_oversample": 0,
        "actual_iterations": int(valid_count),
        "total_simulations": int(iterations),
        "valid_simulations": valid_count,
        "invalid_simulations": int(iterations - valid_count),
        "invalid_simulation_reasons": {
            "ke_too_low": int(np.sum(sim_ke <= terminal_growth)),
            "zero_or_invalid_equity": int(iterations - valid_count),
        },
        "corr_sample_size": 0,
        "corr_method": "insurance_ddm_independent_draws",
        "is_corr_regularized": False,
        "hist_corr_gm": 0.0,
    }


def generate_insurance_sensitivity_grid(
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float,
    projection_years: int = 5,
    base_growth: Optional[float] = None,
    base_roe: Optional[float] = None,
    base_ke: Optional[float] = None,
    model_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate 5x5 sensitivity grid: Net Income Growth vs Cost of Equity (Ke)."""
    prof = _extract_insurance_profile(metrics, stock_data, model_type=model_type)
    ke_data = compute_bank_cost_of_equity(stock_data, market_profile)
    mid_ke = float(base_ke) if base_ke is not None else float(ke_data["cost_of_equity"])
    mid_growth = float(base_growth) if base_growth is not None else prof["default_start_growth"]
    t_roe = float(base_roe) if base_roe is not None else prof["default_target_roe"]

    growth_steps = [mid_growth - 0.02, mid_growth - 0.01, mid_growth, mid_growth + 0.01, mid_growth + 0.02]
    ke_steps = [mid_ke - 0.01, mid_ke - 0.005, mid_ke, mid_ke + 0.005, mid_ke + 0.01]

    grid = [
        [
            0.0 if k <= terminal_growth else run_insurance_valuation(
                start_growth=g,
                target_roe=t_roe,
                cost_of_equity=k,
                metrics=metrics,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                use_mid_year=True,
                model_type=model_type,
            ).get("implied_price", 0.0)
            for g in growth_steps
        ]
        for k in ke_steps
    ]
    return {
        "wacc_range": ke_steps,
        "growth_range": growth_steps,
        "grid": grid,
        "price_grid": grid,
        "base_growth": mid_growth,
        "base_wacc": mid_ke,
    }


def generate_insurance_roe_sensitivity_grid(
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float,
    projection_years: int = 5,
    base_growth: Optional[float] = None,
    base_roe: Optional[float] = None,
    base_ke: Optional[float] = None,
    model_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate 5x5 sensitivity grid: Target Ex-AOCI ROE vs Cost of Equity (Ke)."""
    prof = _extract_insurance_profile(metrics, stock_data, model_type=model_type)
    ke_data = compute_bank_cost_of_equity(stock_data, market_profile)
    mid_ke = float(base_ke) if base_ke is not None else float(ke_data["cost_of_equity"])
    mid_growth = float(base_growth) if base_growth is not None else prof["default_start_growth"]
    t_roe = float(base_roe) if base_roe is not None else prof["default_target_roe"]

    roe_steps = [t_roe - 0.04, t_roe - 0.02, t_roe, t_roe + 0.02, t_roe + 0.04]
    ke_steps = [mid_ke - 0.01, mid_ke - 0.005, mid_ke, mid_ke + 0.005, mid_ke + 0.01]

    grid = [
        [
            0.0 if k <= terminal_growth else run_insurance_valuation(
                start_growth=mid_growth,
                target_roe=r,
                cost_of_equity=k,
                metrics=metrics,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                use_mid_year=True,
                model_type=model_type,
            ).get("implied_price", 0.0)
            for r in roe_steps
        ]
        for k in ke_steps
    ]
    return {
        "wacc_range": ke_steps,
        "margin_range": roe_steps,
        "roe_range": roe_steps,
        "grid": grid,
        "price_grid": grid,
        "base_margin": t_roe,
        "base_wacc": mid_ke,
    }
