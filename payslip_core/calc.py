"""Turning raw workbook rows into payslip data, with validation. Pure functions, no UI, no disk."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import config as cfg
from .comments import parse_leave_comment
from .fonts import unsupported_chars
from .models import (Cell, ColumnInfo, ERROR, Flag, INFO, LeaveInfo, Line, Payslip, RawRow, SheetData,
                     WARNING)
from .util import fmt_amount, fmt_number, money, parse_amount_text, tidy_id, tidy_name, to_decimal

# types accepted for manual extra lines
EXTRA_INCOME, EXTRA_DEDUCTION, EXTRA_TAX = "Income", "Deduction", "Tax / after-total deduction"
EXTRA_TYPES = [EXTRA_INCOME, EXTRA_DEDUCTION, EXTRA_TAX]


def read_amount(cell: Optional[Cell]) -> Tuple[Optional[Decimal], str]:
    """(amount, problem). Blank -> (None, ''). A problem string means the cell could not be read."""
    if cell is None:
        return None, ""
    if cell.is_error:
        return None, f"shows an Excel error ({cell.value})"
    v = cell.value
    if v is None:
        if cell.formula:
            return None, "has a formula but no stored result (open and save the workbook in Excel first)"
        return None, ""
    d = to_decimal(v)
    if d is not None:
        return d, ""
    if isinstance(v, str):
        t = v.strip()
        if not t:
            return None, ""
        d = parse_amount_text(t)
        if d is not None:
            return d, ""
        return None, f"contains the text '{t[:40]}' instead of a number"
    return None, "contains a value that is not a number"


def _row_has_income(raw: RawRow, income_cols: Sequence[ColumnInfo]) -> bool:
    for c in income_cols:
        d, _ = read_amount(raw.cells.get(c.index))
        if d:
            return True
    return False


def _process_leave(col: ColumnInfo, cell: Cell, amount: Optional[Decimal], override,
                   tol: Decimal, flags: List[Flag],
                   per_day_rate: Optional[Decimal] = None) -> Tuple[LeaveInfo, List[Line]]:
    parsed = parse_leave_comment(cell.comment)
    info = LeaveInfo(cell_amount=amount, comment=parsed.text, status=parsed.status,
                     parsed=list(parsed.entries))
    base = col.label
    where = f"{col.letter}"
    cell_paid = amount is not None and amount != 0

    if override:
        lines = [Line(lab, money(a), "edited") for lab, a in override]
        info.source, info.used = "edited in the app", lines
        total = sum((l.amount for l in lines), Decimal(0))
        if amount is not None and abs(total - amount) > tol:
            flags.append(Flag(ERROR, f"Edited paid-leave entries add up to {fmt_amount(total)} but the "
                                     f"workbook's {base} cell says {fmt_amount(amount)}.", "leave_edit_mismatch"))
        elif amount is None:
            flags.append(Flag(WARNING, f"Paid-leave entries were added by hand ({fmt_amount(total)}) but the "
                                       f"workbook's {base} cell is blank.", "leave_edit_blank"))
        return info, lines

    def single(label: str, source: str) -> List[Line]:
        return [Line(label, money(amount), where)]

    # ---- day-count entries: "Earned Leave 2 days; Sick Leave 1 day" x per_day_rate
    if parsed.days_entries and per_day_rate is not None and per_day_rate > 0:
        entries = [Line(lab, money(Decimal(str(days)) * per_day_rate), "comment")
                   for lab, days in parsed.days_entries]
        total = sum(l.amount for l in entries)
        info.source = f"day counts from comment × per-day rate ({fmt_amount(per_day_rate)}/day)"
        info.used = entries
        info.parsed = [(lab, money(Decimal(str(days)) * per_day_rate)) for lab, days in parsed.days_entries]
        if cell_paid and abs(total - amount) > tol:
            flags.append(Flag(INFO,
                f"The {base} comment lists {fmt_amount(total)} from day counts but the cell says "
                f"{fmt_amount(amount)}. Day-count amounts were used.", "leave_day_rate_mismatch"))
        elif not cell_paid and total:
            flags.append(Flag(WARNING,
                f"Paid leave of {fmt_amount(total)} was calculated from the comment day counts, "
                f"but the {base} cell is blank.", "leave_from_comment"))
        return info, entries

    st = parsed.status
    if st == "none":
        if cell_paid:
            info.source = "workbook cell"
            info.used = single(base, "cell")
    elif st == "names_only":
        if cell_paid:
            label = f"{base} ({', '.join(parsed.names)})"
            info.source = "workbook cell amount + reasons from the comment"
            info.used = single(label, "cell")
            flags.append(Flag(INFO, f"The {base} comment lists reasons without amounts "
                                    f"({', '.join(parsed.names)}); printed as one line using the amount in the cell. "
                                    "Use 'Edit paid-leave entries' to split it.", "leave_names_only"))
        else:
            flags.append(Flag(INFO, f"The {base} comment names {', '.join(parsed.names)} but no amount "
                                    "is entered, so nothing was added.", "leave_names_no_amount"))
    elif st == "days_only":
        # day counts present but per_day_rate was None (handled above when rate is known)
        if cell_paid:
            names_str = ", ".join(parsed.names) if parsed.names else ""
            label = f"{base} ({names_str})" if names_str else base
            info.source = "workbook cell amount (day counts in comment; per-day rate not yet available)"
            info.used = single(label, "cell")
            flags.append(Flag(INFO, f"The {base} comment has day counts ({names_str}); the cell amount was "
                              "used because the per-day rate could not be determined. "
                              "Add a Gross Salary column to enable automatic splitting.",
                              "leave_day_no_rate"))
        else:
            flags.append(Flag(INFO, f"The {base} comment has day counts ({', '.join(parsed.names)}) "
                              "but no amount is entered, so nothing was added.", "leave_names_no_amount"))
    elif st == "amounts":
        total = parsed.amount_total
        entries = [Line(lab, money(a), "comment") for lab, a in parsed.entries]
        if cell_paid:
            if abs(total - amount) <= Decimal("0.01"):
                info.source = "itemised from the comment (matches the cell, counted once)"
                info.used = entries
            else:
                info.source = "workbook cell amount (comment disagrees)"
                info.used = single(base, "cell")
                flags.append(Flag(ERROR, f"The {base} comment lists {fmt_amount(total)} "
                                         f"({', '.join(f'{l} {fmt_amount(a)}' for l, a in parsed.entries)}) but the cell "
                                         f"says {fmt_amount(amount)}. The cell amount was used - please review.",
                                  "leave_amount_mismatch"))
        else:
            info.source = "comment only (cell is blank)"
            info.used = entries
            flags.append(Flag(WARNING, f"Paid leave of {fmt_amount(total)} was read from the comment, but the "
                                       f"{base} cell is blank, so the workbook's own total does not include it.",
                              "leave_from_comment"))
    else:   # mixed | ambiguous | conflict
        for p in parsed.problems:
            flags.append(Flag(ERROR, f"{base} comment: {p}. Please review or correct it.", "leave_ambiguous"))
        if cell_paid:
            info.source = "workbook cell amount (comment not understood)"
            info.used = single(base, "cell")
    return info, info.used


def build_payslips(sheet: SheetData, settings: Dict[str, Any],
                   leave_overrides: Optional[Dict[int, List[Tuple[str, Decimal]]]] = None,
                   extra_lines: Optional[List[Dict[str, Any]]] = None) -> List[Payslip]:
    leave_overrides = leave_overrides or {}
    extras: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for e in extra_lines or []:
        extras[int(e["row"])].append(e)
    tol = Decimal(str(settings.get("tolerance", "0.10")))
    capitalise = bool(settings.get("capitalise_names", True))

    cols = sheet.columns
    by_role: Dict[str, List[ColumnInfo]] = defaultdict(list)
    for c in cols:
        by_role[c.role].append(c)
    income_like = (by_role[cfg.ROLE_INCOME] + by_role[cfg.ROLE_LEAVE]
                   + by_role[cfg.ROLE_INCOME_AFTER] + by_role[cfg.ROLE_WORKING_DAY_AMT])

    # ---- statistics across all employees (used for 'blank where most are filled' checks)
    n_with_income = 0
    filled_after: Counter = Counter()
    total_formula = Counter()
    for raw in sheet.rows:
        if _row_has_income(raw, income_like):
            n_with_income += 1
            for c in by_role[cfg.ROLE_DEDUCTION_AFTER]:
                d, _ = read_amount(raw.cells.get(c.index))
                if d:
                    filled_after[c.index] += 1
        for c in by_role[cfg.ROLE_WB_TOTAL]:
            cl = raw.cells.get(c.index)
            if cl and cl.value is not None:
                total_formula[(c.index, bool(cl.formula))] += 1

    def first_value(raw: RawRow, role: str):
        for c in by_role[role]:
            v = raw.cells[c.index].value
            if v is not None:
                return v
        return None

    id_counts = Counter(tidy_id(first_value(r, cfg.ROLE_ID)).upper() for r in sheet.rows
                        if tidy_id(first_value(r, cfg.ROLE_ID)))
    name_counts = Counter(tidy_name(first_value(r, cfg.ROLE_NAME), capitalise).lower() for r in sheet.rows
                          if first_value(r, cfg.ROLE_NAME) is not None)

    slips: List[Payslip] = []
    for raw in sheet.rows:
        r = raw.row
        cells = raw.cells
        flags: List[Flag] = []
        notes: List[str] = []
        income: List[Line] = []
        deductions: List[Line] = []
        pre_income = Decimal(0)
        pre_ded = Decimal(0)

        # ---- identity
        name_raw = first_value(raw, cfg.ROLE_NAME)
        name = tidy_name(name_raw, capitalise)
        emp_id = tidy_id(first_value(raw, cfg.ROLE_ID))
        pan_val = first_value(raw, cfg.ROLE_PAN)
        pan = tidy_id(pan_val)
        include_default = True
        if not name:
            flags.append(Flag(ERROR, "The employee name is missing.", "no_name"))
            name = f"(Row {r})"
            include_default = False
        else:
            bad = unsupported_chars(name)
            if bad:
                flags.append(Flag(ERROR, f"The name contains characters the PDF font cannot print ({bad}). "
                                         "Please write the name in English letters in the workbook.", "font"))
            if name_counts[name.lower()] > 1:
                flags.append(Flag(WARNING, "Another employee has the same name.", "dup_name"))
        if not emp_id:
            flags.append(Flag(WARNING, "The employee ID is missing.", "no_id"))
        elif id_counts[emp_id.upper()] > 1:
            flags.append(Flag(ERROR, f"The employee ID '{emp_id}' is used by more than one row.", "dup_id"))

        # ---- attendance
        att: Dict[str, Optional[Decimal]] = {}
        for role, label in ((cfg.ROLE_ATT_WORKING, "Working Days"), (cfg.ROLE_ATT_PRESENT, "Present Days"),
                            (cfg.ROLE_ATT_ABSENT, "Absent Days"), (cfg.ROLE_ATT_HOLIDAYS, "Holidays")):
            for c in by_role[role]:
                d, _ = read_amount(cells.get(c.index))
                if d is not None:
                    att[label] = d
                    break
        attendance: List[Tuple[str, str]] = []
        if "Working Days" in att:
            attendance.append(("Working Days", fmt_number(att["Working Days"])))
        if "Present Days" in att:
            attendance.append(("Present Days", fmt_number(att["Present Days"])))
            attendance.append(("Absent Days", fmt_number(att.get("Absent Days", Decimal(0)))))
        elif "Absent Days" in att:
            attendance.append(("Absent Days", fmt_number(att["Absent Days"])))
        if "Holidays" in att:
            attendance.append(("Holidays", fmt_number(att["Holidays"])))

        # ---- per-day rate pre-pass (needed before processing leave and working day amount)
        working_days_n: Optional[Decimal] = att.get("Working Days")
        present_days_n: Optional[Decimal] = att.get("Present Days")
        absent_days_n: Decimal = att.get("Absent Days") or Decimal(0)

        # Read base salary (full monthly, e.g. from 'Gross Salary' column)
        base_salary_val: Optional[Decimal] = None
        for _c in by_role[cfg.ROLE_BASE_SALARY]:
            _d, _ = read_amount(cells.get(_c.index))
            if _d and _d > 0:
                base_salary_val = _d
                break

        # Read working day amount (prorated, e.g. from 'Working Day Amount' column)
        working_day_amt_val: Optional[Decimal] = None
        for _c in by_role[cfg.ROLE_WORKING_DAY_AMT]:
            _d, _ = read_amount(cells.get(_c.index))
            if _d is not None:
                working_day_amt_val = _d
                break

        # Compute per-day rate: prefer base_salary / working_days, fallback to wda / present_days
        per_day_rate: Optional[Decimal] = None
        if base_salary_val and working_days_n and working_days_n > 0:
            per_day_rate = money(base_salary_val / working_days_n)
        elif working_day_amt_val and working_day_amt_val > 0 and present_days_n and present_days_n > 0:
            per_day_rate = money(working_day_amt_val / present_days_n)

        # Flag to track whether we've written a working-day-amount income line
        wda_processed = False
        zero_omitted: List[str] = []
        leave_infos: List[LeaveInfo] = []
        unmapped: List[str] = []
        for col in cols:
            cell = cells[col.index]
            role = col.role
            where = f"{col.letter}{r}"
            # ---- base salary column: used only for per-day rate (not printed)
            if role == cfg.ROLE_BASE_SALARY:
                continue

            # ---- working day amount: show as "Basic Salary" (full = prorated + absent top-up)
            elif role == cfg.ROLE_WORKING_DAY_AMT:
                amount, issue = read_amount(cell)
                if issue:
                    flags.append(Flag(ERROR, f"{col.label} (cell {where}) {issue}.", "bad_amount"))
                    continue
                if amount is None or amount == 0:
                    if amount == 0:
                        zero_omitted.append(col.label)
                    continue
                # Reconstruct full monthly basic salary by adding absent days back
                if per_day_rate and per_day_rate > 0 and absent_days_n > 0:
                    basic_full = money(amount + money(absent_days_n * per_day_rate))
                else:
                    basic_full = amount
                income.append(Line(col.label, basic_full, col.letter))
                pre_income += basic_full
                wda_processed = True
                continue

            elif role in (cfg.ROLE_INCOME, cfg.ROLE_LEAVE, cfg.ROLE_INCOME_AFTER,
                          cfg.ROLE_DEDUCTION, cfg.ROLE_DEDUCTION_AFTER):
                amount, issue = read_amount(cell)
                if issue:
                    flags.append(Flag(ERROR, f"{col.label} (cell {where}) {issue}.", "bad_amount"))
                    if role == cfg.ROLE_LEAVE:
                        # still read the comment so the person can see it
                        leave_infos.append(LeaveInfo(comment=parse_leave_comment(cell.comment).text))
                    continue
                if role == cfg.ROLE_LEAVE:
                    info, lines = _process_leave(col, cell, amount, leave_overrides.get(r), tol, flags,
                                                 per_day_rate)
                    leave_infos.append(info)
                    income.extend(lines)
                    pre_income += sum((l.amount for l in lines), Decimal(0))
                    if amount is not None and amount < 0:
                        flags.append(Flag(WARNING, f"{col.label} (cell {where}) is negative.", "negative"))
                    continue
                if amount is None or amount == 0:
                    if amount == 0:
                        zero_omitted.append(col.label)
                    if cell.comment:
                        flags.append(Flag(WARNING, f"{col.label} (cell {where}) has a note ('{cell.comment[:80]}') "
                                                   "but no amount, so nothing was added. Check whether it is due.",
                                          "note_no_amount"))
                    continue
                line = Line(col.label, money(amount), col.letter)
                if amount < 0:
                    flags.append(Flag(WARNING, f"{col.label} (cell {where}) is negative ({fmt_amount(amount)}); "
                                               "it is shown as entered.", "negative"))
                if cell.comment:
                    notes.append(f"{col.label} ({where}): {cell.comment}")
                if role in (cfg.ROLE_INCOME, cfg.ROLE_INCOME_AFTER):
                    income.append(line)
                    if role == cfg.ROLE_INCOME:
                        pre_income += line.amount
                else:
                    deductions.append(line)
                    if role == cfg.ROLE_DEDUCTION:
                        pre_ded += line.amount
            elif role == cfg.ROLE_UNMAPPED:
                if cell.value is not None:
                    unmapped.append(f"{col.header} = {str(cell.value)[:30]}")
            elif role == cfg.ROLE_REMARKS:
                if cell.value is not None:
                    text = str(cell.value).strip()
                    notes.append(f"Remarks ({where}): {text}")
                    if re.search(r"\d", text):
                        flags.append(Flag(WARNING, f"Remarks mention a number ('{text[:60]}'); it was not added to "
                                                   "the payslip. Check whether it is a payment.", "remarks_number"))
            elif role == cfg.ROLE_INFO:
                if isinstance(cell.value, str) and cell.value.strip():
                    notes.append(f"{col.header} ({where}): {cell.value.strip()}")
                if cell.comment:
                    notes.append(f"{col.header} ({where}): {cell.comment}")
            elif role in (cfg.ROLE_ID, cfg.ROLE_NAME, cfg.ROLE_PAN) or role.startswith("att_") \
                    or role in (cfg.ROLE_WB_TOTAL, cfg.ROLE_WB_NET):
                if cell.comment and role not in (cfg.ROLE_ID, cfg.ROLE_NAME):
                    notes.append(f"{col.header} ({where}): {cell.comment}")

        # ---- auto absent deduction (balances the Basic Salary top-up; keeps cross-check intact)
        if wda_processed and per_day_rate and per_day_rate > 0 and absent_days_n > 0:
            absent_amt = money(absent_days_n * per_day_rate)
            day_word = "Day" if absent_days_n == 1 else "Days"
            abs_label = f"Absent ({fmt_number(absent_days_n)} {day_word})"
            deductions.append(Line(abs_label, absent_amt, "absent_calc"))
            pre_ded += absent_amt

        if zero_omitted:
            flags.append(Flag(INFO, "Amounts entered as 0 were left out: " + ", ".join(zero_omitted) + ".", "zero"))
        if unmapped:
            flags.append(Flag(WARNING, "Values found in columns that are not mapped (not printed, not added): "
                                       + "; ".join(unmapped) + ".", "unmapped"))

        # ---- manual extra lines entered in the app
        for e in extras.get(r, []):
            amt = to_decimal(e.get("amount"))
            label = str(e.get("label") or "").strip()
            if amt is None or not label or amt == 0:
                continue
            line = Line(label, money(amt), "manual")
            kind = e.get("type")
            if kind == EXTRA_INCOME:
                income.append(line)
                pre_income += line.amount
            elif kind == EXTRA_DEDUCTION:
                deductions.append(line)
                pre_ded += line.amount
            else:
                deductions.append(line)
            flags.append(Flag(INFO, f"Line added by hand: {label} ({kind}) {fmt_amount(amt)}.", "manual"))

        slip = Payslip(row=r, emp_id=emp_id, name=name, pan=pan, attendance=attendance, income=income,
                       deductions=deductions, flags=flags, notes=notes, leave=leave_infos)
        slip.calc_total_before_tax = pre_income - pre_ded

        if not income:
            flags.append(Flag(ERROR, "No salary or allowance amounts were found for this employee, "
                                     "so there is nothing to pay. Excluded by default.", "no_salary"))
            include_default = False

        # ---- tax blank where most employees have it
        if income and n_with_income:
            for c in by_role[cfg.ROLE_DEDUCTION_AFTER]:
                d, _ = read_amount(cells.get(c.index))
                if not d and filled_after[c.index] / n_with_income >= 0.6 \
                        and not any(l.source in (c.letter, "manual") and l.label == c.label for l in deductions):
                    flags.append(Flag(WARNING, f"{c.label} is blank for this employee although it is filled for "
                                               f"{filled_after[c.index]} of {n_with_income} employees. No such "
                                               "deduction is shown on this payslip.", "deduction_blank"))

        # ---- cross-check with the workbook's own totals
        wb_total = wb_net = None
        for c in by_role[cfg.ROLE_WB_TOTAL]:
            cl = cells.get(c.index)
            d, issue = read_amount(cl)
            if issue:
                flags.append(Flag(WARNING, f"{c.header} (cell {c.letter}{r}) {issue}.", "wb_total"))
            if d is not None:
                wb_total = d
                n_formula = total_formula[(c.index, True)]
                n_const = total_formula[(c.index, False)]
                if cl and not cl.formula and n_formula and n_formula >= 0.6 * (n_formula + n_const):
                    flags.append(Flag(WARNING, f"{c.header} (cell {c.letter}{r}) is typed in by hand, not a "
                                               "formula like in most rows.", "wb_total_typed"))
            break
        for c in by_role[cfg.ROLE_WB_NET]:
            d, issue = read_amount(cells.get(c.index))
            if issue:
                flags.append(Flag(WARNING, f"{c.header} (cell {c.letter}{r}) {issue}.", "wb_net"))
            if d is not None:
                wb_net = d
            break
        slip.wb_total, slip.wb_net = wb_total, wb_net

        if income:
            if wb_total is not None:
                diff = slip.calc_total_before_tax - wb_total
                if abs(diff) > tol:
                    flags.append(Flag(ERROR, f"Calculated total before tax {fmt_amount(slip.calc_total_before_tax)} "
                                             f"differs from the workbook's Total Amount {fmt_amount(wb_total)} "
                                             f"(difference {fmt_amount(diff)}).", "total_mismatch"))
            elif by_role[cfg.ROLE_WB_TOTAL]:
                flags.append(Flag(WARNING, "The workbook has no Total Amount for this employee, so the calculation "
                                           "could not be cross-checked.", "no_wb_total"))
            if wb_net is not None:
                diff = slip.net_salary - wb_net
                if abs(diff) > tol:
                    flags.append(Flag(ERROR, f"Calculated net salary {fmt_amount(slip.net_salary)} differs from the "
                                             f"workbook's net pay {fmt_amount(wb_net)} "
                                             f"(difference {fmt_amount(diff)}).", "net_mismatch"))
            elif by_role[cfg.ROLE_WB_NET]:
                flags.append(Flag(WARNING, "The workbook has no net pay (PayCheque) for this employee; the net "
                                           "salary shown is Total Income - Total Deductions.", "no_wb_net"))
            if slip.net_salary < 0:
                flags.append(Flag(ERROR, "Net salary is negative.", "negative_net"))

        # ---- stray notes that mention this employee
        low = name.lower()
        for (sr, sl, text) in sheet.stray:
            if low and low in text.lower():
                flags.append(Flag(WARNING, f"Cell {sl}{sr} contains a note about this employee that is not part of "
                                           f"their row: '{text}'. It was not added to the payslip.", "stray_note"))

        slip.include_default = include_default
        slips.append(slip)
    return slips


def summarise(slips: Sequence[Payslip], included_rows: Sequence[int]) -> Dict[str, int]:
    inc = set(included_rows)
    chosen = [s for s in slips if s.row in inc]
    return {
        "employees": len(slips),
        "included": len(chosen),
        "with_errors": sum(1 for s in slips if s.errors),
        "with_warnings": sum(1 for s in slips if s.warnings and not s.errors),
    }
