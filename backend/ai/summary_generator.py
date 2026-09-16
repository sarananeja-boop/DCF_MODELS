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

MODEL = "groq/compound"


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

    try:
        client = _get_client()
        chat_completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=6000,
            top_p=0.9,
        )
        return chat_completion.choices[0].message.content

    except Exception as exc:
        logger.error("Groq API call failed: %s", exc)
        return _build_fallback(analysis_data)


# ---------------------------------------------------------------------------
# Fallback (no LLM)
# ---------------------------------------------------------------------------

def _build_fallback(data: Dict[str, Any]) -> str:
    """Return a simple markdown summary with key numbers when the LLM is unavailable."""

    company = data.get("company", {})
    market_data = data.get("market_data", {})
    dcf = data.get("dcf_result", {})
    mc_stats = data.get("monte_carlo", {}).get("stats", {})
    wacc = data.get("wacc", {})
    validation = data.get("validation", {})
    verdict = data.get("verdict", {})
    sym = company.get("symbol", "$")

    fallback_md = f"""## Valuation Summary — {company.get('name', 'N/A')} ({company.get('ticker', 'N/A')})

> *AI-generated summary unavailable. Key metrics below.*

| Metric | Value |
|--------|-------|
| **Current Price** | {_fmt_num(market_data.get('current_price'), prefix=sym)} |
| **DCF Implied Price** | {_fmt_num(dcf.get('implied_price'), prefix=sym)} |
| **MC Mean** | {_fmt_num(mc_stats.get('mean'), prefix=sym)} |
| **MC Median** | {_fmt_num(mc_stats.get('median'), prefix=sym)} |
| **MC Range (P5–P95)** | {_fmt_num(mc_stats.get('p5'), prefix=sym)} – {_fmt_num(mc_stats.get('p95'), prefix=sym)} |
| **WACC** | {_fmt_pct(wacc.get('wacc'))} |
| **EV/EBITDA (Market)** | {_fmt_num(validation.get('market_ev_ebitda'), decimals=1)}x |
| **EV/EBITDA (Model)** | {_fmt_num(validation.get('model_ev_ebitda'), decimals=1)}x |

**Verdict:** {verdict.get('verdict', 'N/A')} — {verdict.get('description', 'N/A')}
(Upside: {_fmt_pct(verdict.get('upside_pct'))})
"""
    import json
    return json.dumps({
        "summary": fallback_md,
        "risks": ["AI generation unavailable. Please verify API keys and quota."]
    })
