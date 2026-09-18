"""
AI-Powered Valuation Summary Generator
=======================================
Uses the Groq SDK (LLaMA 3.1 70B) to produce a professional
sell-side equity research note from the structured analysis data.
"""

import os
import logging
from typing import Any, Dict

logger = logging.getLogger("dcf-api.ai")

# ---------------------------------------------------------------------------
# Groq client (lazy-initialised so import doesn't fail without the key)
# ---------------------------------------------------------------------------
_groq_client = None

MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]


def _get_client():
    """Return a cached Groq client, creating it on first call."""
    global _groq_client
    if _groq_client is None:
        try:
            from groq import Groq

            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("GROQ_API_KEY environment variable is not set")
            _groq_client = Groq(api_key=api_key)
        except ImportError:
            raise RuntimeError(
                "The 'groq' package is not installed. "
                "Run: pip install groq"
            )
    return _groq_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(d: dict, *keys, default="N/A"):
    """Safely traverse nested dicts."""
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k, default)
        else:
            return default
    return cur


def _fmt_pct(val, default="N/A") -> str:
    if val is None or val == "N/A":
        return default
    try:
        return f"{float(val) * 100:.1f}%"
    except (TypeError, ValueError):
        return default


def _fmt_num(val, prefix="", decimals=2, default="N/A") -> str:
    if val is None or val == "N/A":
        return default
    try:
        return f"{prefix}{float(val):,.{decimals}f}"
    except (TypeError, ValueError):
        return default


