"""
DUOL & CESC Primary Statutory Filings Regression Suite
=======================================================
Verifies offline deterministic statutory extraction from:
- DUOL SEC 10-K / 10-Q / companyfacts (diluted TSM shares, lease policy, ROU alignment, zero D&A mismatch)
- CESC Ind AS AR 2025-26 & Q4FY26 results (Note 16 Cash Bridge, Note 46 D&A Recoupment, Note 32c Commitments,
  Note 11 Capital Advances, Regulatory Deferral Assets, and Ind AS 116 Lease Alignment).
"""

import pytest
from engine.data_layer import fetch_stock_data, compute_historical_metrics


def test_duol_primary_sec_filing_tsm_and_lease_alignment():
    sd = fetch_stock_data("DUOL", "US")
    met = compute_historical_metrics(sd)

    assert sd.get("sec_edgar", {}).get("available") is True
    share_recon = met["share_reconciliation"]
    # TSM Diluted shares > Basic shares due to positive RSU / option dilution (and overrides stale aggregator)
    assert share_recon["valuation_diluted_shares"] > share_recon["valuation_basic_shares"]
    assert share_recon["valuation_basic_shares"] == pytest.approx(47_178_260, abs=10_000)
    assert share_recon["valuation_diluted_shares"] == pytest.approx(47_597_920, abs=50_000)

    # Lease policy under ASC 842: EV debt excludes operating lease liabilities when R&D/OpEx already embeds rent
    assert met["accounting_standard"] == "US_GAAP"
    cash_recon = met["cash_reconciliation"]
    assert cash_recon["restricted_earmarked_cash"] >= 0.0
    assert abs(cash_recon["unrestricted_cash"] + cash_recon["restricted_earmarked_cash"] - cash_recon["gross_cash_and_sti"]) < 1000.0


def test_cesc_primary_ind_as_disclosures_and_cash_bridge():
    sd = fetch_stock_data("CESC.NS", "IN")
    met = compute_historical_metrics(sd)

    assert sd.get("primary_filing", {}).get("available") is True
    assert met["accounting_standard"] == "IND_AS"

    # Note 16 Cash Reconciliation: Gross 5,671.11 Cr - Restricted 985.53 Cr = 4,685.58 Cr
    cr = met["cash_reconciliation"]
    assert cr["gross_cash_and_sti"] / 1e7 == pytest.approx(5671.11, abs=0.2)
    assert cr["restricted_earmarked_cash"] / 1e7 == pytest.approx(985.53, abs=0.2)
    assert cr["unrestricted_cash"] / 1e7 == pytest.approx(4685.58, abs=0.2)
    assert met["cash_and_equivalents"] == pytest.approx(cr["unrestricted_cash"], abs=1e4)

    # Note 46 D&A recoupment separated cleanly from P&L operating D&A
    dr = met["depreciation_reconciliation"]
    assert dr["is_recouped"] is True
    assert dr["reported_gross_cf_da"][-1] > dr["operating_net_da"][-1]
    assert dr["recouped_da"][-1] / 1e7 == pytest.approx(212.26, abs=0.5)
    assert dr["operating_net_da"][-1] / 1e7 == pytest.approx(1228.40, abs=0.5)

    # Note 32(c) Capital Commitments & Note 11 Capital Advances preserved (in INR Cr -> * 1e7)
    assert met["capital_commitments"] / 1e7 == pytest.approx(13216.43, abs=1.0)
    assert met["capital_advances"] / 1e7 == pytest.approx(1643.12, abs=1.0)
