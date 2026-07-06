from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.job_link_extractor import extrair_dados_link  # noqa: E402
from utils.job_radar import (  # noqa: E402
    buscar_adzuna,
    buscar_greenhouse,
    buscar_lever,
    campos_faltantes_para_avaliacao,
    radar_para_vagas_crm,
)
from utils.job_sources import (  # noqa: E402
    GUPY_MANUAL_OBSERVATION,
    buscar_gupy_site,
    is_gupy_url,
    search_jobs_openai_web,
)
from utils.sheets import (  # noqa: E402
    SheetsClientError,
    atualizar_link_pendente,
    conectar_planilha,
    diagnosticar_vagas_crm,
    enviar_para_vagas_crm,
    encontrar_duplicata_link,
    garantir_abas_radar,
    ler_empresas_alvo,
    ler_links_pendentes,
    ler_radar_config,
    registrar_radar_resultados,
)


@dataclass
class RadarStats:
    buscas_executadas: int = 0
    vagas_encontradas: int = 0
    vagas_inseridas: int = 0
    ignoradas_duplicata: int = 0
    ignoradas_baixa_aderencia: int = 0
    links_pendentes_encontrados: int = 0
    links_pendentes_sucesso: int = 0
    links_pendentes_duplicados: int = 0
    links_pendentes_precisa_descricao: int = 0
    links_pendentes_erros: int = 0
    gupy_links_pendentes: int = 0
    gupy_precisa_descricao: int = 0
    gupy_erros: int = 0
    web_searches_executadas: int = 0
    urls_encontradas_web: int = 0
    erros: int = 0


@dataclass
class FonteStats:
    buscas: int = 0
    encontrados: int = 0
    inseridos: int = 0
    precisa_descricao: int = 0
    duplicatas: int = 0
    baixa_aderencia: int = 0
    erros: int = 0


def _env_int(nome: str, default: int) -> int:
    try:
        return int(os.getenv(nome, default))
    except ValueError:
        return default


def _ativo(valor: Any) -> bool:
    return str(valor or "").strip().lower() in {"sim", "true", "1", "ativo", "yes"}


def _score(vaga: dict[str, Any]) -> int:
    try:
        return int(float(vaga.get("score_preliminar", 0)))
    except (TypeError, ValueError):
        return 0


def _fonte(vaga: dict[str, Any]) -> str:
    return str(vaga.get("fonte") or vaga.get("Fonte") or "Desconhecida").strip() or "Desconhecida"