def _fmt_large(val, prefix="", default="N/A") -> str:
    """Format large numbers into human-readable B/M notation."""
    if val is None or val == "N/A":
        return default
    try:
        v = float(val)
        if abs(v) >= 1e9:
            return f"{prefix}{v / 1e9:,.1f}B"
        if abs(v) >= 1e6:
            return f"{prefix}{v / 1e6:,.1f}M"
        return f"{prefix}{v:,.0f}"
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(data: Dict[str, Any]) -> str:
    """Construct a detailed system + user prompt for the LLM."""

    company = data.get("company", {})
    market_data = data.get("market_data", {})
    macro = data.get("macro", {})
    historicals = data.get("historicals", {})
    wacc = data.get("wacc", {})
    dcf = data.get("dcf_result", {})
    mc = data.get("monte_carlo", {})
    mc_stats = mc.get("stats", {})
    validation = data.get("validation", {})
    verdict = data.get("verdict", {})
    trends = data.get("trends", {})
    overrides = data.get("overrides_applied", {})

    sym = company.get("symbol", "$")
    currency = company.get("currency", "USD")

    # Build the data context block
    context = f"""
=== COMPANY ===
Name: {company.get('name', 'N/A')}
Ticker: {company.get('ticker', 'N/A')}
Market: {company.get('market', 'N/A')} ({currency})
Current Price: {_fmt_num(market_data.get('current_price'), prefix=sym)}
Market Cap: {_fmt_large(market_data.get('market_cap'), prefix=sym)}
Beta: {_fmt_num(market_data.get('beta'), decimals=2)}
Shares Outstanding: {_fmt_large(market_data.get('shares_outstanding'))}

=== MACRO ASSUMPTIONS ===
Risk-Free Rate: {_fmt_pct(macro.get('risk_free_rate'))} (Source: {macro.get('risk_free_source', 'N/A')})
Expected Market Return: {_fmt_pct(macro.get('market_return'))}
Tax Rate: {_fmt_pct(macro.get('tax_rate'))}
Benchmark: {macro.get('benchmark_index', 'N/A')}

=== WACC BREAKDOWN ===
Cost of Equity: {_fmt_pct(wacc.get('cost_of_equity'))}
Cost of Debt (after-tax): {_fmt_pct(wacc.get('cost_of_debt'))}
Equity Weight: {_fmt_pct(wacc.get('weight_equity'))}
Debt Weight: {_fmt_pct(wacc.get('weight_debt'))}
WACC: {_fmt_pct(wacc.get('wacc'))}
Total Debt: {_fmt_large(wacc.get('total_debt'), prefix=sym)}

=== HISTORICAL METRICS ({historicals.get('n_years', 'N/A')} years) ===
Avg Revenue Growth: {_fmt_pct(historicals.get('avg_rev_growth'))} (σ = {_fmt_pct(historicals.get('std_rev_growth'))})
Avg EBIT Margin: {_fmt_pct(historicals.get('avg_ebit_margin'))} (σ = {_fmt_pct(historicals.get('std_ebit_margin'))})
Avg CapEx (% of Rev): {_fmt_pct(historicals.get('avg_capex_pct'))}
Avg D&A (% of Rev): {_fmt_pct(historicals.get('avg_dna_pct'))}
Avg ΔNWC (% of Rev): {_fmt_pct(historicals.get('avg_dnwc_pct'))}

=== DCF RESULT ===
Implied Share Price: {_fmt_num(dcf.get('implied_price'), prefix=sym)}
Enterprise Value: {_fmt_large(dcf.get('enterprise_value'), prefix=sym)}
Terminal Value: {_fmt_large(dcf.get('terminal_value'), prefix=sym)}
PV of Terminal Value: {_fmt_large(dcf.get('pv_terminal_value'), prefix=sym)}
Equity Value: {_fmt_large(dcf.get('equity_value'), prefix=sym)}

=== MONTE CARLO SIMULATION ({mc.get('actual_iterations', 'N/A')} iterations) ===
Mean Price: {_fmt_num(mc_stats.get('mean'), prefix=sym)}
Median Price: {_fmt_num(mc_stats.get('median'), prefix=sym)}
5th Percentile: {_fmt_num(mc_stats.get('p5'), prefix=sym)}
25th Percentile: {_fmt_num(mc_stats.get('p25'), prefix=sym)}
75th Percentile: {_fmt_num(mc_stats.get('p75'), prefix=sym)}
95th Percentile: {_fmt_num(mc_stats.get('p95'), prefix=sym)}

=== CROSS-CHECK (EV/EBITDA) ===
Trailing EBITDA: {_fmt_large(validation.get('trailing_ebitda'), prefix=sym)}
Market EV: {_fmt_large(validation.get('market_ev'), prefix=sym)}
Market EV/EBITDA: {_fmt_num(validation.get('market_ev_ebitda'), decimals=1)}x
Model EV/EBITDA: {_fmt_num(validation.get('model_ev_ebitda'), decimals=1)}x
Multiple Gap: {_fmt_pct(validation.get('multiple_gap_pct'))}
Status: {validation.get('status', 'N/A')}

=== VERDICT ===
Signal: {verdict.get('verdict', 'N/A')}
Upside/Downside: {_fmt_pct(verdict.get('upside_pct'))}
Description: {verdict.get('description', 'N/A')}

=== TREND ANALYSIS ===
Revenue CAGR: {_fmt_pct(trends.get('revenue_cagr'))}
Margin Trend: {trends.get('margin_trend', 'N/A')}
CapEx Trend: {trends.get('capex_trend', 'N/A')}
"""

    # Overrides
    active_overrides = {
        k: v for k, v in (overrides or {}).items() if v is not None
    }
    if active_overrides:
        context += "\n=== USER OVERRIDES APPLIED ===\n"
        for k, v in active_overrides.items():
            context += f"  {k}: {v}\n"

    return context


from ai.prompts import SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_valuation_summary(analysis_data: Dict[str, Any]) -> str:
    """
    Generate a professional equity research note using Groq.

    Parameters
    ----------
    analysis_data : dict
        The full response dict from the /api/analyze endpoint.

    Returns
    -------
    str
        Markdown-formatted research note.
    """

    data_context = _build_prompt(analysis_data)

    user_prompt = f"""Write a professional equity research note based on the following
DCF valuation analysis. Use the exact numbers provided. Strictly follow the OUTPUT STRUCTURE defined in your system prompt.

{data_context}
"""

    client = _get_client()
    for model_name in MODELS:
        try:
            logger.info("Attempting AI summary generation with model: %s", model_name)
            chat_completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=3500,
                top_p=0.9,
            )
            content = chat_completion.choices[0].message.content
            if content and "headline_metrics" in content:
                logger.info("AI summary successfully generated with %s", model_name)
                return content
            logger.warning("Model %s returned incomplete JSON, trying next", model_name)
        except Exception as exc:
            logger.warning("Groq call failed for model %s: %s", model_name, exc)

    logger.error("All AI models failed, using institutional algorithmic fallback")
    return _build_fallback(analysis_data)


# ---------------------------------------------------------------------------
# Fallback (Algorithmic Synthesis)
# ---------------------------------------------------------------------------

