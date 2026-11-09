"""
Centralized Classification & Special-Case Override Registry (`classification_overrides.py`).

Consolidates all ticker-specific classification overrides, sector/industry fixes,
captive-finance debt netting flags, cross-currency reporting rules, and balance-sheet
financial institution sets into a single auditable registry.

Every entry requires:
  - `symbol`: Base uppercase symbol (without `.NS` / `.BO` exchange suffix)
  - `category`: Primary domain classification bucket
  - `reason`: Explicit institutional/accounting rationale for the override
  - `added`: ISO date (`YYYY-MM-DD`) when the rule was verified and recorded
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple


@dataclass(frozen=True)
class TickerOverrideEntry:
    symbol: str
    category: str
    is_extractive: Optional[bool] = None
    is_cyclical: Optional[bool] = None
    is_financial: Optional[bool] = None
    has_captive_finance: bool = False
    consolidates_nbfc_assets: bool = False
    is_downstream_refiner: bool = False
    usd_reporting_indian_adr: bool = False
    reporting_currency: Optional[str] = None
    force_sector: Optional[str] = None
    force_industry: Optional[str] = None
    fallback_sector: Optional[str] = None
    fallback_industry: Optional[str] = None
    reason: str = ""
    added: str = "2026-11-06"


def normalize_base_symbol(symbol: Optional[str]) -> str:
    """Strip `.NS` / `.BO` suffixes and normalize to uppercase."""
    return (symbol or "").replace(".NS", "").replace(".BO", "").strip().upper()


# ---------------------------------------------------------------------------
# 1. Explicit Per-Ticker Override Registry
# ---------------------------------------------------------------------------
_RAW_ENTRIES = [
    # --- Diversified Conglomerates & Specialty Compounders (Not Extractive/Cyclical) ---
    TickerOverrideEntry(
        symbol="RELIANCE",
        category="non_cyclical_conglomerate",
        is_extractive=False,
        is_cyclical=False,
        fallback_sector="Energy",
        fallback_industry="Oil & Gas Refining & Marketing",
        reason="Diversified conglomerate (Jio Telecom + Reliance Retail + O2C) — not an upstream depleting oil/coal mine.",
        added="2026-11-06",
    ),
    TickerOverrideEntry(
        symbol="ADANIENT",
        category="non_cyclical_conglomerate",
        is_extractive=False,
        is_cyclical=False,
        force_sector="Industrials",
        force_industry="Infrastructure & Conglomerates",
        fallback_sector="Industrials",
        fallback_industry="Infrastructure & Conglomerates",
        reason="Infrastructure incubator (7 privatized Airports, Solar Module Mfg, Roads, Data Centers) misclassified by Yahoo as legacy Thermal Coal.",
        added="2026-11-06",
    ),
    TickerOverrideEntry(
        symbol="PIDILITIND",
        category="specialty_compounder",
        is_extractive=False,
        is_cyclical=False,
        fallback_sector="Basic Materials",
        fallback_industry="Specialty Chemicals",
        reason="Branded consumer adhesives compounder (Fevicol) with pricing power, not a commodity chemical producer.",
        added="2026-11-06",
    ),
    TickerOverrideEntry(
        symbol="ASIANPAINT",
        category="specialty_compounder",
        is_extractive=False,
        is_cyclical=False,
        fallback_sector="Basic Materials",
        fallback_industry="Specialty Chemicals",
        reason="Branded decorative coatings & home decor compounder, not a bulk commodity cyclical.",
        added="2026-11-06",
    ),
    TickerOverrideEntry(
        symbol="BERGEPAINT",
        category="specialty_compounder",
        is_extractive=False,
        is_cyclical=False,
        fallback_sector="Basic Materials",
        fallback_industry="Specialty Chemicals",
        reason="Branded decorative paints compounder with consumer pricing power.",
        added="2026-11-06",
    ),
    TickerOverrideEntry(
        symbol="SHW",
        category="specialty_compounder",
        is_extractive=False,
        is_cyclical=False,
        fallback_sector="Basic Materials",
        fallback_industry="Specialty Chemicals",
        reason="Sherwin-Williams branded architectural coatings compounder.",
        added="2026-11-06",
    ),
    TickerOverrideEntry(
        symbol="LIN",
        category="specialty_compounder",
        is_extractive=False,
        is_cyclical=False,
        fallback_sector="Basic Materials",
        fallback_industry="Specialty Chemicals",
        reason="Linde industrial gases operating on long-term take-or-pay onsite contracts.",
        added="2026-11-06",
    ),
    TickerOverrideEntry(
        symbol="ECL",
        category="specialty_compounder",
        is_extractive=False,
        is_cyclical=False,
        fallback_sector="Basic Materials",
        fallback_industry="Specialty Chemicals",
        reason="Ecolab institutional hygiene & water treatment compounder.",
        added="2026-11-06",
    ),
    TickerOverrideEntry(
        symbol="APD",
        category="specialty_compounder",
        is_extractive=False,
        is_cyclical=False,
        fallback_sector="Basic Materials",
        fallback_industry="Specialty Chemicals",
        reason="Air Products industrial gases with contracted take-or-pay cash flows.",
        added="2026-11-06",
    ),

    # --- Upstream Extractive Oil, Gas & Mining (Physical Reserve Depletion) ---
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="extractive_oil_gas",
            is_extractive=True,
            is_cyclical=True,
            fallback_sector="Energy",
            fallback_industry="Oil & Gas Integrated",
            reason="Upstream/integrated oil & gas producer subject to physical reservoir depletion and infill CapEx.",
            added="2026-11-06",
        )
        for sym in [
            "ONGC", "OIL", "XOM", "CVX", "COP", "OXY", "EOG",
            "DVN", "FANG", "APA", "HES", "MRO", "CTRA", "EQT",
        ]
    ],
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="extractive_mining_coal",
            is_extractive=True,
            is_cyclical=True,
            fallback_sector="Basic Materials",
            fallback_industry="Metals & Mining",
            reason="Extractive coal/metals mining operator with finite reserve life and statutory mine-closure ARO.",
            added="2026-11-06",
        )
        for sym in [
            "COALINDIA", "VEDL", "NMDC", "MOIL", "GMDC", "HINDCOPPER", "HINDZINC",
            "BHP", "RIO", "VALE", "FCX", "NEM", "GOLD", "AEM", "SCCO", "TECK",
            "BTU", "ARCH", "AMR",
        ]
    ],

    # --- Downstream Oil Refining & Marketing Cyclicals ---
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="cyclical_refining",
            is_extractive=False,
            is_cyclical=True,
            is_downstream_refiner=sym in {"IOC", "BPCL", "HPCL", "HINDPETRO", "MRPL", "CHENNPETRO"},
            fallback_sector="Energy",
            fallback_industry="Oil & Gas Refining & Marketing",
            reason="Downstream refining & marketing operator whose margins mean-revert with Singapore GRM refining cracks.",
            added="2026-11-06",
        )
        for sym in [
            "IOC", "BPCL", "HPCL", "HINDPETRO", "HNDNPETRO", "MRPL", "CHENNPETRO",
            "CASTROLIND", "PSX", "MPC", "VLO",
        ]
    ],

    # --- Metals, Steel, Cement & Commodity Chemical Cyclicals ---
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="cyclical_materials",
            is_extractive=False,
            is_cyclical=True,
            fallback_sector="Basic Materials",
            fallback_industry="Steel & Basic Materials",
            reason="Commodity steel, aluminum, cement, or chemical producer subject to multi-year margin cycles.",
            added="2026-11-06",
        )
        for sym in [
            "TATASTEEL", "JSWSTEEL", "SAIL", "JINDALSTEL", "JSL", "APLAPOLLO",
            "HINDALCO", "NATIONALUM", "ULTRACEMCO", "AMBUJACEM", "SHREECEM",
            "ACC", "DALBHARAT", "RAMCOCEM", "JKCEMENT", "NUE", "STLD", "CLF",
            "X", "AA", "DOW", "LYB", "CF", "MOS", "NTR",
        ]
    ],

    # --- Healthcare & Pharma Cloud-IP Sector Fallbacks ---
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="healthcare_pharma",
            fallback_sector="Healthcare",
            fallback_industry="Drug Manufacturers - Specialty & Generic",
            reason="Pharmaceutical manufacturer requiring deterministic Healthcare sector tag when cloud IPs rate-limit quoteSummary.",
            added="2026-11-06",
        )
        for sym in [
            "SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN",
            "AUROPHARMA", "TORNTPHARM", "ZYDUSLIFE",
        ]
    ],

    # --- IT Services & USD-Reporting Indian ADRs ---
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="it_services",
            usd_reporting_indian_adr=sym in {"INFY", "WIT"},
            fallback_sector="Technology",
            fallback_industry="Information Technology Services",
            reason="IT services exporter; INFY/WIT file IFRS statements in USD while trading in INR on NSE/BSE.",
            added="2026-11-06",
        )
        for sym in [
            "INFY", "WIT", "TCS", "WIPRO", "HCLTECH", "TECHM",
            "LTIM", "PERSISTENT", "COFORGE", "MPHASIS",
        ]
    ],

    # --- Industrial & Auto Conglomerates with Captive Finance / Consolidated NBFC Arms ---
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="captive_finance_industrial",
            is_extractive=False if sym == "GRASIM" else None,
            is_cyclical=True if sym == "GRASIM" else None,
            is_financial=True if sym == "BAJAJFINSV" else None,
            has_captive_finance=True,
            consolidates_nbfc_assets=sym in {"GRASIM", "ABREL", "LT", "M&M", "BAJAJFINSV"},
            reporting_currency="JPY" if sym in {"TM", "HMC"} else None,
            fallback_sector="Basic Materials" if sym == "GRASIM" else None,
            fallback_industry="Building Materials" if sym == "GRASIM" else None,
            reason="Industrial/OEM conglomerate with a consolidated captive financing or NBFC lending subsidiary whose customer loan receivables offset non-operating financial debt.",
            added="2026-11-06",
        )
        for sym in [
            "DE", "CAT", "PCAR", "F", "GM", "TM", "HMC", "HPE", "IBM",
            "LT", "M&M", "TATAMOTORS", "TMPV", "TMCV", "BAJAJ-AUTO", "TVSMOTOR",
            "ASHOKLEY", "GRASIM", "ABREL", "CHOLAHLDNG", "BAJAJFINSV",
        ]
    ],

    # --- Foreign-Currency Reporting ADRs Trading in USD on US Exchanges ---
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="foreign_currency_adr",
            reporting_currency=curr,
            fallback_sector=sec,
            fallback_industry=ind,
            reason=f"Foreign ADR trading in USD on NYSE/NASDAQ while reporting statutory financial statements in {curr}.",
            added="2026-11-08",
        )
        for sym, curr, sec, ind in [
            ("NVO", "DKK", "Healthcare", "Drug Manufacturers - General"),
            ("TSM", "TWD", "Technology", "Semiconductors"),
            ("ASML", "EUR", "Technology", "Semiconductor Equipment & Materials"),
            ("SAP", "EUR", "Technology", "Software - Application"),
            ("SNY", "EUR", "Healthcare", "Drug Manufacturers - General"),
            ("SONY", "JPY", "Technology", "Consumer Electronics"),
            ("BABA", "CNY", "Consumer Cyclical", "Internet Retail"),
            ("PDD", "CNY", "Consumer Cyclical", "Internet Retail"),
            ("JD", "CNY", "Consumer Cyclical", "Internet Retail"),
            ("BIDU", "CNY", "Communication Services", "Internet Content & Information"),
        ]
    ],

    # --- Capital-Light Fee-Based Financial Platforms & Electronic Brokers (Not Commercial Banks) ---
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="capital_light_financial",
            is_financial=False,
            reason="Fee-based market infrastructure, discount broker, depository, AMC, or fintech platform with no lending balance sheet; evaluated via Standard FCFF DCF.",
            added="2026-11-09",
        )
        for sym in [
            "GROWW", "ANGELONE", "5PAISA", "GEOJITFSL", "SMCGLOBAL", "SHAREINDIA",
            "MONARCH", "DBSTOCKBRO", "ARIHANTCAP", "ASHIKAG", "ALMONDZ", "INDOTHAI",
            "ALGOQUANT", "ALANKIT", "DAMCAPITAL", "MCX", "BSE", "IEX", "CDSL",
            "CAMS", "CAMSLTD", "KFINTECH", "CRISIL", "ICRA", "CAREERP", "HDFCAMC",
            "NAM-INDIA", "UTIAMC", "ABSLAMC", "ISEC", "MOTILALOFS", "ANANDRATHI",
            "PRUDENT", "NUVAMA", "360ONE", "POLICYBZR", "PAYTM",
            "NDAQ", "ICE", "CME", "CBOE", "SPGI", "MCO", "MSCI", "FDS", "V", "MA",
            "PYPL", "XYZ", "SQ", "COIN", "HOOD", "BLK", "TROW", "BEN", "IVZ",
            "IBKR", "LPLA", "RJF", "VIRT", "FUTU", "TIGR", "XP",
        ]
    ],

    # --- Enterprise Software Misclassified by 'Financial' Keyword in Name ---
    TickerOverrideEntry(
        symbol="OFSS",
        category="it_services",
        is_financial=False,
        force_sector="Technology",
        force_industry="Software - Infrastructure",
        fallback_sector="Technology",
        fallback_industry="Software - Infrastructure",
        reason="Oracle Financial Services Software is an enterprise core banking software vendor (FLEXCUBE), not a banking or lending institution.",
        added="2026-11-09",
    ),

    # --- Known Balance-Sheet Financial Institutions (Banks, NBFCs, Insurers) ---
    *[
        TickerOverrideEntry(
            symbol=sym,
            category="balance_sheet_financial",
            is_financial=True,
            reason="Balance-sheet lending institution, commercial bank, NBFC, or insurer routed to Multi-Stage FCFE / DDM model.",
            added="2026-11-06",
        )
        for sym in [
            "IREDA", "PFC", "REC", "IRFC", "HUDCO", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK",
            "KOTAKBANK", "BAJFINANCE", "BAJAJHFL", "CHOLAFIN", "MUTHOOTFIN", "MANAPPURAM",
            "SHRIRAMFIN", "M&MFIN", "JIOFIN", "POONAWALLA", "AAVAS", "CANFINHOME", "HOMEFIRST",
            "CREDITACC", "IDFCFIRSTB", "BANDHANBNK", "FEDERALBNK", "INDUSINDBK", "AUBANK", "PNB",
            "BANKBARODA", "UNIONBANK", "CANBK", "INDIANB", "MAHABANK", "UCOBANK", "CENTRALBK",
            "IOB", "J&KBANK", "KARURVYSYA", "SOUTHBANK", "CSBBANK", "DCBBANK", "CITYUNIONB",
            "EQUITASBNK", "UJJIVANSFB", "SURYODAY", "ESAFSFB", "SBICARD", "ICICIGI", "HDFCLIFE",
            "SBILIFE", "ICICIPRULI", "LICI", "GICRE", "NIACL", "STARHEALTH", "SAMMAANCAP", "LTF",
            "JMFINANCIL", "EDELWEISS", "IIFL", "ABCAPITAL", "SUNDARMFIN", "MASFIN", "REPCOHOME",
            "LICHSGFIN", "PNBHOUSING", "GICHSGFIN", "APTUS", "SBFC", "FIVESTAR", "SPANDANA",
            "FUSION", "SATIN", "ARMANFIN", "UGROCAP", "CGCL", "PAISALO", "IFCI", "PFS",
            "TOURISMFIN", "PEL", "RELIGARE", "CENTRUM", "RBLBANK", "YESBANK", "IDBI", "KTKBANK",
            "TMB", "DHANBANK", "CAPTRUST", "MUTHOOTMF", "INDOSTAR", "FEDFINA", "UTKARSHBNK",
            "JANASFB", "CAPITALSFB", "TATACAP", "JPM", "BAC", "WFC", "C", "GS", "MS", "AXP",
            "COF", "USB", "PNC", "TFC", "SCHW", "BK", "FITB", "MTB", "KEY", "CFG", "HBAN",
            "RF", "SYF", "DFS", "SOFI", "AFRM", "ALLY", "SLM", "NAVI",
        ]
    ],
]


# Build lookup dictionary by symbol
CLASSIFICATION_REGISTRY: Dict[str, TickerOverrideEntry] = {
    entry.symbol: entry for entry in _RAW_ENTRIES
}

# Derived sets for fast O(1) lookups in data_layer.py and main.py
KNOWN_BALANCE_SHEET_FINANCIAL_SYMBOLS: Set[str] = {
    s for s, e in CLASSIFICATION_REGISTRY.items()
    if e.is_financial is True
}
NON_CYCLICAL_CONGLOMERATE_SYMBOLS: Set[str] = {
    s for s, e in CLASSIFICATION_REGISTRY.items()
    if e.is_extractive is False and e.is_cyclical is False
}
KNOWN_EXTRACTIVE_SYMBOLS: Set[str] = {
    s for s, e in CLASSIFICATION_REGISTRY.items()
    if e.is_extractive is True
}
KNOWN_CYCLICAL_SYMBOLS: Set[str] = {
    s for s, e in CLASSIFICATION_REGISTRY.items()
    if e.is_cyclical is True
}
DOWNSTREAM_REFINING_SYMBOLS: Set[str] = {
    s for s, e in CLASSIFICATION_REGISTRY.items()
    if e.is_downstream_refiner
}
CAPTIVE_FINANCE_SYMBOLS: Set[str] = {
    s for s, e in CLASSIFICATION_REGISTRY.items()
    if e.has_captive_finance
}
NBFC_CONSOLIDATING_SYMBOLS: Set[str] = {
    s for s, e in CLASSIFICATION_REGISTRY.items()
    if e.consolidates_nbfc_assets
}
USD_REPORTING_INDIAN_ADR_SYMBOLS: Set[str] = {
    s for s, e in CLASSIFICATION_REGISTRY.items()
    if e.usd_reporting_indian_adr
}
KNOWN_CAPITAL_LIGHT_FINANCIAL_SYMBOLS: Set[str] = {
    s for s, e in CLASSIFICATION_REGISTRY.items()
    if e.category == "capital_light_financial" or (e.is_financial is False and "broker" in e.reason.lower())
}


def get_override_entry(symbol: Optional[str]) -> Optional[TickerOverrideEntry]:
    """Return the TickerOverrideEntry for `symbol` (ignoring .NS/.BO), or None."""
    return CLASSIFICATION_REGISTRY.get(normalize_base_symbol(symbol))


def resolve_sector_and_industry(
    symbol: Optional[str],
    company_name: Optional[str],
    raw_sector: Optional[str],
    raw_industry: Optional[str],
    is_extractive: bool,
    is_cyclical: bool,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Apply explicit sector/industry corrections (e.g. ADANIENT) and deterministic
    cloud-IP fallbacks when Yahoo Finance endpoints are rate-limited.
    """
    clean_sym = normalize_base_symbol(symbol)
    entry = CLASSIFICATION_REGISTRY.get(clean_sym)
    sector = raw_sector
    industry = raw_industry

    if entry and entry.force_sector:
        sector = entry.force_sector
    if entry and entry.force_industry:
        industry = entry.force_industry

    if not sector:
        name_lower = (company_name or "").lower()
        if is_extractive:
            if (
                any(k in name_lower for k in ["oil", "gas", "petroleum"])
                or (entry and entry.category == "extractive_oil_gas")
            ):
                sector = "Energy"
                industry = industry or "Oil & Gas Integrated"
            else:
                sector = "Basic Materials"
                industry = industry or "Metals & Mining"
        elif is_cyclical:
            if (
                any(k in name_lower for k in ["petroleum", "oil", "refin"])
                or clean_sym in DOWNSTREAM_REFINING_SYMBOLS
            ):
                sector = "Energy"
                industry = industry or "Oil & Gas Refining & Marketing"
            else:
                sector = "Basic Materials"
                industry = industry or "Steel & Basic Materials"
        elif (
            any(k in name_lower for k in ["pharma", "laboratories", "healthcare", "biocon", "hospital", "lifesciences"])
            or (entry and entry.category == "healthcare_pharma")
        ):
            sector = "Healthcare"
            industry = industry or "Drug Manufacturers - Specialty & Generic"
        elif (
            any(k in name_lower for k in ["infosys", "technologies", "software", "consultancy", "tech ", "systems", "infotech", "wipro", "mindtree"])
            or (entry and entry.category == "it_services")
        ):
            sector = "Technology"
            industry = industry or "Information Technology Services"
        elif clean_sym == "RELIANCE" or "reliance industries" in name_lower:
            sector = "Energy"
            industry = industry or "Oil & Gas Refining & Marketing"

    return sector, industry
