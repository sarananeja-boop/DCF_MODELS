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
    current_margin: Optional[float] = None,
    tax_rate: Optional[float] = None,
    use_mid_year: bool = True,
    base_growth: Optional[float] = None,
    base_wacc: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Generates a 2D sensitivity grid for Revenue Growth vs. WACC.
    """
    avg_rev_growth = base_growth if base_growth is not None else metrics.get('avg_rev_growth', 0.0)
    ebit_margin = target_margin if target_margin is not None else metrics.get('avg_ebit_margin', 0.0)
    base_wacc = base_wacc if base_wacc is not None else wacc_data.get('wacc', 0.10)
    
    if tax_rate is None and market_profile:
        tax_rate = market_profile.get("tax_rate")
        
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
                    current_margin=current_margin,
                    tax_rate=tax_rate,
                    use_mid_year=use_mid_year,
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
    current_margin: Optional[float] = None,
    tax_rate: Optional[float] = None,
    use_mid_year: bool = True,
    base_growth: Optional[float] = None,
    base_wacc: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Generates a 2D sensitivity grid for EBIT Margin vs. WACC.
    """
    avg_rev_growth = base_growth if base_growth is not None else metrics.get('avg_rev_growth', 0.0)
    base_margin = target_margin if target_margin is not None else metrics.get('avg_ebit_margin', 0.0)
    base_wacc = base_wacc if base_wacc is not None else wacc_data.get('wacc', 0.10)
    
    if tax_rate is None and market_profile:
        tax_rate = market_profile.get("tax_rate")
        
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
                    current_margin=current_margin,
                    tax_rate=tax_rate,
                    use_mid_year=use_mid_year,
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


def generate_terminal_growth_sensitivity_grid(
    metrics: Dict[str, Any],
    wacc_data: Dict[str, float],
    stock_data: Dict[str, Any],
    market_profile: Dict[str, Any],
    terminal_growth: float = 0.025,
    projection_years: int = 5,
    grid_size: int = 9,
    target_margin: float = None,
    current_margin: Optional[float] = None,
    tax_rate: Optional[float] = None,
    use_mid_year: bool = True,
    base_growth: Optional[float] = None,
    base_wacc: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Generates a 2D sensitivity grid for Terminal Growth Rate (g) vs. WACC.
    Rows: WACC (increasing top-to-bottom), Columns: Terminal Growth Rate (g, increasing left-to-right).
    """
    avg_rev_growth = base_growth if base_growth is not None else metrics.get("avg_rev_growth", 0.0)
    base_margin = target_margin if target_margin is not None else metrics.get("avg_ebit_margin", 0.0)
    base_wacc = base_wacc if base_wacc is not None else wacc_data.get("wacc", 0.10)

    if tax_rate is None and market_profile:
        tax_rate = market_profile.get("tax_rate")

    # Evaluate base DCF first to anchor on effective_terminal_growth and base terminal_reinv_rate
    base_dcf = run_dcf(
        start_growth=avg_rev_growth,
        ebit_margin=base_margin,
        discount_rate=base_wacc,
        metrics=metrics,
        wacc_data=wacc_data,
        stock_data=stock_data,
        terminal_growth=terminal_growth,
        projection_years=projection_years,
        current_margin=current_margin,
        tax_rate=tax_rate,
        use_mid_year=use_mid_year,
    )
    eff_base_tg = float(base_dcf.get("effective_terminal_growth", terminal_growth))
    base_reinv = float(base_dcf.get("terminal_reinv_rate", 0.10))
    base_ufcf = [float(x) for x in (base_dcf.get("projected_ufcf") or base_dcf.get("ufcf") or [])]
    base_nopat = [float(x) for x in (base_dcf.get("projected_nopat") or base_dcf.get("nopat") or [])]
    last_nopat = base_nopat[-1] if base_nopat else 0.0
    n_proj = len(base_ufcf) if base_ufcf else projection_years
    periods = [0.5 + k if use_mid_year else 1.0 + k for k in range(n_proj)]

    terminal_val = float(base_dcf.get("terminal_value") or 0.0)
    spread_base = float(base_wacc) - eff_base_tg
    pure_gordon_tv = (
        (last_nopat * (1.0 + eff_base_tg) * (1.0 - base_reinv)) / spread_base
        if (spread_base > 0 and last_nopat > 0)
        else terminal_val
    )
    tv_scale = (terminal_val / pure_gordon_tv) if (pure_gordon_tv > 0 and abs(terminal_val - pure_gordon_tv) > 1.0) else 1.0

    cash_val = float(base_dcf.get("cash", wacc_data.get("total_cash", 0.0)) or 0.0)
    debt_val = float(base_dcf.get("total_debt", wacc_data.get("total_debt", 0.0)) or 0.0)
    min_int_val = float(base_dcf.get("minority_interest", wacc_data.get("minority_interest_claim", 0.0)) or 0.0) + float(
        base_dcf.get("preferred_stock", wacc_data.get("preferred_stock_claim", 0.0)) or 0.0
    )
    shares_cnt = float(stock_data.get("shares_outstanding", 1.0) or 1.0)

    raw_wacc_range = np.linspace(base_wacc - 0.02, base_wacc + 0.02, grid_size)
    max_tg_bound = min(eff_base_tg + 0.01, float(np.min(raw_wacc_range)) - 0.016)
    half_span = max(0.004, min(0.01, max_tg_bound - eff_base_tg, eff_base_tg - 0.005))
    tg_range = np.linspace(eff_base_tg - half_span, eff_base_tg + half_span, grid_size)
    wacc_range = raw_wacc_range[raw_wacc_range > float(np.max(tg_range)) + 0.015]

    price_grid = []
    for w in wacc_range:
        w_f = float(w)
        row = []
        for tg in tg_range:
            tg_f = float(tg)
            try:
                pv_fcff = sum(cf / ((1.0 + w_f) ** t) for cf, t in zip(base_ufcf, periods))
                eff_g = min(tg_f, w_f - 0.015)
                term_ufcf = last_nopat * (1.0 + eff_g) * (1.0 - base_reinv)
                tv_nom = (term_ufcf / max(0.015, w_f - eff_g)) * tv_scale if last_nopat > 0 else 0.0
                pv_tv = tv_nom / ((1.0 + w_f) ** periods[-1]) if periods else 0.0
                eq_val = pv_fcff + pv_tv + cash_val - debt_val - min_int_val
                row.append(max(0.0, float(eq_val / shares_cnt)))
            except Exception:
                row.append(0.0)
        price_grid.append(row)

    return {
        "terminal_growth_range": tg_range.tolist(),
        "wacc_range": wacc_range.tolist(),
        "price_grid": price_grid,
        "base_terminal_growth": eff_base_tg,
        "base_wacc": float(base_wacc),
    }

