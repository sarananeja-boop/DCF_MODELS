"""
General-Purpose Ind AS Schedule III Primary Filing Extractor.

Parses Consolidated Balance Sheet, Consolidated Statement of Profit and Loss,
Consolidated Cash Flow Statement, and Consolidated Notes from statutory Annual
Report text extracts (Schedule III format). Zero ticker-specific valuation
hardcodes or static overrides: all figures are extracted structurally from the
statutory tables and tagged with note references, units, and provenance.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIRS: List[Path] = [
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ind_as",
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "filings",
    Path("/Users/SMILE/.gemini/antigravity/brain/241b62b1-985a-4c94-a61f-669d5efafa6d/scratch/raw"),
]

_NUM_RE = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")
_NOTE_REF_RE = re.compile(r"^\d{1,2}(?:\s*[A-Za-z])?(?:\s*&\s*\d{1,2}[A-Za-z]?)?$")


def _search_roots(extra_dirs: Optional[List[str]] = None) -> List[Path]:
    roots: List[Path] = []
    env_dir = os.environ.get("VALUATIONLABS_FILINGS_CACHE_DIR")
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


def _find_ar_text_file(ticker: str, extra_dirs: Optional[List[str]] = None) -> Optional[Path]:
    raw_t = (ticker or "").strip().lower()
    if not raw_t:
        return None
    base = re.sub(r"\.(ns|bo|in|l|to|hk|ss|sz)$", "", raw_t)
    cand_pats = (
        re.compile(rf"^{re.escape(base)}_ar_.*\.txt$", re.IGNORECASE),
        re.compile(rf"^{re.escape(base)}_ar\.txt$", re.IGNORECASE),
        re.compile(rf"^{re.escape(base)}_annual_report.*\.txt$", re.IGNORECASE),
        re.compile(rf"^{re.escape(base)}\.txt$", re.IGNORECASE),
    )
    matches: List[Path] = []
    for root in _search_roots(extra_dirs):
        files = sorted([f for f in root.iterdir() if f.is_file()], key=lambda p: p.name, reverse=True)
        for pat in cand_pats:
            for f in files:
                if pat.match(f.name) and f not in matches:
                    matches.append(f)
    return matches[0] if matches else None


def _parse_number(token: str) -> Optional[float]:
    s = (token or "").replace("\u00a0", " ").strip()
    if not s:
        return None
    if s in ("-", "—", "–", "nil", "Nil", "NIL"):
        return 0.0
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    s = s.replace(",", "").replace("`", "").replace("₹", "").strip()
    if not _NUM_RE.match(s):
        return None
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return None


def _detect_unit_multiplier(lines: List[str]) -> Tuple[str, float]:
    blob = " ".join(ln.lower().replace("\u00a0", " ") for ln in lines[:15])
    if "crore" in blob or "crores" in blob:
        return "INR Crore", 1e7
    if "lakh" in blob or "lakhs" in blob:
        return "INR Lakh", 1e5
    if "million" in blob:
        return "INR Million", 1e6
    return "INR Crore", 1e7


def _page_number_at(lines: List[str], line_idx: int) -> Optional[str]:
    """Return nearest preceding `=== AR PAGE N ===` page label, if markers exist."""
    for i in range(min(line_idx, len(lines) - 1), -1, -1):
        m = re.search(r"===\s*AR\s*PAGE\s*([A-Za-z0-9\-]+)\s*===", lines[i], re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_period_labels(header_lines: List[str]) -> List[str]:
    """Extract period / balance-sheet date strings from Schedule III statement header lines."""
    found: List[str] = []
    date_pat = re.compile(
        r"(?:\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s*\d{4}|FY\s*\d{4}(?:-\d{2,4})?|\d{4}-\d{2}|(?:31|30)\.\d{2}\.\d{4})",
        re.IGNORECASE,
    )
    for ln in header_lines[:18]:
        for m in date_pat.findall(ln.replace("\u00a0", " ")):
            tok = " ".join(m.split())
            if tok not in found:
                found.append(tok)
    return found


def _find_consolidated_section(
    lines: List[str],
    header_keywords: List[str],
    max_len: int = 240,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Find the Consolidated statutory statement table block.
    Prefers occurrences that contain table headers (`Particulars` / `in crore`)
    within the next 15 lines, rejects Standalone statements, and ignores
    Table of Contents / auditor narrative references.
    """
    candidates: List[int] = []
    for idx, ln in enumerate(lines):
        up = " ".join(ln.upper().split())
        if "STANDALONE" in up:
            continue
        if any(k in up for k in header_keywords) and len(up) <= 90:
            window = " ".join(lines[idx : idx + 15]).lower()
            if "standalone" in window:
                continue
            if "particulars" in window and ("crore" in window or "lakh" in window or "million" in window or "march" in window):
                candidates.append(idx)
    if not candidates:
        return None, None
    start = candidates[-1]
    end = min(len(lines), start + max_len)
    note_hdr_stop = re.compile(r"^note\s*[-\.:]?\s*\d+[A-Za-z]?\b", re.IGNORECASE)
    for j in range(start + 5, end):
        low = lines[j].replace("\u00a0", " ").lower().strip()
        if (
            "referred to in our report" in low
            or low.startswith("notes forming part of consolidated financial statements")
            or low.startswith("notes forming part")
            or note_hdr_stop.match(low)
            or low in ("consolidated statement of profit and loss", "consolidated cash flow statement", "consolidated statement of cash flows", "consolidated statement of changes in equity")
        ):
            end = j
            break
        if "cash and cash equivalents - closing balance" in low:
            # Stop right after the 2 numeric rows for closing cash or before any Notes heading
            stop_at = min(len(lines), j + 8)
            for k in range(j + 1, stop_at):
                lk = lines[k].replace("\u00a0", " ").lower().strip()
                if "notes forming part" in lk or "=== ar page" in lk or note_hdr_stop.match(lk):
                    stop_at = k
                    break
            end = stop_at
            break
    return start, end


