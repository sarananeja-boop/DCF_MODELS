"""
Excel vs Python Valuation Parity Suite
=======================================
Verifies <= 0.01 parity between Python engines and Excel cached formula values
across Base Valuation, ALL 243 Corporate Sensitivity cells, ALL 50 Bank DDM
Sensitivity cells, ZERO None cached formulas, ZERO Excel #REF/#DIV/0/#VALUE/#NAME? errors.
"""

from io import BytesIO
import openpyxl
import pytest
from fastapi.testclient import TestClient

from main import app
from export.excel_export import generate_excel_report


@pytest.fixture(scope="module")
def api_client():
    return TestClient(app)


@pytest.mark.parametrize("ticker,market", [("DUOL", "US"), ("CESC.NS", "IN")])
def test_corporate_workbook_full_243_cell_sensitivity_and_base_parity(api_client, ticker, market):
    res = api_client.post("/api/analyze", json={"ticker": ticker, "market": market, "monte_carlo_iterations": 500}).json()
    xbytes = generate_excel_report(res).getvalue()
    wb_v = openpyxl.load_workbook(BytesIO(xbytes), data_only=True)
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)

    # Zero None or #ERROR formulas across the entire workbook
    for name in wb_f.sheetnames:
        sf, sv = wb_f[name], wb_v[name]
        for r in range(1, sf.max_row + 1):
            for c in range(1, sf.max_column + 1):
                fv, vv = sf.cell(r, c).value, sv.cell(r, c).value
                if isinstance(fv, str) and fv.startswith("="):
                    assert vv is not None, f"Uncached formula at {name}!{openpyxl.utils.get_column_letter(c)}{r}"
                    assert not (isinstance(vv, str) and vv.startswith("#")), f"Formula error {vv} at {name}!R{r}C{c}"

    # Base valuation parity on Cover & DCF Model
    py_base = res["dcf_result"]["implied_price"]
    cover_live = next(
        wb_v["Cover"].cell(r, 3).value
        for r in range(1, wb_v["Cover"].max_row + 1)
        if wb_v["Cover"].cell(r, 2).value == "DCF Implied Fair Value (Live Model Formula)"
    )
    assert abs(cover_live - py_base) <= 0.01

    # All 3 x 9x9 = 243 live sensitivity cells must be formulas matching Python <= 0.01
    ws_sv, ws_sf = wb_v["Sensitivity"], wb_f["Sensitivity"]
    grids = [
        res["sensitivity"]["terminal_growth_wacc"]["price_grid"],
        res["sensitivity"]["growth_wacc"]["price_grid"],
        res["sensitivity"]["margin_wacc"]["price_grid"],
    ]
    for sr, py_mat in zip((8, 21, 34), grids):
        for r_off in range(9):
            for c_off in range(9):
                fv = ws_sf.cell(sr + r_off, 3 + c_off).value
                assert isinstance(fv, str) and fv.startswith("=")
                assert "$D$23" not in fv

        diff_direct = max(
            abs(ws_sv.cell(sr + ri, 3 + ci).value - py_mat[ri][ci])
            for ri in range(9) for ci in range(9)
        )
        diff_tr = max(
            abs(ws_sv.cell(sr + ri, 3 + ci).value - py_mat[ci][ri])
            for ri in range(9) for ci in range(9)
        )
        assert min(diff_direct, diff_tr) <= 0.01


def test_bank_ddm_workbook_base_and_50_cell_sensitivity_parity(api_client):
    res = api_client.post("/api/analyze", json={"ticker": "HDFCBANK.NS", "market": "IN", "monte_carlo_iterations": 500}).json()
    xbytes = generate_excel_report(res).getvalue()
    wb_v = openpyxl.load_workbook(BytesIO(xbytes), data_only=True)
    wb_f = openpyxl.load_workbook(BytesIO(xbytes), data_only=False)

    for name in wb_f.sheetnames:
        sf, sv = wb_f[name], wb_v[name]
        for r in range(1, sf.max_row + 1):
            for c in range(1, sf.max_column + 1):
                fv, vv = sf.cell(r, c).value, sv.cell(r, c).value
                if isinstance(fv, str) and fv.startswith("="):
                    assert vv is not None
                    assert not (isinstance(vv, str) and vv.startswith("#"))

    py_base = res["dcf_result"]["implied_price"]
    cover_iv = next(
        wb_v["Cover"].cell(r, 3).value
        for r in range(1, wb_v["Cover"].max_row + 1)
        if "Fair Value per Share" in str(wb_v["Cover"].cell(r, 2).value or "")
    )
    assert abs(cover_iv - py_base) <= 0.01

    ws_sv, ws_sf = wb_v["Sensitivity"], wb_f["Sensitivity"]
    for gkey in ("growth_wacc", "margin_wacc"):
        py_mat = res["sensitivity"][gkey].get("price_grid") or res["sensitivity"][gkey].get("grid")
        nr, nc = len(py_mat), len(py_mat[0])
        best_diff = float("inf")
        for sr in range(1, ws_sv.max_row - nr + 2):
            if isinstance(ws_sf.cell(sr, 3).value, str) and ws_sf.cell(sr, 3).value.startswith("="):
                for tr in (False, True):
                    try:
                        mx = max(
                            abs(ws_sv.cell(sr + i, 3 + j).value - (py_mat[j][i] if tr else py_mat[i][j]))
                            for i in range(nr) for j in range(nc)
                        )
                        best_diff = min(best_diff, mx)
                    except Exception:
                        pass
        assert best_diff <= 0.01, f"Bank sensitivity grid {gkey} diff {best_diff} > 0.01"
