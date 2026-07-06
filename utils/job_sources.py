from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

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
DEFAULT_OPENAI_RADAR_MODEL = "gpt-4.1-mini"
TRACKING_PARAMS_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "trk", "ref"}


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


def normalize_job_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
        and not any(key.lower().startswith(prefix) for prefix in TRACKING_PARAMS_PREFIXES)
    ]
    cleaned = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower().removeprefix("www."),
        path=parsed.path.rstrip("/"),
        query=urlencode(query, doseq=True),
        fragment="",
    )
    return urlunparse(cleaned)


def _texto_limpo(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _json_from_text(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    payload = json.loads(cleaned)
    return payload if isinstance(payload, dict) else {}


def _response_to_dict(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if isinstance(response, dict):
        return response
    return json.loads(json.dumps(response, default=lambda value: getattr(value, "__dict__", str(value))))


def _response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", "")
    if output_text:
        return str(output_text)
    payload = _response_to_dict(response)
    texts: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text") or content.get("output_text")
            if text:
                texts.append(str(text))
    return "\n".join(texts)


def _collect_source_entries(value: Any, in_source_context: bool = False) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    if isinstance(value, dict):
        value_type = str(value.get("type", "")).lower()
        source_context = in_source_context or value_type in {
            "url_citation",
            "web_search_call",
            "web_search_result",
        }
        if source_context:
            for key in ("url", "uri", "link"):
                if value.get(key):
                    normalized = normalize_job_url(str(value[key]))
                    if normalized:
                        entries.setdefault(
                            normalized,
                            {
                                "url": normalized,
                                "title": str(value.get("title") or value.get("text") or value.get("name") or ""),
                                "snippet": str(value.get("snippet") or value.get("description") or ""),
                            },
                        )
        for key, child in value.items():
            child_context = source_context or key in {
                "annotations",
                "sources",
                "source",
                "results",
                "search_results",
                "citations",
            }
            entries.update(_collect_source_entries(child, child_context))
    elif isinstance(value, list):
        for child in value:
            entries.update(_collect_source_entries(child, in_source_context))
    return entries


def _openai_response_with_web_search(client: OpenAI, model: str, prompt: str, allowed_domains: list[str]) -> Any:
    filters = {"allowed_domains": allowed_domains} if allowed_domains else None
    tool_variants = [
        {"type": "web_search", "search_context_size": "low", **({"filters": filters} if filters else {})},
        {"type": "web_search_preview", "search_context_size": "low"},
    ]
    last_error: Exception | None = None
    for tool in tool_variants:
        for tool_choice in ({"type": tool["type"]}, "required", None):
            try:
                kwargs = {
                    "model": model,
                    "input": prompt,
                    "tools": [tool],
                }
                if tool_choice is not None:
                    kwargs["tool_choice"] = tool_choice
                return client.responses.create(**kwargs)
            except Exception as exc:
                last_error = exc
    raise RuntimeError(f"OpenAI web_search indisponível: {last_error}")


def search_jobs_openai_web(
    query: str,
    allowed_domains: list[str] | None = None,
    fonte: str = "OpenAI Web Search",
    max_results: int = 8,
    model: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não configurada para OpenAI Web Search.")

    selected_model = model or os.getenv("OPENAI_RADAR_MODEL") or DEFAULT_OPENAI_RADAR_MODEL
    domains_text = ", ".join(allowed_domains or []) or "public career pages and job boards"
    prompt = f"""
Use web search to find public job openings aligned with Ricardo Guidara's profile.

Query: {query}
Allowed/preferred domains: {domains_text}

Prioritize: AI Creative Director, Creative Director, Head of Creative, Head de Criação,
Creative Lead, Gerente de Criação, Gerente de Marketing, Gerente de Conteúdo,
Head of Content, Content Lead, Creative Operations Lead, AI Creative Lead,
Brand Content Manager.

Areas: creative leadership, creative strategy, generative AI, creative operations,
storytelling, content, audiovisual, marketing, branding, corporate education.

Location rules:
- Brazil: São Paulo, São Paulo region, remote Brazil, hybrid São Paulo.
- International: remote only.
- Fluent English is not a red flag.

Avoid operational graphic designer, operational social media, pure motion designer,
pure video editor, junior/mid analyst and operational paid traffic roles.

Return only valid JSON:
{{
  "jobs": [
    {{
      "fonte": "{fonte}",
      "plataforma": "",
      "empresa": "",
      "cargo": "",
      "link": "",
      "local": "",
      "modelo": "",
      "regime": "",
      "senioridade": "",
      "area_principal": "",
      "descricao_vaga": "",
      "descricao_resumida": "",
      "observacoes": ""
    }}
  ]
}}

Do not invent URLs. Include only jobs whose URLs you found through web search.
Limit to {int(max_results)} jobs.
""".strip()

    response = _openai_response_with_web_search(OpenAI(api_key=api_key), selected_model, prompt, allowed_domains or [])
    source_entries = _collect_source_entries(_response_to_dict(response))
    source_urls = set(source_entries)
    try:
        payload = _json_from_text(_response_text(response))
    except (json.JSONDecodeError, ValueError):
        payload = {}
    jobs = payload.get("jobs", [])
    if not isinstance(jobs, list):
        jobs = []

    normalized_jobs = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        normalized_url = normalize_job_url(str(job.get("link", "")))
        if not normalized_url or normalized_url not in source_urls:
            continue
        descricao = job.get("descricao_vaga") or job.get("descricao") or job.get("descricao_resumida", "")
        normalized_jobs.append(
            normalizar_para_radar(
                {
                    "empresa": job.get("empresa", ""),
                    "cargo": job.get("cargo", ""),
                    "link": normalized_url,
                    "local": job.get("local", ""),
                    "modelo": job.get("modelo", ""),
                    "regime": job.get("regime", ""),
                    "senioridade": job.get("senioridade", ""),
                    "area_principal": job.get("area_principal", ""),
                    "descricao": descricao,
                    "descricao_resumida": job.get("descricao_resumida", descricao),
                    "observacoes": job.get("observacoes", ""),
                    "plataforma": job.get("plataforma", fonte),
                },
                job.get("fonte") or fonte,
            )
        )
    if not normalized_jobs:
        for entry in source_entries.values():
            title = entry.get("title") or entry["url"]
            snippet = entry.get("snippet", "")
            normalized_jobs.append(
                normalizar_para_radar(
                    {
                        "empresa": "",
                        "cargo": title,
                        "link": entry["url"],
                        "local": "",
                        "modelo": "",
                        "regime": "",
                        "senioridade": "",
                        "area_principal": "",
                        "descricao": snippet,
                        "descricao_resumida": snippet,
                        "observacoes": "Vaga detectada por OpenAI Web Search. Revise a descrição antes de gerar candidatura.",
                        "plataforma": fonte,
                    },
                    fonte,
                )
            )
            if len(normalized_jobs) >= max_results:
                break

    return normalized_jobs, sorted(source_urls)


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
