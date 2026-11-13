"""
General-Purpose SEC EDGAR XBRL Extractor & Primary Filing Reconciler.

Works cleanly for any US GAAP SEC registrant across both:
  1. Local fixture / cached XBRL directories (companyfacts JSON + 10-K / 10-Q iXBRL/XML).
  2. Live SEC EDGAR API (`data.sec.gov`) when outbound HTTPS is permitted.

Never uses ticker-specific hardcoded share counts or overrides. Every extracted
figure carries period, form, unit, and exact US-GAAP / DEI taxonomy tag provenance.
"""

from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIRS: List[Path] = [
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sec",
    Path("/Users/SMILE/.gemini/antigravity/brain/241b62b1-985a-4c94-a61f-669d5efafa6d/scratch/raw"),
]

_USER_AGENT = os.environ.get(
    "SEC_EDGAR_USER_AGENT",
    "ValuationLabsInstitutionalResearch/1.0 (audit@valuationlabs.local)",
)


def _search_roots(extra_dirs: Optional[List[str]] = None) -> List[Path]:
    roots: List[Path] = []
    env_dir = os.environ.get("VALUATIONLABS_SEC_CACHE_DIR")
    if env_dir:
        roots.append(Path(env_dir))
    if extra_dirs:
        roots.extend(Path(d) for d in extra_dirs if d)
    roots.extend(_DEFAULT_CACHE_DIRS)
    seen = set()
    uniq: List[Path] = []
    for p in roots:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp not in seen and p.exists():
            seen.add(rp)
            uniq.append(p)
    return uniq


def _load_local_companyfacts(ticker: str, cik: Optional[str] = None, extra_dirs: Optional[List[str]] = None) -> Tuple[Optional[dict], Optional[str]]:
    t_low = (ticker or "").strip().lower()
    candidates: List[str] = []
    if t_low:
        candidates.extend([f"{t_low}_facts.json", f"{t_low}.json", f"{t_low}_companyfacts.json"])
    if cik:
        c_pad = str(cik).zfill(10)
        candidates.extend([f"CIK{c_pad}.json", f"{c_pad}.json"])

    for root in _search_roots(extra_dirs):
        for fname in candidates:
            fp = root / fname
            if fp.is_file():
                try:
                    data = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
                    if "facts" in data:
                        return data, f"SEC EDGAR cached companyfacts ({fp.name})"
                except Exception as exc:
                    logger.warning("Failed reading SEC facts %s: %s", fp, exc)
    return None, None


def _load_live_companyfacts(ticker: str, cik: Optional[str] = None) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    if os.environ.get("VALUATIONLABS_OFFLINE", "").lower() in ("1", "true", "yes"):
        return None, None, None
    try:
        import requests

        headers = {"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip, deflate"}
        resolved_cik = cik
        if not resolved_cik:
            resp = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=5)
            if resp.status_code == 200:
                t_up = (ticker or "").strip().upper()
                for entry in resp.json().values():
                    if str(entry.get("ticker", "")).upper() == t_up:
                        resolved_cik = str(entry.get("cik_str")).zfill(10)
                        break
        if not resolved_cik:
            return None, None, None
        c_pad = str(resolved_cik).zfill(10)
        r2 = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c_pad}.json", headers=headers, timeout=8)
        if r2.status_code == 200:
            data = r2.json()
            if "facts" in data:
                return data, f"SEC EDGAR Live companyfacts API (CIK {c_pad})", c_pad
    except Exception as exc:
        logger.debug("Live SEC EDGAR lookup unavailable for %s: %s", ticker, exc)
    return None, None, None


