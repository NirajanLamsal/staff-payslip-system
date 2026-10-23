"""Salary-month handling. Bikram Sambat (Nepali) months are kept as BS - never converted."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

BS_MONTHS = ["Baisakh", "Jestha", "Ashadh", "Shrawan", "Bhadra", "Ashwin",
             "Kartik", "Mangsir", "Poush", "Magh", "Falgun", "Chaitra"]
AD_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]

_BS_ALIASES = {
    0: ["baisakh", "baishakh", "baisak", "vaisakh", "baishak"],
    1: ["jestha", "jeth", "jyestha", "jaistha", "jyeshtha"],
    2: ["ashadh", "asadh", "asar", "ashar", "ashad", "asaar"],
    3: ["shrawan", "shravan", "sawan", "saun", "srawan", "shrawon"],
    4: ["bhadra", "bhadau", "bhadra", "bhadrapad"],
    5: ["ashwin", "aswin", "asoj", "ashoj", "ashwayuj", "asuj"],
    6: ["kartik", "kattik", "kartic", "kaartik"],
    7: ["mangsir", "mangshir", "marg", "margashirsha", "manshir"],
    8: ["poush", "push", "pous", "paush"],
    9: ["magh", "mag", "maagh"],
    10: ["falgun", "phalgun", "fagun", "phagun", "falgoon"],
    11: ["chaitra", "chait", "chaitr", "chaitra"],
}
_AD_ALIASES = {i: [m.lower(), m.lower()[:3]] for i, m in enumerate(AD_MONTHS)}
_AD_ALIASES[8].append("sept")

CAL_BS = "BS"
CAL_AD = "AD"


@dataclass
class SalaryMonth:
    calendar: str   # "BS" or "AD"
    year: int
    month: int      # 1..12

    @property
    def name(self) -> str:
        return (BS_MONTHS if self.calendar == CAL_BS else AD_MONTHS)[self.month - 1]

    @property
    def label(self) -> str:
        """Text printed on the payslip, e.g. 'Bhadra 2083'."""
        return f"{self.name} {self.year}"

    @property
    def code(self) -> str:
        """Used in filenames / folders, e.g. '2083-05'."""
        return f"{self.year}-{self.month:02d}"


def month_names(calendar: str) -> List[str]:
    return BS_MONTHS if calendar == CAL_BS else AD_MONTHS


def _find_month(text: str, aliases) -> Optional[int]:
    words = re.findall(r"[a-z]+", text.lower())
    # prefer longest alias match to avoid 'mag' matching inside other words
    for idx, names in aliases.items():
        for w in words:
            if w in names:
                return idx
    return None


def detect_month(*texts: str) -> Tuple[Optional[SalaryMonth], str]:
    """Best-effort detection from sheet / file names such as 'bhadra 8384' or 'Salary_83_84'.
    Returns (SalaryMonth or None, explanation). Never guesses from today's date."""
    joined = " ".join(t for t in texts if t)
    bs_idx = _find_month(joined, _BS_ALIASES)
    ad_idx = _find_month(joined, _AD_ALIASES) if bs_idx is None else None
    if bs_idx is None and ad_idx is None:
        return None, "No month name found in the sheet or file name."

    if bs_idx is not None:
        m = re.search(r"(?<!\d)(20\d{2}|19\d{2})(?!\d)", joined)
        if m and not re.search(r"(?<!\d)\d{2}[\s_\-/]?\d{2}(?!\d)", joined.replace(m.group(1), "")):
            return SalaryMonth(CAL_BS, int(m.group(1)), bs_idx + 1), \
                f"Detected {BS_MONTHS[bs_idx]} {m.group(1)} from the sheet/file name."
        # fiscal-year pattern: 8384, 83_84, 83-84, 2083-84
        for fm in re.finditer(r"(?<!\d)(?:20)?(\d{2})[\s_\-/]?(?:20)?(\d{2})(?!\d)", joined):
            a, b = int(fm.group(1)), int(fm.group(2))
            if b == (a + 1) % 100:
                fy_start = 2000 + a
                # Nepali fiscal year runs Shrawan (4th month) -> Ashadh (3rd month)
                year = fy_start if bs_idx >= 3 else fy_start + 1
                return SalaryMonth(CAL_BS, year, bs_idx + 1), (
                    f"Detected {BS_MONTHS[bs_idx]} of fiscal year {fy_start}/{b:02d} "
                    f"-> {BS_MONTHS[bs_idx]} {year}. Please confirm.")
        if m:
            return SalaryMonth(CAL_BS, int(m.group(1)), bs_idx + 1), \
                f"Detected {BS_MONTHS[bs_idx]} {m.group(1)}."
        return SalaryMonth(CAL_BS, 0, bs_idx + 1), \
            f"Detected month {BS_MONTHS[bs_idx]} but no year - please enter the year."

    m = re.search(r"(?<!\d)(20\d{2})(?!\d)", joined)
    year = int(m.group(1)) if m else 0
    return SalaryMonth(CAL_AD, year, ad_idx + 1), (
        f"Detected {AD_MONTHS[ad_idx]}" + (f" {year}." if year else " but no year - please enter the year."))
