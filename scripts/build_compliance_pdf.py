"""从合规声明 Markdown 生成比赛提交用 PDF。"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "submission" / "05-伦理与安全合规性声明.md"
OUTPUT = ROOT / "output" / "pdf" / "05-伦理与安全合规性声明.pdf"
FONT_NAME = "ComplianceChinese"


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(FONT_NAME, 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(18 * mm, 10 * mm, "油训智安 · 伦理与安全合规性声明")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build() -> Path:
    global FONT_NAME
    embedded_font = Path("C:/Windows/Fonts/simhei.ttf")
    if embedded_font.exists():
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(embedded_font)))
    else:
        FONT_NAME = "STSong-Light"
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ChineseTitle",
        parent=styles["Title"],
        fontName=FONT_NAME,
        fontSize=20,
        leading=28,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0B5F6B"),
        spaceAfter=8 * mm,
    )
    heading = ParagraphStyle(
        "ChineseHeading",
        parent=styles["Heading2"],
        fontName=FONT_NAME,
        fontSize=13,
        leading=19,
        textColor=colors.HexColor("#0B5F6B"),
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
        keepWithNext=True,
    )
    body = ParagraphStyle(
        "ChineseBody",
        parent=styles["BodyText"],
        fontName=FONT_NAME,
        fontSize=10.5,
        leading=17,
        textColor=colors.HexColor("#1D2939"),
        spaceAfter=2.2 * mm,
        wordWrap="CJK",
    )
    bullet = ParagraphStyle(
        "ChineseBullet",
        parent=body,
        leftIndent=6 * mm,
        firstLineIndent=-4 * mm,
        bulletIndent=1 * mm,
        spaceAfter=1.6 * mm,
    )
    note = ParagraphStyle(
        "ChineseNote",
        parent=body,
        fontSize=9,
        leading=15,
        textColor=colors.HexColor("#7A2E0E"),
        backColor=colors.HexColor("#FFF4E5"),
        borderColor=colors.HexColor("#F5C278"),
        borderWidth=0.5,
        borderPadding=7,
        spaceBefore=3 * mm,
    )

    story = []
    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        elif line.startswith("# "):
            story.append(Paragraph(escape(line[2:]), title))
        elif line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), heading))
        elif line.startswith("- "):
            story.append(Paragraph("· " + escape(line[2:]), bullet))
        elif line.startswith("> "):
            story.append(Paragraph(escape(line[2:]), note))
        else:
            story.append(Paragraph(escape(line), body))

    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=18 * mm,
        title="伦理与安全合规性声明",
        author="油训智安项目团队",
        subject="比赛提交合规材料",
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return OUTPUT


if __name__ == "__main__":
    print(build())
