"""PDF payslip drawing with ReportLab (A4, one payslip per page)."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Union

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Image, Paragraph, Table, TableStyle

from .fonts import BOLD, ITALIC, REGULAR, register_fonts
from .models import Payslip
from .util import amount_in_words, fmt_amount

TEAL = colors.HexColor("#16B29D")
TEAL_DARK = colors.HexColor("#0F7F70")
TEAL_LIGHT = colors.HexColor("#E6F6F3")
BLUE = colors.HexColor("#61A2CB")
INK = colors.HexColor("#1F2D3D")
GRAY = colors.HexColor("#6B7785")
LINE = colors.HexColor("#C9D3DC")

PAGE_W, PAGE_H = A4
MARGIN = 14 * mm
PAD = 6 * mm
INNER_W = PAGE_W - 2 * MARGIN - 2 * PAD


@dataclass
class Branding:
    firm_name: str
    address: str = ""
    logo_path: Optional[Path] = None
    grouping: str = "nepali"
    show_pan: bool = False
    show_words: bool = True
    show_attendance: bool = True
    show_signatures: bool = True


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _styles(scale: float):
    def ps(name, size, font=REGULAR, color=INK, align=0, leading=None):
        return ParagraphStyle(name, fontName=font, fontSize=size * scale, textColor=color,
                              alignment=align, leading=(leading or size * 1.28) * scale)
    return {
        "firm": ps("firm", 19, BOLD, TEAL_DARK, leading=23),
        "addr": ps("addr", 8.5, REGULAR, GRAY),
        "label": ps("label", 9.5, REGULAR, INK),
        "labelc": ps("labelc", 8.5, REGULAR, GRAY),
        "amt": ps("amt", 9.5, REGULAR, INK, align=2),
        "hdr": ps("hdr", 9.5, BOLD, colors.white),
        "hdr_r": ps("hdr_r", 9.5, BOLD, colors.white, align=2),
        "tot": ps("tot", 10, BOLD, INK),
        "tot_r": ps("tot_r", 10, BOLD, INK, align=2),
        "muted": ps("muted", 9, ITALIC, GRAY),
        "name": ps("name", 12, BOLD, INK, leading=15),
        "value": ps("value", 10, BOLD, INK),
        "words": ps("words", 9, ITALIC, INK),
        "foot": ps("foot", 7.5, REGULAR, GRAY, align=1),
        "sig": ps("sig", 8.5, REGULAR, GRAY, align=1),
    }


def _logo_flowable(path: Optional[Path], height: float):
    if not path or not Path(path).exists():
        return None
    try:
        w, h = ImageReader(str(path)).getSize()
        return Image(str(path), width=height * w / h, height=height, kind="direct", mask="auto")
    except Exception:
        return None


def _build_blocks(slip: Payslip, month_label: str, b: Branding, scale: float):
    st = _styles(scale)
    blocks: List[tuple] = []   # (flowable, space_after)

    # ---- header: logo + firm name
    logo = _logo_flowable(b.logo_path, 17 * mm * scale if scale < 1 else 17 * mm)
    name_cell = [Paragraph(_esc(b.firm_name), st["firm"])]
    if b.address.strip():
        name_cell.append(Paragraph(_esc(b.address.strip()), st["addr"]))
    logo_w = (logo.drawWidth + 4 * mm) if logo else 0
    header = Table([[logo if logo else "", name_cell]], colWidths=[logo_w or 1, INNER_W - (logo_w or 1)])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 1.4, BLUE),
    ]))
    blocks.append((header, 4 * mm))

    # ---- title band
    band = Table([[Paragraph("PAYSLIP", ParagraphStyle("t", fontName=BOLD, fontSize=14 * scale, textColor=colors.white, leading=17 * scale)),
                   Paragraph(f"Salary Month: {_esc(month_label)}",
                             ParagraphStyle("m", fontName=BOLD, fontSize=11 * scale, textColor=colors.white, alignment=2, leading=14 * scale))]],
                 colWidths=[INNER_W * 0.4, INNER_W * 0.6])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                              ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    blocks.append((band, 4 * mm))

    # ---- employee details
    lab = st["labelc"]
    rows = [[Paragraph("Employee Name", lab), Paragraph(_esc(slip.name), st["name"])]]
    rows.append([Paragraph("Employee ID", lab), Paragraph(_esc(slip.emp_id or "-"), st["value"])])
    if b.show_pan and slip.pan:
        rows.append([Paragraph("PAN No.", lab), Paragraph(_esc(slip.pan), st["value"])])
    emp = Table(rows, colWidths=[32 * mm, INNER_W - 32 * mm])
    emp.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    blocks.append((emp, 3 * mm))

    if b.show_attendance and slip.attendance:
        cells = [[Paragraph(f"{_esc(k)}", ParagraphStyle("ak", fontName=REGULAR, fontSize=7.5 * scale, textColor=GRAY, alignment=1, leading=9 * scale))
                  for k, _ in slip.attendance],
                 [Paragraph(_esc(v), ParagraphStyle("av", fontName=BOLD, fontSize=10 * scale, textColor=INK, alignment=1, leading=12 * scale))
                  for _, v in slip.attendance]]
        n = len(slip.attendance)
        att = Table(cells, colWidths=[INNER_W / n] * n)
        att.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL_LIGHT),
                                 ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        blocks.append((att, 4 * mm))

    # ---- earnings (left) and deductions (right)
    inc, ded = slip.income, slip.deductions
    n = max(len(inc), len(ded), 5)
    gap = 4 * mm
    rest = INNER_W - gap
    cw = [rest * 0.31, rest * 0.19, gap, rest * 0.31, rest * 0.19]
    data = [[Paragraph("EARNINGS / INCOME", st["hdr"]), Paragraph("Amount (Rs.)", st["hdr_r"]), "",
             Paragraph("DEDUCTIONS", st["hdr"]), Paragraph("Amount (Rs.)", st["hdr_r"])]]
    for i in range(n):
        left = (Paragraph(_esc(inc[i].label), st["label"]), Paragraph(fmt_amount(inc[i].amount, b.grouping, ""), st["amt"])) \
            if i < len(inc) else ("", "")
        if i < len(ded):
            right = (Paragraph(_esc(ded[i].label), st["label"]), Paragraph(fmt_amount(ded[i].amount, b.grouping, ""), st["amt"]))
        elif i == 0 and not ded:
            right = (Paragraph("No deductions", st["muted"]), "")
        else:
            right = ("", "")
        data.append([left[0], left[1], "", right[0], right[1]])
    last = len(data)
    data.append([Paragraph("Total Income", st["tot"]), Paragraph(fmt_amount(slip.total_income, b.grouping, ""), st["tot_r"]), "",
                 Paragraph("Total Deductions", st["tot"]), Paragraph(fmt_amount(slip.total_deductions, b.grouping, ""), st["tot_r"])])
    t = Table(data, colWidths=cw)
    style = [
        ("BACKGROUND", (0, 0), (1, 0), TEAL), ("BACKGROUND", (3, 0), (4, 0), TEAL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2 * scale), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2 * scale),
        ("BOX", (0, 0), (1, -1), 0.6, LINE), ("BOX", (3, 0), (4, -1), 0.6, LINE),
        ("LINEBELOW", (0, 1), (1, last - 1), 0.3, colors.HexColor("#E3E9EE")),
        ("LINEBELOW", (3, 1), (4, last - 1), 0.3, colors.HexColor("#E3E9EE")),
        ("BACKGROUND", (0, last), (1, last), TEAL_LIGHT), ("BACKGROUND", (3, last), (4, last), TEAL_LIGHT),
        ("LINEABOVE", (0, last), (1, last), 0.9, TEAL), ("LINEABOVE", (3, last), (4, last), 0.9, TEAL),
        ("LEFTPADDING", (2, 0), (2, -1), 0), ("RIGHTPADDING", (2, 0), (2, -1), 0),
    ]
    t.setStyle(TableStyle(style))
    blocks.append((t, 4 * mm))

    # ---- net salary
    net = Table([[Paragraph("NET SALARY PAYABLE", ParagraphStyle("n1", fontName=BOLD, fontSize=12 * scale, textColor=colors.white, leading=15 * scale)),
                  Paragraph(fmt_amount(slip.net_salary, b.grouping),
                            ParagraphStyle("n2", fontName=BOLD, fontSize=13 * scale, textColor=colors.white, alignment=2, leading=16 * scale))]],
                colWidths=[INNER_W * 0.55, INNER_W * 0.45])
    net.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL_DARK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                             ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    blocks.append((net, 2.5 * mm))
    if b.show_words:
        blocks.append((Paragraph("In words: " + amount_in_words(slip.net_salary), st["words"]), 12 * mm))
    else:
        blocks.append((Paragraph("", st["words"]), 8 * mm))

    if b.show_signatures:
        sig = Table([[Paragraph("Employee Signature", st["sig"]), "", Paragraph("Authorised Signatory", st["sig"])]],
                    colWidths=[INNER_W * 0.34, INNER_W * 0.32, INNER_W * 0.34])
        sig.setStyle(TableStyle([("LINEABOVE", (0, 0), (0, 0), 0.6, GRAY), ("LINEABOVE", (2, 0), (2, 0), 0.6, GRAY),
                                 ("TOPPADDING", (0, 0), (-1, -1), 3)]))
        blocks.append((sig, 6 * mm))
    blocks.append((Paragraph("This is a computer-generated payslip.", st["foot"]), 0))
    return blocks


def draw_payslip(c: rl_canvas.Canvas, slip: Payslip, month_label: str, b: Branding) -> None:
    register_fonts()
    avail = PAGE_H - 2 * MARGIN - 2 * PAD
    blocks = None
    for scale in (1.0, 0.92, 0.84, 0.76, 0.68, 0.6):
        cand = _build_blocks(slip, month_label, b, scale)
        total = 0.0
        for f, after in cand:
            _, h = f.wrap(INNER_W, 10_000)
            total += h + after
        if total <= avail:
            blocks = cand
            break
    if blocks is None:
        raise ValueError(f"The payslip for {slip.name} has too many lines to fit on one A4 page.")

    heights = []
    for f, after in blocks:
        _, h = f.wrap(INNER_W, 10_000)
        heights.append(h)
    content_h = sum(heights) + sum(a for _, a in blocks)
    frame_h = content_h + 2 * PAD
    top = PAGE_H - MARGIN
    c.setStrokeColor(LINE)
    c.setLineWidth(0.8)
    c.roundRect(MARGIN, top - frame_h, PAGE_W - 2 * MARGIN, frame_h, 4 * mm, stroke=1, fill=0)
    y = top - PAD
    x = MARGIN + PAD
    for (f, after), h in zip(blocks, heights):
        f.drawOn(c, x, y - h)
        y -= h + after
    c.showPage()


def _new_canvas(target: Union[str, io.BytesIO], title: str, b: Branding) -> rl_canvas.Canvas:
    register_fonts()
    c = rl_canvas.Canvas(target, pagesize=A4, pageCompression=1)
    c.setTitle(title)
    c.setAuthor(b.firm_name)
    c.setCreator("Payslip Manager")
    return c


def render_payslips(target: Union[str, io.BytesIO], slips: Sequence[Payslip], month_label: str,
                    b: Branding, title: str) -> None:
    c = _new_canvas(target, title, b)
    for s in slips:
        draw_payslip(c, s, month_label, b)
    c.save()
