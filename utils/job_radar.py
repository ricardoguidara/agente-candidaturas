from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from html import unescape
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import urlopen


TERMOS_PRIORITARIOS = {
    "ai creative director": 28,
    "creative director": 24,
    "head of creative": 24,
    "head de criação": 24,
    "head de criacao": 24,
    "creative lead": 20,
    "gerente de criação": 20,
    "gerente de criacao": 20,
    "gerente de marketing": 18,
    "gerente de conteúdo": 18,
    "gerente de conteudo": 18,
    "content lead": 18,
    "creative operations lead": 22,
    "brand content manager": 18,
    "head of content": 20,
}

SINAIS_ESTRATEGICOS = {
    "liderança": 8,
    "lideranca": 8,
    "strategy": 8,
    "estratégia": 8,
    "estrategia": 8,
    "generative ai": 10,
    "ia generativa": 10,
    "creative operations": 10,
    "storytelling": 8,
    "branding": 7,
    "brand": 6,
    "marketing": 5,
    "content": 5,
    "conteúdo": 5,
    "conteudo": 5,
    "audiovisual": 5,
}

TERMOS_NEGATIVOS = {
    "designer gráfico": 25,
    "designer grafico": 25,
    "social media": 20,
    "motion designer": 22,
    "editor de vídeo": 22,
    "editor de video": 22,
    "tráfego pago": 20,
    "trafego pago": 20,
    "analista júnior": 18,
    "analista junior": 18,
    "analista pleno": 12,
}


def gerar_id_vaga(empresa: str, cargo: str, link: str = "") -> str:
    base = f"{empresa}|{cargo}|{link}".lower().strip()
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"radar-{digest}"


def inferir_plataforma(link: str) -> str:
    host = urlparse(link or "").netloc.lower()
    if "greenhouse.io" in host:
        return "Greenhouse"
    if "lever.co" in host:
        return "Lever"
    if "gupy.io" in host:
        return "Gupy"
    if "adzuna" in host:
        return "Adzuna"
    if "linkedin.com" in host:
        return "LinkedIn"
    if not host:
        return ""
    return host.replace("www.", "")


def pontuar_vaga(vaga: dict[str, Any]) -> tuple[int, str, str]:
    texto = " ".join(
        str(vaga.get(campo, ""))
        for campo in [
            "cargo",
            "empresa",
            "descricao",
            "descricao_resumida",
            "local",
            "modelo",
            "regime",
            "senioridade",
            "area_principal",
        ]
    ).lower()

    score = 35
    motivos = []
    red_flags = []

    for termo, pontos in TERMOS_PRIORITARIOS.items():
        if termo in texto:
            score += pontos
            motivos.append(f"Aderente a {termo}.")

    for termo, pontos in SINAIS_ESTRATEGICOS.items():
        if termo in texto:
            score += pontos

    if "remoto" in texto or "remote" in texto:
        score += 10
        motivos.append("Modelo remoto.")
    if "híbrido" in texto or "hibrido" in texto or "hybrid" in texto:
        score += 6
        motivos.append("Modelo híbrido.")

    for termo, pontos in TERMOS_NEGATIVOS.items():
        if termo in texto:
            score -= pontos
            red_flags.append(f"Sinal operacional: {termo}.")

    if "presencial" in texto and not any(s in texto for s in ["sênior", "senior", "lead", "head", "gerente"]):
        score -= 12
        red_flags.append("Presencial rígido sem senioridade clara.")

    score = max(0, min(100, score))
    motivo = " ".join(motivos) or "Aderência preliminar calculada por palavras-chave."
    return score, motivo, " ".join(red_flags)


def resumir_html(texto: str, limite: int = 700) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    texto = unescape(re.sub(r"\s+", " ", texto)).strip()
    return texto[:limite]


def normalizar_para_radar(vaga: dict[str, Any], fonte: str) -> dict[str, Any]:
    score, motivo, red_flags = pontuar_vaga(vaga)
    return {
        "data_busca": date.today().isoformat(),
        "fonte": fonte,
        "empresa": vaga.get("empresa", ""),
        "cargo": vaga.get("cargo", ""),
        "link": vaga.get("link", ""),
        "local": vaga.get("local", ""),
        "modelo": vaga.get("modelo", ""),
        "regime": vaga.get("regime", ""),
        "senioridade": vaga.get("senioridade", ""),
        "area_principal": vaga.get("area_principal", ""),
        "descricao_resumida": resumir_html(vaga.get("descricao", vaga.get("descricao_resumida", ""))),
        "score_preliminar": score,
        "motivo": motivo,
        "red_flags": red_flags,
        "status_radar": "Novo",
    }


