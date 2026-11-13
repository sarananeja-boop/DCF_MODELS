"""
Unit tests for AI Institutional Valuation Summary Generator
===========================================================
Verifies:
1. Terminal growth rate fidelity in prompt context and user prompt.
2. Macro GDP anchor accuracy (India 6.5% vs US 2.5%).
3. Sanitizer catches and corrects hallucinated 2.5% perpetual growth rates for Indian equities.
4. Fallback generation outputs accurate terminal growth (e.g. 5.0% for IN) and no BUY/SELL.
"""

import json
import pytest
from ai.summary_generator import _build_prompt, _enrich_and_validate_report, _build_fallback


@pytest.fixture
def indian_analysis_data():
    return {
        "company": {
            "name": "Hindustan Unilever Limited",
            "ticker": "HINDUNILVR.NS",
            "market": "IN",
            "currency": "INR",
            "symbol": "₹",
            "sector": "Consumer Defensive",
            "industry": "Household & Personal Products",
            "country": "India",
            "description": "Hindustan Unilever Limited is an FMCG company.",
        },
        "market_data": {
            "current_price": 1990.30,
            "market_cap": 4676000000000.0,
            "shares_outstanding": 2349591180,
            "beta": 0.74,
            "trailing_pe": 45.2,
            "forward_pe": 41.0,
            "price_to_sales": 7.5,
        },
        "macro": {
            "risk_free_rate": 0.071,
            "risk_free_source": "India 10Y Sovereign Bond Benchmark (7.10%)",
            "market_return": 0.13,
            "tax_rate": 0.2517,
            "terminal_growth": 0.050,
            "gdp_growth": 0.065,
        },
        "historicals": {
            "avg_rev_growth": 0.050,
            "std_rev_growth": 0.021,
            "avg_ebit_margin": 0.232,
            "std_ebit_margin": 0.012,
            "avg_capex_pct": 0.025,
            "avg_dna_pct": 0.022,
            "avg_dnwc_pct": -0.015,
            "n_years": 4,
        },
        "wacc": {
            "cost_of_equity": 0.1147,
            "cost_of_debt": 0.0531,
            "weight_equity": 0.997,
            "weight_debt": 0.003,
            "wacc": 0.114,
            "synthetic_rating": "AAA",
        },
        "dcf_result": {
            "implied_price": 789.61,
            "enterprise_value": 1850000000000.0,
            "pv_ufcf": 500000000000.0,
            "pv_terminal_value": 1350000000000.0,
            "terminal_growth": 0.050,
            "effective_terminal_growth": 0.050,
            "terminal_growth_capped": False,
            "benchmark_exit_multiple": 14.5,
            "implied_exit_multiple": 10.0,
        },
        "monte_carlo": {
            "stats": {
                "mean": 810.20,
                "median": 795.54,
                "p5": 548.72,
                "p25": 670.10,
                "p75": 920.40,
                "p95": 1307.79,
            }
        },
        "reverse_dcf": {
            "current_price": 1990.30,
            "model_fair_value": 789.61,
            "valuation_gap_pct": -60.3,
            "base_growth": 0.050,
            "market_implied_growth": 0.402,
            "growth_hurdle_gap_bps": 3520.0,
            "stance": "Extreme Growth Hurdle",
            "plausibility": "Severe Overvaluation",
        },
    }


def test_build_prompt_contains_accurate_terminal_growth_and_macro(indian_analysis_data):
    prompt_context = _build_prompt(indian_analysis_data)
    # Check that 5.0% terminal growth is explicitly present in context
    assert "Modeled Perpetual Terminal Growth Rate (g): 5.0%" in prompt_context
    assert "Sovereign Long-Run Nominal GDP Growth Anchor: 6.5%" in prompt_context
    assert "Effective Modeled Terminal Growth: 5.0%" in prompt_context


