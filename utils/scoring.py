from __future__ import annotations


CAMPOS_LISTA = ["pontos_fortes", "lacunas", "red_flags", "palavras_chave_ats"]


def _lista(valor) -> list[str]:
    if valor is None:
        return []
    if isinstance(valor, list):
        return [str(item).strip() for item in valor if str(item).strip()]
    return [str(valor).strip()] if str(valor).strip() else []


def _texto(valor, fallback: str = "") -> str:
    if valor is None:
        return fallback
    texto = str(valor).strip()
    return texto or fallback


def normalizar_analise(analise: dict) -> dict:
    try:
        fit_score = int(float(analise.get("fit_score", 0)))
    except (TypeError, ValueError):
        fit_score = 0
    fit_score = max(0, min(100, fit_score))

    normalizada = {
        "fit_score": fit_score,
        "prioridade": _texto(analise.get("prioridade"), "Baixa"),
        "decisao": _texto(analise.get("decisao"), "Avaliar com cautela"),
        "versao_cv_recomendada": _texto(
            analise.get("versao_cv_recomendada"),
            "lideranca_criativa",
        ),
        "expectativa_salarial": _texto(analise.get("expectativa_salarial"), "A avaliar"),
        "proxima_acao": _texto(analise.get("proxima_acao"), "Revisar vaga manualmente"),
        "justificativa": _texto(analise.get("justificativa"), ""),
    }
    for campo in CAMPOS_LISTA:
        normalizada[campo] = _lista(analise.get(campo))
    return normalizada
