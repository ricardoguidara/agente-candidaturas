from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#111827"),
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4B5563"),
            spaceAfter=14,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#111827"),
            spaceAfter=7,
        ),
        "heading": ParagraphStyle(
            "Heading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#111827"),
            spaceBefore=9,
            spaceAfter=5,
        ),
    }


def _normalizar_linha(linha: str) -> str:
    linha = linha.strip()
    if linha.startswith("#"):
        return linha.lstrip("#").strip()
    if linha.startswith("- "):
        return f"• {linha[2:].strip()}"
    return linha


def gerar_cv_pdf(nome: str, cargo_alvo: str, texto_cv: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.7 * cm,
        leftMargin=1.7 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"CV {nome}",
        author=nome,
    )
    styles = _styles()
    story = [
        Paragraph(nome, styles["title"]),
        Paragraph(f"CV direcionado para {cargo_alvo}", styles["subtitle"]),
    ]

    for bloco in texto_cv.split("\n"):
        linha = _normalizar_linha(bloco)
        if not linha:
            story.append(Spacer(1, 5))
            continue
        estilo = styles["heading"] if len(linha) <= 48 and not linha.endswith(".") else styles["body"]
        story.append(Paragraph(linha, estilo))

    doc.build(story)
    return buffer.getvalue()