def test_sanitizer_corrects_hallucinated_2_5_percent_for_indian_stock(indian_analysis_data):
    # Simulate a raw LLM response that hallucinated 2.5% perpetual growth
    hallucinated_report = {
        "headline_metrics": {
            "current_price": 1990.30,
            "dcf_value": 789.61,
        },
        "dcf_cash_flow_bridge": {
            "terminal_value_mechanics": {
                "tv_share_of_ev": 72.8,
                "analysis": "Terminal value uses a 2.5% perpetual growth rate, consistent with India's long-run GDP growth, and a 10x EV/EBITDA multiple.",
            }
        },
        "executive_summary": {
            "thesis_narrative": "Model incorporates a 2.5% terminal growth rate assumption."
        }
    }

    cleaned = _enrich_and_validate_report(hallucinated_report, indian_analysis_data)

    tv_analysis = cleaned["dcf_cash_flow_bridge"]["terminal_value_mechanics"]["analysis"]
    # Verify 2.5% was sanitized to 5.0%
    assert "5.0% perpetual growth rate" in tv_analysis
    assert "2.5%" not in tv_analysis
    # Verify India's GDP growth is not stated as 2.5%
    assert "6.5%" in tv_analysis or "5.0%" in tv_analysis

    exec_narrative = cleaned["executive_summary"]["thesis_narrative"]
    assert "5.0% perpetual growth rate" in exec_narrative
    assert "2.5%" not in exec_narrative


def test_build_fallback_uses_5_percent_terminal_growth_for_indian_stock(indian_analysis_data):
    fallback_json = _build_fallback(indian_analysis_data)
    fallback_obj = json.loads(fallback_json)

    tv_analysis = fallback_obj["dcf_cash_flow_bridge"]["terminal_value_mechanics"]["analysis"]
    assert "5.0% perpetual growth rate" in tv_analysis
    assert "6.5%" in tv_analysis
    assert "2.5%" not in tv_analysis

    # Verify no BUY/SELL recommendations
    assert "recommendation" not in fallback_obj["headline_metrics"]
    assert "BUY" not in fallback_obj["headline_metrics"].get("valuation_posture", "")
    assert "SELL" not in fallback_obj["headline_metrics"].get("valuation_posture", "")



def test_enrich_and_validate_enforces_us_currency_over_hallucinated_inr():
    us_analysis_data = {
        "company": {
            "ticker": "ASML",
            "name": "ASML Holding N.V.",
            "market": "US",
            "currency": "USD",
            "symbol": "$",
            "sector": "Technology",
            "industry": "Semiconductor Equipment & Materials",
        },
        "market_data": {"current_price": 1495.0, "market_cap": 576e9, "shares_outstanding": 385e6, "beta": 1.25},
        "macro": {"risk_free_rate": 0.051, "market_return": 0.10, "tax_rate": 0.21, "terminal_growth": 0.025, "gdp_growth": 0.025},
        "historicals": {"n_years": 4, "avg_rev_growth": 0.12, "avg_ebit_margin": 0.32, "avg_roe": 0.45},
        "wacc": {"wacc": 0.11, "cost_of_equity": 0.112, "cost_of_debt": 0.04},
        "dcf_result": {"implied_price": 450.0, "terminal_growth": 0.025, "effective_terminal_growth": 0.025, "enterprise_value": 180e9, "pv_ufcf": 50e9, "pv_terminal_value": 130e9},
        "monte_carlo": {"stats": {"median": 460.0, "p5": 300.0, "p25": 380.0, "p75": 540.0, "p95": 680.0}},
        "reverse_dcf": {"growth_hurdle_gap_bps": 450.0, "market_implied_growth": 0.165, "base_growth": 0.12, "stance": "High Expectations Hurdle"},
    }
    hallucinated_report = {
        "company": "Wrong Co",
        "ticker": "WRONG",
        "currency": "INR",
        "headline_metrics": {},
    }
    cleaned = _enrich_and_validate_report(hallucinated_report, us_analysis_data)
    assert cleaned["currency"] == "USD"
    assert cleaned["company"] == "ASML Holding N.V."
    assert cleaned["ticker"] == "ASML"
