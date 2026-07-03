from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

from utils.openai_client import OpenAIClientError, gerar_json, gerar_texto
from utils.pdf_generator import gerar_cv_pdf
from utils.scoring import normalizar_analise
from utils.sheets import (
    SheetsClientError,
    atualizar_vaga,
    conectar_planilha,
    ler_vagas_avaliar,
    registrar_output,
)


BASE_DIR = Path(__file__).parent
PROMPTS_DIR = BASE_DIR / "prompts"
CV_INVALIDO_MSG = (
    "CV contém placeholders ou dados inválidos. "
    "Ajuste o prompt ou revise a saída antes de gerar o PDF."
)
PADROES_CV_INVALIDO = [
    "[Seu",
    "[Nome",
    "[Data",
    "[Cidade",
    "[Universidade",
    "Lorem ipsum",
    "Endereço",
    "Endereco",
    "https://ricardoguidara.com/(https://ricardoguidara.com/)",
]


st.set_page_config(
    page_title="agente-candidaturas",
    page_icon="📄",
    layout="wide",
)


def carregar_prompt(nome_arquivo: str) -> str:
    return (PROMPTS_DIR / nome_arquivo).read_text(encoding="utf-8")


def vaga_para_contexto(vaga: dict) -> str:
    linhas = []
    for chave, valor in vaga.items():
        if chave == "_row_number":
            continue
        if valor not in (None, ""):
            linhas.append(f"{chave}: {valor}")
    return "\n".join(linhas)


def criar_prompt_completo(prompt: str, perfil: str, vaga: dict, analise: dict | None = None) -> str:
    conteudo = prompt.replace("{{PERFIL_BASE}}", perfil)
    conteudo = conteudo.replace("{{DESCRICAO_VAGA}}", vaga_para_contexto(vaga))
    if analise is not None:
        conteudo = conteudo.replace(
            "{{ANALISE_JSON}}",
            json.dumps(analise, ensure_ascii=False, indent=2),
        )
    return conteudo


def validar_cv_para_pdf(cv_texto_final: str) -> list[str]:
    problemas = []
    texto_lower = cv_texto_final.lower()

    for padrao in PADROES_CV_INVALIDO:
        if padrao.lower() in texto_lower:
            problemas.append(f"Padrão inválido encontrado: {padrao}")

    for linha in cv_texto_final.splitlines():
        linha_limpa = linha.strip()
        tem_rotulo_telefone = re.search(r"\btelefone\b", linha_limpa, flags=re.IGNORECASE)
        tem_numero_real = re.search(r"\d{8,}", linha_limpa)
        if tem_rotulo_telefone and not tem_numero_real:
            problemas.append("Campo Telefone sem dado real.")

    return problemas


def mostrar_lista(titulo: str, itens: list[str]) -> None:
    st.markdown(f"**{titulo}**")
    if itens:
        for item in itens:
            st.markdown(f"- {item}")
    else:
        st.caption("Nenhum item informado.")


def mostrar_analise(analise: dict) -> None:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Fit score", analise["fit_score"])
    m2.metric("Prioridade", analise["prioridade"])
    m3.metric("Decisão", analise["decisao"])
    m4.metric("Versão CV", analise["versao_cv_recomendada"])

    st.markdown(f"**Expectativa salarial:** {analise['expectativa_salarial']}")
    st.markdown(f"**Próxima ação:** {analise['proxima_acao']}")
    st.markdown(f"**Justificativa:** {analise['justificativa']}")

    col1, col2 = st.columns(2)
    with col1:
        mostrar_lista("Pontos fortes", analise["pontos_fortes"])
        mostrar_lista("Lacunas", analise["lacunas"])
    with col2:
        mostrar_lista("Red flags", analise["red_flags"])
        mostrar_lista("Palavras-chave ATS", analise["palavras_chave_ats"])

    with st.expander("JSON completo da análise", expanded=False):
        st.json(analise)


