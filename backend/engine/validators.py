from typing import Dict, Any

def validate_valuation(dcf_result: Dict[str, Any], stock_data: Dict[str, Any], metrics: Dict[str, Any], wacc_data: Dict[str, float]) -> Dict[str, Any]:
    """
    Computes EV/EBITDA cross-check and validation status.
    """
    ebit_arr = metrics.get('ebit', [])
    dna_arr = metrics.get('dna', [])
    
    last_ebit = ebit_arr[-1] if len(ebit_arr) > 0 else 0.0
    last_dna = dna_arr[-1] if len(dna_arr) > 0 else 0.0
    
    trailing_ebitda = last_ebit + last_dna
    if trailing_ebitda <= 0:
        trailing_ebitda = 1.0  # Prevent division by zero
        
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
    market_ev_ebitda = market_ev / trailing_ebitda
    
    enterprise_value = dcf_result.get('enterprise_value', 0.0)
    model_ev_ebitda = enterprise_value / trailing_ebitda
    
    multiple_gap_pct = 0.0
    if market_ev_ebitda != 0:
        multiple_gap_pct = abs(model_ev_ebitda - market_ev_ebitda) / market_ev_ebitda * 100.0
        
    status = "PASS" if multiple_gap_pct < 50.0 else "WARNING"
    
    return {
        "trailing_ebitda": float(trailing_ebitda),
        "market_ev": float(market_ev),
        "market_ev_ebitda": float(market_ev_ebitda),
        "model_ev_ebitda": float(model_ev_ebitda),
        "multiple_gap_pct": float(multiple_gap_pct),
        "status": status
    }

def generate_verdict(current_price: float, mc_stats: Dict[str, float]) -> Dict[str, Any]:
    """
    Generates a BUY/SELL/HOLD verdict based on Monte Carlo percentiles.
    """
    p5 = mc_stats.get('p5', 0.0)
    p25 = mc_stats.get('p25', 0.0)
    median = mc_stats.get('median', 0.0)
    p75 = mc_stats.get('p75', 0.0)
    p95 = mc_stats.get('p95', 0.0)
    
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
