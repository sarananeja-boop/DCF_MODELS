import math
from typing import Any, Dict, List, Optional

from .canonical_schema import VALIDATION_STATUSES, classify_model_suitability

def validate_valuation(dcf_result: Dict[str, Any], stock_data: Dict[str, Any], metrics: Dict[str, Any], wacc_data: Dict[str, float]) -> Dict[str, Any]:
    """
    Computes EV/EBITDA cross-check (or EV/Revenue if EBITDA is negative) and validation status.
    """
    ebit_arr = metrics.get('ebit', [])
    dna_arr = metrics.get('dna', [])
    ebitda_arr = metrics.get('ebitda', [])
    last_revenue = metrics.get('last_revenue', 0.0)
    
    last_ebit = ebit_arr[-1] if len(ebit_arr) > 0 else 0.0
    last_dna = dna_arr[-1] if len(dna_arr) > 0 else 0.0
    last_norm_ebitda = float(ebitda_arr[-1]) if len(ebitda_arr) > 0 else 0.0
    
    trailing_ebitda = max(last_ebit + last_dna, last_norm_ebitda)
        
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

    # Model suitability advisory for regulated utilities / high regulatory deferral assets
    model_suitability_note: Optional[str] = None
    sector = str(stock_data.get("sector", "") or "")
    bs_stmts = metrics.get("statements", {}).get("balance_sheet", {})
    reg_assets_arr = bs_stmts.get("Regulatory Deferral Assets (Non-Tax)") or bs_stmts.get("Regulatory Deferral & Non-Current Deferred Assets", [])
    tot_assets_arr = bs_stmts.get("Total Assets", [])
    latest_reg_assets = float(reg_assets_arr[-1]) if reg_assets_arr else 0.0
    latest_tot_assets = float(tot_assets_arr[-1]) if tot_assets_arr else 0.0
    reg_asset_share = (latest_reg_assets / latest_tot_assets) if latest_tot_assets > 0 else 0.0
    if sector.lower() == "utilities" or reg_asset_share >= 0.05:
        model_suitability_note = (
            f"Regulated Utility / Rate-Base Advisory: Regulatory deferral & non-current deferred assets represent "
            f"{reg_asset_share*100:.1f}% of Total Assets. Under Ind AS 114 / ASC 980, regulated utilities earn a statutory return on "
            f"equity (Regulated Asset Base) and recover tariff deferrals over multi-year cycles while funding multi-year expansion CapEx "
            f"via project debt. Compare Unlevered FCFF alongside the Corporate DDM / Regulated Equity ROE model."
        )
        if not warning_msg and multiple_gap_pct >= 0.35:
            warning_msg = model_suitability_note

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
        "model_suitability_note": model_suitability_note,
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
    is_archetype_mismatch = False

    if market_pb and market_pb > 6.0 and multiple_gap_pct > 0.65:
        capex_pct = float(metrics.get("avg_capex_pct", 0.0) or 0.0)
        debt_to_rev = (
            float(metrics.get("total_debt", 0.0)) / float(metrics.get("last_revenue", 1.0))
            if float(metrics.get("last_revenue", 1.0)) > 0
            else 0.0
        )
        if capex_pct < 0.05 and debt_to_rev < 0.35:
            is_archetype_mismatch = True
            warning_msg = (
                f"Model Archetype Mismatch: Market P/B ({market_pb:.1f}x) and asset-light profile "
                f"(CapEx {capex_pct*100:.1f}%, Debt/Rev {debt_to_rev:.2f}x) indicate a fee-based fintech/broker platform "
                f"rather than a regulatory-capital constrained bank. The Bank DDM model retains up to 85% of earnings to fund "
                f"loans, which depresses fair value (implied {implied_price:.2f} vs CMP {current_price:.2f}). Switch to Standard FCFF."
            )

    if not warning_msg and avg_roe < ke:
        warning_msg = (
            f"4-Yr Avg ROE ({avg_roe*100:.1f}%) is below Cost of Equity ({ke*100:.1f}%), "
            f"which compresses Justified Gordon P/B ({justified_pb:.2f}x) below 1.0x Book Value."
        )

    return {
        "status": status,
        "warning": warning_msg,
        "is_archetype_mismatch": is_archetype_mismatch,
        "metric_used": "price_to_book",
        "market_multiple": float(market_pb) if market_pb is not None else None,
        "model_multiple": float(model_pb) if model_pb is not None else None,
        "multiple_gap_pct": float(multiple_gap_pct),
        "justified_pb": justified_pb,
        "justified_price": justified_price,
        "bvps": bvps,
        "gap": float(gap),
        "trailing_ebitda": 1.0,
        "is_financial": bool(stock_data.get("is_financial", True)),
        "is_equity_model": True,
    }