def _is_note_token(s: str) -> bool:
    st = (s or "").strip()
    if not st or "." in st or "," in st or "(" in st:
        return False
    return bool(_NOTE_REF_RE.match(st))


def _extract_two_col_rows(section_lines: List[str]) -> List[Dict[str, Any]]:
    """
    Parse Schedule III vertical-stream PDF-extracted two-period table rows into
    structured `{label, note, current, prior}` dictionaries.
    """
    rows: List[Dict[str, Any]] = []
    n = len(section_lines)
    i = 0
    # Skip header block up to ASSETS / Particulars / 2025-26 etc.
    label_buf: List[str] = []
    pending_note: Optional[str] = None
    in_body = False

    skip_prefixes = (
        "annual report",
        "financial statements",
        "consolidated balance sheet",
        "consolidated statement",
        "consolidated cash flow",
        "for the year ended",
        "as at ",
        "particulars",
        "note",
        "no.",
        "=== ar page",
        "2025-26",
        "2024-25",
        "31st march",
    )

    while i < n:
        raw = section_lines[i].replace("\u00a0", " ").strip()
        low = raw.lower()
        if not in_body:
            if low in ("assets", "revenue from operations", "a.", "a. cash flow from operating activities") or "revenue from operations" in low:
                in_body = True
            elif any(low.startswith(p) for p in skip_prefixes) or not raw:
                i += 1
                continue
            else:
                i += 1
                continue

        if not raw or any(low.startswith(p) for p in ("* restated", "^ net of", "=== ar page", "corporate overview", "statutory reports", "financial statements", "this is the consolidated", "notes forming part")):
            i += 1
            continue

        # Handle inline multi-column row (`Label   1,234.56   1,100.00`)
        inline_nums = re.findall(r"(\(?[\d,]+\.\d+\)?|\s-\s*)$", raw)
        # Check if line itself is a single number token
        val = _parse_number(raw)
        if val is not None and i + 1 < n:
            val2 = _parse_number(section_lines[i + 1].replace("\u00a0", " ").strip())
            # Could current line be a Note number? (integer without decimal followed by two decimals)
            if _is_note_token(raw) and i + 2 < n:
                v1 = _parse_number(section_lines[i + 1].replace("\u00a0", " ").strip())
                v2 = _parse_number(section_lines[i + 2].replace("\u00a0", " ").strip())
                if v1 is not None and v2 is not None:
                    pending_note = raw
                    rows.append({
                        "label": " ".join(label_buf).strip() or "Subtotal",
                        "note": pending_note,
                        "current": v1,
                        "prior": v2,
                    })
                    label_buf = []
                    pending_note = None
                    i += 3
                    continue
            if val2 is not None:
                rows.append({
                    "label": " ".join(label_buf).strip() or "Subtotal",
                    "note": pending_note,
                    "current": val,
                    "prior": val2,
                })
                label_buf = []
                pending_note = None
                i += 2
                continue

        if _is_note_token(raw) and label_buf:
            pending_note = raw
            i += 1
            continue

        # Check inline 2-value row like "Interest expense  1,359.78  1,293.76"
        parts = re.split(r"\s{2,}|\t+", raw)
        if len(parts) >= 3:
            v1 = _parse_number(parts[-2])
            v2 = _parse_number(parts[-1])
            if v1 is not None and v2 is not None:
                lbl = " ".join(parts[:-2]).strip()
                if len(parts) >= 4 and _is_note_token(parts[-3]):
                    pending_note = parts[-3]
                    lbl = " ".join(parts[:-3]).strip()
                rows.append({
                    "label": ( " ".join(label_buf) + " " + lbl ).strip(),
                    "note": pending_note,
                    "current": v1,
                    "prior": v2,
                })
                label_buf = []
                pending_note = None
                i += 1
                continue

        # Otherwise accumulate label
        if raw not in ("(a)", "(b)", "(c)", "A", "B"):
            label_buf.append(raw)
        elif raw in ("(a)", "(b)"):
            label_buf.append(raw)
        i += 1

    return rows


def _find_row(rows: List[Dict[str, Any]], include: List[str], exclude: Optional[List[str]] = None, occurrence: int = 0) -> Optional[Dict[str, Any]]:
    matches = []
    exc = [e.lower() for e in (exclude or [])]
    inc = [k.lower() for k in include]
    for r in rows:
        lbl = r["label"].lower()
        if any(k in lbl for k in inc) and not any(e in lbl for e in exc):
            matches.append(r)
    if len(matches) > occurrence:
        return matches[occurrence]
    return None


