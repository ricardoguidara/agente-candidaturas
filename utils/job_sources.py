from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from utils.job_radar import normalizar_para_radar, resumir_html


USER_AGENT = (
    "Mozilla/5.0 (compatible; agente-candidaturas/0.2; "
    "+https://ricardoguidara.com/)"
)
TIMEOUT = 20
GUPY_MANUAL_OBSERVATION = (
    "Link Gupy detectado, mas não foi possível extrair a descrição completa automaticamente. "
    "Cole a descrição da vaga manualmente."
)


def _get(url: str, params: dict[str, Any] | None = None) -> str:
    response = requests.get(
        url,
        params=params,
        timeout=TIMEOUT,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
    )
    response.raise_for_status()
    return response.text


def _get_json(url: str, token: str = "", params: dict[str, Any] | None = None) -> Any:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(url, params=params, timeout=TIMEOUT, headers=headers)
    response.raise_for_status()
    return response.json()


def _texto_limpo(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _absoluto(base_url: str, href: str) -> str:
    return urljoin(base_url, href or "")


def _cards_com_links(soup: BeautifulSoup, base_url: str, host_fragment: str) -> list[dict[str, str]]:
    cards = []
    vistos = set()
    for link_tag in soup.find_all("a", href=True):
        href = _absoluto(base_url, link_tag["href"])
        if host_fragment not in urlparse(href).netloc and host_fragment not in href:
            continue
        titulo = _texto_limpo(link_tag)
        container = link_tag.find_parent(["article", "li", "div", "section"]) or link_tag
        texto = _texto_limpo(container)
        if not titulo or href in vistos:
            continue
        vistos.add(href)
        cards.append(
            {
                "cargo": titulo[:180],
                "link": href,
                "descricao": resumir_html(texto, 1200),
            }
        )
    return cards


def is_gupy_url(link: str) -> bool:
    host = urlparse(link or "").netloc.lower()
    return any(fragment in host for fragment in ["gupy.io", "gupy.com.br", "jobs.gupy.io"])


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _gupy_jobs_from_json(payload: Any, empresa_fallback: str = "") -> list[dict[str, Any]]:
    vagas = []
    vistos = set()
    for item in _walk_json(payload):
        titulo = item.get("title") or item.get("name") or item.get("jobName")
        link = item.get("jobUrl") or item.get("url") or item.get("applicationUrl")
        job_id = item.get("id") or item.get("jobId") or item.get("code")
        if not titulo:
            continue
        if not link and job_id:
            link = f"https://jobs.gupy.io/jobs/{job_id}"
        if not link:
            continue
        link = str(link)
        if link in vistos:
            continue
        vistos.add(link)
        descricao = item.get("description") or item.get("responsibilities") or item.get("shortDescription") or ""
        vagas.append(
            {
                "empresa": item.get("companyName") or item.get("company") or empresa_fallback,
                "cargo": titulo,
                "link": link,
                "local": item.get("workplace") or item.get("city") or item.get("location") or "",
                "modelo": item.get("workplaceType") or item.get("remoteWorking") or "",
                "regime": item.get("type") or item.get("contractType") or "",
                "senioridade": "",
                "area_principal": item.get("department") or "",
                "descricao": resumir_html(str(descricao), 5000),
                "plataforma": "Gupy",
                "observacoes": "" if len(resumir_html(str(descricao), 5000)) >= 180 else GUPY_MANUAL_OBSERVATION,
            }
        )
    return vagas


def _gupy_jobs_from_html(html: str, base_url: str, empresa: str = "") -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    vagas = []
    for script in soup.find_all("script", id="__NEXT_DATA__"):
        try:
            payload = json.loads(script.string or script.get_text() or "{}")
        except json.JSONDecodeError:
            continue
        vagas.extend(_gupy_jobs_from_json(payload, empresa))

    if vagas:
        return vagas

    for item in _cards_com_links(soup, base_url, "gupy"):
        item.update(
            {
                "empresa": empresa,
                "local": "",
                "modelo": "",
                "regime": "",
                "senioridade": "",
                "area_principal": "",
                "plataforma": "Gupy",
                "observacoes": GUPY_MANUAL_OBSERVATION,
            }
        )
        vagas.append(item)
    return vagas


def buscar_gupy_site(
    site_carreiras: str,
    empresa: str = "",
    token: str = "",
    quantidade: int = 10,
) -> list[dict[str, Any]]:
    site = str(site_carreiras or "").strip()
    if not site:
        return []

    resultados = []
    if token:
        for endpoint in _gupy_api_candidates(site):
            try:
                payload = _get_json(endpoint, token)
                resultados.extend(_gupy_jobs_from_json(payload, empresa))
                if resultados:
                    break
            except Exception:
                continue

    if not resultados:
        html = _get(site)
        resultados.extend(_gupy_jobs_from_html(html, site, empresa))

    return [normalizar_para_radar(vaga, "Gupy") for vaga in resultados[:quantidade]]


def _gupy_api_candidates(site: str) -> list[str]:
    parsed = urlparse(site)
    path_parts = [part for part in parsed.path.split("/") if part]
    company_slug = path_parts[0] if path_parts else ""
    candidates = [
        "https://portal.api.gupy.io/api/job",
        "https://jobs.gupy.io/api/jobs",
    ]
    if company_slug:
        candidates.append(f"https://{parsed.netloc}/api/jobs")
        candidates.append(f"https://{parsed.netloc}/{company_slug}/api/jobs")
    return candidates


def buscar_empregando_brasil(termo: str, local: str = "", quantidade: int = 10) -> list[dict[str, Any]]:
    termo = str(termo or "").strip()
    if not termo:
        return []

    urls = [
        (
            "https://www.empregandobrasil.com.br/vagas",
            {"q": termo, "cidade": local or ""},
        ),
        (
            f"https://www.empregandobrasil.com.br/vagas/{quote_plus(termo)}",
            None,
        ),
    ]
    resultados = []
    for url, params in urls:
        try:
            html = _get(url, params)
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for item in _cards_com_links(soup, url, "empregandobrasil.com.br"):
            item.update(
                {
                    "empresa": "",
                    "local": local,
                    "modelo": "",
                    "regime": "",
                    "senioridade": "",
                    "area_principal": "",
                }
            )
            resultados.append(normalizar_para_radar(item, "Empregando Brasil"))
            if len(resultados) >= quantidade:
                return resultados
    return resultados


def buscar_recruit_net(termo: str, local: str = "", quantidade: int = 10) -> list[dict[str, Any]]:
    termo = str(termo or "").strip()
    if not termo:
        return []

    html = _get(
        "https://www.recruit.net/search",
        {"query": termo, "location": local or "Brazil"},
    )
    soup = BeautifulSoup(html, "html.parser")
    resultados = []
    for item in _cards_com_links(soup, "https://www.recruit.net/search", "recruit.net"):
        item.update(
            {
                "empresa": "",
                "local": local,
                "modelo": "",
                "regime": "",
                "senioridade": "",
                "area_principal": "",
            }
        )
        resultados.append(normalizar_para_radar(item, "Recruit.net"))
        if len(resultados) >= quantidade:
            break
    return resultados


def buscar_google_programmable(
    api_key: str,
    cx: str,
    termo: str,
    quantidade: int = 10,
) -> list[dict[str, Any]]:
    termo = str(termo or "").strip()
    if not api_key or not cx or not termo:
        return []

    query = (
        f'{termo} ("AI Creative Director" OR "Creative Director" OR "Head of Creative" '
        'OR "Content Lead" OR "Creative Operations Lead") '
        "(site:linkedin.com/jobs/view OR site:gupy.io/jobs OR site:gupy.com.br OR "
        "site:empregandobrasil.com.br/vagas OR site:recruit.net)"
    )
    response = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": api_key, "cx": cx, "q": query, "num": min(int(quantidade), 10)},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = json.loads(response.text)

    resultados = []
    for item in payload.get("items", []):
        link = item.get("link", "")
        fonte = _fonte_por_link(link)
        observacao = ""
        if fonte == "LinkedIn":
            observacao = "LinkedIn detectado por busca pública. Cole a descrição completa antes de gerar candidatura."
        elif fonte == "Gupy":
            observacao = GUPY_MANUAL_OBSERVATION

        resultados.append(
            normalizar_para_radar(
                {
                    "empresa": item.get("displayLink", ""),
                    "cargo": item.get("title", ""),
                    "link": link,
                    "local": "",
                    "modelo": "",
                    "regime": "",
                    "senioridade": "",
                    "area_principal": "",
                    "descricao": item.get("snippet", ""),
                    "observacoes": observacao,
                    "plataforma": fonte,
                },
                fonte or "Busca web",
            )
        )
    return resultados


def _fonte_por_link(link: str) -> str:
    host = urlparse(link or "").netloc.lower()
    if "linkedin.com" in host:
        return "LinkedIn"
    if "gupy.io" in host or "gupy.com.br" in host:
        return "Gupy"
    if "empregandobrasil.com.br" in host:
        return "Empregando Brasil"
    if "recruit.net" in host:
        return "Recruit.net"
    return "Busca web"
