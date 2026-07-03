from __future__ import annotations

import json
from typing import Any

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials


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


class SheetsClientError(RuntimeError):
    """Erro de configuração ou comunicação com Google Sheets."""


def ensure_row_length(row: list[Any], target_length: int) -> list[Any]:
    if len(row) < target_length:
        row.extend([""] * (target_length - len(row)))
    return row


def _service_account_info() -> dict:
    json_text = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if json_text:
        try:
            return json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise SheetsClientError(
                "`GOOGLE_SERVICE_ACCOUNT_JSON` contém JSON inválido. "
                "Cole o JSON inteiro da service account dentro de três aspas simples."
            ) from exc

    info = st.secrets.get("GOOGLE_SERVICE_ACCOUNT")
    if not info:
        raise SheetsClientError(
            "Configure `GOOGLE_SERVICE_ACCOUNT_JSON` em `st.secrets`. "
            "O formato antigo `GOOGLE_SERVICE_ACCOUNT` ainda é aceito."
        )
    return dict(info)


def conectar_planilha() -> gspread.Spreadsheet:
    sheet_id = st.secrets.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise SheetsClientError("Configure `GOOGLE_SHEET_ID` em `st.secrets`.")

    try:
        credentials = Credentials.from_service_account_info(
            _service_account_info(),
            scopes=SCOPES,
        )
        client = gspread.authorize(credentials)
        return client.open_by_key(sheet_id)
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
        st.info(f"Aba `{nome}` criada automaticamente.")
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


def garantir_abas_radar(planilha: gspread.Spreadsheet) -> None:
    _obter_ou_criar_worksheet(planilha, RADAR_CONFIG_WORKSHEET, RADAR_CONFIG_HEADERS)
    _obter_ou_criar_worksheet(planilha, EMPRESAS_ALVO_WORKSHEET, EMPRESAS_ALVO_HEADERS)
    _obter_ou_criar_worksheet(planilha, RADAR_RESULTADOS_WORKSHEET, RADAR_RESULTADOS_HEADERS)


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
            st.info(f"Cabeçalhos atualizados na aba `{ws.title}`.")
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
            st.warning(f"Coluna `{chave}` não encontrada na aba `{ws.title}`.")
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
                st.warning(f"Coluna `{nome}` não encontrada na aba `{VAGAS_WORKSHEET}`.")
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
            st.info(f"Aba `{OUTPUTS_WORKSHEET}` criada automaticamente.")

        colunas = _garantir_colunas(ws, list(dados.keys()))
        _append_dict_row(ws, colunas, dados)
    except SheetsClientError:
        raise
    except Exception as exc:
        raise SheetsClientError(
            "Não foi possível registrar o output na planilha. "
            "Confira os cabeçalhos da aba `Outputs` e tente novamente."
        ) from exc
