import copy
import io
import os
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from payslip_core import calc, config as cfg, workbook as wbk  # noqa: E402
from payslip_core.comments import clean_comment, parse_leave_comment  # noqa: E402
from payslip_core.months import SalaryMonth, detect_month  # noqa: E402
from payslip_core.output import generate  # noqa: E402
from payslip_core.pdfgen import Branding  # noqa: E402
from payslip_core.util import UserError, amount_in_words, fmt_amount, safe_filename  # noqa: E402
import make_synthetic  # noqa: E402

SETTINGS = cfg.load_settings()


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    p = tmp_path_factory.mktemp("d") / "SYN.xlsx"
    make_synthetic.build(p)
    data = p.read_bytes()
    sheet = wbk.read_sheet(data, "SYN.xlsx", "synthetic 2083", SETTINGS)
    return data, sheet, {s.name: s for s in calc.build_payslips(sheet, SETTINGS)}


def labels(lines):
    return [l.label for l in lines]


def test_multiple_sheets_listed(synthetic):
    assert wbk.sheet_names(synthetic[0], "a.xlsx") == ["synthetic 2083", "Other notes"]


def test_employee_specific_allowances(synthetic):
    s = synthetic[2]
    assert "Loyalty Allowance" in labels(s["Ram Many"].income) and "Travelling" in labels(s["Ram Many"].income)
    assert labels(s["Sita Travel"].income) == ["Salary (Working Day Amount)", "Travelling"]
    assert labels(s["Hari Basic"].income) == ["Salary (Working Day Amount)"]


def test_explicit_zero_not_printed(synthetic):
    z = synthetic[2]["Zero Loyalty"]
    assert "Loyalty Allowance" not in labels(z.income)
    assert any(f.code == "zero" for f in z.flags)


def test_leave_items_from_comment_counted_once(synthetic):
    ram = synthetic[2]["Ram Many"]
    assert ("Earned Leave", Decimal("500.00")) in [(l.label, l.amount) for l in ram.income]
    assert ("Restricted Leave", Decimal("500.00")) in [(l.label, l.amount) for l in ram.income]
    assert ram.total_income == Decimal("25000") + 2000 + 1000 + 1000


def test_empty_comment_uses_cell_amount(synthetic):
    s = synthetic[2]["Empty Comment"]
    assert ("Paid Leave", Decimal("500.00")) in [(l.label, l.amount) for l in s.income]


def test_malformed_comment_flagged(synthetic):
    assert synthetic[2]["Bad Comment"].errors


def test_deduction_and_net(synthetic):
    s = synthetic[2]["A Very Long Employee Name With Many Parts Sharma Shrestha Bhattarai Gurung"]
    assert [l.amount for l in s.deductions] == [Decimal("3000.00")]
    assert s.net_salary == s.total_income - s.total_deductions == Decimal("27500.00")


def test_formula_cells_without_cache_are_recalculated_or_flagged(synthetic):
    s = synthetic[2]["Formula Person"]
    if synthetic[1].recalculated:
        assert s.net_salary == Decimal("9998.00") - 0 or s.net_salary > 0
        assert not s.errors
    else:
        assert s.errors


def test_missing_data_and_duplicates(synthetic):
    s = synthetic[2]
    assert any(f.code == "bad_amount" for f in s["Text Amount"].flags)
    assert any(f.code == "dup_id" for f in s["Duplicate Id"].flags)
    assert any(f.code == "no_name" for f in s["(Row 12)"].flags) and not s["(Row 12)"].include_default


def test_comment_parser_variants():
    for txt in ["Earned Leave 500", "Earned Leave: 500", "Earned Leave = 500", "Earned Leave: Rs. 500",
                "Earned Leave: NPR 500"]:
        p = parse_leave_comment(txt)
        assert p.status == "amounts" and p.entries == [("Earned Leave", Decimal(500))], txt
    p = parse_leave_comment("Earned Leave: 1,500, Casual 200")
    assert p.entries == [("Earned Leave", Decimal(1500)), ("Casual", Decimal(200))]
    assert parse_leave_comment("earned leave 2 days").status == "names_only"
    assert parse_leave_comment("Earned 500\nEarned 500").status == "conflict"


def test_threaded_comment_boilerplate_removed():
    raw = "[Threaded comment]\n Your version of Excel allows you ... linkid=870924\nComment:\n\tcamp replacement\n"
    assert clean_comment(raw) == "camp replacement"


def test_month_detection_bs_fiscal_year():
    m, _ = detect_month("bhadra 8384", "Salary_83_84.xlsx")
    assert (m.year, m.month, m.label, m.code) == (2083, 5, "Bhadra 2083", "2083-05")
    m, _ = detect_month("Baisakh 8384")
    assert m.year == 2084


def test_formatting():
    assert fmt_amount(Decimal("1234567.5")) == "Rs. 12,34,567.50"
    assert fmt_amount(Decimal("1234567.5"), "international") == "Rs. 1,234,567.50"
    assert amount_in_words(Decimal("30466.26")).startswith("Rupees Thirty Thousand Four Hundred Sixty-Six and Twenty-Six")
    assert safe_filename("A/B: C?") == "A_B_C"


def test_site_logo_is_independent_of_payslip_logo():
    assert cfg.resolve_site_logo() == cfg.SITE_LOGO


def test_capitalise_names_setting(synthetic):
    sheet = copy.deepcopy(synthetic[1])
    name_col = next(c for c in sheet.columns if c.role == cfg.ROLE_NAME)
    sheet.rows[0].cells[name_col.index].value = "sample employee"

    settings = dict(SETTINGS, capitalise_names=False)
    assert calc.build_payslips(sheet, settings)[0].name == "sample employee"

    settings["capitalise_names"] = True
    assert calc.build_payslips(sheet, settings)[0].name == "Sample Employee"


def test_bad_files():
    with pytest.raises(UserError):
        wbk.read_sheet(b"not excel", "x.xlsx", None, SETTINGS)
    with pytest.raises(UserError):
        wbk.sheet_names(b"x", "x.csv")


def test_generate_pdfs_zip_and_nothing_overwritten(synthetic, tmp_path):
    slips = [s for s in synthetic[2].values() if s.include_default and not s.errors]
    b = Branding(firm_name="Hello Health Polyclinic", logo_path=cfg.resolve_logo(SETTINGS))
    month = SalaryMonth("BS", 2083, 5)
    r1 = generate(slips, month, b, base=tmp_path)
    assert r1.success and len(r1.individual) == len(slips)
    assert r1.combined and r1.zip_path
    names = zipfile.ZipFile(r1.zip_path).namelist()
    assert len(names) == len(slips) + 1
    assert all("2083-05" in n for n in names)
    first = r1.individual[0].path
    before = first.read_bytes()
    r2 = generate(slips, month, b, mode="new", base=tmp_path)
    assert r2.folder.name == "2083-05_v2" and first.read_bytes() == before


REAL = os.environ.get("PAYSLIP_REAL_XLSX")


@pytest.mark.skipif(not REAL, reason="set PAYSLIP_REAL_XLSX to run against a real workbook")
def test_real_workbook_matches_workbook_net_pay():
    data = Path(REAL).read_bytes()
    sheet = wbk.read_sheet(data, Path(REAL).name, None, SETTINGS)
    for s in calc.build_payslips(sheet, SETTINGS):
        if s.wb_net is not None and not s.errors:
            assert abs(s.net_salary - s.wb_net) <= Decimal("0.10")
