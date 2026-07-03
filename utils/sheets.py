from __future__ import annotations

import json
import os
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

try:
    import streamlit as st
except Exception:
    st = None


VAGAS_WORKSHEET = "Vagas_CRM"
OUTPUTS_WORKSHEET = "Outputs"
RADAR_CONFIG_WORKSHEET = "Radar_Config"
EMPRESAS_ALVO_WORKSHEET = "Empresas_Alvo"
RADAR_RESULTADOS_WORKSHEET = "Radar_Resultados"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

RADAR_CONFIG_HEADERS = [
    "termo_busca",
    "local",
    "idioma",
    "modelo",
    "prioridade",
    "ativo",
    "observacao",
]
EMPRESAS_ALVO_HEADERS = [
    "empresa",
    "prioridade",
    "plataforma",
    "site_carreiras",
    "observacao",
    "ativo",
]
RADAR_RESULTADOS_HEADERS = [
    "data_busca",
    "fonte",
    "empresa",
    "cargo",
    "link",
    "local",
    "modelo",
    "regime",
    "senioridade",
    "area_principal",
    "descricao_resumida",
    "score_preliminar",
    "motivo",
    "red_flags",
    "status_radar",
]
VAGAS_CRM_RADAR_HEADERS = [
    "ID",
    "Data encontrada",
    "Fonte",
    "Plataforma",
    "Empresa",
    "Cargo",
    "Link",
    "Local",
    "Modelo",
    "Regime",
    "Senioridade",
    "Área principal",
    "Status",
    "Descrição da vaga",
    "Observações",
]
STATUS_LINK_PENDENTE_CANONICO = "Link pendente"
STATUS_LINK_PENDENTE_VARIANTES = {
    "link pendente",
    "link pender",
}
OBSERVACOES_ALIASES = {
    "observações",
    "observacoes",
    "observação",
    "observacao",
    "observações da vaga",
    "observacoes da vaga",
}


class SheetsClientError(RuntimeError):
    """Erro de configuração ou comunicação com Google Sheets."""


def _secret(nome: str, default: Any = None) -> Any:
    env_value = os.environ.get(nome)
    if env_value:
        return env_value
    if st is None:
        return default
    try:
        return st.secrets.get(nome, default)
    except Exception:
        return default


def _info(mensagem: str) -> None:
    if st is not None:
        try:
            st.info(mensagem)
            return
        except Exception:
            pass
    print(f"INFO: {mensagem}")


def _warning(mensagem: str) -> None:
    if st is not None:
        try:
            st.warning(mensagem)
            return
        except Exception:
            pass
    print(f"AVISO: {mensagem}")


def _streamlit_service_account() -> dict | None:
    if st is None:
        return None
    try:
        info = st.secrets.get("GOOGLE_SERVICE_ACCOUNT")
    except Exception:
        return None
    return dict(info) if info else None


def _streamlit_secret_json() -> str | None:
    if st is None:
        return None
    try:
        return st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    except Exception:
        return None


def _parse_service_account_json(json_text: str) -> dict:
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise SheetsClientError(
            "`GOOGLE_SERVICE_ACCOUNT_JSON` contém JSON inválido. "
            "Cole o JSON inteiro da service account dentro de três aspas simples."
        ) from exc


def _service_account_info() -> dict:
    env_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if env_json:
        return _parse_service_account_json(env_json)

    streamlit_json = _streamlit_secret_json()
    if streamlit_json:
        return _parse_service_account_json(streamlit_json)

    info = _streamlit_service_account()
    if info:
        return info

    raise SheetsClientError(
        "GOOGLE_SERVICE_ACCOUNT_JSON não configurado. No Streamlit, cadastre em Secrets. "
        "No GitHub Actions, cadastre em Settings > Secrets and variables > Actions."
    )


def ensure_row_length(row: list[Any], target_length: int) -> list[Any]:
    if len(row) < target_length:
        row.extend([""] * (target_length - len(row)))
    return row


def conectar_planilha() -> gspread.Spreadsheet:
    sheet_id = _secret("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise SheetsClientError(
            "GOOGLE_SHEET_ID não configurado. No Streamlit, cadastre em Secrets. "
            "No GitHub Actions, cadastre em Settings > Secrets and variables > Actions."
        )

    try:
        credentials = Credentials.from_service_account_info(
            _service_account_info(),
            scopes=SCOPES,
        )
        client = gspread.authorize(credentials)
        return client.open_by_key(sheet_id)
    except SheetsClientError:
        raise
    except Exception as exc:
        raise SheetsClientError(f"Erro ao conectar ao Google Sheets: {exc}") from exc


