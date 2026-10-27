"""
Ticker Universe, Live Exchange Sync, Corporate Action Resolver & Asset Gatekeeper
=================================================================================

Provides:
1. Non-DCF instrument filtering (ETFs, Commodity ETFs, Mutual Funds, Segregated
   Portfolios, REITs, InvITs, Indices, Warrants, Rights).
2. Curated + Auto-Detected Corporate Action Redirects (renames, mergers,
   reverse-mergers, demergers) using permanent legal identifiers:
   - India (NSE): ISIN NUMBER from official NSE Master (`EQUITY_L.csv`)
   - US (SEC):    CIK from official SEC EDGAR (`company_tickers.json`)
3. Capital-light financial infrastructure classification (Exchanges like MCX/BSE,
   Depositories like CDSL, RTAs like CAMS/KFINTECH, AMCs, Rating Agencies) so they
   route to Standard FCFF DCF rather than Commercial Bank Tier-1 Capital DDM.
4. Background live sync that keeps the autocomplete universe and redirect table
   automatically updated when corporate actions or new IPOs occur.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Path to frontend bundled stocks.json (used as baseline & updated on sync if writable)
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_STOCKS_JSON_PATH = os.path.abspath(
    os.path.join(_CURRENT_DIR, "..", "..", "frontend", "src", "data", "stocks.json")
)

# ---------------------------------------------------------------------------
# 1. Curated Corporate Action Redirects (Old/Merged/Demerged -> Active Ticker)
# ---------------------------------------------------------------------------
# Maps clean uppercase ticker (without .NS/.BO) -> (new_symbol_with_market_suffix, market, reason)
LEGACY_TICKER_REDIRECTS: Dict[str, Tuple[str, str, str]] = {
    # --- Indian Reverse Mergers & Financial Amalgamations ---
    "UJJIVAN": ("UJJIVANSFB.NS", "IN", "Ujjivan Financial Services reverse-merged into Ujjivan Small Finance Bank (UJJIVANSFB)"),
    "EQUITAS": ("EQUITASBNK.NS", "IN", "Equitas Holdings reverse-merged into Equitas Small Finance Bank (EQUITASBNK)"),
    "IDFC": ("IDFCFIRSTB.NS", "IN", "IDFC Ltd reverse-merged into IDFC First Bank (IDFCFIRSTB)"),
    "IDFCBANK": ("IDFCFIRSTB.NS", "IN", "IDFC Bank renamed to IDFC First Bank (IDFCFIRSTB)"),
    "HDFC": ("HDFCBANK.NS", "IN", "HDFC Ltd merged into HDFC Bank (HDFCBANK)"),
    "SRTRANSFIN": ("SHRIRAMFIN.NS", "IN", "Shriram Transport Finance merged into Shriram Finance (SHRIRAMFIN)"),
    "SHRIRAMCIT": ("SHRIRAMFIN.NS", "IN", "Shriram City Union Finance merged into Shriram Finance (SHRIRAMFIN)"),
    "IBULHSGFIN": ("SAMMAANCAP.NS", "IN", "Indiabulls Housing Finance rebranded to Sammaan Capital (SAMMAANCAP)"),
    "L&TFH": ("LTF.NS", "IN", "L&T Finance Holdings renamed to L&T Finance (LTF)"),
    # --- Indian PSU Bank Mega-Mergers ---
    "ALBK": ("INDIANB.NS", "IN", "Allahabad Bank merged into Indian Bank (INDIANB)"),
    "ANDHRABANK": ("UNIONBANK.NS", "IN", "Andhra Bank merged into Union Bank of India (UNIONBANK)"),
    "CORPBANK": ("UNIONBANK.NS", "IN", "Corporation Bank merged into Union Bank of India (UNIONBANK)"),
    "SYNDIBANK": ("CANBK.NS", "IN", "Syndicate Bank merged into Canara Bank (CANBK)"),
    "ORIENTBANK": ("PNB.NS", "IN", "Oriental Bank of Commerce merged into Punjab National Bank (PNB)"),
    "UNITEDBNK": ("PNB.NS", "IN", "United Bank of India merged into Punjab National Bank (PNB)"),
    "DENABANK": ("BANKBARODA.NS", "IN", "Dena Bank merged into Bank of Baroda (BANKBARODA)"),
    "VIJAYABANK": ("BANKBARODA.NS", "IN", "Vijaya Bank merged into Bank of Baroda (BANKBARODA)"),
    # --- Major Indian Corporate Demergers, Mergers & Renames ---
    "ZOMATO": ("ETERNAL.NS", "IN", "Zomato Ltd rebranded to Eternal Ltd (ETERNAL)"),
    "TATAMOTORS": ("TMPV.NS", "IN", "Tata Motors demerged into Tata Motors Passenger Vehicles (TMPV) & Commercial Vehicles (TMCV)"),
    "TATAMTRDVR": ("TMPV.NS", "IN", "Tata Motors DVR converted into Tata Motors ordinary shares (TMPV / TMCV)"),
    "TATAGLOBAL": ("TATACONSUM.NS", "IN", "Tata Global Beverages renamed to Tata Consumer Products (TATACONSUM)"),
    "TATACOFFEE": ("TATACONSUM.NS", "IN", "Tata Coffee merged into Tata Consumer Products (TATACONSUM)"),
    "TATAMETALI": ("TATASTEEL.NS", "IN", "Tata Metaliks merged into Tata Steel (TATASTEEL)"),
    "TATASPONGE": ("TATASTEEL.NS", "IN", "Tata Sponge / Tata Steel Long Products merged into Tata Steel (TATASTEEL)"),
    "TATASTLBSL": ("TATASTEEL.NS", "IN", "Tata Steel BSL merged into Tata Steel (TATASTEEL)"),
    "MINDTREE": ("LTIM.NS", "IN", "Mindtree merged into LTIMindtree (LTIM)"),
    "LTI": ("LTIM.NS", "IN", "Larsen & Toubro Infotech merged into LTIMindtree (LTIM)"),
    "CADILAHC": ("ZYDUSLIFE.NS", "IN", "Cadila Healthcare renamed to Zydus Lifesciences (ZYDUSLIFE)"),
    "MOTHERSUMI": ("MOTHERSON.NS", "IN", "Motherson Sumi Systems renamed to Samvardhana Motherson International (MOTHERSON)"),
    "PVR": ("PVRINOX.NS", "IN", "PVR merged with INOX Leisure to form PVR INOX (PVRINOX)"),
    "INOXLEISUR": ("PVRINOX.NS", "IN", "INOX Leisure merged with PVR to form PVR INOX (PVRINOX)"),
    "ADANIGAS": ("ATGL.NS", "IN", "Adani Gas renamed to Adani Total Gas (ATGL)"),
    "ADANITRANS": ("ADANIENSOL.NS", "IN", "Adani Transmission renamed to Adani Energy Solutions (ADANIENSOL)"),
    "AMARAJABAT": ("ARE&M.NS", "IN", "Amara Raja Batteries renamed to Amara Raja Energy & Mobility (ARE&M)"),
    "GMRINFRA": ("GMRAIRPORT.NS", "IN", "GMR Infrastructure renamed to GMR Airports (GMRAIRPORT)"),
    "MCDOWELL-N": ("UNITDSPR.NS", "IN", "United Spirits ticker updated from MCDOWELL-N to UNITDSPR"),
    "CENTURYTEX": ("ABREL.NS", "IN", "Century Textiles renamed to Aditya Birla Real Estate (ABREL)"),
    "MINDAIND": ("UNOMINDA.NS", "IN", "Minda Industries renamed to Uno Minda (UNOMINDA)"),
    "RUCHISOYA": ("PATANJALI.NS", "IN", "Ruchi Soya Industries renamed to Patanjali Foods (PATANJALI)"),
    "NIITTECH": ("COFORGE.NS", "IN", "NIIT Technologies renamed to Coforge (COFORGE)"),
    "WELSPUNIND": ("WELSPUNLIV.NS", "IN", "Welspun India renamed to Welspun Living (WELSPUNLIV)"),
    "WABCOINDIA": ("ZFCVINDIA.NS", "IN", "WABCO India renamed to ZF Commercial Vehicle Control Systems India (ZFCVINDIA)"),
    "GUJFLUORO": ("FLUOROCHEM.NS", "IN", "Gujarat Fluorochemicals listed under FLUOROCHEM"),
    "KPIT": ("KPITTECH.NS", "IN", "KPIT Technologies listed under KPITTECH"),
    "HEXAWARE": ("HEXT.NS", "IN", "Hexaware Technologies listed under HEXT"),
    "AEGISCHEM": ("AEGISLOG.NS", "IN", "Aegis Logistics ticker updated from AEGISCHEM to AEGISLOG"),
    "GDL": ("GATEWAY.NS", "IN", "Gateway Distriparks ticker updated from GDL to GATEWAY"),
    "DAAWAT": ("LTFOODS.NS", "IN", "LT Foods ticker updated from DAAWAT to LTFOODS"),
    "STRTECH": ("STLTECH.NS", "IN", "Sterlite Technologies ticker updated from STRTECH to STLTECH"),
    "SUBEX": ("SUBEXLTD.NS", "IN", "Subex ticker updated from SUBEX to SUBEXLTD"),
    "SUNCLAYLTD": ("SUNCLAY.NS", "IN", "Sundaram Clayton ticker updated from SUNCLAYLTD to SUNCLAY"),
    "SUPPETRO": ("SPLPETRO.NS", "IN", "Supreme Petrochem ticker updated from SUPPETRO to SPLPETRO"),
    "SPENCER": ("SPENCERS.NS", "IN", "Spencer's Retail ticker updated from SPENCER to SPENCERS"),
    "MSTC": ("MSTCLTD.NS", "IN", "MSTC ticker updated from MSTC to MSTCLTD"),
    "MAXINDIA": ("MAXIND.NS", "IN", "Max India ticker updated from MAXINDIA to MAXIND"),
    "ALOKTEXT": ("ALOKINDS.NS", "IN", "Alok Industries ticker updated from ALOKTEXT to ALOKINDS"),
    "3IINFOTECH": ("3IINFOLTD.NS", "IN", "3i Infotech ticker updated from 3IINFOTECH to 3IINFOLTD"),
    "ADORWELD": ("ADOR.NS", "IN", "Ador Welding ticker updated from ADORWELD to ADOR"),
    "BAJAJCORP": ("BAJAJCON.NS", "IN", "Bajaj Corp renamed to Bajaj Consumer Care (BAJAJCON)"),
    "SHRIRAMEPC": ("SEPC.NS", "IN", "Shriram EPC renamed to SEPC (SEPC)"),
    "CAMSLTD": ("CAMS.NS", "IN", "Computer Age Management Services trades on NSE under CAMS"),
    "BRAINBEES": ("FIRSTCRY.NS", "IN", "Brainbees Solutions (FirstCry) trades on NSE under FIRSTCRY"),
    "NSE": ("NSE.BO", "IN", "National Stock Exchange of India is listed on BSE under NSE.BO (SEBI prohibits self-listing)"),
    # --- Corrupted legacy symbol artifacts ---
    "3M(INDIA)": ("3MINDIA.NS", "IN", "Normalized corrupted ticker symbol to 3MINDIA"),
    "ABBOT(INDIA)": ("ABBOTINDIA.NS", "IN", "Normalized corrupted ticker symbol to ABBOTINDIA"),
    "AKZO(INDIA)": ("AKZOINDIA.NS", "IN", "Normalized corrupted ticker symbol to AKZOINDIA"),
    "BATA(INDIA)": ("BATAINDIA.NS", "IN", "Normalized corrupted ticker symbol to BATAINDIA"),
    "COAL(INDIA)": ("COALINDIA.NS", "IN", "Normalized corrupted ticker symbol to COALINDIA"),
    "DLINK(INDIA)": ("DLINKINDIA.NS", "IN", "Normalized corrupted ticker symbol to DLINKINDIA"),
    "ESAB(INDIA)": ("ESABINDIA.NS", "IN", "Normalized corrupted ticker symbol to ESABINDIA"),
    "JTEKT(INDIA)": ("JTEKTINDIA.NS", "IN", "Normalized corrupted ticker symbol to JTEKTINDIA"),
    "LINDE(INDIA)": ("LINDEINDIA.NS", "IN", "Normalized corrupted ticker symbol to LINDEINDIA"),
    "MAX(INDIA)": ("MAXIND.NS", "IN", "Normalized corrupted ticker symbol to MAXIND"),
    "NLC(INDIA)": ("NLCINDIA.NS", "IN", "Normalized corrupted ticker symbol to NLCINDIA"),
    "SKF(INDIA)": ("SKFINDIA.NS", "IN", "Normalized corrupted ticker symbol to SKFINDIA"),
    "STC(INDIA)": ("STCINDIA.NS", "IN", "Normalized corrupted ticker symbol to STCINDIA"),
    "TI(INDIA)": ("TIINDIA.NS", "IN", "Normalized corrupted ticker symbol to TIINDIA"),
    "VINYL(INDIA)": ("VINYLINDIA.NS", "IN", "Normalized corrupted ticker symbol to VINYLINDIA"),
    "WABCO(INDIA)": ("ZFCVINDIA.NS", "IN", "Normalized corrupted ticker symbol to ZFCVINDIA"),
    "XPRO(INDIA)": ("XPROINDIA.NS", "IN", "Normalized corrupted ticker symbol to XPROINDIA"),
    "SMCGLOBAL*": ("SMCGLOBAL.NS", "IN", "Normalized corrupted ticker symbol to SMCGLOBAL"),
    # --- US Corporate Ticker Renames ---
    "SQ": ("XYZ", "US", "Block Inc. (formerly Square) updated its ticker from SQ to XYZ"),
    "MMC": ("MRSH", "US", "Marsh & McLennan Companies updated its ticker from MMC to MRSH"),
    "FI": ("FISV", "US", "Fiserv Inc. updated its ticker from FI to FISV"),
    "FB": ("META", "US", "Meta Platforms Inc. (formerly Facebook) updated its ticker from FB to META"),
}

# Search aliases & display enrichments for renamed / demerged / popular companies
# Maps active symbol (with .NS for IN, plain for US) -> {"display_suffix": ..., "aliases": ...}
ACTIVE_COMPANY_ENRICHMENTS: Dict[str, Dict[str, str]] = {
    "ETERNAL.NS": {
        "name_override": "Eternal Ltd (formerly Zomato)",
        "aliases": "ZOMATO Zomato Ltd Blinkit",
    },
    "TMPV.NS": {
        "name_override": "Tata Motors Passenger Vehicles Ltd (TMPV)",
        "aliases": "TATAMOTORS Tata Motors Ltd JLR Jaguar Land Rover",
    },
    "TMCV.NS": {
        "name_override": "Tata Motors Commercial Vehicles Ltd (TMCV)",
        "aliases": "TATAMOTORS Tata Motors Ltd",
    },
    "UJJIVANSFB.NS": {
        "name_override": "Ujjivan Small Finance Bank Ltd",
        "aliases": "UJJIVAN Ujjivan Financial Services",
    },
    "EQUITASBNK.NS": {
        "name_override": "Equitas Small Finance Bank Ltd",
        "aliases": "EQUITAS Equitas Holdings",
    },
    "IDFCFIRSTB.NS": {
        "name_override": "IDFC First Bank Ltd",
        "aliases": "IDFC IDFCBANK IDFC Ltd",
    },
    "HDFCBANK.NS": {
        "name_override": "HDFC Bank Ltd",
        "aliases": "HDFC Housing Development Finance Corporation",
    },
    "LTIM.NS": {
        "name_override": "LTIMindtree Ltd",
        "aliases": "LTI MINDTREE Larsen & Toubro Infotech",
    },
    "ZYDUSLIFE.NS": {
        "name_override": "Zydus Lifesciences Ltd (formerly Cadila)",
        "aliases": "CADILAHC Cadila Healthcare",
    },
    "TATACONSUM.NS": {
        "name_override": "Tata Consumer Products Ltd",
        "aliases": "TATAGLOBAL TATACOFFEE Tata Global Beverages Tata Coffee",
    },
    "MOTHERSON.NS": {
        "name_override": "Samvardhana Motherson International Ltd",
        "aliases": "MOTHERSUMI Motherson Sumi Systems",
    },
    "SHRIRAMFIN.NS": {
        "name_override": "Shriram Finance Ltd",
        "aliases": "SRTRANSFIN SHRIRAMCIT Shriram Transport Finance",
    },
    "PVRINOX.NS": {
        "name_override": "PVR INOX Ltd",
        "aliases": "PVR INOXLEISUR PVR Cinemas INOX",
    },
    "ATGL.NS": {
        "name_override": "Adani Total Gas Ltd",
        "aliases": "ADANIGAS Adani Gas",
    },
    "ADANIENSOL.NS": {
        "name_override": "Adani Energy Solutions Ltd",
        "aliases": "ADANITRANS Adani Transmission",
    },
    "ARE&M.NS": {
        "name_override": "Amara Raja Energy & Mobility Ltd",
        "aliases": "AMARAJABAT Amara Raja Batteries",
    },
    "GMRAIRPORT.NS": {
        "name_override": "GMR Airports Ltd",
        "aliases": "GMRINFRA GMR Infrastructure",
    },
    "UNITDSPR.NS": {
        "name_override": "United Spirits Ltd (Diageo India)",
        "aliases": "MCDOWELL-N McDowell",
    },
    "SAMMAANCAP.NS": {
        "name_override": "Sammaan Capital Ltd (formerly Indiabulls Housing)",
        "aliases": "IBULHSGFIN Indiabulls Housing Finance",
    },
    "ABREL.NS": {
        "name_override": "Aditya Birla Real Estate Ltd (formerly Century Textiles)",
        "aliases": "CENTURYTEX Century Textiles",
    },
    "UNOMINDA.NS": {
        "name_override": "Uno Minda Ltd",
        "aliases": "MINDAIND Minda Industries",
    },
    "PATANJALI.NS": {
        "name_override": "Patanjali Foods Ltd (formerly Ruchi Soya)",
        "aliases": "RUCHISOYA Ruchi Soya",
    },
    "COFORGE.NS": {
        "name_override": "Coforge Ltd (formerly NIIT Tech)",
        "aliases": "NIITTECH NIIT Technologies",
    },
    "FIRSTCRY.NS": {
        "name_override": "Brainbees Solutions Ltd (FirstCry)",
        "aliases": "BRAINBEES FirstCry",
    },
    "NYKAA.NS": {
        "name_override": "FSN E-Commerce Ventures Ltd (Nykaa)",
        "aliases": "FSN Nykaa",
    },
    "PAYTM.NS": {
        "name_override": "One 97 Communications Ltd (Paytm)",
        "aliases": "ONE97 Paytm",
    },
    "POLICYBZR.NS": {
        "name_override": "PB Fintech Ltd (Policybazaar)",
        "aliases": "PBFINTECH Policybazaar",
    },
    "MEDANTA.NS": {
        "name_override": "Global Health Ltd (Medanta)",
        "aliases": "GLOBALHEALTH Medanta Hospital",
    },
    "HAL.NS": {
        "name_override": "Hindustan Aeronautics Ltd (HAL)",
        "aliases": "HAL Hindustan Aeronautics",
    },
    "XYZ": {
        "name_override": "Block Inc. (formerly Square)",
        "aliases": "SQ Square Cash App",
    },
    "MRSH": {
        "name_override": "Marsh & McLennan Companies Inc.",
        "aliases": "MMC Marsh McLennan",
    },
    "FISV": {
        "name_override": "Fiserv Inc.",
        "aliases": "FI Fiserv",
    },
    "META": {
        "name_override": "Meta Platforms Inc. (Facebook)",
        "aliases": "FB Facebook Instagram WhatsApp",
    },
    "GOOGL": {
        "name_override": "Alphabet Inc. Class A (Google)",
        "aliases": "Google YouTube",
    },
    "GOOG": {
        "name_override": "Alphabet Inc. Class C (Google)",
        "aliases": "Google YouTube",
    },
    "NSE.BO": {
        "name_override": "National Stock Exchange of India Ltd",
        "aliases": "NSE National Stock Exchange",
    },
}


# ---------------------------------------------------------------------------
# 2. Non-DCF Instrument Classifier (ETFs, Commodity ETFs, MFs, REITs, InvITs)
# ---------------------------------------------------------------------------
KNOWN_NON_DCF_SYMBOLS = {
    # Indian Commodity & Index ETFs
    "GOLDBEES", "SILVERBEES", "NIFTYBEES", "BANKBEES", "JUNIORBEES", "PSUBNKBEES",
    "SHARIABEES", "HNGSNGBEES", "INFRABEES", "LIQUIDBEES", "PHARMABEES", "ITBEES",
    "CONSUMBEES", "AUTOBEES", "MID150BEES", "MON100", "M50", "M100", "N100", "MONQ50",
    "MAFANG", "CPSEETF", "ICICIB22", "SILVER", "ICICIGOLD", "ICICISILVE", "HDFCMFGETF",
    "KOTAKGOLD", "AXISGOLD", "QGOLDHALF", "SBIGETS", "GOLDSHARE", "IVZINGOLD",
    "IDBIGOLD", "BSLGOLDETF", "SETFGOLD", "SETFNIF50", "SETFNIFBK", "SETFBSE100",
    "SETFSN50", "NIFTYEES", "QNIFTY", "KTKSENSEX", "ICICISENSX", "ICICINIFTY",
    # Indian REITs & InvITs
    "EMBASSY", "MINDSPACE", "BIRET", "NEXUSSELECT", "NXST", "INDIGRID", "IRBINVIT",
    "PGINVIT", "INDINFR", "INFRATRUST", "NHIT", "TOWERINFRA",
    # US ETFs, Commodity Trusts & Equity REITs
    "SPY", "IVV", "VOO", "QQQ", "QQQM", "DIA", "IWM", "VTI", "VEA", "VWO", "EFA",
    "EEM", "GLD", "IAU", "SLV", "USO", "UNG", "DBC", "PDBC", "IBIT", "FBTC", "GBTC",
    "ETHE", "ARKK", "ARKW", "ARKG", "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP",
    "XLU", "XLB", "XLRE", "XLC", "SMH", "SOXX", "SOXL", "TQQQ", "SQQQ", "TLT", "HYG",
    "LQD", "BND", "AGG", "SCHD", "VIG", "VYM", "JEPI", "JEPQ",
    # Major US REITs & MLPs in SEC top list
    "PLD", "AMT", "EQIX", "WELL", "SPG", "DLR", "O", "PSA", "CCI", "VICI", "EXR",
    "AVB", "EQR", "IRM", "SBAC", "WY", "ARE", "INVH", "MAA", "ESS", "VTR",
    "EPD", "ET", "MPLX", "CQP",
}

_ETF_MF_NAME_REGEX = re.compile(
    r"(\bETF\b|\bETFS\b|\bBEES\b|EXCHANGE\s+TRADED\s+FUND|EXCHANGE\s+TRADED\s+SCHEME|"
    r"MUTUAL\s+FUND|INDEX\s+FUND|GOLD\s+FUND|GOLD\s+TRUST|SILVER\s+TRUST|BITCOIN\s+TRUST|"
    r"ETHER\s+TRUST|OIL\s+FUND|COMMODITY\s+TRUST|SEGREGATED\s+PORTFOLIO|CLOSE\s+ENDED|"
    r"DIRECT\s+PLAN|REGULAR\s+PLAN|DIVIDEND\s+PAYOUT|CUMULATIVE\s+OPTION|GROWTH\s+OPTION|"
    r"\bSPDR\b|\bISHARES\b|\bVANGUARD\b|\bPROSHARES\b|\bDIREXION\b|\bWISDOMTREE\b|"
    r"\bVANECK\b|\bGLOBAL\s+X\b|S&P\s+500\s+ETF|NIFTY\s+50\s+ETF|NIFTY\s+ETF|"
    r"SENSEX\s+ETF|BHARAT\s+22|BHARAT\s+BOND)",
    re.IGNORECASE,
)

_REIT_INVIT_NAME_REGEX = re.compile(
    r"(\bREIT\b|\bINVIT\b|REAL\s+ESTATE\s+INVESTMENT\s+TRUST|REAL\s+ESTATE\s+TRUST|"
    r"INFRASTRUCTURE\s+INVESTMENT\s+TRUST|INFRASTRUCTURE\s+TRUST|INFRA\s+TRUST|"
    r"GRID\s+TRUST|INDINFRAVIT|DIGITAL\s+REALTY\s+TRUST|REALTY\s+INCOME\s+CORP|"
    r"VICI\s+PROPERTIES)",
    re.IGNORECASE,
)


def is_non_dcf_instrument(
    symbol: Optional[str] = None,
    name: Optional[str] = None,
    quote_type: Optional[str] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """Check whether a security is an ETF, Commodity Trust, Mutual Fund, REIT, or InvIT.

    Returns:
        (is_excluded, category, user_message)
    """
    sym_raw = (symbol or "").strip().upper()
    sym_clean = re.sub(r"\.(NS|BO)$", "", sym_raw)
    name_clean = html.unescape(name or "").strip()
    qt = (quote_type or "").strip().upper()
    sec = (sector or "").strip().lower()
    ind = (industry or "").strip().lower()

    # 1. Explicit non-equity quoteType from Yahoo Finance
    if qt in ("ETF", "MUTUALFUND", "INDEX", "CRYPTOCURRENCY", "CURRENCY", "FUTURE", "OPTION", "MONEYMARKET"):
        label = {
            "ETF": "an Exchange-Traded Fund (ETF) / Commodity Trust",
            "MUTUALFUND": "a Mutual Fund scheme",
            "INDEX": "a Market Index",
            "CRYPTOCURRENCY": "a Cryptocurrency asset",
            "CURRENCY": "a Foreign Exchange pair",
            "FUTURE": "a Commodity / Derivatives Futures contract",
            "OPTION": "an Options contract",
        }.get(qt, f"a non-corporate instrument ({qt})")
        return (
            True,
            qt,
            f"'{sym_clean}' is {label}. Discounted Cash Flow (DCF) valuation applies only to operating companies that generate business cash flows, not pooled funds, indices, or commodities valued by Net Asset Value (NAV).",
        )

    # 2. NSE REIT / InvIT series suffixes (-RR, -IV) or REIT industry metadata
    if sym_raw.endswith("-RR.NS") or sym_raw.endswith("-IV.NS") or "reit" in ind or _REIT_INVIT_NAME_REGEX.search(name_clean):
        return (
            True,
            "REIT_INVIT",
            f"'{sym_clean}' ({name_clean or sym_clean}) is a REIT / InvIT (Real Estate or Infrastructure Investment Trust). Pass-through trusts distribute mandated cash flows (NDCF) and are valued using Distribution Yield & Net Asset Value (NAV) rather than standard corporate FCFF DCF.",
        )

    # 3. Known ETF / MF / Segregated Portfolio symbol patterns
    if (
        sym_clean in KNOWN_NON_DCF_SYMBOLS
        or (sym_clean.endswith("BEES") and sym_clean != "BRAINBEES")
        or sym_clean.endswith("ETF")
        or re.match(r"^(08|11)[A-Z]{3}$", sym_clean)
        or sym_clean.startswith(("NIEHSP", "NIESSP", "IPRU", "ABSLRIF", "KTKIND", "HEOF", "HHOF", "IDFCEOS"))
        or _ETF_MF_NAME_REGEX.search(name_clean)
    ):
        if sym_clean in ("EMBASSY", "MINDSPACE", "BIRET", "NEXUSSELECT", "NXST", "INDIGRID", "IRBINVIT", "PGINVIT", "INDINFR", "INFRATRUST", "NHIT", "TOWERINFRA") or sym_clean in ("PLD", "AMT", "EQIX", "WELL", "SPG", "DLR", "O", "PSA", "CCI", "VICI"):
            return (
                True,
                "REIT_INVIT",
                f"'{sym_clean}' is a REIT / InvIT trust vehicle. Standard corporate DCF does not apply to pass-through property/infrastructure trusts valued by NAV and distribution yield.",
            )
        return (
            True,
            "ETF_MF",
            f"'{sym_clean}' ({name_clean or sym_clean}) is an Exchange-Traded Fund (ETF), Commodity Fund, or Mutual Fund scheme. DCF valuation requires corporate operating revenues, EBIT, and reinvestment cash flows, and cannot be applied to ETFs or commodities.",
        )

    return (False, "", "")


# ---------------------------------------------------------------------------
# 3. Capital-Light Financial Infrastructure Classifier (Exchanges, AMCs, RTAs)
# ---------------------------------------------------------------------------
# Fee-based market infrastructure & asset-light financial platforms should be
# valued via Standard Operating Cash Flow (FCFF) DCF, NOT Commercial Bank
# Tier-1 Regulatory Capital / Price-to-Book (P/B) DDM.
CAPITAL_LIGHT_FINANCIAL_INFRA = {
    # Indian Exchanges, Depositories, RTAs, Rating Agencies, AMCs & Tech Brokers
    "MCX", "BSE", "IEX", "CDSL", "CAMS", "CAMSLTD", "KFINTECH",
    "CRISIL", "ICRA", "CAREERP", "HDFCAMC", "NAM-INDIA", "UTIAMC", "ABSLAMC",
    "ANGELONE", "ISEC", "MOTILALOFS", "ANANDRATHI", "PRUDENT", "NUVAMA", "360ONE",
    "POLICYBZR", "PAYTM",
    # US Exchanges, Rating Agencies, Financial Data & Asset-Light Platforms
    "NDAQ", "ICE", "CME", "CBOE", "SPGI", "MCO", "MSCI", "FDS", "V", "MA",
    "PYPL", "XYZ", "SQ", "COIN", "HOOD", "BLK", "TROW", "BEN", "IVZ",
}


def is_capital_light_financial(
    symbol: Optional[str] = None,
    name: Optional[str] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
) -> bool:
    """Return True if the company is a fee-based exchange, depository, RTA, rating agency, AMC, or fintech platform."""
    sym_clean = re.sub(r"\.(NS|BO)$", "", (symbol or "").strip().upper())
    if sym_clean in CAPITAL_LIGHT_FINANCIAL_INFRA:
        return True

    ind_l = (industry or "").strip().lower()
    name_l = (name or "").strip().lower()

    if any(k in ind_l for k in ["financial data & stock exchanges", "stock exchanges", "asset management"]):
        return True
    if any(k in name_l for k in ["commodity exchange", "stock exchange", "energy exchange", "depository services", "asset management", "computer age management"]):
        return True
    return False


# ---------------------------------------------------------------------------
# 4. Name Formatting & Live Universe State
# ---------------------------------------------------------------------------
_UNIVERSE_LOCK = threading.Lock()
_LIVE_UNIVERSE: List[Dict[str, Any]] = []
_LIVE_UNIVERSE_VERSION: str = "init"
_LAST_SYNC_TS: float = 0.0
_SYNC_INTERVAL_SECONDS: int = 43200  # 12 hours
_DYNAMIC_REDIRECTS: Dict[str, Tuple[str, str, str]] = {}


def lookup_company_name(ticker: str) -> Optional[str]:
    """Look up the canonical company name for a ticker from enrichments, live universe, or baseline stocks.json."""
    if not ticker:
        return None
    sym_upper = ticker.strip().upper()
    sym_clean = re.sub(r"\.(NS|BO)$", "", sym_upper)

    # 1. Check explicit enrichments
    for key in (sym_upper, f"{sym_clean}.NS", sym_clean):
        enr = ACTIVE_COMPANY_ENRICHMENTS.get(key)
        if enr and enr.get("name_override"):
            return enr["name_override"]

    # 2. Check in-memory universe (or load baseline if not yet initialized)
    global _LIVE_UNIVERSE, _LIVE_UNIVERSE_VERSION
    with _UNIVERSE_LOCK:
        if not _LIVE_UNIVERSE:
            baseline = load_baseline_universe()
            _LIVE_UNIVERSE = baseline
            _LIVE_UNIVERSE_VERSION = _compute_version(baseline)
        universe_snapshot = list(_LIVE_UNIVERSE)

    for item in universe_snapshot:
        item_sym = str(item.get("s", "")).strip().upper()
        item_clean = re.sub(r"\.(NS|BO)$", "", item_sym)
        if item_sym == sym_upper or item_clean == sym_clean:
            name = item.get("n")
            if name and name.upper() != item_sym:
                return str(name)
    return None


def clean_company_name(raw_name: str) -> str:
    """Clean HTML entities, mojibake, and awkward NSE formatting from company names."""
    if not raw_name:
        return ""
    text = html.unescape(str(raw_name))
    text = text.replace("Â€“", "-").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()

    # If Yahoo Finance returned a raw ticker like "JMFINANCIL.NS" instead of a name, resolve via universe
    if re.match(r"^[A-Z0-9&\-]+\.(NS|BO)$", text, flags=re.IGNORECASE):
        resolved = lookup_company_name(text)
        if resolved:
            return resolved
        return re.sub(r"\.(NS|BO)$", "", text, flags=re.IGNORECASE).upper()

    # Fix "(India)" -> "India" when preceded by words
    text = re.sub(r"\(India\)", "India", text, flags=re.IGNORECASE)

    # Expand truncated exchange suffixes like " L" or " L." to " Ltd" so names are never cut off
    text = re.sub(r"\bL\.?$", "Ltd", text, flags=re.IGNORECASE)

    # Convert ALL-CAPS names from NSE/SEC into clean Title Case while preserving acronyms
    if text.isupper() or text.islower():
        words = text.split(" ")
        acronyms = {
            "LIMITED": "Ltd", "LTD": "Ltd", "LTD.": "Ltd", "INC": "Inc.", "INC.": "Inc.",
            "CORP": "Corp.", "CORP.": "Corp.", "PLC": "plc", "LLC": "LLC", "LLP": "LLP",
            "NV": "N.V.", "SA": "S.A.", "SE": "SE", "AG": "AG",
            "HDFC": "HDFC", "ICICI": "ICICI", "SBI": "SBI", "IDBI": "IDBI", "IDFC": "IDFC",
            "LIC": "LIC", "PNB": "PNB", "UCO": "UCO", "IOB": "IOB", "CSB": "CSB",
            "DCB": "DCB", "RBL": "RBL", "AU": "AU", "KVB": "KVB", "TMB": "TMB",
            "NTPC": "NTPC", "NHPC": "NHPC", "ONGC": "ONGC", "GAIL": "GAIL", "BPCL": "BPCL",
            "HPCL": "HPCL", "IOC": "IOC", "BHEL": "BHEL", "BEL": "BEL", "BEML": "BEML",
            "HAL": "HAL", "SAIL": "SAIL", "NMDC": "NMDC", "MOIL": "MOIL", "NALCO": "NALCO",
            "NLC": "NLC", "SJVN": "SJVN", "IRCTC": "IRCTC", "IRCON": "IRCON", "IRFC": "IRFC",
            "RVNL": "RVNL", "RITES": "RITES", "PFC": "PFC", "REC": "REC", "IREDA": "IREDA",
            "HUDCO": "HUDCO", "NBCC": "NBCC", "ITDC": "ITDC", "MMTC": "MMTC", "STC": "STC",
            "SCI": "SCI", "CONCOR": "CONCOR", "GIC": "GIC", "NIACL": "NIACL",
            "TCS": "TCS", "HCL": "HCL", "L&T": "L&T", "LT": "L&T", "LTIM": "LTIM",
            "KPIT": "KPIT", "NIIT": "NIIT", "CMS": "CMS", "SIS": "SIS", "PVR": "PVR",
            "INOX": "INOX", "TVS": "TVS", "MRF": "MRF", "CEAT": "CEAT", "JK": "JK",
            "KPR": "KPR", "CCL": "CCL", "EID": "EID", "DCM": "DCM", "SRF": "SRF",
            "GHCL": "GHCL", "HEG": "HEG", "KEI": "KEI", "KEC": "KEC", "NCC": "NCC",
            "IRB": "IRB", "GMR": "GMR", "GVK": "GVK", "DLF": "DLF", "PVRINOX": "PVR INOX",
            "MCX": "MCX", "BSE": "BSE", "CDSL": "CDSL", "CAMS": "CAMS", "CRISIL": "CRISIL",
            "ICRA": "ICRA", "CARE": "CARE", "IEX": "IEX", "CESC": "CESC", "RPG": "RPG",
            "JSW": "JSW", "APL": "APL", "vst": "VST", "VST": "VST", "ITC": "ITC",
            "3M": "3M", "SKF": "SKF", "ABB": "ABB", "TDK": "TDK", "BASF": "BASF",
            "ESAB": "ESAB", "LG": "LG", "HP": "HP", "IBM": "IBM", "AMD": "AMD",
            "NVIDIA": "NVIDIA", "ASML": "ASML", "SAP": "SAP", "TSMC": "TSMC",
            "S&P": "S&P", "US": "US", "USA": "USA", "UK": "UK", "II": "II", "III": "III",
        }
        cleaned_words = []
        for w in words:
            w_up = w.upper().strip(",.")
            if w.upper() in acronyms:
                cleaned_words.append(acronyms[w.upper()])
            elif w_up in acronyms and w.endswith((",", ".")):
                cleaned_words.append(acronyms[w_up])
            else:
                cleaned_words.append(w.capitalize())
        text = " ".join(cleaned_words)

    # Standardize trailing "Limited" -> "Ltd" for compactness
    text = re.sub(r"\bLimited\.?$", "Ltd", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+/NEW$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _normalize_company_stem(name: str) -> str:
    """Create a canonical alphanumeric stem of a company name (stripping only legal entity suffixes)."""
    s = html.unescape(name or "").lower()
    s = re.sub(r"\(formerly.*?\)", "", s)
    s = re.sub(
        r"\b(ltd|limited|inc|incorporated|plc|llc|llp|nv|sa|se|ag|pvt|private|the|of|and)\b",
        " ",
        s,
    )
    return re.sub(r"[^a-z0-9]", "", s)


def _compute_version(universe: List[Dict[str, Any]]) -> str:
    raw = json.dumps([(x.get("s"), x.get("n"), x.get("a", "")) for x in universe], sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


# Curated Indian equities listed exclusively on BSE (such as NSE, which cannot list on itself due to SEBI rules)
CURATED_BSE_EQUITIES: List[Dict[str, Any]] = [
    {
        "s": "NSE.BO",
        "n": "National Stock Exchange of India Ltd",
        "m": "IN",
        "id": "INE721I01024",
        "a": "NSE National Stock Exchange",
    }
]


def load_baseline_universe(path: str = _DEFAULT_STOCKS_JSON_PATH) -> List[Dict[str, Any]]:
    """Load the local baseline `stocks.json` file."""
    data = []
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    data = loaded
    except Exception as exc:
        logger.warning("Failed to load baseline stocks.json: %s", exc)

    # Ensure curated BSE-exclusive equities (like NSE.BO) are always present
    existing_syms = {str(x.get("s", "")).upper() for x in data}
    for item in CURATED_BSE_EQUITIES:
        if item["s"].upper() not in existing_syms:
            data.append(item)
    return data


def fetch_live_nse_equities(timeout: int = 12) -> List[Dict[str, Any]]:
    """Fetch official active NSE Mainboard equities (`SERIES in ['EQ', 'BE']`) from NSE Archives."""
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/csv,text/plain,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = [c.strip().upper() for c in df.columns]

    # Keep only active EQ (rolling) and BE (trade-for-trade) equity series.
    # Exclude BZ (suspended/non-compliant Z-group shells).
    if "SERIES" in df.columns:
        df = df[df["SERIES"].astype(str).str.strip().str.upper().isin(["EQ", "BE"])]

    results: List[Dict[str, Any]] = []
    seen_syms = set()

    for _, row in df.iterrows():
        raw_sym = str(row.get("SYMBOL", "")).strip().upper()
        raw_name = str(row.get("NAME OF COMPANY", "")).strip()
        isin = str(row.get("ISIN NUMBER", "")).strip().upper()

        if not raw_sym or raw_sym in seen_syms:
            continue
        # Reject any symbol with invalid characters
        if re.search(r"[^A-Z0-9&\-]", raw_sym):
            continue

        full_sym = f"{raw_sym}.NS"
        excluded, _, _ = is_non_dcf_instrument(symbol=full_sym, name=raw_name, quote_type="EQUITY")
        if excluded:
            continue

        clean_name = clean_company_name(raw_name)
        enrichment = ACTIVE_COMPANY_ENRICHMENTS.get(full_sym, {})
        if enrichment.get("name_override"):
            clean_name = enrichment["name_override"]

        entry: Dict[str, Any] = {
            "s": full_sym,
            "n": clean_name,
            "m": "IN",
        }
        if isin and isin.startswith("INE"):
            entry["id"] = isin
        if enrichment.get("aliases"):
            entry["a"] = enrichment["aliases"]

        results.append(entry)
        seen_syms.add(raw_sym)

    return results


def fetch_live_us_equities(baseline_us: List[Dict[str, Any]], max_sec_rank: int = 550, timeout: int = 12) -> List[Dict[str, Any]]:
    """Fetch official SEC EDGAR active US equities and merge with verified baseline US stocks."""
    url = "https://www.sec.gov/files/company_tickers.json"
    headers = {"User-Agent": "ValuationLab/1.0 (contact@valuationlab.app)"}
    sec_data = requests.get(url, headers=headers, timeout=timeout).json()

    # Map all live SEC tickers and CIKs
    sec_by_ticker: Dict[str, Dict[str, Any]] = {}
    sec_by_cik: Dict[str, Dict[str, Any]] = {}
    sec_items = list(sec_data.values())

    for idx, item in enumerate(sec_items):
        t = str(item.get("ticker", "")).strip().upper()
        cik = str(item.get("cik_str", "")).strip()
        title = str(item.get("title", "")).strip()
        if not t:
            continue
        rec = {"ticker": t, "cik": cik, "title": title, "rank": idx}
        if t not in sec_by_ticker:
            sec_by_ticker[t] = rec
        if cik and cik not in sec_by_cik:
            sec_by_cik[cik] = rec

    results: List[Dict[str, Any]] = []
    seen_us = set()

    # 1. Process baseline US stocks (auto-healing any renamed symbols via CIK or LEGACY_TICKER_REDIRECTS)
    for b_item in baseline_us:
        sym = str(b_item.get("s", "")).strip().upper()
        name = str(b_item.get("n", "")).strip()
        cik = str(b_item.get("id", "")).strip()

        # Check curated redirects first (e.g. SQ -> XYZ, MMC -> MRSH, FI -> FISV)
        if sym in LEGACY_TICKER_REDIRECTS:
            new_sym, _, _ = LEGACY_TICKER_REDIRECTS[sym]
            sym = new_sym

        # Check if CIK now points to a new primary ticker in SEC EDGAR
        if cik and cik in sec_by_cik and sym not in sec_by_ticker:
            new_sec_sym = sec_by_cik[cik]["ticker"]
            if new_sec_sym != sym:
                _DYNAMIC_REDIRECTS[sym] = (
                    new_sec_sym,
                    "US",
                    f"{name} updated its SEC ticker from {sym} to {new_sec_sym}",
                )
                sym = new_sec_sym

        if sym in seen_us:
            continue

        excluded, _, _ = is_non_dcf_instrument(symbol=sym, name=name, quote_type="EQUITY")
        if excluded:
            continue

        sec_rec = sec_by_ticker.get(sym)
        resolved_cik = sec_rec["cik"] if sec_rec else cik
        clean_name = clean_company_name(name or (sec_rec["title"] if sec_rec else sym))

        enrichment = ACTIVE_COMPANY_ENRICHMENTS.get(sym, {})
        if enrichment.get("name_override"):
            clean_name = enrichment["name_override"]

        entry: Dict[str, Any] = {"s": sym, "n": clean_name, "m": "US"}
        if resolved_cik:
            entry["id"] = resolved_cik
        if enrichment.get("aliases"):
            entry["a"] = enrichment["aliases"]
        elif b_item.get("a"):
            entry["a"] = b_item["a"]

        results.append(entry)
        seen_us.add(sym)

    # 2. Add top SEC operating companies by market cap rank (excluding share classes/warrants/ETFs/REITs)
    for item in sec_items[:max_sec_rank]:
        sym = str(item.get("ticker", "")).strip().upper()
        title = str(item.get("title", "")).strip()
        cik = str(item.get("cik_str", "")).strip()

        if not sym or sym in seen_us:
            continue
        # Skip preferreds/warrants/units with hyphens (except BRK-B / BRK-A)
        if "-" in sym and not sym.startswith("BRK-"):
            continue

        excluded, _, _ = is_non_dcf_instrument(symbol=sym, name=title, quote_type="EQUITY")
        if excluded:
            continue

        clean_name = clean_company_name(title)
        enrichment = ACTIVE_COMPANY_ENRICHMENTS.get(sym, {})
        if enrichment.get("name_override"):
            clean_name = enrichment["name_override"]

        entry = {"s": sym, "n": clean_name, "m": "US"}
        if cik:
            entry["id"] = cik
        if enrichment.get("aliases"):
            entry["a"] = enrichment["aliases"]

        results.append(entry)
        seen_us.add(sym)

    return results


def sync_live_universe(persist_to_disk: bool = False, stocks_path: str = _DEFAULT_STOCKS_JSON_PATH) -> List[Dict[str, Any]]:
    """Synchronize the ticker universe with live NSE & SEC master feeds and detect corporate actions."""
    global _LIVE_UNIVERSE, _LIVE_UNIVERSE_VERSION, _LAST_SYNC_TS

    baseline = load_baseline_universe(stocks_path)
    baseline_in = [x for x in baseline if x.get("m") == "IN"]
    baseline_us = [x for x in baseline if x.get("m") == "US"]

    # Build lookup maps from baseline for automatic corporate action diffing
    old_by_isin: Dict[str, Dict[str, Any]] = {}
    old_by_stem: Dict[str, Dict[str, Any]] = {}
    for item in baseline_in:
        isin = str(item.get("id", "")).strip().upper()
        if isin:
            old_by_isin[isin] = item
        stem = _normalize_company_stem(item.get("n", ""))
        if len(stem) >= 6:
            old_by_stem[stem] = item

    # 1. Fetch live NSE equities
    try:
        live_in = fetch_live_nse_equities()
        live_in_syms = {x["s"].replace(".NS", "").upper() for x in live_in}

        # Auto-detect ISIN or exact Company-Name symbol changes (Corporate Actions!)
        for new_item in live_in:
            new_sym_full = new_item["s"]
            new_sym_clean = new_sym_full.replace(".NS", "").upper()
            isin = new_item.get("id")
            stem = _normalize_company_stem(new_item.get("n", ""))

            matched_old = None
            if isin and isin in old_by_isin:
                matched_old = old_by_isin[isin]
            elif len(stem) >= 6 and stem in old_by_stem:
                candidate = old_by_stem[stem]
                cand_sym = candidate["s"].replace(".NS", "").replace(".BO", "").upper()
                # Only treat as a rename if the old symbol is no longer active on NSE
                if cand_sym not in live_in_syms:
                    matched_old = candidate

            if matched_old:
                old_sym_clean = matched_old["s"].replace(".NS", "").replace(".BO", "").upper()
                if (
                    old_sym_clean != new_sym_clean
                    and old_sym_clean not in LEGACY_TICKER_REDIRECTS
                    and re.match(r"^[A-Z0-9&\-]+$", old_sym_clean)
                ):
                    _DYNAMIC_REDIRECTS[old_sym_clean] = (
                        new_sym_full,
                        "IN",
                        f"{matched_old.get('n', old_sym_clean)} updated its NSE ticker from {old_sym_clean} to {new_sym_clean}",
                    )
                    existing_aliases = new_item.get("a", "")
                    if old_sym_clean not in existing_aliases.upper().split():
                        new_item["a"] = f"{existing_aliases} {old_sym_clean} {matched_old.get('n', '')}".strip()

        logger.info("Live NSE equity sync succeeded: %d active mainboard stocks (%d dynamic redirects).", len(live_in), len(_DYNAMIC_REDIRECTS))
    except Exception as exc:
        logger.warning("Live NSE sync failed, falling back to sanitized baseline: %s", exc)
        live_in = [
            x for x in baseline_in
            if not is_non_dcf_instrument(x.get("s"), x.get("n"), "EQUITY")[0]
            and not re.search(r"[^A-Z0-9&.\-]", str(x.get("s", "")).upper())
        ]

    # 2. Fetch live US equities
    try:
        live_us = fetch_live_us_equities(baseline_us)
        logger.info("Live SEC US equity sync succeeded: %d active US stocks.", len(live_us))
    except Exception as exc:
        logger.warning("Live SEC US sync failed, falling back to sanitized baseline: %s", exc)
        live_us = []
        for x in baseline_us:
            sym = str(x.get("s", "")).strip().upper()
            if sym in LEGACY_TICKER_REDIRECTS:
                sym = LEGACY_TICKER_REDIRECTS[sym][0]
            if not is_non_dcf_instrument(sym, x.get("n"), "EQUITY")[0]:
                live_us.append({"s": sym, "n": clean_company_name(x.get("n", sym)), "m": "US"})

    # Ensure curated BSE-exclusive equities (such as NSE.BO) are preserved
    existing_in_syms = {str(x.get("s", "")).upper() for x in live_in}
    for item in CURATED_BSE_EQUITIES:
        if item["s"].upper() not in existing_in_syms:
            live_in.append(item)

    combined = live_us + live_in
    version = _compute_version(combined)

    with _UNIVERSE_LOCK:
        _LIVE_UNIVERSE = combined
        _LIVE_UNIVERSE_VERSION = version
        _LAST_SYNC_TS = time.time()

    if persist_to_disk:
        try:
            with open(stocks_path, "w", encoding="utf-8") as f:
                json.dump(combined, f, ensure_ascii=False, separators=(",", ":"))
            logger.info("Persisted %d clean equities to %s", len(combined), stocks_path)
        except Exception as exc:
            logger.warning("Could not write updated universe to %s: %s", stocks_path, exc)

    return combined


def get_universe_payload() -> Dict[str, Any]:
    """Return the active in-memory ticker universe, initializing from baseline or live sync if needed."""
    global _LIVE_UNIVERSE, _LIVE_UNIVERSE_VERSION
    with _UNIVERSE_LOCK:
        if not _LIVE_UNIVERSE:
            baseline = load_baseline_universe()
            _LIVE_UNIVERSE = baseline
            _LIVE_UNIVERSE_VERSION = _compute_version(baseline)

        needs_refresh = (time.time() - _LAST_SYNC_TS) > _SYNC_INTERVAL_SECONDS
        payload = {
            "version": _LIVE_UNIVERSE_VERSION,
            "count": len(_LIVE_UNIVERSE),
            "stocks": _LIVE_UNIVERSE,
        }

    if needs_refresh:
        threading.Thread(target=sync_live_universe, daemon=True).start()

    return payload


def resolve_ticker(ticker: str, market: str = "auto") -> Tuple[str, str, Optional[str]]:
    """Resolve a potentially old, renamed, merged, or demerged ticker to its active symbol.

    Args:
        ticker: Raw ticker string entered by user (e.g. 'UJJIVAN', 'ZOMATO.NS', 'TATAMOTORS', 'SQ').
        market: 'US', 'IN', or 'auto'.

    Returns:
        (resolved_ticker, resolved_market, redirect_note)
    """
    raw = ticker.strip().upper()
    clean = re.sub(r"\.(NS|BO)$", "", raw)
    has_in_suffix = raw.endswith(".NS") or raw.endswith(".BO")

    # 1. Check Curated Redirects
    if clean in LEGACY_TICKER_REDIRECTS:
        target_sym, target_mkt, note = LEGACY_TICKER_REDIRECTS[clean]
        if market.upper() in ("AUTO", target_mkt) or has_in_suffix:
            return target_sym, target_mkt, note

    # 2. Check Dynamically Detected Corporate Action Redirects (from ISIN/CIK diffing)
    if clean in _DYNAMIC_REDIRECTS:
        target_sym, target_mkt, note = _DYNAMIC_REDIRECTS[clean]
        if market.upper() in ("AUTO", target_mkt) or has_in_suffix:
            return target_sym, target_mkt, note

    resolved_mkt = "IN" if has_in_suffix else (market.upper() if market.upper() in ("US", "IN") else "US")
    return raw, resolved_mkt, None


def search_successor_via_yahoo(dead_ticker: str, market: str, session: Any) -> Optional[Tuple[str, str, str]]:
    """Self-healing fallback: if a ticker fails on Yahoo Finance due to a recent corporate action,
    search Yahoo Finance for an active equity on the same exchange matching the company's name or alias.
    """
    clean_sym = re.sub(r"\.(NS|BO)$", "", dead_ticker.strip().upper())

    # Look up if we know the company's historical name from baseline or redirects
    query_terms = [clean_sym]
    for item in _LIVE_UNIVERSE:
        s_clean = item.get("s", "").replace(".NS", "").replace(".BO", "").upper()
        aliases = str(item.get("a", "")).upper()
        if s_clean == clean_sym or clean_sym in aliases.split():
            if s_clean != clean_sym:
                return (
                    item["s"],
                    item.get("m", market),
                    f"Resolved legacy ticker {clean_sym} to active listing {item['s']} ({item.get('n')})",
                )
            query_terms.insert(0, item.get("n", clean_sym))
            break

    allowed_exchanges = {"NSI", "BSE"} if market.upper() == "IN" else {"NMS", "NYQ", "NGM", "NCM", "ASE", "PCX"}

    for q in query_terms:
        try:
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={requests.utils.quote(q)}&quotesCount=8&newsCount=0"
            r = session.get(url, timeout=4)
            quotes = r.json().get("quotes", [])
            for qt in quotes:
                cand_sym = str(qt.get("symbol", "")).strip().upper()
                cand_clean = re.sub(r"\.(NS|BO)$", "", cand_sym)
                cand_type = str(qt.get("quoteType", "")).strip().upper()
                cand_exch = str(qt.get("exchange", "")).strip().upper()
                cand_name = qt.get("shortname") or qt.get("longname") or ""

                if cand_type != "EQUITY" or cand_exch not in allowed_exchanges:
                    continue
                if cand_clean == clean_sym:
                    continue
                excluded, _, _ = is_non_dcf_instrument(cand_sym, cand_name, cand_type)
                if excluded:
                    continue

                # Prefer .NS for India
                if market.upper() == "IN" and cand_sym.endswith(".BO"):
                    cand_sym = cand_clean + ".NS"
                return (
                    cand_sym,
                    market.upper(),
                    f"Auto-resolved '{clean_sym}' to active exchange ticker '{cand_sym}' ({cand_name})",
                )
        except Exception:
            continue

    return None
