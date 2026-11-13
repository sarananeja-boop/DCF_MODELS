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
    cash_equiv: float = float(metrics.get("cash_and_equivalents", 0.0))
    hist_dna = metrics.get("dna", [])
    last_dna = float(hist_dna[-1]) if len(hist_dna) > 0 else 0.0
    hist_ebitda = metrics.get("ebitda", [])
    last_ebitda = max(
        last_ebit + last_dna,
        float(hist_ebitda[-1]) if len(hist_ebitda) > 0 else 0.0,
    )
    last_rev = float(metrics.get("last_revenue", 0.0))
    avg_ebit = float(metrics.get("avg_ebit_margin", 0.0)) * last_rev
    avg_ebitda = float(metrics.get("avg_ebitda_margin", 0.0)) * last_rev
    latest_fcf = float(metrics.get("latest_fcf_margin", 0.0)) * last_rev

    if interest_expense > 0:
        # For cash-generative or high-D&A operating firms where single-year GAAP EBIT is depressed
        # by non-cash amortization, restructuring, or CapEx cycles, evaluate interest coverage using
        # normalized EBIT / EBITDA / FCF backing so solvent going-concern firms are not rated 'D'.
        if cash_equiv >= total_debt and max(last_ebitda, latest_fcf) > last_ebit:
            effective_coverage_earnings = max(last_ebit, last_ebitda, latest_fcf * 0.75)
        elif last_ebitda > 0:
            effective_coverage_earnings = max(
                last_ebit,
                avg_ebit,
                0.75 * last_ebitda,
                0.75 * avg_ebitda,
                latest_fcf,
            )
        else:
            effective_coverage_earnings = last_ebit
        interest_coverage = float(effective_coverage_earnings / interest_expense)
    else:
        interest_coverage = 999.0

    # Keep metrics["interest_coverage"] synchronized with WACC coverage
    metrics["interest_coverage"] = float(interest_coverage)

    synthetic_rating, default_spread = get_synthetic_rating_and_spread(
        interest_coverage, market_cap, currency=currency
    )

    # Point 2: Rf already embeds sovereign default spread (G-Sec/Treasury). Kd = Rf + Company Default Spread.
    synthetic_kd = risk_free_rate + default_spread

    raw_debt_denom = max(total_debt, float(metrics.get("raw_total_debt", total_debt) or total_debt))
    if total_debt > 0 and interest_expense > 0 and raw_debt_denom > 0:
        hist_kd = abs(interest_expense / raw_debt_denom)
        if risk_free_rate <= hist_kd <= risk_free_rate + 0.075 and last_ebitda > 0:
            if interest_coverage < 3.0:
                cost_of_debt = 0.50 * hist_kd + 0.50 * synthetic_kd
            else:
                cost_of_debt = min(hist_kd, synthetic_kd) if hist_kd >= 0.04 else synthetic_kd
        elif interest_coverage < 3.0:
            cost_of_debt = max(min(hist_kd, risk_free_rate + 0.08), synthetic_kd)
        else:
            cost_of_debt = min(hist_kd, synthetic_kd) if hist_kd >= 0.04 else synthetic_kd
    else:
        cost_of_debt = synthetic_kd if total_debt > 0 else 0.04

    # Point 6: Interest tax shield evaluation (using sustainable operating earnings backing)
    marginal_tax_rate = tax_rate
    conventional_kd_after_tax = cost_of_debt * (1.0 - marginal_tax_rate)
    tax_shield_capped = False
    usable_tax_shield = 0.0
    if total_debt > 0:
        taxable_capacity = max(0.0, last_ebit, avg_ebit, 0.70 * last_ebitda)
        usable_interest = max(0.0, min(interest_expense, taxable_capacity))
        if interest_expense > 0:
            shield_ratio = usable_interest / interest_expense
        else:
            shield_ratio = 1.0
        usable_tax_shield = marginal_tax_rate * usable_interest
        effective_kd_after_tax = cost_of_debt * (1.0 - marginal_tax_rate * shield_ratio)
        # Senior debt after tax cannot exceed junior Cost of Equity in a going-concern WACC
        max_kd_after_tax = max(conventional_kd_after_tax, cost_of_equity - 0.005)
        effective_kd_after_tax = float(np.clip(effective_kd_after_tax, 0.02, min(cost_of_debt, max_kd_after_tax)))
        if interest_expense > 0 and usable_interest < interest_expense * 0.99:
            tax_shield_capped = True
    else:
        effective_kd_after_tax = conventional_kd_after_tax

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
        "conventional_cost_of_debt": float(conventional_kd_after_tax),
        "pretax_cost_of_debt": float(cost_of_debt),
        "tax_rate_used": float(marginal_tax_rate),
        "tax_shield_capped": tax_shield_capped,
        "usable_tax_shield": float(usable_tax_shield),
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
        "raw_total_debt": float(metrics.get("raw_total_debt", total_debt)),
        "lease_obligations": float(metrics.get("lease_obligations", 0.0)),
        "captive_debt_offset": float(metrics.get("captive_debt_offset", 0.0)),
        "minority_interest_claim": float(metrics.get("minority_interest_claim", 0.0)),
        "aro_provisions_claim": float(metrics.get("aro_provisions_claim", 0.0)),
        "greenfield_debt_offset": float(metrics.get("greenfield_debt_offset", 0.0)),
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
    ignore_terminal_growth_cap: bool = False,
    fixed_terminal_reinv_rate: Optional[float] = None,
    shares_override: Optional[float] = None,
    capex_floor_abs: Optional[float] = None,
    use_raw_capex: bool = False,
    disable_tv_blend: bool = False,
    debt_override: Optional[float] = None,
) -> dict:
    """Run a single multi-stage DCF valuation with continuous growth fade and Mid-Year convention.

    Implements Damodaran DCF modeling (matching HUL FINAL MODEL.xlsx):

    1. Revenue grows from ``start_growth`` in Year 1 to ``terminal_growth``
       in Year *N* via a continuous fade exponent (1.0 linear up to +5% spread,
       smoothly ramping to 1.35 concave fade above +15% spread).
    2. UFCF = NOPAT + D&A − CapEx − Δ NWC (all as % of projected revenue).
    3. Discount projected UFCFs using Mid-Year Convention (t = 0.5, 1.5, 2.5, 3.5, 4.5).
    4. Terminal Value via Gordon Growth Model, discounted via the terminal period factor.
    5. EV → Equity bridge (add cash, subtract debt, minority interest & preferred claims, floor at 0).
    """
    avg_dna_pct: float = metrics["avg_dna_pct"]
    avg_capex_pct: float = metrics["avg_capex_pct"]
    # Fallback for backward compatibility if normalized_nwc_to_revenue isn't present
    normalized_nwc_to_revenue: float = metrics.get("normalized_nwc_to_revenue", metrics.get("avg_dnwc_pct", 0.0))
    last_revenue: float = metrics["last_revenue"]
    total_debt: float = float(debt_override) if debt_override is not None else wacc_data["total_debt"]
    cash_equiv: float = metrics["cash_and_equivalents"]
    minority_interest_claim: float = float(metrics.get("minority_interest_claim", 0.0) or 0.0)
    preferred_stock_claim: float = float(metrics.get("preferred_stock_claim", 0.0) or 0.0)
    shares_basic: float = float(
        stock_data.get("basic_valuation_shares")
        or stock_data.get("shares_outstanding")
        or 0.0
    )
    shares_out: float = float(
        shares_override
        if (shares_override is not None and shares_override > 0)
        else (stock_data.get("diluted_valuation_shares") or stock_data["shares_outstanding"])
    )

    is_extractive = stock_data.get("is_extractive", False)
    is_cyclical = stock_data.get("is_cyclical", False)
    if "is_extractive" not in stock_data or "is_cyclical" not in stock_data:
        from engine.data_layer import classify_sector_dynamics
        is_extractive, is_cyclical = classify_sector_dynamics(
            stock_data.get("sector"),
            stock_data.get("industry"),
            stock_data.get("ticker"),
            stock_data.get("name"),
        )

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

    # Smooth continuous growth fade from start_growth (Year 1) to terminal_growth (Year N)
    if projection_years > 1:
        steps = np.arange(projection_years, dtype=float) / float(projection_years - 1)
    else:
        steps = np.zeros(1, dtype=float)
    if not is_extractive and not is_cyclical:
        fade_blend = min(1.0, max(0.0, (start_growth - terminal_growth - 0.05) / 0.10))
        growth_fade_exponent = 1.0 + 0.35 * fade_blend
    else:
        growth_fade_exponent = 1.0
    growth_schedule = start_growth - (start_growth - terminal_growth) * (steps ** growth_fade_exponent)
    
    valuation_adjustments: List[Dict[str, Any]] = []
    if metrics.get("valuation_adjustments"):
        valuation_adjustments.extend(metrics["valuation_adjustments"])

    # Margin schedule (step from Year-0 current_margin toward Year-N target ebit_margin)
    if current_margin is not None:
        margin_schedule = np.linspace(current_margin, ebit_margin, projection_years + 1)[1:]
    else:
        margin_schedule = np.array([ebit_margin] * projection_years)

    # Bound D&A when non-PPE amortization (e.g. streaming content amortization in NFLX or acquisition
    # intangible amortization in LBOs) makes D&A far exceed physical CapEx.
    effective_dna_pct = (
        min(avg_dna_pct, max(avg_capex_pct * 1.05, 0.025))
        if avg_dna_pct > avg_capex_pct * 1.15
        else avg_dna_pct
    )

    # In corporate finance / Damodaran framework, CapEx% converges towards steady-state
    # maintenance CapEx: D&A * (1 + terminal_growth).
    # Preserve raw avg_capex_pct; when greenfield/extractive/cyclical tapering adjusts explicit CapEx,
    # document exact delta & expose unadjusted_capex scenario.
    base_steady_state = effective_dna_pct * (1.0 + terminal_growth)
    cwip_to_rev = float(metrics.get("cwip_to_rev", 0.0) or 0.0)
    if use_raw_capex:
        steady_state_capex_pct = max(base_steady_state, avg_capex_pct)
        eff_start_capex = avg_capex_pct
    elif is_extractive:
        if cwip_to_rev > 0.50:
            max_ext_capex = effective_dna_pct * 1.45
        else:
            max_ext_capex = max(effective_dna_pct * 2.5, max(0.05, ebit_margin) * (1.0 - tax_rate) * 0.72)
        steady_state_capex_pct = max(base_steady_state, min(avg_capex_pct, max_ext_capex))
        eff_start_capex = min(avg_capex_pct, max_ext_capex * 1.10)
    elif is_cyclical:
        steady_state_capex_pct = max(base_steady_state, min(avg_capex_pct * 0.90, effective_dna_pct * 1.35))
        eff_start_capex = avg_capex_pct
    else:
        steady_state_capex_pct = base_steady_state
        if avg_capex_pct > effective_dna_pct * 2.20 and avg_capex_pct > 0.15:
            eff_start_capex = effective_dna_pct * (1.0 + max(0.10, terminal_growth))
        elif avg_capex_pct > effective_dna_pct * 1.40 and avg_capex_pct > 0.12:
            eff_start_capex = min(
                avg_capex_pct,
                effective_dna_pct * (1.0 + max(0.15, start_growth * 1.8)),
            )
        else:
            eff_start_capex = avg_capex_pct

    capex_taper_applied = (
        abs(eff_start_capex - avg_capex_pct) > 1e-4
        or abs(steady_state_capex_pct - avg_capex_pct) > 1e-4
    )
    if (not use_raw_capex) and abs(eff_start_capex - avg_capex_pct) > 0.015:
        valuation_adjustments.append({
            "name": "Explicit CapEx / Greenfield Tapering",
            "category": "capex_tapering",
            "status": "APPLIED",
            "raw_value": float(avg_capex_pct),
            "applied_value": float(eff_start_capex),
            "steady_state_capex_pct": float(steady_state_capex_pct),
            "rationale": (
                f"Historical avg CapEx/Rev ({avg_capex_pct*100:.2f}%) exceeded D&A/Rev ({effective_dna_pct*100:.2f}%) "
                f"(CWIP/Rev={cwip_to_rev*100:.1f}%); started explicit maintenance CapEx at {eff_start_capex*100:.2f}% "
                f"tapering to {steady_state_capex_pct*100:.2f}%."
            ),
            "alternative_scenario": "unadjusted_capex",
        })

    capex_schedule = np.linspace(eff_start_capex, steady_state_capex_pct, projection_years)

    for yr in range(projection_years):
        g = growth_schedule[yr]
        next_rev = last_rev * (1 + g)
        margin = margin_schedule[yr]

        nopat = next_rev * margin * (1 - tax_rate)
        dna_add = next_rev * effective_dna_pct
        capex_sub = next_rev * capex_schedule[yr]
        if capex_floor_abs is not None and capex_floor_abs > 0:
            capex_sub = max(capex_sub, float(capex_floor_abs))
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
    
    # Calculate Sustainable Terminal ROIC & Reinvestment Rate (excluding historical M&A Goodwill
    # for organic marginal reinvestment, floored at 15% of revenue)
    bs = metrics.get("statements", {}).get("balance_sheet", {}) if isinstance(metrics.get("statements"), dict) else {}
    equity_series = bs.get("Total Stockholders' Equity", [0]) if isinstance(bs, dict) else [0]
    equity_bv = equity_series[-1] if equity_series else 0.0
    gw_series = bs.get("Intangible Assets & Goodwill", [0]) if isinstance(bs, dict) else [0]
    gw_val = float(gw_series[-1]) if gw_series else 0.0
    invested_capital = max(1.0, equity_bv + total_debt - cash_equiv)
    tangible_ic = max(last_revenue * 0.15, invested_capital - 1.00 * max(0.0, gw_val))
    
    hist_ebit = metrics.get("ebit", [])
    last_ebit = hist_ebit[-1] if hist_ebit else (last_rev * ebit_margin)
    hist_nopat = last_ebit * (1 - tax_rate)
    hist_roic = (hist_nopat / tangible_ic) if (tangible_ic > 0 and hist_nopat > 0) else 0.0
    yr5_tangible_ic = tangible_ic * max(1.0, (proj_rev[-1] / last_revenue) if last_revenue > 0 and len(proj_rev) > 0 else 1.0)
    proj_roic = (
        (proj_nopat[-1] / yr5_tangible_ic)
        if (yr5_tangible_ic > 0 and len(proj_nopat) > 0 and proj_nopat[-1] > 0)
        else discount_rate
    )
    effective_roic = max(hist_roic, proj_roic) if hist_roic <= 0.02 else (0.50 * hist_roic + 0.50 * proj_roic if current_margin is not None else hist_roic)

    # Economic competition bounds sustainable long-term ROIC (accommodating capital-light compounders)
    is_high_roic = (
        not is_extractive
        and not is_cyclical
        and effective_roic >= 0.22
        and (float(metrics.get("avg_gross_margin", 0.0)) >= 0.45 or effective_roic >= 0.28)
    )
    max_roic_cap = 0.45 if is_high_roic else 0.30
    min_reinv_floor = 0.06 if is_high_roic else 0.10
    min_roic_floor = (discount_rate + 0.045) if (not is_extractive and not is_cyclical and avg_capex_pct > effective_dna_pct * 2.20) else discount_rate
    sustainable_roic = max(min_roic_floor, min(effective_roic, max_roic_cap))

    is_india = (stock_data.get("market") == "IN")
    if ignore_terminal_growth_cap:
        max_g_allowed = max(0.01, discount_rate - 0.015)
    elif is_extractive:
        max_g_allowed = 0.025
    else:
        max_g_allowed = 0.050 if is_india else 0.025
    clamped_terminal_growth = min(terminal_growth, max_g_allowed)

    # Enforce minimum spread: WACC - g >= 0.025 (2.5% minimum spread, or 1.5% in sensitivity sweep)
    min_spread = 0.015 if ignore_terminal_growth_cap else 0.025
    if discount_rate - clamped_terminal_growth < min_spread:
        effective_terminal_growth = max(0.01, discount_rate - min_spread)
        terminal_growth_capped = True
        terminal_value_note = (
            f"Terminal growth capped at {effective_terminal_growth*100:.1f}% to preserve minimum "
            f"{min_spread*100:.1f}% spread below WACC ({discount_rate*100:.1f}%)."
        )
    else:
        effective_terminal_growth = clamped_terminal_growth
        if effective_terminal_growth < terminal_growth - 1e-6:
            terminal_growth_capped = True
            terminal_value_note = (
                f"Requested terminal growth ({terminal_growth*100:.2f}%) capped at "
                f"{effective_terminal_growth*100:.2f}% ({'Extractive' if is_extractive else ('IN' if is_india else 'US')} bound)."
            )

    if terminal_growth_capped:
        valuation_adjustments.append({
            "name": "Terminal Growth Rate Cap",
            "category": "terminal_growth_cap",
            "status": "APPLIED",
            "raw_value": float(terminal_growth),
            "applied_value": float(effective_terminal_growth),
            "rationale": terminal_value_note or "Terminal growth capped below WACC / regional nominal ceiling.",
        })

    roic_reinv = effective_terminal_growth / sustainable_roic
    yr5_nopat_margin = max(0.01, margin_schedule[-1] * (1.0 - tax_rate)) if margin_schedule[-1] > 0 else 0.01
    model_yr5_reinv = max(
        0.0,
        (
            (steady_state_capex_pct - effective_dna_pct)
            + max(0.0, normalized_nwc_to_revenue * effective_terminal_growth)
        )
        / yr5_nopat_margin,
    )
    if fixed_terminal_reinv_rate is not None:
        terminal_reinv_rate = float(fixed_terminal_reinv_rate)
    elif is_high_roic and margin_schedule[-1] > 0:
        blended_reinv = min(roic_reinv, 0.45 * roic_reinv + 0.55 * model_yr5_reinv)
        terminal_reinv_rate = min(0.80, max(min_reinv_floor, blended_reinv))
    else:
        terminal_reinv_rate = min(0.80, max(min_reinv_floor, roic_reinv))

    # For extractive/capital-intensive firms, terminal reinvestment rate must also fund sustaining net CapEx
    if fixed_terminal_reinv_rate is None and is_extractive and margin_schedule[-1] > 0:
        yr5_nopat_margin = max(0.01, margin_schedule[-1] * (1.0 - tax_rate))
        net_capex_reinv = max(0.0, (steady_state_capex_pct - effective_dna_pct) / yr5_nopat_margin)
        terminal_reinv_rate = min(0.80, max(terminal_reinv_rate, net_capex_reinv))
    elif fixed_terminal_reinv_rate is None and is_cyclical and margin_schedule[-1] > 0:
        yr5_nopat_margin = max(0.01, margin_schedule[-1] * (1.0 - tax_rate))
        net_capex_reinv = max(0.0, (steady_state_capex_pct - effective_dna_pct) / yr5_nopat_margin)
        terminal_reinv_rate = min(0.80, max(terminal_reinv_rate, net_capex_reinv * 0.85))

    # Terminal NOPAT in Year N+1
    terminal_nopat = proj_rev[-1] * (1.0 + effective_terminal_growth) * margin_schedule[-1] * (1.0 - tax_rate)
    terminal_ufcf = terminal_nopat * (1.0 - terminal_reinv_rate)

    # ------------------------------------------------------------------
    # Exit Multiple Valuation Cross-Check (Damodaran & Institutional standard)
    # ------------------------------------------------------------------
    terminal_ebitda = proj_rev[-1] * (1.0 + effective_terminal_growth) * (margin_schedule[-1] + effective_dna_pct)
    avg_gm_val = float(metrics.get("avg_gross_margin", 0.0))
    if is_extractive:
        benchmark_exit_mult = 4.5 if is_india else 8.0
    elif is_cyclical:
        benchmark_exit_mult = 5.5 if is_india else 7.5
    elif str(stock_data.get("sector") or "").lower() == "utilities":
        benchmark_exit_mult = 7.5
    elif stock_data.get("is_financial", False):
        benchmark_exit_mult = 8.0
    elif (avg_gm_val >= 0.55 or (avg_gm_val >= 0.50 and float(metrics.get("latest_rnd_pct", 0.0)) >= 0.18)) and start_growth >= 0.15:
        benchmark_exit_mult = 16.0
    elif avg_gm_val >= 0.45 and start_growth >= 0.10:
        benchmark_exit_mult = 12.5
    else:
        benchmark_exit_mult = 10.0

    exit_terminal_value = terminal_ebitda * benchmark_exit_mult if terminal_ebitda > 0 else 0.0
    pv_exit_tv = exit_terminal_value / discount_factors[-1] if len(discount_factors) > 0 else 0.0
    exit_ev = pv_ufcf + pv_exit_tv
    exit_equity = exit_ev + cash_equiv - total_debt - minority_interest_claim - preferred_stock_claim
    exit_implied_price = max(0.0, exit_equity / shares_out) if shares_out > 0 else 0.0

    pure_gordon_tv = None
    tv_blend_applied = False
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
        gordon_tv = terminal_ufcf / spread
        pure_gordon_tv = float(gordon_tv)
        # For extractive resource firms (finite ~12-15 yr reserve life) and commodity cyclicals,
        # anchor perpetual Gordon Growth TV against the reserve-life / mid-cycle Exit Multiple TV
        if (not disable_tv_blend) and is_extractive and exit_terminal_value > 0 and gordon_tv > exit_terminal_value:
            terminal_value = 0.35 * gordon_tv + 0.65 * exit_terminal_value
            tv_blend_applied = True
            valuation_adjustments.append({
                "name": "Extractive Reserve-Life Terminal Value Blend",
                "category": "tv_blend",
                "status": "APPLIED",
                "raw_value": float(gordon_tv),
                "applied_value": float(terminal_value),
                "exit_terminal_value": float(exit_terminal_value),
                "weights": "35% Gordon Growth + 65% Exit Multiple",
                "rationale": "Anchored perpetual Gordon Growth TV against finite reserve-life EV/EBITDA Exit Multiple TV.",
                "alternative_scenario": "pure_gordon_tv",
            })
        elif (not disable_tv_blend) and is_cyclical and exit_terminal_value > 0 and gordon_tv > exit_terminal_value:
            terminal_value = 0.45 * gordon_tv + 0.55 * exit_terminal_value
            tv_blend_applied = True
            valuation_adjustments.append({
                "name": "Cyclical Mid-Cycle Terminal Value Blend",
                "category": "tv_blend",
                "status": "APPLIED",
                "raw_value": float(gordon_tv),
                "applied_value": float(terminal_value),
                "exit_terminal_value": float(exit_terminal_value),
                "weights": "45% Gordon Growth + 55% Exit Multiple",
                "rationale": "Anchored perpetual Gordon Growth TV against mid-cycle EV/EBITDA Exit Multiple TV.",
                "alternative_scenario": "pure_gordon_tv",
            })
        else:
            terminal_value = gordon_tv
        pv_terminal_value = terminal_value / discount_factors[-1]

    implied_exit_multiple = (terminal_value / terminal_ebitda) if (terminal_value and terminal_ebitda > 0) else None

    # EV → Equity bridge (subtract financial debt, minority interest, and preferred stock claims)
    enterprise_val = pv_ufcf + pv_terminal_value
    equity_value = enterprise_val + cash_equiv - total_debt - minority_interest_claim - preferred_stock_claim
    
    # Implied price per share floored at 0.0
    implied_price = max(0.0, equity_value / shares_out) if shares_out > 0 else 0.0

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
        "capex_schedule": [float(c) for c in capex_schedule],
        "effective_dna_pct": float(effective_dna_pct),
        "steady_state_capex_pct": float(steady_state_capex_pct),
        "pv_ufcf": float(pv_ufcf),
        "pv_ufcf_list": [float(p) for p in pv_ufcf_list],
        "discount_periods": discount_periods,
        "discount_factors": [float(1.0 / df) for df in discount_factors],
        "terminal_nopat": float(terminal_nopat),
        "terminal_ufcf": float(terminal_ufcf),
        "terminal_value": float(terminal_value) if terminal_value is not None else None,
        "pv_terminal_value": float(pv_terminal_value),
        "equity_value": float(equity_value),
        "cash": float(cash_equiv),
        "total_debt": float(total_debt),
        "minority_interest": float(minority_interest_claim),
        "preferred_stock": float(preferred_stock_claim),
        "terminal_value_valid": terminal_value_valid,
        "terminal_value_note": terminal_value_note,
        "terminal_growth_capped": terminal_growth_capped,
        "effective_terminal_growth": float(effective_terminal_growth),
        "terminal_reinv_rate": float(terminal_reinv_rate),
        "model_yr5_reinv": float(model_yr5_reinv),
        "min_reinv_floor": float(min_reinv_floor),
        "growth_fade_exponent": float(growth_fade_exponent),
        "sustainable_roic": float(sustainable_roic),
        "tangible_ic": float(tangible_ic),
        "hist_roic": float(hist_roic),
        "proj_roic": float(proj_roic),
        "effective_roic": float(effective_roic),
        "roic_reinv": float(roic_reinv),
        "is_high_roic": bool(is_high_roic),
        "shares_used": float(shares_out),
        "shares_basic": float(shares_basic),
        "exit_ev": float(exit_ev),
        "exit_equity": float(exit_equity),
        "exit_terminal_value": float(exit_terminal_value),
        "pv_exit_tv": float(pv_exit_tv),
        "terminal_ebitda": float(terminal_ebitda),
        "tv_share_of_ev": float(tv_share_of_ev),
        "tv_share_flag": tv_share_flag,
        "tv_share_note": tv_share_note,
        "normalized_nwc_to_revenue": float(normalized_nwc_to_revenue),
        "current_margin": float(current_margin) if current_margin is not None else None,
        "tax_rate": float(tax_rate),
        "terminal_growth": float(terminal_growth),
        "requested_terminal_growth": float(terminal_growth),
        "pure_gordon_tv": pure_gordon_tv,
        "tv_blend_applied": tv_blend_applied,
        "capex_taper_applied": bool(capex_taper_applied),
        "raw_avg_capex_pct": float(avg_capex_pct),
        "valuation_adjustments": valuation_adjustments,
        "use_mid_year": use_mid_year,
    }