def _worksheet(planilha: gspread.Spreadsheet, nome: str) -> gspread.Worksheet:
    try:
        return planilha.worksheet(nome)
    except gspread.WorksheetNotFound as exc:
        raise SheetsClientError(f"A aba `{nome}` não existe na planilha.") from exc


def _obter_ou_criar_worksheet(
    planilha: gspread.Spreadsheet,
    nome: str,
    headers: list[str],
    rows: int = 1000,
    cols: int = 30,
) -> gspread.Worksheet:
    try:
        ws = planilha.worksheet(nome)
    except gspread.WorksheetNotFound:
        ws = planilha.add_worksheet(title=nome, rows=rows, cols=max(cols, len(headers)))
        _info(f"Aba `{nome}` criada automaticamente.")
    _garantir_colunas(ws, headers)
    return ws


def ler_vagas_avaliar(planilha: gspread.Spreadsheet) -> list[dict[str, Any]]:
    ws = _worksheet(planilha, VAGAS_WORKSHEET)
    registros = ws.get_all_records()
    vagas = []
    for index, registro in enumerate(registros, start=2):
        if str(registro.get("Status", "")).strip().lower() == "avaliar":
            registro["_row_number"] = index
            vagas.append(registro)
    return vagas


def ler_links_pendentes(planilha: gspread.Spreadsheet) -> list[dict[str, Any]]:
    ws = _obter_ou_criar_worksheet(planilha, VAGAS_WORKSHEET, VAGAS_CRM_RADAR_HEADERS)
    colunas = _garantir_colunas(ws, VAGAS_CRM_RADAR_HEADERS)
    registros = ws.get_all_records()
    pendentes = []
    for index, registro in enumerate(registros, start=2):
        if _is_link_pendente(registro.get("Status")):
            if str(registro.get("Status", "")).strip() != STATUS_LINK_PENDENTE_CANONICO:
                coluna_status = colunas.get("Status")
                if coluna_status:
                    ws.update_cell(index, coluna_status, STATUS_LINK_PENDENTE_CANONICO)
                    registro["Status"] = STATUS_LINK_PENDENTE_CANONICO
            registro["_row_number"] = index
            pendentes.append(registro)
    return pendentes


def garantir_abas_radar(planilha: gspread.Spreadsheet) -> None:
    _obter_ou_criar_worksheet(planilha, RADAR_CONFIG_WORKSHEET, RADAR_CONFIG_HEADERS)
    _obter_ou_criar_worksheet(planilha, EMPRESAS_ALVO_WORKSHEET, EMPRESAS_ALVO_HEADERS)
    _obter_ou_criar_worksheet(planilha, RADAR_RESULTADOS_WORKSHEET, RADAR_RESULTADOS_HEADERS)


def ler_radar_config(planilha: gspread.Spreadsheet) -> list[dict[str, Any]]:
    ws = _obter_ou_criar_worksheet(planilha, RADAR_CONFIG_WORKSHEET, RADAR_CONFIG_HEADERS)
    configs = []
    for registro in ws.get_all_records():
        ativo = str(registro.get("ativo", "")).strip().lower()
        if ativo in {"sim", "true", "1", "ativo", "yes"}:
            configs.append(registro)
    return configs


def ler_empresas_alvo(planilha: gspread.Spreadsheet) -> list[dict[str, Any]]:
    ws = _obter_ou_criar_worksheet(planilha, EMPRESAS_ALVO_WORKSHEET, EMPRESAS_ALVO_HEADERS)
    empresas = []
    for registro in ws.get_all_records():
        ativo = str(registro.get("ativo", "")).strip().lower()
        if ativo in {"sim", "true", "1", "ativo", "yes"}:
            empresas.append(registro)
    return empresas


def ler_radar_resultados(planilha: gspread.Spreadsheet) -> list[dict[str, Any]]:
    ws = _obter_ou_criar_worksheet(planilha, RADAR_RESULTADOS_WORKSHEET, RADAR_RESULTADOS_HEADERS)
    return ws.get_all_records()


def _garantir_colunas(ws: gspread.Worksheet, colunas: list[str]) -> dict[str, int]:
    header = ws.row_values(1) or []
    alterou = False
    for coluna in colunas:
        if coluna not in header:
            header.append(coluna)
            alterou = True
    if alterou:
        try:
            ws.update("1:1", [header])
            _info(f"Cabeçalhos atualizados na aba `{ws.title}`.")
        except Exception as exc:
            raise SheetsClientError(
                f"Não foi possível criar cabeçalhos na aba `{ws.title}`: {exc}"
            ) from exc
    return {nome: index for index, nome in enumerate(header, start=1) if nome}