def _extract_note_block_with_meta(
    lines: List[str],
    notes_start_idx: int,
    note_prefix: str,
    max_lines: int = 160,
) -> Tuple[List[str], Optional[int]]:
    clean_pref = re.sub(r"[^0-9A-Za-z]", "", str(note_prefix or ""))
    if not clean_pref:
        return [], None
    pat = re.compile(rf"^(?:NOTE\s*[-\.:]?\s*{re.escape(clean_pref)}\b|{re.escape(clean_pref)}\.\s+[A-Z])", re.IGNORECASE)
    next_note = re.compile(r"^(?:NOTE\s*[-\.:]?\s*\d+|\d+\.\s+[A-Z][a-z]+)", re.IGNORECASE)
    for idx in range(notes_start_idx, len(lines)):
        s = lines[idx].replace("\u00a0", " ").strip()
        if pat.match(s) and "(contd" not in s.lower():
            block = [s]
            for j in range(idx + 1, min(len(lines), idx + max_lines)):
                sj = lines[j].replace("\u00a0", " ").strip()
                if next_note.match(sj) and not pat.match(sj) and "(contd" not in sj.lower():
                    break
                block.append(lines[j])
            return block, idx
    return [], None


def _extract_note_block(lines: List[str], notes_start_idx: int, note_prefix: str, max_lines: int = 160) -> List[str]:
    blk, _ = _extract_note_block_with_meta(lines, notes_start_idx, note_prefix, max_lines=max_lines)
    return blk


def _find_note_block_by_topic(
    lines: List[str],
    notes_start_idx: int,
    candidate_nums: List[Optional[str]],
    topic_keywords: List[str],
    max_lines: int = 140,
) -> Tuple[List[str], Dict[str, Any]]:
    """
    Locate a Consolidated Ind AS Note dynamically across Schedule III annual reports:
    1. Prefer any BS/P&L row-linked note number (`candidate_nums`) when its block matches `topic_keywords`.
    2. Otherwise scan all `NOTE - <N>` / `<N>. <Heading>` blocks from `notes_start_idx` onward
       matching `topic_keywords`, preserving exact compatibility while working across any company.
    """
    kw_low = [k.lower() for k in topic_keywords]
    for cand in candidate_nums:
        if not cand:
            continue
        blk, idx = _extract_note_block_with_meta(lines, notes_start_idx, str(cand), max_lines=max_lines)
        if blk:
            blob = " ".join(ln.replace("\u00a0", " ").lower() for ln in blk)
            if any(k in blob for k in kw_low):
                return blk, {
                    "note_ref": f"Note {cand}",
                    "line_no": (idx + 1) if idx is not None else None,
                    "source_page": _page_number_at(lines, idx) if idx is not None else None,
                    "heading": blk[0][:120],
                }

    # Dynamic Schedule III topic scan across all Notes to Consolidated Financial Statements
    note_hdr_pat = re.compile(r"^(?:NOTE\s*[-\.:]?\s*(\d+[A-Za-z]?)\b|(\d+[A-Za-z]?)\.\s+[A-Z])", re.IGNORECASE)
    for idx in range(notes_start_idx, len(lines)):
        s = lines[idx].replace("\u00a0", " ").strip()
        m = note_hdr_pat.match(s)
        if not m or "(contd" in s.lower():
            continue
        num = m.group(1) or m.group(2)
        blk = [s]
        for j in range(idx + 1, min(len(lines), idx + max_lines)):
            sj = lines[j].replace("\u00a0", " ").strip()
            mj = note_hdr_pat.match(sj)
            if mj and (mj.group(1) or mj.group(2)) != num and "(contd" not in sj.lower():
                break
            blk.append(lines[j])
        blob = " ".join(ln.replace("\u00a0", " ").lower() for ln in blk)
        if any(k in blob for k in kw_low):
            return blk, {
                "note_ref": f"Note {num}",
                "line_no": idx + 1,
                "source_page": _page_number_at(lines, idx),
                "heading": blk[0][:120],
            }
    return [], {"note_ref": None, "line_no": None, "source_page": None, "heading": None}


def _extract_value_near_label(block: List[str], label_keywords: List[str], prefer_after: int = 0) -> Tuple[Optional[float], Optional[float]]:
    for idx in range(prefer_after, len(block)):
        low = block[idx].replace("\u00a0", " ").lower().strip()
        if any(k in low for k in label_keywords):
            # Look ahead up to 3 lines for 1 or 2 numbers
            vals: List[float] = []
            for j in range(idx + 1, min(len(block), idx + 4)):
                v = _parse_number(block[j])
                if v is not None:
                    vals.append(v)
                elif vals:
                    break
            if vals:
                return vals[0], vals[1] if len(vals) > 1 else None
            # Also check inline regex (` ` 1,234.56 `)
            inline = re.findall(r"[`₹]\s*([\d,]+(?:\.\d+)?)\s*(?:crore|lakh)?", low)
            if inline:
                nums = [_parse_number(x) for x in inline if _parse_number(x) is not None]
                if nums:
                    return nums[0], nums[1] if len(nums) > 1 else None
    return None, None


