"""Optional: recalculate formulas with a local LibreOffice when the workbook has no cached results."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


def libreoffice_path() -> Optional[str]:
    return shutil.which("soffice") or shutil.which("libreoffice")


def recalculate(data: bytes, timeout: int = 120) -> Optional[bytes]:
    """Return a recalculated copy of the workbook bytes, or None if that is not possible.
    Everything happens in a temporary folder on this computer that is deleted afterwards."""
    exe = libreoffice_path()
    if not exe:
        return None
    with tempfile.TemporaryDirectory(prefix="payslip_recalc_") as tmp:
        tmpdir = Path(tmp)
        src = tmpdir / "in" / "workbook.xlsx"
        out = tmpdir / "out"
        src.parent.mkdir()
        out.mkdir()
        src.write_bytes(data)
        profile = tmpdir / "profile"
        cmd = [exe, f"-env:UserInstallation=file://{profile}", "--headless", "--norestore",
               "--calc", "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out), str(src)]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=timeout, check=True)
        except (subprocess.SubprocessError, OSError):
            return None
        result = out / "workbook.xlsx"
        if result.exists() and result.stat().st_size > 0:
            return result.read_bytes()
    return None
