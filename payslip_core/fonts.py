"""Fonts used in the PDF. DejaVu Sans is bundled in assets/fonts so nothing has to be installed."""
from __future__ import annotations

from typing import Optional, Set

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .config import ASSETS_DIR

REGULAR, BOLD, ITALIC, BOLD_ITALIC = "PS-Sans", "PS-Sans-Bold", "PS-Sans-Italic", "PS-Sans-BoldItalic"
_registered = False
_covered: Optional[Set[int]] = None


def register_fonts() -> None:
    global _registered, _covered
    if _registered:
        return
    d = ASSETS_DIR / "fonts"
    files = {REGULAR: "DejaVuSans.ttf", BOLD: "DejaVuSans-Bold.ttf",
             ITALIC: "DejaVuSans-Oblique.ttf", BOLD_ITALIC: "DejaVuSans-BoldOblique.ttf"}
    for name, fn in files.items():
        pdfmetrics.registerFont(TTFont(name, str(d / fn)))
    pdfmetrics.registerFontFamily(REGULAR, normal=REGULAR, bold=BOLD, italic=ITALIC, boldItalic=BOLD_ITALIC)
    _covered = set(pdfmetrics.getFont(REGULAR).face.charToGlyph.keys())
    _registered = True


def unsupported_chars(text: str) -> str:
    """Characters in `text` that the PDF font cannot draw (e.g. Devanagari)."""
    register_fonts()
    bad = []
    for ch in text:
        if ch in "\n\r\t":
            continue
        if ord(ch) not in _covered and ch not in bad:
            bad.append(ch)
    return "".join(bad)
