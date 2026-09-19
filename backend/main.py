"""
Automated DCF Valuation Platform — FastAPI Backend
===================================================
Serves the valuation engine, AI summary, and Excel export
through a REST API consumed by the Next.js / React frontend.
"""

import os
import logging
from io import BytesIO
from typing import Optional, Dict, Any, List

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Engine imports (built in parallel – see engine/ package)
# ---------------------------------------------------------------------------
from engine.market_config import detect_market, get_market_profile
from engine.data_layer import fetch_stock_data, compute_historical_metrics
from engine.dcf_engine import compute_wacc, run_dcf
from engine.monte_carlo import run_monte_carlo
from engine.sensitivity import (
    generate_sensitivity_grid,
    generate_margin_sensitivity_grid,
)
from engine.validators import validate_valuation, validate_bank_valuation, generate_verdict
from engine.trend_analysis import compute_trends
from engine.bank_engine import (
    compute_bank_cost_of_equity,
    run_bank_valuation,
    run_bank_monte_carlo,
    generate_bank_sensitivity_grid,
    generate_bank_roe_sensitivity_grid,
)

# Local modules
from ai.summary_generator import generate_valuation_summary
from export.excel_export import generate_excel_report

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("dcf-api")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

app = FastAPI(
    title="Automated DCF Valuation Platform",
    version="1.0.0",
    description="End-to-end equity valuation via DCF, Monte Carlo simulation, "
    "sensitivity analysis, AI commentary, and Excel export.",
)

# CORS — allow everything so the Vercel-deployed frontend can call us
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════


class Overrides(BaseModel):
    revenue_growth: Optional[float] = None
    ebit_margin: Optional[float] = None
    wacc: Optional[float] = None
    terminal_growth: Optional[float] = None
    projection_years: Optional[int] = None


class AnalyzeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, description="Stock ticker symbol")
    market: str = Field(
        "auto", description="'US', 'IN', or 'auto' for auto-detection"
    )
    overrides: Optional[Overrides] = None
    monte_carlo_iterations: int = Field(
        10000, ge=100, le=100000, description="Number of MC iterations"
    )


class AISummaryRequest(BaseModel):
    """Accepts the full /api/analyze response (or key sections)."""
    analysis_data: Dict[str, Any]


class ExcelExportRequest(BaseModel):
    """Accepts the full /api/analyze response."""
    analysis_data: Dict[str, Any]


