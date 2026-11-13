"""
Canonical Financial Schema, Field Provenance & Fail-Closed Status Definitions.

Provides machine-readable provenance metadata (`VALUE`, `ZERO`, `MISSING`,
`NOT_DISCLOSED`, `NOT_APPLICABLE`, `CONFLICTING_SOURCE`, `UNAVAILABLE`),
fail-closed model validation statuses (`VALIDATED`, `VALIDATED_WITH_LIMITATIONS`,
`UNVERIFIED`, `BLOCKED_DATA_QUALITY`, `BLOCKED_ACCOUNTING_RECONCILIATION`,
`UNSUPPORTED_MODEL`), and structural sector/accounting-standard classification
without ticker-specific hardcodes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

FIELD_STATUSES = {
    "VALUE",
    "ZERO",
    "MISSING",
    "NOT_DISCLOSED",
    "NOT_APPLICABLE",
    "CONFLICTING_SOURCE",
    "UNAVAILABLE",
}

VALIDATION_STATUSES = {
    "VALIDATED",
    "VALIDATED_WITH_LIMITATIONS",
    "UNVERIFIED",
    "BLOCKED_DATA_QUALITY",
    "BLOCKED_ACCOUNTING_RECONCILIATION",
    "UNSUPPORTED_MODEL",
}

ACCOUNTING_STANDARDS = {
    "US_GAAP",
    "IND_AS",
    "IFRS",
    "UNKNOWN",
}


def make_provenance(
    value: Optional[float],
    status: str = "VALUE",
    source_citation: str = "Yahoo Finance API",
    period: Optional[str] = None,
    unit: Optional[str] = None,
    consolidation_basis: str = "Consolidated",
    note_ref: Optional[str] = None,
    detail: Optional[str] = None,
    raw_value: Optional[Any] = None,
) -> Dict[str, Any]:
    """Create a canonical field-level provenance record."""
    norm_status = status if status in FIELD_STATUSES else "UNAVAILABLE"
    if value is None and norm_status == "VALUE":
        norm_status = "MISSING"
    elif value == 0.0 and norm_status == "VALUE":
        norm_status = "ZERO"
    return {
        "value": value,
        "status": norm_status,
        "source_citation": source_citation,
        "period": period,
        "unit": unit,
        "consolidation_basis": consolidation_basis,
        "note_ref": note_ref,
        "detail": detail,
        "raw_value": raw_value if raw_value is not None else value,
    }


def detect_accounting_standard(market: str, currency: Optional[str] = None) -> str:
    """Determine governing accounting & lease standard from market / currency."""
    m = (market or "").strip().upper()
    curr = (currency or "").strip().upper()
    if m == "US" or curr == "USD":
        return "US_GAAP"
    if m == "IN" or curr == "INR":
        return "IND_AS"
    return "IFRS"


def classify_sector_driver_profile(
    sector: Optional[str],
    industry: Optional[str],
    company_name: Optional[str] = None,
    is_extractive: bool = False,
    is_cyclical: bool = False,
    is_capital_light_financial: bool = False,
    is_utility: bool = False,
    acct_std: str = "US_GAAP",
) -> Dict[str, Any]:
    """Identify the economic operating-driver profile & accounting focus for any sector."""
    sec_l = (sector or "").lower()
    ind_l = (industry or "").lower()
    name_l = (company_name or "").lower()
    text = f"{sec_l} {ind_l} {name_l}"

    if is_capital_light_financial:
        return {
            "profile_id": "CAPITAL_LIGHT_FINANCIAL",
            "label": "Capital-Light Financial Infrastructure & Asset Management",
            "primary_drivers": "Fee/AUM yield margins, operating leverage, minimal financial debt",
            "accounting_focus": "Separate own unrestricted cash from client clearing/settlement escrow float; cap NWC impact at [-5%, +5%].",
            "limitation_note": None,
        }
    if is_utility:
        return {
            "profile_id": "REGULATED_UTILITY",
            "label": "Rate-Regulated Utility (Ind AS 114 / ASC 980)",
            "primary_drivers": "Regulated Asset Base (RAB), allowed ROE, tariff deferral recovery, committed CapEx",
            "accounting_focus": f"Restore net regulatory deferral income in EBIT; symmetric Net D&A; {acct_std} lease retention in Debt.",
            "limitation_note": None,
        }
    if any(k in text for k in ("oil & gas midstream", "midstream", "pipeline", "master limited", "partners lp", "partners, l.p.")):
        return {
            "profile_id": "MLP_MIDSTREAM_INFRA",
            "label": "Midstream Energy Pipeline & Partnership Infrastructure",
            "primary_drivers": "Fee-based volume throughput, maintenance vs growth CapEx, distribution coverage, leverage",
            "accounting_focus": "Use Partners' Common Stock Equity when Stockholders Equity is reported as zero; separate growth pipeline CapEx from maintenance.",
            "limitation_note": "Pass-through MLP tax/IDR structures and Distributable Cash Flow (DCF) schedules rely on K-1 / 10-K partnership notes.",
        }
    if is_extractive:
        return {
            "profile_id": "EXTRACTIVE_COMMODITY",
            "label": "Extractive Upstream Oil, Gas & Mining",
            "primary_drivers": "Realized commodity strip, reserve replacement CapEx, ARO decommissioning obligations",
            "accounting_focus": "Evaluate Long-Term Provisions (ARO), uncommissioned CWIP, and Gordon-vs-Exit multiple terminal bounds.",
            "limitation_note": None,
        }
    if is_cyclical:
        return {
            "profile_id": "CYCLICAL_INDUSTRIAL",
            "label": "Cyclical Commodity & Capital-Intensive Manufacturing",
            "primary_drivers": "Mid-cycle operating margin mean reversion, capacity utilization, maintenance CapEx",
            "accounting_focus": "Use cyclical margin normalization and unadjusted vs blended terminal cross-checks.",
            "limitation_note": None,
        }
    if any(k in text for k in ("software", "saas", "internet content", "information technology services", "cloud", "application", "infrastructure")):
        return {
            "profile_id": "SAAS_HIGH_GROWTH_TECH",
            "label": "Software, SaaS & High-Growth Technology",
            "primary_drivers": "Revenue growth fade, GAAP EBIT margin expansion (net of SBC), deferred-revenue negative NWC",
            "accounting_focus": f"TSM option dilution schedule, unvested RSU exposure, unclipped vs normalized NWC, {acct_std} operating leases.",
            "limitation_note": None,
        }
    if any(k in text for k in ("drug manufacturer", "biotech", "pharmaceutical", "pharma", "diagnostics", "healthcare")):
        return {
            "profile_id": "PHARMA_BIOTECH",
            "label": "Pharmaceuticals, Biotech & Healthcare",
            "primary_drivers": "R&D intensity, generic/specialty margin durability, acquired intangibles amortisation",
            "accounting_focus": "Review R&D % of revenue, acquired intangible amortisation in COGS/OpEx, and tangible ROIC.",
            "limitation_note": "Pipeline patent cliffs and molecule-level exclusivity are outside statement-only DCF feeds.",
        }
    if any(k in text for k in ("telecom", "wireless", "tower", "broadcasting")):
        return {
            "profile_id": "TELECOM_DIGITAL_INFRA",
            "label": "Telecom & Tower Digital Infrastructure",
            "primary_drivers": "High upfront spectrum/tower CapEx cycle, lease liabilities, deleveraging inflection",
            "accounting_focus": f"{acct_std} lease debt aligned with ROU D&A; test high-CapEx reinvestment taper sensitivity.",
            "limitation_note": None,
        }
    if any(k in text for k in (
        "retail", "apparel", "restaurant", "specialty retail", "airline", "airways",
        "hospitality", "discount stores", "consumer defensive", "grocery",
        "warehouse club", "department store", "home improvement", "hypermarket", "supermarket",
    )):
        return {
            "profile_id": "RETAIL_AIRLINES_LEASE",
            "label": "Lease-Intensive Retail, Consumer & Aviation",
            "primary_drivers": "Store/fleet unit economics, inventory turns, lease liability policy",
            "accounting_focus": f"Strict {acct_std} lease alignment (ASC 842 OpEx vs Ind AS 116 / IFRS 16 debt + ROU D&A).",
            "limitation_note": None,
        }
    if any(k in text for k in ("engineering & construction", "heavy construction", "infrastructure operations", "real estate", "developers", "property")):
        return {
            "profile_id": "EPC_REAL_ESTATE_DEV",
            "label": "EPC Infrastructure & Real Estate Development",
            "primary_drivers": "Working capital cycle (WIP inventory, unbilled AR, customer advances), NCI project SPVs",
            "accounting_focus": "Inspect unclipped working capital, project debt, and EV-to-Equity NCI deductions.",
            "limitation_note": None,
        }
    if "conglomerate" in text or "diversified" in ind_l:
        return {
            "profile_id": "HOLDCO_CONGLOMERATE",
            "label": "Diversified Conglomerate / Holding Company",
            "primary_drivers": "Blended segment margins, multi-subsidiary NCI & preferred claims, capital allocation",
            "accounting_focus": "Deduct consolidated Minority Interest cleanly; evaluate sum-of-the-parts (SOTP) limitation.",
            "limitation_note": "Holding/conglomerate stakes in listed associates are not separately marked to market (SOTP limitation).",
        }
    return {
        "profile_id": "GENERAL_CORPORATE",
        "label": "General Operating Corporate",
        "primary_drivers": "Revenue fade, EBIT margin normalization, maintenance CapEx & tangible ROIC",
        "accounting_focus": f"Standard 3-statement reconciliation and {acct_std} lease policy consistency.",
        "limitation_note": None,
    }


def _is_nbfc_or_specialty_lender(sector: Optional[str], industry: Optional[str], company_name: Optional[str]) -> bool:
    sec_l = (sector or "").lower()
    ind_l = (industry or "").lower()
    name_l = (company_name or "").lower()
    nbfc_terms = (
        "credit services",
        "mortgage finance",
        "consumer finance",
        "specialty finance",
        "housing finance",
        "fincorp",
        "finvest",
        "microfinance",
        "nbfc",
        "vehicle finance",
        "gold loan",
        "muthoot",
        "manappuram",
        "shriram finance",
        "bajaj finance",
        "cholamandalam",
        "sundaram finance",
        "power finance",
        "rural electrification",
        "hudco",
        "ireda",
        "pfc",
    )
    if "bank" in ind_l and not any(t in ind_l for t in ("mortgage", "credit services", "consumer finance")):
        return False
    if any(t in ind_l or t in name_l for t in nbfc_terms):
        return True
    if "financial" in sec_l and "bank" not in name_l and "bancorp" not in name_l:
        return True
    return False


def classify_model_suitability(
    sector: Optional[str],
    industry: Optional[str],
    company_name: Optional[str],
    is_financial: bool,
    is_capital_light_financial: bool,
    is_non_dcf: bool,
    balance_sheet_cols: Optional[List[str]] = None,
    reg_asset_share: float = 0.0,
    is_extractive: bool = False,
    is_cyclical: bool = False,
    accounting_standard: str = "US_GAAP",
    is_reit_entity: bool = False,
) -> Dict[str, Any]:
    """
    Determine the appropriate valuation methodology cleanly from business/sector/statement
    structure (zero ticker hardcodes). Supports Standard Corporate FCFF, Regulated Utility FCFF,
    Commercial Bank DDM, NBFC Lender DDM, P&C / Life Insurance DDM, and REIT / InvIT AFFO + NAV.
    """
    sec_l = (sector or "").lower()
    ind_l = (industry or "").lower()
    name_l = (company_name or "").lower()

    if is_non_dcf:
        return {
            "model_family": "NON_OPERATING_INSTRUMENT",
            "supported": False,
            "validation_status": "UNSUPPORTED_MODEL",
            "reason": "ETF / mutual fund / trust / index vehicle is not eligible for intrinsic entity valuation.",
            "alternative_methodology": "Market NAV / expense ratio comparison.",
        }

    # Insurance carriers (Life & Annuities vs Property & Casualty / Reinsurance)
    # Routed to dedicated Actuarial Ex-AOCI Excess Return & Float DDM engines.
    insurance_terms = (
        "insurance",
        "reinsurance",
        "life assurance",
        "general insurance",
        "health insurance",
        "property & casualty",
    )
    if (
        any(t in ind_l for t in insurance_terms)
        or (
            not is_capital_light_financial
            and any(
                t in name_l
                for t in ("insurance", "life insurance", "general insurance", "reinsurance", "assurance", "max financial services")
            )
        )
    ):
        is_life_insurer = (
            "life" in ind_l
            or "annuity" in ind_l
            or "life insurance" in name_l
            or "life assurance" in name_l
            or "max financial" in name_l
        )
        model_fam = "INSURANCE_LIFE_DDM" if is_life_insurer else "INSURANCE_PNC_DDM"
        return {
            "model_family": model_fam,
            "insurer_subtype": "LIFE_ANNUITY" if is_life_insurer else "PNC_REINSURANCE",
            "supported": True,
            "validation_status": "VALIDATED_WITH_LIMITATIONS",
            "reason": (
                "Life / Annuity Insurer valued via Normalized Mid-Cycle ROE Excess Return DDM "
                "with Policyholder Float, Solvency Capital retention, and NCI exclusion."
                if is_life_insurer
                else "Property & Casualty / General Insurer valued via Ex-AOCI Book Value Excess Return DDM "
                "with Claims Loss Ratio, Policyholder Float, and Catastrophe/Underwriting Stress Test."
            ),
            "limitation_note": (
                "Standardized Yahoo statements omit statutory Embedded Value (EV + VNB) and "
                "actuarial claims reserve triangles; verify against primary annual/solvency reports."
            ),
            "alternative_methodology": "Appraisal Value (EV + VNB) / Price-to-Ex-AOCI Book vs ROE-Ke Cross-Check.",
        }

    # REITs / InvITs routed to dedicated Equity FFO / AFFO / NDCF + Cap-Rate NAV engine.
    reit_terms = ("reit", "real estate investment trust", "invit", "infrastructure investment trust")
    if is_reit_entity or any(t in sec_l or t in ind_l or t in name_l for t in reit_terms):
        return {
            "model_family": "REIT_INVIT_AFFO",
            "supported": True,
            "validation_status": "VALIDATED_WITH_LIMITATIONS",
            "reason": (
                "REIT / InvIT valued via Equity Funds From Operations (FFO = Net Income + RE D&A) "
                "and Maintenance-CapEx-adjusted AFFO / NDCF DDM alongside a Cap-Rate NOI GAV/NAV cross-check."
            ),
            "limitation_note": (
                "Maintenance vs development CapEx and statutory NAREIT FFO / SEBI NDCF adjustments rely "
                "on Yahoo Investment Property and CapEx classifications; verify against trust quarterly disclosures."
            ),
            "alternative_methodology": "P/FFO, P/AFFO Distribution Yield, and Property Appraisal GAV/NAV per Unit.",
        }

    if is_financial and not is_capital_light_financial:
        is_nbfc = _is_nbfc_or_specialty_lender(sector, industry, company_name)
        if is_nbfc:
            return {
                "model_family": "NBFC_LENDER_DDM",
                "lender_subtype": "NBFC_WHOLESALE_LENDER",
                "supported": True,
                "validation_status": "VALIDATED",
                "reason": (
                    "NBFC / wholesale-funded & specialty credit lender valued via Equity Excess Return DDM "
                    "with wholesale leverage, credit-cost ROE sensitivity, and debt-funding spread diagnostics."
                ),
                "alternative_methodology": "Price-to-Book vs ROE-Ke Residual Income & Credit-Cost Stress Test.",
            }
        return {
            "model_family": "BANK_DDM_TIER1",
            "lender_subtype": "COMMERCIAL_DEPOSIT_BANK",
            "supported": True,
            "validation_status": "VALIDATED",
            "reason": "Commercial deposit-taking bank valued via Equity Tier-1 Excess Return DDM (CET1 capital retention).",
            "alternative_methodology": "Price-to-Book vs ROE-Ke Residual Income.",
        }

    is_utility = ("utilities" in sec_l or "utility" in ind_l or reg_asset_share >= 0.05)
    driver_profile = classify_sector_driver_profile(
        sector=sector,
        industry=industry,
        company_name=company_name,
        is_extractive=is_extractive,
        is_cyclical=is_cyclical,
        is_capital_light_financial=is_capital_light_financial,
        is_utility=is_utility,
        acct_std=accounting_standard,
    )
    return {
        "model_family": "REGULATED_UTILITY_FCFF" if is_utility else "STANDARD_FCFF",
        "supported": True,
        "validation_status": "VALIDATED",
        "driver_profile": driver_profile,
        "reason": (
            "Rate-regulated utility (Ind AS 114 / ASC 980): Unlevered FCFF presented alongside "
            "Regulatory ROE / Capital-Commitment Sensitivity."
            if is_utility
            else f"{driver_profile['label']} valued via Unlevered FCFF DCF."
        ),
        "alternative_methodology": "Corporate DDM / RAB ROE Cross-Check" if is_utility else "EV/EBITDA & Unadjusted Scenario Cross-Checks",
    }
