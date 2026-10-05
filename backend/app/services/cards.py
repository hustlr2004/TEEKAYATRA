from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO
from typing import Dict, Iterable, List, Optional

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Child, Dose, VaccineSchedule
from .schedule import next_visit


HELPLINE = "National Health Helpline: 104 / Childline: 1098"
SIDE_EFFECTS = "Mild fever, swelling or pain can happen. Seek urgent help for breathing trouble, high fever, fits, or severe rash."
SIDE_EFFECTS_HI = "Halka bukhar, sujan ya dard ho sakta hai. Saans ki takleef, tez bukhar, daure, ya gambhir daane par turant madad lein."


@dataclass(frozen=True)
class MilestoneRow:
    label: str
    label_hi: str
    due_days: int
    vaccines: List[VaccineSchedule]

    @property
    def due_label(self) -> str:
        if self.due_days == 0:
            return "At birth"
        if self.due_days < 365:
            return "%s days" % self.due_days
        years = round(self.due_days / 365)
        return "%s years" % years


def vaccination_card_pdf(db: Session, child: Optional[Child]) -> bytes:
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A5)
    width, height = A5
    rows = milestone_rows(db)
    dose_by_code = {dose.vaccine_code: dose for dose in child.doses} if child is not None else {}

    _draw_background(canvas, width, height)
    _draw_fold_line(canvas, width, height)
    _draw_header(canvas, child, width, height)
    _draw_child_details(canvas, child, width, height)
    _draw_next_visit(canvas, child, width, height)
    _draw_qr(canvas, "child:%s" % child.id if child is not None else "blank-template", width - 34 * mm, height - 43 * mm)
    _draw_tree(canvas, rows, dose_by_code, width - 45 * mm, height - 84 * mm)
    _draw_milestone_table(canvas, child, rows, dose_by_code, 6 * mm, height - 94 * mm, width - 12 * mm)
    _draw_footer_panels(canvas, width, height)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def milestone_rows(db: Session) -> List[MilestoneRow]:
    schedules = list(db.scalars(select(VaccineSchedule).order_by(VaccineSchedule.age_due_days, VaccineSchedule.vaccine_code)).all())
    grouped: Dict[int, List[VaccineSchedule]] = {}
    for schedule in schedules:
        due_days = 670 if schedule.vaccine_code.startswith("VITA_") and schedule.vaccine_code != "VITA_1" and schedule.vaccine_code != "VITA_2" else schedule.age_due_days
        grouped.setdefault(due_days, []).append(schedule)
    return [
        MilestoneRow(label=_milestone_label(days), label_hi=_milestone_label_hi(days), due_days=days, vaccines=items)
        for days, items in sorted(grouped.items())
    ]


def _draw_background(canvas: Canvas, width: float, height: float) -> None:
    canvas.setFillColor(colors.HexColor("#fffdf2"))
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#b8c7a6"))
    canvas.setLineWidth(0.7)
    canvas.roundRect(6 * mm, 6 * mm, width - 12 * mm, height - 12 * mm, 4 * mm, fill=0)


def _draw_fold_line(canvas: Canvas, width: float, height: float) -> None:
    canvas.setDash(3, 3)
    canvas.setStrokeColor(colors.HexColor("#8a9b80"))
    canvas.line(8 * mm, height / 2, width - 8 * mm, height / 2)
    canvas.setDash()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#5d6a58"))
    canvas.drawRightString(width - 8 * mm, height / 2 + 2 * mm, "fold / modo")


