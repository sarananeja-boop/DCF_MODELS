"""
AI-Powered Institutional Valuation Summary Generator
===================================================
Produces a Wall Street sell-side equity research initiation note and
Expectations Investing memorandum using Groq and the quantitative DCF engine.
"""

import json
import logging
import os
import re
from typing import Any, Dict

logger = logging.getLogger("dcf-api.ai")

# ---------------------------------------------------------------------------
# Groq client (lazy-initialised so import doesn't fail without the key)
# ---------------------------------------------------------------------------
_groq_client = None

MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]


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


def _clean_point_labels(text: str) -> str:
    """Strip lazy 'Point 1:', 'Point 2:' AI artifacts."""
    if not isinstance(text, str):
        return text
    return re.sub(r'^(Point\s*\d+\s*:\s*|\d+\.\s*)', '', text.strip(), flags=re.IGNORECASE)


def _resolve_terminal_and_macro_anchors(data: Dict[str, Any]) -> tuple:
    """Consistently resolve sovereign macro anchors and terminal growth parameters."""
    company = data.get("company", {})
    ticker = company.get("ticker", "")
    market = company.get("market") or ("IN" if str(ticker).endswith((".NS", ".BO")) else "US")
    macro = data.get("macro", {})
    dcf = data.get("dcf_result", {})
    overrides = data.get("overrides_applied", {})

    term_g = macro.get("terminal_growth")
    if term_g is None:
        term_g = dcf.get("effective_terminal_growth")
    if term_g is None:
        term_g = dcf.get("terminal_growth")
    if term_g is None:
        term_g = overrides.get("terminal_growth")
    if term_g is None:
        term_g = 0.050 if market == "IN" else 0.025

    eff_term_g = dcf.get("effective_terminal_growth", term_g)
    gdp_anchor = macro.get("gdp_growth", 0.065 if market == "IN" else 0.025)
    tv_capped = bool(dcf.get("terminal_growth_capped", False))
    return market, term_g, eff_term_g, gdp_anchor, tv_capped


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
    diagnostics = data.get("diagnostics", {})
    overrides = data.get("overrides_applied", {})

    sym = company.get("symbol", "$")
    currency = company.get("currency", "USD")
    market, modeled_term_g, eff_term_g, gdp_anchor, tv_capped = _resolve_terminal_and_macro_anchors(data)

    # Reverse DCF data (expectations investing)
    rev_dcf = data.get("reverse_dcf", {})
    if not rev_dcf:
        from engine.reverse_dcf import calculate_reverse_dcf
        try:
            rev_dcf = calculate_reverse_dcf(
                current_price=market_data.get("current_price", 0.0),
                model_fair_value=dcf.get("implied_price", 0.0),
                base_start_growth=float(diagnostics.get("default_growth", historicals.get("avg_rev_growth", 0.10))),
                base_target_margin=float(diagnostics.get("default_margin", historicals.get("avg_ebit_margin", 0.15))),
                discount_rate=float(diagnostics.get("default_wacc", wacc.get("wacc", 0.10))),
                metrics=historicals,
                stock_data=company,
                wacc_data=wacc,
                terminal_growth=modeled_term_g,
                is_equity_model=company.get("is_equity_model", False),
            )
        except Exception as exc:
            logger.debug("On-the-fly reverse DCF calculation failed: %s", exc)
            rev_dcf = {}

    desc = company.get("description", "")
    if len(desc) > 2200:
        desc = desc[:2200] + "..."

    # Build the rich data context block
    context = f"""
=== COMPANY PROFILE & COMMERCIAL OPERATIONS ===
Name: {company.get('name', 'N/A')}
Ticker: {company.get('ticker', 'N/A')}
Market: {company.get('market', 'N/A')} ({currency})
Sector: {company.get('sector', 'N/A')}
Industry: {company.get('industry', 'N/A')}
Country: {company.get('country', 'N/A')} | City: {company.get('city', 'N/A')}
Full-Time Employees: {company.get('employees', 'N/A')}
Website: {company.get('website', 'N/A')}

BUSINESS DESCRIPTION & OPERATING SEGMENTS:
{desc if desc else "Commercial enterprise operating in " + str(company.get('industry', 'general industry')) + "."}

=== MARKET PRICING & VALUATION METRICS ===
Current Trading Price: {_fmt_num(market_data.get('current_price'), prefix=sym)}
Market Capitalization: {_fmt_large(market_data.get('market_cap'), prefix=sym)}
Shares Outstanding: {_fmt_large(market_data.get('shares_outstanding'))}
Beta: {_fmt_num(market_data.get('beta'), decimals=2)}
Trailing P/E: {_fmt_num(market_data.get('trailing_pe'), decimals=1)}x
Forward P/E: {_fmt_num(market_data.get('forward_pe'), decimals=1)}x
Price / Sales: {_fmt_num(market_data.get('price_to_sales'), decimals=2)}x

=== EXPECTATIONS INVESTING (REVERSE DCF ANALYSIS) ===
Current Market Price: {_fmt_num(rev_dcf.get('current_price', market_data.get('current_price')), prefix=sym)}
Model Fundamental Fair Value: {_fmt_num(rev_dcf.get('model_fair_value', dcf.get('implied_price')), prefix=sym)}
Valuation Gap vs Market: {_fmt_pct(rev_dcf.get('valuation_gap_pct') / 100.0 if rev_dcf.get('valuation_gap_pct') is not None else 0.0)}
Model Baseline Growth CAGR: {_fmt_pct(rev_dcf.get('base_growth', historicals.get('avg_rev_growth')))}
Market-Implied Growth Hurdle Rate: {_fmt_pct(rev_dcf.get('market_implied_growth'))}
Growth Hurdle Gap: {rev_dcf.get('growth_hurdle_gap_bps', 0.0):+.0f} bps
Market-Implied Operating Margin: {_fmt_pct(rev_dcf.get('market_implied_margin')) if rev_dcf.get('market_implied_margin') is not None else "Unachievable via margin alone"}
Market-Implied Cost of Capital (WACC): {_fmt_pct(rev_dcf.get('market_implied_wacc')) if rev_dcf.get('market_implied_wacc') is not None else "N/A"}
Expectations Stance: {rev_dcf.get('stance', 'Neutral')}
Plausibility Assessment: {rev_dcf.get('plausibility', 'Fairly Valued')}
Reverse DCF Narrative: {rev_dcf.get('narrative', 'N/A')}

=== FUNDAMENTAL DCF VALUATION BREAKDOWN ===
Implied Intrinsic Share Price: {_fmt_num(dcf.get('implied_price'), prefix=sym)}
Enterprise Value: {_fmt_large(dcf.get('enterprise_value'), prefix=sym)}
PV of Explicit 5-Yr Cash Flows: {_fmt_large(dcf.get('pv_ufcf'), prefix=sym)}
PV of Terminal Value: {_fmt_large(dcf.get('pv_terminal_value'), prefix=sym)}
Terminal Value Share of Enterprise Value: {_fmt_pct((dcf.get('pv_terminal_value', 0.0) / dcf.get('enterprise_value', 1.0)) if dcf.get('enterprise_value') else 0.70)}
Damodaran Exit Multiple Implied Price: {_fmt_num(dcf.get('exit_implied_price'), prefix=sym)}
Benchmark Exit Multiple: {_fmt_num(dcf.get('benchmark_exit_multiple'), decimals=1)}x EV/EBITDA
Implied Perpetual Exit Multiple: {_fmt_num(dcf.get('implied_exit_multiple'), decimals=1)}x EV/EBITDA

=== TERMINAL VALUE & PERPETUAL MACRO ASSUMPTIONS ===
Modeled Perpetual Terminal Growth Rate (g): {_fmt_pct(modeled_term_g)} (MANDATORY: You must cite this exact modeled rate of {_fmt_pct(modeled_term_g)})
Effective Modeled Terminal Growth: {_fmt_pct(eff_term_g)}
Terminal Growth Capped by Model Bounds: {'YES (constrained to preserve minimum spread)' if tv_capped else 'NO'}
Sovereign Long-Run Nominal GDP Growth Anchor: {_fmt_pct(gdp_anchor)} (Macro benchmark cap for {company.get('country', 'domestic economy')})
Terminal Value Share of Enterprise Value: {_fmt_pct((dcf.get('pv_terminal_value', 0.0) / dcf.get('enterprise_value', 1.0)) if dcf.get('enterprise_value') else 0.70)}
Implied Perpetual Exit Multiple: {_fmt_num(dcf.get('implied_exit_multiple'), decimals=1)}x EV/EBITDA
Benchmark Sector Exit Multiple: {_fmt_num(dcf.get('benchmark_exit_multiple'), decimals=1)}x EV/EBITDA

=== COST OF CAPITAL (WACC / Ke) BREAKDOWN ===
Risk-Free Rate: {_fmt_pct(macro.get('risk_free_rate'))} ({macro.get('risk_free_source', 'Sovereign 10Y Benchmark')})
Expected Market Return: {_fmt_pct(macro.get('market_return'))}
Cost of Equity: {_fmt_pct(wacc.get('cost_of_equity'))}
Pre-Tax Cost of Debt: {_fmt_pct(wacc.get('pretax_cost_of_debt'))}
After-Tax Cost of Debt: {_fmt_pct(wacc.get('cost_of_debt'))}
Capital Weights: Equity {_fmt_pct(wacc.get('weight_equity'))} | Debt {_fmt_pct(wacc.get('weight_debt'))}
WACC (Discount Rate): {_fmt_pct(wacc.get('wacc'))}
Synthetic Credit Rating: {wacc.get('synthetic_rating', 'A')} (Default Spread: {_fmt_pct(wacc.get('default_spread'))})
Interest Coverage Ratio: {_fmt_num(wacc.get('interest_coverage'), decimals=1)}x

=== HISTORICAL OPERATING PERFORMANCE ({historicals.get('n_years', 'N/A')} years) ===
Historical Avg Revenue Growth: {_fmt_pct(historicals.get('avg_rev_growth'))} (Volatility σ = {_fmt_pct(historicals.get('std_rev_growth'))})
Historical Avg EBIT Margin: {_fmt_pct(historicals.get('avg_ebit_margin'))} (Volatility σ = {_fmt_pct(historicals.get('std_ebit_margin'))})
Historical Avg Gross Margin: {_fmt_pct(diagnostics.get('avg_gross_margin', historicals.get('avg_gross_margin')))}
Avg CapEx (% of Revenue): {_fmt_pct(historicals.get('avg_capex_pct'))}
Avg D&A (% of Revenue): {_fmt_pct(historicals.get('avg_dna_pct'))}
Avg ΔNWC (% of Revenue): {_fmt_pct(historicals.get('avg_dnwc_pct'))}
Avg Return on Equity (ROE): {_fmt_pct(historicals.get('avg_roe'))}
Avg Dividend Payout Ratio: {_fmt_pct(historicals.get('avg_payout'))}

=== MONTE CARLO PROBABILITY SIMULATION (10,000 Runs) ===
Mean Simulated Price: {_fmt_num(mc_stats.get('mean'), prefix=sym)}
Median Price (P50): {_fmt_num(mc_stats.get('median'), prefix=sym)}
5th Percentile (Severe Bear Floor): {_fmt_num(mc_stats.get('p5'), prefix=sym)}
25th Percentile (Conservative Case): {_fmt_num(mc_stats.get('p25'), prefix=sym)}
75th Percentile (Optimistic Case): {_fmt_num(mc_stats.get('p75'), prefix=sym)}
95th Percentile (Aggressive Bull Ceiling): {_fmt_num(mc_stats.get('p95'), prefix=sym)}
Probability of Upside (Simulated > CMP): {_fmt_pct(mc_stats.get('prob_upside', 0.0))}

=== MODEL RELATIVE CROSS-CHECK ===
Trailing EBITDA: {_fmt_large(validation.get('trailing_ebitda'), prefix=sym)}
Market EV/EBITDA: {_fmt_num(validation.get('market_ev_ebitda'), decimals=1)}x
Model Implied EV/EBITDA: {_fmt_num(validation.get('model_ev_ebitda'), decimals=1)}x
Multiple Gap: {_fmt_pct(validation.get('multiple_gap_pct'))} (Status: {validation.get('status', 'N/A')})
"""

    if dcf.get("justified_pb"):
        context += f"\n=== BANK DDM / P/B CROSS-CHECK ===\n"
        context += f"Justified P/B Multiple: {_fmt_num(dcf.get('justified_pb'), decimals=2)}x\n"
        context += f"Justified Share Price: {_fmt_num(dcf.get('justified_price'), prefix=sym)}\n"
        context += f"Book Value Per Share: {_fmt_num(diagnostics.get('bvps'), prefix=sym)}\n"

    # Overrides
    active_overrides = {
        k: v for k, v in (overrides or {}).items() if v is not None
    }
    if active_overrides:
        context += "\n=== USER MODEL OVERRIDES ACTIVE ===\n"
        for k, v in active_overrides.items():
            context += f"  {k}: {v}\n"

    return context