def _fetch_live_latest_xbrl_cover(cik_padded: str) -> Optional[Tuple[str, str]]:
    """Fetch latest 10-Q / 10-K XBRL XML instance from data.sec.gov/submissions when live & online."""
    if not cik_padded or os.environ.get("VALUATIONLABS_OFFLINE", "").lower() in ("1", "true", "yes"):
        return None
    try:
        import requests

        c_pad = str(cik_padded).zfill(10)
        cik_num = str(int(c_pad))
        headers = {"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip, deflate"}
        sub_resp = requests.get(f"https://data.sec.gov/submissions/CIK{c_pad}.json", headers=headers, timeout=6)
        if sub_resp.status_code != 200:
            return None
        recent = (sub_resp.json().get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accs = recent.get("accessionNumber") or []
        pdocs = recent.get("primaryDocument") or []
        for idx, frm in enumerate(forms):
            if str(frm).upper() in ("10-Q", "10-K", "10-Q/A", "10-K/A") and idx < len(accs):
                acc_raw = str(accs[idx])
                acc_no_dash = acc_raw.replace("-", "")
                pdoc = str(pdocs[idx]) if idx < len(pdocs) else ""
                base_dir = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_no_dash}"
                idx_resp = requests.get(f"{base_dir}/index.json", headers=headers, timeout=6)
                if idx_resp.status_code != 200:
                    continue
                items = (idx_resp.json().get("directory") or {}).get("item") or []
                xml_name = None
                # Prefer extracted iXBRL instance (*_htm.xml) over generic taxonomy/linkbase xml
                for it in items:
                    nm = str(it.get("name", ""))
                    if nm.lower().endswith("_htm.xml"):
                        xml_name = nm
                        break
                if not xml_name:
                    stem = pdoc.rsplit(".", 1)[0].lower() if "." in pdoc else ""
                    for it in items:
                        nm = str(it.get("name", ""))
                        nl = nm.lower()
                        if nl.endswith(".xml") and not any(x in nl for x in ("_cal.", "_def.", "_lab.", "_pre.", "filingsummary", "metalinks")) and (not stem or stem in nl or len(nl) < 40):
                            xml_name = nm
                            break
                if not xml_name:
                    continue
                xresp = requests.get(f"{base_dir}/{xml_name}", headers=headers, timeout=10)
                if xresp.status_code == 200 and "<" in xresp.text[:200]:
                    return xresp.text, f"{frm} ({xml_name})"
                break
    except Exception as exc:
        logger.debug("Live SEC submissions XML lookup skipped for CIK %s: %s", cik_padded, exc)
    return None


def _pick_annual_duration_facts(
    facts_dict: dict,
    taxonomy: str,
    tags: List[str],
    preferred_unit: str,
) -> Dict[int, Dict[str, Any]]:
    """
    Extract annual (FY ~360-370 day) duration values keyed by end-year from SEC companyfacts.
    Prefers 10-K filings matching the ending calendar/fiscal year, keeping most recent frame/filed date.
    """
    out: Dict[int, Dict[str, Any]] = {}
    ns = facts_dict.get("facts", {}).get(taxonomy, {})
    for tag in tags:
        node = ns.get(tag)
        if not node:
            continue
        items = node.get("units", {}).get(preferred_unit, [])
        if not items and node.get("units"):
            first_u = next(iter(node["units"]))
            items = node["units"][first_u]
        for it in items:
            form = str(it.get("form", ""))
            if not form.startswith("10-K"):
                continue
            start = it.get("start")
            end = it.get("end")
            if not start or not end:
                continue
            try:
                from datetime import date

                d0 = date.fromisoformat(start[:10])
                d1 = date.fromisoformat(end[:10])
                days = (d1 - d0).days
            except Exception:
                continue
            if not (350 <= days <= 380):
                continue
            yr = d1.year
            filed = str(it.get("filed", ""))
            score = (1 if str(it.get("frame", "")).startswith("CY") else 0, filed, -tags.index(tag))
            prev = out.get(yr)
            if prev is None or score > prev["_score"]:
                out[yr] = {
                    "value": float(it["val"]),
                    "tag": f"{taxonomy}:{tag}",
                    "form": form,
                    "filed": filed,
                    "start": start,
                    "end": end,
                    "unit": preferred_unit,
                    "_score": score,
                }
    for yr in out:
        out[yr].pop("_score", None)
    return out


