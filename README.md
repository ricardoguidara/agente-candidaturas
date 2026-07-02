# agente-candidaturas

MVP em Python/Streamlit para avaliar vagas em uma planilha Google Sheets e gerar um pacote de candidatura para Ricardo Guidara.

Esta versão implementa apenas o **Agente 2: Candidatura de Alta Aderência**. Ela não faz scraping de LinkedIn, não busca vagas automaticamente e não realiza candidatura automática.

## Funcionalidades

- Conecta ao Google Sheets com credenciais em `st.secrets`.
- Lê a aba `Vagas_CRM`.
- Filtra vagas com `Status = Avaliar`.
- Exibe vagas pendentes e detalhes da vaga selecionada.
- Envia descrição da vaga e perfil base para a OpenAI API.
- Gera análise estruturada em JSON.
- Gera CV, carta de apresentação, mensagem LinkedIn, respostas de formulário e checklist.
- Gera CV em PDF com ReportLab.
- Disponibiliza download direto do PDF no Streamlit.
- Atualiza a linha da vaga na planilha.
- Registra o pacote gerado na aba `Outputs`.

## Estrutura

```text
app.py
requirements.txt
.streamlit/secrets.toml.example
prompts/
  perfil_base_ricardo.md
  prompt_avaliacao.md
  prompt_cv.md
  prompt_carta.md
  prompt_formulario.md
utils/
  sheets.py
  openai_client.py
  pdf_generator.py
  scoring.py
outputs/.gitkeep
```

## Colunas recomendadas na aba `Vagas_CRM`

O app funciona com colunas extras, mas recomenda-se começar com:

```text
Empresa
Cargo
Descrição
Link
Modelo de contratação
Salário
Localidade
Status
```

Para uma vaga entrar na fila, use:

```text
Status = Avaliar
```

Ao gerar o pacote, o app cria ou atualiza estas colunas:

```text
Fit Score
Prioridade
Decisão
Versão CV
Expectativa salarial
Próxima ação
Status
```

## Rodar localmente

1. Crie e ative um ambiente virtual:

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Instale as dependências:

```bash
pip install -r requirements.txt
```

3. Copie o exemplo de secrets:

```bash
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
```

4. Preencha `.streamlit/secrets.toml` com:

```toml
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-4o-mini"
GOOGLE_SHEET_ID = "id-da-sua-planilha"

[GOOGLE_SERVICE_ACCOUNT]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
universe_domain = "googleapis.com"
```

5. Compartilhe a planilha com o `client_email` da service account.

6. Execute:

```bash
streamlit run app.py
```

## Deploy no Streamlit Community Cloud

1. Suba este projeto para um repositório GitHub.
2. Acesse o Streamlit Community Cloud.
3. Crie um app apontando para `app.py`.
4. Em **App settings > Secrets**, cole o conteúdo do seu `secrets.toml`.
5. Compartilhe a Google Sheet com o e-mail da service account.
6. Faça o deploy.

## Observações

- O CV é sempre gerado em PDF.
- O app usa respostas estruturadas em JSON para a análise da vaga.
- A geração de conteúdo depende da qualidade da descrição da vaga na planilha.
- Revise manualmente o pacote antes de enviar qualquer candidatura.
