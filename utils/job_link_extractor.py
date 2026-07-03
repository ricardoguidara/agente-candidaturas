from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Callable
from urllib.parse import urlparse

from utils.job_radar import inferir_plataforma, pontuar_vaga, resumir_html


MIN_TEXT_LENGTH = 500
USER_AGENT = (
    "Mozilla/5.0 (compatible; agente-candidaturas/0.1; "
    "+https://ricardoguidara.com/)"
)

MODELOS = {
    "remoto": "Remoto",
    "remote": "Remoto",
    "híbrido": "Híbrido",
    "hibrido": "Híbrido",
    "hybrid": "Híbrido",
    "presencial": "Presencial",
    "onsite": "Presencial",
}
REGIMES = {
    "clt": "CLT",
    "pj": "PJ",
    "freelancer": "Freelancer",
    "freelance": "Freelancer",
    "temporário": "Temporário",
    "temporario": "Temporário",
    "temporary": "Temporário",
}
SENIORIDADES = {
    "coordenador": "Coordenador",
    "coordinator": "Coordenador",
    "gerente": "Gerente",
    "manager": "Gerente",
    "head": "Head",
    "diretor": "Diretor",
    "director": "Diretor",
    "lead": "Lead",
    "sênior": "Sênior",
    "senior": "Sênior",
}
AREAS = {
    "criação": "Criação",
    "criacao": "Criação",
    "creative": "Criação",
    "marketing": "Marketing",
    "conteúdo": "Conteúdo",
    "conteudo": "Conteúdo",
    "content": "Conteúdo",
    "comunicação": "Comunicação",
    "comunicacao": "Comunicação",
    "communication": "Comunicação",
    "audiovisual": "Audiovisual",
    "video": "Audiovisual",
    "ia": "IA",
    "ai": "IA",
    "generative ai": "IA",
    "creative operations": "Creative Operations",
}


def identificar_plataforma(url: str) -> str:
    plataforma = inferir_plataforma(url)
    if plataforma:
        return plataforma
    host = urlparse(url or "").netloc.lower()
    if "workable.com" in host:
        return "Workable"
    if "indeed." in host:
        return "Indeed"
    if host:
        return "Site próprio"
    return "Outro"


def _primeiro_match(texto: str, opcoes: dict[str, str], fallback: str = "Não informado") -> str:
    texto_lower = (texto or "").lower()
    for chave, valor in opcoes.items():
        if chave in texto_lower:
            return valor
    return fallback


def normalizar_campos(vaga: dict[str, Any]) -> dict[str, Any]:
    texto = " ".join(
        str(vaga.get(campo, ""))
        for campo in ["cargo", "descricao_vaga", "descricao_resumida", "local", "modelo", "regime", "senioridade", "area_principal"]
    )
    vaga["modelo"] = _normalizar_valor(vaga.get("modelo"), MODELOS, texto)
    vaga["regime"] = _normalizar_valor(vaga.get("regime"), REGIMES, texto)
    vaga["senioridade"] = _normalizar_valor(vaga.get("senioridade"), SENIORIDADES, texto)
    vaga["area_principal"] = _normalizar_valor(vaga.get("area_principal"), AREAS, texto)
    return vaga


def _normalizar_valor(valor: Any, mapa: dict[str, str], texto_fallback: str) -> str:
    valor_texto = str(valor or "").strip()
    if valor_texto:
        normalizado = _primeiro_match(valor_texto, mapa, "")
        if normalizado:
            return normalizado
    return _primeiro_match(texto_fallback, mapa)


def _baixar_html(url: str) -> tuple[str, str]:
    import requests

    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
    )
    response.raise_for_status()
    return response.text, response.url


def _json_ld_jobs(soup: BeautifulSoup) -> list[dict[str, Any]]:
    jobs = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        texto = script.string or script.get_text()
        if not texto:
            continue
        try:
            payload = json.loads(texto)
        except json.JSONDecodeError:
            continue
        itens = payload if isinstance(payload, list) else [payload]
        for item in itens:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                jobs.append(item)
            graph = item.get("@graph") if isinstance(item, dict) else None
            if isinstance(graph, list):
                jobs.extend(node for node in graph if isinstance(node, dict) and node.get("@type") == "JobPosting")
    return jobs