def _pick_latest_instant_fact(
    facts_dict: dict,
    taxonomy: str,
    tags: List[str],
    preferred_unit: str,
    target_year: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    ns = facts_dict.get("facts", {}).get(taxonomy, {})
    best: Optional[Dict[str, Any]] = None
    for tag in tags:
        node = ns.get(tag)
        if not node:
            continue
        items = node.get("units", {}).get(preferred_unit, [])
        for it in items:
            form = str(it.get("form", ""))
            if not (form.startswith("10-K") or form.startswith("10-Q")):
                continue
            end = str(it.get("end", ""))
            if target_year is not None and not end.startswith(f"{target_year}-"):
                continue
            filed = str(it.get("filed", ""))
            score = (end, filed, 1 if form.startswith("10-Q") else 0, -tags.index(tag))
            if best is None or score > best["_score"]:
                best = {
                    "value": float(it["val"]),
                    "tag": f"{taxonomy}:{tag}",
                    "form": form,
                    "filed": filed,
                    "end": end,
                    "unit": preferred_unit,
                    "_score": score,
                }
    if best:
        best.pop("_score", None)
    return best


def _parse_xbrl_cover_text(text: str, source_file: str) -> Optional[Dict[str, Any]]:
    """Parse DEI cover shares, equity awards & consolidated annual duration tags from an XBRL instance XML string."""
    tree = ET.fromstring(text)
    contexts: Dict[str, str] = {}
    for elem in tree.iter():
        ln = elem.tag.split("}")[-1]
        if ln == "context":
            cid = elem.attrib.get("id", "")
            desc = " ".join("".join(sub.itertext()).strip() for sub in elem.iter() if "explicitMember" in sub.tag or "instant" in sub.tag)
            contexts[cid] = desc
    class_shares: List[Tuple[str, float]] = []
    options_out = None
    options_waep = None
    rsus_nonvested = None
    rsus_fv = None
    for elem in tree.iter():
        ln = elem.tag.split("}")[-1]
        if ln == "EntityCommonStockSharesOutstanding" and elem.text:
            val = float(elem.text.strip())
            ctx = elem.attrib.get("contextRef", "")
            class_shares.append((contexts.get(ctx, ctx), val))
        elif ln == "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber" and elem.text:
            try:
                options_out = float(elem.text.strip())
            except ValueError:
                pass
        elif ln == "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice" and elem.text:
            try:
                options_waep = float(elem.text.strip())
            except ValueError:
                pass
        elif ln == "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber" and elem.text:
            try:
                rsus_nonvested = float(elem.text.strip())
            except ValueError:
                pass
        elif ln == "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedWeightedAverageGrantDateFairValue" and elem.text:
            try:
                rsus_fv = float(elem.text.strip())
            except ValueError:
                pass

    xml_duration_tags = {
        "WeightedAverageNumberOfSharesOutstandingBasic": "basic_waso",
        "WeightedAverageNumberOfDilutedSharesOutstanding": "diluted_waso",
        "EarningsPerShareBasic": "basic_eps",
        "EarningsPerShareDiluted": "diluted_eps",
        "IncomeTaxesPaidNet": "cash_taxes_paid",
        "IncomeTaxesPaid": "cash_taxes_paid",
    }
    xml_durations: Dict[str, Dict[int, Dict[str, Any]]] = {v: {} for v in xml_duration_tags.values()}
    ctx_periods: Dict[str, Tuple[Optional[str], Optional[str], bool]] = {}
    for elem in tree.iter():
        if elem.tag.split("}")[-1] == "context":
            cid = elem.attrib.get("id", "")
            s_dt = e_dt = None
            dims = []
            for sub in elem.iter():
                sln = sub.tag.split("}")[-1]
                if sln == "startDate" and sub.text:
                    s_dt = sub.text.strip()
                elif sln == "endDate" and sub.text:
                    e_dt = sub.text.strip()
                elif "explicitMember" in sln or "typedMember" in sln:
                    dims.append((sub.text or "").strip().lower())
            has_non_consolidated_dim = any(
                not ("and" in d and "commonstock" in d) for d in dims
            )
            ctx_periods[cid] = (s_dt, e_dt, has_non_consolidated_dim)
    for elem in tree.iter():
        ln = elem.tag.split("}")[-1]
        if ln in xml_duration_tags and elem.text:
            ctx = elem.attrib.get("contextRef", "")
            s_dt, e_dt, has_dim = ctx_periods.get(ctx, (None, None, True))
            if not has_dim and s_dt and e_dt:
                try:
                    from datetime import date
                    days = (date.fromisoformat(e_dt[:10]) - date.fromisoformat(s_dt[:10])).days
                    if days >= 300:
                        yr = int(e_dt[:4])
                        bucket = xml_duration_tags[ln]
                        xml_durations[bucket][yr] = {
                            "value": float(elem.text.strip()),
                            "tag": f"us-gaap:{ln}",
                            "form": "10-K" if "10k" in source_file.lower() or "10-k" in source_file.lower() else "10-Q",
                            "start": s_dt,
                            "end": e_dt,
                            "source_file": source_file,
                            "consolidation_basis": "Consolidated",
                        }
                except Exception:
                    pass

    if class_shares:
        seen_ctx = {}
        for desc, val in class_shares:
            if desc not in seen_ctx:
                seen_ctx[desc] = val
        total = float(sum(seen_ctx.values()))
        return {
            "total_common_shares": total,
            "share_classes": seen_ctx,
            "source_file": source_file,
            "options_outstanding": options_out,
            "options_waep": options_waep,
            "rsus_nonvested": rsus_nonvested,
            "rsus_grant_fv": rsus_fv,
            "xml_durations": xml_durations,
        }
    return None


def _extract_cover_shares_from_xml(ticker: str, extra_dirs: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """
    Parse DEI EntityCommonStockSharesOutstanding across multi-class share contexts
    (e.g. Class A + Class B common stock) from cached latest 10-Q / 10-K XML when available.
    """
    t_low = (ticker or "").strip().lower()
    if not t_low:
        return None
    for root in _search_roots(extra_dirs):
        for suffix in ("10q.xml", "_10q.xml", "10k.xml", "_10k.xml"):
            fp = root / f"{t_low}{suffix}"
            if not fp.is_file():
                continue
            try:
                parsed = _parse_xbrl_cover_text(fp.read_text(encoding="utf-8", errors="ignore"), fp.name)
                if parsed:
                    return parsed
            except Exception as exc:
                logger.debug("XML cover parse skipped for %s: %s", fp, exc)
    return None


def compute_tsm_dilution_bridge(
    basic_period_end_shares: float,
    current_price: float,
    options_outstanding: Optional[float] = None,
    options_waep: Optional[float] = None,
    rsus_nonvested: Optional[float] = None,
    qtr_diluted_waso: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute an explicit Treasury Stock Method (TSM) share count bridge.

    Note on GAAP SBC Double-Counting Tradeoff:
    Our FCFF model projects NOPAT from GAAP EBIT (which already deducts ongoing
    Stock-Based Compensation expense). Adding *unvested* future-service RSUs in
    full without offsetting unrecognized compensation cost can double-count SBC
    dilution; ITM vested/outstanding options carry real economic dilution via TSM.
    We therefore report:
      - `basic_period_end_shares`: exact latest Class A+B cover basic count
      - `itm_option_incremental_shares`: N_opt * (1 - WAEP / P) when P > WAEP
      - `tsm_diluted_shares_ex_unvested_rsus`: basic + ITM option dilution
      - `tsm_diluted_shares_with_rsus`: basic + ITM option dilution + nonvested RSUs (conservative upper bound)
      - `qtr_reported_diluted_waso`: latest 10-Q reported diluted WASO for reference
    """
    if basic_period_end_shares <= 0:
        return {"status": "MISSING", "recommended_shares": 0.0}

    opt_inc = 0.0
    if options_outstanding and options_waep is not None and current_price > options_waep > 0:
        opt_inc = float(options_outstanding) * (1.0 - float(options_waep) / float(current_price))

    tsm_ex_rsu = float(basic_period_end_shares + opt_inc)
    rsu_shares = float(rsus_nonvested or 0.0)
    tsm_full = float(tsm_ex_rsu + rsu_shares)

    return {
        "status": "VALUE",
        "basic_period_end_shares": float(basic_period_end_shares),
        "options_outstanding": float(options_outstanding or 0.0),
        "options_waep": float(options_waep) if options_waep is not None else None,
        "itm_option_incremental_shares": float(opt_inc),
        "rsus_nonvested": rsu_shares,
        "tsm_diluted_shares_ex_unvested_rsus": tsm_ex_rsu,
        "tsm_diluted_shares_with_rsus": tsm_full,
        "qtr_reported_diluted_waso": float(qtr_diluted_waso) if qtr_diluted_waso else None,
        # Standard institutional GAAP DCF (where EBIT already deducts SBC):
        # Include ITM options TSM dilution on top of cover basic shares and surface RSUs separately.
        "recommended_shares": tsm_ex_rsu if opt_inc > 0 else float(basic_period_end_shares),
    }


def extract_sec_edgar_reconciliation(
    ticker: str,
    cik: Optional[str] = None,
    current_price: float = 0.0,
    extra_dirs: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Retrieve authoritative SEC EDGAR XBRL facts for any US GAAP ticker.
    Returns structured annual & latest-quarter provenance dicts or None if unavailable.
    """
    facts, source_label = _load_local_companyfacts(ticker, cik=cik, extra_dirs=extra_dirs)
    resolved_cik = str(facts.get("cik") or cik or "").zfill(10) if (facts or cik) else None
    if not facts:
        facts, source_label, live_cik = _load_live_companyfacts(ticker, cik=cik)
        if live_cik:
            resolved_cik = live_cik
    xml_cover = _extract_cover_shares_from_xml(ticker, extra_dirs=extra_dirs)
    if not xml_cover and resolved_cik:
        live_xml = _fetch_live_latest_xbrl_cover(resolved_cik)
        if live_xml:
            try:
                xml_cover = _parse_xbrl_cover_text(live_xml[0], live_xml[1])
            except Exception as exc:
                logger.debug("Live XML cover parse skipped for %s: %s", ticker, exc)

    if not facts and not xml_cover:
        return None

    result: Dict[str, Any] = {
        "available": True,
        "entity_name": facts.get("entityName") if facts else ticker,
        "cik": facts.get("cik") if facts else (resolved_cik or cik),
        "consolidation_basis": "Consolidated",
        "currency": "USD",
        "source_citation": source_label or (f"SEC XBRL Filing ({xml_cover['source_file']})" if xml_cover else "SEC EDGAR"),
        "basic_waso_by_year": {},
        "diluted_waso_by_year": {},
        "basic_eps_by_year": {},
        "diluted_eps_by_year": {},
        "cash_taxes_paid_by_year": {},
        "revenue_by_year": {},
        "operating_income_by_year": {},
        "operating_lease_liability_by_year": {},
        "restricted_cash_by_year": {},
        "latest_quarter": {},
        "cover_shares": xml_cover,
    }

    # Pre-seed annual duration facts from cached 10-K XML when available (and merge companyfacts below)
    for k_xml, bucket_key in [
        ("basic_waso", "basic_waso_by_year"),
        ("diluted_waso", "diluted_waso_by_year"),
        ("basic_eps", "basic_eps_by_year"),
        ("diluted_eps", "diluted_eps_by_year"),
        ("cash_taxes_paid", "cash_taxes_paid_by_year"),
    ]:
        # Also inspect 10k.xml specifically if cover file was 10q.xml
        if xml_cover and xml_cover.get("xml_durations", {}).get(k_xml):
            result[bucket_key].update(xml_cover["xml_durations"][k_xml])

    if facts:
        for yr, rec in _pick_annual_duration_facts(
            facts, "us-gaap",
            ["WeightedAverageNumberOfSharesOutstandingBasic", "WeightedAverageNumberOfShareBasicAndDiluted"],
            "shares",
        ).items():
            result["basic_waso_by_year"].setdefault(yr, rec)
        result["diluted_waso_by_year"].update(_pick_annual_duration_facts(
            facts, "us-gaap",
            ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
            "shares",
        ))
        result["basic_eps_by_year"].update(_pick_annual_duration_facts(
            facts, "us-gaap", ["EarningsPerShareBasic"], "USD/shares"
        ))
        result["diluted_eps_by_year"].update(_pick_annual_duration_facts(
            facts, "us-gaap", ["EarningsPerShareDiluted"], "USD/shares"
        ))
        result["cash_taxes_paid_by_year"].update(_pick_annual_duration_facts(
            facts, "us-gaap", ["IncomeTaxesPaid", "IncomeTaxesPaidNet"], "USD"
        ))
        result["revenue_by_year"].update(_pick_annual_duration_facts(
            facts,
            "us-gaap",
            [
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
            ],
            "USD",
        ))
        result["operating_income_by_year"].update(_pick_annual_duration_facts(
            facts, "us-gaap", ["OperatingIncomeLoss"], "USD"
        ))

        # Check cached 10-K XML too if basic_waso has gaps relative to diluted_waso
        missing_basic_yrs = set(result["diluted_waso_by_year"]) - set(result["basic_waso_by_year"])
        if missing_basic_yrs:
            t_low = (ticker or "").strip().lower()
            for root in _search_roots(extra_dirs):
                for sfx in ("10k.xml", "_10k.xml"):
                    fp10k = root / f"{t_low}{sfx}"
                    if fp10k.is_file():
                        try:
                            tree10k = ET.fromstring(fp10k.read_text(encoding="utf-8", errors="ignore"))
                            ctxs = {}
                            for elem in tree10k.iter():
                                if elem.tag.split("}")[-1] == "context":
                                    cid = elem.attrib.get("id", "")
                                    s_d = e_d = None
                                    dims = []
                                    for sub in elem.iter():
                                        sln = sub.tag.split("}")[-1]
                                        if sln == "startDate" and sub.text:
                                            s_d = sub.text.strip()
                                        elif sln == "endDate" and sub.text:
                                            e_d = sub.text.strip()
                                        elif "explicitMember" in sln or "typedMember" in sln:
                                            dims.append((sub.text or "").strip().lower())
                                    h_d = any(not ("and" in d and "commonstock" in d) for d in dims)
                                    ctxs[cid] = (s_d, e_d, h_d)
                            for elem in tree10k.iter():
                                if elem.tag.split("}")[-1] == "WeightedAverageNumberOfSharesOutstandingBasic" and elem.text:
                                    s_d, e_d, h_d = ctxs.get(elem.attrib.get("contextRef", ""), (None, None, True))
                                    if not h_d and s_d and e_d:
                                        from datetime import date
                                        if (date.fromisoformat(e_d[:10]) - date.fromisoformat(s_d[:10])).days >= 300:
                                            yr = int(e_d[:4])
                                            result["basic_waso_by_year"][yr] = {
                                                "value": float(elem.text.strip()),
                                                "tag": "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
                                                "form": "10-K",
                                                "start": s_d,
                                                "end": e_d,
                                                "unit": "shares",
                                            }
                        except Exception:
                            pass
                        break

        # Latest balance-sheet instant facts (leases, restricted cash, equity awards, cover shares)
        lease_tot = _pick_latest_instant_fact(facts, "us-gaap", ["OperatingLeaseLiability"], "USD")
        lease_cur = _pick_latest_instant_fact(facts, "us-gaap", ["OperatingLeaseLiabilityCurrent"], "USD")
        lease_nc = _pick_latest_instant_fact(facts, "us-gaap", ["OperatingLeaseLiabilityNoncurrent"], "USD")
        rc_latest = _pick_latest_instant_fact(
            facts, "us-gaap",
            ["RestrictedCashAndCashEquivalentsAtCarryingValue", "RestrictedCashAndCashEquivalents", "RestrictedCashCurrent", "RestrictedCash"],
            "USD",
        )
        aro_latest = _pick_latest_instant_fact(
            facts, "us-gaap",
            ["AssetRetirementObligationsNoncurrent", "AssetRetirementObligation"],
            "USD",
        )
        opt_out = _pick_latest_instant_fact(
            facts, "us-gaap",
            ["ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber"],
            "shares",
        )
        opt_waep = _pick_latest_instant_fact(
            facts, "us-gaap",
            ["ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice"],
            "USD/shares",
        )
        rsu_nonv = _pick_latest_instant_fact(
            facts, "us-gaap",
            ["ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber"],
            "shares",
        )
        # Latest 10-Q / 10-K diluted WASO (prefer shortest duration e.g. 3M quarterly on latest end date)
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        qtr_dil = None
        for it in us_gaap.get("WeightedAverageNumberOfDilutedSharesOutstanding", {}).get("units", {}).get("shares", []):
            if str(it.get("form", "")).startswith(("10-Q", "10-K")):
                score = (str(it.get("end", "")), str(it.get("start", "")), str(it.get("filed", "")))
                if qtr_dil is None or score > qtr_dil[0]:
                    qtr_dil = (score, float(it["val"]), it.get("end"), it.get("form"))

        cover_tot = (xml_cover or {}).get("total_common_shares")
        if cover_tot is None:
            dei_cover = _pick_latest_instant_fact(facts, "dei", ["EntityCommonStockSharesOutstanding"], "shares")
            if dei_cover:
                cover_tot = dei_cover["value"]

        result["latest_quarter"] = {
            "operating_lease_total": lease_tot,
            "operating_lease_current": lease_cur,
            "operating_lease_noncurrent": lease_nc,
            "restricted_cash": rc_latest,
            "aro_obligation": aro_latest,
            "options_outstanding": opt_out,
            "options_waep": opt_waep,
            "rsus_nonvested": rsu_nonv,
            "diluted_waso": {"value": qtr_dil[1], "end": qtr_dil[2], "form": qtr_dil[3]} if qtr_dil else None,
        }
        if cover_tot and cover_tot > 0:
            result["tsm_bridge"] = compute_tsm_dilution_bridge(
                basic_period_end_shares=float(cover_tot),
                current_price=current_price,
                options_outstanding=opt_out["value"] if opt_out else (xml_cover or {}).get("options_outstanding"),
                options_waep=opt_waep["value"] if opt_waep else (xml_cover or {}).get("options_waep"),
                rsus_nonvested=rsu_nonv["value"] if rsu_nonv else (xml_cover or {}).get("rsus_nonvested"),
                qtr_diluted_waso=qtr_dil[1] if qtr_dil else None,
            )

    return result