def buscar_adzuna(
    app_id: str,
    app_key: str,
    termo: str,
    pais: str = "br",
    local: str = "",
    quantidade: int = 10,
) -> list[dict[str, Any]]:
    encoded_termo = quote(termo)
    encoded_local = quote(local)
    url = (
        f"https://api.adzuna.com/v1/api/jobs/{pais}/search/1"
        f"?app_id={quote(app_id)}&app_key={quote(app_key)}"
        f"&results_per_page={int(quantidade)}&what={encoded_termo}&where={encoded_local}"
        "&content-type=application/json"
    )
    with urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    resultados = []
    for item in payload.get("results", []):
        resultados.append(
            normalizar_para_radar(
                {
                    "empresa": item.get("company", {}).get("display_name", ""),
                    "cargo": item.get("title", ""),
                    "link": item.get("redirect_url", ""),
                    "local": item.get("location", {}).get("display_name", ""),
                    "modelo": "Remoto" if "remote" in str(item).lower() else "",
                    "regime": item.get("contract_type", ""),
                    "senioridade": "",
                    "area_principal": item.get("category", {}).get("label", ""),
                    "descricao": item.get("description", ""),
                },
                "Adzuna",
            )
        )
    return resultados


def buscar_greenhouse(site_carreiras: str, empresa: str) -> list[dict[str, Any]]:
    slug = site_carreiras.rstrip("/").split("/")[-1]
    if not slug:
        return []
    url = f"https://boards-api.greenhouse.io/v1/boards/{quote(slug)}/jobs?content=true"
    with urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    return [
        normalizar_para_radar(
            {
                "empresa": empresa,
                "cargo": item.get("title", ""),
                "link": item.get("absolute_url", ""),
                "local": item.get("location", {}).get("name", ""),
                "descricao": item.get("content", ""),
            },
            "Greenhouse",
        )
        for item in payload.get("jobs", [])
    ]


def buscar_lever(site_carreiras: str, empresa: str) -> list[dict[str, Any]]:
    slug = site_carreiras.rstrip("/").split("/")[-1]
    if not slug:
        return []
    url = f"https://api.lever.co/v0/postings/{quote(slug)}?mode=json"
    with urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    return [
        normalizar_para_radar(
            {
                "empresa": empresa,
                "cargo": item.get("text", ""),
                "link": item.get("hostedUrl", ""),
                "local": item.get("categories", {}).get("location", ""),
                "modelo": item.get("workplaceType", ""),
                "regime": item.get("categories", {}).get("commitment", ""),
                "area_principal": item.get("categories", {}).get("team", ""),
                "descricao": " ".join(
                    section.get("text", "")
                    for section in item.get("content", {}).get("sections", [])
                ),
            },
            "Lever",
        )
        for item in payload
    ]


def radar_para_vagas_crm(vaga: dict[str, Any]) -> dict[str, Any]:
    link = vaga.get("link", "")
    empresa = vaga.get("empresa", "")
    cargo = vaga.get("cargo", "")
    return {
        "ID": gerar_id_vaga(empresa, cargo, link),
        "Data encontrada": vaga.get("data_busca", date.today().isoformat()),
        "Fonte": vaga.get("fonte", ""),
        "Plataforma": inferir_plataforma(link) or vaga.get("fonte", ""),
        "Empresa": empresa,
        "Cargo": cargo,
        "Link": link,
        "Local": vaga.get("local", ""),
        "Modelo": vaga.get("modelo", ""),
        "Regime": vaga.get("regime", ""),
        "Senioridade": vaga.get("senioridade", ""),
        "Área principal": vaga.get("area_principal", ""),
        "Status": "Avaliar",
        "Descrição da vaga": vaga.get("descricao", vaga.get("descricao_resumida", "")),
        "Observações": vaga.get("observacoes", vaga.get("motivo", "")),
    }