from ai.prompts import SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_valuation_summary(analysis_data: Dict[str, Any]) -> str:
    """
    Generate an institutional equity research valuation memorandum using Groq.

    Parameters
    ----------
    analysis_data : dict
        The full response dict from the /api/analyze endpoint.

    Returns
    -------
    str
        JSON-formatted institutional equity research memorandum.
    """

    market, modeled_term_g, eff_term_g, gdp_anchor, tv_capped = _resolve_terminal_and_macro_anchors(analysis_data)
    data_context = _build_prompt(analysis_data)

    company_name = analysis_data.get("company", {}).get("name", "the company")
    ticker = analysis_data.get("company", {}).get("ticker", "TICKER")

    user_prompt = f"""Generate an authoritative Institutional Equity Research Memorandum for {company_name} ({ticker}).

COMPLIANCE & MODEL INTEGRITY MANDATE:
- Do NOT output 'BUY', 'SELL', 'HOLD', or 'STRONG BUY/SELL'. Use descriptive valuation posture only (e.g. 'Trading at Premium to DCF Fair Value').
- Do NOT use 'Point 1', 'Point 2', or 'Point 3'. Use named thematic titles for every analytical pillar.
- Write in flowing, continuous, highly sophisticated institutional prose.
- TERMINAL VALUE FIDELITY: You MUST state the exact Perpetual Terminal Growth Rate ({_fmt_pct(modeled_term_g)}) from the context. NEVER assume or state 2.5% for an Indian stock when the modeled rate is {_fmt_pct(modeled_term_g)}. Anchor your perpetual growth discussion relative to the sovereign nominal GDP growth anchor ({_fmt_pct(gdp_anchor)}).
- Provide deep analysis of the business segments, revenue drivers, and the Reverse DCF expectations gap.

Strictly adhere to the JSON schema defined in your system prompt.

{data_context}
"""

    try:
        client = _get_client()
        for model_name in MODELS:
            try:
                logger.info("Generating institutional valuation summary with model: %s", model_name)
                chat_completion = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.25,
                    max_tokens=4000,
                    top_p=0.9,
                )
                content = chat_completion.choices[0].message.content
                if content and "headline_metrics" in content:
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and "headline_metrics" in parsed:
                            enriched = _enrich_and_validate_report(parsed, analysis_data)
                            logger.info("Institutional AI research note successfully compiled with %s", model_name)
                            return json.dumps(enriched)
                    except Exception as parse_err:
                        logger.warning("Failed to parse LLM JSON with %s: %s", model_name, parse_err)

                logger.warning("Model %s returned incomplete JSON, trying next model", model_name)
            except Exception as exc:
                logger.warning("Groq call failed for model %s: %s", model_name, exc)
    except Exception as client_err:
        logger.warning("Groq client initialization or connectivity failed: %s", client_err)

    logger.error("All AI models failed or unavailable, building algorithmic institutional memorandum fallback")
    return _build_fallback(analysis_data)


