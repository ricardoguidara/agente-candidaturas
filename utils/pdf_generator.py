from __future__ import annotations

import html
import re
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


SECOES_CONHECIDAS = {
    "resumo profissional",
    "competências-chave",
    "competencias-chave",
    "competências",
    "competencias",
    "experiência profissional relevante",
    "experiencia profissional relevante",
    "experiência profissional",
    "experiencia profissional",
    "clientes e projetos selecionados",
    "clientes",
    "projetos selecionados",
    "formação",
    "formacao",
    "ferramentas",
    "idiomas",
}

PADROES_META_CV = [
    "este cv foi elaborado",
    "cv direcionado",
    "expectativa salarial",
    "documento adaptado",
    "observações sobre a vaga",
    "observacoes sobre a vaga",
]


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "Name",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#111827"),
            spaceAfter=5,
        ),
        "headline": ParagraphStyle(
            "Headline",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#374151"),
            spaceAfter=5,
        ),
        "contact": ParagraphStyle(
            "Contact",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=11,
            textColor=colors.HexColor("#4B5563"),
            spaceAfter=8,
        ),
        "section": ParagraphStyle(
            "Section",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=14,
            textColor=colors.HexColor("#111827"),
            spaceBefore=9,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.6,
            leading=13,
            textColor=colors.HexColor("#111827"),
            spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.4,
            leading=12.5,
            leftIndent=12,
            firstLineIndent=-6,
            textColor=colors.HexColor("#111827"),
            spaceAfter=3,
        ),
    }


def _limpar_markdown_linha(linha: str) -> str:
    linha = linha.strip()
    linha = re.sub(r"^#{1,6}\s*", "", linha)
    linha = linha.replace("**", "").replace("__", "")
    linha = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1: \2", linha)
    linha = re.sub(r"^\s*[-*_]{3,}\s*$", "", linha)
    linha = linha.replace("https://ricardoguidara.com/(https://ricardoguidara.com/)", "https://ricardoguidara.com/")
    return linha.strip()


def _linha_meta_ou_salarial(linha: str) -> bool:
    texto = linha.lower()
    return any(padrao in texto for padrao in PADROES_META_CV)


def _normalizar_linha(linha: str) -> tuple[str, bool]:
    linha = _limpar_markdown_linha(linha)
    if not linha or _linha_meta_ou_salarial(linha):
        return "", False

    bullet = False
    if re.match(r"^[-•]\s+", linha):
        bullet = True
        linha = re.sub(r"^[-•]\s+", "", linha).strip()

    linha = linha.replace("LinkedIn::", "LinkedIn:")
    linha = linha.replace("Portfolio::", "Portfolio:")
    return linha, bullet


def _eh_secao(linha: str) -> bool:
    texto = linha.strip().rstrip(":").lower()
    if texto in SECOES_CONHECIDAS:
        return True
    return len(linha) <= 42 and not linha.endswith(".") and ":" not in linha


def _escape(texto: str) -> str:
    return html.escape(texto, quote=False)


def _linhas_limpas(texto_cv: str) -> list[tuple[str, bool]]:
    linhas = []
    for bloco in texto_cv.splitlines():
        linha, bullet = _normalizar_linha(bloco)
        if linha:
            linhas.append((linha, bullet))
    return linhas


def gerar_cv_pdf(nome: str, cargo_alvo: str, texto_cv: str) -> bytes:
    _ = cargo_alvo
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.6 * cm,
        leftMargin=1.6 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title=f"CV {nome}",
        author=nome,
    )
    styles = _styles()
    story = []
    linhas = _linhas_limpas(texto_cv)

    if linhas and linhas[0][0].strip().lower() == nome.lower():
        story.append(Paragraph(_escape(linhas.pop(0)[0]), styles["name"]))
    else:
        story.append(Paragraph(_escape(nome), styles["name"]))

    headline_consumed = False
    for linha, bullet in linhas:
        if bullet:
            story.append(Paragraph(_escape(linha), styles["bullet"], bulletText="•"))
            continue

        if (
            "linkedin:" in linha.lower()
            or "portfolio:" in linha.lower()
            or "são paulo" in linha.lower()
            or "sao paulo" in linha.lower()
        ):
            story.append(Paragraph(_escape(linha), styles["contact"]))
            continue

        if _eh_secao(linha):
            story.append(Paragraph(_escape(linha.rstrip(":")), styles["section"]))
            continue

        if not headline_consumed:
            story.append(Paragraph(_escape(linha), styles["headline"]))
            headline_consumed = True
            story.append(Spacer(1, 3))
        else:
            story.append(Paragraph(_escape(linha), styles["body"]))

    doc.build(story)
    return buffer.getvalue()
