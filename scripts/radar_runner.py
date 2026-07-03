from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.job_radar import (  # noqa: E402
    buscar_adzuna,
    buscar_greenhouse,
    buscar_lever,
    campos_faltantes_para_avaliacao,
    radar_para_vagas_crm,
)
from utils.job_link_extractor import extrair_dados_link  # noqa: E402
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


def _filtrar_por_score(vagas: list[dict[str, Any]], limite: int, stats: RadarStats) -> list[dict[str, Any]]:
    aprovadas = []
    for vaga in vagas:
        if _score(vaga) >= limite:
            aprovadas.append(vaga)
        else:
            stats.ignoradas_baixa_aderencia += 1
    return aprovadas


def _crm_from_extracao(extraido: dict[str, Any]) -> dict[str, Any]:
    return radar_para_vagas_crm(
        {
            **extraido,
            "fonte": "Link manual",
            "descricao": extraido.get("descricao_vaga", ""),
            "observacoes": extraido.get("observacoes_extracao", ""),
        }
    )


def _processar_links_pendentes(planilha, stats: RadarStats) -> None:
    pendentes = ler_links_pendentes(planilha)
    stats.links_pendentes_encontrados = len(pendentes)
    print(f"Linhas com Status normalizado como Link pendente: {len(pendentes)}")

    for item in pendentes:
        row_number = item["_row_number"]
        link = str(item.get("Link", "")).strip()
        print(f"Linha {row_number}: processando link pendente: {link or '(sem link)'}")
        if not link:
            atualizar_link_pendente(
                planilha,
                row_number,
                {"Observações": "Não foi possível extrair dados automaticamente. Cole a descrição da vaga manualmente."},
                "Precisa descrição",
            )
            stats.links_pendentes_precisa_descricao += 1
            print(f"Linha {row_number}: resultado=precisa descrição; motivo=sem link.")
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
            elif status_extracao == "parcial" or faltantes:
                observacao = (
                    "Extração parcial. Complete manualmente: "
                    + (", ".join(faltantes) if faltantes else "revise a descrição da vaga.")
                )
                status = "Precisa descrição"
                stats.links_pendentes_precisa_descricao += 1
                print(f"Linha {row_number}: resultado=precisa descrição; faltantes={', '.join(faltantes) or 'revisão manual'}.")
            else:
                observacao = "Não foi possível extrair dados automaticamente. Cole a descrição da vaga manualmente."
                status = "Precisa descrição"
                stats.links_pendentes_precisa_descricao += 1
                print(f"Linha {row_number}: resultado=precisa descrição; motivo=extração insuficiente.")

            crm["Observações"] = observacao
            atualizar_link_pendente(planilha, row_number, crm, status)
        except Exception as exc:
            atualizar_link_pendente(
                planilha,
                row_number,
                {"Observações": "Não foi possível extrair dados automaticamente. Cole a descrição da vaga manualmente."},
                "Precisa descrição",
            )
            stats.links_pendentes_precisa_descricao += 1
            stats.links_pendentes_erros += 1
            print(f"Linha {row_number}: resultado=erro; status=Precisa descrição; erro={exc}")


def _buscar_adzuna_por_config(configs: list[dict[str, Any]], stats: RadarStats) -> list[dict[str, Any]]:
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("Adzuna não configurado. Pulando busca Adzuna.")
        return []

    pais = os.getenv("RADAR_ADZUNA_COUNTRY", "br")
    quantidade = _env_int("RADAR_RESULTS_PER_QUERY", 20)
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
            resultados.extend(encontrados)
            print(f"Adzuna: {len(encontrados)} vaga(s) para termo '{termo}'.")
        except Exception as exc:
            stats.erros += 1
            print(f"Erro Adzuna termo '{termo}': {exc}")
    return resultados


def _buscar_empresas_alvo(empresas: list[dict[str, Any]], stats: RadarStats) -> list[dict[str, Any]]:
    resultados = []
    for empresa in empresas:
        if not _ativo(empresa.get("ativo")):
            continue
        plataforma = str(empresa.get("plataforma", "")).strip().lower()
        nome = str(empresa.get("empresa", "")).strip()
        site = (
            str(empresa.get("site_carreiras", "")).strip()
            or str(empresa.get("board_token", "")).strip()
            or str(empresa.get("slug", "")).strip()
        )
        if not nome or not site:
            continue
        try:
            if plataforma == "greenhouse":
                encontrados = buscar_greenhouse(site, nome)
            elif plataforma == "lever":
                encontrados = buscar_lever(site, nome)
            else:
                print(f"{nome}: plataforma '{plataforma}' não entra no robô automático v0.1.")
                continue
            stats.buscas_executadas += 1
            stats.vagas_encontradas += len(encontrados)
            resultados.extend(encontrados)
            print(f"{nome}/{plataforma}: {len(encontrados)} vaga(s).")
        except Exception as exc:
            stats.erros += 1
            print(f"Erro {nome}/{plataforma}: {exc}")
    return resultados


def main() -> int:
    limite_score = _env_int("RADAR_SCORE_MIN", 65)
    stats = RadarStats()

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
    resultados.extend(_buscar_adzuna_por_config(configs, stats))
    resultados.extend(_buscar_empresas_alvo(empresas, stats))

    try:
        registrar_radar_resultados(planilha, resultados)
    except SheetsClientError as exc:
        stats.erros += 1
        print(f"Erro ao registrar Radar_Resultados: {exc}")

    aprovadas = _filtrar_por_score(resultados, limite_score, stats)
    vagas_crm = [radar_para_vagas_crm(vaga) for vaga in aprovadas]

    try:
        inseridas, avisos = enviar_para_vagas_crm(planilha, vagas_crm)
        stats.vagas_inseridas = inseridas
        stats.ignoradas_duplicata = len(avisos)
        for aviso in avisos:
            print(aviso)
    except SheetsClientError as exc:
        stats.erros += 1
        print(f"Erro ao enviar para Vagas_CRM: {exc}")
        return 1

    print("Resumo Radar")
    print(f"Buscas executadas: {stats.buscas_executadas}")
    print(f"Vagas encontradas: {stats.vagas_encontradas}")
    print(f"Vagas inseridas: {stats.vagas_inseridas}")
    print(f"Ignoradas por duplicata: {stats.ignoradas_duplicata}")
    print(f"Ignoradas por baixa aderência: {stats.ignoradas_baixa_aderencia}")
    print(f"Links pendentes encontrados: {stats.links_pendentes_encontrados}")
    print(f"Links pendentes com sucesso: {stats.links_pendentes_sucesso}")
    print(f"Links pendentes duplicados: {stats.links_pendentes_duplicados}")
    print(f"Links pendentes precisam descrição: {stats.links_pendentes_precisa_descricao}")
    print(f"Links pendentes com erro tratado: {stats.links_pendentes_erros}")
    print(f"Erros: {stats.erros}")
    return 0 if stats.erros == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