def _agrupar_por_fonte(vagas: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grupos: dict[str, list[dict[str, Any]]] = {}
    for vaga in vagas:
        grupos.setdefault(_fonte(vaga), []).append(vaga)
    return grupos


def _filtrar_por_score(
    vagas: list[dict[str, Any]],
    limite: int,
    stats: RadarStats,
    fontes: dict[str, FonteStats],
) -> list[dict[str, Any]]:
    aprovadas = []
    for vaga in vagas:
        fonte = _fonte(vaga)
        fonte_stats = fontes.setdefault(fonte, FonteStats())
        if _score(vaga) >= limite:
            aprovadas.append(vaga)
        else:
            stats.ignoradas_baixa_aderencia += 1
            fonte_stats.baixa_aderencia += 1
    return aprovadas


def _contar_precisa_descricao(vagas_crm: list[dict[str, Any]]) -> int:
    return sum(1 for vaga in vagas_crm if str(vaga.get("Status", "")).strip().lower() == "precisa descrição")


def _registrar_encontrados(resultados: list[dict[str, Any]], fontes: dict[str, FonteStats]) -> None:
    for fonte, vagas in _agrupar_por_fonte(resultados).items():
        fontes.setdefault(fonte, FonteStats()).encontrados += len(vagas)


def _web_search_specs(configs: list[dict[str, Any]], max_calls: int) -> list[dict[str, Any]]:
    sources = [
        {"fonte": "LinkedIn", "domains": ["linkedin.com"]},
        {"fonte": "Gupy", "domains": ["gupy.io"]},
        {"fonte": "Recruit.net", "domains": ["recruit.net"]},
        {"fonte": "Empregando Brasil", "domains": ["empregandobrasil.com.br"]},
        {"fonte": "OpenAI Web Search", "domains": []},
    ]
    active_configs = configs or []
    specs = []
    for index, config in enumerate(active_configs):
        source = sources[index % len(sources)]
        termo = str(config.get("termo_busca", "")).strip()
        local = str(config.get("local", "")).strip()
        modelo = str(config.get("modelo", "")).strip()
        idioma = str(config.get("idioma", "")).strip()
        if not termo:
            continue
        query = " ".join(part for part in [termo, local, modelo, idioma, "public job opening"] if part)
        specs.append({**source, "query": query})
        if len(specs) >= max_calls:
            break
    return specs


def _crm_from_extracao(extraido: dict[str, Any]) -> dict[str, Any]:
    return radar_para_vagas_crm(
        {
            **extraido,
            "fonte": extraido.get("fonte", "Link manual"),
            "descricao": extraido.get("descricao_vaga", ""),
            "observacoes": extraido.get("observacoes_extracao", ""),
        }
    )


def _processar_links_pendentes(planilha, stats: RadarStats) -> None:
    pendentes = ler_links_pendentes(planilha)
    stats.links_pendentes_encontrados = len(pendentes)
    stats.gupy_links_pendentes = sum(1 for item in pendentes if is_gupy_url(str(item.get("Link", ""))))
    print(f"Linhas com Status normalizado como Link pendente: {len(pendentes)}")
    print(f"Gupy links pendentes encontrados: {stats.gupy_links_pendentes}")

    for item in pendentes:
        row_number = item["_row_number"]
        link = str(item.get("Link", "")).strip()
        link_gupy = is_gupy_url(link)
        print(f"Linha {row_number}: processando link pendente: {link or '(sem link)'}")
        if not link:
            _marcar_precisa_descricao(planilha, row_number, "sem link", stats, link_gupy)
            continue

        duplicada_linha = encontrar_duplicata_link(planilha, link, row_number)
        if duplicada_linha:
            atualizar_link_pendente(
                planilha,
                row_number,
                {"Observações": f"Link duplicado. Já existe na linha {duplicada_linha}."},
                "Duplicada",
            )
            stats.links_pendentes_duplicados += 1
            print(f"Linha {row_number}: resultado=duplicado; linha_original={duplicada_linha}.")
            continue

        try:
            extraido = extrair_dados_link(link)
            crm = _crm_from_extracao(extraido)
            faltantes = campos_faltantes_para_avaliacao(crm)
            status_extracao = extraido.get("status_extracao")

            if status_extracao == "sucesso" and not faltantes:
                observacao = extraido.get("observacoes_extracao", "Extração automática concluída.")
                status = "Avaliar"
                stats.links_pendentes_sucesso += 1
                print(f"Linha {row_number}: resultado=sucesso; status=Avaliar.")
            elif link_gupy:
                observacao = GUPY_MANUAL_OBSERVATION
                status = "Precisa descrição"
                stats.links_pendentes_precisa_descricao += 1
                stats.gupy_precisa_descricao += 1
                print(f"Linha {row_number}: resultado=precisa descrição; fonte=Gupy.")
            elif status_extracao == "parcial" or faltantes:
                observacao = (
                    "Extração parcial. Complete manualmente: "
                    + (", ".join(faltantes) if faltantes else "revise a descrição da vaga.")
                )
                status = "Precisa descrição"
                stats.links_pendentes_precisa_descricao += 1
                print(
                    f"Linha {row_number}: resultado=precisa descrição; "
                    f"faltantes={', '.join(faltantes) or 'revisão manual'}."
                )
            else:
                observacao = "Não foi possível extrair dados automaticamente. Cole a descrição da vaga manualmente."
                status = "Precisa descrição"
                stats.links_pendentes_precisa_descricao += 1
                print(f"Linha {row_number}: resultado=precisa descrição; motivo=extração insuficiente.")

            crm["Observações"] = observacao
            atualizar_link_pendente(planilha, row_number, crm, status)
        except Exception as exc:
            observacao = GUPY_MANUAL_OBSERVATION if link_gupy else (
                "Não foi possível extrair dados automaticamente. Cole a descrição da vaga manualmente."
            )
            atualizar_link_pendente(planilha, row_number, {"Observações": observacao}, "Precisa descrição")
            stats.links_pendentes_precisa_descricao += 1
            stats.links_pendentes_erros += 1
            if link_gupy:
                stats.gupy_precisa_descricao += 1
                stats.gupy_erros += 1
            print(f"Linha {row_number}: resultado=erro; status=Precisa descrição; erro={exc}")


def _marcar_precisa_descricao(planilha, row_number: int, motivo: str, stats: RadarStats, link_gupy: bool) -> None:
    observacao = GUPY_MANUAL_OBSERVATION if link_gupy else (
        "Não foi possível extrair dados automaticamente. Cole a descrição da vaga manualmente."
    )
    atualizar_link_pendente(planilha, row_number, {"Observações": observacao}, "Precisa descrição")
    stats.links_pendentes_precisa_descricao += 1
    if link_gupy:
        stats.gupy_precisa_descricao += 1
    print(f"Linha {row_number}: resultado=precisa descrição; motivo={motivo}.")


def _buscar_adzuna_por_config(configs: list[dict[str, Any]], stats: RadarStats, fontes: dict[str, FonteStats]) -> list[dict[str, Any]]:
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    fonte_stats = fontes.setdefault("Adzuna", FonteStats())
    if not app_id or not app_key:
        print("Adzuna não configurado. Pulando busca Adzuna.")
        return []

    pais = os.getenv("RADAR_ADZUNA_COUNTRY", "br")
    quantidade = _env_int("RADAR_RESULTS_PER_QUERY", 10)
    resultados = []
    for config in configs:
        termo = str(config.get("termo_busca", "")).strip()
        if not termo:
            continue
        local = str(config.get("local", "")).strip()
        try:
            encontrados = buscar_adzuna(app_id, app_key, termo, pais, local, quantidade)
            stats.buscas_executadas += 1
            stats.vagas_encontradas += len(encontrados)
            fonte_stats.buscas += 1
            resultados.extend(encontrados)
            print(f"Adzuna: {len(encontrados)} vaga(s) para termo '{termo}'.")
        except Exception as exc:
            stats.erros += 1
            fonte_stats.erros += 1
            print(f"Erro Adzuna termo '{termo}': {exc}")
    return resultados


def _buscar_openai_web(configs: list[dict[str, Any]], stats: RadarStats, fontes: dict[str, FonteStats]) -> list[dict[str, Any]]:
    max_calls = max(0, _env_int("RADAR_MAX_WEB_SEARCH_CALLS", 8))
    if max_calls == 0:
        print("RADAR_MAX_WEB_SEARCH_CALLS=0. Pulando OpenAI Web Search.")
        return []
    if not os.getenv("OPENAI_API_KEY"):
        stats.erros += 1
        fontes.setdefault("OpenAI Web Search", FonteStats()).erros += 1
        print("OPENAI_API_KEY não configurada. OpenAI Web Search não foi executado.")
        return []

    model = os.getenv("OPENAI_RADAR_MODEL") or os.getenv("OPENAI_MODEL")
    resultados = []
    specs = _web_search_specs(configs, max_calls)
    print(f"OpenAI Web Search: chamadas planejadas={len(specs)}; limite={max_calls}.")
    for spec in specs:
        fonte = spec["fonte"]
        fonte_stats = fontes.setdefault(fonte, FonteStats())
        try:
            encontrados, urls = search_jobs_openai_web(
                query=spec["query"],
                allowed_domains=spec["domains"],
                fonte=fonte,
                max_results=_env_int("RADAR_WEB_RESULTS_PER_QUERY", 8),
                model=model,
            )
            stats.buscas_executadas += 1
            stats.web_searches_executadas += 1
            stats.urls_encontradas_web += len(urls)
            stats.vagas_encontradas += len(encontrados)
            fonte_stats.buscas += 1
            resultados.extend(encontrados)
            print(f"OpenAI Web Search/{fonte}: query='{spec['query']}'; urls={len(urls)}; vagas={len(encontrados)}.")
            for url in urls[:12]:
                print(f"- URL encontrada: {url}")
        except Exception as exc:
            stats.erros += 1
            fonte_stats.erros += 1
            print(f"Erro OpenAI Web Search/{fonte}: {exc}")
    return resultados


def _buscar_empresas_alvo(empresas: list[dict[str, Any]], stats: RadarStats, fontes: dict[str, FonteStats]) -> list[dict[str, Any]]:
    resultados = []
    gupy_token = os.getenv("GUPY_API_TOKEN", "")
    if not gupy_token:
        print("GUPY_API_TOKEN não configurado. Gupy seguirá com leitura pública sem API autenticada.")

    for empresa in empresas:
        if not _ativo(empresa.get("ativo")):
            continue
        plataforma = str(empresa.get("plataforma", "")).strip().lower()
        nome = str(empresa.get("empresa", "")).strip()
        site = (
            str(empresa.get("board_token", "")).strip()
            or str(empresa.get("site_carreiras", "")).strip()
            or str(empresa.get("slug", "")).strip()
        )
        if not nome or not site:
            continue
        try:
            if plataforma == "greenhouse":
                fonte = "Greenhouse"
                encontrados = buscar_greenhouse(site, nome)
            elif plataforma == "lever":
                fonte = "Lever"
                encontrados = buscar_lever(site, nome)
            elif plataforma == "gupy":
                fonte = "Gupy"
                encontrados = buscar_gupy_site(site, nome, gupy_token, _env_int("RADAR_RESULTS_PER_SOURCE", 10))
            else:
                print(f"{nome}: plataforma '{plataforma}' não entra no robô automático por API pública.")
                continue
            fonte_stats = fontes.setdefault(fonte, FonteStats())
            stats.buscas_executadas += 1
            stats.vagas_encontradas += len(encontrados)
            fonte_stats.buscas += 1
            resultados.extend(encontrados)
            print(f"{nome}/{fonte}: {len(encontrados)} vaga(s).")
        except Exception as exc:
            fonte = "Gupy" if plataforma == "gupy" else plataforma or "Empresas_Alvo"
            fonte_stats = fontes.setdefault(fonte, FonteStats())
            stats.erros += 1
            fonte_stats.erros += 1
            if plataforma == "gupy":
                stats.gupy_erros += 1
            print(f"Erro/bloqueio {nome}/{plataforma}: {exc}")
    return resultados


def _enviar_por_fonte(planilha, vagas_crm: list[dict[str, Any]], stats: RadarStats, fontes: dict[str, FonteStats]) -> None:
    for fonte, vagas in _agrupar_por_fonte(vagas_crm).items():
        fonte_stats = fontes.setdefault(fonte, FonteStats())
        inseridas, avisos = enviar_para_vagas_crm(planilha, vagas)
        fonte_stats.inseridos += inseridas
        fonte_stats.duplicatas += len(avisos)
        fonte_stats.precisa_descricao += _contar_precisa_descricao(vagas)
        stats.vagas_inseridas += inseridas
        stats.ignoradas_duplicata += len(avisos)
        print(
            f"Fonte {fonte}: inseridos={inseridas}; "
            f"precisa_descrição={fonte_stats.precisa_descricao}; duplicatas={len(avisos)}."
        )
        for aviso in avisos:
            print(aviso)


def main() -> int:
    limite_score = _env_int("RADAR_SCORE_MIN", 65)
    stats = RadarStats()
    fontes: dict[str, FonteStats] = {}

    try:
        planilha = conectar_planilha()
        garantir_abas_radar(planilha)
        diagnostico = diagnosticar_vagas_crm(planilha)
    except SheetsClientError as exc:
        print(f"Erro de planilha: {exc}")
        return 1

    print(f"Planilha conectada: {diagnostico['nome_planilha']}")
    print(f"Abas encontradas: {', '.join(diagnostico['abas'])}")
    print(f"Total de linhas em Vagas_CRM: {diagnostico['total_linhas_vagas_crm']}")
    print("Contagem de Status em Vagas_CRM:")
    for status, quantidade in sorted(diagnostico["contagem_status"].items()):
        print(f"- {status}: {quantidade}")
    print(f'Linhas com Status exatamente igual a "Link pendente": {diagnostico["link_pendente_exato"]}')

    configs = ler_radar_config(planilha)
    empresas = ler_empresas_alvo(planilha)

    print(f"Configurações ativas: {len(configs)}")
    print(f"Empresas-alvo ativas: {len(empresas)}")
    print(f"Score mínimo: {limite_score}")

    try:
        _processar_links_pendentes(planilha, stats)
    except SheetsClientError as exc:
        stats.erros += 1
        print(f"Erro ao processar links pendentes: {exc}")

    resultados = []
    lotes = [
        _buscar_openai_web(configs, stats, fontes),
        _buscar_empresas_alvo(empresas, stats, fontes),
        _buscar_adzuna_por_config(configs, stats, fontes),
    ]
    for lote in lotes:
        _registrar_encontrados(lote, fontes)
        resultados.extend(lote)

    try:
        registrar_radar_resultados(planilha, resultados)
    except SheetsClientError as exc:
        stats.erros += 1
        print(f"Erro ao registrar Radar_Resultados: {exc}")

    aprovadas = _filtrar_por_score(resultados, limite_score, stats, fontes)
    vagas_crm = [radar_para_vagas_crm(vaga) for vaga in aprovadas]

    try:
        _enviar_por_fonte(planilha, vagas_crm, stats, fontes)
    except SheetsClientError as exc:
        stats.erros += 1
        print(f"Erro ao enviar para Vagas_CRM: {exc}")
        return 1

    print("Resumo Radar")
    print(f"Buscas executadas: {stats.buscas_executadas}")
    print(f"Vagas encontradas: {stats.vagas_encontradas}")
    print(f"Vagas inseridas: {stats.vagas_inseridas}")
    print(f"Web searches executadas: {stats.web_searches_executadas}")
    print(f"URLs encontradas via web search: {stats.urls_encontradas_web}")
    print(f"Ignoradas por duplicata: {stats.ignoradas_duplicata}")
    print(f"Ignoradas por baixa aderência: {stats.ignoradas_baixa_aderencia}")
    print(f"Links pendentes encontrados: {stats.links_pendentes_encontrados}")
    print(f"Links pendentes com sucesso: {stats.links_pendentes_sucesso}")
    print(f"Links pendentes duplicados: {stats.links_pendentes_duplicados}")
    print(f"Links pendentes precisam descrição: {stats.links_pendentes_precisa_descricao}")
    print(f"Links pendentes com erro tratado: {stats.links_pendentes_erros}")
    print(f"Gupy links pendentes encontrados: {stats.gupy_links_pendentes}")
    print(f"Gupy precisa descrição: {stats.gupy_precisa_descricao}")
    print(f"Gupy erros/bloqueios: {stats.gupy_erros}")
    print("Resumo por fonte")
    for fonte, fonte_stats in sorted(fontes.items()):
        print(
            f"- {fonte}: buscas={fonte_stats.buscas}; encontrados={fonte_stats.encontrados}; "
            f"inseridos={fonte_stats.inseridos}; precisa_descrição={fonte_stats.precisa_descricao}; "
            f"duplicatas={fonte_stats.duplicatas}; baixa_aderência={fonte_stats.baixa_aderencia}; "
            f"erros={fonte_stats.erros}"
        )
    print(f"Erros: {stats.erros}")
    return 0 if stats.erros == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