def _enrich_and_validate_report(report: dict, analysis_data: dict) -> dict:
    """Guarantee compliance, scrub forbidden terms, and ensure all institutional fields are populated."""
    company = analysis_data.get("company", {})
    market_data = analysis_data.get("market_data", {})
    dcf = analysis_data.get("dcf_result", {})
    mc_stats = analysis_data.get("monte_carlo", {}).get("stats", {})
    wacc = analysis_data.get("wacc", {})
    historicals = analysis_data.get("historicals", {})
    rev_dcf = analysis_data.get("reverse_dcf", {})
    sym = company.get("symbol", "$")

    current_price = float(market_data.get("current_price", 0.0))
    dcf_value = float(dcf.get("implied_price", 0.0))

    # Enforce canonical company identity and trading currency from model payload
    if company.get("name"):
        report["company"] = company["name"]
    if company.get("ticker"):
        report["ticker"] = company["ticker"]
    report["currency"] = company.get("currency", report.get("currency", "USD"))

    # Guarantee headline metrics
    if not report.get("headline_metrics"):
        report["headline_metrics"] = {}
    hl = report["headline_metrics"]
    hl["current_price"] = current_price
    hl["dcf_value"] = dcf_value
    hl["monte_carlo_median"] = float(mc_stats.get("median", dcf_value))
    hl["monte_carlo_p5"] = float(mc_stats.get("p5", dcf_value * 0.7))
    hl["monte_carlo_p25"] = float(mc_stats.get("p25", dcf_value * 0.85))
    hl["monte_carlo_p75"] = float(mc_stats.get("p75", dcf_value * 1.15))
    hl["monte_carlo_p95"] = float(mc_stats.get("p95", dcf_value * 1.4))
    hl["dcf_upside_percent"] = round(((dcf_value / current_price) - 1.0) * 100.0, 1) if current_price > 0 else 0.0
    hl["monte_carlo_upside_percent"] = round(((hl["monte_carlo_median"] / current_price) - 1.0) * 100.0, 1) if current_price > 0 else 0.0

    # COMPLIANCE: Scrub any recommendation ('SELL', 'BUY', etc.) and establish descriptive posture
    hl.pop("recommendation", None)
    dcf_upside = hl["dcf_upside_percent"]
    if dcf_upside <= -35.0:
        posture = "TRADING AT SIGNIFICANT PREMIUM TO DCF"
    elif dcf_upside < -10.0:
        posture = "TRADING AT PREMIUM TO DCF"
    elif dcf_upside <= 15.0:
        posture = "VALUED WITHIN DCF FAIR VALUE RANGE"
    elif dcf_upside <= 35.0:
        posture = "TRADING AT DISCOUNT TO DCF"
    else:
        posture = "TRADING AT SIGNIFICANT DISCOUNT TO DCF"
    hl["valuation_posture"] = posture

    # Clean executive summary
    exec_sum = report.get("executive_summary", {})
    if not isinstance(exec_sum, dict):
        exec_sum = {}
        report["executive_summary"] = exec_sum

    if not exec_sum.get("thesis_narrative"):
        exec_sum["thesis_narrative"] = (
            f"Fundamental multi-stage discounted cash flow analysis for {company.get('name', 'the company')} ({company.get('ticker')}) "
            f"establishes an intrinsic fair value of {sym}{dcf_value:.2f} per share against current market trading levels of "
            f"{sym}{current_price:.2f}, indicating an implied valuation spread of {dcf_upside:+.1f}%. "
            f"This valuation divergence is anchored in the disconnect between normalized historical delivery ({_fmt_pct(historicals.get('avg_rev_growth'))} CAGR) "
            f"and the operational hurdle rate embedded in current market prices."
        )

    # Clean variant perception and strip lazy 'Point 1/2/3' prefixes
    vp = report.get("variant_perception", {})
    if not isinstance(vp, dict):
        vp = {}
        report["variant_perception"] = vp

    growth_gap = rev_dcf.get("growth_hurdle_gap_bps", 0.0)
    gap_dir = "premium" if growth_gap > 0 else "discount"
    if not vp.get("divergence_headline"):
        vp["divergence_headline"] = f"Market Pricing Demands {abs(growth_gap):.0f} bps Growth {gap_dir.capitalize()} Beyond Fundamental Capacity"

    # Scrub structural_pillars
    pillars = vp.get("structural_pillars") or []
    if not pillars and vp.get("thesis_points"):
        # Convert legacy thesis_points
        pillars = []
        for p in vp.get("thesis_points", []):
            cleaned = _clean_point_labels(p)
            parts = cleaned.split(":", 1)
            if len(parts) == 2:
                pillars.append({"theme": parts[0].strip(), "analysis": parts[1].strip()})
            else:
                pillars.append({"theme": "Valuation & Cash Flow Disconnect", "analysis": cleaned})
    
    if not pillars:
        pillars = [
            {
                "theme": "Top-Line Revenue Durability vs. Market Hurdle",
                "analysis": f"Current market price requires a sustained {rev_dcf.get('market_implied_growth', 0.1)*100:.1f}% growth rate, diverging from the historical baseline of {_fmt_pct(historicals.get('avg_rev_growth'))}.",
            },
            {
                "theme": "Operating Profitability & Margin Ceilings",
                "analysis": f"Operating margin modeled at steady-state {_fmt_pct(historicals.get('avg_ebit_margin'))} reflects established cost structure and pass-through limits.",
            },
            {
                "theme": "Capital Allocation & Reinvestment Efficiency",
                "analysis": f"Historical CapEx intensity of {_fmt_pct(historicals.get('avg_capex_pct'))} and working capital requirements govern sustainable cash flow generation.",
            },
        ]
    else:
        for item in pillars:
            if isinstance(item, dict):
                item["theme"] = _clean_point_labels(item.get("theme", ""))
                item["analysis"] = _clean_point_labels(item.get("analysis", ""))

    vp["structural_pillars"] = pillars

    # Clean expectations investing
    if not report.get("expectations_investing") or not report["expectations_investing"].get("plausibility_assessment"):
        report["expectations_investing"] = {
            "market_implied_growth_cagr": float(rev_dcf.get("market_implied_growth", historicals.get("avg_rev_growth", 0.10))) * 100.0,
            "baseline_growth_cagr": float(rev_dcf.get("base_growth", historicals.get("avg_rev_growth", 0.10))) * 100.0,
            "growth_hurdle_gap_bps": float(rev_dcf.get("growth_hurdle_gap_bps", 0.0)),
            "market_implied_margin": f"{rev_dcf.get('market_implied_margin') * 100:.1f}%" if rev_dcf.get("market_implied_margin") is not None else "Unachievable via margin alone",
            "market_implied_wacc": f"{rev_dcf.get('market_implied_wacc') * 100:.1f}%" if rev_dcf.get("market_implied_wacc") is not None else "N/A",
            "hurdle_classification": rev_dcf.get("stance", "Consensus Aligned"),
            "plausibility_assessment": rev_dcf.get("narrative", f"Current market pricing demands a {rev_dcf.get('market_implied_growth', 0.1)*100:.1f}% CAGR hurdle."),
        }

    # Map dcf_analysis to dcf_cash_flow_bridge for backward/forward compatibility
    if not report.get("dcf_cash_flow_bridge") and report.get("dcf_analysis"):
        report["dcf_cash_flow_bridge"] = report["dcf_analysis"]
    elif not report.get("dcf_analysis") and report.get("dcf_cash_flow_bridge"):
        report["dcf_analysis"] = report["dcf_cash_flow_bridge"]

    # Map scenarios to asymmetric_scenarios
    if not report.get("asymmetric_scenarios") and report.get("scenarios"):
        report["asymmetric_scenarios"] = report["scenarios"]
    elif not report.get("scenarios") and report.get("asymmetric_scenarios"):
        report["scenarios"] = report["asymmetric_scenarios"]

    # Map risks to downside_risks
    if not report.get("downside_risks") and report.get("risks"):
        report["downside_risks"] = report["risks"]
    elif not report.get("risks") and report.get("downside_risks"):
        report["risks"] = report["downside_risks"]

    # Map quarterly_monitoring_signposts
    if not report.get("quarterly_monitoring_signposts") and report.get("thesis_invalidation_and_monitoring"):
        report["quarterly_monitoring_signposts"] = report["thesis_invalidation_and_monitoring"]

    # Final synthesis
    if not report.get("final_synthesis"):
        syn = report.get("final_synopsis", {})
        if isinstance(syn, dict) and syn.get("paragraph"):
            report["final_synthesis"] = syn["paragraph"]
        else:
            report["final_synthesis"] = (
                f"In conclusion, DCF intrinsic modeling establishes an implied fair value of {sym}{dcf_value:.2f} for {company.get('name', 'the company')}, "
                f"positioning current market trading levels ({sym}{current_price:.2f}) at a {dcf_upside:+.1f}% valuation spread. "
                f"Reverse DCF expectations modeling reveals that the market is discounting an aggressive operational hurdle of "
                f"{rev_dcf.get('market_implied_growth', 0.1)*100:.1f}% CAGR. Investors should closely monitor quarterly volume momentum and operating margin conversion."
            )

    # -----------------------------------------------------------------------
    # Enforce terminal growth and macro anchor fidelity across all text fields
    # -----------------------------------------------------------------------
    market, modeled_term_g, eff_term_g, gdp_anchor, tv_capped = _resolve_terminal_and_macro_anchors(analysis_data)
    g_str = _fmt_pct(modeled_term_g)
    gdp_str = _fmt_pct(gdp_anchor)

    def _sanitize_macro_text(val: Any) -> Any:
        if isinstance(val, str):
            res = val
            if market == "IN" or abs(modeled_term_g - 0.025) > 0.005:
                # Replace hallucinated 2.5% perpetual/terminal growth references with actual modeled terminal rate
                res = re.sub(
                    r'2\.5%\s*(?:perpetual\s*growth\s*rate|terminal\s*growth\s*rate|perpetual\s*growth|terminal\s*growth)',
                    f'{g_str} perpetual growth rate',
                    res,
                    flags=re.IGNORECASE,
                )
                res = re.sub(r'uses\s+a\s+2\.5%', f'uses a {g_str}', res, flags=re.IGNORECASE)
                res = re.sub(
                    r'consistent\s+with\s+India[\'’]?s\s+long[- ]run\s+GDP\s+growth',
                    f'anchored against India’s long-run nominal GDP growth trajectory (~{gdp_str})',
                    res,
                    flags=re.IGNORECASE,
                )
                res = re.sub(
                    r'India[\'’]?s\s+long[- ]run\s+GDP\s+growth\s*(?:of\s*2\.5%|at\s*2\.5%)',
                    f'India’s long-run nominal GDP growth of ~{gdp_str}',
                    res,
                    flags=re.IGNORECASE,
                )
            return res
        elif isinstance(val, dict):
            return {k: _sanitize_macro_text(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [_sanitize_macro_text(item) for item in val]
        return val

    report = _sanitize_macro_text(report)

    return report


# ---------------------------------------------------------------------------
# Fallback (Algorithmic Institutional Memorandum Synthesis)
# ---------------------------------------------------------------------------

def _build_fallback(data: Dict[str, Any]) -> str:
    """Return a complete institutional equity research note when the LLM is unavailable."""
    company = data.get("company", {})
    ticker = company.get("ticker", "N/A")
    name = company.get("name", ticker)
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    mc = data.get("monte_carlo", {})
    mc_stats = mc.get("stats", {})
    wacc = data.get("wacc", {})
    historicals = data.get("historicals", {})
    sym = company.get("symbol", "$")
    currency = company.get("currency", "USD")
    market, term_g, eff_term_g, gdp_anchor, tv_capped = _resolve_terminal_and_macro_anchors(data)

    # Reverse DCF
    rev_dcf = data.get("reverse_dcf", {})
    if not rev_dcf:
        from engine.reverse_dcf import calculate_reverse_dcf
        try:
            rev_dcf = calculate_reverse_dcf(
                current_price=market_data.get("current_price", 0.0),
                model_fair_value=dcf.get("implied_price", 0.0),
                base_start_growth=float(historicals.get("avg_rev_growth", 0.10)),
                base_target_margin=float(historicals.get("avg_ebit_margin", 0.15)),
                discount_rate=float(wacc.get("wacc", 0.10)),
                metrics=historicals,
                stock_data=company,
                wacc_data=wacc,
                terminal_growth=term_g,
                is_equity_model=company.get("is_equity_model", False),
            )
        except Exception:
            rev_dcf = {}

    current_price = float(market_data.get("current_price", 0.0))
    dcf_value = float(dcf.get("implied_price", 0.0))
    mc_median = float(mc_stats.get("median", dcf_value))
    mc_p5 = float(mc_stats.get("p5", dcf_value * 0.70))
    mc_p25 = float(mc_stats.get("p25", dcf_value * 0.85))
    mc_p75 = float(mc_stats.get("p75", dcf_value * 1.15))
    mc_p95 = float(mc_stats.get("p95", dcf_value * 1.45))

    dcf_upside = ((dcf_value / current_price) - 1.0) * 100 if current_price > 0 else 0.0
    mc_upside = ((mc_median / current_price) - 1.0) * 100 if current_price > 0 else 0.0

    growth_hurdle_gap_bps = float(rev_dcf.get("growth_hurdle_gap_bps", 0.0))
    growth_gap_bps = growth_hurdle_gap_bps
    market_implied_g = float(rev_dcf.get("market_implied_growth", historicals.get("avg_rev_growth", 0.10)))

    if dcf_upside <= -35.0:
        posture = "TRADING AT SIGNIFICANT PREMIUM TO DCF"
    elif dcf_upside < -10.0:
        posture = "TRADING AT PREMIUM TO DCF"
    elif dcf_upside <= 15.0:
        posture = "VALUED WITHIN DCF FAIR VALUE RANGE"
    elif dcf_upside <= 35.0:
        posture = "TRADING AT DISCOUNT TO DCF"
    else:
        posture = "TRADING AT SIGNIFICANT DISCOUNT TO DCF"

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
            "dcf_upside_percent": round(dcf_upside, 1),
            "monte_carlo_upside_percent": round(mc_upside, 1),
            "valuation_posture": posture,
        },
        "executive_summary": {
            "thesis_narrative": (
                f"Fundamental valuation synthesis for {name} ({ticker}). Rigorous discounted cash flow modeling establishes "
                f"an intrinsic fair value of {sym}{dcf_value:.2f} per share compared to current market trading levels of "
                f"{sym}{current_price:.2f} ({dcf_upside:+.1f}% valuation spread). "
                f"Our analysis indicates that prevailing market prices reflect significant multiple expansion and heightened expectations "
                f"that require sustained top-line acceleration beyond normalized industry delivery."
            ),
            "valuation_gap_analysis": (
                f"The stock trades at a {abs(dcf_upside):.1f}% {'premium' if dcf_upside < 0 else 'discount'} to DCF intrinsic value. "
                f"This divergence is driven by market consensus assuming aggressive operational acceleration compared to baseline historical cash flow generation."
            ),
            "core_value_engine": f"Discount rate of {_fmt_pct(wacc.get('wacc'))} applied to projected cash flows expanding at baseline {_fmt_pct(historicals.get('avg_rev_growth'))} CAGR.",
            "primary_downside_vulnerability": f"Simulation downside percentile (P5) boundary established at {sym}{mc_p5:.2f} if volume demand softens.",
        },
        "variant_perception": {
            "divergence_headline": f"Market Pricing Assumes {abs(growth_gap_bps):.0f} bps Growth Disconnect From Historical Baseline",
            "consensus_narrative": f"Current market price of {sym}{current_price:.2f} bakes in an operational growth hurdle of {market_implied_g*100:.1f}% CAGR.",
            "fundamental_reality": f"Normalized historical delivery of {_fmt_pct(historicals.get('avg_rev_growth'))} and mature category penetration constrain sustainable volume growth.",
            "structural_pillars": [
                {
                    "theme": "Top-Line Growth Hurdle & Category Saturation",
                    "analysis": f"To validate current market valuation, revenue must compound at {market_implied_g*100:.1f}% ({growth_hurdle_gap_bps:+.0f} bps over the {historicals.get('avg_rev_growth', 0.1)*100:.1f}% historical baseline).",
                },
                {
                    "theme": "Operating Profitability & Pass-Through Elasticity",
                    "analysis": f"Operating margins modeled at {_fmt_pct(historicals.get('avg_ebit_margin'))} reflect competitive intensity and raw material input cost realities.",
                },
                {
                    "theme": "Cash Flow Reinvestment & Capital Efficiency",
                    "analysis": f"Asset-light reinvestment profile with CapEx at {_fmt_pct(historicals.get('avg_capex_pct'))} of revenue supports cash generation but bounds inorganic expansion.",
                },
            ],
        },
        "business_and_moat": {
            "business_model": company.get("description", "")[:600] or f"{name} operates across diversified consumer and commercial product lines in {company.get('industry', 'its industry')}.",
            "competitive_moat": f"Durable competitive advantages stemming from distribution depth, customer switching costs, and brand equity in {company.get('sector', 'its sector')}.",
            "market_position_and_clients": f"Operations anchored in {company.get('country', 'global markets')} with extensive reach across enterprise and retail consumer cohorts.",
        },
        "expectations_investing": {
            "market_implied_growth_cagr": round(market_implied_g * 100.0, 1),
            "baseline_growth_cagr": round(float(historicals.get("avg_rev_growth", 0.10)) * 100.0, 1),
            "growth_hurdle_gap_bps": growth_gap_bps,
            "market_implied_margin": f"{rev_dcf.get('market_implied_margin') * 100:.1f}%" if rev_dcf.get("market_implied_margin") is not None else "Unachievable via margin alone",
            "market_implied_wacc": f"{rev_dcf.get('market_implied_wacc') * 100:.1f}%" if rev_dcf.get("market_implied_wacc") is not None else "N/A",
            "hurdle_classification": rev_dcf.get("stance", "Consensus Aligned"),
            "plausibility_assessment": rev_dcf.get("narrative", f"Market price requires {market_implied_g*100:.1f}% growth CAGR."),
        },
        "dcf_cash_flow_bridge": {
            "fair_value": dcf_value,
            "revenue_trajectory": {
                "forecast_cagr": float(historicals.get("avg_rev_growth") or 0.10) * 100,
                "historical_cagr": float(historicals.get("avg_rev_growth") or 0.10) * 100,
                "analysis": f"Projected baseline growth reflects {historicals.get('n_years', 4)}-year historical delivery of {_fmt_pct(historicals.get('avg_rev_growth'))} CAGR.",
            },
            "operating_margin_leverage": {
                "forecast_margin": float(historicals.get("avg_ebit_margin") or 0.15) * 100,
                "historical_margin": float(historicals.get("avg_ebit_margin") or 0.15) * 100,
                "analysis": f"Operating margin modeled at {_fmt_pct(historicals.get('avg_ebit_margin'))}, consistent with normalized operating leverage.",
            },
            "reinvestment_dynamics": {
                "capex_intensity": f"{_fmt_pct(historicals.get('avg_capex_pct'))} of revenue.",
                "working_capital_float": f"{_fmt_pct(historicals.get('avg_dnwc_pct'))} of revenue.",
                "fcf_conversion_analysis": "Efficient cash conversion supported by disciplined working capital management.",
            },
            "cost_of_capital": {
                "wacc": float(wacc.get("wacc") or 0.10) * 100,
                "cost_of_equity": float(wacc.get("cost_of_equity") or 0.10) * 100,
                "cost_of_debt": float(wacc.get("cost_of_debt") or 0.05) * 100,
                "analysis": f"Discount rate of {_fmt_pct(wacc.get('wacc'))} reflects sovereign risk benchmark and equity risk premium.",
            },
            "terminal_value_mechanics": {
                "tv_share_of_ev": round(float((dcf.get("pv_terminal_value", 0.0) / dcf.get("enterprise_value", 1.0)) * 100), 1) if dcf.get("enterprise_value", 0.0) > 0 else 70.0,
                "exit_multiple_cross_check": f"Implied EV/EBITDA exit multiple: {_fmt_num(dcf.get('implied_exit_multiple'), decimals=1)}x vs sector benchmark of {_fmt_num(dcf.get('benchmark_exit_multiple'), decimals=1)}x.",
                "analysis": f"Terminal value modeled with a {_fmt_pct(term_g)} perpetual growth rate, anchored against sovereign long-run nominal GDP growth (~{_fmt_pct(gdp_anchor)}), yielding an implied exit multiple of {_fmt_num(dcf.get('implied_exit_multiple'), decimals=1)}x EV/EBITDA.",
            },
        },
        "monte_carlo_analysis": {
            "distribution_interpretation": f"10,000-run simulation establishes a 90% confidence corridor between {sym}{mc_p5:.2f} (P5) and {sym}{mc_p95:.2f} (P95), with median outcome at {sym}{mc_median:.2f}.",
            "downside_floor_p5": f"5th percentile downside floor stands at {sym}{mc_p5:.2f}, reflecting severe volume deceleration or input inflation.",
            "base_case_p50": f"Median expected outcome is {sym}{mc_median:.2f}, confirming central DCF intrinsic valuation.",
            "upside_ceiling_p95": f"95th percentile bull case reaches {sym}{mc_p95:.2f} under aggressive operational execution.",
        },
        "asymmetric_scenarios": {
            "bear": {
                "fair_value": mc_p5,
                "revenue_growth": f"{max(0.01, float(historicals.get('avg_rev_growth', 0.10)) * 0.5) * 100:.1f}%",
                "ebit_margin": f"{float(historicals.get('avg_ebit_margin', 0.15)) * 0.85 * 100:.1f}%",
                "operational_catalysts": "Demand contraction, pricing resistance, and valuation multiple compression.",
            },
            "base": {
                "fair_value": dcf_value,
                "revenue_growth": f"{float(historicals.get('avg_rev_growth', 0.10)) * 100:.1f}%",
                "ebit_margin": f"{float(historicals.get('avg_ebit_margin', 0.15)) * 100:.1f}%",
                "operational_catalysts": "Execution aligned with historical baseline and normalized guidance.",
            },
            "bull": {
                "fair_value": mc_p95,
                "revenue_growth": f"{float(historicals.get('avg_rev_growth', 0.10)) * 1.5 * 100:.1f}%",
                "ebit_margin": f"{min(0.85, float(historicals.get('avg_ebit_margin', 0.15)) * 1.15) * 100:.1f}%",
                "operational_catalysts": "Category volume re-acceleration, premiumization, and margin expansion.",
            },
        },
        "key_drivers": [
            {
                "driver": "Top-line Revenue Growth",
                "assumption": f"{_fmt_pct(historicals.get('avg_rev_growth'))} CAGR",
                "valuation_sensitivity": "Directly compounds operating revenue and free cash flow generation.",
                "monitoring_metric": "Quarterly underlying volume growth and realizations.",
            },
            {
                "driver": "Operating Profitability (EBIT Margin)",
                "assumption": f"{_fmt_pct(historicals.get('avg_ebit_margin'))} margin",
                "valuation_sensitivity": "Converts top-line volume into NOPAT and enterprise free cash flow.",
                "monitoring_metric": "Gross margin stability and employee cost leverage.",
            },
            {
                "driver": "Cost of Capital (WACC)",
                "assumption": f"{_fmt_pct(wacc.get('wacc'))} discount rate",
                "valuation_sensitivity": "Present value factor determining equity value capitalization.",
                "monitoring_metric": "10-Year sovereign bond yield shifts and corporate credit spread.",
            },
        ],
        "downside_risks": [
            {
                "risk": "Input Cost Inflation & Pricing Resistance",
                "severity": "High",
                "transmission_mechanism": "Raw material inflation eroding gross margins when competitive intensity prevents full price pass-through.",
                "early_warning_indicator": "Quarterly gross margin trends and commodity price indices.",
            },
            {
                "risk": "Demand Softening in Core Categories",
                "severity": "Medium",
                "transmission_mechanism": "Macroeconomic or rural demand slowdown dampening volume uptake and sales velocity.",
                "early_warning_indicator": "Quarterly volume growth disclosures and distributor inventory levels.",
            },
        ],
        "quarterly_monitoring_signposts": {
            "quarterly_kpis": [
                f"Quarterly organic revenue growth rate vs. {_fmt_pct(historicals.get('avg_rev_growth'))} baseline",
                f"Operating margin delivery relative to {_fmt_pct(historicals.get('avg_ebit_margin'))} benchmark",
                "Underlying volume growth trajectory across primary product lines",
            ],
            "invalidation_triggers": [
                f"Top-line growth deviating persistently by >400 bps from the {_fmt_pct(historicals.get('avg_rev_growth'))} baseline",
                "Sustained EBIT margin decline exceeding 250 bps without offsetting volume acceleration",
            ],
        },
        "final_synthesis": (
            f"Multi-stage DCF valuation establishes an intrinsic fair value of {sym}{dcf_value:.2f} for {name} ({ticker}) "
            f"versus current market price of {sym}{current_price:.2f} ({dcf_upside:+.1f}% implied spread). "
            f"Reverse DCF expectations analysis indicates that the market prices in a demanding {market_implied_g*100:.1f}% growth hurdle, "
            f"establishing a '{posture}' valuation posture. Investors should monitor quarterly volume momentum and operating margin resilience."
        ),
    }
    return json.dumps(fallback_obj)