def inicializar_estado() -> None:
    defaults = {
        "vagas": [],
        "vaga_selecionada": None,
        "analise": None,
        "pacote": None,
        "pdf_bytes": None,
    }
    for chave, valor in defaults.items():
        st.session_state.setdefault(chave, valor)


def gerar_pacote(vaga: dict, analise: dict) -> dict:
    perfil = carregar_prompt("perfil_base_ricardo.md")

    cv = gerar_texto(
        system_prompt="Você é um especialista em CVs executivos, ATS-friendly, para cargos de liderança criativa.",
        user_prompt=criar_prompt_completo(
            carregar_prompt("prompt_cv.md"),
            perfil,
            vaga,
            analise,
        ),
    )
    carta = gerar_texto(
        system_prompt="Você escreve cartas de apresentação objetivas, humanas e adequadas ao mercado brasileiro.",
        user_prompt=criar_prompt_completo(
            carregar_prompt("prompt_carta.md"),
            perfil,
            vaga,
            analise,
        ),
    )
    formulario = gerar_json(
        system_prompt="Você gera respostas de formulário de candidatura em JSON válido.",
        user_prompt=criar_prompt_completo(
            carregar_prompt("prompt_formulario.md"),
            perfil,
            vaga,
            analise,
        ),
    )

    return {
        "cv_texto": cv.strip(),
        "carta_apresentacao": carta.strip(),
        "mensagem_linkedin": formulario.get("mensagem_linkedin", ""),
        "respostas_formulario": formulario.get("respostas_formulario", []),
        "checklist_aplicacao": formulario.get("checklist_aplicacao", []),
    }


def sidebar_config() -> None:
    st.sidebar.title("agente-candidaturas")
    st.sidebar.caption("Agente 2: candidatura de alta aderência")

    with st.sidebar.expander("Configuração esperada", expanded=False):
        st.markdown(
            """
            - `OPENAI_API_KEY`
            - `OPENAI_MODEL`
            - `GOOGLE_SHEET_ID`
            - `GOOGLE_SERVICE_ACCOUNT_JSON`
            """
        )


