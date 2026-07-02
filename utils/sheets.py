from __future__ import annotations

from typing import Any

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials


VAGAS_WORKSHEET = "Vagas_CRM"
OUTPUTS_WORKSHEET = "Outputs"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsClientError(RuntimeError):
    """Erro de configuração ou comunicação com Google Sheets."""


def _service_account_info() -> dict:
    info = st.secrets.get("GOOGLE_SERVICE_ACCOUNT")
    if not info:
        raise SheetsClientError("Configure `GOOGLE_SERVICE_ACCOUNT` em `st.secrets`.")
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


def ler_vagas_avaliar(planilha: gspread.Spreadsheet) -> list[dict[str, Any]]:
    ws = _worksheet(planilha, VAGAS_WORKSHEET)
    registros = ws.get_all_records()
    vagas = []
    for index, registro in enumerate(registros, start=2):
        if str(registro.get("Status", "")).strip().lower() == "avaliar":
            registro["_row_number"] = index
            vagas.append(registro)
    return vagas


def _garantir_colunas(ws: gspread.Worksheet, colunas: list[str]) -> dict[str, int]:
    header = ws.row_values(1)
    alterou = False
    for coluna in colunas:
        if coluna not in header:
            header.append(coluna)
            alterou = True
    if alterou:
        ws.update("1:1", [header])
    return {nome: index for index, nome in enumerate(header, start=1)}


def atualizar_vaga(planilha: gspread.Spreadsheet, row_number: int, analise: dict) -> None:
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
    updates = [
        {
            "range": gspread.utils.rowcol_to_a1(row_number, colunas[nome]),
            "values": [[valor]],
        }
        for nome, valor in valores.items()
    ]
    ws.batch_update(updates, value_input_option="USER_ENTERED")


def registrar_output(planilha: gspread.Spreadsheet, dados: dict[str, Any]) -> None:
    try:
        ws = planilha.worksheet(OUTPUTS_WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = planilha.add_worksheet(title=OUTPUTS_WORKSHEET, rows=1000, cols=20)

    colunas = _garantir_colunas(ws, list(dados.keys()))
    linha = [""] * len(colunas)
    for chave, valor in dados.items():
        linha[colunas[chave] - 1] = valor
    ws.append_row(linha, value_input_option="USER_ENTERED")
