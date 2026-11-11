"""
Reverse DCF Engine — Expectations Investing Module
=================================================
Calculates what financial expectations are implied by the current market price (P0).
Based on Michael J. Mauboussin's "Expectations Investing" and Damodaran's narrative mechanics:
  1. Market-Implied Revenue / Net Income Growth Rate (Hurdle Rate)
  2. Expectations Gap in basis points (Market Hurdle vs. Fundamental Baseline)
  3. Market-Implied Operating Margin / ROE
  4. Market-Implied Cost of Capital (Discount Rate)
  5. Expectations Assessment & Plausibility Verdict
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


def calculate_reverse_dcf(
    current_price: float,
    model_fair_value: float,
    base_start_growth: float,
    base_target_margin: float,
    discount_rate: float,
    metrics: Dict[str, Any],
    stock_data: Dict[str, Any],
    wacc_data: Optional[Dict[str, Any]] = None,
    terminal_growth: float = 0.025,
    projection_years: int = 5,
    current_margin: Optional[float] = None,
    tax_rate: Optional[float] = None,
    market_profile: Optional[Dict[str, Any]] = None,
    is_equity_model: bool = False,
) -> Dict[str, Any]:
    """Solve for the market-implied growth hurdle, margin, and discount rate.

    Parameters
    ----------
    current_price : float
        Current market trading price (P0).
    model_fair_value : float
        Intrinsic fair value computed by the baseline model.
    base_start_growth : float
        Baseline start growth rate used in the model (e.g. 0.104 for 10.4%).
    base_target_margin : float
        Baseline target EBIT margin (or ROE for banking models).
    discount_rate : float
        Discount rate used in the model (WACC for FCFF, Cost of Equity for DDM).
    metrics : dict
        Historical financial metrics from compute_historical_metrics.
    stock_data : dict
        Stock profile and financial statement data.
    wacc_data : dict, optional
        WACC breakdown dict from compute_wacc.
    terminal_growth : float, default 0.025
        Perpetual terminal growth rate.
    projection_years : int, default 5
        Explicit forecast horizon.
    current_margin : float, optional
        Current period margin for linear margin step-up.
    tax_rate : float, optional
        Effective marginal corporate tax rate.
    market_profile : dict, optional
        Country market profile (risk-free rate, equity risk premium).
    is_equity_model : bool, default False
        True if valuing a bank / capital-intensive financial using DDM / FCFE.

    Returns
    -------
    dict
        Structured reverse DCF metrics, expectation hurdles, and narrative verdict.
    """
    if current_price is None or current_price <= 0 or model_fair_value is None or model_fair_value <= 0:
        return _empty_reverse_dcf(current_price, model_fair_value, base_start_growth, base_target_margin, discount_rate)

    is_india = (
        stock_data.get("market") == "IN"
        or str(stock_data.get("ticker", "")).endswith((".NS", ".BO"))
        or (market_profile and market_profile.get("currency") == "INR")
    )
    if terminal_growth is None:
        terminal_growth = (market_profile.get("terminal_growth") if market_profile else None) or (0.050 if is_india else 0.025)

    from engine.dcf_engine import run_dcf
    from engine.bank_engine import run_bank_valuation

    # 1. Price evaluator helper function
    def _eval_growth(g: float) -> float:
        try:
            if is_equity_model:
                res = run_bank_valuation(
                    start_growth=g,
                    target_roe=base_target_margin,
                    cost_of_equity=discount_rate,
                    metrics=metrics,
                    stock_data=stock_data,
                    market_profile=market_profile,
                    terminal_growth=terminal_growth,
                    projection_years=projection_years,
                )
            else:
                res = run_dcf(
                    start_growth=g,
                    ebit_margin=base_target_margin,
                    discount_rate=discount_rate,
                    metrics=metrics,
                    wacc_data=wacc_data or {},
                    stock_data=stock_data,
                    terminal_growth=terminal_growth,
                    projection_years=projection_years,
                    current_margin=current_margin,
                    tax_rate=tax_rate,
                )
            return float(res.get("implied_price", 0.0))
        except Exception as exc:
            logger.debug("Reverse DCF growth evaluation failed at g=%.3f: %s", g, exc)
            return 0.0

    # 2. Solve for Market-Implied Growth Rate (g_implied)
    low_g, high_g = -0.60, 3.00
    p_min = _eval_growth(low_g)
    p_max = _eval_growth(high_g)

    if current_price <= p_min:
        market_implied_growth = low_g
        growth_status = "bounded_low"
    elif current_price >= p_max:
        market_implied_growth = high_g
        growth_status = "bounded_high"
    else:
        # Bisection search (36 iterations yields < 1e-10 precision)
        low, high = low_g, high_g
        for _ in range(36):
            mid = (low + high) / 2.0
            p_mid = _eval_growth(mid)
            if p_mid < current_price:
                low = mid
            else:
                high = mid
        market_implied_growth = float((low + high) / 2.0)
        growth_status = "solved"

    growth_hurdle_gap = market_implied_growth - base_start_growth
    growth_hurdle_gap_bps = round(growth_hurdle_gap * 10000.0, 1)

    # 3. Solve for Market-Implied Margin / ROE (holding growth at baseline)
    market_implied_margin = None
    margin_gap_bps = None

    if not is_equity_model:
        def _eval_margin(m: float) -> float:
            try:
                res = run_dcf(
                    start_growth=base_start_growth,
                    ebit_margin=m,
                    discount_rate=discount_rate,
                    metrics=metrics,
                    wacc_data=wacc_data or {},
                    stock_data=stock_data,
                    terminal_growth=terminal_growth,
                    projection_years=projection_years,
                    current_margin=current_margin,
                    tax_rate=tax_rate,
                )
                return float(res.get("implied_price", 0.0))
            except Exception:
                return 0.0

        p_m_low = _eval_margin(0.01)
        p_m_high = _eval_margin(0.95)

        if p_m_low <= current_price <= p_m_high:
            m_low, m_high = 0.01, 0.95
            for _ in range(32):
                m_mid = (m_low + m_high) / 2.0
                p_mid = _eval_margin(m_mid)
                if p_mid < current_price:
                    m_low = m_mid
                else:
                    m_high = m_mid
            market_implied_margin = float((m_low + m_high) / 2.0)
            margin_gap_bps = round((market_implied_margin - base_target_margin) * 10000.0, 1)

    # 4. Solve for Market-Implied Discount Rate (WACC / Ke) holding cash flows constant
    market_implied_wacc = None
    wacc_gap_bps = None

    if not is_equity_model:
        def _eval_wacc(r: float) -> float:
            try:
                res = run_dcf(
                    start_growth=base_start_growth,
                    ebit_margin=base_target_margin,
                    discount_rate=r,
                    metrics=metrics,
                    wacc_data=wacc_data or {},
                    stock_data=stock_data,
                    terminal_growth=terminal_growth,
                    projection_years=projection_years,
                    current_margin=current_margin,
                    tax_rate=tax_rate,
                )
                return float(res.get("implied_price", 0.0))
            except Exception:
                return 0.0

        min_w = terminal_growth + 0.005
        max_w = 0.35
        p_w_min = _eval_wacc(max_w)  # high discount rate -> lower price
        p_w_max = _eval_wacc(min_w)  # low discount rate -> higher price

        if p_w_min <= current_price <= p_w_max:
            w_low, w_high = min_w, max_w
            for _ in range(32):
                w_mid = (w_low + w_high) / 2.0
                p_mid = _eval_wacc(w_mid)
                if p_mid > current_price:
                    w_low = w_mid
                else:
                    w_high = w_mid
            market_implied_wacc = float((w_low + w_high) / 2.0)
            wacc_gap_bps = round((market_implied_wacc - discount_rate) * 10000.0, 1)

    # 5. Narrative Expectations Synthesis
    if growth_hurdle_gap_bps >= 2500:
        stance = "Extreme Growth Hurdle"
        plausibility = "Speculative Premium / Demands Secular Acceleration"
        narrative = (
            f"Current market price of {current_price:.2f} requires a sustained {market_implied_growth*100:.1f}% "
            f"revenue CAGR over the next {projection_years} years (+{growth_hurdle_gap_bps:+.0f} bps over the "
            f"{base_start_growth*100:.1f}% fundamental baseline). To justify today's price, the company must execute "
            f"an unprecedented operational expansion that far outstrips historical delivery."
        )
    elif growth_hurdle_gap_bps >= 800:
        stance = "Aggressive Growth Hurdle"
        plausibility = "Demanding / Requires Multiple Expansion or New S-Curves"
        narrative = (
            f"Market pricing bakes in a {market_implied_growth*100:.1f}% growth rate (+{growth_hurdle_gap_bps:+.0f} bps "
            f"over fundamental baseline of {base_start_growth*100:.1f}%). Investors are paying a premium anticipating "
            f"market share gains, TAM expansion, or pricing power beyond historical norms."
        )
    elif growth_hurdle_gap_bps >= -300:
        stance = "Consensus Aligned"
        plausibility = "Realistic / Fundamental Parity"
        narrative = (
            f"Current market price implies a {market_implied_growth*100:.1f}% growth rate, closely aligning with "
            f"the {base_start_growth*100:.1f}% fundamental baseline ({growth_hurdle_gap_bps:+.0f} bps delta). "
            f"Market valuation appears broadly anchored in current operational reality."
        )
    elif growth_hurdle_gap_bps >= -1500:
        stance = "Priced for Deceleration"
        plausibility = "Conservative / Discounted Expectations"
        narrative = (
            f"The market is discounting future performance, pricing in a growth deceleration to "
            f"{market_implied_growth*100:.1f}% ({growth_hurdle_gap_bps:+.0f} bps below baseline of "
            f"{base_start_growth*100:.1f}%). Offers potential margin of safety if baseline growth persists."
        )
    else:
        stance = "Priced for Structural Contraction"
        plausibility = "Deep Discount / Severe Distress Priced In"
        narrative = (
            f"Current price reflects severe skepticism, implying a growth trajectory of "
            f"{market_implied_growth*100:.1f}% ({growth_hurdle_gap_bps:+.0f} bps below baseline). "
            f"Market expects secular obsolescence, margin collapse, or capital destruction."
        )

    return {
        "current_price": float(current_price),
        "model_fair_value": float(model_fair_value),
        "valuation_gap_pct": round(((model_fair_value / current_price) - 1.0) * 100.0, 2),
        "base_growth": float(base_start_growth),
        "market_implied_growth": float(market_implied_growth),
        "growth_hurdle_gap_bps": float(growth_hurdle_gap_bps),
        "growth_status": growth_status,
        "base_margin": float(base_target_margin),
        "market_implied_margin": float(market_implied_margin) if market_implied_margin is not None else None,
        "margin_gap_bps": float(margin_gap_bps) if margin_gap_bps is not None else None,
        "base_discount_rate": float(discount_rate),
        "market_implied_wacc": float(market_implied_wacc) if market_implied_wacc is not None else None,
        "wacc_gap_bps": float(wacc_gap_bps) if wacc_gap_bps is not None else None,
        "stance": stance,
        "plausibility": plausibility,
        "narrative": narrative,
    }


def _empty_reverse_dcf(
    current_price: float,
    model_fair_value: float,
    base_start_growth: float,
    base_target_margin: float,
    discount_rate: float,
) -> Dict[str, Any]:
    return {
        "current_price": float(current_price or 0.0),
        "model_fair_value": float(model_fair_value or 0.0),
        "valuation_gap_pct": 0.0,
        "base_growth": float(base_start_growth or 0.0),
        "market_implied_growth": float(base_start_growth or 0.0),
        "growth_hurdle_gap_bps": 0.0,
        "growth_status": "insufficient_data",
        "base_margin": float(base_target_margin or 0.0),
        "market_implied_margin": None,
        "margin_gap_bps": None,
        "base_discount_rate": float(discount_rate or 0.0),
        "market_implied_wacc": None,
        "wacc_gap_bps": None,
        "stance": "Neutral",
        "plausibility": "Insufficient Data",
        "narrative": "Unable to calculate reverse DCF due to invalid pricing or cash flow inputs.",
    }