class ErrorResponse(BaseModel):
    error: str


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _numpy_to_python(obj: Any) -> Any:
    """Recursively convert numpy types to Python native types."""
    if isinstance(obj, dict):
        return {k: _numpy_to_python(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_numpy_to_python(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_numpy_to_python(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _histogram(prices: Any, bins: int = 100) -> Dict[str, List[float]]:
    """Return {bins, counts} suitable for Plotly histogram rendering."""
    arr = np.asarray(prices, dtype=float)
    counts, bin_edges = np.histogram(arr, bins=bins)
    # Use bin midpoints for the x-axis
    midpoints = ((bin_edges[:-1] + bin_edges[1:]) / 2).tolist()
    return {
        "bins": [float(b) for b in midpoints],
        "counts": [int(c) for c in counts],
    }


def _downsample(arr: Any, max_points: int = 2000) -> List[float]:
    """Downsample an array to *max_points* evenly-spaced entries."""
    arr = np.asarray(arr, dtype=float)
    if len(arr) <= max_points:
        return arr.tolist()
    indices = np.linspace(0, len(arr) - 1, max_points, dtype=int)
    return arr[indices].tolist()


# ═══════════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/health")
def health_check():
    """Simple liveness probe."""
    return {"status": "healthy", "service": "dcf-valuation-api"}


# ---------------------------------------------------------------------------
# GET /api/macro-rates
# ---------------------------------------------------------------------------
@app.get("/api/macro-rates")
def macro_rates(market: str = Query(..., description="Market code: 'US' or 'IN'")):
    """Return live risk-free rate and full market profile."""
    try:
        market = market.upper().strip()
        if market not in ("US", "IN"):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported market '{market}'. Use 'US' or 'IN'.",
            )
        profile = get_market_profile(market)
        return _numpy_to_python(profile)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("macro-rates failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# POST /api/analyze
# ---------------------------------------------------------------------------
@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    """
    Run the full valuation pipeline:
    detect market → fetch data → WACC → DCF → Monte Carlo →
    sensitivity → validation → verdict → trends.
    """
    try:
        ticker = req.ticker.strip().upper()
        overrides = req.overrides or Overrides()

        # 1. Market detection
        if req.market.lower() == "auto":
            market = detect_market(ticker)
        else:
            market = req.market.upper().strip()
        logger.info("Analyzing %s in market %s", ticker, market)

        # 2. Fetch stock data
        stock_data = fetch_stock_data(ticker, market)

        # 3. Historical metrics
        metrics = compute_historical_metrics(stock_data)

        # 4. Market profile (with live RFR)
        market_profile = get_market_profile(market)

        # 5. Dual Engine Routing: Financial Institutions vs Non-Financial Corporations
        is_financial = stock_data.get("is_financial", False)

        default_terminal_g = market_profile.get("terminal_growth", 0.055 if market == "IN" else 0.025)
        terminal_growth = (
            overrides.terminal_growth
            if overrides.terminal_growth is not None
            else default_terminal_g
        )
        projection_years = (
            overrides.projection_years
            if overrides.projection_years is not None
            else 5
        )

        tax_rate = market_profile.get("tax_rate", 0.2517 if market == "IN" else 0.21)
        stock_data["_tax_rate"] = tax_rate
        stock_data["market"] = market

        if is_financial:
            logger.info("Routing %s to Financial Services (Bank/NBFC) Multi-Stage FCFE Model", ticker)
            # Cost of Equity (Ke via CAPM)
            wacc_data = compute_bank_cost_of_equity(stock_data, market_profile)

            start_growth = (
                overrides.revenue_growth
                if overrides.revenue_growth is not None
                else metrics.get("avg_ni_growth", 0.10)
            )
            target_margin = (
                overrides.ebit_margin
                if overrides.ebit_margin is not None
                else metrics.get("avg_roe", 0.14)
            )
            current_margin = metrics.get("avg_roe", 0.14)

            discount_rate = (
                overrides.wacc
                if overrides.wacc is not None
                else wacc_data.get("cost_of_equity", 0.10)
            )

            # Bank Multi-Stage FCFE / Regulatory Capital Model
            dcf_result = run_bank_valuation(
                start_growth=start_growth,
                target_roe=target_margin,
                cost_of_equity=discount_rate,
                metrics=metrics,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                use_mid_year=True,
            )

            # Bank Monte Carlo
            mc_result = run_bank_monte_carlo(
                metrics=metrics,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                iterations=req.monte_carlo_iterations,
                base_growth=start_growth,
                base_roe=target_margin,
                base_ke=discount_rate,
            )

            # Bank Sensitivity Grids
            sens_growth_wacc = generate_bank_sensitivity_grid(
                metrics=metrics,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                base_growth=start_growth,
                base_roe=target_margin,
                base_ke=discount_rate,
            )
            sens_margin_wacc = generate_bank_roe_sensitivity_grid(
                metrics=metrics,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                base_growth=start_growth,
                base_roe=target_margin,
                base_ke=discount_rate,
            )

            validation = validate_bank_valuation(dcf_result, stock_data, metrics)
        else:
            # Standard FCFF + WACC Pipeline for Non-Financials
            wacc_data = compute_wacc(stock_data, metrics, market_profile)

            start_growth = (
                overrides.revenue_growth
                if overrides.revenue_growth is not None
                else metrics.get("avg_rev_growth", 0.10)
            )
            
            avg_ebit_margin = metrics.get("avg_ebit_margin", 0.15)
            if avg_ebit_margin < 0 and overrides.ebit_margin is None:
                target_margin = 0.0
                current_margin = avg_ebit_margin
            elif avg_ebit_margin < 0 and overrides.ebit_margin is not None:
                target_margin = overrides.ebit_margin
                current_margin = avg_ebit_margin
            else:
                target_margin = overrides.ebit_margin if overrides.ebit_margin is not None else avg_ebit_margin
                current_margin = None

            discount_rate = (
                overrides.wacc
                if overrides.wacc is not None
                else wacc_data.get("wacc", 0.10)
            )

            # Base-case DCF with Mid-Year Convention
            dcf_result = run_dcf(
                start_growth=start_growth,
                ebit_margin=target_margin,
                discount_rate=discount_rate,
                metrics=metrics,
                wacc_data=wacc_data,
                stock_data=stock_data,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                current_margin=current_margin,
                tax_rate=tax_rate,
                use_mid_year=True,
            )

            # Monte Carlo
            mc_result = run_monte_carlo(
                metrics=metrics,
                wacc_data=wacc_data,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                iterations=req.monte_carlo_iterations,
                base_growth=start_growth,
                base_margin=target_margin,
                base_wacc=discount_rate,
            )

            # Sensitivity grids
            sens_growth_wacc = generate_sensitivity_grid(
                metrics=metrics,
                wacc_data=wacc_data,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                target_margin=target_margin,
                current_margin=current_margin,
                tax_rate=tax_rate,
                use_mid_year=True,
            )
            sens_margin_wacc = generate_margin_sensitivity_grid(
                metrics=metrics,
                wacc_data=wacc_data,
                stock_data=stock_data,
                market_profile=market_profile,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                target_margin=target_margin,
                current_margin=current_margin,
                tax_rate=tax_rate,
            )

            # Validation (EV/EBITDA cross-check)
            validation = validate_valuation(dcf_result, stock_data, metrics, wacc_data)

        # 11. Verdict
        current_price = stock_data.get("current_price", 0)
        
        terminal_value_valid = dcf_result.get("terminal_value_valid", True)
        mc_valid = mc_result.get("actual_iterations", 0) > 0
        
        verdict = generate_verdict(current_price, mc_result.get("stats", {}), terminal_value_valid=terminal_value_valid, mc_valid=mc_valid)

        # 12. Trends
        trends = compute_trends(stock_data, metrics)

        # ----- Build response --------------------------------------------------
        # Monte Carlo: histogram + downsampled scatter arrays
        mc_histogram = _histogram(mc_result.get("simulated_prices", []))
        mc_scatter = {
            "sim_growth": _downsample(mc_result.get("sim_growth", []), 2000),
            "sim_margin": _downsample(mc_result.get("sim_margin", []), 2000),
            "sim_wacc": _downsample(mc_result.get("sim_wacc", []), 2000),
        }

        response = {
            "company": {
                "ticker": ticker,
                "name": stock_data.get("name", ticker),
                "market": market,
                "currency": market_profile.get("currency", "USD"),
                "symbol": market_profile.get("symbol", "$"),
                "sector": stock_data.get("sector"),
                "industry": stock_data.get("industry"),
                "is_financial": is_financial,
                "model_type": "BANKING_DDM" if is_financial else "STANDARD_FCFF",
            },
            "market_data": {
                "current_price": current_price,
                "shares_outstanding": stock_data.get("shares_outstanding"),
                "market_cap": stock_data.get("market_cap"),
                "beta": stock_data.get("beta"),
                "raw_beta": stock_data.get("raw_beta"),
                "beta_clamped": stock_data.get("beta_clamped", False),
                "beta_note": stock_data.get("beta_note", ""),
            },
            "macro": {
                "risk_free_rate": market_profile.get("risk_free_rate"),
                "risk_free_source": market_profile.get("risk_free_source"),
                "market_return": market_profile.get("market_return"),
                "tax_rate": tax_rate,
                "terminal_growth": terminal_growth,
                "gdp_growth": market_profile.get("gdp_growth", 0.065 if market == "IN" else 0.025),
                "benchmark_index": market_profile.get("benchmark_index"),
            },
            "historicals": {
                "years": metrics.get("years"),
                "revenue": metrics.get("revenue"),
                "ebit": metrics.get("ebit"),
                "capex": metrics.get("capex"),
                "dna": metrics.get("dna"),
                "delta_nwc": metrics.get("delta_nwc"),
                "rev_growth": metrics.get("rev_growth"),
                "ebit_margins": metrics.get("ebit_margins"),
                "avg_rev_growth": metrics.get("avg_rev_growth"),
                "std_rev_growth": metrics.get("std_rev_growth"),
                "avg_ebit_margin": metrics.get("avg_ebit_margin"),
                "std_ebit_margin": metrics.get("std_ebit_margin"),
                "avg_capex_pct": metrics.get("avg_capex_pct"),
                "avg_dna_pct": metrics.get("avg_dna_pct"),
                "avg_dnwc_pct": metrics.get("avg_dnwc_pct"),
                "n_years": metrics.get("n_years"),
                "cash_and_equivalents": metrics.get("cash_and_equivalents"),
            },
            "wacc": {
                "cost_of_equity": wacc_data.get("cost_of_equity"),
                "raw_cost_of_equity": wacc_data.get("raw_cost_of_equity"),
                "ke_floored": wacc_data.get("ke_floored", False),
                "ke_note": wacc_data.get("ke_note"),
                "cost_of_debt": wacc_data.get("cost_of_debt"),
                "weight_equity": wacc_data.get("weight_equity"),
                "weight_debt": wacc_data.get("weight_debt"),
                "wacc": wacc_data.get("wacc"),
                "total_debt": wacc_data.get("total_debt"),
                "operational_debt": wacc_data.get("operational_debt", 0.0),
                "total_cash": metrics.get("cash_and_equivalents"),
                "note": wacc_data.get("note"),
            },
            "dcf_result": dcf_result,
            "monte_carlo": {
                "stats": mc_result.get("stats", {}),
                "actual_iterations": mc_result.get("actual_iterations"),
                "total_simulations": mc_result.get("total_simulations", 0),
                "valid_simulations": mc_result.get("valid_simulations", 0),
                "invalid_simulations": mc_result.get("invalid_simulations", 0),
                "invalid_simulation_reasons": mc_result.get("invalid_simulation_reasons", {}),
                "zero_price_simulations": mc_result.get("stats", {}).get("zero_price_simulations", 0),
                "negative_equity_simulations": mc_result.get("stats", {}).get("negative_equity_simulations", 0),
                "positive_price_simulations": mc_result.get("stats", {}).get("positive_price_simulations", 0),
                "zero_price_pct": mc_result.get("stats", {}).get("zero_price_pct", 0.0),
                "min_raw_equity_value": mc_result.get("stats", {}).get("min_raw_equity_value", 0.0),
                "min_raw_share_price": mc_result.get("stats", {}).get("min_raw_share_price", 0.0),
                "max_share_price": mc_result.get("stats", {}).get("max_share_price", 0.0),
                "histogram": mc_histogram,
                "scatter": mc_scatter,
                "hist_corr_gm": mc_result.get("hist_corr_gm"),
            },
            "sensitivity": {
                "growth_wacc": sens_growth_wacc,
                "margin_wacc": sens_margin_wacc,
            },
            "trends": trends,
            "validation": validation,
            "verdict": verdict,
            "diagnostics": {
                "is_financial": is_financial,
                "model_type": "BANKING_DDM" if is_financial else "STANDARD_FCFF",
                "bvps": dcf_result.get("bvps"),
                "justified_pb": dcf_result.get("justified_pb"),
                "justified_price": dcf_result.get("justified_price"),
                "beta": stock_data.get("beta"),
                "raw_beta": stock_data.get("raw_beta"),
                "beta_clamped": stock_data.get("beta_clamped", False),
                "beta_note": stock_data.get("beta_note", ""),
                "ke_floored": wacc_data.get("ke_floored", False),
                "raw_ke": wacc_data.get("raw_cost_of_equity"),
                "ke_note": wacc_data.get("ke_note"),
                "terminal_growth_capped": dcf_result.get("terminal_growth_capped", False),
                "effective_terminal_growth": dcf_result.get("effective_terminal_growth", terminal_growth),
                "historical_fcf_negative": False,
                "terminal_ufcf_positive": bool(dcf_result.get("terminal_value_valid", True)),
                "terminal_value_valid": dcf_result.get("terminal_value_valid", True),
                "terminal_value_note": dcf_result.get("terminal_value_note"),
                "negative_ebitda": validation.get("trailing_ebitda", 1.0) <= 0,
                "metric_used": validation.get("metric_used", "none"),
                "margin_normalization_used": current_margin is not None,
                "current_ebit_margin": float(current_margin) if current_margin is not None else float(metrics.get("avg_roe" if is_financial else "avg_ebit_margin", 0.14)),
                "target_ebit_margin": float(target_margin),
                "normalized_nwc_to_revenue": float(metrics.get("normalized_nwc_to_revenue", 0.0)),
            },
            "overrides_applied": {
                "revenue_growth": overrides.revenue_growth,
                "ebit_margin": overrides.ebit_margin,
                "wacc": overrides.wacc,
                "terminal_growth": overrides.terminal_growth,
                "projection_years": overrides.projection_years,
            },
        }

        # Convert every numpy type to native Python before serialization
        response = _numpy_to_python(response)
        return response

    except HTTPException:
        raise
    except ValueError as exc:
        err_str = str(exc)
        logger.warning("Analyze — bad input: %s", exc)
        # Detect Yahoo Finance 429 rate limiting and return a user-friendly message
        if "429" in err_str or "Too Many Requests" in err_str or "Expecting value" in err_str:
            raise HTTPException(
                status_code=429,
                detail="Yahoo Finance is rate-limiting this server. Please wait 10–15 minutes and try again."
            )
        raise HTTPException(status_code=400, detail=err_str)
    except Exception as exc:
        err_str = str(exc)
        logger.exception("Analyze — server error")
        if "429" in err_str or "Too Many Requests" in err_str:
            raise HTTPException(
                status_code=429,
                detail="Yahoo Finance is rate-limiting this server. Please wait 10–15 minutes and try again."
            )
        raise HTTPException(status_code=500, detail=err_str)


# ---------------------------------------------------------------------------
# POST /api/ai-summary
# ---------------------------------------------------------------------------
@app.post("/api/ai-summary")
def ai_summary(req: AISummaryRequest):
    """Generate an AI-written equity research note for the analysis."""
    try:
        markdown = generate_valuation_summary(req.analysis_data)
        return {"summary": markdown}
    except Exception as exc:
        logger.exception("AI summary generation failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# POST /api/export/excel
# ---------------------------------------------------------------------------
@app.post("/api/export/excel")
def export_excel(req: ExcelExportRequest):
    """Generate a formatted .xlsx workbook and stream it to the client."""
    try:
        buffer: BytesIO = generate_excel_report(req.analysis_data)
        buffer.seek(0)

        company_name = (
            req.analysis_data.get("company", {}).get("ticker", "valuation")
        )
        filename = f"{company_name}_DCF_Report.xlsx"

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except Exception as exc:
        logger.exception("Excel export failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Entrypoint for `python main.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True,
    )

import requests
_search_cache = {}

@app.get("/api/search")
def search_ticker(q: str):
    q_norm = q.strip().upper()
    if q_norm in _search_cache:
        return {"results": _search_cache[q_norm]}

    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={q}&quotesCount=8&newsCount=0"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=4)
        data = r.json()
        results = [
            {"symbol": quote['symbol'], "name": quote.get('shortname', quote.get('longname', ''))}
            for quote in data.get('quotes', [])
            if quote.get('quoteType') in ['EQUITY', 'ETF']
        ]
        if results:
            _search_cache[q_norm] = results
        return {"results": results}
    except Exception as e:
        return {"results": []}
