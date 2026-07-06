from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

from utils.job_radar import (
    buscar_adzuna,
    buscar_greenhouse,
    buscar_lever,
    campos_faltantes_para_avaliacao,
    inferir_plataforma,
    normalizar_para_radar,
    radar_para_vagas_crm,
)
from utils.job_link_extractor import extrair_dados_link, prompt_estruturacao_link
from utils.openai_client import OpenAIClientError, gerar_json, gerar_texto
from utils.pdf_generator import gerar_cv_pdf
from utils.scoring import normalizar_analise
from utils.sheets import (
    SheetsClientError,
    atualizar_vaga,
    conectar_planilha,
    diagnosticar_vagas_crm,
    enviar_para_vagas_crm,
    encontrar_duplicata_link,
    garantir_abas_radar,
    atualizar_link_pendente,
    ler_empresas_alvo,
    ler_links_pendentes,
    ler_radar_resultados,
    ler_vagas_avaliar,
    registrar_output,
    registrar_radar_resultados,
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
    "Este CV foi elaborado",
    "CV direcionado",
    "Expectativa Salarial",
    "[LinkedIn]",
    "](",
    "**",
    "---",
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
        "radar_resultados": [],
        "link_preview": None,
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


def estruturar_link_com_openai(url: str, plataforma: str):
    def _estruturar(texto: str) -> dict:
        return gerar_json(
            system_prompt="Você extrai dados de vagas a partir de texto público. Responda apenas JSON válido e nunca invente dados.",
            user_prompt=prompt_estruturacao_link(url, plataforma, texto),
        )

    return _estruturar


def preview_para_crm(preview: dict) -> dict:
    crm = radar_para_vagas_crm(
        {
            "data_busca": preview.get("data_busca", datetime.now().date().isoformat()),
            "fonte": "Link manual",
            "empresa": preview.get("empresa", ""),
            "cargo": preview.get("cargo", ""),
            "link": preview.get("link", ""),
            "local": preview.get("local", ""),
            "modelo": preview.get("modelo", ""),
            "regime": preview.get("regime", ""),
            "senioridade": preview.get("senioridade", ""),
            "area_principal": preview.get("area_principal", ""),
            "descricao": preview.get("descricao_vaga", ""),
            "observacoes": preview.get("observacoes_extracao", ""),
            "motivo": preview.get("motivo", ""),
        }
    )
    crm["Plataforma"] = preview.get("plataforma", "") or inferir_plataforma(preview.get("link", ""))
    return crm


def sidebar_config() -> None:
    st.sidebar.title("agente-candidaturas")
    st.sidebar.caption("Agentes de radar e candidatura")

    with st.sidebar.expander("Configuração esperada", expanded=False):
        st.markdown(
            """
            - `OPENAI_API_KEY`
            - `OPENAI_MODEL`
            - `GOOGLE_SHEET_ID`
            - `GOOGLE_SERVICE_ACCOUNT_JSON`
            """
        )


def render_radar() -> None:
    st.subheader("Radar de Vagas Estratégicas")
    st.caption("Agente 1 automático: GitHub Actions + OpenAI Web Search + fontes públicas alimentando Vagas_CRM.")

    try:
        planilha = conectar_planilha()
        garantir_abas_radar(planilha)
        diagnostico = diagnosticar_vagas_crm(planilha)
        resultados_planilha = ler_radar_resultados(planilha)
    except SheetsClientError as exc:
        st.error(str(exc))
        return

    status_counts = diagnostico.get("contagem_status", {})
    ultima_execucao = max(
        [str(item.get("data_busca", "")) for item in resultados_planilha if item.get("data_busca")],
        default="Ainda não registrada",
    )
    total_avaliar = status_counts.get("Avaliar", 0)
    total_precisa = status_counts.get("Precisa descrição", 0)

    st.success("Radar automático ativo")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Última execução conhecida", ultima_execucao)
    m2.metric("Vagas em Avaliar", total_avaliar)
    m3.metric("Precisa descrição", total_precisa)
    m4.metric("Capturadas pelo Radar", len(resultados_planilha))
    st.info("A operação normal acontece pelo GitHub Actions. Use o Agente 2 para revisar vagas novas e gerar candidaturas.")

    with st.expander("Ferramentas manuais e diagnóstico", expanded=False):
        st.markdown("### Inserir vaga por link")
        url_vaga = st.text_input("URL da vaga", key="radar_url_vaga")
        if st.button("Extrair dados da vaga", use_container_width=True):
            if not url_vaga:
                st.warning("Cole uma URL de vaga antes de extrair.")
            else:
                try:
                    plataforma = inferir_plataforma(url_vaga)
                    st.session_state.link_preview = extrair_dados_link(
                        url_vaga,
                        estruturador=estruturar_link_com_openai(url_vaga, plataforma),
                    )
                    st.success("Dados extraídos. Revise a prévia antes de enviar.")
                except Exception as exc:
                    st.error(f"Não foi possível extrair a vaga: {exc}")

        preview = st.session_state.link_preview
        if preview:
            preview["empresa"] = st.text_input("Empresa", value=preview.get("empresa", ""), key="preview_empresa")
            preview["cargo"] = st.text_input("Cargo", value=preview.get("cargo", ""), key="preview_cargo")
            preview["descricao_vaga"] = st.text_area("Descrição da vaga", value=preview.get("descricao_vaga", ""), height=180, key="preview_descricao")
            preview["observacoes_extracao"] = st.text_area("Observações", value=preview.get("observacoes_extracao", ""), height=80, key="preview_observacoes")
            if st.button("Enviar link para Vagas_CRM", type="primary", use_container_width=True):
                try:
                    inseridas, avisos = enviar_para_vagas_crm(planilha, [preview_para_crm(preview)])
                    st.success(f"{inseridas} vaga(s) enviada(s) para Vagas_CRM.")
                    for aviso in avisos:
                        st.warning(aviso)
                except SheetsClientError as exc:
                    st.error(str(exc))

        st.markdown("### Processar links pendentes")
        if st.button("Processar links pendentes", use_container_width=True):
            try:
                pendentes = ler_links_pendentes(planilha)
                for item in pendentes:
                    link_pendente = item.get("Link", "")
                    if not link_pendente:
                        atualizar_link_pendente(
                            planilha,
                            item["_row_number"],
                            {"Observações": "Não foi possível extrair dados automaticamente. Cole a descrição da vaga manualmente."},
                            "Precisa descrição",
                        )
                        continue
                    duplicada_linha = encontrar_duplicata_link(planilha, link_pendente, item["_row_number"])
                    if duplicada_linha:
                        atualizar_link_pendente(
                            planilha,
                            item["_row_number"],
                            {"Observações": f"Link duplicado. Já existe na linha {duplicada_linha}."},
                            "Duplicada",
                        )
                        continue
                    extraido = extrair_dados_link(link_pendente)
                    crm = preview_para_crm(extraido)
                    faltantes = campos_faltantes_para_avaliacao(crm)
                    status = "Avaliar" if extraido.get("status_extracao") == "sucesso" and not faltantes else "Precisa descrição"
                    atualizar_link_pendente(planilha, item["_row_number"], crm, status)
                st.success(f"{len(pendentes)} link(s) pendente(s) processado(s).")
            except Exception as exc:
                st.error(f"Não foi possível processar links pendentes: {exc}")

        st.markdown("### Entrada manual assistida")
        with st.form("radar_manual_form"):
            c1, c2 = st.columns(2)
            empresa = c1.text_input("Empresa")
            cargo = c2.text_input("Cargo")
            link = st.text_input("Link da vaga")
            local = st.text_input("Local")
            descricao = st.text_area("Descrição da vaga", height=160)
            observacoes = st.text_area("Observações", height=80)
            salvar_manual = st.form_submit_button("Salvar em Vagas_CRM", type="primary")

        if salvar_manual:
            radar_vaga = normalizar_para_radar(
                {"empresa": empresa, "cargo": cargo, "link": link, "local": local, "descricao": descricao, "observacoes": observacoes},
                "Manual assistido",
            )
            try:
                inseridas, avisos = enviar_para_vagas_crm(planilha, [radar_para_vagas_crm({**radar_vaga, "descricao": descricao})])
                st.success(f"{inseridas} vaga(s) enviada(s) para Vagas_CRM.")
                for aviso in avisos:
                    st.warning(aviso)
            except SheetsClientError as exc:
                st.error(str(exc))

        st.markdown("### Busca Adzuna manual")
        adzuna_id = st.secrets.get("ADZUNA_APP_ID")
        adzuna_key = st.secrets.get("ADZUNA_APP_KEY")
        if not adzuna_id or not adzuna_key:
            st.warning("Adzuna não configurado.")
        else:
            termo = st.text_input("Termo Adzuna", value="Creative Director")
            if st.button("Buscar no Adzuna", use_container_width=True):
                resultados = buscar_adzuna(adzuna_id, adzuna_key, termo, "br", "", 10)
                registrar_radar_resultados(planilha, resultados)
                st.session_state.radar_resultados = resultados
                st.success(f"{len(resultados)} resultados registrados.")

        st.markdown("### Greenhouse / Lever manual")
        if st.button("Buscar empresas-alvo públicas", use_container_width=True):
            resultados = []
            avisos = []
            for empresa_cfg in ler_empresas_alvo(planilha):
                plataforma = str(empresa_cfg.get("plataforma", "")).strip().lower()
                empresa_nome = str(empresa_cfg.get("empresa", "")).strip()
                site = str(empresa_cfg.get("board_token") or empresa_cfg.get("site_carreiras", "")).strip()
                try:
                    if plataforma == "greenhouse":
                        resultados.extend(buscar_greenhouse(site, empresa_nome))
                    elif plataforma == "lever":
                        resultados.extend(buscar_lever(site, empresa_nome))
                except Exception as exc:
                    avisos.append(f"{empresa_nome}: busca pública indisponível ({exc}).")
            registrar_radar_resultados(planilha, resultados)
            st.session_state.radar_resultados = resultados
            st.success(f"{len(resultados)} resultados públicos registrados.")
            for aviso in avisos:
                st.warning(aviso)

        st.markdown("### Radar_Resultados")
        if st.button("Carregar Radar_Resultados da planilha", use_container_width=True):
            st.session_state.radar_resultados = ler_radar_resultados(planilha)

        resultados = st.session_state.radar_resultados
        if resultados:
            linhas = [{"selecionar": False, **item} for item in resultados]
            editado = st.data_editor(linhas, use_container_width=True, hide_index=True, key="radar_resultados_editor")
            selecionadas = [linha for linha in editado if linha.get("selecionar")]
            if st.button("Enviar selecionadas para Vagas_CRM", type="primary", use_container_width=True):
                vagas_crm = [radar_para_vagas_crm(vaga) for vaga in selecionadas]
                inseridas, avisos = enviar_para_vagas_crm(planilha, vagas_crm)
                st.success(f"{inseridas} vaga(s) enviada(s) para Vagas_CRM.")
                for aviso in avisos:
                    st.warning(aviso)


def render_agente2() -> None:
    st.subheader("Agente 2: Candidatura de Alta Aderência")

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


def main() -> None:
    inicializar_estado()
    sidebar_config()

    st.title("agente-candidaturas")
    st.caption("Radar de vagas, análise de aderência e geração de pacote de candidatura.")

    tab_radar, tab_agente2 = st.tabs(
        ["Radar de Vagas Estratégicas", "Candidatura de Alta Aderência"]
    )
    with tab_radar:
        render_radar()
    with tab_agente2:
        render_agente2()


if __name__ == "__main__":
    main()