def _meta(soup: BeautifulSoup, *nomes: str) -> str:
    for nome in nomes:
        tag = soup.find("meta", attrs={"property": nome}) or soup.find("meta", attrs={"name": nome})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def _texto_principal(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    candidatos = [
        soup.find("main"),
        soup.find(attrs={"role": "main"}),
        soup.find("article"),
        soup.body,
    ]
    for candidato in candidatos:
        if candidato:
            texto = re.sub(r"\s+", " ", candidato.get_text(" ")).strip()
            if len(texto) >= MIN_TEXT_LENGTH:
                return texto[:12000]
    return ""


def _extrair_basico(url: str, html: str, final_url: str) -> dict[str, Any]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    plataforma = identificar_plataforma(final_url or url)
    jobs = _json_ld_jobs(soup)

    if jobs:
        job = jobs[0]
        org = job.get("hiringOrganization", {})
        local = job.get("jobLocation", {})
        if isinstance(local, list):
            local = local[0] if local else {}
        endereco = local.get("address", {}) if isinstance(local, dict) else {}
        descricao = resumir_html(job.get("description", ""), 5000)
        return {
            "empresa": org.get("name", "") if isinstance(org, dict) else "",
            "cargo": job.get("title", ""),
            "plataforma": plataforma,
            "link": final_url or url,
            "local": endereco.get("addressLocality", "") if isinstance(endereco, dict) else "",
            "modelo": "Remoto" if job.get("jobLocationType") == "TELECOMMUTE" else "",
            "regime": job.get("employmentType", ""),
            "senioridade": "",
            "area_principal": "",
            "descricao_vaga": descricao,
            "descricao_resumida": resumir_html(descricao, 700),
            "fonte": "Link manual",
            "status_extracao": "sucesso" if len(descricao) >= MIN_TEXT_LENGTH else "parcial",
            "observacoes_extracao": "Dados extraídos de JSON-LD JobPosting.",
            "_texto_extraido": descricao,
        }

    titulo = _meta(soup, "og:title", "twitter:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    descricao_meta = _meta(soup, "description", "og:description", "twitter:description")
    texto = _texto_principal(soup)
    descricao = texto or descricao_meta
    status = "sucesso" if len(descricao) >= MIN_TEXT_LENGTH else "precisa_descricao"
    return {
        "empresa": _meta(soup, "og:site_name"),
        "cargo": titulo,
        "plataforma": plataforma,
        "link": final_url or url,
        "local": "",
        "modelo": "",
        "regime": "",
        "senioridade": "",
        "area_principal": "",
        "descricao_vaga": descricao,
        "descricao_resumida": resumir_html(descricao_meta or descricao, 700),
        "fonte": "Link manual",
        "status_extracao": status,
        "observacoes_extracao": (
            "Texto público extraído da página." if status != "precisa_descricao"
            else "Não foi possível extrair descrição suficiente da página pública. Cole a descrição manualmente."
        ),
        "_texto_extraido": descricao,
    }


def _mesclar_estruturado(base: dict[str, Any], estruturado: dict[str, Any]) -> dict[str, Any]:
    for chave in [
        "empresa",
        "cargo",
        "local",
        "modelo",
        "regime",
        "senioridade",
        "area_principal",
        "descricao_vaga",
        "descricao_resumida",
    ]:
        valor = estruturado.get(chave)
        if valor:
            base[chave] = valor
    return base


def extrair_dados_link(
    url: str,
    estruturador: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        html, final_url = _baixar_html(url)
        dados = _extrair_basico(url, html, final_url)
    except Exception as exc:
        dados = {
            "empresa": "",
            "cargo": "",
            "plataforma": identificar_plataforma(url),
            "link": url,
            "local": "",
            "modelo": "Não informado",
            "regime": "Não informado",
            "senioridade": "Não informado",
            "area_principal": "Não informado",
            "descricao_vaga": "",
            "descricao_resumida": "",
            "fonte": "Link manual",
            "status_extracao": "precisa_descricao",
            "observacoes_extracao": f"Página pública indisponível ou bloqueada: {exc}. Cole a descrição manualmente.",
            "_texto_extraido": "",
        }

    texto = dados.get("_texto_extraido", "")
    if estruturador and len(texto) >= MIN_TEXT_LENGTH:
        try:
            dados = _mesclar_estruturado(dados, estruturador(texto))
            if dados.get("status_extracao") == "precisa_descricao":
                dados["status_extracao"] = "parcial"
        except Exception as exc:
            dados["observacoes_extracao"] = (
                f"{dados.get('observacoes_extracao', '')} Estruturação por IA indisponível: {exc}"
            ).strip()

    dados = normalizar_campos(dados)
    score, motivo, red_flags = pontuar_vaga(
        {
            "cargo": dados.get("cargo", ""),
            "empresa": dados.get("empresa", ""),
            "descricao": dados.get("descricao_vaga", ""),
            "local": dados.get("local", ""),
            "modelo": dados.get("modelo", ""),
            "regime": dados.get("regime", ""),
            "senioridade": dados.get("senioridade", ""),
            "area_principal": dados.get("area_principal", ""),
        }
    )
    dados["score_preliminar"] = score
    dados["motivo"] = motivo
    dados["red_flags"] = red_flags
    dados["data_busca"] = date.today().isoformat()
    dados.pop("_texto_extraido", None)
    return dados


def prompt_estruturacao_link(url: str, plataforma: str, texto: str) -> str:
    return f"""
Extraia campos estruturados da vaga abaixo. Não invente dados ausentes.

URL: {url}
Plataforma: {plataforma}

Texto público extraído:
{texto[:10000]}

Responda apenas JSON válido com:
{{
  "empresa": "",
  "cargo": "",
  "local": "",
  "modelo": "Remoto | Híbrido | Presencial | Não informado",
  "regime": "CLT | PJ | Freelancer | Temporário | Não informado",
  "senioridade": "Coordenador | Gerente | Head | Diretor | Lead | Sênior | Não informado",
  "area_principal": "Criação | Marketing | Conteúdo | Comunicação | Audiovisual | IA | Creative Operations | Não informado",
  "descricao_vaga": "",
  "descricao_resumida": ""
}}
""".strip()
