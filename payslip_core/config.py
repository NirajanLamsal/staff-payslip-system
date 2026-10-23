"""Local settings (firm name, logo, column roles). Stored in config/settings.json next to the app."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict

from .util import norm_header

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
SITE_LOGO = CONFIG_DIR / "logo.png"
ASSETS_DIR = BASE_DIR / "assets"
DEFAULT_LOGO = ASSETS_DIR / "default_logo.png"
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"

# Roles a column can have
ROLE_INCOME = "income"                    # earning, included in the workbook 'Total Amount'
ROLE_LEAVE = "leave"                      # the paid-leave amount (comments are read for details)
ROLE_INCOME_AFTER = "income_after_total"  # added after the total (e.g. 'Previous/Due')
ROLE_DEDUCTION = "deduction"              # deducted before the workbook 'Total Amount'
ROLE_DEDUCTION_AFTER = "deduction_after_total"  # e.g. income tax computed on the total
ROLE_WORKING_DAY_AMT = "working_day_amt"  # prorated salary for days worked → printed as "Basic Salary"
ROLE_BASE_SALARY = "base_salary"          # full monthly gross salary (for per-day rate; NOT printed)
ROLE_ID = "id"
ROLE_NAME = "name"
ROLE_PAN = "pan"
ROLE_ATT_WORKING = "att_working"
ROLE_ATT_PRESENT = "att_present"
ROLE_ATT_ABSENT = "att_absent"
ROLE_ATT_HOLIDAYS = "att_holidays"
ROLE_WB_TOTAL = "wb_total"
ROLE_WB_NET = "wb_net"
ROLE_REMARKS = "remarks"
ROLE_INFO = "info"        # kept for reference only, never printed or added up
ROLE_UNMAPPED = "unmapped"

ALL_ROLES = [ROLE_INCOME, ROLE_LEAVE, ROLE_INCOME_AFTER, ROLE_DEDUCTION, ROLE_DEDUCTION_AFTER,
             ROLE_WORKING_DAY_AMT, ROLE_BASE_SALARY,
             ROLE_ID, ROLE_NAME, ROLE_PAN, ROLE_ATT_WORKING, ROLE_ATT_PRESENT, ROLE_ATT_ABSENT,
             ROLE_ATT_HOLIDAYS, ROLE_WB_TOTAL, ROLE_WB_NET, ROLE_REMARKS, ROLE_INFO, ROLE_UNMAPPED]

ROLE_HELP = {
    ROLE_INCOME: "Earning (shown on the left, only when the employee has an amount)",
    ROLE_LEAVE: "Paid leave amount (details are read from the cell comment)",
    ROLE_INCOME_AFTER: "Earning added after the workbook total",
    ROLE_DEDUCTION: "Deduction taken before the workbook total",
    ROLE_DEDUCTION_AFTER: "Deduction taken after the workbook total (e.g. income tax)",
    ROLE_WORKING_DAY_AMT: "Prorated salary for days worked (shown as 'Basic Salary'; absent deduction is auto-generated)",
    ROLE_BASE_SALARY: "Full monthly gross/base salary (used to compute per-day rate; NOT printed as income)",
    ROLE_ID: "Employee ID", ROLE_NAME: "Employee name", ROLE_PAN: "PAN number",
    ROLE_ATT_WORKING: "Working days", ROLE_ATT_PRESENT: "Present days",
    ROLE_ATT_ABSENT: "Absent days", ROLE_ATT_HOLIDAYS: "Holidays",
    ROLE_WB_TOTAL: "Workbook 'Total Amount' (used only as a cross-check)",
    ROLE_WB_NET: "Workbook net pay (used only as a cross-check)",
    ROLE_REMARKS: "Remarks (shown in preview only)",
    ROLE_INFO: "Reference only - not printed, not added",
    ROLE_UNMAPPED: "Not mapped yet",
}

# Roles for the headers found in the supplied workbook (keys are lower-case, single-spaced headers)
DEFAULT_COLUMN_ROLES: Dict[str, str] = {
    "s.n": ROLE_INFO,
    "employe id": ROLE_ID, "employee id": ROLE_ID, "emp id": ROLE_ID, "id": ROLE_ID,
    "name of employees": ROLE_NAME, "name of employee": ROLE_NAME, "employee name": ROLE_NAME,
    "name": ROLE_NAME,
    "pan no": ROLE_PAN, "pan": ROLE_PAN, "pan number": ROLE_PAN,
    # full monthly base salary (used for per-day rate, not printed as income)
    "gross salary": ROLE_BASE_SALARY, "training salary": ROLE_BASE_SALARY,
    "basic salary": ROLE_BASE_SALARY, "monthly salary": ROLE_BASE_SALARY,
    "gross pay": ROLE_BASE_SALARY,
    # reference-only columns
    "s rate day": ROLE_INFO,
    "s rate night": ROLE_INFO, "day+evening shift no": ROLE_INFO, "night shift no": ROLE_INFO,
    "total no of days/hours": ROLE_INFO, "training days": ROLE_INFO, "ael": ROLE_INFO,
    "tel": ROLE_INFO, "overtime": ROLE_INFO, "daily wage": ROLE_INFO, "expense": ROLE_INFO,
    "absent days": ROLE_ATT_ABSENT, "holidays": ROLE_ATT_HOLIDAYS,
    "present days": ROLE_ATT_PRESENT, "working days": ROLE_ATT_WORKING,
    # prorated salary for days worked → "Basic Salary" on payslip
    "working day amount": ROLE_WORKING_DAY_AMT,
    "paid leave": ROLE_LEAVE,
    "overtime amount": ROLE_INCOME, "pca incentive": ROLE_INCOME,
    "overtime hour amount": ROLE_INCOME, "client visit (hhcr)": ROLE_INCOME,
    "home care": ROLE_INCOME, "previous/due": ROLE_INCOME_AFTER,
    "advance": ROLE_DEDUCTION,
    "ta/la": ROLE_INCOME, "performance allowance": ROLE_INCOME, "rent allowance": ROLE_INCOME,
    "food allowance": ROLE_INCOME, "travelling": ROLE_INCOME, "revenue incentive": ROLE_INCOME,
    "oet incentive": ROLE_INCOME, "carer incentive": ROLE_INCOME, "loyalty allowance": ROLE_INCOME,
    "inconvenience allowance": ROLE_INCOME, "arrears": ROLE_INCOME, "camp incentive": ROLE_INCOME,
    "fixed ssf dedections(11%)": ROLE_DEDUCTION,
    "total amount": ROLE_WB_TOTAL,
    "income tax (1%)": ROLE_DEDUCTION_AFTER,
    "paycheque": ROLE_WB_NET,
    "remarks": ROLE_REMARKS,
}

# Display names printed on the payslip (key = normalised header). Falls back to a tidied header.
DEFAULT_LABELS: Dict[str, str] = {
    "working day amount": "Basic Salary",
    "paid leave": "Paid Leave",
    "pca incentive": "PCA Incentive",
    "client visit (hhcr)": "Client Visit (HHCR)",
    "ta/la": "TA/LA",
    "oet incentive": "OET Incentive",
    "previous/due": "Previous / Due",
    "fixed ssf dedections(11%)": "SSF Deduction",
    "income tax (1%)": "Income Tax (1%)",
    "travelling": "Travelling",
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "firm_name": "copmany name",  # e.g. "Hello Health Polyclinic"
    "firm_address": "",
    "logo_path": "assets/default_logo.png",
    "calendar": "BS",
    "digit_grouping": "nepali",          # 'nepali' (12,34,567.00) or 'international' (1,234,567.00)
    "capitalise_names": True,
    "show_pan_on_payslip": False,
    "show_amount_in_words": True,
    "show_attendance": True,
    "show_signatures": True,
    "tolerance": "0.10",                 # allowed difference (Rs.) when cross-checking workbook totals
    "column_roles": {},                  # user changes, keyed by normalised header
    "labels": {},
}


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_settings() -> Dict[str, Any]:
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                for k, v in stored.items():
                    if k in settings:
                        settings[k] = v
    except (OSError, ValueError):
        pass  # corrupt settings file -> fall back to defaults silently
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    clean = {k: settings.get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    _atomic_write_json(SETTINGS_FILE, clean)


def resolve_logo(settings: Dict[str, Any]) -> Path | None:
    candidates = []
    lp = settings.get("logo_path")
    if lp:
        p = Path(lp)
        candidates.append(p if p.is_absolute() else BASE_DIR / p)
    candidates.append(DEFAULT_LOGO)
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def resolve_site_logo() -> Path | None:
    """Return the fixed website logo, independent of the uploaded payslip logo."""
    return SITE_LOGO if SITE_LOGO.is_file() else None


def effective_roles(settings: Dict[str, Any]) -> Dict[str, str]:
    roles = dict(DEFAULT_COLUMN_ROLES)
    roles.update({norm_header(k): v for k, v in settings.get("column_roles", {}).items()
                  if v in ALL_ROLES})
    return roles


def guess_role(header_key: str) -> str:
    """For headers we have never seen: a conservative suggestion the user can change."""
    h = header_key
    if re.search(r"\bname\b", h):
        return ROLE_NAME
    if re.search(r"\b(emp(loyee)?|staff)\b.*\bid\b|^id$", h):
        return ROLE_ID
    if re.search(r"\bpan\b", h):
        return ROLE_PAN
    if re.search(r"\bworking\s*day\s*(amount|pay|salary)\b|^wda$", h):
        return ROLE_WORKING_DAY_AMT
    if re.search(r"\b(gross|training|monthly)\s*(salary|pay)\b|^basic\s*(salary|pay)$", h):
        return ROLE_BASE_SALARY
    if re.search(r"tax|tds|income tax", h):
        return ROLE_DEDUCTION_AFTER
    if re.search(r"deduct|dedect|ssf|\bpf\b|provident|advance|loan|fine|penalt", h):
        return ROLE_DEDUCTION
    if re.search(r"allowance|incentive|bonus|arrear|commission|overtime amount|ot amount", h):
        return ROLE_INCOME
    if re.search(r"remark|note", h):
        return ROLE_REMARKS
    return ROLE_UNMAPPED


def display_label(header_raw: str, settings: Dict[str, Any]) -> str:
    key = norm_header(header_raw)
    custom = {norm_header(k): v for k, v in settings.get("labels", {}).items()}
    if key in custom and custom[key].strip():
        return custom[key].strip()
    if key in DEFAULT_LABELS:
        return DEFAULT_LABELS[key]
    text = re.sub(r"\s+", " ", str(header_raw).replace("\xa0", " ")).strip()
    if text.isupper() and len(text) > 5:
        text = text.title()
    words = [(w[0].upper() + w[1:]) if w and w[0].islower() else w for w in text.split(" ")]
    return " ".join(words)
