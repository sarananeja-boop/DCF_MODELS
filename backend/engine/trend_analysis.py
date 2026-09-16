import numpy as np
from typing import Dict, Any

def compute_trends(stock_data: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes historical trends for revenue, margins, capex, and nwc.
    """
    revenue_arr = metrics.get('revenue', [])
    ebit_margins_arr = metrics.get('ebit_margins', [])
    capex_pct_arr = metrics.get('capex_pct', []) # Assumes data_layer exposes this if needed, else we compute
    dnwc_pct_arr = metrics.get('dnwc_pct', [])
    years = metrics.get('years', [])
    
    # If percentages aren't directly in metrics, we calculate them
    if not capex_pct_arr and 'capex' in metrics:
        capex_pct_arr = [c/r if r > 0 else 0 for c, r in zip(metrics['capex'], revenue_arr)]
    if not dnwc_pct_arr and 'delta_nwc' in metrics:
        dnwc_pct_arr = [n/r if r > 0 else 0 for n, r in zip(metrics['delta_nwc'], revenue_arr)]
        
    # Free Cash Flow history proxy: (EBIT - CapEx - deltaNWC)
    # A true UFCF requires tax rate and D&A, we'll approximate with NOPAT + D&A - CapEx - dNWC
    ebit_arr = metrics.get('ebit', [])
    dna_arr = metrics.get('dna', [])
    capex_arr = metrics.get('capex', [])
    dnwc_arr = metrics.get('delta_nwc', [])
    
    tax_rate = 0.25 # approximation if not provided
    fcf_arr = []
    for i in range(len(revenue_arr)):
        nopat = ebit_arr[i] * (1 - tax_rate)
        fcf = nopat + dna_arr[i] - capex_arr[i] - dnwc_arr[i]
        fcf_arr.append(fcf)
        
    revenue_history = [{"year": str(y), "value": float(v)} for y, v in zip(years, revenue_arr)]
    margin_history = [{"year": str(y), "value": float(v)} for y, v in zip(years, ebit_margins_arr)]
    capex_intensity = [{"year": str(y), "value": float(v)} for y, v in zip(years, capex_pct_arr)]
    nwc_efficiency = [{"year": str(y), "value": float(v)} for y, v in zip(years, dnwc_pct_arr)]
    fcf_history = [{"year": str(y), "value": float(v)} for y, v in zip(years, fcf_arr)]
    
    # Revenue CAGR
    revenue_cagr = 0.0
    if len(revenue_arr) >= 2 and revenue_arr[0] > 0:
        revenue_cagr = (revenue_arr[-1] / revenue_arr[0]) ** (1 / (len(revenue_arr) - 1)) - 1
        
    # Margin trend
    margin_trend = "stable"
    if len(ebit_margins_arr) >= 2:
        slope = np.polyfit(np.arange(len(ebit_margins_arr)), ebit_margins_arr, 1)[0]
        if slope > 0.005:
            margin_trend = "expanding"
        elif slope < -0.005:
            margin_trend = "compressing"
            
    # CapEx trend
    capex_trend = "stable"
    if len(capex_pct_arr) >= 2:
        slope = np.polyfit(np.arange(len(capex_pct_arr)), capex_pct_arr, 1)[0]
        if slope > 0.005:
            capex_trend = "increasing"
        elif slope < -0.005:
            capex_trend = "decreasing"

    return {
        "revenue_history": revenue_history,
        "revenue_cagr": float(revenue_cagr),
        "margin_history": margin_history,
        "margin_trend": margin_trend,
        "capex_intensity": capex_intensity,
        "capex_trend": capex_trend,
        "nwc_efficiency": nwc_efficiency,
        "fcf_history": fcf_history
    }
