"""Reading Excel notes / threaded comments and turning paid-leave comments into entries."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Tuple

from .util import clean_text, parse_amount_text

_THREAD_MARK = re.compile(r"(?:^|\n)\s*(Comment|Reply):\s*\n", re.I)


def clean_comment(text: Optional[str]) -> str:
    """Remove Excel's boilerplate from threaded comments and return only what the person wrote."""
    if not text:
        return ""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    if "[Threaded comment]" in t or _THREAD_MARK.search(t):
        parts = re.findall(r"(?:Comment|Reply):\s*\n(.*?)(?=\n\s*(?:Comment|Reply):\s*\n|\Z)", t,
                           flags=re.S | re.I)
        if parts:
            t = "\n".join(p.strip() for p in parts if p.strip())
        else:
            t = re.sub(r"\[Threaded comment\].*?(?:linkid=\d+)\s*", "", t, flags=re.S)
    t = t.replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


# ----------------------------------------------------------------------------- parsing
_CUR = r"(?:rs\.?|npr|nrs\.?|inr|रु\.?)"
_AMOUNT_RE = re.compile(rf"(?<![\w.,/\-])(?:{_CUR}\s*)?(\d[\d,]*(?:\.\d+)?)(?:\s*/-)?(?![\w/])", re.I)
_SPLIT_RE = re.compile(r"[\n;|]+|,(?!\d{3}(?!\d))")
_DAYCOUNT_RE = re.compile(r"^\s*(?:days?|din)\b", re.I)
# matches "N days" / "N.5 din" patterns for per-day-rate conversion
_DAYCOUNT_PAT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:days?|din)\b", re.I)


def tidy_label(text: str) -> str:
    t = clean_text(text)
    t = re.sub(r"^[\s:=\-–—.,()]+|[\s:=\-–—.,()]+$", "", t)
    words = [(w[0].upper() + w[1:]) if w and w[0].islower() else w for w in t.split(" ")]
    return " ".join(words)


@dataclass
class Segment:
    raw: str
    label: str = ""
    amount: Optional[Decimal] = None
    days: Optional[Decimal] = None   # day count from "N days/din" pattern
    problem: str = ""        # non-empty -> segment could not be read safely


@dataclass
class ParsedLeave:
    status: str                          # none | names_only | days_only | amounts | mixed | ambiguous | conflict
    text: str = ""                       # cleaned comment text
    names: List[str] = field(default_factory=list)
    entries: List[Tuple[str, Decimal]] = field(default_factory=list)
    days_entries: List[Tuple[str, Decimal]] = field(default_factory=list)  # (label, day_count)
    problems: List[str] = field(default_factory=list)

    @property
    def amount_total(self) -> Decimal:
        return sum((a for _, a in self.entries), Decimal(0))


def _parse_segment(raw: str) -> Optional[Segment]:
    s = clean_text(raw)
    if not s:
        return None

    # ---- day-count pattern first: "Earned Leave 2 days", "Sick Leave 1.5 din"
    day_m = _DAYCOUNT_PAT.search(s)
    if day_m:
        # Verify no explicit monetary amount exists elsewhere in the text
        rest = s[:day_m.start()] + " " + s[day_m.end():]
        monetary_in_rest = [
            m for m in _AMOUNT_RE.finditer(rest)
            if re.match(rf"\s*{_CUR}", m.group(0), re.I)  # only currency-prefixed counts
               or not _DAYCOUNT_RE.match(rest[m.end():])
        ]
        if not monetary_in_rest:
            label = tidy_label(rest)
            try:
                return Segment(raw=s, label=label or "Paid Leave", days=Decimal(day_m.group(1)))
            except Exception:
                pass  # fall through to normal parsing

    # ---- monetary amount parsing (original logic)
    matches = list(_AMOUNT_RE.finditer(s))
    # numbers followed by "days" are day counts, not money (unless a currency is written)
    real = []
    for m in matches:
        has_cur = re.match(rf"\s*{_CUR}", m.group(0), re.I) is not None
        if not has_cur and _DAYCOUNT_RE.match(s[m.end():]):
            continue
        real.append(m)
    if not real:
        return Segment(raw=s, label=tidy_label(s))
    if len(real) > 1:
        return Segment(raw=s, label=tidy_label(s),
                       problem=f"more than one amount in '{s}'")
    m = real[0]
    amount = parse_amount_text(m.group(1))
    label = tidy_label((s[:m.start()] + " " + s[m.end():]))
    if amount is None:
        return Segment(raw=s, label=tidy_label(s), problem=f"could not read the amount in '{s}'")
    return Segment(raw=s, label=label or "Paid Leave", amount=amount)


def parse_leave_comment(text: Optional[str]) -> ParsedLeave:
    """Interpret a paid-leave comment.

    Accepts lines such as 'Earned Leave 500', 'Earned Leave: 500', 'Earned Leave = Rs. 500',
    'Earned Leave: NPR 500', several entries on separate lines or separated by ; or , and
    comments that only name the reason ('camp replacement, restricted holiday').
    Also supports day-count style: 'Earned Leave 2 days; Sick Leave 1 day' which will be
    converted to amounts by calc.py using the employee's per-day rate.
    """
    cleaned = clean_comment(text)
    if not cleaned:
        return ParsedLeave(status="none")
    segments: List[Segment] = []
    for piece in _SPLIT_RE.split(cleaned):
        # split name-only pieces joined by 'and' / '&'
        if not _AMOUNT_RE.search(piece):
            subs = re.split(r"\s+(?:and|&)\s+", piece, flags=re.I)
        else:
            subs = [piece]
        for sub in subs:
            seg = _parse_segment(sub)
            if seg:
                segments.append(seg)
    if not segments:
        return ParsedLeave(status="none", text=cleaned)

    problems = [f"Cannot read safely: {s.problem}" for s in segments if s.problem]
    if problems:
        return ParsedLeave(status="ambiguous", text=cleaned, problems=problems,
                           names=[s.label for s in segments if s.label])

    with_amt = [s for s in segments if s.amount is not None]
    with_days = [s for s in segments if s.days is not None]
    without = [s for s in segments if s.amount is None and s.days is None]

    # ---- all entries are day-count based (no monetary amounts)
    if with_days and not with_amt:
        return ParsedLeave(
            status="days_only",
            text=cleaned,
            names=[s.label for s in segments if s.label],
            days_entries=[(s.label, s.days) for s in with_days],
        )

    if not with_amt:
        return ParsedLeave(status="names_only", text=cleaned, names=[s.label for s in without])
    if without:
        return ParsedLeave(
            status="mixed", text=cleaned,
            names=[s.label for s in segments],
            entries=[(s.label, s.amount) for s in with_amt],
            problems=["Some entries have an amount and some do not: "
                      + ", ".join(s.label for s in without)])
    # all have amounts: detect conflicting repeats of the same label
    seen = {}
    for s in with_amt:
        key = s.label.lower()
        if key in seen:
            same = "twice with the same amount" if seen[key] == s.amount else \
                f"with different amounts ({seen[key]} and {s.amount})"
            return ParsedLeave(status="conflict", text=cleaned,
                               entries=[(x.label, x.amount) for x in with_amt],
                               problems=[f"'{s.label}' appears {same}; it may be entered twice"])
        seen[key] = s.amount
    return ParsedLeave(status="amounts", text=cleaned,
                       names=[s.label for s in with_amt],
                       entries=[(s.label, s.amount) for s in with_amt])