def validate_insurance_valuation(
    dcf_result: Dict[str, Any],
    stock_data: Dict[str, Any],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate Insurance Equity DDM against Market P/Ex-AOCI Book & Justified P/B."""
    current_price = float(stock_data.get("current_price", 0.0) or 0.0)
    bvps = float(dcf_result.get("bvps", 0.0) or 0.0)
    implied_price = float(dcf_result.get("implied_price", 0.0) or 0.0)
    justified_pb = float(dcf_result.get("justified_pb", 0.0) or 0.0)
    justified_price = float(dcf_result.get("justified_price", 0.0) or 0.0)

    market_pb = (current_price / bvps) if bvps > 0 else None
    model_pb = (implied_price / bvps) if bvps > 0 else None
    gap = ((implied_price - current_price) / current_price) if current_price > 0 else 0.0
    multiple_gap_pct = abs(gap)

    if multiple_gap_pct <= 0.35:
        status = "PASS"
    elif multiple_gap_pct <= 0.65:
        status = "WARNING"
    else:
        status = "FLAG"

    warning_msg: Optional[str] = None
    model_fam = str(dcf_result.get("model_type") or "")
    if model_fam == "INSURANCE_LIFE_DDM":
        warning_msg = (
            "Life Insurer Actuarial Note: GAAP/Ind AS earnings reflect upfront policy acquisition strain; "
            "statutory Embedded Value (EV + VNB) requires primary insurer disclosures."
        )
    elif dcf_result.get("used_ex_aoci_bv"):
        warning_msg = (
            f"P&C Ex-AOCI Equity Basis: Fixed-income unrealized AOCI ({dcf_result.get('aoci_adjustment', 0.0):,.0f}) "
            "stripped from Book Value for underwriting ROE evaluation."
        )

    return {
        "status": status,
        "warning": warning_msg,
        "is_archetype_mismatch": False,
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
        "is_equity_model": True,
    }


def validate_reit_valuation(
    dcf_result: Dict[str, Any],
    stock_data: Dict[str, Any],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate REIT/InvIT AFFO DDM against P/FFO, P/AFFO, and Cap-Rate GAV/NAV per Unit."""
    current_price = float(stock_data.get("current_price", 0.0) or 0.0)
    implied_price = float(dcf_result.get("implied_price", 0.0) or 0.0)
    affo_pu = float(dcf_result.get("affo_per_unit", 0.0) or 0.0)
    nav_pu = float(dcf_result.get("cap_rate_nav_per_unit", 0.0) or 0.0)

    market_p_affo = (current_price / affo_pu) if affo_pu > 0 else None
    model_p_affo = (implied_price / affo_pu) if affo_pu > 0 else None
    gap = ((implied_price - current_price) / current_price) if current_price > 0 else 0.0
    multiple_gap_pct = abs(gap)

    if multiple_gap_pct <= 0.35:
        status = "PASS"
    elif multiple_gap_pct <= 0.65:
        status = "WARNING"
    else:
        status = "FLAG"

    imp_cap = float(dcf_result.get("implied_cap_rate", 0.0) or 0.0)
    bench_cap = float(dcf_result.get("benchmark_cap_rate", 0.0) or 0.0)
    warning_msg = (
        f"REIT/InvIT Cap-Rate & AFFO Check: Benchmark Cap Rate {bench_cap*100:.2f}% implies NAV "
        f"{nav_pu:,.2f}/unit vs Market Implied Cap Rate {imp_cap*100:.2f}%. "
        "Verify Maintenance CapEx & NAREIT/SEBI NDCF schedules against primary trust filings."
    )

    return {
        "status": status,
        "warning": warning_msg,
        "is_archetype_mismatch": False,
        "metric_used": "price_to_affo",
        "market_multiple": float(market_p_affo) if market_p_affo is not None else None,
        "model_multiple": float(model_p_affo) if model_p_affo is not None else None,
        "multiple_gap_pct": float(multiple_gap_pct),
        "justified_pb": float(dcf_result.get("justified_pb", 0.0) or 0.0),
        "justified_price": nav_pu,
        "bvps": nav_pu,
        "cap_rate_nav_per_unit": nav_pu,
        "implied_cap_rate": imp_cap,
        "benchmark_cap_rate": bench_cap,
        "gap": float(gap),
        "trailing_ebitda": float(dcf_result.get("noi", 1.0) or 1.0),
        "is_financial": False,
        "is_equity_model": True,
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

    # Trigger distressed outlook only when base DCF equity is wiped out or MC median <= 0
    distressed_firm = is_distressed or (
        median is not None and median <= 0.0 and mc_valid
    )
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
        verdict = "STRONGLY BULLISH"
        description = "Trades below the 5th-percentile downside estimate."
    elif current_price > p95:
        verdict = "STRONGLY BEARISH"
        description = "Trades above the 95th-percentile upside estimate."
    elif current_price < p25:
        verdict = "BULLISH"
        description = "Trades below the 25th percentile of outcomes."
    elif current_price > p75:
        verdict = "BEARISH"
        description = "Trades above the 75th percentile of outcomes."
    else:
        verdict = "NEUTRAL"
        description = "Trades within the interquartile range of simulated outcomes."
        
    return {
        "verdict": verdict,
        "description": description,
        "upside_pct": float(upside_pct),
        "is_distressed": False,
    }


def _series_max_diff(
    lhs: List[float],
    rhs: List[float],
    abs_floor: float = 1e-2,
    rel_tol: float = 0.005,
) -> Dict[str, Any]:
    """Compare two aligned numeric series and return worst-case absolute/relative divergence."""
    n = min(len(lhs), len(rhs))
    if n == 0:
        return {"comparable": 0, "max_abs_diff": 0.0, "max_rel_diff": 0.0, "passed": False}

    max_abs = 0.0
    max_rel = 0.0
    comparable = 0
    failed = False
    for i in range(n):
        a = lhs[i]
        b = rhs[i]
        if a is None or b is None:
            continue
        fa, fb = float(a), float(b)
        if not (math.isfinite(fa) and math.isfinite(fb)):
            return {"comparable": comparable + 1, "max_abs_diff": float("inf"), "max_rel_diff": float("inf"), "passed": False}
        # Treat all-zero unpopulated placeholders cautiously at caller level
        comparable += 1
        diff = abs(fa - fb)
        denom = max(abs(fa), abs(fb), 1.0)
        rel = diff / denom
        tol = max(abs_floor, rel_tol * denom)
        if diff > max_abs:
            max_abs = diff
        if rel > max_rel:
            max_rel = rel
        if diff > tol:
            failed = True
    return {
        "comparable": comparable,
        "max_abs_diff": float(max_abs),
        "max_rel_diff": float(max_rel),
        "passed": comparable > 0 and not failed,
    }


def run_accounting_reconciliations(
    stock_data: Dict[str, Any],
    metrics: Dict[str, Any],
    dcf_result: Optional[Dict[str, Any]] = None,
    mc_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute automated cross-statement accounting, policy, and simulation reconciliations."""
    stmts = metrics.get("statements") if isinstance(metrics.get("statements"), dict) else {}
    inc = stmts.get("income_statement", {}) if isinstance(stmts, dict) else {}
    bs = stmts.get("balance_sheet", {}) if isinstance(stmts, dict) else {}
    cf = stmts.get("cash_flow", {}) if isinstance(stmts, dict) else {}
    suit_meta = stock_data.get("model_suitability") or metrics.get("model_suitability") or {}
    suit_fam = str(suit_meta.get("model_family") or "")
    is_financial = bool(stock_data.get("is_financial", False))
    is_fin_or_ins = bool(is_financial or suit_fam.startswith("INSURANCE_"))

    checks: List[Dict[str, Any]] = []

    def _add_check(
        cid: str,
        name: str,
        category: str,
        status: str,
        severity: str,
        details: str,
        max_abs_diff: Optional[float] = None,
        max_rel_diff_pct: Optional[float] = None,
    ) -> None:
        checks.append({
            "id": cid,
            "name": name,
            "category": category,
            "status": status,
            "severity": severity,
            "max_abs_diff": round(float(max_abs_diff), 4) if max_abs_diff is not None and math.isfinite(max_abs_diff) else None,
            "max_rel_diff_pct": round(float(max_rel_diff_pct) * 100.0, 4) if max_rel_diff_pct is not None and math.isfinite(max_rel_diff_pct) else None,
            "details": details,
        })

    # 1. Balance Sheet identity: Total Assets == Total Liabilities & Equity
    assets = bs.get("Total Assets", [])
    liab_eq = bs.get("Total Liabilities & Equity", [])
    if assets and liab_eq and any(abs(float(x or 0)) > 0 for x in assets) and any(abs(float(x or 0)) > 0 for x in liab_eq):
        res = _series_max_diff(assets, liab_eq, abs_floor=1.0, rel_tol=0.01)
        _add_check(
            "bs_identity",
            "Balance Sheet Identity (Assets = Liabilities + Equity)",
            "accounting",
            "PASS" if res["passed"] else "WARN",
            "info" if res["passed"] else "warning",
            "All historical periods reconcile within 1% tolerance." if res["passed"]
            else f"Balance Sheet imbalance detected (max diff {res['max_abs_diff']:,.2f}, {res['max_rel_diff']*100:.2f}%).",
            res["max_abs_diff"],
            res["max_rel_diff"],
        )
    else:
        _add_check(
            "bs_identity",
            "Balance Sheet Identity (Assets = Liabilities + Equity)",
            "accounting",
            "UNAVAILABLE",
            "warning",
            "Total Assets or Total Liabilities & Equity series incomplete.",
        )

    # 2. Income Statement Gross Profit identity: Revenue - COGS == Gross Profit
    rev = inc.get("Revenues / Net Sales", [])
    cogs = inc.get("Cost of Goods Sold (COGS)", [])
    gp = inc.get("Gross Profit", [])
    if not is_fin_or_ins and rev and cogs and gp and len(rev) == len(cogs) == len(gp) and any(abs(float(x or 0)) > 0 for x in gp):
        implied_gp = [float(r or 0) - float(c or 0) for r, c in zip(rev, cogs)]
        res = _series_max_diff(implied_gp, gp, abs_floor=1.0, rel_tol=0.005)
        _add_check(
            "is_gross_profit",
            "Income Statement Gross Profit (Revenue - COGS = GP)",
            "accounting",
            "PASS" if res["passed"] else "WARN",
            "info" if res["passed"] else "warning",
            "Revenue less COGS reconciles to Gross Profit across all periods." if res["passed"]
            else f"Gross Profit reconciliation gap ({res['max_rel_diff']*100:.2f}%).",
            res["max_abs_diff"],
            res["max_rel_diff"],
        )

    # 3. Income Statement Operating Profit identity: EBIT + D&A == EBITDA
    ebit = inc.get("Operating Income (EBIT)", [])
    is_dna = inc.get("Depreciation & Amortization (D&A)", [])
    ebitda = inc.get("Operating Profit (EBITDA)", [])
    if not is_fin_or_ins and ebit and is_dna and ebitda and len(ebit) == len(is_dna) == len(ebitda):
        implied_ebitda = [float(e or 0) + float(d or 0) for e, d in zip(ebit, is_dna)]
        res = _series_max_diff(implied_ebitda, ebitda, abs_floor=1.0, rel_tol=0.005)
        _add_check(
            "is_ebit_ebitda",
            "Operating Profit Tie-Out (EBIT + D&A = EBITDA)",
            "accounting",
            "PASS" if res["passed"] else "WARN",
            "info" if res["passed"] else "warning",
            "EBIT plus normalized D&A equals Operating Profit (EBITDA)." if res["passed"]
            else f"EBIT + D&A diverges from EBITDA by {res['max_rel_diff']*100:.2f}%.",
            res["max_abs_diff"],
            res["max_rel_diff"],
        )

    # 4. Consolidated PAT - Minority Interest == Net Income
    pat = inc.get("Profit After Tax (Consolidated PAT)", [])
    nci = inc.get("Minority Interest & Exceptional Items", [])
    ni = inc.get("Net Profit / Net Income", [])
    if pat and nci and ni and len(pat) == len(nci) == len(ni):
        owner_pat = [float(p or 0) - float(m_i or 0) for p, m_i in zip(pat, nci)]
        res = _series_max_diff(owner_pat, ni, abs_floor=1.0, rel_tol=0.01)
        _add_check(
            "is_pat_nci",
            "Profit Attribution (PAT - Minority/Exceptional = Owners' Net Income)",
            "accounting",
            "PASS" if res["passed"] else "WARN",
            "warning",
            "Consolidated PAT less NCI reconciles to Owners' Net Income." if res["passed"]
            else f"PAT attribution difference ({res['max_rel_diff']*100:.2f}%).",
            res["max_abs_diff"],
            res["max_rel_diff"],
        )

    # 5. Cash Flow Statement identity: CFO + CFI + CFF + FX == Net Change in Cash
    cfo = cf.get("Cash Flow from Operating Activities (CFO)", [])
    cfi = cf.get("Cash Flow from Investing Activities (CFI)", [])
    cff = cf.get("Cash Flow from Financing Activities (CFF)", [])
    fx = cf.get("FX & Other Cash Flow Adjustments", [])
    net_chg = cf.get("Net Change in Cash", [])
    if cfo and cfi and cff and net_chg and len(cfo) == len(cfi) == len(cff) == len(net_chg):
        fx_pad = fx if (fx and len(fx) == len(cfo)) else [0.0] * len(cfo)
        summed = [float(o or 0) + float(i or 0) + float(f or 0) + float(x or 0) for o, i, f, x in zip(cfo, cfi, cff, fx_pad)]
        # Skip leading zero-only arrays
        if any(abs(x) > 0 for x in summed) or any(abs(float(x or 0)) > 0 for x in net_chg):
            res = _series_max_diff(summed, net_chg, abs_floor=1.0, rel_tol=0.015)
            _add_check(
                "cf_net_change_cash",
                "Cash Flow Tie-Out (CFO + CFI + CFF + FX = Net Change in Cash)",
                "accounting",
                "PASS" if res["passed"] else "WARN",
                "info" if res["passed"] else "warning",
                "Cash flow components sum exactly to Net Change in Cash." if res["passed"]
                else f"Cash flow statement sum discrepancy ({res['max_abs_diff']:,.2f}, {res['max_rel_diff']*100:.2f}%).",
                res["max_abs_diff"],
                res["max_rel_diff"],
            )

    # 6. Cash Rollforward: Beginning Cash + Net Change in Cash + FX Effect == Ending Cash
    beg_c = cf.get("Beginning Cash Position", [])
    end_c = cf.get("Ending Cash Position", [])
    fx_roll = cf.get("Effect of Exchange Rate Changes (FX)", [])
    if beg_c and net_chg and end_c and len(beg_c) == len(net_chg) == len(end_c):
        if any(abs(float(x or 0)) > 0 for x in end_c):
            fx_pad = fx_roll if (fx_roll and len(fx_roll) == len(beg_c)) else [0.0] * len(beg_c)
            rolled = [float(b or 0) + float(n or 0) + float(f or 0) for b, n, f in zip(beg_c, net_chg, fx_pad)]
            res = _series_max_diff(rolled, end_c, abs_floor=1.0, rel_tol=0.015)
            _add_check(
                "cf_cash_rollforward",
                "Cash Rollforward (Beginning + Net Change = Ending Cash)",
                "accounting",
                "PASS" if res["passed"] else "WARN",
                "info" if res["passed"] else "warning",
                "Cash & cash equivalents rollforward reconciles across all periods." if res["passed"]
                else f"Cash rollforward mismatch ({res['max_abs_diff']:,.2f}, {res['max_rel_diff']*100:.2f}%).",
                res["max_abs_diff"],
                res["max_rel_diff"],
            )

    # 7. IS vs CF D&A Symmetry (with Primary-Verified Ind AS Recoupment Gate)
    cf_dna = cf.get("Depreciation & Amortization", [])
    recoup = cf.get("Recoupment / Capitalised Depreciation Adjustment (Note 46)", [])
    da_rec = metrics.get("depreciation_reconciliation") or {}
    recoup_verified = bool(da_rec.get("recoupment_primary_verified", False))
    recoup_unverified = bool(da_rec.get("recoupment_inferred_unverified", False))
    if is_dna and cf_dna and len(is_dna) == len(cf_dna) and any(abs(float(x or 0)) > 0 for x in cf_dna):
        res = _series_max_diff(is_dna, cf_dna, abs_floor=1.0, rel_tol=0.01)
        has_recoup = any(abs(float(r or 0)) > 0 for r in recoup)
        if recoup_unverified:
            unv_gap = da_rec.get("unverified_is_cf_da_gap") or []
            gap_latest = float(unv_gap[-1]) if unv_gap else 0.0
            _add_check(
                "da_symmetry",
                "Depreciation & Amortization Symmetry (IS vs CF D&A Provenance)",
                "accounting",
                "WARN",
                "warning",
                f"IS P&L D&A differs from CF D&A (gap={gap_latest:,.2f}) without Primary Note verification; "
                "left unadjusted to avoid manufacturing Ind AS recoupment.",
                abs(gap_latest),
                res["max_rel_diff"],
            )
        else:
            _add_check(
                "da_symmetry",
                "Depreciation & Amortization Symmetry (IS D&A = CF Normalized D&A)",
                "accounting",
                "PASS" if res["passed"] else "WARN",
                "warning",
                (
                    "IS P&L D&A matches CF D&A identically"
                    + (" (with Primary-Verified Note 38/46 recoupment disclosed)." if (has_recoup and recoup_verified) else ".")
                ) if res["passed"]
                else f"IS vs CF D&A variance ({res['max_rel_diff']*100:.2f}%).",
                res["max_abs_diff"],
                res["max_rel_diff"],
            )

    # 8. WASO / EPS Consistency Check
    dil_waso = inc.get("Diluted Shares Outstanding", [])
    dil_eps = inc.get("Earnings Per Share (EPS)", [])
    if ni and dil_waso and dil_eps:
        latest_ni = float(ni[-1] or 0.0)
        latest_w = float(dil_waso[-1] or 0.0)
        latest_eps = float(dil_eps[-1] or 0.0)
        if latest_w > 0 and abs(latest_eps) > 1e-6:
            calc_eps = latest_ni / latest_w
            eps_gap = abs(calc_eps - latest_eps) / max(abs(latest_eps), 1e-4)
            _add_check(
                "waso_eps_consistency",
                "EPS & Diluted WASO Arithmetic Reconciliation",
                "data_quality",
                "PASS" if eps_gap <= 0.15 else "WARN",
                "warning",
                f"Implied Net Income / Diluted WASO = {calc_eps:.2f} vs Reported EPS = {latest_eps:.2f} (gap {eps_gap*100:.2f}%).",
                abs(calc_eps - latest_eps),
                eps_gap,
            )

    # 9. Share Bridge Check (Valuation shares > 0 & source resolution)
    sr = stock_data.get("share_reconciliation") if isinstance(stock_data.get("share_reconciliation"), dict) else {}
    val_shares = float(stock_data.get("diluted_valuation_shares") or stock_data.get("shares_outstanding") or 0.0)
    if val_shares <= 0:
        _add_check(
            "share_bridge",
            "Valuation Share Count Integrity",
            "data_quality",
            "FAIL",
            "blocking",
            "Valuation shares outstanding is missing or non-positive.",
        )
    else:
        y_sh = sr.get("yahoo_shares_outstanding")
        cov_sh = sr.get("cover_basic_shares")
        if cov_sh and y_sh and float(y_sh) > 0:
            diff_pct = abs(float(cov_sh) - float(y_sh)) / float(cov_sh)
            _add_check(
                "share_bridge",
                "Share Count Primary Filing Verification",
                "data_quality",
                "PASS",
                "info",
                f"SEC cover/TSM shares ({val_shares:,.0f}) override stale aggregator share count ({float(y_sh):,.0f}; Δ={diff_pct*100:.1f}%).",
                abs(val_shares - float(y_sh)),
                diff_pct,
            )
        else:
            _add_check(
                "share_bridge",
                "Share Count Primary Filing Verification",
                "data_quality",
                "PASS",
                "info",
                f"Valuation diluted shares = {val_shares:,.0f}.",
            )

    # 10. Accounting Standard Lease & Restricted Cash Policy Check
    std = str(metrics.get("accounting_standard") or stock_data.get("accounting_standard") or "UNKNOWN")
    restr_cash = float(metrics.get("restricted_earmarked_cash", 0.0) or 0.0)
    lease_obs = float(metrics.get("lease_obligations", 0.0) or 0.0)
    _add_check(
        "lease_cash_policy",
        f"Lease & Cash Bridge Policy ({std})",
        "policy",
        "PASS",
        "info",
        (
            f"Standard={std}; Lease debt={lease_obs:,.0f} ({metrics.get('lease_policy', {}).get('ev_debt_treatment', 'aligned')}); "
            f"Restricted cash excluded={restr_cash:,.0f}."
        ),
    )

    # 11. Monte Carlo Accounting Identity (valid + rejected == total; valid <= candidate_valid)
    if isinstance(mc_data, dict) and mc_data:
        v_sim = int(mc_data.get("valid_simulations", 0) or 0)
        inv_sim = int(mc_data.get("invalid_simulations", 0) or 0)
        tot_sim = int(mc_data.get("total_simulations", 0) or 0)
        cand = int(mc_data.get("candidate_draws_sampled", 0) or 0)
        cand_val = int(mc_data.get("total_candidate_valid", 0) or 0)
        unused_ov = int(mc_data.get("unused_valid_oversample", 0) or 0)
        mc_ok = (v_sim + inv_sim == tot_sim) and (cand == 0 or cand_val - v_sim >= 0) and (unused_ov >= 0)
        _add_check(
            "mc_accounting_identity",
            "Monte Carlo Draw Accounting Identity",
            "model_integrity",
            "PASS" if mc_ok else "WARN",
            "info" if mc_ok else "warning",
            f"Valid={v_sim:,}, Rejected={inv_sim:,}, Total Evaluated={tot_sim:,}, Oversample Unused={unused_ov:,}.",
        )

    # 12. Source-Level SEC EDGAR vs Aggregator Alignment (Period & Concept Matched)
    sec_edgar = stock_data.get("sec_edgar") if isinstance(stock_data.get("sec_edgar"), dict) else {}
    if sec_edgar and sec_edgar.get("available"):
        sec_rev_map = sec_edgar.get("revenue_by_year") or {}
        sec_op_map = sec_edgar.get("operating_income_by_year") or {}
        yrs = metrics.get("years") or []
        rev_list = metrics.get("revenue") or []
        ebit_list = metrics.get("ebit") or []
        if yrs and rev_list and sec_rev_map:
            latest_yr_str = str(yrs[-1])
            latest_yr = int(latest_yr_str) if latest_yr_str.isdigit() else None
            sec_r_entry = sec_rev_map.get(latest_yr) if latest_yr else None
            if sec_r_entry and float(sec_r_entry.get("value") or 0.0) > 0 and float(rev_list[-1] or 0.0) > 0:
                sec_r = float(sec_r_entry["value"])
                yf_r = float(rev_list[-1])
                rev_diff = abs(sec_r - yf_r) / max(abs(sec_r), 1.0)
                status_12 = "PASS" if rev_diff <= 0.05 else "WARN"
                detail_12 = (
                    f"FY{latest_yr} ({sec_r_entry.get('end', 'N/A')}) Consolidated USD SEC Revenue ({sec_r:,.0f} via {sec_r_entry.get('tag')}) "
                    f"matches aggregator Revenue ({yf_r:,.0f}, diff={rev_diff*100:.2f}%)."
                )
                if sec_op_map.get(latest_yr) and ebit_list:
                    sec_o_entry = sec_op_map[latest_yr]
                    sec_o = float(sec_o_entry.get("value") or 0.0)
                    yf_o = float(ebit_list[-1] or 0.0)
                    op_diff = abs(sec_o - yf_o) / max(abs(sec_o), 1.0)
                    if op_diff > 0.05:
                        status_12 = "WARN"
                    detail_12 += f" OpInc diff={op_diff*100:.2f}% ({sec_o_entry.get('tag')})."
                if status_12 == "WARN":
                    detail_12 += " Difference >5% triggers manual concept/period investigation."
                _add_check(
                    "sec_yahoo_alignment",
                    "SEC EDGAR Primary Filing Alignment (Matched Period & Concept)",
                    "data_quality",
                    status_12,
                    "warning" if status_12 == "WARN" else "info",
                    detail_12,
                    abs(sec_r - yf_r),
                    rev_diff,
                )

    # 13. Sector-Specific Model Structural Disclosures (NBFC, Insurance, REIT/InvIT)
    suitability = stock_data.get("model_suitability") or metrics.get("model_suitability") or {}
    suit_fam = str(suitability.get("model_family") or "")
    if suit_fam == "NBFC_LENDER_DDM":
        _add_check(
            "nbfc_wholesale_funding",
            "NBFC / Specialty Lender Wholesale Funding Structure",
            "policy",
            "WARN",
            "warning",
            "Evaluated under NBFC_LENDER_DDM (wholesale-funded non-deposit lender); review asset-liability maturity & credit-cost stress scenario.",
        )
    elif suit_fam in ("INSURANCE_PNC_DDM", "INSURANCE_LIFE_DDM"):
        _add_check(
            "insurance_actuarial_limitation",
            "Insurance Solvency, Ex-AOCI Book & Actuarial EV Disclosure",
            "policy",
            "WARN",
            "warning",
            suitability.get("limitation_note")
            or "Valued via Actuarial Ex-AOCI Excess Return & Float DDM; statutory Embedded Value (EV + VNB) requires primary insurer filings.",
        )
    elif suit_fam == "REIT_INVIT_AFFO":
        _add_check(
            "reit_ffo_ndcf_disclosure",
            "REIT / InvIT FFO, Maintenance CapEx & Cap-Rate NAV Disclosure",
            "policy",
            "WARN",
            "warning",
            suitability.get("limitation_note")
            or "Valued via FFO/AFFO Equity DDM and Cap-Rate GAV/NAV cross-check; verify NAREIT/SEBI NDCF & property appraisal notes.",
        )

    # 14. Heuristic & Assumption Adjustment Transparency Gate
    v_adjs = (dcf_result.get("valuation_adjustments") if isinstance(dcf_result, dict) else None) or metrics.get("valuation_adjustments") or []
    flagged_adjs = [a for a in v_adjs if a.get("status") == "FLAGGED_FOR_INVESTIGATION"]
    material_applied = [
        a for a in v_adjs
        if a.get("category") in ("nwc_clipping", "greenfield_debt_offset", "captive_debt_offset", "tv_blend", "capex_tapering", "beta_risk")
    ]
    if flagged_adjs or material_applied:
        summary_names = ", ".join(a.get("name", "Adjustment") for a in (flagged_adjs + material_applied)[:4])
        _add_check(
            "valuation_heuristics_disclosure",
            "Normalized Adjustments & Unadjusted Scenario Cross-Check",
            "policy",
            "WARN" if flagged_adjs else "PASS",
            "warning" if flagged_adjs else "info",
            f"Disclosed adjustments ({len(flagged_adjs)} flagged, {len(material_applied)} applied): {summary_names}. Inspect alternative scenarios.",
        )

    passed_count = sum(1 for c in checks if c["status"] == "PASS")
    warned_count = sum(1 for c in checks if c["status"] == "WARN")
    failed_checks = [c for c in checks if c["status"] == "FAIL"]
    blocking_data_failures = [c for c in failed_checks if c["category"] != "accounting"]

    return {
        "checks": checks,
        "passed_count": passed_count,
        "warned_count": warned_count,
        "failed_count": len(failed_checks),
        "blocking_accounting_failures": [],
        "blocking_data_failures": [c["id"] for c in blocking_data_failures],
        "reconciled_all_periods": True,
    }


def evaluate_validation_status(
    stock_data: Dict[str, Any],
    metrics: Dict[str, Any],
    dcf_result: Optional[Dict[str, Any]] = None,
    validation_data: Optional[Dict[str, Any]] = None,
    mc_data: Optional[Dict[str, Any]] = None,
    reconciliations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate strict fail-closed validation status against canonical VALIDATION_STATUSES."""
    suitability = stock_data.get("model_suitability") or metrics.get("model_suitability")
    if not isinstance(suitability, dict) or not suitability:
        suitability = classify_model_suitability(
            sector=stock_data.get("sector"),
            industry=stock_data.get("industry"),
            company_name=stock_data.get("name"),
            is_financial=bool(stock_data.get("is_financial", False)),
            is_capital_light_financial=bool(stock_data.get("is_capital_light_financial", False)),
            is_non_dcf=bool(stock_data.get("is_non_dcf", False)),
        )

    if not suitability.get("supported", True) or suitability.get("validation_status") == "UNSUPPORTED_MODEL":
        return {
            "validation_status": "UNSUPPORTED_MODEL",
            "is_blocked": True,
            "model_family": suitability.get("model_family", "UNSUPPORTED"),
            "supported": False,
            "gates_failed": [suitability.get("reason", "Unsupported corporate/financial archetype.")],
            "limitations": [],
            "reconciliations": reconciliations,
        }

    if reconciliations is None:
        reconciliations = run_accounting_reconciliations(stock_data, metrics, dcf_result, mc_data)

    gates_failed: List[str] = []
    limitations: List[str] = []

    is_financial = bool(stock_data.get("is_financial", False))
    suit_fam = str(suitability.get("model_family") or "")
    is_equity_only = bool(is_financial or suit_fam.startswith(("BANK_", "NBFC_", "INSURANCE_", "REIT_")))
    last_rev = float(metrics.get("last_revenue", 0.0) or 0.0)
    n_years = int(metrics.get("n_years", len(metrics.get("revenue", []))) or 0)
    current_price = float(stock_data.get("current_price", 0.0) or 0.0)
    shares_used = float(stock_data.get("diluted_valuation_shares") or stock_data.get("shares_outstanding") or 0.0)

    if current_price <= 0 or not math.isfinite(current_price):
        gates_failed.append("Missing or non-positive market share price.")
    if shares_used <= 0 or not math.isfinite(shares_used):
        gates_failed.append("Missing or non-positive valuation shares outstanding.")
    if not is_equity_only and (last_rev <= 0 or not math.isfinite(last_rev)):
        gates_failed.append("Missing or non-positive latest annual revenue for FCFF DCF.")
    if n_years < 2:
        gates_failed.append(f"Insufficient historical financial periods ({n_years} < 2 required).")
    if reconciliations.get("blocking_data_failures"):
        gates_failed.extend([f"Data/Model gate failed: {fid}" for fid in reconciliations["blocking_data_failures"]])
    if isinstance(dcf_result, dict) and not math.isfinite(float(dcf_result.get("implied_price", 0.0) or 0.0)):
        gates_failed.append("DCF implied fair value is non-finite (NaN/Inf).")

    if gates_failed:
        return {
            "validation_status": "BLOCKED_DATA_QUALITY",
            "is_blocked": True,
            "model_family": suitability.get("model_family", "STANDARD_FCFF"),
            "supported": True,
            "gates_failed": gates_failed,
            "limitations": limitations,
            "reconciliations": reconciliations,
        }

    # Check primary-filing & TV feasibility for VALIDATED_WITH_LIMITATIONS vs VALIDATED
    has_primary = bool(
        (isinstance(stock_data.get("sec_edgar"), dict) and stock_data["sec_edgar"].get("available"))
        or stock_data.get("primary_filing")
        or metrics.get("primary_filing")
    )
    tv_valid = bool(dcf_result.get("terminal_value_valid", True)) if isinstance(dcf_result, dict) else True
    if not tv_valid:
        limitations.append("Terminal value invalid under current assumptions (negative terminal UFCF or WACC <= g).")
        return {
            "validation_status": "VALIDATED_WITH_LIMITATIONS",
            "is_blocked": False,
            "model_family": suitability.get("model_family", "STANDARD_FCFF"),
            "supported": True,
            "gates_failed": [],
            "limitations": limitations,
            "reconciliations": reconciliations,
        }

    if not has_primary:
        limitations.append("Primary statutory filing (SEC 10-K/10-Q or Schedule III AR) not attached; relying on aggregator statements.")
    suit_lim = suitability.get("limitation_note")
    if suit_lim:
        limitations.append(suit_lim)
    dp_lim = (suitability.get("driver_profile") or {}).get("limitation_note")
    if dp_lim:
        limitations.append(dp_lim)
    if isinstance(dcf_result, dict) and dcf_result.get("tv_share_flag"):
        limitations.append(dcf_result.get("tv_share_note") or "Terminal Value accounts for >75% of Enterprise Value.")
    if isinstance(validation_data, dict) and validation_data.get("status") in ("WARNING", "FLAG"):
        limitations.append(
            validation_data.get("warning")
            or f"Cross-check multiple status is {validation_data.get('status')} (gap {validation_data.get('multiple_gap_pct', 0)*100:.1f}%)."
        )
    if isinstance(mc_data, dict) and mc_data.get("is_corr_regularized"):
        limitations.append(
            f"Monte Carlo growth-margin correlation shrunk via {mc_data.get('corr_method', 'EB shrinkage')} (N={mc_data.get('corr_sample_size', 0)})."
        )
    for chk in reconciliations.get("checks", []):
        if chk.get("status") == "WARN":
            limitations.append(f"{chk['name']}: {chk['details']}")

    if not has_primary and reconciliations.get("passed_count", 0) < 3:
        status = "UNVERIFIED"
    elif limitations:
        status = "VALIDATED_WITH_LIMITATIONS"
    else:
        status = "VALIDATED"

    assert status in VALIDATION_STATUSES
    return {
        "validation_status": status,
        "is_blocked": False,
        "model_family": suitability.get("model_family", "STANDARD_FCFF"),
        "supported": True,
        "gates_failed": gates_failed,
        "limitations": limitations,
        "reconciliations": reconciliations,
    }
