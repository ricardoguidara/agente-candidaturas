from __future__ import annotations

import json

import streamlit as st
from openai import OpenAI


class OpenAIClientError(RuntimeError):
    """Erro de configuração ou execução da OpenAI API."""


def _client() -> OpenAI:
    api_key = st.secrets.get("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIClientError("Configure `OPENAI_API_KEY` em `st.secrets`.")
    return OpenAI(api_key=api_key)


def _model() -> str:
    return st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")


def gerar_texto(system_prompt: str, user_prompt: str) -> str:
    try:
        response = _client().chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
    except Exception as exc:
        raise OpenAIClientError(f"Erro ao chamar OpenAI API: {exc}") from exc

    content = response.choices[0].message.content
    if not content:
        raise OpenAIClientError("A OpenAI retornou uma resposta vazia.")
    return content


def gerar_json(system_prompt: str, user_prompt: str) -> dict:
    try:
        response = _client().chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    except Exception as exc:
        raise OpenAIClientError(f"Erro ao chamar OpenAI API: {exc}") from exc

    content = response.choices[0].message.content
    if not content:
        raise OpenAIClientError("A OpenAI retornou JSON vazio.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenAIClientError(f"JSON inválido retornado pela OpenAI: {exc}") from exc

    if not isinstance(parsed, dict):
        raise OpenAIClientError("A resposta JSON precisa ser um objeto.")
    return parsed
