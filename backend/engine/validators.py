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
    
    # Compute Cash (including Short-Term Marketable Securities, consistent with EV bridge)
    cash = float(metrics.get('cash_and_equivalents', 0.0) or 0.0)
    if cash <= 0.0:
        balance_sheet = stock_data.get('balance_sheet')
        if balance_sheet is not None and not balance_sheet.empty:
            if 'Cash Cash Equivalents And Short Term Investments' in balance_sheet.columns:
                cash_vals = balance_sheet['Cash Cash Equivalents And Short Term Investments'].dropna()
                if len(cash_vals) > 0:
                    cash = float(cash_vals.iloc[0])
            elif 'Cash And Cash Equivalents' in balance_sheet.columns:
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
        if multiple_gap_pct < 0.50:
            status = "PASS"
        elif multiple_gap_pct <= 0.80:
            status = "WARNING"
        else:
            status = "FLAG"

    warning_msg: Optional[str] = None
    if dcf_result.get("equity_value", 1.0) <= 0:
        status = "FLAG"
        warning_msg = "Net debt claims exceed DCF Enterprise Value, resulting in zero baseline equity value."
    elif not dcf_result.get("terminal_value_valid", True):
        status = "FLAG"
        warning_msg = "Year-5 projected cash flow is negative; perpetual Gordon Growth terminal value cannot be capitalized."
    elif trailing_ebitda <= 0:
        warning_msg = "Trailing EBITDA is negative or zero; switched cross-check to EV/Sales and applied turnaround margin convergence."
    elif dcf_result.get("tv_share_flag", False):
        warning_msg = "Terminal Value accounts for >75% of Enterprise Value; valuation is highly sensitive to terminal WACC and growth."

    return {
        "metric_used": metric_used,
        "trailing_ebitda": float(trailing_ebitda),
        "trailing_revenue": float(last_revenue),
        "market_ev": float(market_ev),
        "market_multiple": float(market_multiple) if market_multiple is not None else None,
        "model_multiple": float(model_multiple) if model_multiple is not None else None,
        "multiple_gap_pct": float(multiple_gap_pct),
        "status": status,
        "warning": warning_msg,
        "exit_implied_price": dcf_result.get("exit_implied_price"),
        "benchmark_exit_multiple": dcf_result.get("benchmark_exit_multiple"),
        "implied_exit_multiple": dcf_result.get("implied_exit_multiple"),
    }


def validate_bank_valuation(
    dcf_result: Dict[str, Any],
    stock_data: Dict[str, Any],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Computes P/B (Price-to-Book) validation cross-check for banking and financial services firms.
    Compares Market P/B vs Implied Model P/B vs Justified Gordon P/B.
    """
    current_price = float(stock_data.get("current_price", 0.0))
    bvps = float(dcf_result.get("bvps", 0.0) or metrics.get("bvps", 0.0) or 0.0)
    implied_price = float(dcf_result.get("implied_price", 0.0))
    justified_pb = float(dcf_result.get("justified_pb", 0.0) or 0.0)
    justified_price = float(dcf_result.get("justified_price", 0.0) or 0.0)

    market_pb = (current_price / bvps) if bvps > 0 else None
    model_pb = (implied_price / bvps) if bvps > 0 else None

    if current_price > 0:
        gap = (implied_price - current_price) / current_price
    else:
        gap = 0.0

    multiple_gap_pct = abs(gap)

    if multiple_gap_pct <= 0.35:
        status = "PASS"
    elif multiple_gap_pct <= 0.65:
        status = "WARNING"
    else:
        status = "FLAG"

    warning_msg: Optional[str] = None
    avg_roe = float(metrics.get("avg_roe", 0.14) or 0.14)
    ke = float(dcf_result.get("cost_of_equity", 0.12) or 0.12)
    if avg_roe < ke:
        warning_msg = (
            f"4-Yr Avg ROE ({avg_roe*100:.1f}%) is below Cost of Equity ({ke*100:.1f}%), "
            f"which compresses Justified Gordon P/B ({justified_pb:.2f}x) below 1.0x Book Value."
        )

    return {
        "status": status,
        "warning": warning_msg,
        "metric_used": "price_to_book",
        "market_multiple": float(market_pb) if market_pb is not None else None,
        "model_multiple": float(model_pb) if model_pb is not None else None,
        "multiple_gap_pct": float(multiple_gap_pct),
        "justified_pb": justified_pb,
        "justified_price": justified_price,
        "bvps": bvps,
        "gap": float(gap),
        "trailing_ebitda": 1.0,
        "is_financial": True,
    }


def generate_verdict(
    current_price: float,
    mc_stats: Dict[str, float],
    terminal_value_valid: bool = True,
    mc_valid: bool = True,
    is_distressed: bool = False,
) -> Dict[str, Any]:
    """
    Generates a BUY/SELL/HOLD or DCF UNRELIABLE / DISTRESSED verdict based on Monte Carlo percentiles.
    """
    p5 = mc_stats.get('p5')
    p25 = mc_stats.get('p25')
    median = mc_stats.get('median')
    p75 = mc_stats.get('p75')
    p95 = mc_stats.get('p95')
    zero_price_pct = mc_stats.get('zero_price_pct', 0.0)

    import math
    def is_invalid(val):
        return val is None or math.isnan(val) or math.isinf(val) or val < 0.0

    # Point 7: Change verdict and label for high distress / equity wipeout names
    # Equity in a distressed firm behaves like an option; truncated DCF is unreliable
    distressed_firm = is_distressed or (zero_price_pct > 0.20) or (p25 is not None and p25 <= 0.0) or (median == 0.0 and mc_valid)
    if distressed_firm:
        distressed_upside = -100.0 if (is_invalid(median) or median == 0.0) else float(((median / current_price) - 1) * 100 if current_price > 0 else 0.0)
        return {
            "verdict": "DCF UNRELIABLE / DISTRESSED",
            "description": (
                f"Severe financial distress or equity wipeout detected ({zero_price_pct*100:.1f}% equity wipeout simulations). "
                "Equity in a distressed firm behaves like an option; truncated-at-zero DCF is an unreliable basis for a fair-value call."
            ),
            "upside_pct": float(distressed_upside),
            "is_distressed": True,
        }

    if not terminal_value_valid or not mc_valid or is_invalid(p5) or is_invalid(p95) or is_invalid(median) or median == 0.0:
        return {
            "verdict": "N/A",
            "description": "Valuation assumptions do not currently support a valid terminal value or sufficient valid simulations.",
            "upside_pct": 0.0,
            "is_distressed": False,
        }
    
    upside_pct = ((median / current_price) - 1) * 100 if current_price > 0 else 0.0

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
        
    return {
        "verdict": verdict,
        "description": description,
        "upside_pct": float(upside_pct),
        "is_distressed": False,
    }