def compute_dcf_scenarios(
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
) -> Dict[str, Any]:
    """Compute canonical valuation cross-check scenarios around the Base FCFF DCF."""
    base_res = run_dcf(
        start_growth=start_growth,
        ebit_margin=ebit_margin,
        discount_rate=discount_rate,
        metrics=metrics,
        wacc_data=wacc_data,
        stock_data=stock_data,
        terminal_growth=terminal_growth,
        projection_years=projection_years,
        current_margin=current_margin,
        tax_rate=tax_rate,
        use_mid_year=use_mid_year,
    )
    base_price = float(base_res["implied_price"])

    def _delta_pct(val: float) -> float:
        return float((val / base_price - 1.0) * 100.0) if base_price > 0 else 0.0

    scenarios: Dict[str, Any] = {
        "base": {
            "label": "Base Case (FCFF DCF)",
            "applicable": True,
            "implied_price": base_price,
            "enterprise_value": float(base_res["enterprise_value"]),
            "equity_value": float(base_res["equity_value"]),
            "shares_used": float(base_res["shares_used"]),
            "delta_vs_base_pct": 0.0,
            "key_driver": (
                f"Norm NWC/Rev={base_res['normalized_nwc_to_revenue']*100:.2f}%, "
                f"Shares={base_res['shares_used']:,.0f}"
            ),
            "note": "Primary institutional unlevered FCFF valuation.",
        }
    }

    # 1. Unclipped NWC Exposure Scenario
    norm_nwc = float(metrics.get("normalized_nwc_to_revenue", 0.0) or 0.0)
    unclipped_nwc = metrics.get("historical_unclipped_nwc_to_revenue")
    if unclipped_nwc is not None and abs(float(unclipped_nwc) - norm_nwc) > 1e-4:
        m_unclipped = dict(metrics)
        m_unclipped["normalized_nwc_to_revenue"] = float(unclipped_nwc)
        unclipped_res = run_dcf(
            start_growth=start_growth,
            ebit_margin=ebit_margin,
            discount_rate=discount_rate,
            metrics=m_unclipped,
            wacc_data=wacc_data,
            stock_data=stock_data,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
            current_margin=current_margin,
            tax_rate=tax_rate,
            use_mid_year=use_mid_year,
        )
        u_price = float(unclipped_res["implied_price"])
        scenarios["unclipped_nwc"] = {
            "label": "Unclipped Historical NWC",
            "applicable": True,
            "implied_price": u_price,
            "enterprise_value": float(unclipped_res["enterprise_value"]),
            "equity_value": float(unclipped_res["equity_value"]),
            "shares_used": float(unclipped_res["shares_used"]),
            "delta_vs_base_pct": _delta_pct(u_price),
            "key_driver": f"Unclipped NWC/Rev={float(unclipped_nwc)*100:.2f}% vs Base {norm_nwc*100:.2f}%",
            "note": "Shows valuation sensitivity to removing working-capital winsorization.",
        }
    else:
        scenarios["unclipped_nwc"] = {
            "label": "Unclipped Historical NWC",
            "applicable": False,
            "implied_price": base_price,
            "enterprise_value": float(base_res["enterprise_value"]),
            "equity_value": float(base_res["equity_value"]),
            "shares_used": float(base_res["shares_used"]),
            "delta_vs_base_pct": 0.0,
            "key_driver": f"NWC/Rev={norm_nwc*100:.2f}% (unclipped)",
            "note": "Normalized NWC already equals unclipped historical NWC/Revenue.",
        }

    # 2. Contracted Capital Commitments Scenario (e.g. Ind AS Note 32c)
    cap_commit = metrics.get("capital_commitments")
    if cap_commit is not None and float(cap_commit) > 0:
        annual_commit = float(cap_commit) / float(max(1, projection_years))
        commit_res = run_dcf(
            start_growth=start_growth,
            ebit_margin=ebit_margin,
            discount_rate=discount_rate,
            metrics=metrics,
            wacc_data=wacc_data,
            stock_data=stock_data,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
            current_margin=current_margin,
            tax_rate=tax_rate,
            use_mid_year=use_mid_year,
            capex_floor_abs=annual_commit,
        )
        c_price = float(commit_res["implied_price"])
        scenarios["committed_capex"] = {
            "label": "Contracted Capital Commitments",
            "applicable": True,
            "implied_price": c_price,
            "enterprise_value": float(commit_res["enterprise_value"]),
            "equity_value": float(commit_res["equity_value"]),
            "shares_used": float(commit_res["shares_used"]),
            "delta_vs_base_pct": _delta_pct(c_price),
            "key_driver": f"Annual CapEx >= {annual_commit:,.2f} ({float(cap_commit):,.2f} / {projection_years}Y)",
            "note": "Floors annual explicit CapEx at disclosed capital commitments without crediting post-Year-5 incremental cash flows.",
        }
    else:
        scenarios["committed_capex"] = {
            "label": "Contracted Capital Commitments",
            "applicable": False,
            "implied_price": base_price,
            "enterprise_value": float(base_res["enterprise_value"]),
            "equity_value": float(base_res["equity_value"]),
            "shares_used": float(base_res["shares_used"]),
            "delta_vs_base_pct": 0.0,
            "key_driver": "Not disclosed",
            "note": "No separate contracted capital commitment schedule disclosed.",
        }

    # 3. Exit Multiple Cross-Check Scenario
    e_price = float(base_res["exit_implied_price"])
    scenarios["exit_multiple"] = {
        "label": f"Exit Multiple ({base_res['benchmark_exit_multiple']:.1f}x Term. EBITDA)",
        "applicable": True,
        "implied_price": e_price,
        "enterprise_value": float(base_res["exit_ev"]),
        "equity_value": float(base_res["exit_equity"]),
        "shares_used": float(base_res["shares_used"]),
        "delta_vs_base_pct": _delta_pct(e_price),
        "key_driver": f"Benchmark EV/EBITDA={base_res['benchmark_exit_multiple']:.1f}x",
        "note": "Gordon Growth terminal value replaced by sector benchmark EV/EBITDA exit multiple.",
    }

    # 4. Full RSU Dilution Scenario (incl. unvested RSUs / no buyback offset)
    tsm_bridge = (stock_data.get("share_reconciliation") or {}).get("tsm_bridge") or {}
    full_rsu_shares = tsm_bridge.get("tsm_diluted_shares_with_rsus")
    base_shares = float(base_res["shares_used"])
    if full_rsu_shares is not None and float(full_rsu_shares) > base_shares * 1.001:
        rsu_res = run_dcf(
            start_growth=start_growth,
            ebit_margin=ebit_margin,
            discount_rate=discount_rate,
            metrics=metrics,
            wacc_data=wacc_data,
            stock_data=stock_data,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
            current_margin=current_margin,
            tax_rate=tax_rate,
            use_mid_year=use_mid_year,
            shares_override=float(full_rsu_shares),
        )
        r_price = float(rsu_res["implied_price"])
        scenarios["full_rsu_dilution"] = {
            "label": "Full RSU Dilution (All Unvested Awards)",
            "applicable": True,
            "implied_price": r_price,
            "enterprise_value": float(rsu_res["enterprise_value"]),
            "equity_value": float(rsu_res["equity_value"]),
            "shares_used": float(full_rsu_shares),
            "delta_vs_base_pct": _delta_pct(r_price),
            "key_driver": f"Shares={float(full_rsu_shares):,.0f} vs Base {base_shares:,.0f}",
            "note": "Stress-tests per-share value including all unvested RSUs alongside ITM option dilution.",
        }
    else:
        scenarios["full_rsu_dilution"] = {
            "label": "Full RSU Dilution",
            "applicable": False,
            "implied_price": base_price,
            "enterprise_value": float(base_res["enterprise_value"]),
            "equity_value": float(base_res["equity_value"]),
            "shares_used": base_shares,
            "delta_vs_base_pct": 0.0,
            "key_driver": f"Shares={base_shares:,.0f} (no separate unvested RSU overhang)",
            "note": "No separate unvested RSU tranche disclosed in primary filing.",
        }

    # 5. Pure Unblended Gordon Growth TV Scenario (for extractive/cyclical blend transparency)
    if base_res.get("tv_blend_applied"):
        pg_res = run_dcf(
            start_growth=start_growth,
            ebit_margin=ebit_margin,
            discount_rate=discount_rate,
            metrics=metrics,
            wacc_data=wacc_data,
            stock_data=stock_data,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
            current_margin=current_margin,
            tax_rate=tax_rate,
            use_mid_year=use_mid_year,
            disable_tv_blend=True,
        )
        pg_price = float(pg_res["implied_price"])
        scenarios["pure_gordon_tv"] = {
            "label": "Pure Gordon Growth TV (Unblended)",
            "applicable": True,
            "implied_price": pg_price,
            "enterprise_value": float(pg_res["enterprise_value"]),
            "equity_value": float(pg_res["equity_value"]),
            "shares_used": float(pg_res["shares_used"]),
            "delta_vs_base_pct": _delta_pct(pg_price),
            "key_driver": f"Pure Gordon TV vs Blended {float(base_res.get('terminal_value') or 0.0):,.0f}",
            "note": "Removes extractive/cyclical Exit-Multiple TV anchor blend.",
        }

    # 6. Unadjusted Historical CapEx Scenario (no greenfield / extractive tapering)
    if base_res.get("capex_taper_applied"):
        rc_res = run_dcf(
            start_growth=start_growth,
            ebit_margin=ebit_margin,
            discount_rate=discount_rate,
            metrics=metrics,
            wacc_data=wacc_data,
            stock_data=stock_data,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
            current_margin=current_margin,
            tax_rate=tax_rate,
            use_mid_year=use_mid_year,
            use_raw_capex=True,
        )
        rc_price = float(rc_res["implied_price"])
        scenarios["unadjusted_capex"] = {
            "label": "Unadjusted Historical Avg CapEx",
            "applicable": True,
            "implied_price": rc_price,
            "enterprise_value": float(rc_res["enterprise_value"]),
            "equity_value": float(rc_res["equity_value"]),
            "shares_used": float(rc_res["shares_used"]),
            "delta_vs_base_pct": _delta_pct(rc_price),
            "key_driver": f"Raw CapEx/Rev={float(metrics.get('avg_capex_pct', 0.0))*100:.2f}%",
            "note": "Runs historical average CapEx/Rev across forecast years without greenfield tapering.",
        }

    # 7. Unverified Extractive ARO Provisions Debt Stress (75% LT Provisions added to Debt)
    aro_stress = float(metrics.get("unverified_aro_stress_claim") or 0.0)
    if aro_stress > 0:
        aro_debt = float(base_res["total_debt"]) + aro_stress
        aro_res = run_dcf(
            start_growth=start_growth,
            ebit_margin=ebit_margin,
            discount_rate=discount_rate,
            metrics=metrics,
            wacc_data=wacc_data,
            stock_data=stock_data,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
            current_margin=current_margin,
            tax_rate=tax_rate,
            use_mid_year=use_mid_year,
            debt_override=aro_debt,
        )
        a_price = float(aro_res["implied_price"])
        scenarios["aro_provisions_stress"] = {
            "label": "75% LT-Provisions ARO Debt Stress",
            "applicable": True,
            "implied_price": a_price,
            "enterprise_value": float(aro_res["enterprise_value"]),
            "equity_value": float(aro_res["equity_value"]),
            "shares_used": float(aro_res["shares_used"]),
            "delta_vs_base_pct": _delta_pct(a_price),
            "key_driver": f"+75% LT Provisions ({aro_stress:,.0f}) added to Debt",
            "note": "Stress-tests extractive balance sheet treating 75% of unverified Long-Term Provisions as ARO debt.",
        }

    # 8. Unadjusted Gross Debt Scenario (reversing greenfield CWIP / captive finance offsets)
    gf_off = float(metrics.get("greenfield_debt_offset") or 0.0)
    cap_off = float(metrics.get("captive_debt_offset") or 0.0)
    if gf_off > 0 or cap_off > 0:
        unadj_debt = float(base_res["total_debt"]) + gf_off + cap_off
        gd_res = run_dcf(
            start_growth=start_growth,
            ebit_margin=ebit_margin,
            discount_rate=discount_rate,
            metrics=metrics,
            wacc_data=wacc_data,
            stock_data=stock_data,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
            current_margin=current_margin,
            tax_rate=tax_rate,
            use_mid_year=use_mid_year,
            debt_override=unadj_debt,
        )
        gd_price = float(gd_res["implied_price"])
        scenarios["unadjusted_gross_debt"] = {
            "label": "Unadjusted Gross Debt (No CWIP/Captive Offset)",
            "applicable": True,
            "implied_price": gd_price,
            "enterprise_value": float(gd_res["enterprise_value"]),
            "equity_value": float(gd_res["equity_value"]),
            "shares_used": float(gd_res["shares_used"]),
            "delta_vs_base_pct": _delta_pct(gd_price),
            "key_driver": f"Restores {gf_off + cap_off:,.0f} offset back into EV Debt",
            "note": "Deducts full policy-aligned financial borrowings without CWIP or captive receivables debt offsets.",
        }

    # 9. Sector Bottom-Up Beta vs Raw Empirical Beta Cross-Check
    base_beta = float(stock_data.get("beta", 1.0) or 1.0)
    rf = float(wacc_data.get("min_wacc", 0.055) - 0.015)
    raw_ke = float(wacc_data.get("raw_cost_of_equity", wacc_data.get("cost_of_equity", discount_rate)))
    erp = (raw_ke - rf) / base_beta if base_beta > 0 else 0.055
    we = float(wacc_data.get("weight_equity", 1.0))
    wd = float(wacc_data.get("weight_debt", 0.0))
    kd_at = float(wacc_data.get("cost_of_debt", 0.05))
    min_w = float(wacc_data.get("min_wacc", rf + 0.015))
    if stock_data.get("cyclical_beta_low_flag", False):
        sec_beta = float(stock_data.get("sector_bottom_up_beta", base_beta))
        alt_ke = max(rf + 0.015, rf + sec_beta * erp)
        alt_wacc = max(min_w, we * alt_ke + wd * kd_at)
        b_res = run_dcf(
            start_growth=start_growth,
            ebit_margin=ebit_margin,
            discount_rate=alt_wacc,
            metrics=metrics,
            wacc_data=wacc_data,
            stock_data=stock_data,
            terminal_growth=terminal_growth,
            projection_years=projection_years,
            current_margin=current_margin,
            tax_rate=tax_rate,
            use_mid_year=use_mid_year,
        )
        b_price = float(b_res["implied_price"])
        scenarios["bottom_up_sector_beta"] = {
            "label": "Bottom-Up Cyclical Sector Beta",
            "applicable": True,
            "implied_price": b_price,
            "enterprise_value": float(b_res["enterprise_value"]),
            "equity_value": float(b_res["equity_value"]),
            "shares_used": float(b_res["shares_used"]),
            "delta_vs_base_pct": _delta_pct(b_price),
            "key_driver": f"Sector Beta={sec_beta:.2f} -> WACC={alt_wacc*100:.2f}%",
            "note": "Replaces low empirical cyclical regression beta with Damodaran relevered sector beta.",
        }
    elif stock_data.get("beta_clamped", False):
        raw_bl = float(stock_data.get("raw_blume_beta", base_beta))
        if abs(raw_bl - base_beta) > 0.02:
            alt_ke = max(rf + 0.015, rf + raw_bl * erp)
            alt_wacc = max(min_w, we * alt_ke + wd * kd_at)
            ub_res = run_dcf(
                start_growth=start_growth,
                ebit_margin=ebit_margin,
                discount_rate=alt_wacc,
                metrics=metrics,
                wacc_data=wacc_data,
                stock_data=stock_data,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                current_margin=current_margin,
                tax_rate=tax_rate,
                use_mid_year=use_mid_year,
            )
            ub_price = float(ub_res["implied_price"])
            scenarios["unadjusted_beta"] = {
                "label": "Unclamped Raw Regression Beta",
                "applicable": True,
                "implied_price": ub_price,
                "enterprise_value": float(ub_res["enterprise_value"]),
                "equity_value": float(ub_res["equity_value"]),
                "shares_used": float(ub_res["shares_used"]),
                "delta_vs_base_pct": _delta_pct(ub_price),
                "key_driver": f"Raw Blume Beta={raw_bl:.2f} -> WACC={alt_wacc*100:.2f}%",
                "note": "Shows valuation sensitivity using unclamped raw regression beta.",
            }

    return scenarios


