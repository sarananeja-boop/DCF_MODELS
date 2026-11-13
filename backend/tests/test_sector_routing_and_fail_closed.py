"""
Sector Routing & Validation Gate Suite
======================================
Ensures Insurance & REIT/InvIT route to their dedicated actuarial / AFFO engines
with honest ``VALIDATED_WITH_LIMITATIONS`` disclosure, Banks route exclusively to
BANKING_DDM, and missing data fails closed cleanly without blocking valid operating models.
"""

from io import BytesIO
import openpyxl
import pytest
from fastapi.testclient import TestClient

import main as main_mod
from engine.canonical_schema import classify_model_suitability
from engine.validators import evaluate_validation_status
from engine.data_layer import fetch_stock_data, compute_historical_metrics
from export.excel_export import generate_excel_report


@pytest.mark.parametrize("sector,industry,name,expected_family,expected_supported,expected_status", [
    ("Financial Services", "Insurance - Life", "Life Insurance Corp", "INSURANCE_LIFE_DDM", True, "VALIDATED_WITH_LIMITATIONS"),
    ("Financial Services", "Insurance - Property & Casualty", "Progressive Corp", "INSURANCE_PNC_DDM", True, "VALIDATED_WITH_LIMITATIONS"),
    ("Real Estate", "REIT - Industrial", "Prologis Inc", "REIT_INVIT_AFFO", True, "VALIDATED_WITH_LIMITATIONS"),
    ("Real Estate", "REIT - Diversified", "Embassy Office Parks REIT", "REIT_INVIT_AFFO", True, "VALIDATED_WITH_LIMITATIONS"),
    ("Financial Services", "Banks - Regional", "HDFC Bank Limited", "BANK_DDM_TIER1", True, "VALIDATED"),
    ("Technology", "Software - Application", "Duolingo Inc", "STANDARD_FCFF", True, "VALIDATED"),
    ("Utilities", "Utilities - Regulated Electric", "CESC Limited", "REGULATED_UTILITY_FCFF", True, "VALIDATED"),
])
def test_canonical_sector_classification(sector, industry, name, expected_family, expected_supported, expected_status):
    is_reit = "REIT" in industry.upper() or "REIT" in name.upper()
    suit = classify_model_suitability(sector, industry, name, "Financial Services" in sector, False, False, is_reit)
    assert suit["model_family"] == expected_family
    assert suit["supported"] is expected_supported
    assert suit["validation_status"] == expected_status


def test_insurance_api_analyze_and_excel_valid_with_limitations(monkeypatch):
    def _mock_insurance(ticker, market):
        base = fetch_stock_data("HDFCBANK.NS", "IN")
        base = dict(base)
        base["ticker"] = "LICI.NS"
        base["name"] = "Life Insurance Corporation of India"
        base["sector"] = "Financial Services"
        base["industry"] = "Insurance - Life"
        base["is_financial"] = True
        return base

    monkeypatch.setattr(main_mod, "fetch_stock_data", _mock_insurance)
    client = TestClient(main_mod.app)
    res = client.post("/api/analyze", json={"ticker": "LICI.NS", "market": "IN"}).json()

    assert res["company"]["model_type"] == "INSURANCE_LIFE_DDM"
    assert res["validation_gate"]["validation_status"] == "VALIDATED_WITH_LIMITATIONS"
    assert res["validation_gate"]["is_blocked"] is False
    assert res["dcf_result"]["implied_price"] > 0
    assert res["monte_carlo"] is not None
    assert res["sensitivity"] is not None
    assert res["verdict"]["is_blocked"] is False

    xbytes = generate_excel_report(res).getvalue()
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)
    wb_v = openpyxl.load_workbook(BytesIO(xbytes), data_only=True)
    assert "DDM & FCFE Model" in wb_f.sheetnames
    assert "Sensitivity" in wb_f.sheetnames
    assert wb_v["Cover"]["C6"].value == "Life Insurance Corporation of India"
    cover_texts = [
        str(wb_v["Cover"].cell(r, c).value or "")
        for r in range(1, wb_v["Cover"].max_row + 1)
        for c in range(1, wb_v["Cover"].max_column + 1)
    ]
    assert not any("VALIDATED_WITH_LIMITATIONS" in t or "Seed =" in t for t in cover_texts)


def test_non_operating_etf_still_routes_to_unsupported_model():
    suit = classify_model_suitability("", "", "Vanguard S&P 500 ETF", False, True, True, False)
    assert suit["supported"] is False
    assert suit["validation_status"] == "UNSUPPORTED_MODEL"


def test_zero_price_or_missing_shares_blocks_data_quality():
    sd = dict(fetch_stock_data("DUOL", "US"))
    met = compute_historical_metrics(sd)
    sd["current_price"] = 0.0
    gate = evaluate_validation_status(sd, met)
    assert gate["validation_status"] == "BLOCKED_DATA_QUALITY"
    assert gate["is_blocked"] is True
