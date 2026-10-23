"""Writing, verifying and zipping the generated payslips."""
from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .config import OUTPUT_DIR
from .logsetup import log_error, log_info
from .models import Payslip
from .months import SalaryMonth
from .pdfgen import Branding, render_payslips
from .util import UserError, safe_filename


@dataclass
class GeneratedFile:
    row: int
    name: str
    path: Optional[Path] = None
    ok: bool = False
    message: str = ""


@dataclass
class GenerationResult:
    folder: Path
    individual: List[GeneratedFile] = field(default_factory=list)
    combined: Optional[Path] = None
    zip_path: Optional[Path] = None
    problems: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.individual) and all(f.ok for f in self.individual) and self.combined is not None \
            and self.zip_path is not None and not self.problems


def month_folder(month: SalaryMonth, base: Path = OUTPUT_DIR) -> Path:
    return base / month.code


def existing_files(month: SalaryMonth, base: Path = OUTPUT_DIR) -> List[Path]:
    folder = month_folder(month, base)
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file())


def resolve_folder(month: SalaryMonth, mode: str, base: Path = OUTPUT_DIR) -> Path:
    """mode 'replace': reuse output/<code>; mode 'new': output/<code>_v2, _v3 ... (older folders untouched)."""
    folder = month_folder(month, base)
    if mode != "new" or not folder.exists():
        return folder
    n = 2
    while (base / f"{month.code}_v{n}").exists():
        n += 1
    return base / f"{month.code}_v{n}"


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _atomic_write(path: Path, writer: Callable[[Path], None]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".part")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        writer(tmp_path)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def verify_pdf(path: Path, expected_pages: List[List[str]]) -> Optional[str]:
    """Open the written PDF again and check page count and that each page has the expected texts.
    Returns None when fine, else a plain-language problem."""
    if not path.exists() or path.stat().st_size < 500:
        return "the file was not created"
    with open(path, "rb") as fh:
        if fh.read(5) != b"%PDF-":
            return "the file is not a valid PDF"
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
    except Exception:
        return "the PDF could not be opened again for checking"
    if len(reader.pages) != len(expected_pages):
        return f"expected {len(expected_pages)} page(s) but found {len(reader.pages)}"
    for i, needles in enumerate(expected_pages):
        try:
            text = _norm(reader.pages[i].extract_text() or "")
        except Exception:
            return f"page {i + 1} text could not be read back"
        for n in needles:
            if _norm(n) not in text:
                return f"page {i + 1} does not contain '{n}'"
    return None


def generate(slips: Sequence[Payslip], month: SalaryMonth, branding: Branding,
             mode: str = "replace", base: Path = OUTPUT_DIR,
             progress: Optional[Callable[[int, int, str], None]] = None) -> GenerationResult:
    if not slips:
        raise UserError("No employees are selected for payslip generation.")
    folder = resolve_folder(month, mode, base)
    ind_dir, comb_dir = folder / "individual", folder / "combined"
    try:
        ind_dir.mkdir(parents=True, exist_ok=True)
        comb_dir.mkdir(parents=True, exist_ok=True)
        probe = tempfile.NamedTemporaryFile(dir=str(folder), delete=True)
        probe.close()
    except OSError as exc:
        log_error("create output folder", exc)
        raise UserError(f"The output folder could not be created or written to ({folder}). "
                        "Check that you have permission to save files there.")

    result = GenerationResult(folder=folder)
    used: Dict[str, int] = {}
    month_label = month.label
    total = len(slips)
    for i, slip in enumerate(slips, 1):
        base_name = f"{safe_filename(slip.name)}_Payslip_{month.code}"
        fname = base_name + ".pdf"
        if fname.lower() in used:
            suffix = safe_filename(slip.emp_id) if slip.emp_id else f"row{slip.row}"
            fname = f"{base_name}_{suffix}.pdf"
            while fname.lower() in used:
                fname = f"{base_name}_{suffix}_{slip.row}.pdf"
        used[fname.lower()] = 1
        gf = GeneratedFile(row=slip.row, name=slip.name, path=ind_dir / fname)
        if progress:
            progress(i, total, slip.name)
        try:
            _atomic_write(gf.path, lambda p: render_payslips(
                str(p), [slip], month_label, branding, f"Payslip - {slip.name} - {month_label}"))
            problem = verify_pdf(gf.path, [[slip.name, month_label, branding.firm_name]])
            gf.ok, gf.message = problem is None, problem or "verified"
        except PermissionError as exc:
            log_error("write payslip", exc)
            gf.message = "no permission to save this file"
        except Exception as exc:
            log_error("render payslip", exc)
            gf.message = "the PDF could not be created"
        result.individual.append(gf)

    good = [(s, g) for s, g in zip(slips, result.individual) if g.ok]
    if good:
        comb = comb_dir / f"All_Payslips_{month.code}.pdf"
        try:
            _atomic_write(comb, lambda p: render_payslips(
                str(p), [s for s, _ in good], month_label, branding, f"All Payslips - {month_label}"))
            problem = verify_pdf(comb, [[s.name, month_label] for s, _ in good])
            if problem:
                result.problems.append(f"Combined PDF: {problem}.")
            else:
                result.combined = comb
        except Exception as exc:
            log_error("render combined", exc)
            result.problems.append("The combined PDF could not be created.")

        zpath = folder / "payslips.zip"
        try:
            def write_zip(p: Path) -> None:
                with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
                    for _, g in good:
                        zf.write(g.path, f"individual/{g.path.name}")
                    if result.combined:
                        zf.write(result.combined, f"combined/{result.combined.name}")
            _atomic_write(zpath, write_zip)
            with zipfile.ZipFile(zpath) as zf:
                expected = len(good) + (1 if result.combined else 0)
                if zf.testzip() is not None or len(zf.namelist()) != expected:
                    result.problems.append("The ZIP archive failed its integrity check.")
                else:
                    result.zip_path = zpath
        except Exception as exc:
            log_error("zip", exc)
            result.problems.append("The ZIP archive could not be created.")

    for g in result.individual:
        if not g.ok:
            result.problems.append(f"{g.name}: {g.message}.")
    log_info(f"Generated {sum(1 for g in result.individual if g.ok)}/{total} payslips for {month.code} "
             f"(success={result.success})")
    return result


_MONTH_DIR = re.compile(r"^\d{4}-\d{2}(_v\d+)?$")


def _generated_dirs(base: Path = OUTPUT_DIR) -> List[Path]:
    """Only folders this app creates (e.g. 2083-05, 2083-05_v2); never follows symlinks."""
    if not base.exists():
        return []
    return [d for d in base.iterdir() if d.is_dir() and not d.is_symlink() and _MONTH_DIR.match(d.name)]


def purge_outputs(older_than_hours: Optional[float] = None, base: Path = OUTPUT_DIR) -> int:
    """Delete generated payslip folders (all, or only those not touched for `older_than_hours`).
    Returns how many folders were removed. Salary PDFs should not linger on a server."""
    removed = 0
    cutoff = None if older_than_hours is None else time.time() - older_than_hours * 3600
    root = base.resolve()
    for d in _generated_dirs(base):
        try:
            if root not in d.resolve().parents:
                continue
            newest = max([d.stat().st_mtime] + [p.stat().st_mtime for p in d.rglob("*")])
            if cutoff is None or newest < cutoff:
                shutil.rmtree(d)
                removed += 1
        except OSError as exc:
            log_error("purge outputs", exc)
    return removed