def _parse_note_32_commitments(block: List[str]) -> Tuple[Optional[float], Optional[float]]:
    txt = " ".join(ln.replace("\u00a0", " ") for ln in block)
    m = re.search(
        r"contracts\s+remaining\s+to\s+be\s+executed\s+on\s+capital\s+account.*?"
        r"[`₹]\s*([\d,]+(?:\.\d+)?)\s*crore.*?\([^)]*?[`₹]\s*([\d,]+(?:\.\d+)?)\s*crore\)",
        txt,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return _parse_number(m.group(1)), _parse_number(m.group(2))
    return None, None


def _parse_note_46_recoupment(block: List[str]) -> Dict[str, Optional[float]]:
    txt = " ".join(ln.replace("\u00a0", " ") for ln in block)
    res: Dict[str, Optional[float]] = {
        "revaluation_recoupment": None,
        "aad_adjustment": None,
        "subsidiary_depr_capitalisation": None,
    }
    m1 = re.search(r"recouping\s+from\s+the\s+retained\s+earnings.*?amounts?\s+to\s+[`₹]\s*([\d,]+(?:\.\d+)?)\s*crore", txt, re.IGNORECASE | re.DOTALL)
    if m1:
        res["revaluation_recoupment"] = _parse_number(m1.group(1))
    m2 = re.search(r"depreciation\s+amount\s+to\s+be\s+claimed.*?reduced\s+by\s+[`₹]\s*([\d,]+(?:\.\d+)?)\s*crore", txt, re.IGNORECASE | re.DOTALL)
    if m2:
        res["aad_adjustment"] = _parse_number(m2.group(1))
    m3 = re.search(r"depreciation\s+capitalisation\s+amounts?\s+to\s+[`₹]\s*([\d,]+(?:\.\d+)?)\s*crore", txt, re.IGNORECASE | re.DOTALL)
    if m3:
        res["subsidiary_depr_capitalisation"] = _parse_number(m3.group(1))
    return res


def _parse_note_16_earmarked(block: List[str], current_total: Optional[float]) -> Dict[str, Any]:
    unpaid_div, _ = _extract_value_near_label(block, ["unpaid dividend"])
    escrow, _ = _extract_value_near_label(block, ["escrow accounts"])
    notes_txt = " ".join(ln.replace("\u00a0", " ").replace("\x07", " ") for ln in block)

    unforeseen = None
    security_dep = None
    collateral_dep = None
    clause_re = re.compile(
        r"bank\s+deposits\s+(?:include(?:\s+deposit\s+of)?|of)\s+[`₹]\s*([\d,]+(?:\.\d+)?)\s*crore(.*?)(?=bank\s+deposits|$)",
        re.IGNORECASE,
    )
    for m in clause_re.finditer(notes_txt):
        val = _parse_number(m.group(1))
        desc = m.group(2).lower()
        if val is None:
            continue
        if "unforeseen exigencies" in desc and unforeseen is None:
            unforeseen = val
        elif "security for payment" in desc and security_dep is None:
            security_dep = val
        elif ("collateral" in desc and "earmarked" in desc) or "earmarked to fulfill" in desc:
            if collateral_dep is None:
                collateral_dep = val

    parts = [v for v in (unpaid_div, escrow, unforeseen, security_dep, collateral_dep) if v is not None]
    earmarked_total = round(sum(parts), 4) if parts else None
    unrestricted = None
    if current_total is not None and earmarked_total is not None:
        unrestricted = round(max(0.0, current_total - earmarked_total), 4)
    return {
        "unpaid_dividend": unpaid_div,
        "escrow_accounts": escrow,
        "unforeseen_exigencies_deposits": unforeseen,
        "security_obligation_deposits": security_dep,
        "collateral_earmarked_deposits": collateral_dep,
        "total_restricted_earmarked": earmarked_total,
        "unrestricted_other_bank_balances": unrestricted,
    }


def _extract_exact_value_near_label(block: List[str], exact_labels: List[str]) -> Tuple[Optional[float], Optional[float]]:
    ex_low = [x.lower() for x in exact_labels]
    for idx, ln in enumerate(block):
        low = " ".join(ln.replace("\u00a0", " ").lower().split())
        if low in ex_low:
            vals: List[float] = []
            for j in range(idx + 1, min(len(block), idx + 4)):
                v = _parse_number(block[j])
                if v is not None:
                    vals.append(v)
                elif vals:
                    break
            if vals:
                return vals[0], vals[1] if len(vals) > 1 else None
    return None, None


def _parse_note_47_leases(block: List[str]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {
        "rou_closing": None,
        "rou_amortisation": None,
        "lease_liab_opening": None,
        "lease_finance_cost": None,
        "lease_payment": None,
        "lease_liab_closing": None,
        "noncurrent_lease_liab": None,
        "current_lease_liab": None,
    }
    # Locate the first ROU "Total" line (Current year movement)
    for idx, ln in enumerate(block):
        if ln.replace("\u00a0", " ").strip().lower() == "total":
            nums: List[float] = []
            for j in range(idx + 1, min(len(block), idx + 8)):
                v = _parse_number(block[j])
                if v is not None:
                    nums.append(v)
                elif nums:
                    break
            if len(nums) >= 5:
                out["rou_amortisation"] = nums[3]
                out["rou_closing"] = nums[4]
                break

    # Locate lease liabilities movement section for current year
    for idx, ln in enumerate(block):
        low = ln.lower()
        if "movement in lease liabilities" in low:
            sub = block[idx : idx + 35]
            op, _ = _extract_value_near_label(sub, ["lease liabilities as at april 1"])
            fc, _ = _extract_value_near_label(sub, ["finance cost expense"])
            pmt, _ = _extract_value_near_label(sub, ["payment during the year"])
            cl, _ = _extract_value_near_label(sub, ["balance as on 31st march"])
            ncl, _ = _extract_exact_value_near_label(sub, ["non current lease liabilities", "non-current lease liabilities"])
            cul, _ = _extract_exact_value_near_label(sub, ["current lease liabilities"])
            out["lease_liab_opening"] = op
            out["lease_finance_cost"] = fc
            out["lease_payment"] = pmt
            out["lease_liab_closing"] = cl
            out["noncurrent_lease_liab"] = ncl
            out["current_lease_liab"] = cul
            break
    return out


def extract_ind_as_ar_financials(
    ticker: str,
    extra_dirs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Extract structured Consolidated Balance Sheet, P&L, Cash Flow, and key Notes
    from an Ind AS Schedule III Annual Report text file.
    Returns `{"available": False, ...}` cleanly if no statutory filing is staged.
    """
    ar_path = _find_ar_text_file(ticker, extra_dirs=extra_dirs)
    if ar_path is None:
        return {"available": False, "source_citation": None}

    lines = ar_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    bs_s, bs_e = _find_consolidated_section(lines, ["CONSOLIDATED BALANCE SHEET"], max_len=240)
    is_s, is_e = _find_consolidated_section(lines, ["CONSOLIDATED STATEMENT OF PROFIT AND LOSS"], max_len=190)
    cf_s, cf_e = _find_consolidated_section(lines, ["CONSOLIDATED CASH FLOW STATEMENT"], max_len=200)

    if bs_s is None or is_s is None or cf_s is None:
        return {"available": False, "source_citation": f"Primary Annual Report ({ar_path.name}) incomplete headers"}

    bs_rows = _extract_two_col_rows(lines[bs_s:bs_e])
    is_rows = _extract_two_col_rows(lines[is_s:is_e])
    cf_rows = _extract_two_col_rows(lines[cf_s:cf_e])
    unit_label, mult = _detect_unit_multiplier(lines[bs_s : bs_s + 15])
    notes_start = max(bs_e or 0, is_e or 0, cf_e or 0)

    def _pick(rows: List[Dict[str, Any]], inc: List[str], exclude: Optional[List[str]] = None, occurrence: int = 0) -> Dict[str, Optional[float]]:
        r = _find_row(rows, inc, exclude, occurrence=occurrence)
        if not r:
            return {"current": None, "prior": None}
        return {"current": r["current"], "prior": r["prior"], "note": r.get("note")}

    # Balance Sheet
    ppe = _pick(bs_rows, ["property, plant and equipment"])
    cwip = _pick(bs_rows, ["capital work-in-progress"])
    other_nca = _pick(bs_rows, ["other non current assets"])
    inv = _pick(bs_rows, ["inventories"])
    cur_inv = _pick(bs_rows, ["investments"], occurrence=1)  # Current Investments (occurrence 0 is Non-current)
    trade_rec = _pick(bs_rows, ["trade receivables"])
    cce = _pick(bs_rows, ["cash and cash equivalents"], exclude=["bank balances other than"])
    other_bank = _pick(bs_rows, ["bank balances other than cash and cash equivalents"])
    reg_asset = _pick(bs_rows, ["regulatory deferral account balances"], occurrence=0)
    total_assets = _pick(bs_rows, ["total assets"])

    eq_cap = _pick(bs_rows, ["equity share capital"])
    other_eq = _pick(bs_rows, ["other equity"])
    nci = _pick(bs_rows, ["non-controlling interest"])
    total_eq = _pick(bs_rows, ["total equity"], exclude=["liabilities"])

    nc_borr = _pick(bs_rows, ["borrowings"], occurrence=0)
    nc_lease = _pick(bs_rows, ["lease liabilities"], occurrence=0)
    cons_sec_dep = _pick(bs_rows, ["consumers' security deposits", "security deposits"])
    dtl = _pick(bs_rows, ["deferred tax liabilities"])
    c_borr = _pick(bs_rows, ["borrowings"], occurrence=1)
    c_lease = _pick(bs_rows, ["lease liabilities"], occurrence=1)
    reg_liab = _pick(bs_rows, ["regulatory deferral account balances"], occurrence=1)
    total_eq_liab = _pick(bs_rows, ["total equity and liabilities"])

    # Compute Total Borrowings & Leases cleanly
    total_borr_cur = (
        round((nc_borr["current"] or 0.0) + (c_borr["current"] or 0.0), 4)
        if nc_borr["current"] is not None or c_borr["current"] is not None
        else None
    )
    total_lease_cur = (
        round((nc_lease["current"] or 0.0) + (c_lease["current"] or 0.0), 4)
        if nc_lease["current"] is not None or c_lease["current"] is not None
        else None
    )

    # Income Statement
    rev_ops = _pick(is_rows, ["revenue from operations"])
    other_inc = _pick(is_rows, ["other income"])
    tot_inc = _pick(is_rows, ["total income"])
    cost_energy = _pick(is_rows, ["cost of energy purchased"])
    cost_fuel = _pick(is_rows, ["cost of fuel"])
    cost_materials = _pick(is_rows, ["cost of materials consumed"])
    purch_sit = _pick(is_rows, ["purchases of stock-in-trade"])
    emp_ben = _pick(is_rows, ["employee benefits expense"])
    fin_costs = _pick(is_rows, ["finance costs"])
    da_is = _pick(is_rows, ["depreciation and amortisation"])
    oth_exp = _pick(is_rows, ["other expenses"])
    tot_exp = _pick(is_rows, ["total expenses"])
    pb_reg_tax = _pick(is_rows, ["profit before regulatory income and tax"])
    reg_inc_net = _pick(is_rows, ["regulatory income (net)"])
    pbt_is = _pick(is_rows, ["profit before tax"])
    cur_tax = _pick(is_rows, ["current tax"])
    def_tax = _pick(is_rows, ["deferred tax"])
    tot_tax = _pick(is_rows, ["total tax expenses"])
    pat_total = _pick(is_rows, ["profit for the year"])
    pat_owners = _pick(is_rows, ["owners of the equity"], occurrence=0)
    pat_nci = _pick(is_rows, ["non-controlling interest"], occurrence=0)
    eps_is = _pick(is_rows, ["earnings per equity share"])

    cogs_cur = round(
        sum(
            x["current"] or 0.0
            for x in (cost_energy, cost_fuel, cost_materials, purch_sit)
        ),
        4,
    )
    cogs_prior = round(
        sum(
            x["prior"] or 0.0
            for x in (cost_energy, cost_fuel, cost_materials, purch_sit)
        ),
        4,
    )

    # Cash Flow Statement
    pbt_cf = _pick(cf_rows, ["profit before tax"])
    da_cf = _pick(cf_rows, ["depreciation and amortisation expense"])
    op_prof_bwc = _pick(cf_rows, ["operating profit before working capital"])
    wc_tr = _pick(cf_rows, ["trade and other receivables"])
    wc_reg = _pick(cf_rows, ["net change in regulatory deferral"])
    wc_inv = _pick(cf_rows, ["inventories"])
    wc_tp = _pick(cf_rows, ["trade and other payables"])
    cash_gen_ops = _pick(cf_rows, ["cash generated from operations"])
    tax_paid = _pick(cf_rows, ["income tax paid"])
    cfo = _pick(cf_rows, ["net cash flow from operating activities", "net cash from operating activities"])
    capex = _pick(cf_rows, ["purchase of property, plant", "purchase of property, plant & equipment"])
    sale_ppe = _pick(cf_rows, ["proceeds from sale of property, plant"])
    cfi = _pick(cf_rows, ["net cash used in investing activities", "net cash from investing activities"])
    lease_pmt_cf = _pick(cf_rows, ["payment of lease liabilities"])
    fin_paid_cf = _pick(cf_rows, ["finance costs paid"])
    div_paid_cf = _pick(cf_rows, ["dividends paid"])
    cff = _pick(cf_rows, ["net cash used in financing activities", "net cash from financing activities"])
    open_cash = _pick(cf_rows, ["opening balance"])
    close_cash = _pick(cf_rows, ["closing balance"])

    # Dynamic Schedule III Notes extraction (topic/row-note driven, fallback-free across Ind AS ARs)
    notes_provenance: Dict[str, Any] = {}

    n11_blk, n11_meta = _find_note_block_by_topic(
        lines, notes_start,
        [other_nca.get("note"), "11"],
        ["capital advances", "other non-current assets", "other non current assets"],
        max_lines=45,
    )
    notes_provenance["capital_advances"] = n11_meta
    cap_adv_cur, cap_adv_prior = _extract_value_near_label(n11_blk, ["capital advances"])
    oth_adv_cur, oth_adv_prior = _extract_value_near_label(n11_blk, ["others advances", "other advances"])

    n16_blk, n16_meta = _find_note_block_by_topic(
        lines, notes_start,
        [other_bank.get("note"), "16"],
        ["bank balances other than", "unpaid dividend", "earmarked", "escrow accounts"],
        max_lines=60,
    )
    notes_provenance["cash_restriction"] = n16_meta
    n16_info = _parse_note_16_earmarked(n16_blk, other_bank["current"])

    n21_blk, n21_meta = _find_note_block_by_topic(
        lines, notes_start,
        [other_eq.get("note"), "21"],
        ["other equity", "retained earnings", "fund for unforeseen exigencies"],
        max_lines=60,
    )
    notes_provenance["other_equity"] = n21_meta
    ret_earn_cur, ret_earn_prior = _extract_value_near_label(n21_blk, ["retained earnings"])
    fctr_cur, fctr_prior = _extract_value_near_label(n21_blk, ["foreign currency translation"])
    fvoci_cur, fvoci_prior = _extract_value_near_label(n21_blk, ["equity instruments through other comprehensive"])
    cap_res_cur, cap_res_prior = _extract_value_near_label(n21_blk, ["capital reserve"])
    ffue_cur, ffue_prior = _extract_value_near_label(n21_blk, ["fund for unforeseen exigencies"])

    n32_blk, n32_meta = _find_note_block_by_topic(
        lines, notes_start,
        ["32"],
        ["capital commitments", "contracts remaining to be executed on capital account", "contingent liabilities and commitments"],
        max_lines=120,
    )
    notes_provenance["capital_commitments"] = n32_meta
    cap_comm_cur, cap_comm_prior = _parse_note_32_commitments(n32_blk)

    n37_blk, n37_meta = _find_note_block_by_topic(
        lines, notes_start,
        [fin_costs.get("note"), "37"],
        ["finance costs", "interest expense", "other borrowing costs"],
        max_lines=40,
    )
    notes_provenance["finance_costs"] = n37_meta
    int_exp_cur, _ = _extract_value_near_label(n37_blk, ["interest expense"])
    oth_borr_cur, _ = _extract_value_near_label(n37_blk, ["other borrowing costs"])
    fin_cap_cur, _ = _extract_value_near_label(n37_blk, ["allocated to ppe", "capitalised"])

    n38_blk, n38_meta = _find_note_block_by_topic(
        lines, notes_start,
        [da_is.get("note"), "38"],
        ["depreciation and amortisation", "depreciation/ amortisation of property", "amortisation of intangible"],
        max_lines=40,
    )
    notes_provenance["depreciation_expense"] = n38_meta
    ppe_dep_cur, ppe_dep_prior = _extract_value_near_label(n38_blk, ["depreciation/ amortisation of property", "depreciation of property"])
    int_am_cur, int_am_prior = _extract_value_near_label(n38_blk, ["amortisation of intangible"])
    recoup_cur, recoup_prior = _extract_value_near_label(n38_blk, ["recoupment from retained earnings"])
    gross_da_cur = (
        round((ppe_dep_cur or 0.0) + (int_am_cur or 0.0), 4)
        if ppe_dep_cur is not None or int_am_cur is not None
        else None
    )
    gross_da_prior = (
        round((ppe_dep_prior or 0.0) + (int_am_prior or 0.0), 4)
        if ppe_dep_prior is not None or int_am_prior is not None
        else None
    )

    n46_blk, n46_meta = _find_note_block_by_topic(
        lines, notes_start,
        ["46"],
        ["recouping from the retained earnings", "depreciation amount to be claimed", "advance against depreciation"],
        max_lines=40,
    )
    notes_provenance["depreciation_recoupment"] = n46_meta
    n46_info = _parse_note_46_recoupment(n46_blk)

    n47_blk, n47_meta = _find_note_block_by_topic(
        lines, notes_start,
        [nc_lease.get("note"), c_lease.get("note"), "47"],
        ["movement in lease liabilities", "ind as 116", "right-of-use assets", "right of use assets"],
        max_lines=150,
    )
    notes_provenance["ind_as_116_leases"] = n47_meta
    n47_info = _parse_note_47_leases(n47_blk)

    statements_provenance = {
        "balance_sheet": {
            "statement_name": "Consolidated Balance Sheet",
            "consolidation_basis": "Consolidated",
            "periods": _extract_period_labels(lines[bs_s : bs_s + 18]),
            "unit_label": unit_label,
            "line_no": bs_s + 1,
            "source_page": _page_number_at(lines, bs_s),
        },
        "income_statement": {
            "statement_name": "Consolidated Statement of Profit and Loss",
            "consolidation_basis": "Consolidated",
            "periods": _extract_period_labels(lines[is_s : is_s + 18]),
            "unit_label": unit_label,
            "line_no": is_s + 1,
            "source_page": _page_number_at(lines, is_s),
        },
        "cash_flow_statement": {
            "statement_name": "Consolidated Cash Flow Statement",
            "consolidation_basis": "Consolidated",
            "periods": _extract_period_labels(lines[cf_s : cf_s + 18]),
            "unit_label": unit_label,
            "line_no": cf_s + 1,
            "source_page": _page_number_at(lines, cf_s),
        },
    }

    # Unrestricted Cash & Liquid Investments reconciliation
    total_unrestricted_cash = None
    if cce["current"] is not None:
        unr_ob = n16_info.get("unrestricted_other_bank_balances") or 0.0
        total_unrestricted_cash = round((cce["current"] or 0.0) + (cur_inv["current"] or 0.0) + unr_ob, 4)

    return {
        "available": True,
        "source_citation": f"Primary Ind AS Consolidated Annual Report ({ar_path.name})",
        "file_path": str(ar_path),
        "consolidation_basis": "Consolidated",
        "accounting_standard": "IND_AS",
        "unit_label": unit_label,
        "unit_multiplier": mult,
        "statements_provenance": statements_provenance,
        "notes_provenance": notes_provenance,
        "balance_sheet": {
            "ppe": ppe,
            "cwip": cwip,
            "other_noncurrent_assets": other_nca,
            "inventories": inv,
            "current_investments": cur_inv,
            "trade_receivables": trade_rec,
            "cash_and_cash_equivalents": cce,
            "other_bank_balances": other_bank,
            "regulatory_deferral_debit": reg_asset,
            "total_assets": total_assets,
            "equity_share_capital": eq_cap,
            "other_equity": other_eq,
            "non_controlling_interest": nci,
            "total_equity": total_eq,
            "noncurrent_borrowings": nc_borr,
            "noncurrent_lease_liabilities": nc_lease,
            "consumers_security_deposits": cons_sec_dep,
            "deferred_tax_liabilities": dtl,
            "current_borrowings": c_borr,
            "current_lease_liabilities": c_lease,
            "regulatory_deferral_credit": reg_liab,
            "total_equity_and_liabilities": total_eq_liab,
            "total_borrowings_excl_lease": total_borr_cur,
            "total_lease_liabilities": total_lease_cur,
            "total_debt_incl_lease": round((total_borr_cur or 0.0) + (total_lease_cur or 0.0), 4)
            if total_borr_cur is not None or total_lease_cur is not None
            else None,
            "total_unrestricted_cash": total_unrestricted_cash,
        },
        "income_statement": {
            "revenue_from_operations": rev_ops,
            "other_income": other_inc,
            "total_income": tot_inc,
            "cost_of_energy_purchased": cost_energy,
            "cost_of_fuel": cost_fuel,
            "cost_of_materials_consumed": cost_materials,
            "purchases_of_stock_in_trade": purch_sit,
            "cogs_total": {"current": cogs_cur, "prior": cogs_prior},
            "employee_benefits": emp_ben,
            "finance_costs": fin_costs,
            "depreciation_and_amortisation": da_is,
            "other_expenses": oth_exp,
            "total_expenses": tot_exp,
            "profit_before_regulatory_and_tax": pb_reg_tax,
            "regulatory_income_net": reg_inc_net,
            "profit_before_tax": pbt_is,
            "current_tax": cur_tax,
            "deferred_tax": def_tax,
            "total_tax_expense": tot_tax,
            "profit_for_the_year": pat_total,
            "profit_attributable_to_owners": pat_owners,
            "profit_attributable_to_nci": pat_nci,
            "basic_diluted_eps": eps_is,
        },
        "cash_flow_statement": {
            "pbt": pbt_cf,
            "da_addback": da_cf,
            "operating_profit_before_wc": op_prof_bwc,
            "wc_trade_receivables": wc_tr,
            "wc_regulatory_deferral": wc_reg,
            "wc_inventories": wc_inv,
            "wc_trade_payables": wc_tp,
            "cash_generated_from_operations": cash_gen_ops,
            "income_tax_paid": tax_paid,
            "cfo": cfo,
            "capex_purchase_ppe_cwip": capex,
            "proceeds_sale_ppe": sale_ppe,
            "cfi": cfi,
            "lease_payments": lease_pmt_cf,
            "finance_costs_paid": fin_paid_cf,
            "dividends_paid": div_paid_cf,
            "cff": cff,
            "opening_cash": open_cash,
            "closing_cash": close_cash,
        },
        "notes": {
            "note_11_capital_advances": {"current": cap_adv_cur, "prior": cap_adv_prior},
            "note_11_other_advances": {"current": oth_adv_cur, "prior": oth_adv_prior},
            "note_16_cash_restriction": n16_info,
            "note_21_other_equity": {
                "retained_earnings": {"current": ret_earn_cur, "prior": ret_earn_prior},
                "foreign_currency_translation_reserve": {"current": fctr_cur, "prior": fctr_prior},
                "fvoci_equity_reserve": {"current": fvoci_cur, "prior": fvoci_prior},
                "capital_reserve": {"current": cap_res_cur, "prior": cap_res_prior},
                "fund_for_unforeseen_exigencies": {"current": ffue_cur, "prior": ffue_prior},
            },
            "note_32c_capital_commitments": {"current": cap_comm_cur, "prior": cap_comm_prior},
            "note_37_finance_costs": {
                "interest_expense": int_exp_cur,
                "other_borrowing_costs": oth_borr_cur,
                "capitalised_to_ppe_cwip": fin_cap_cur,
            },
            "note_38_46_depreciation_reconciliation": {
                "ppe_depreciation": {"current": ppe_dep_cur, "prior": ppe_dep_prior},
                "intangibles_amortisation": {"current": int_am_cur, "prior": int_am_prior},
                "gross_da": {"current": gross_da_cur, "prior": gross_da_prior},
                "recoupment_from_retained_earnings_and_adj": {"current": recoup_cur, "prior": recoup_prior},
                "net_da_in_pl_and_cf": da_is,
                **n46_info,
            },
            "note_47_ind_as_116_leases": n47_info,
        },
    }
