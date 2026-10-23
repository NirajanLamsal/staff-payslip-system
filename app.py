"""Payslip Manager - local website for turning a salary workbook into PDF payslips.

Everything runs on this computer. The uploaded workbook is only held in memory.
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from payslip_core import calc, config as cfg, ui, workbook as wbk  # noqa: E402
from payslip_core.logsetup import log_error  # noqa: E402
from payslip_core.models import ERROR, INFO, WARNING, Payslip  # noqa: E402
from payslip_core.months import (AD_MONTHS, BS_MONTHS, CAL_AD, CAL_BS, SalaryMonth, detect_month,  # noqa: E402
                                 month_names)
from payslip_core.output import existing_files, generate, purge_outputs, resolve_folder  # noqa: E402
from payslip_core.pdfgen import Branding  # noqa: E402
from payslip_core.recalc import libreoffice_path  # noqa: E402
from payslip_core.util import UserError, fmt_amount, to_decimal  # noqa: E402

page_logo = cfg.resolve_site_logo()
st.set_page_config(page_title="Payslip Manager", page_icon=str(page_logo) if page_logo else "🔒",
                   layout="wide", initial_sidebar_state="expanded")

# Everything below this line is only reachable after the admin has signed in.
ui.require_login()

HOSTED = os.environ.get("PAYSLIP_HOSTED", "").strip().lower() in ("1", "true", "yes")
PURGE_HOURS = float(os.environ.get("PAYSLIP_PURGE_HOURS", "24" if HOSTED else "0") or 0)
if PURGE_HOURS > 0 and "purged" not in st.session_state:
    purge_outputs(older_than_hours=PURGE_HOURS)   # salary PDFs should not linger on a server
    st.session_state["purged"] = True

step = ui.step


def show_flag(f) -> None:
    msg = ui.md_esc(f.message)
    if f.level == ERROR:
        st.error(msg, icon="🛑")
    elif f.level == WARNING:
        st.warning(msg, icon="⚠️")
    else:
        st.info(msg, icon="ℹ️")


def download_button(label: str, data: bytes, file_name: str, mime: str, key: str, **kw) -> None:
    try:
        st.download_button(label, data, file_name=file_name, mime=mime, key=key, on_click="ignore", **kw)
    except TypeError:
        st.download_button(label, data, file_name=file_name, mime=mime, key=key, **kw)


# ------------------------------------------------------------------ settings & branding sidebar
settings = cfg.load_settings()


def save_logo(uploaded) -> str:
    from PIL import Image
    raw = uploaded.getvalue()
    if len(raw) > 2_000_000:
        raise UserError("That logo is larger than 2 MB. Please upload a smaller PNG or JPG.")
    Image.MAX_IMAGE_PIXELS = 20_000_000
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ("PNG", "JPEG"):
            raise ValueError("format")
        img.load()
    except Exception:
        raise UserError("That logo file could not be read. Please upload a PNG or JPG image.")
    cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    dest = cfg.CONFIG_DIR / f"logo_{hashlib.sha256(raw).hexdigest()[:16]}.png"
    fd, tmp_name = tempfile.mkstemp(dir=str(cfg.CONFIG_DIR), suffix=".tmp")
    os.close(fd)
    try:
        img.convert("RGBA").save(tmp_name, format="PNG")
        os.replace(tmp_name, dest)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return f"config/{dest.name}"


with st.sidebar:
    ui.sidebar_account()
    st.header("Firm details & options")
    st.caption("Saved on this computer and remembered next time.")
    logo_file = cfg.resolve_logo(settings)
    if logo_file:
        st.image(str(logo_file), width=200)
        st.caption("This logo is used on generated payslips. The website uses config/logo.png.")
    else:
        st.error("No logo found. Upload one below - it is printed on every payslip.")
    with st.form("branding"):
        firm_name = st.text_input("Firm / company name", value=settings["firm_name"])
        firm_address = st.text_input("Address line (optional)", value=settings["firm_address"])
        new_logo = st.file_uploader("Replace logo (PNG or JPG)", type=["png", "jpg", "jpeg"])
        reset_logo = st.checkbox("Go back to the original logo")
        st.markdown("**Payslip options**")
        calendar_default = st.selectbox("Calendar for salary month", [CAL_BS, CAL_AD],
                                        index=0 if settings["calendar"] == CAL_BS else 1,
                                        format_func=lambda c: "Bikram Sambat (Nepali)" if c == CAL_BS else "Gregorian (English)")
        grouping = st.selectbox("Number grouping", ["nepali", "international"],
                                index=0 if settings["digit_grouping"] == "nepali" else 1,
                                format_func=lambda g: "Nepali  12,34,567.00" if g == "nepali" else "International  1,234,567.00")
        show_pan = st.checkbox("Print PAN number on payslip", value=settings["show_pan_on_payslip"])
        show_att = st.checkbox("Print attendance (days) strip", value=settings["show_attendance"])
        show_words = st.checkbox("Print net salary in words", value=settings["show_amount_in_words"])
        show_sig = st.checkbox("Print signature lines", value=settings["show_signatures"])
        if st.form_submit_button("Save", width="stretch"):
            try:
                new = dict(settings)
                new.update(firm_name=firm_name.strip() or settings["firm_name"], firm_address=firm_address.strip(),
                           calendar=calendar_default, digit_grouping=grouping,
                           show_pan_on_payslip=show_pan, show_attendance=show_att,
                           show_amount_in_words=show_words, show_signatures=show_sig)
                if new_logo is not None:
                    new["logo_path"] = save_logo(new_logo)
                elif reset_logo:
                    new["logo_path"] = "config/logo.png"
                cfg.save_settings(new)
                st.success("Saved.")
                st.rerun()
            except UserError as exc:
                st.error(str(exc))
            except OSError as exc:
                log_error("save settings", exc)
                st.error("The settings could not be saved. Check that this folder is writable.")
    st.divider()
    if HOSTED:
        st.caption("Uploaded workbooks are kept in memory only. Generated PDFs are deleted automatically "
                   f"after {PURGE_HOURS:g} hours.")
    else:
        st.caption("All salary processing happens on this computer. No data is sent anywhere.")
    if st.button("Delete all generated payslips now", width="stretch", key="wipe_out"):
        st.toast(f"Deleted {purge_outputs()} folder(s) of generated payslips.")

settings = cfg.load_settings()
logo_file = cfg.resolve_logo(settings)

# ------------------------------------------------------------------ header
ui.brand_header(settings["firm_name"])

# ------------------------------------------------------------------ cached readers
@st.cache_data(show_spinner="Reading the workbook...", max_entries=3, ttl=900)
def cached_sheet_names(data: bytes, filename: str) -> List[str]:
    return wbk.sheet_names(data, filename)


@st.cache_data(show_spinner="Reading the sheet...", max_entries=3, ttl=900)
def cached_guess(data: bytes, settings_key: str) -> str:
    return wbk.guess_sheet(data, cfg.load_settings())


@st.cache_data(show_spinner="Reading the sheet (recalculating formulas if needed)...", max_entries=3, ttl=900)
def cached_sheet(data: bytes, filename: str, sheet: str, header_row: Optional[int], settings_key: str):
    return wbk.read_sheet(data, filename, sheet, cfg.load_settings(), header_row=header_row)


def settings_key(s: Dict[str, Any]) -> str:
    import json
    return json.dumps({k: s[k] for k in ("column_roles", "labels")}, sort_keys=True)


# ------------------------------------------------------------------ step 1: upload
step(1, "Upload the Excel salary workbook")
uploaded = st.file_uploader("Choose the .xlsx file (your original file is never changed)",
                            type=["xlsx", "xlsm", "xls"], label_visibility="collapsed")
if uploaded is None:
    st.info("Choose your salary workbook above to begin. It is read in memory only and never saved on the server."
            if HOSTED else "Choose your salary workbook above to begin. Nothing is uploaded to the internet - "
            "the file is read on this computer only.")
    st.stop()

data = uploaded.getvalue()
fhash = hashlib.sha1(data).hexdigest()[:10]
try:
    sheets = cached_sheet_names(data, uploaded.name)
except UserError as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:  # unexpected
    log_error("open workbook", exc)
    st.error("Something went wrong while opening the workbook. Please check the file and try again.")
    st.stop()

# ------------------------------------------------------------------ step 2: sheet + month
step(2, "Choose the worksheet and confirm the salary month")
c1, c2 = st.columns([1, 2])
default_sheet = cached_guess(data, settings_key(settings))
with c1:
    sheet_name = st.selectbox("Worksheet", sheets, index=sheets.index(default_sheet) if default_sheet in sheets else 0,
                              key=f"sheet_{fhash}")
    with st.expander("Advanced: header row"):
        hdr_override = st.number_input("Header row number (0 = detect automatically)", min_value=0, max_value=200,
                                       value=0, step=1, key=f"hdr_{fhash}_{sheet_name}")

try:
    sheet = cached_sheet(data, uploaded.name, sheet_name, int(hdr_override) or None, settings_key(settings))
except UserError as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:
    log_error("read sheet", exc)
    st.error("Something went wrong while reading this worksheet. Try another worksheet or check the file.")
    st.stop()

detected, note = detect_month(sheet_name, uploaded.name)
mkey = f"{fhash}_{sheet_name}"
with c2:
    mc1, mc2, mc3 = st.columns([1.3, 1.3, 1])
    cal_default = detected.calendar if detected else settings["calendar"]
    cal = mc1.selectbox("Calendar", [CAL_BS, CAL_AD], index=0 if cal_default == CAL_BS else 1,
                        format_func=lambda c: "Bikram Sambat" if c == CAL_BS else "Gregorian", key=f"cal_{mkey}")
    names = month_names(cal)
    m_default = (detected.month - 1) if (detected and detected.calendar == cal) else 0
    month_idx = mc2.selectbox("Month", list(range(12)), index=m_default, format_func=lambda i: names[i],
                              key=f"month_{mkey}_{cal}")
    y_default = detected.year if (detected and detected.calendar == cal and detected.year) else (2083 if cal == CAL_BS else 2026)
    year = mc3.number_input("Year", min_value=1900, max_value=2200, value=int(y_default), step=1, key=f"year_{mkey}_{cal}")
    salary_month = SalaryMonth(cal, int(year), int(month_idx) + 1)
    st.caption(f"{note}  The payslips will say **{salary_month.label}**; files are saved under "
               f"`output/{salary_month.code}`.")
    month_ok = st.checkbox(f"Yes, the salary month is {salary_month.label}", key=f"monthok_{mkey}_{salary_month.code}")

if sheet.recalculated:
    st.caption("Formula results were recalculated on this computer with LibreOffice because the file had none stored.")

# ------------------------------------------------------------------ step 3: column mapping
step(3, "Check how the columns are understood")
role_labels = cfg.ROLE_HELP
with st.expander("Column mapping (open only if a column is treated wrongly)"):
    st.caption("Each column of your sheet has a role. Earnings are printed on the left, deductions on the right. "
               "'Reference only' columns are never printed or added. Change a role or the printed name, then press Apply.")
    map_df = pd.DataFrame([{
        "Column": c.letter, "Header in workbook": c.header, "Role": c.role, "Printed name": c.label,
    } for c in sheet.columns])
    edited_map = st.data_editor(
        map_df, hide_index=True, width="stretch", key=f"map_{fhash}_{sheet_name}",
        disabled=["Column", "Header in workbook"],
        column_config={"Role": st.column_config.SelectboxColumn("Role", options=cfg.ALL_ROLES, required=True,
                                                                  help="; ".join(f"{k}: {v}" for k, v in role_labels.items()))})
    if st.button("Apply column mapping"):
        new = cfg.load_settings()
        roles = dict(new.get("column_roles", {}))
        labels = dict(new.get("labels", {}))
        for col, row in zip(sheet.columns, edited_map.to_dict("records")):
            if row["Role"] != col.role:
                roles[col.key] = row["Role"]
            if str(row["Printed name"]).strip() and row["Printed name"] != col.label:
                labels[col.header] = str(row["Printed name"]).strip()
        new["column_roles"], new["labels"] = roles, labels
        cfg.save_settings(new)
        st.rerun()
    st.caption("Roles: " + " | ".join(f"**{k}** = {v}" for k, v in role_labels.items()))

# ------------------------------------------------------------------ step 4: corrections (optional) + review
base_slips = calc.build_payslips(sheet, settings)
base_by_row = {s.row: s for s in base_slips}

step(4, "Review employees, allowances, deductions and paid leave")

# --- paid-leave entries editor and manual lines (optional corrections)
leave_rows = []
for s in base_slips:
    for info in s.leave:
        for ln in info.used:
            leave_rows.append({"Excel row": s.row, "Employee": s.name, "Entry": ln.label, "Amount (Rs.)": float(ln.amount)})
leave_df = pd.DataFrame(leave_rows, columns=["Excel row", "Employee", "Entry", "Amount (Rs.)"])
with st.expander("Optional corrections: split / edit paid-leave entries, or add a line by hand"):
    st.markdown("**Paid-leave entries** - change the text or amounts, or split one line into several "
                "(for example *Earned Leave 500* and *Restricted Leave 500*). The amounts must add up to the paid-leave "
                "amount in your workbook, otherwise the employee is flagged. Add a row for an employee using their "
                "Excel row number.")
    edited_leave = st.data_editor(leave_df, num_rows="dynamic", hide_index=True, width="stretch",
                                  key=f"leave_{fhash}_{sheet_name}", disabled=["Employee"],
                                  column_config={"Excel row": st.column_config.NumberColumn(format="%d", step=1),
                                                 "Amount (Rs.)": st.column_config.NumberColumn(format="%.2f", step=0.01)})
    st.markdown("**Lines added by hand** - for something missing from the workbook (for example a deduction or "
                "an amount you want printed). They are added to the employee's totals and shown as a note.")
    extra_df = pd.DataFrame({"Excel row": pd.Series(dtype="int64"), "Type": pd.Series(dtype="object"),
                             "Label": pd.Series(dtype="object"), "Amount (Rs.)": pd.Series(dtype="float64")})
    edited_extra = st.data_editor(extra_df, num_rows="dynamic", hide_index=True, width="stretch",
                                  key=f"extra_{fhash}_{sheet_name}",
                                  column_config={"Excel row": st.column_config.NumberColumn(format="%d", step=1),
                                                 "Type": st.column_config.SelectboxColumn(options=calc.EXTRA_TYPES),
                                                 "Amount (Rs.)": st.column_config.NumberColumn(format="%.2f", step=0.01)})

overrides: Dict[int, List[tuple]] = {}
if edited_leave is not None and len(edited_leave):
    grouped: Dict[int, List[tuple]] = {}
    for rec in edited_leave.to_dict("records"):
        try:
            row = int(rec["Excel row"])
            amt = to_decimal(float(rec["Amount (Rs.)"]))
        except (TypeError, ValueError):
            continue
        label = str(rec.get("Entry") or "").strip()
        if row in base_by_row and amt is not None and label and amt != 0:
            grouped.setdefault(row, []).append((label, amt))
    for row, entries in grouped.items():
        base_entries = sorted((l.label, l.amount) for i in base_by_row[row].leave for l in i.used)
        if sorted((lab, calc.money(a)) for lab, a in entries) != base_entries:
            overrides[row] = entries

extras: List[Dict[str, Any]] = []
if edited_extra is not None and len(edited_extra):
    for rec in edited_extra.to_dict("records"):
        try:
            row = int(rec["Excel row"])
            amt = to_decimal(float(rec["Amount (Rs.)"]))
        except (TypeError, ValueError):
            continue
        if row in base_by_row and amt is not None and rec.get("Type") in calc.EXTRA_TYPES \
                and str(rec.get("Label") or "").strip():
            extras.append({"row": row, "type": rec["Type"], "label": str(rec["Label"]).strip(), "amount": amt})

slips = calc.build_payslips(sheet, settings, leave_overrides=overrides, extra_lines=extras)
by_row = {s.row: s for s in slips}

# --- summary & global notes
for f in sheet.global_flags:
    if f.level != INFO:
        show_flag(f)

# --- selection table
rows_tbl = []
for s in slips:
    ne, nw = len(s.errors), len(s.warnings)
    issues = " · ".join(x for x in (f"🛑 {ne} error{'s' if ne != 1 else ''}" if ne else "",
                                    f"⚠️ {nw} warning{'s' if nw != 1 else ''}" if nw else "") if x) or "✅ OK"
    rows_tbl.append({"Include": s.include_default, "Reviewed": False, "Excel row": s.row, "Employee ID": s.emp_id,
                     "Name": s.name, "Total income": float(s.total_income), "Total deductions": float(s.total_deductions),
                     "Net salary": float(s.net_salary), "Check": issues})
sel_df = pd.DataFrame(rows_tbl)
st.markdown("**Employees** - untick *Include* to leave someone out. Employees with a 🛑 error must be ticked "
            "*Reviewed* after you have looked at the details below (or be left out).")
edited_sel = st.data_editor(
    sel_df, hide_index=True, width="stretch", key=f"sel_{fhash}_{sheet_name}",
    disabled=["Excel row", "Employee ID", "Name", "Total income", "Total deductions", "Net salary", "Check"],
    column_config={
        "Total income": st.column_config.NumberColumn(format="%.2f"),
        "Total deductions": st.column_config.NumberColumn(format="%.2f"),
        "Net salary": st.column_config.NumberColumn(format="%.2f"),
        "Include": st.column_config.CheckboxColumn(help="Create a payslip for this employee"),
        "Reviewed": st.column_config.CheckboxColumn(help="I have checked the flagged items for this employee"),
    })
included_rows = [int(r["Excel row"]) for r in edited_sel.to_dict("records") if r["Include"]]
reviewed_rows = {int(r["Excel row"]) for r in edited_sel.to_dict("records") if r["Reviewed"]}
chosen = [by_row[r] for r in included_rows]
unreviewed = [s for s in chosen if s.errors and s.row not in reviewed_rows]

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Employees found", len(slips))
m2.metric("Payslips to create", len(chosen))
m3.metric("With errors 🛑", sum(1 for s in slips if s.errors))
m4.metric("With warnings ⚠️", sum(1 for s in slips if s.warnings and not s.errors))
m5.metric("Total net salary", fmt_amount(sum((s.net_salary for s in chosen), Decimal(0)), settings["digit_grouping"]))

attention = [(s, f) for s in slips for f in s.flags if f.level in (ERROR, WARNING)]
if attention:
    with st.expander(f"Items needing attention ({len(attention)})", expanded=bool(unreviewed)):
        for s, f in attention:
            icon = "🛑" if f.level == ERROR else "⚠️"
            st.markdown(f"{icon} **{ui.md_esc(s.name)}** (row {s.row}): {ui.md_esc(f.message)}")

# --- allowance & deduction preview (employee-specific)
colmap = {c.letter: c for c in sheet.columns}


def header_for(line, deduction: bool) -> str:
    base = colmap[line.source].label if line.source in colmap else line.label
    return ("Less: " + base) if deduction else base


inc_cols: List[str] = []
ded_cols: List[str] = []
for s in slips:
    for l in s.income:
        h = header_for(l, False)
        if h not in inc_cols:
            inc_cols.append(h)
    for l in s.deductions:
        h = header_for(l, True)
        if h not in ded_cols:
            ded_cols.append(h)
wide_rows = []
for s in slips:
    rec: Dict[str, Any] = {"Name": s.name}
    for l in s.income:
        h = header_for(l, False)
        rec[h] = float(rec.get(h, 0) or 0) + float(l.amount)
    for l in s.deductions:
        h = header_for(l, True)
        rec[h] = float(rec.get(h, 0) or 0) + float(l.amount)
    rec["Total income"], rec["Total deductions"], rec["Net salary"] = float(s.total_income), float(s.total_deductions), float(s.net_salary)
    wide_rows.append(rec)
wide_df = pd.DataFrame(wide_rows, columns=["Name"] + inc_cols + ded_cols + ["Total income", "Total deductions", "Net salary"])
tab_a, tab_b, tab_c = st.tabs(["Allowances & deductions per employee", "Paid-leave comments", "One employee in detail"])
with tab_a:
    st.caption("Blank = the employee does not receive it, so it will not appear on their payslip.")
    st.dataframe(wide_df, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.2f") for c in wide_df.columns if c != "Name"})
with tab_b:
    leave_view = []
    for s in slips:
        for info in s.leave:
            if info.cell_amount or info.comment or info.used:
                leave_view.append({
                    "Name": s.name, "Paid leave in workbook": float(info.cell_amount) if info.cell_amount is not None else None,
                    "Comment in workbook": info.comment.replace("\n", " / "), "How it was read": info.status,
                    "Printed as": "; ".join(f"{l.label}: {fmt_amount(l.amount, settings['digit_grouping'])}" for l in info.used) or "(nothing)",
                    "Source": info.source})
    if leave_view:
        st.dataframe(pd.DataFrame(leave_view), hide_index=True, width="stretch",
                     column_config={"Paid leave in workbook": st.column_config.NumberColumn(format="%.2f")})
    else:
        st.write("No paid-leave amounts or comments were found.")
with tab_c:
    pick = st.selectbox("Employee", [s.row for s in slips], format_func=lambda r: f"{by_row[r].name} (row {r})",
                        key=f"pick_{fhash}_{sheet_name}")
    s = by_row[pick]
    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**Income**")
        st.dataframe(pd.DataFrame([{"Item": l.label, "Rs.": fmt_amount(l.amount, settings["digit_grouping"], "")} for l in s.income]
                                  or [{"Item": "(none)", "Rs.": ""}]), hide_index=True, width="stretch")
        st.markdown(f"**Total income: {fmt_amount(s.total_income, settings['digit_grouping'])}**")
    with d2:
        st.markdown("**Deductions**")
        st.dataframe(pd.DataFrame([{"Item": l.label, "Rs.": fmt_amount(l.amount, settings["digit_grouping"], "")} for l in s.deductions]
                                  or [{"Item": "(none)", "Rs.": ""}]), hide_index=True, width="stretch")
        st.markdown(f"**Total deductions: {fmt_amount(s.total_deductions, settings['digit_grouping'])}**")
    st.markdown(f"### Net salary payable: {fmt_amount(s.net_salary, settings['digit_grouping'])}")
    if s.wb_net is not None or s.wb_total is not None:
        st.caption(f"Workbook says: Total Amount {fmt_amount(s.wb_total) if s.wb_total is not None else '-'}, "
                   f"net pay {fmt_amount(s.wb_net) if s.wb_net is not None else '-'}.")
    if s.attendance:
        st.caption("Attendance: " + ", ".join(f"{k} {v}" for k, v in s.attendance))
    for f in s.flags:
        show_flag(f)
    if s.notes:
        st.markdown("**Notes in the workbook (shown here only, not printed):**")
        for n in s.notes:
            st.text(str(n))

# ------------------------------------------------------------------ step 5: generate
step(5, "Create the payslips")
ctx = (fhash, sheet_name, salary_month.code)
if st.session_state.get("ctx") != ctx:
    st.session_state["ctx"] = ctx
    st.session_state["stage"] = "review"
    st.session_state.pop("result", None)
stage = st.session_state.get("stage", "review")

branding = Branding(firm_name=settings["firm_name"], address=settings["firm_address"], logo_path=logo_file,
                    grouping=settings["digit_grouping"], show_pan=settings["show_pan_on_payslip"],
                    show_words=settings["show_amount_in_words"], show_attendance=settings["show_attendance"],
                    show_signatures=settings["show_signatures"])

existing = existing_files(salary_month)
save_mode = "replace"
replace_ok = True
if existing and stage != "done":
    st.warning(f"The folder output/{salary_month.code} already contains {len(existing)} file(s) from an earlier run.")
    choice = st.radio("What should happen to them?",
                      [f"Keep the old files and save this run in a new folder (output/{resolve_folder(salary_month, 'new').name})",
                       f"Replace files with the same name in output/{salary_month.code}"],
                      key=f"mode_{fhash}_{salary_month.code}")
    save_mode = "new" if choice.startswith("Keep") else "replace"
    if save_mode == "replace":
        replace_ok = st.checkbox("I understand that same-named PDFs, the combined PDF and the ZIP will be overwritten",
                                 key=f"repl_{fhash}_{salary_month.code}")

problems = []
if not month_ok:
    problems.append("Tick the box in step 2 to confirm the salary month.")
if not chosen:
    problems.append("No employee is selected (see the *Include* column).")
if unreviewed:
    problems.append("Tick *Reviewed* (or untick *Include*) for: " + ", ".join(ui.md_esc(s.name) for s in unreviewed) + ".")
if not logo_file:
    problems.append("A logo is needed: upload one in the sidebar.")
if not settings["firm_name"].strip():
    problems.append("Enter the firm name in the sidebar.")
if existing and save_mode == "replace" and not replace_ok:
    problems.append("Confirm that existing files may be replaced, or choose to keep them.")

if stage == "review":
    for p in problems:
        st.caption(f"⛔ {p}")
    if st.button("Review summary & generate payslips", type="primary", disabled=bool(problems)):
        st.session_state["stage"] = "confirm"
        st.session_state["mode"] = save_mode
        st.rerun()

elif stage == "confirm":
    if problems:
        st.session_state["stage"] = "review"
        st.rerun()
    mode = st.session_state.get("mode", "replace")
    folder = resolve_folder(salary_month, mode)
    n_warn = sum(1 for s in chosen if s.warnings)
    n_rev = sum(1 for s in chosen if s.errors)
    st.info(f"**Ready to create {len(chosen)} payslip(s) for {salary_month.label}.**  \n"
            f"Folder: `output/{folder.name}`  \nEmployees with warnings: {n_warn}; with errors you marked as reviewed: {n_rev}.  \n"
            f"Total net salary: {fmt_amount(sum((s.net_salary for s in chosen), Decimal(0)), settings['digit_grouping'])}")
    b1, b2, _ = st.columns([1, 1, 3])
    go = b1.button("Confirm and create PDFs", type="primary")
    back = b2.button("Go back to the preview")
    if back:
        st.session_state["stage"] = "review"
        st.rerun()
    if go:
        bar = st.progress(0.0, text="Starting...")

        def progress(i: int, total: int, name: str) -> None:
            bar.progress(i / total, text=f"Creating payslip {i} of {total}: {name}")

        try:
            res = generate(chosen, salary_month, branding, mode=mode, progress=progress)
            st.session_state["result"] = res
            st.session_state["stage"] = "done"
            bar.empty()
            st.rerun()
        except UserError as exc:
            bar.empty()
            st.error(str(exc))
        except Exception as exc:
            bar.empty()
            log_error("generate", exc)
            st.error("The payslips could not be created because of an unexpected problem. "
                     "Nothing was reported as finished. Details were saved in the logs folder.")

elif stage == "done":
    res = st.session_state.get("result")
    if res is None:
        st.session_state["stage"] = "review"
        st.rerun()
    ok_files = [g for g in res.individual if g.ok]
    if res.success:
        st.success(f"Done - {len(ok_files)} payslip(s) were created and checked (name, month and firm name found in each PDF). "
                   f"Saved in `output/{res.folder.name}`.")
    else:
        st.error("Some files could not be created or failed the check. Only verified files are listed below.")
        for p in res.problems:
            st.write("• " + p)
    zip_name = f"Payslips_{res.folder.name}.zip"
    cols = [1.4, 1.2, 1] if not HOSTED else [1.4, 1.2]
    d_cols = st.columns(cols)
    if res.zip_path and res.zip_path.exists():
        with d_cols[0]:
            download_button(f"📦 Download All Output (ZIP)", res.zip_path.read_bytes(), zip_name,
                            "application/zip", "dl_zip", type="primary", width="stretch")
    if res.combined and res.combined.exists():
        with d_cols[1]:
            download_button("⬇ Combined PDF (all payslips)", res.combined.read_bytes(), res.combined.name,
                            "application/pdf", "dl_combined", width="stretch")
    if not HOSTED and len(d_cols) > 2:
        with d_cols[2]:
            if st.button("Open output folder", width="stretch"):
                opener = shutil.which("xdg-open")
                if opener:
                    try:
                        subprocess.Popen([opener, str(res.folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except OSError:
                        st.info(f"Open this folder yourself: {res.folder}")
                else:
                    st.info(f"Open this folder yourself: {res.folder}")
    st.caption(f"All generated payslips and combined PDF are packaged in `{zip_name}`." if HOSTED
               else f"All files packaged in `{zip_name}` • Folder on this computer: {res.folder}")
    with st.expander(f"Individual payslips ({len(ok_files)})", expanded=True):
        for g in ok_files:
            r1, r2 = st.columns([3, 1], vertical_alignment="center")
            r1.write(f"{ui.md_esc(g.name)}  \n`{g.path.name}`")
            with r2:
                download_button("Download", g.path.read_bytes(), g.path.name, "application/pdf", f"dl_{g.row}",
                                width="stretch")
    if st.button("Back to the preview / make changes"):
        st.session_state["stage"] = "review"
        st.rerun()
