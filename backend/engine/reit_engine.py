"""
REIT & InvIT Equity FFO / AFFO / NDCF + Cap-Rate NAV Valuation Engine
=====================================================================

Replaces broken Corporate EV/FCFF and Bank Tier-1 P/B models for Real Estate
Investment Trusts (REITs) and Infrastructure Investment Trusts (InvITs):
  1. Funds From Operations (FFO) = Normalized Net Income + Real Estate D&A
     (with Ind AS / IFRS SPV cash-distribution NDCF bridge when statutory
     non-cash D&A / deferred taxes depress accounting Net Income below cash
     CFO less Cash Interest).
  2. Adjusted FFO (AFFO / NDCF) = FFO - Recurring Maintenance CapEx
     (stripping discrete property acquisitions ``Purchase Of Investment Properties``
     and growth capex spikes, or applying an explicit 8% upkeep reserve when
     CapEx is unseparated).
  3. Equity Discount Model at CAPM Cost of Equity (Ke) on Distributable AFFO
     projected from Revenue Growth and Target AFFO Margin (% of Revenue).
  4. Institutional Real-Asset Cross-Check: Cap-Rate GAV -> NAV per Unit
     (NOI / Benchmark Cap Rate + Cash - Debt - Minority Interest - Preferred).

Reuses ``compute_bank_cost_of_equity`` and mirrors Equity/DDM output keys so
the existing UI tabs and Excel Formula Engine integrate cleanly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import numpy as np

from .bank_engine import compute_bank_cost_of_equity


def _safe_latest_col(df: Any, columns: List[str], default: float = 0.0) -> float:
    """Return newest non-NaN value from the first matching statement column."""
    if df is None or not hasattr(df, "columns"):
        return default
    for col in columns:
        if col in df.columns:
            series = df[col].dropna()
            if len(series) > 0:
                val = float(series.iloc[0])
                if np.isfinite(val):
                    return val
    return default


def _extract_reit_profile(
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
) -> Dict[str, Any]:
    """Extract normalized FFO, Maintenance CapEx, AFFO/NDCF, NOI, and Cap-Rate NAV metrics."""
    is_ = stock_data.get("income_stmt")
    bs = stock_data.get("balance_sheet")
    cf = stock_data.get("cash_flow")
    info = stock_data.get("info") or {}

    shares_out = float(stock_data.get("shares_outstanding", 1.0) or 1.0)
    if shares_out <= 0:
        shares_out = 1.0

    last_revenue = float(metrics.get("last_revenue", 0.0) or 0.0)
    if last_revenue <= 0:
        last_revenue = max(1e6, _safe_latest_col(is_, ["Total Revenue", "Operating Revenue"], 1e9))

    # 1. Real Estate D&A & Normalized Net Income
    ni_hist = [float(x) for x in (metrics.get("net_income") or []) if x is not None and np.isfinite(x)]
    gaap_ni = float(ni_hist[-1]) if ni_hist else _safe_latest_col(is_, ["Net Income"], 0.0)
    norm_ni = _safe_latest_col(is_, ["Normalized Income"], 0.0)
    recurring_ni = norm_ni if (norm_ni > 0 and gaap_ni > 0) else (gaap_ni if gaap_ni != 0 else norm_ni)

    dna_arr = [float(x) for x in (metrics.get("dna") or []) if x is not None and np.isfinite(x)]
    re_dna = _safe_latest_col(is_, ["Depreciation And Amortization In Income Statement", "Depreciation"], 0.0)
    if re_dna <= 0:
        re_dna = abs(dna_arr[-1]) if dna_arr else abs(_safe_latest_col(cf, ["Depreciation And Amortization"], 0.0))

    cfo = _safe_latest_col(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0.0)
    interest_exp = abs(_safe_latest_col(is_, ["Interest Expense", "Interest Expense Non Operating"], 0.0))
    cfo_after_int = cfo - interest_exp if cfo > interest_exp else 0.0
    cash_div_paid = abs(_safe_latest_col(cf, ["Cash Dividends Paid", "Common Stock Dividend Paid"], 0.0))

    gaap_ffo = recurring_ni + re_dna
    acct_std = str(stock_data.get("accounting_standard") or "US_GAAP")
    used_ndcf_bridge = False

    if gaap_ffo <= 0 and cfo_after_int > 0:
        base_ffo = cfo_after_int
        used_ndcf_bridge = True
    elif acct_std in ("IND_AS", "IFRS") and cfo_after_int > gaap_ffo * 1.15 and cash_div_paid > gaap_ffo:
        # Ind AS / IFRS REITs upstream SPV cash via non-cash D&A/deferred tax add-backs;
        # blend transparently without exceeding confirmed cash distribution capacity.
        base_ffo = min(0.5 * (gaap_ffo + cfo_after_int), cash_div_paid * 1.05)
        used_ndcf_bridge = True
    else:
        base_ffo = max(gaap_ffo, 1.0)

    # 2. Separate Acquisition Outlays vs Maintenance CapEx
    raw_capex = abs(_safe_latest_col(cf, ["Capital Expenditure"], 0.0))
    acquisition_outlays = abs(_safe_latest_col(cf, ["Purchase Of Investment Properties", "Net Business Purchase And Sale"], 0.0))
    estimated_maint_capex = False
    if raw_capex > 0 and raw_capex <= 0.35 * base_ffo:
        maint_capex = raw_capex
    elif raw_capex > 0.35 * base_ffo:
        maint_capex = 0.15 * base_ffo
    else:
        maint_capex = 0.08 * base_ffo
        estimated_maint_capex = True

    base_affo = max(1.0, base_ffo - maint_capex)
    raw_affo_margin = base_affo / last_revenue if last_revenue > 0 else 0.50
    base_affo_margin = max(0.08, min(0.85, raw_affo_margin))

    # 3. Historical AFFO / Revenue Growth
    rev_growth = float(metrics.get("avg_rev_growth", 0.05) or 0.05)
    ebitda_hist = [float(x) for x in (metrics.get("ebitda") or []) if x is not None and np.isfinite(x) and x > 0]
    dna_series = [abs(float(x)) for x in (metrics.get("dna") or []) if x is not None and np.isfinite(x)]
    ffo_growth = rev_growth
    if len(ni_hist) >= 2 and len(dna_series) >= 2:
        ffo_series = [ni_hist[i] + dna_series[i] for i in range(min(len(ni_hist), len(dna_series)))]
        pos_ffo = [x for x in ffo_series if x > 0]
        if len(pos_ffo) >= 2 and pos_ffo[0] > 0:
            cagr_ffo = (pos_ffo[-1] / pos_ffo[0]) ** (1.0 / (len(pos_ffo) - 1)) - 1.0
            if np.isfinite(cagr_ffo):
                ffo_growth = 0.50 * rev_growth + 0.50 * max(-0.05, min(0.25, cagr_ffo))
    default_start_growth = max(-0.02, min(0.22, ffo_growth))

    # 4. Property NOI, Leverage & Cap-Rate GAV/NAV Cross-Check
    ebitda = _safe_latest_col(is_, ["EBITDA"], 0.0)
    if ebitda <= 0 and ebitda_hist:
        ebitda = float(ebitda_hist[-1])
    ebit = _safe_latest_col(is_, ["EBIT", "Operating Income"], 0.0)
    noi = max(ebitda, ebit + re_dna, last_revenue * 0.65)

    total_debt = max(0.0, float(metrics.get("total_debt", _safe_latest_col(bs, ["Total Debt"], 0.0)) or 0.0))
    cash = max(0.0, float(metrics.get("cash_and_equivalents", 0.0) or _safe_latest_col(
        bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"], 0.0
    )))
    minority_interest = max(0.0, float(metrics.get("minority_interest", _safe_latest_col(bs, ["Minority Interest"], 0.0)) or 0.0))
    preferred_stock = max(0.0, float(metrics.get("preferred_stock", _safe_latest_col(bs, ["Preferred Stock", "Preferred Stock Equity"], 0.0)) or 0.0))
    inv_properties = max(0.0, _safe_latest_col(bs, ["Investment Properties", "Net PPE"], 0.0))

    mkt_code = str(stock_data.get("market") or market_profile.get("market") or "US").upper()
    benchmark_cap_rate = 0.080 if mkt_code == "IN" else 0.0575
    gav = noi / benchmark_cap_rate if benchmark_cap_rate > 0 else 0.0
    nav_equity = max(0.0, gav + cash - total_debt - minority_interest - preferred_stock)
    cap_rate_nav_per_unit = float(nav_equity / shares_out) if shares_out > 0 else 0.0

    current_price = float(stock_data.get("current_price", 0.0) or 0.0)
    market_cap = float(stock_data.get("market_cap", 0.0) or (current_price * shares_out))
    market_ev = market_cap + total_debt + minority_interest + preferred_stock - cash
    implied_cap_rate = float(noi / market_ev) if market_ev > 0 else 0.0

    ffo_per_unit = float(base_ffo / shares_out) if shares_out > 0 else 0.0
    affo_per_unit = float(base_affo / shares_out) if shares_out > 0 else 0.0
    p_ffo = float(current_price / ffo_per_unit) if ffo_per_unit > 0 and current_price > 0 else 0.0
    p_affo = float(current_price / affo_per_unit) if affo_per_unit > 0 and current_price > 0 else 0.0
    dividend_yield = float(cash_div_paid / market_cap) if market_cap > 0 else 0.0
    ltv_ratio = float((total_debt - cash) / gav) if gav > 0 else 0.0

    bve_hist = [float(x) for x in (metrics.get("book_value") or []) if x is not None and np.isfinite(x) and x > 0]
    base_bve = float(bve_hist[-1]) if bve_hist else max(0.0, _safe_latest_col(bs, ["Stockholders Equity", "Common Stock Equity"], 0.0))

    return {
        "shares_out": shares_out,
        "last_revenue": float(last_revenue),
        "gaap_ni": float(gaap_ni),
        "recurring_ni": float(recurring_ni),
        "re_dna": float(re_dna),
        "gaap_ffo": float(gaap_ffo),
        "cfo_after_int": float(cfo_after_int),
        "cash_div_paid": float(cash_div_paid),
        "used_ndcf_bridge": used_ndcf_bridge,
        "base_ffo": float(base_ffo),
        "raw_capex": float(raw_capex),
        "acquisition_outlays": float(acquisition_outlays),
        "maint_capex": float(maint_capex),
        "estimated_maint_capex": estimated_maint_capex,
        "base_affo": float(base_affo),
        "base_affo_margin": float(base_affo_margin),
        "default_start_growth": float(default_start_growth),
        "noi": float(noi),
        "total_debt": float(total_debt),
        "cash": float(cash),
        "minority_interest": float(minority_interest),
        "preferred_stock": float(preferred_stock),
        "inv_properties": float(inv_properties),
        "benchmark_cap_rate": float(benchmark_cap_rate),
        "gav": float(gav),
        "nav_equity": float(nav_equity),
        "cap_rate_nav_per_unit": float(cap_rate_nav_per_unit),
        "implied_cap_rate": float(implied_cap_rate),
        "ffo_per_unit": float(ffo_per_unit),
        "affo_per_unit": float(affo_per_unit),
        "p_ffo": float(p_ffo),
        "p_affo": float(p_affo),
        "dividend_yield": float(dividend_yield),
        "ltv_ratio": float(ltv_ratio),
        "base_bve": float(base_bve),
        "bvps": float(base_bve / shares_out) if shares_out > 0 else 0.0,
    }


def _reit_retention_ratio(g_next: float, terminal_growth: float) -> float:
    """Compute required AFFO retention above contractual rent escalators [5%..25%]."""
    return float(min(0.25, max(0.05, max(0.0, g_next - 0.70 * terminal_growth) / 0.12)))


def run_reit_valuation(
    start_growth: float,
    target_affo_margin: float,
    cost_of_equity: float,
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float = 0.055,
    projection_years: int = 5,
    use_mid_year: bool = True,
) -> Dict[str, Any]:
    """Run Multi-Stage REIT / InvIT Distributable AFFO (NDCF) Discount Valuation + Cap-Rate NAV Cross-Check."""
    prof = _extract_reit_profile(metrics, stock_data, market_profile)
    shares_out = prof["shares_out"]
    last_rev = prof["last_revenue"]
    base_affo_margin = prof["base_affo_margin"]
    target_margin = max(0.08, min(0.85, float(target_affo_margin)))

    margin_schedule = np.linspace(base_affo_margin, target_margin, projection_years)
    step_fractions = np.linspace(0.0, 1.0, projection_years) if projection_years > 1 else np.array([0.0])
    growth_excess = max(0.0, start_growth - terminal_growth)
    fade_blend = min(1.0, max(0.0, (growth_excess - 0.03) / 0.06))
    growth_fade_exponent = 1.0 + 0.35 * fade_blend
    growth_schedule = start_growth - (start_growth - terminal_growth) * (step_fractions ** growth_fade_exponent)

    proj_revenue: List[float] = []
    proj_affo: List[float] = []
    proj_retention_rate: List[float] = []
    proj_reinvested: List[float] = []
    proj_distributable_affo: List[float] = []

    cur_rev = last_rev
    for yr in range(projection_years):
        g = float(growth_schedule[yr])
        m = float(margin_schedule[yr])
        cur_rev = cur_rev * (1.0 + g)
        affo_yr = cur_rev * m

        g_next = float(growth_schedule[yr + 1]) if (yr + 1) < projection_years else terminal_growth
        ret_b = _reit_retention_ratio(g_next, terminal_growth)
        reinvested = affo_yr * ret_b
        ndcf_payout = affo_yr * (1.0 - ret_b)

        proj_revenue.append(float(cur_rev))
        proj_affo.append(float(affo_yr))
        proj_retention_rate.append(float(ret_b))
        proj_reinvested.append(float(reinvested))
        proj_distributable_affo.append(float(ndcf_payout))

    discount_periods = [i + 0.5 if use_mid_year else float(i + 1) for i in range(projection_years)]
    discount_factors = [(1.0 + cost_of_equity) ** t for t in discount_periods]
    pv_ndcf_list = [f / df for f, df in zip(proj_distributable_affo, discount_factors)]
    pv_ndcf = sum(pv_ndcf_list)

    terminal_value_valid = True
    terminal_value_note = ""
    terminal_growth_capped = False
    effective_terminal_growth = terminal_growth

    if cost_of_equity <= terminal_growth:
        terminal_value = 0.0
        pv_terminal_value = 0.0
        terminal_value_valid = False
        terminal_value_note = "Cost of Equity (Ke) must exceed terminal growth rate for REIT AFFO perpetuity model."
    else:
        spread = cost_of_equity - terminal_growth
        if spread < 0.020:
            effective_terminal_growth = cost_of_equity - 0.020
            terminal_growth_capped = True
            terminal_value_note = (
                f"Terminal growth capped at {effective_terminal_growth*100:.1f}% to preserve minimum 2.0% Ke spread."
            )
            eff_spread = 0.020
        else:
            eff_spread = spread
        term_ret = _reit_retention_ratio(effective_terminal_growth, effective_terminal_growth)
        term_affo = proj_affo[-1] * (1.0 + effective_terminal_growth)
        term_ndcf = term_affo * (1.0 - term_ret)
        terminal_value = term_ndcf / eff_spread
        pv_terminal_value = terminal_value / discount_factors[-1]

    equity_value = pv_ndcf + pv_terminal_value
    implied_price = max(0.0, equity_value / shares_out) if shares_out > 0 else 0.0

    # Stressed Cap-Rate NAV (+75 bps expansion) & +50 bps Ke
    stressed_cap_rate = prof["benchmark_cap_rate"] + 0.0075
    stressed_gav = prof["noi"] / stressed_cap_rate if stressed_cap_rate > 0 else 0.0
    stressed_nav = max(
        0.0,
        stressed_gav + prof["cash"] - prof["total_debt"] - prof["minority_interest"] - prof["preferred_stock"],
    )
    cap_rate_stress_price = float(stressed_nav / shares_out) if shares_out > 0 else 0.0

    tv_share_of_ev = float(pv_terminal_value / equity_value) if equity_value > 0 else 0.0
    tv_share_flag = bool(tv_share_of_ev > 0.78)
    tv_share_note = (
        f"Terminal REIT Equity Value accounts for {tv_share_of_ev*100:.1f}% of Total Implied Equity Value."
        if tv_share_flag
        else None
    )

    implied_p_affo = float(implied_price / prof["affo_per_unit"]) if prof["affo_per_unit"] > 0 else 15.0
    funding_note = (
        f"REIT/InvIT AFFO & Cap-Rate Engine: Base FFO={prof['base_ffo']:,.0f}, Maint CapEx={prof['maint_capex']:,.0f}"
        f"{' (est 8% FFO reserve)' if prof['estimated_maint_capex'] else ''}, AFFO={prof['base_affo']:,.0f}. "
        f"Cap-Rate GAV ({prof['benchmark_cap_rate']*100:.2f}% cap) NAV={prof['cap_rate_nav_per_unit']:,.2f}/unit; "
        f"+75 bps cap-rate stress NAV={cap_rate_stress_price:,.2f}/unit."
    )

    return {
        "implied_price": float(implied_price),
        "enterprise_value": float(equity_value),
        "equity_value": float(equity_value),
        "projected_revenue": [float(r) for r in proj_revenue],
        "projected_ufcf": [float(f) for f in proj_distributable_affo],
        "projected_nopat": [float(a) for a in proj_affo],
        "projected_dna": [float(prof["re_dna"]) for _ in range(projection_years)],
        "projected_capex": [float(r) for r in proj_reinvested],
        "projected_dnwc": [0.0] * projection_years,
        "growth_schedule": growth_schedule.tolist(),
        "margin_schedule": margin_schedule.tolist(),
        "pv_ufcf": float(pv_ndcf),
        "pv_ufcf_list": [float(p) for p in pv_ndcf_list],
        "discount_periods": discount_periods,
        "discount_factors": [float(1.0 / df) for df in discount_factors],
        "terminal_value": float(terminal_value),
        "pv_terminal_value": float(pv_terminal_value),
        "terminal_value_valid": terminal_value_valid,
        "terminal_value_note": terminal_value_note,
        "terminal_growth_capped": terminal_growth_capped,
        "effective_terminal_growth": float(effective_terminal_growth),
        "tv_share_of_ev": tv_share_of_ev,
        "tv_share_flag": tv_share_flag,
        "tv_share_note": tv_share_note,
        "tax_rate": 0.0,
        "terminal_growth": float(terminal_growth),
        "use_mid_year": use_mid_year,
        # Dedicated REIT / InvIT Equity Model Fields
        "is_financial": False,
        "is_reit": True,
        "is_equity_model": True,
        "model_type": "REIT_INVIT_AFFO",
        "base_revenue": float(last_rev),
        "base_ffo": prof["base_ffo"],
        "gaap_ffo": prof["gaap_ffo"],
        "base_affo": prof["base_affo"],
        "maint_capex": prof["maint_capex"],
        "estimated_maint_capex": prof["estimated_maint_capex"],
        "acquisition_outlays": prof["acquisition_outlays"],
        "used_ndcf_bridge": prof["used_ndcf_bridge"],
        "re_dna": prof["re_dna"],
        "base_net_income": float(prof["base_affo"]),
        "base_bve": float(prof["nav_equity"]),
        "bvps": float(prof["cap_rate_nav_per_unit"]),
        "base_roe": float(base_affo_margin),
        "target_roe": float(target_margin),
        "base_affo_margin": float(base_affo_margin),
        "target_affo_margin": float(target_margin),
        "growth_fade_exponent": float(growth_fade_exponent),
        "cost_of_equity": float(cost_of_equity),
        "justified_pb": float(implied_p_affo),
        "justified_price": float(prof["cap_rate_nav_per_unit"]),
        "cap_rate_nav_per_unit": float(prof["cap_rate_nav_per_unit"]),
        "benchmark_cap_rate": float(prof["benchmark_cap_rate"]),
        "implied_cap_rate": float(prof["implied_cap_rate"]),
        "noi": float(prof["noi"]),
        "gav": float(prof["gav"]),
        "ltv_ratio": float(prof["ltv_ratio"]),
        "ffo_per_unit": float(prof["ffo_per_unit"]),
        "affo_per_unit": float(prof["affo_per_unit"]),
        "p_ffo": float(prof["p_ffo"]),
        "p_affo": float(prof["p_affo"]),
        "dividend_yield": float(prof["dividend_yield"]),
        "wholesale_leverage_ratio": float(prof["ltv_ratio"]),
        "credit_cost_stress_price": float(cap_rate_stress_price),
        "cap_rate_stress_price": float(cap_rate_stress_price),
        "funding_model_note": funding_note,
        "projected_net_income": [float(a) for a in proj_affo],
        "projected_fcfe": [float(f) for f in proj_distributable_affo],
        "retention_schedule": [float(b) for b in proj_retention_rate],
        "payout_schedule": [float(1.0 - b) for b in proj_retention_rate],
        "roe_schedule": [float(m) for m in margin_schedule],
    }


def run_reit_monte_carlo(
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float,
    projection_years: int = 5,
    iterations: int = 1000,
    base_growth: Optional[float] = None,
    base_affo_margin: Optional[float] = None,
    base_ke: Optional[float] = None,
) -> Dict[str, Any]:
    """Run vectorized Monte Carlo over REIT Growth, AFFO Margin, and Cost of Equity (Ke)."""
    prof = _extract_reit_profile(metrics, stock_data, market_profile)
    g_mean = float(base_growth) if base_growth is not None else prof["default_start_growth"]
    g_std = max(0.015, float(metrics.get("std_rev_growth", 0.03) or 0.03))

    m_mean = float(base_affo_margin) if base_affo_margin is not None else prof["base_affo_margin"]
    m_std = 0.035

    ke_data = compute_bank_cost_of_equity(stock_data, market_profile)
    ke_mean = float(base_ke) if base_ke is not None else float(ke_data["cost_of_equity"])
    ke_std = 0.0125

    rng = np.random.default_rng(42)
    sim_growth = np.clip(rng.normal(g_mean, g_std, iterations), -0.04, 0.25)
    sim_margin = np.clip(rng.normal(m_mean, m_std, iterations), 0.08, 0.85)
    sim_ke = np.clip(rng.normal(ke_mean, ke_std, iterations), terminal_growth + 0.005, 0.22)

    n = len(sim_growth)
    shares_out = prof["shares_out"]
    last_rev = prof["last_revenue"]
    base_m = prof["base_affo_margin"]

    steps = np.arange(projection_years, dtype=float) / float(projection_years - 1) if projection_years > 1 else np.zeros(1)
    fade_blend = np.clip((sim_growth - terminal_growth - 0.03) / 0.06, 0.0, 1.0)
    fade_exponents = 1.0 + 0.35 * fade_blend
    growth_schedule = sim_growth[:, None] - (sim_growth[:, None] - terminal_growth) * (steps[None, :] ** fade_exponents[:, None])
    margin_schedule = np.linspace(base_m, sim_margin, projection_years, axis=1)

    discount_periods = np.arange(projection_years, dtype=float) + 0.5
    discount_factors = (1.0 + sim_ke[:, None]) ** discount_periods[None, :]

    cur_rev = np.full(n, last_rev, dtype=float)
    pv_ndcf = np.zeros(n, dtype=float)
    for yr in range(projection_years):
        g = growth_schedule[:, yr]
        g_next = growth_schedule[:, yr + 1] if (yr + 1) < projection_years else np.full(n, terminal_growth, dtype=float)
        m = margin_schedule[:, yr]
        cur_rev = cur_rev * (1.0 + g)
        affo_yr = cur_rev * m
        ret_b = np.clip(np.maximum(0.0, g_next - 0.70 * terminal_growth) / 0.12, 0.05, 0.25)
        pv_ndcf += (affo_yr * (1.0 - ret_b)) / discount_factors[:, yr]

    valid_tv = sim_ke > terminal_growth
    spread = sim_ke - terminal_growth
    narrow = valid_tv & (spread < 0.020)
    eff_g = np.where(narrow, sim_ke - 0.020, terminal_growth)
    eff_spread = np.where(narrow, 0.020, np.where(valid_tv, spread, 1.0))
    term_ret = np.clip(np.maximum(0.0, eff_g * 0.30) / 0.12, 0.05, 0.25)
    term_affo = (cur_rev * margin_schedule[:, -1]) * (1.0 + eff_g)
    pv_terminal = np.where(valid_tv, (term_affo * (1.0 - term_ret)) / eff_spread, 0.0) / discount_factors[:, -1]

    all_prices = np.maximum(0.0, (pv_ndcf + pv_terminal) / shares_out) if shares_out > 0 else np.zeros(n)
    valid_mask = (all_prices > 0) & np.isfinite(all_prices)
    sim_arr = all_prices[valid_mask]
    valid_count = int(len(sim_arr))
    if valid_count == 0:
        sim_arr = np.array([0.0])

    current_price = float(stock_data.get("current_price", 1.0) or 1.0)
    stats = {
        "mean": float(np.mean(sim_arr)),
        "median": float(np.median(sim_arr)),
        "std": float(np.std(sim_arr)),
        "std_dev": float(np.std(sim_arr)),
        "p5": float(np.percentile(sim_arr, 5)),
        "p10": float(np.percentile(sim_arr, 10)),
        "p25": float(np.percentile(sim_arr, 25)),
        "p75": float(np.percentile(sim_arr, 75)),
        "p90": float(np.percentile(sim_arr, 90)),
        "p95": float(np.percentile(sim_arr, 95)),
        "prob_undervalued": float(np.mean(sim_arr > current_price)) if len(sim_arr) > 0 else 0.0,
        "zero_price_simulations": int(iterations - valid_count),
        "positive_price_simulations": valid_count,
    }
    return {
        "stats": stats,
        "simulated_prices": sim_arr.tolist(),
        "sim_growth": sim_growth.tolist(),
        "sim_margin": sim_margin.tolist(),
        "sim_wacc": sim_ke.tolist(),
        "seed": 42,
        "requested_iterations": int(iterations),
        "candidate_draws_sampled": int(iterations),
        "total_candidate_valid": valid_count,
        "rejected_draws": int(iterations - valid_count),
        "unused_valid_oversample": 0,
        "actual_iterations": int(valid_count),
        "total_simulations": int(iterations),
        "valid_simulations": valid_count,
        "invalid_simulations": int(iterations - valid_count),
        "invalid_simulation_reasons": {
            "ke_too_low": int(np.sum(sim_ke <= terminal_growth)),
            "zero_or_invalid_equity": int(iterations - valid_count),
        },
        "corr_sample_size": 0,
        "corr_method": "reit_affo_independent_draws",
        "is_corr_regularized": False,
        "hist_corr_gm": 0.0,
    }


def generate_reit_sensitivity_grid(
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float,
    projection_years: int = 5,
    base_growth: Optional[float] = None,
    base_affo_margin: Optional[float] = None,
    base_ke: Optional[float] = None,
) -> Dict[str, Any]:
    """Generate 5x5 sensitivity grid: AFFO/Revenue Growth vs Cost of Equity (Ke)."""
    prof = _extract_reit_profile(metrics, stock_data, market_profile)
    ke_data = compute_bank_cost_of_equity(stock_data, market_profile)
    mid_ke = float(base_ke) if base_ke is not None else float(ke_data["cost_of_equity"])
    mid_growth = float(base_growth) if base_growth is not None else prof["default_start_growth"]
    t_margin = float(base_affo_margin) if base_affo_margin is not None else prof["base_affo_margin"]

    growth_steps = [mid_growth - 0.02, mid_growth - 0.01, mid_growth, mid_growth + 0.01, mid_growth + 0.02]
    ke_steps = [mid_ke - 0.01, mid_ke - 0.005, mid_ke, mid_ke + 0.005, mid_ke + 0.01]

    grid = [
        [
            0.0 if k <= terminal_growth else run_reit_valuation(
                start_growth=g,
                target_affo_margin=t_margin,
                cost_of_equity=k,
                metrics=metrics,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                use_mid_year=True,
            ).get("implied_price", 0.0)
            for g in growth_steps
        ]
        for k in ke_steps
    ]
    return {
        "wacc_range": ke_steps,
        "growth_range": growth_steps,
        "grid": grid,
        "price_grid": grid,
        "base_growth": mid_growth,
        "base_wacc": mid_ke,
    }


def generate_reit_margin_sensitivity_grid(
    metrics: dict,
    stock_data: dict,
    market_profile: dict,
    terminal_growth: float,
    projection_years: int = 5,
    base_growth: Optional[float] = None,
    base_affo_margin: Optional[float] = None,
    base_ke: Optional[float] = None,
) -> Dict[str, Any]:
    """Generate 5x5 sensitivity grid: Target AFFO Margin vs Cost of Equity (Ke)."""
    prof = _extract_reit_profile(metrics, stock_data, market_profile)
    ke_data = compute_bank_cost_of_equity(stock_data, market_profile)
    mid_ke = float(base_ke) if base_ke is not None else float(ke_data["cost_of_equity"])
    mid_growth = float(base_growth) if base_growth is not None else prof["default_start_growth"]
    t_margin = float(base_affo_margin) if base_affo_margin is not None else prof["base_affo_margin"]

    margin_steps = [t_margin - 0.04, t_margin - 0.02, t_margin, t_margin + 0.02, t_margin + 0.04]
    ke_steps = [mid_ke - 0.01, mid_ke - 0.005, mid_ke, mid_ke + 0.005, mid_ke + 0.01]

    grid = [
        [
            0.0 if k <= terminal_growth else run_reit_valuation(
                start_growth=mid_growth,
                target_affo_margin=m,
                cost_of_equity=k,
                metrics=metrics,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                use_mid_year=True,
            ).get("implied_price", 0.0)
            for m in margin_steps
        ]
        for k in ke_steps
    ]
    return {
        "wacc_range": ke_steps,
        "margin_range": margin_steps,
        "roe_range": margin_steps,
        "grid": grid,
        "price_grid": grid,
        "base_margin": t_margin,
        "base_wacc": mid_ke,
    }