def run_dcf_batch(
    sim_growth: np.ndarray,
    sim_margin: np.ndarray,
    sim_wacc: np.ndarray,
    metrics: dict,
    wacc_data: dict,
    stock_data: dict,
    terminal_growth: float = 0.025,
    projection_years: int = 5,
    tax_rate: Optional[float] = None,
    use_mid_year: bool = True,
    current_margin: Optional[float] = None,
    shares_override: Optional[float] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized multi-stage DCF evaluation across all Monte Carlo draws simultaneously.

    Mathematically aligned with ``run_dcf`` (including continuous smooth growth fade exponent
    and margin convergence from ``current_margin``), returning
    ``(implied_prices, enterprise_values, equity_values)``.
    """
    n = len(sim_growth)
    avg_dna_pct: float = float(metrics["avg_dna_pct"])
    avg_capex_pct: float = float(metrics["avg_capex_pct"])
    normalized_nwc_to_revenue: float = float(
        metrics.get("normalized_nwc_to_revenue", metrics.get("avg_dnwc_pct", 0.0))
    )
    last_revenue: float = float(metrics["last_revenue"])
    total_debt: float = float(wacc_data["total_debt"])
    cash_equiv: float = float(metrics["cash_and_equivalents"])
    minority_interest_claim: float = float(metrics.get("minority_interest_claim", 0.0) or 0.0)
    preferred_stock_claim: float = float(metrics.get("preferred_stock_claim", 0.0) or 0.0)
    shares_out: float = float(
        shares_override
        if (shares_override is not None and shares_override > 0)
        else (stock_data.get("diluted_valuation_shares") or stock_data["shares_outstanding"])
    )

    is_extractive = stock_data.get("is_extractive", False)
    is_cyclical = stock_data.get("is_cyclical", False)
    if "is_extractive" not in stock_data or "is_cyclical" not in stock_data:
        from engine.data_layer import classify_sector_dynamics
        is_extractive, is_cyclical = classify_sector_dynamics(
            stock_data.get("sector"),
            stock_data.get("industry"),
            stock_data.get("ticker"),
            stock_data.get("name"),
        )

    if tax_rate is None:
        tax_rate = stock_data.get(
            "_tax_rate", 0.2517 if stock_data.get("market") == "IN" else 0.21
        )

    if projection_years > 1:
        steps = np.arange(projection_years, dtype=float) / float(projection_years - 1)
    else:
        steps = np.zeros(1, dtype=float)
    if not is_extractive and not is_cyclical:
        fade_blend = np.clip((sim_growth - terminal_growth - 0.05) / 0.10, 0.0, 1.0)
        fade_exponents = 1.0 + 0.35 * fade_blend
        growth_schedule = sim_growth[:, None] - (sim_growth[:, None] - terminal_growth) * (
            steps[None, :] ** fade_exponents[:, None]
        )
    else:
        growth_schedule = sim_growth[:, None] - (sim_growth[:, None] - terminal_growth) * steps[None, :]

    if current_margin is not None:
        base_m_mean = float(np.mean(sim_margin)) if n > 0 else float(current_margin)
        sim_start_m = float(current_margin) + 0.5 * (sim_margin - base_m_mean)
        margin_schedule = np.linspace(sim_start_m, sim_margin, projection_years + 1, axis=1)[:, 1:]
    else:
        margin_schedule = np.repeat(sim_margin[:, None], projection_years, axis=1)

    effective_dna_pct = (
        min(avg_dna_pct, max(avg_capex_pct * 1.05, 0.025))
        if avg_dna_pct > avg_capex_pct * 1.15
        else avg_dna_pct
    )

    base_steady_state = effective_dna_pct * (1.0 + terminal_growth)
    mean_start_g = float(np.mean(sim_growth)) if n > 0 else 0.05
    mean_sim_m = float(np.mean(sim_margin)) if n > 0 else 0.12
    cwip_to_rev = float(metrics.get("cwip_to_rev", 0.0) or 0.0)
    if is_extractive:
        if cwip_to_rev > 0.50:
            max_ext_capex = effective_dna_pct * 1.45
        else:
            max_ext_capex = max(effective_dna_pct * 2.5, max(0.05, mean_sim_m) * (1.0 - tax_rate) * 0.72)
        steady_state_capex_pct = max(base_steady_state, min(avg_capex_pct, max_ext_capex))
        eff_start_capex = min(avg_capex_pct, max_ext_capex * 1.10)
    elif is_cyclical:
        steady_state_capex_pct = max(base_steady_state, min(avg_capex_pct * 0.90, effective_dna_pct * 1.35))
        eff_start_capex = avg_capex_pct
    else:
        steady_state_capex_pct = base_steady_state
        if avg_capex_pct > effective_dna_pct * 2.20 and avg_capex_pct > 0.15:
            eff_start_capex = effective_dna_pct * (1.0 + max(0.10, terminal_growth))
        elif avg_capex_pct > effective_dna_pct * 1.40 and avg_capex_pct > 0.12:
            eff_start_capex = min(
                avg_capex_pct,
                effective_dna_pct * (1.0 + max(0.15, mean_start_g * 1.8)),
            )
        else:
            eff_start_capex = avg_capex_pct
    capex_schedule = np.linspace(eff_start_capex, steady_state_capex_pct, projection_years)

    if use_mid_year:
        discount_periods = np.arange(projection_years, dtype=float) + 0.5
    else:
        discount_periods = np.arange(projection_years, dtype=float) + 1.0
    discount_factors = (1.0 + sim_wacc[:, None]) ** discount_periods[None, :]

    last_rev = np.full(n, last_revenue, dtype=float)
    pv_ufcf = np.zeros(n, dtype=float)
    last_nopat = np.zeros(n, dtype=float)

    for yr in range(projection_years):
        g = growth_schedule[:, yr]
        m_yr = margin_schedule[:, yr]
        next_rev = last_rev * (1.0 + g)
        nopat = next_rev * m_yr * (1.0 - tax_rate)
        dna_add = next_rev * effective_dna_pct
        capex_sub = next_rev * capex_schedule[yr]
        delta_nwc = normalized_nwc_to_revenue * (next_rev - last_rev)
        ufcf = nopat + dna_add - capex_sub - delta_nwc
        pv_ufcf += ufcf / discount_factors[:, yr]
        last_rev = next_rev
        last_nopat = nopat

    bs = (
        metrics.get("statements", {}).get("balance_sheet", {})
        if isinstance(metrics.get("statements"), dict)
        else {}
    )
    equity_series = bs.get("Total Stockholders' Equity", [0]) if isinstance(bs, dict) else [0]
    equity_bv = equity_series[-1] if equity_series else 0.0
    gw_series = bs.get("Intangible Assets & Goodwill", [0]) if isinstance(bs, dict) else [0]
    gw_val = float(gw_series[-1]) if gw_series else 0.0
    invested_capital = max(1.0, equity_bv + total_debt - cash_equiv)
    tangible_ic = max(last_revenue * 0.15, invested_capital - 1.00 * max(0.0, gw_val))

    hist_ebit = metrics.get("ebit", [])
    if hist_ebit:
        last_ebit = np.full(n, float(hist_ebit[-1]), dtype=float)
    else:
        last_ebit = last_rev * sim_margin
    hist_nopat = last_ebit * (1.0 - tax_rate)
    hist_roic = np.where(
        (tangible_ic > 0) & (hist_nopat > 0),
        hist_nopat / tangible_ic,
        0.0,
    )
    yr5_tangible_ic_arr = tangible_ic * np.maximum(1.0, last_rev / max(1.0, last_revenue))
    proj_roic = np.where(
        (yr5_tangible_ic_arr > 0) & (last_nopat > 0),
        last_nopat / yr5_tangible_ic_arr,
        sim_wacc,
    )
    if current_margin is not None:
        effective_roic = np.where(hist_roic <= 0.02, np.maximum(hist_roic, proj_roic), 0.50 * hist_roic + 0.50 * proj_roic)
    else:
        effective_roic = np.where(hist_roic > 0, hist_roic, proj_roic)

    is_high_gm = (not is_extractive and not is_cyclical and float(metrics.get("avg_gross_margin", 0.0)) >= 0.45)
    is_high_roic_arr = (not is_extractive and not is_cyclical) & (effective_roic >= 0.22) & (is_high_gm | (effective_roic >= 0.28))
    max_roic_cap = np.where(is_high_roic_arr, 0.45, 0.30)
    min_reinv_floor = np.where(is_high_roic_arr, 0.06, 0.10)
    min_roic_floor_arr = (sim_wacc + 0.045) if (not is_extractive and not is_cyclical and avg_capex_pct > effective_dna_pct * 2.20) else sim_wacc
    sustainable_roic = np.maximum(min_roic_floor_arr, np.minimum(effective_roic, max_roic_cap))

    is_india = stock_data.get("market") == "IN"
    if is_extractive:
        max_g_allowed = 0.025
    else:
        max_g_allowed = 0.050 if is_india else 0.025
    clamped_terminal_growth = min(terminal_growth, max_g_allowed)

    min_spread = 0.025
    effective_terminal_growth = np.where(
        sim_wacc - clamped_terminal_growth < min_spread,
        np.maximum(0.01, sim_wacc - min_spread),
        clamped_terminal_growth,
    )

    roic_reinv = effective_terminal_growth / sustainable_roic
    if not is_extractive and not is_cyclical:
        yr5_nopat_m = np.maximum(0.01, sim_margin * (1.0 - tax_rate))
        model_yr5_reinv = np.maximum(
            0.0,
            (
                (steady_state_capex_pct - effective_dna_pct)
                + np.maximum(0.0, normalized_nwc_to_revenue * effective_terminal_growth)
            )
            / yr5_nopat_m,
        )
        blended_reinv = np.minimum(roic_reinv, 0.45 * roic_reinv + 0.55 * model_yr5_reinv)
        reinv_candidate = np.where(is_high_roic_arr, blended_reinv, roic_reinv)
        terminal_reinv_rate = np.minimum(0.80, np.maximum(min_reinv_floor, reinv_candidate))
    else:
        terminal_reinv_rate = np.minimum(0.80, np.maximum(min_reinv_floor, roic_reinv))

    if is_extractive:
        pos_m = sim_margin > 0
        yr5_nopat_m_arr = np.maximum(0.01, sim_margin * (1.0 - tax_rate))
        net_capex_reinv = np.where(
            pos_m,
            np.maximum(0.0, (steady_state_capex_pct - effective_dna_pct) / yr5_nopat_m_arr),
            0.0,
        )
        terminal_reinv_rate = np.where(
            pos_m,
            np.minimum(0.80, np.maximum(terminal_reinv_rate, net_capex_reinv)),
            terminal_reinv_rate,
        )
    elif is_cyclical:
        pos_m = sim_margin > 0
        yr5_nopat_m_arr = np.maximum(0.01, sim_margin * (1.0 - tax_rate))
        net_capex_reinv = np.where(
            pos_m,
            np.maximum(0.0, (steady_state_capex_pct - effective_dna_pct) / yr5_nopat_m_arr),
            0.0,
        )
        terminal_reinv_rate = np.where(
            pos_m,
            np.minimum(0.80, np.maximum(terminal_reinv_rate, net_capex_reinv * 0.85)),
            terminal_reinv_rate,
        )

    terminal_nopat = last_rev * (1.0 + effective_terminal_growth) * sim_margin * (1.0 - tax_rate)
    terminal_ufcf = terminal_nopat * (1.0 - terminal_reinv_rate)
    terminal_ebitda = last_rev * (1.0 + effective_terminal_growth) * (sim_margin + effective_dna_pct)

    valid_tv = (sim_wacc > effective_terminal_growth) & (terminal_ufcf > 0)
    spread = np.where(valid_tv, sim_wacc - effective_terminal_growth, 1.0)
    gordon_tv = np.where(
        valid_tv, terminal_ufcf / spread, 0.0
    )
    if is_extractive:
        ext_mult = 4.5 if is_india else 8.0
        exit_tv_arr = np.maximum(0.0, terminal_ebitda * ext_mult)
        terminal_value = np.where(
            (exit_tv_arr > 0) & (gordon_tv > exit_tv_arr),
            0.35 * gordon_tv + 0.65 * exit_tv_arr,
            gordon_tv,
        )
    elif is_cyclical:
        cyc_mult = 5.5 if is_india else 7.5
        exit_tv_arr = np.maximum(0.0, terminal_ebitda * cyc_mult)
        terminal_value = np.where(
            (exit_tv_arr > 0) & (gordon_tv > exit_tv_arr),
            0.45 * gordon_tv + 0.55 * exit_tv_arr,
            gordon_tv,
        )
    else:
        terminal_value = gordon_tv
    pv_terminal_value = np.where(valid_tv, terminal_value / discount_factors[:, -1], 0.0)

    enterprise_val = pv_ufcf + pv_terminal_value
    equity_value = enterprise_val + cash_equiv - total_debt - minority_interest_claim - preferred_stock_claim
    implied_price = (
        np.maximum(0.0, equity_value / shares_out) if shares_out > 0 else np.zeros(n)
    )
    return implied_price, enterprise_val, equity_value