def _draw_header(canvas: Canvas, child: Optional[Child], width: float, height: float) -> None:
    canvas.setFillColor(colors.HexColor("#14532d"))
    canvas.roundRect(8 * mm, height - 24 * mm, width - 16 * mm, 15 * mm, 3 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(12 * mm, height - 18 * mm, "Teeka Yatra Vaccination Card")
    canvas.setFont("Helvetica", 9)
    canvas.drawString(12 * mm, height - 22 * mm, "Tika record card / Teeka record card")
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawRightString(width - 38 * mm, height - 16 * mm, "ID: %s" % (child.id if child is not None else "________"))


def _draw_child_details(canvas: Canvas, child: Optional[Child], width: float, height: float) -> None:
    x = 8 * mm
    y = height - 58 * mm
    w = 86 * mm
    canvas.setStrokeColor(colors.HexColor("#718063"))
    canvas.setFillColor(colors.HexColor("#f3f8ec"))
    canvas.roundRect(x, y, w, 24 * mm, 3 * mm, fill=1, stroke=1)
    canvas.setFillColor(colors.HexColor("#17231d"))
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(x + 4 * mm, y + 18 * mm, "Child details / Bacche ki jankari")
    fields = [
        ("Name / Naam", "________________" if child is None else "Child %s" % child.id),
        ("DOB / Janm", "__________" if child is None else child.dob.isoformat()),
        ("Sex / Ling", "____" if child is None else child.sex.value),
        ("Village / Gaon", "________________" if child is None or child.village is None else child.village.block),
    ]
    canvas.setFont("Helvetica", 7.5)
    for index, (label, value) in enumerate(fields):
        row_y = y + (13 - index * 4) * mm
        canvas.drawString(x + 4 * mm, row_y, label)
        canvas.drawString(x + 26 * mm, row_y, value)


def _draw_next_visit(canvas: Canvas, child: Optional[Child], width: float, height: float) -> None:
    x = 8 * mm
    y = height - 86 * mm
    w = 86 * mm
    visit_text = "Next visit / Agli mulaqat: __________"
    vaccine_text = "Vaccines / Tike: __________________"
    if child is not None:
        plan = next_visit(child)
        if plan.visit_on is not None:
            visit_text = "Next visit / Agli mulaqat: %s" % plan.visit_on.isoformat()
            vaccine_text = "Vaccines / Tike: %s" % ", ".join(item.name for item in plan.vaccines[:3])
    canvas.setFillColor(colors.HexColor("#fff7d1"))
    canvas.roundRect(x, y, w, 24 * mm, 3 * mm, fill=1, stroke=1)
    canvas.setFillColor(colors.HexColor("#3b2d0b"))
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(x + 4 * mm, y + 17 * mm, "Next visit box")
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(x + 4 * mm, y + 11 * mm, _shorten(visit_text, 52))
    canvas.drawString(x + 4 * mm, y + 6 * mm, _shorten(vaccine_text, 56))


def _draw_qr(canvas: Canvas, payload: str, x: float, y: float) -> None:
    image = qrcode.make(payload)
    canvas.drawInlineImage(image, x, y, 23 * mm, 23 * mm)
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(colors.HexColor("#26342b"))
    canvas.drawCentredString(x + 11.5 * mm, y - 2 * mm, "QR: child ID only")


def _draw_tree(canvas: Canvas, rows: List[MilestoneRow], dose_by_code: Dict[str, Dose], x: float, y: float) -> None:
    canvas.setStrokeColor(colors.HexColor("#6b4f2a"))
    canvas.setFillColor(colors.HexColor("#8a5a2b"))
    canvas.rect(x + 13 * mm, y, 5 * mm, 19 * mm, fill=1, stroke=0)
    positions = [
        (9, 17), (19, 18), (3, 26), (14, 28), (24, 26), (7, 36), (20, 38),
        (1, 47), (14, 49), (26, 47),
    ]
    complete_codes = set(dose_by_code)
    for index, (dx, dy) in enumerate(positions[: len(rows)]):
        row = rows[index]
        complete = all(vaccine.vaccine_code in complete_codes for vaccine in row.vaccines)
        canvas.setFillColor(colors.HexColor("#2f9e44") if complete else colors.white)
        canvas.setStrokeColor(colors.HexColor("#2f9e44"))
        canvas.ellipse(x + dx * mm, y + dy * mm, x + (dx + 7) * mm, y + (dy + 4.5) * mm, fill=1, stroke=1)


def _draw_milestone_table(
    canvas: Canvas,
    child: Optional[Child],
    rows: List[MilestoneRow],
    dose_by_code: Dict[str, Dose],
    x: float,
    top: float,
    width: float,
) -> None:
    col_widths = [19 * mm, 38 * mm, 17 * mm, 16 * mm, 14 * mm, 16 * mm, 16 * mm]
    headers = ["Milestone\nUmar", "Vaccines\nTike", "Due\nTareekh", "Date\nDiwas", "Batch", "Stamp\nMohar", "Sign\nHastakshar"]
    row_h = 7.5 * mm
    canvas.setFont("Helvetica-Bold", 6.6)
    current_y = top
    canvas.setFillColor(colors.HexColor("#e6f2dd"))
    canvas.rect(x, current_y, width, row_h, fill=1, stroke=0)
    cell_x = x
    for header, col_w in zip(headers, col_widths):
        canvas.setFillColor(colors.HexColor("#17231d"))
        _draw_wrapped(canvas, header, cell_x + 1 * mm, current_y + 1.6 * mm, col_w - 2 * mm, 2.5 * mm, "Helvetica-Bold", 5.8)
        cell_x += col_w
    canvas.setStrokeColor(colors.HexColor("#566650"))
    canvas.rect(x, current_y, width, row_h, fill=0, stroke=1)
    current_y -= row_h

    canvas.setFont("Helvetica", 5.8)
    for row in rows[:10]:
        due = "____" if child is None else (child.dob + timedelta(days=row.due_days)).isoformat()
        values = [
            "%s / %s" % (row.label, row.label_hi),
            ", ".join(vaccine.name for vaccine in row.vaccines),
            due,
            "",
            "",
            "",
            "",
        ]
        canvas.setFillColor(colors.white)
        canvas.rect(x, current_y, width, row_h, fill=1, stroke=0)
        cell_x = x
        for index, (value, col_w) in enumerate(zip(values, col_widths)):
            canvas.setStrokeColor(colors.HexColor("#9cab91"))
            canvas.rect(cell_x, current_y, col_w, row_h, fill=0, stroke=1)
            if index == 1:
                _draw_leaf_marks(canvas, row, dose_by_code, cell_x + col_w - 10 * mm, current_y + 1.5 * mm)
            canvas.setFillColor(colors.HexColor("#17231d"))
            _draw_wrapped(canvas, value, cell_x + 1 * mm, current_y + 1.5 * mm, col_w - 2 * mm, 2.4 * mm, "Helvetica", 5.2)
            cell_x += col_w
        current_y -= row_h


def _draw_leaf_marks(canvas: Canvas, row: MilestoneRow, dose_by_code: Dict[str, Dose], x: float, y: float) -> None:
    for index, vaccine in enumerate(row.vaccines[:4]):
        complete = vaccine.vaccine_code in dose_by_code
        canvas.setFillColor(colors.HexColor("#2f9e44") if complete else colors.white)
        canvas.setStrokeColor(colors.HexColor("#2f9e44"))
        canvas.ellipse(x + index * 2.1 * mm, y, x + (index * 2.1 + 1.7) * mm, y + 1.3 * mm, fill=1, stroke=1)


def _draw_footer_panels(canvas: Canvas, width: float, height: float) -> None:
    panel_y = 7 * mm
    panel_h = 24 * mm
    left_x = 7 * mm
    right_x = width / 2 + 3 * mm
    panel_w = width / 2 - 10 * mm
    for x, title, body, fill in [
        (left_x, "Helpline / Madad", HELPLINE, "#e6f2ff"),
        (right_x, "Side effects / Savdhani", "%s %s" % (SIDE_EFFECTS, SIDE_EFFECTS_HI), "#ffe9df"),
    ]:
        canvas.setFillColor(colors.HexColor(fill))
        canvas.roundRect(x, panel_y, panel_w, panel_h, 3 * mm, fill=1, stroke=1)
        canvas.setFillColor(colors.HexColor("#17231d"))
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(x + 4 * mm, panel_y + 12 * mm, title)
        _draw_wrapped(canvas, body, x + 4 * mm, panel_y + 4 * mm, panel_w - 8 * mm, 3 * mm, "Helvetica", 6.2)


def _draw_wrapped(canvas: Canvas, text: str, x: float, y: float, width: float, line_height: float, font: str, size: float) -> None:
    canvas.setFont(font, size)
    words = text.split()
    line = ""
    lines: List[str] = []
    for word in words:
        candidate = ("%s %s" % (line, word)).strip()
        if canvas.stringWidth(candidate, font, size) <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    for index, line_text in enumerate(lines[:3]):
        canvas.drawString(x, y + line_height * (2 - index), line_text)


def _milestone_label(days: int) -> str:
    labels = {
        0: "Birth",
        42: "6 weeks",
        70: "10 weeks",
        98: "14 weeks",
        274: "9-11 months",
        487: "16-23 months",
        670: "Vitamin A 6-monthly",
        1826: "5-6 years",
        3652: "10 years",
        5844: "16 years",
    }
    if days in labels:
        return labels[days]
    return "Vitamin A"


def _milestone_label_hi(days: int) -> str:
    labels = {
        0: "Janm",
        42: "6 hafte",
        70: "10 hafte",
        98: "14 hafte",
        274: "9-11 mahine",
        487: "16-23 mahine",
        670: "Vitamin A 6 mahine",
        1826: "5-6 saal",
        3652: "10 saal",
        5844: "16 saal",
    }
    return labels.get(days, "Vitamin A")


def _shorten(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."
