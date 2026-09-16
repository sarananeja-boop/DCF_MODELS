import numpy as np
from typing import Dict, Any, Optional
from .dcf_engine import run_dcf

def generate_sensitivity_grid(
    metrics: Dict[str, Any], 
    wacc_data: Dict[str, float], 
    stock_data: Dict[str, Any], 
    market_profile: Dict[str, Any], 
    terminal_growth: float = 0.025, 
    projection_years: int = 5, 
    grid_size: int = 9,
    target_margin: float = None,
    current_margin: Optional[float] = None
) -> Dict[str, Any]:
    """
    Generates a 2D sensitivity grid for Revenue Growth vs. WACC.
    """
    avg_rev_growth = metrics.get('avg_rev_growth', 0.0)
    ebit_margin = target_margin if target_margin is not None else metrics.get('avg_ebit_margin', 0.0)
    base_wacc = wacc_data.get('wacc', 0.10)
    
    # Generate ranges
    growth_range = np.linspace(avg_rev_growth - 0.06, avg_rev_growth + 0.06, grid_size)
    raw_wacc_range = np.linspace(base_wacc - 0.03, base_wacc + 0.03, grid_size)
    
    # Filter out impossible WACC values
    wacc_range = raw_wacc_range[raw_wacc_range > terminal_growth + 0.005]
    
    price_grid = []
    
    for w in wacc_range:
        row = []
        for g in growth_range:
            try:
                dcf_result = run_dcf(
                    start_growth=g,
                    ebit_margin=ebit_margin,
                    discount_rate=w,
                    metrics=metrics,
                    wacc_data=wacc_data,
                    stock_data=stock_data,
                    terminal_growth=terminal_growth,
                    projection_years=projection_years,
                    current_margin=current_margin
                )
                row.append(float(dcf_result['implied_price']))
            except Exception:
                row.append(0.0)
        price_grid.append(row)
        
    return {
        "growth_range": growth_range.tolist(),
        "wacc_range": wacc_range.tolist(),
        "price_grid": price_grid,
        "base_growth": float(avg_rev_growth),
        "base_wacc": float(base_wacc)
    }

def generate_margin_sensitivity_grid(
    metrics: Dict[str, Any], 
    wacc_data: Dict[str, float], 
    stock_data: Dict[str, Any], 
    market_profile: Dict[str, Any], 
    terminal_growth: float = 0.025, 
    projection_years: int = 5, 
    grid_size: int = 9,
    target_margin: float = None,
    current_margin: Optional[float] = None
) -> Dict[str, Any]:
    """
    Generates a 2D sensitivity grid for EBIT Margin vs. WACC.
    """
    avg_rev_growth = metrics.get('avg_rev_growth', 0.0)
    base_margin = target_margin if target_margin is not None else metrics.get('avg_ebit_margin', 0.0)
    base_wacc = wacc_data.get('wacc', 0.10)
    
    # Generate ranges
    margin_range = np.linspace(base_margin - 0.08, base_margin + 0.08, grid_size)
    raw_wacc_range = np.linspace(base_wacc - 0.03, base_wacc + 0.03, grid_size)
    
    # Filter out impossible WACC values
    wacc_range = raw_wacc_range[raw_wacc_range > terminal_growth + 0.005]
    
    price_grid = []
    
    for w in wacc_range:
        row = []
        for m in margin_range:
            try:
                dcf_result = run_dcf(
                    start_growth=avg_rev_growth,
                    ebit_margin=m,
                    discount_rate=w,
                    metrics=metrics,
                    wacc_data=wacc_data,
                    stock_data=stock_data,
                    terminal_growth=terminal_growth,
                    projection_years=projection_years,
                    current_margin=current_margin
                )
                row.append(float(dcf_result['implied_price']))
            except Exception:
                row.append(0.0)
        price_grid.append(row)
        
    return {
        "margin_range": margin_range.tolist(),
        "wacc_range": wacc_range.tolist(),
        "price_grid": price_grid,
        "base_margin": float(base_margin),
        "base_wacc": float(base_wacc)
    }