def _build_fallback(data: Dict[str, Any]) -> str:
    """Return a fully structured JSON report matching the schema when the LLM is unavailable."""
    import json

    company = data.get("company", {})
    ticker = company.get("ticker", "N/A")
    name = company.get("name", ticker)
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    mc = data.get("monte_carlo", {})
    mc_stats = mc.get("stats", {})
    wacc = data.get("wacc", {})
    validation = data.get("validation", {})
    verdict = data.get("verdict", {})
    historicals = data.get("historicals", {})
    sym = company.get("symbol", "$")
    currency = company.get("currency", "USD")

    current_price = float(market_data.get("current_price", 0.0))
    dcf_value = float(dcf.get("implied_price", 0.0))
    mc_median = float(mc_stats.get("median", 0.0))
    mc_p5 = float(mc_stats.get("p5", 0.0))
    mc_p25 = float(mc_stats.get("p25", 0.0))
    mc_p75 = float(mc_stats.get("p75", 0.0))
    mc_p95 = float(mc_stats.get("p95", 0.0))

    dcf_upside = ((dcf_value / current_price) - 1.0) * 100 if current_price > 0 else 0.0
    mc_upside = ((mc_median / current_price) - 1.0) * 100 if current_price > 0 else 0.0

    fallback_obj = {
        "company": name,
        "ticker": ticker,
        "currency": currency,
        "headline_metrics": {
            "current_price": current_price,
            "dcf_value": dcf_value,
            "monte_carlo_median": mc_median,
            "monte_carlo_p5": mc_p5,
            "monte_carlo_p25": mc_p25,
            "monte_carlo_p75": mc_p75,
            "monte_carlo_p95": mc_p95,
            "dcf_upside_percent": dcf_upside,
            "monte_carlo_upside_percent": mc_upside,
        },
        "executive_summary": {
            "overview": f"{name} ({ticker}) fundamental valuation synthesis. DCF model yields fair value of {sym}{dcf_value:.2f} compared to current market price of {sym}{current_price:.2f} ({dcf_upside:+.1f}% implied gap).",
            "valuation_gap": f"The stock trades at a {abs(dcf_upside):.1f}% {'discount' if dcf_upside >= 0 else 'premium'} to its fundamental DCF intrinsic value.",
            "primary_driver": f"Cost of Capital at {_fmt_pct(wacc.get('wacc'))} and baseline growth rate of {_fmt_pct(historicals.get('avg_rev_growth'))}.",
            "primary_risk": f"Simulation downside percentile (P5) boundary estimated at {sym}{mc_p5:.2f}.",
            "key_takeaway": f"Model verdict: {verdict.get('verdict', 'N/A')} — {verdict.get('description', '')}.",
        },
        "market_pricing": {
            "current_valuation": f"Market price of {sym}{current_price:.2f} reflects market capitalization of {_fmt_large(market_data.get('market_cap'), prefix=sym)}.",
            "what_market_price_implies": f"Current market pricing reflects a discount rate / growth equilibrium near {_fmt_pct(wacc.get('wacc'))}.",
            "growth_expectation": f"Historical revenue CAGR has been {_fmt_pct(historicals.get('avg_rev_growth'))}.",
            "profitability_expectation": f"Operating margin baseline sits at {_fmt_pct(historicals.get('avg_ebit_margin'))}.",
            "market_vs_model": f"Model implied fair value is {sym}{dcf_value:.2f} ({dcf_upside:+.1f}% vs market).",
        },
        "dcf_analysis": {
            "fair_value": dcf_value,
            "revenue_growth": {
                "forecast_cagr": float(historicals.get("avg_rev_growth") or 0.10) * 100,
                "historical_cagr": float(historicals.get("avg_rev_growth") or 0.10) * 100,
                "interpretation": f"Projected baseline growth aligns with historical trajectory of {_fmt_pct(historicals.get('avg_rev_growth'))}.",
            },
            "margin": {
                "historical_margin": float(historicals.get("avg_ebit_margin") or 0.15) * 100,
                "forecast_margin": float(historicals.get("avg_ebit_margin") or 0.15) * 100,
                "change_percentage_points": 0.0,
                "interpretation": f"Operating margins modeled at {_fmt_pct(historicals.get('avg_ebit_margin'))}.",
            },
            "free_cash_flow": {
                "trend": "Stable projected multi-stage cash flow profile.",
                "capex": f"Average CapEx intensity at {_fmt_pct(historicals.get('avg_capex_pct'))}.",
                "working_capital": f"Working capital intensity at {_fmt_pct(historicals.get('avg_dnwc_pct'))}.",
                "interpretation": "Cash flow generation supports intrinsic valuation.",
            },
            "wacc": {
                "value": float(wacc.get("wacc") or 0.10) * 100,
                "cost_of_equity": float(wacc.get("cost_of_equity") or 0.10) * 100,
                "cost_of_debt": float(wacc.get("cost_of_debt") or 0.05) * 100,
                "interpretation": f"Discount rate of {_fmt_pct(wacc.get('wacc'))} reflects systemic risk and market profile.",
            },
            "terminal_value": {
                "value": float(dcf.get("terminal_value", 0.0)),
                "percent_of_enterprise_value": float((dcf.get("pv_terminal_value", 0.0) / dcf.get("enterprise_value", 1.0)) * 100) if dcf.get("enterprise_value", 0.0) > 0 else 70.0,
                "interpretation": "Terminal value reflects steady-state long-run macroeconomic growth rate.",
            },
            "overall_interpretation": f"Fundamental valuation indicates a {verdict.get('verdict', 'HOLD')} recommendation with {dcf_upside:+.1f}% upside.",
        },
        "monte_carlo_analysis": {
            "simulation_count": mc.get("actual_iterations", 10000),
            "median": mc_median,
            "p5": mc_p5,
            "p25": mc_p25,
            "p75": mc_p75,
            "p95": mc_p95,
            "distribution_interpretation": f"Simulated 10,000 randomized parameter sets yield a median value of {sym}{mc_median:.2f} with 90% confidence range between {sym}{mc_p5:.2f} and {sym}{mc_p95:.2f}.",
            "downside_case": f"5th percentile downside floor stands at {sym}{mc_p5:.2f}.",
            "base_case": f"Median expected outcome is {sym}{mc_median:.2f}.",
            "upside_case": f"95th percentile bull case reaches {sym}{mc_p95:.2f}.",
            "current_price_position": f"Current price {sym}{current_price:.2f} is positioned relative to median at {mc_upside:+.1f}%.",
        },
        "key_drivers": [
            {
                "driver": "Top-line Revenue Growth",
                "assumption": f"{_fmt_pct(historicals.get('avg_rev_growth'))} CAGR",
                "valuation_impact": "Directly drives enterprise cash generation.",
                "what_to_monitor": "Volume and pricing trends in core segments.",
            },
            {
                "driver": "Operating Profitability",
                "assumption": f"{_fmt_pct(historicals.get('avg_ebit_margin'))} margin",
                "valuation_impact": "Converts revenue to operational cash flow.",
                "what_to_monitor": "Input costs and gross margin resilience.",
            },
            {
                "driver": "Discount Rate (Cost of Capital)",
                "assumption": f"{_fmt_pct(wacc.get('wacc'))} discount rate",
                "valuation_impact": "Present value factor for projected cash flows.",
                "what_to_monitor": "Benchmark 10Y bond yield and equity risk premium.",
            },
        ],
        "risks": [
            {
                "risk": "Macroeconomic & Industry Slowdown",
                "severity": "Medium",
                "mechanism": "Broader economic softening could depress revenue growth.",
                "indicator_to_monitor": "GDP growth rates and industry demand data.",
            },
            {
                "risk": "Cost Inflation & Margin Pressure",
                "severity": "Medium",
                "mechanism": "Inability to pass through cost increases impairs margin conversion.",
                "indicator_to_monitor": "Quarterly operating margin trends.",
            },
        ],
        "final_synopsis": {
            "paragraph": f"Based on multi-stage DCF modeling and Monte Carlo simulation, {name} presents a fair value estimate of {sym}{dcf_value:.2f} (median outcome {sym}{mc_median:.2f}) versus current market trading price of {sym}{current_price:.2f}, supporting a '{verdict.get('verdict', 'HOLD')}' stance.",
            "monitoring_points": [
                "Quarterly revenue momentum relative to baseline projections",
                "EBITDA margin conversion and free cash flow generation",
                "Yield curve movements impacting discount rate assumptions",
            ],
        },
    }
    return json.dumps(fallback_obj)