def _append_dict_row(ws: gspread.Worksheet, colunas: dict[str, int], dados: dict[str, Any]) -> None:
    target_length = max(colunas.values(), default=len(colunas))
    linha = ensure_row_length([], target_length)
    for chave, valor in dados.items():
        coluna = colunas.get(chave)
        if not coluna:
            _warning(f"Coluna `{chave}` não encontrada na aba `{ws.title}`.")
            continue
        linha = ensure_row_length(linha, coluna)
        linha[coluna - 1] = valor
    ws.append_row(linha, value_input_option="USER_ENTERED")


def registrar_radar_resultados(planilha: gspread.Spreadsheet, vagas: list[dict[str, Any]]) -> int:
    if not vagas:
        return 0
    try:
        ws = _obter_ou_criar_worksheet(
            planilha,
            RADAR_RESULTADOS_WORKSHEET,
            RADAR_RESULTADOS_HEADERS,
        )
        colunas = _garantir_colunas(ws, RADAR_RESULTADOS_HEADERS)
        for vaga in vagas:
            _append_dict_row(ws, colunas, vaga)
        return len(vagas)
    except Exception as exc:
        raise SheetsClientError(
            "Não foi possível registrar resultados do Radar na planilha."
        ) from exc


def _normalizar_texto(valor: Any) -> str:
    return str(valor or "").strip().lower()


def _normalizar_status(valor: Any) -> str:
    return " ".join(str(valor or "").strip().lower().split())


def _is_link_pendente(valor: Any) -> bool:
    return _normalizar_status(valor) in STATUS_LINK_PENDENTE_VARIANTES


def _resolver_coluna_observacoes(colunas: dict[str, int]) -> int | None:
    if "Observações" in colunas:
        return colunas["Observações"]
    for nome, coluna in colunas.items():
        if _normalizar_status(nome) in OBSERVACOES_ALIASES:
            return coluna
    return max(colunas.values(), default=0) or None


def diagnosticar_vagas_crm(planilha: gspread.Spreadsheet) -> dict[str, Any]:
    ws = _obter_ou_criar_worksheet(planilha, VAGAS_WORKSHEET, VAGAS_CRM_RADAR_HEADERS)
    registros = ws.get_all_records()
    contagem_status: dict[str, int] = {}
    link_pendente_exato = 0

    for registro in registros:
        status_bruto = str(registro.get("Status", ""))
        status = status_bruto.strip()
        chave = status or "(vazio)"
        contagem_status[chave] = contagem_status.get(chave, 0) + 1
        if status_bruto == STATUS_LINK_PENDENTE_CANONICO:
            link_pendente_exato += 1

    return {
        "nome_planilha": getattr(planilha, "title", ""),
        "abas": [worksheet.title for worksheet in planilha.worksheets()],
        "total_linhas_vagas_crm": len(registros),
        "contagem_status": contagem_status,
        "link_pendente_exato": link_pendente_exato,
    }


def _vaga_duplicada(existentes: list[dict[str, Any]], vaga: dict[str, Any]) -> bool:
    link = _normalizar_texto(vaga.get("Link"))
    empresa = _normalizar_texto(vaga.get("Empresa"))
    cargo = _normalizar_texto(vaga.get("Cargo"))
    for existente in existentes:
        link_existente = _normalizar_texto(existente.get("Link"))
        empresa_existente = _normalizar_texto(existente.get("Empresa"))
        cargo_existente = _normalizar_texto(existente.get("Cargo"))
        if link and link == link_existente:
            return True
        if empresa and cargo and empresa == empresa_existente and cargo == cargo_existente:
            return True
    return False


def encontrar_duplicata_link(planilha: gspread.Spreadsheet, link: str, row_number: int) -> int | None:
    if not link:
        return None
    ws = _obter_ou_criar_worksheet(planilha, VAGAS_WORKSHEET, VAGAS_CRM_RADAR_HEADERS)
    registros = ws.get_all_records()
    link_normalizado = _normalizar_texto(link)
    for index, registro in enumerate(registros, start=2):
        if index == row_number:
            continue
        if link_normalizado and link_normalizado == _normalizar_texto(registro.get("Link")):
            return index
    return None