def main() -> None:
    inicializar_estado()
    sidebar_config()

    st.title("agente-candidaturas")
    st.caption("Leitura de vagas, análise de aderência e geração de pacote de candidatura.")

    col_carregar, col_status = st.columns([1, 2])
    with col_carregar:
        if st.button("Carregar vagas pendentes", type="primary", use_container_width=True):
            try:
                planilha = conectar_planilha()
                st.session_state.vagas = ler_vagas_avaliar(planilha)
                st.session_state.analise = None
                st.session_state.pacote = None
                st.session_state.pdf_bytes = None
            except SheetsClientError as exc:
                st.error(str(exc))

    with col_status:
        total = len(st.session_state.vagas)
        st.metric("Vagas com status Avaliar", total)

    if not st.session_state.vagas:
        st.info("Carregue a planilha para listar as vagas com status `Avaliar`.")
        return

    opcoes = {
        f"{vaga.get('Empresa', 'Empresa não informada')} | {vaga.get('Cargo', vaga.get('Vaga', 'Cargo não informado'))} | linha {vaga['_row_number']}": vaga
        for vaga in st.session_state.vagas
    }
    escolha = st.selectbox("Selecione uma vaga", options=list(opcoes.keys()))
    vaga = opcoes[escolha]
    st.session_state.vaga_selecionada = vaga

    st.subheader("Detalhes da vaga")
    st.dataframe(
        {k: [v] for k, v in vaga.items() if k != "_row_number"},
        use_container_width=True,
        hide_index=True,
    )

    col_analise, col_pacote = st.columns(2)

    with col_analise:
        if st.button("Analisar aderência", use_container_width=True):
            try:
                perfil = carregar_prompt("perfil_base_ricardo.md")
                prompt = criar_prompt_completo(
                    carregar_prompt("prompt_avaliacao.md"),
                    perfil,
                    vaga,
                )
                analise_bruta = gerar_json(
                    system_prompt="Você é um avaliador sênior de aderência entre vagas e perfis executivos criativos. Responda apenas JSON válido.",
                    user_prompt=prompt,
                )
                st.session_state.analise = normalizar_analise(analise_bruta, vaga)
                st.session_state.pacote = None
                st.session_state.pdf_bytes = None
            except (OpenAIClientError, ValueError) as exc:
                st.error(str(exc))

    if st.session_state.analise:
        st.subheader("Análise estruturada")
        analise = st.session_state.analise
        mostrar_analise(analise)

        with col_pacote:
            if st.button("Gerar pacote de candidatura", type="primary", use_container_width=True):
                try:
                    pacote = gerar_pacote(vaga, analise)
                    problemas_cv = validar_cv_para_pdf(pacote["cv_texto"])
                    if problemas_cv:
                        st.session_state.pacote = pacote
                        st.session_state.pdf_bytes = None
                        with st.expander("Problemas encontrados no CV", expanded=True):
                            for problema in problemas_cv:
                                st.markdown(f"- {problema}")
                        raise ValueError(CV_INVALIDO_MSG)

                    pdf_bytes = gerar_cv_pdf(
                        nome="Ricardo Guidara",
                        cargo_alvo=vaga.get("Cargo") or vaga.get("Vaga") or "Candidatura",
                        texto_cv=pacote["cv_texto"],
                    )
                    st.session_state.pacote = pacote
                    st.session_state.pdf_bytes = pdf_bytes

                    planilha = conectar_planilha()
                    atualizar_vaga(planilha, vaga["_row_number"], analise)
                    registrar_output(
                        planilha,
                        {
                            "Timestamp": datetime.now().isoformat(timespec="seconds"),
                            "Linha Vaga": vaga["_row_number"],
                            "Empresa": vaga.get("Empresa", ""),
                            "Cargo": vaga.get("Cargo", vaga.get("Vaga", "")),
                            "Fit Score": analise["fit_score"],
                            "Decisão": analise["decisao"],
                            "CV": pacote["cv_texto"],
                            "Carta": pacote["carta_apresentacao"],
                            "LinkedIn": pacote["mensagem_linkedin"],
                            "Formulário JSON": json.dumps(
                                pacote["respostas_formulario"],
                                ensure_ascii=False,
                            ),
                            "Checklist JSON": json.dumps(
                                pacote["checklist_aplicacao"],
                                ensure_ascii=False,
                            ),
                        },
                    )
                    st.success("Pacote gerado, vaga atualizada e output registrado.")
                except (OpenAIClientError, SheetsClientError, ValueError) as exc:
                    st.error(str(exc))

    if st.session_state.pacote:
        pacote = st.session_state.pacote
        st.subheader("Pacote de candidatura")

        if st.session_state.pdf_bytes:
            st.download_button(
                "Baixar CV em PDF",
                data=st.session_state.pdf_bytes,
                file_name="CV_Ricardo_Guidara.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.warning(CV_INVALIDO_MSG)

        tabs = st.tabs(["CV", "Carta", "LinkedIn", "Formulário", "Checklist"])
        tabs[0].text_area("Texto final do CV", pacote["cv_texto"], height=420)
        tabs[1].text_area("Carta de apresentação", pacote["carta_apresentacao"], height=320)
        tabs[2].text_area("Mensagem LinkedIn", pacote["mensagem_linkedin"], height=180)

        with tabs[3]:
            for item in pacote["respostas_formulario"]:
                pergunta = item.get("pergunta", "Pergunta")
                resposta = item.get("resposta", "")
                st.markdown(f"**{pergunta}**")
                st.write(resposta)

        with tabs[4]:
            for item in pacote["checklist_aplicacao"]:
                st.checkbox(str(item), value=False)


if __name__ == "__main__":
    main()
