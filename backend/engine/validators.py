from typing import Dict, Any, Optional

def validate_valuation(dcf_result: Dict[str, Any], stock_data: Dict[str, Any], metrics: Dict[str, Any], wacc_data: Dict[str, float]) -> Dict[str, Any]:
    """
    Computes EV/EBITDA cross-check (or EV/Revenue if EBITDA is negative) and validation status.
    """
    ebit_arr = metrics.get('ebit', [])
    dna_arr = metrics.get('dna', [])
    last_revenue = metrics.get('last_revenue', 0.0)
    
    last_ebit = ebit_arr[-1] if len(ebit_arr) > 0 else 0.0
    last_dna = dna_arr[-1] if len(dna_arr) > 0 else 0.0
    
    trailing_ebitda = last_ebit + last_dna
        
    market_cap = stock_data.get('market_cap', 0.0)
    total_debt = wacc_data.get('total_debt', 0.0)
    
    # Compute Cash
    balance_sheet = stock_data.get('balance_sheet')
    cash = 0.0
    if balance_sheet is not None and not balance_sheet.empty:
        if 'Cash And Cash Equivalents' in balance_sheet.columns:
            cash_vals = balance_sheet['Cash And Cash Equivalents'].dropna()
            if len(cash_vals) > 0:
                cash = float(cash_vals.iloc[0])
                
    market_ev = market_cap + total_debt - cash
    enterprise_value = dcf_result.get('enterprise_value', 0.0)
    
    metric_used = "none"
    market_multiple = None
    model_multiple = None
    multiple_gap_pct = 0.0
    status = "N/A"
    
    if trailing_ebitda > 0:
        metric_used = "ev_ebitda"
        market_multiple = market_ev / trailing_ebitda
        model_multiple = enterprise_value / trailing_ebitda
    elif last_revenue > 0:
        metric_used = "ev_revenue"
        market_multiple = market_ev / last_revenue
        model_multiple = enterprise_value / last_revenue

    if market_multiple and market_multiple != 0:
        multiple_gap_pct = abs(model_multiple - market_multiple) / market_multiple
        status = "PASS" if multiple_gap_pct < 0.50 else "WARNING"
    
    return {
        "metric_used": metric_used,
        "trailing_ebitda": float(trailing_ebitda),
        "trailing_revenue": float(last_revenue),
        "market_ev": float(market_ev),
        "market_multiple": float(market_multiple) if market_multiple is not None else None,
        "model_multiple": float(model_multiple) if model_multiple is not None else None,
        "multiple_gap_pct": float(multiple_gap_pct),
        "status": status
    }

def generate_verdict(current_price: float, mc_stats: Dict[str, float], terminal_value_valid: bool = True, mc_valid: bool = True) -> Dict[str, Any]:
    """
    Generates a BUY/SELL/HOLD verdict based on Monte Carlo percentiles.
    """
    p5 = mc_stats.get('p5')
    p25 = mc_stats.get('p25')
    median = mc_stats.get('median')
    p75 = mc_stats.get('p75')
    p95 = mc_stats.get('p95')

    import math
    def is_invalid(val):
        return val is None or math.isnan(val) or math.isinf(val) or val == 0.0

    if not terminal_value_valid or not mc_valid or is_invalid(p5) or is_invalid(p95) or is_invalid(median):
        return {
            "verdict": "N/A",
            "description": "Valuation assumptions do not currently support a valid terminal value or sufficient valid simulations.",
            "upside_pct": 0.0
        }
    
    if current_price < p5:
        verdict = "STRONG BUY"
        description = "Trades below the 5th-percentile downside estimate."
    elif current_price > p95:
        verdict = "STRONG SELL"
        description = "Trades above the 95th-percentile upside estimate."
    elif current_price < p25:
        verdict = "BUY"
        description = "Trades below the 25th percentile of outcomes."
    elif current_price > p75:
        verdict = "SELL"
        description = "Trades above the 75th percentile of outcomes."
    else:
        verdict = "HOLD / FAIR VALUE"
        description = "Trades within the interquartile range of simulated outcomes."
        
    upside_pct = ((median / current_price) - 1) * 100 if current_price > 0 else 0.0
    
    return {
        "verdict": verdict,
        "description": description,
        "upside_pct": float(upside_pct)
    }
