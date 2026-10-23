"""Small helpers: money handling, number formatting, names and filenames."""
from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

CENT = Decimal("0.01")


class UserError(Exception):
    """An error whose message is safe and meant to be shown to the person using the app."""


# --------------------------------------------------------------------------- money
def to_decimal(value: Any) -> Optional[Decimal]:
    """Convert a spreadsheet number to Decimal. Returns None for blanks / non numbers."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return Decimal(str(value))
    return None


def parse_amount_text(text: str) -> Optional[Decimal]:
    """Parse text such as '1,500', 'Rs. 1,500.50', 'NPR 500', '500/-'. None if not an amount."""
    t = text.replace("\xa0", " ").strip()
    t = re.sub(r"^(?:rs\.?|npr|nrs\.?|रु\.?)\s*", "", t, flags=re.I)
    t = re.sub(r"\s*/-\s*$", "", t)
    t = t.replace(",", "").strip()
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", t):
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def money(value: Decimal) -> Decimal:
    """Round to paisa (2 decimals), halves rounded up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def group_digits(int_part: str, grouping: str) -> str:
    if grouping == "international" or len(int_part) <= 3:
        out = []
        while int_part:
            out.append(int_part[-3:])
            int_part = int_part[:-3]
        return ",".join(reversed(out)) if out else "0"
    head, tail = int_part[:-3], int_part[-3:]
    parts = []
    while head:
        parts.append(head[-2:])
        head = head[:-2]
    return ",".join(list(reversed(parts)) + [tail])


def fmt_amount(value: Decimal, grouping: str = "nepali", prefix: str = "Rs. ") -> str:
    """Format as 'Rs. 12,34,567.89' (Nepali/Indian grouping) or 'Rs. 1,234,567.89'."""
    v = money(value)
    neg = v < 0
    s = f"{abs(v):.2f}"
    int_part, dec = s.split(".")
    text = f"{prefix}{group_digits(int_part, grouping)}.{dec}"
    return f"-{text}" if neg else text


def fmt_number(value: Decimal) -> str:
    """Plain number for attendance etc.: 27, 4.5"""
    if value == value.to_integral_value():
        return str(int(value))
    return f"{value.normalize():f}"


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_1000(n: int) -> str:
    words = []
    if n >= 100:
        words.append(_ONES[n // 100] + " Hundred")
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else ""))
    elif n > 0:
        words.append(_ONES[n])
    return " ".join(words)


def int_to_words(n: int) -> str:
    """South-Asian numbering: thousand, lakh, crore."""
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(int_to_words(crore) + " Crore")
    if lakh:
        parts.append(_below_1000(lakh) + " Lakh")
    if thousand:
        parts.append(_below_1000(thousand) + " Thousand")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


def amount_in_words(value: Decimal) -> str:
    v = money(abs(value))
    rupees = int(v)
    paisa = int((v - rupees) * 100)
    text = "Rupees " + int_to_words(rupees)
    if paisa:
        text += " and " + int_to_words(paisa) + " Paisa"
    return ("Minus " if value < 0 else "") + text + " Only"


# --------------------------------------------------------------------------- text
def clean_text(value: Any) -> str:
    """Strip, convert NBSP to space, collapse inner whitespace."""
    if value is None:
        return ""
    s = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm_header(value: Any) -> str:
    return clean_text(value).lower()


def capitalise_words(text: str) -> str:
    """Capitalise words that start with a lowercase letter; preserve existing capitals."""
    out = []
    for w in text.split(" "):
        if w and w[0].islower():
            out.append(w[0].upper() + w[1:])
        else:
            out.append(w)
    return " ".join(out)


def tidy_name(raw: Any, capitalise: bool = True) -> str:
    name = clean_text(raw)
    return capitalise_words(name) if capitalise else name


def tidy_id(raw: Any) -> str:
    """'EI_ 24' -> 'EI_24' (whitespace inside an identifier is never meaningful)."""
    if raw is None:
        return ""
    if isinstance(raw, float) and raw == int(raw):
        raw = int(raw)
    return re.sub(r"\s+", "", str(raw).replace("\xa0", " "))


def safe_filename(text: str, max_len: int = 80) -> str:
    s = unicodedata.normalize("NFKC", text)
    s = re.sub(r"[^\w\-.]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("._-")
    return (s[:max_len].strip("._-")) or "payslip"


def column_letter(idx: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(idx)