def enviar_para_vagas_crm(planilha: gspread.Spreadsheet, vagas: list[dict[str, Any]]) -> tuple[int, list[str]]:
    if not vagas:
        return 0, []
    try:
        ws = _obter_ou_criar_worksheet(
            planilha,
            VAGAS_WORKSHEET,
            VAGAS_CRM_RADAR_HEADERS,
        )
        colunas = _garantir_colunas(ws, VAGAS_CRM_RADAR_HEADERS)
        existentes = ws.get_all_records()
        avisos = []
        inseridas = 0
        for vaga in vagas:
            if _vaga_duplicada(existentes, vaga):
                avisos.append(
                    f"Duplicada ignorada: {vaga.get('Empresa', '')} | {vaga.get('Cargo', '')}"
                )
                continue
            _append_dict_row(ws, colunas, vaga)
            existentes.append(vaga)
            inseridas += 1
        return inseridas, avisos
    except Exception as exc:
        raise SheetsClientError(
            "Não foi possível enviar vagas para `Vagas_CRM`. "
            "Confira os cabeçalhos e permissões da planilha."
        ) from exc


def atualizar_link_pendente(
    planilha: gspread.Spreadsheet,
    row_number: int,
    dados: dict[str, Any],
    status: str,
) -> None:
    try:
        ws = _obter_ou_criar_worksheet(planilha, VAGAS_WORKSHEET, VAGAS_CRM_RADAR_HEADERS)
        colunas = _garantir_colunas(ws, VAGAS_CRM_RADAR_HEADERS)
        atual = ws.row_values(row_number)
        updates = []
        sobrescrever = {"Status", "Observações"}
        for chave, valor in dados.items():
            coluna = _resolver_coluna_observacoes(colunas) if chave == "Observações" else colunas.get(chave)
            if not coluna:
                _warning(f"Coluna `{chave}` não encontrada na aba `{VAGAS_WORKSHEET}`.")
                continue
            atual = ensure_row_length(atual, coluna)
            if chave not in sobrescrever and str(atual[coluna - 1]).strip():
                continue
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_number, coluna),
                    "values": [[valor]],
                }
            )

        coluna_status = colunas.get("Status")
        if coluna_status:
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_number, coluna_status),
                    "values": [[status]],
                }
            )
        if updates:
            ws.batch_update(updates, value_input_option="USER_ENTERED")
    except Exception as exc:
        raise SheetsClientError(
            "Não foi possível processar o link pendente na aba `Vagas_CRM`."
        ) from exc


def atualizar_vaga(planilha: gspread.Spreadsheet, row_number: int, analise: dict) -> None:
    try:
        ws = _worksheet(planilha, VAGAS_WORKSHEET)
        colunas = _garantir_colunas(
            ws,
            [
                "Fit Score",
                "Prioridade",
                "Decisão",
                "Versão CV",
                "Expectativa salarial",
                "Próxima ação",
                "Status",
            ],
        )
        valores = {
            "Fit Score": analise["fit_score"],
            "Prioridade": analise["prioridade"],
            "Decisão": analise["decisao"],
            "Versão CV": analise["versao_cv_recomendada"],
            "Expectativa salarial": analise["expectativa_salarial"],
            "Próxima ação": analise["proxima_acao"],
            "Status": "CV gerado",
        }
        updates = []
        for nome, valor in valores.items():
            coluna = colunas.get(nome)
            if not coluna:
                _warning(f"Coluna `{nome}` não encontrada na aba `{VAGAS_WORKSHEET}`.")
                continue
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_number, coluna),
                    "values": [[valor]],
                }
            )
        if updates:
            ws.batch_update(updates, value_input_option="USER_ENTERED")
    except SheetsClientError:
        raise
    except Exception as exc:
        raise SheetsClientError(
            "Não foi possível atualizar a vaga na planilha. "
            "Confira os cabeçalhos da aba `Vagas_CRM` e tente novamente."
        ) from exc


def registrar_output(planilha: gspread.Spreadsheet, dados: dict[str, Any]) -> None:
    try:
        try:
            ws = planilha.worksheet(OUTPUTS_WORKSHEET)
        except gspread.WorksheetNotFound:
            ws = planilha.add_worksheet(title=OUTPUTS_WORKSHEET, rows=1000, cols=20)
            _info(f"Aba `{OUTPUTS_WORKSHEET}` criada automaticamente.")

        colunas = _garantir_colunas(ws, list(dados.keys()))
        _append_dict_row(ws, colunas, dados)
    except SheetsClientError:
        raise
    except Exception as exc:
        raise SheetsClientError(
            "Não foi possível registrar o output na planilha. "
            "Confira os cabeçalhos da aba `Outputs` e tente novamente."
        ) from exc
