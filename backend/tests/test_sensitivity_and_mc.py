"""
Sensitivity & Monte Carlo Engine Tests
=======================================
Proves sensitivity grids recompute live multi-year trajectories (never frozen Year-1/Year-5 shortcuts)
and Monte Carlo maintains exact deterministic reproducibility, correlation preservation, and draw conservation.
"""

import numpy as np
import pytest

from engine.data_layer import fetch_stock_data, compute_historical_metrics
from engine.market_config import MARKET_PROFILES
from engine.dcf_engine import compute_wacc, run_dcf
from engine.sensitivity import (
    generate_sensitivity_grid,
    generate_margin_sensitivity_grid,
    generate_terminal_growth_sensitivity_grid,
)
from engine.monte_carlo import run_monte_carlo


def test_sensitivity_grids_center_exact_and_reinvest_endogenous():
    sd = fetch_stock_data("DUOL", "US")
    met = compute_historical_metrics(sd)
    mp = MARKET_PROFILES["US"]
    wacc = compute_wacc(sd, met, mp)
    g0 = met["avg_rev_growth"]
    m0 = met["avg_ebit_margin"]
    cm0 = met["ebit_margins"][-1]
    w0 = wacc["wacc"]
    tg0 = mp["terminal_growth"]

    base = run_dcf(g0, m0, w0, met, wacc, sd, terminal_growth=tg0, current_margin=cm0)
    gw = generate_sensitivity_grid(
        met, wacc, sd, mp, terminal_growth=tg0, target_margin=m0, current_margin=cm0, base_growth=g0, base_wacc=w0
    )
    mw = generate_margin_sensitivity_grid(
        met, wacc, sd, mp, terminal_growth=tg0, target_margin=m0, current_margin=cm0, base_growth=g0, base_wacc=w0
    )
    tgw = generate_terminal_growth_sensitivity_grid(
        met, wacc, sd, mp, terminal_growth=tg0, target_margin=m0, current_margin=cm0, base_growth=g0, base_wacc=w0
    )

    assert abs(gw["price_grid"][4][4] - base["implied_price"]) < 0.01
    assert abs(mw["price_grid"][4][4] - base["implied_price"]) < 0.01
    assert abs(tgw["price_grid"][4][4] - base["implied_price"]) < 0.01

    # Varying terminal growth changes terminal reinvestment rate (endogenous g / sustainable_roic), not static NOPAT*c
    low_tg_dcf = run_dcf(g0, m0, w0, met, wacc, sd, terminal_growth=tgw["terminal_growth_range"][0], current_margin=cm0, ignore_terminal_growth_cap=True)
    hi_tg_dcf = run_dcf(g0, m0, w0, met, wacc, sd, terminal_growth=tgw["terminal_growth_range"][-1], current_margin=cm0, ignore_terminal_growth_cap=True)
    assert abs(tgw["price_grid"][4][0] - low_tg_dcf["implied_price"]) < 0.01
    assert abs(tgw["price_grid"][4][-1] - hi_tg_dcf["implied_price"]) < 0.01
    assert hi_tg_dcf["terminal_reinv_rate"] >= low_tg_dcf["terminal_reinv_rate"]


def test_monte_carlo_reproducible_seed_and_draw_accounting():
    sd = fetch_stock_data("CESC.NS", "IN")
    met = compute_historical_metrics(sd)
    mp = MARKET_PROFILES["IN"]
    wacc = compute_wacc(sd, met, mp)

    kwargs = dict(
        metrics=met,
        wacc_data=wacc,
        stock_data=sd,
        market_profile=mp,
        terminal_growth=mp["terminal_growth"],
        iterations=1000,
        base_growth=met["avg_rev_growth"],
        base_margin=met["avg_ebit_margin"],
        base_wacc=wacc["wacc"],
        current_margin=met["ebit_margins"][-1],
    )
    mc1 = run_monte_carlo(**kwargs)
    mc2 = run_monte_carlo(**kwargs)

    assert mc1["seed"] == 42
    assert mc1["input_snapshot_hash"] == mc2["input_snapshot_hash"]
    assert mc1["stats"]["median"] == mc2["stats"]["median"]
    assert mc1["stats"]["p5"] < mc1["stats"]["median"] < mc1["stats"]["p95"]
    assert mc1["stats"]["std_dev"] > 0
    assert mc1["candidate_draws_sampled"] == (
        mc1["valid_simulations"] + mc1["rejected_draws"] + mc1["unused_valid_oversample"]
    )
    assert np.all(np.isfinite(np.array(mc1["simulated_prices"], dtype=float)))
