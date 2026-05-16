from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Iterable, List, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="Tiny", parent=styles["Normal"], fontSize=7, leading=9))
    styles.add(ParagraphStyle(name="HeadingBlue", parent=styles["Heading1"], textColor=colors.HexColor("#1f4e79")))
    return styles


def write_pdf(path: Path, title: str, subtitle: str, sections: List[Tuple[str, Iterable[str]]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm)
    story = [Paragraph(title, styles["HeadingBlue"]), Paragraph(subtitle, styles["Normal"]), Spacer(1, 8)]
    search_parts = [title, subtitle]
    for heading, lines in sections:
        story.append(Paragraph(heading, styles["Heading2"]))
        rows = []
        for line in lines:
            search_parts.append(str(line))
            if ":" in str(line):
                k, v = str(line).split(":", 1)
                rows.append([Paragraph(f"<b>{k.strip()}</b>", styles["Small"]), Paragraph(v.strip(), styles["Small"])])
            else:
                story.append(Paragraph(str(line), styles["Small"]))
        if rows:
            table = Table(rows, colWidths=[48*mm, 110*mm])
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f5f7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(table)
        story.append(Spacer(1, 8))
    doc.build(story)
    return "\n".join(search_parts)


def write_scan_image(path: Path, title: str, lines: List[str], width: int = 1650, height: int = 2338, noise: bool = True) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 54)
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 28)
    except Exception:
        font_title = font = font_small = None

    draw.rectangle([70, 70, width-70, height-70], outline=(80, 80, 80), width=3)
    draw.text((110, 115), title, fill=(25, 45, 70), font=font_title)
    y = 230
    for line in lines:
        wrapped = textwrap.wrap(line, width=70)
        for w in wrapped:
            draw.text((120, y), w, fill=(20, 20, 20), font=font)
            y += 56
        y += 18
    draw.text((120, height-160), "Synthetic scanned evidence for preservation container POC", fill=(100, 100, 100), font=font_small)
    if noise:
        # Light deterministic scan artefacts.
        for x in range(0, width, 97):
            draw.line([(x, 80), (x+12, height-80)], fill=(245, 245, 245), width=2)
        image = image.rotate(0.35, expand=False, fillcolor="white").filter(ImageFilter.SMOOTH_MORE)
    image.save(path, quality=92)
    return "\n".join([title] + lines)


def image_to_pdf(image_path: Path, pdf_path: Path, title: str) -> str:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=8*mm, leftMargin=8*mm, topMargin=8*mm, bottomMargin=8*mm)
    styles = _styles()
    img = RLImage(str(image_path), width=190*mm, height=270*mm)
    doc.build([Paragraph(title, styles["Tiny"]), Spacer(1, 2), img])
    return title
