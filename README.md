# agente-candidaturas

MVP em Python/Streamlit para encontrar oportunidades estratégicas, avaliar vagas em uma planilha Google Sheets e gerar um pacote de candidatura para Ricardo Guidara.

Esta versão implementa o **Agente 1: Radar de Vagas Estratégicas** e o **Agente 2: Candidatura de Alta Aderência**. Ela não faz scraping de LinkedIn logado, não burla termos de plataformas e não realiza candidatura automática.

## Funcionalidades

- Conecta ao Google Sheets com credenciais em `st.secrets`.
- Cria e usa abas de radar: `Radar_Config`, `Empresas_Alvo` e `Radar_Resultados`.
- Permite entrada manual assistida de vagas para `Vagas_CRM`.
- Busca vagas no Adzuna quando `ADZUNA_APP_ID` e `ADZUNA_APP_KEY` estão configurados.
- Busca vagas públicas de empresas-alvo em Greenhouse, Lever e Gupy quando a URL/slug está configurada.
- Lê a aba `Vagas_CRM`.
- Filtra vagas com `Status = Avaliar`.
- Exibe vagas pendentes e detalhes da vaga selecionada.
- Envia descrição da vaga e perfil base para a OpenAI API.
- Gera análise estruturada em JSON.
- Gera CV, carta de apresentação, mensagem LinkedIn, respostas de formulário e checklist.
- Gera CV em PDF com ReportLab.
- Bloqueia a geração do PDF se o CV contiver placeholders ou dados inválidos.
- Disponibiliza download direto do PDF no Streamlit.
- Atualiza a linha da vaga na planilha.
- Registra o pacote gerado na aba `Outputs`.

## Qualidade do output

A integração técnica está validada: o app lê a planilha, chama a OpenAI API, gera análise, pacote de candidatura e PDF.

O app não deve gerar CV com placeholders. Antes de criar o PDF, o texto do CV é validado contra padrões como `[Seu`, `[Nome`, `[Data`, `[Cidade`, `[Universidade`, `Lorem ipsum`, `Endereço`, telefone sem dado real e link de portfólio quebrado.

Se o CV contiver placeholders ou dados inválidos, o PDF é bloqueado e a vaga não é atualizada como `CV gerado`.

Os dados canônicos do perfil de Ricardo ficam em `prompts/perfil_base_ricardo.md`. Atualize esse arquivo quando houver mudanças reais de experiência, formação, idiomas, ferramentas, portfólio ou regras salariais.

## Agente 1: Radar de Vagas Estratégicas

O Radar alimenta a planilha com oportunidades para avaliação posterior pelo Agente 2.

Abas criadas ou garantidas:

```text
Radar_Config
Empresas_Alvo
Radar_Resultados
```

Fontes suportadas na v0.2:

- Inserir vaga por link, com tentativa de extração pública de HTML, metadados, OpenGraph e JSON-LD `JobPosting`.
- Entrada manual assistida, incluindo links Gupy.
- Adzuna API, opcional via secrets.
- Greenhouse público via job board API.
- Lever público via postings API.
- Gupy por link manual, página pública de empresa-alvo e API opcional quando houver token/acesso.
- Empregando Brasil e Recruit.net por busca pública HTTP/HTML.
- LinkedIn apenas por descoberta de links públicos via busca web opcional, sem leitura logada.

Limitações:

- Não faz scraping de LinkedIn logado.
- Não faz scraping logado de Gupy.
- Não usa navegador, captcha ou login.
- Não aplica automaticamente para vagas.
- Não burla termos de uso de plataformas.

Para habilitar Adzuna, adicione aos secrets:

```toml
ADZUNA_APP_ID = "seu-adzuna-app-id"
ADZUNA_APP_KEY = "sua-adzuna-app-key"
```

Se as chaves não estiverem configuradas, o app mostra o aviso: `Adzuna não configurado. Use entrada manual ou configure as chaves.`

### Configuração das abas

`Radar_Config` controla os termos automáticos de busca com as colunas `termo_busca`, `local`, `idioma`, `modelo`, `prioridade`, `ativo` e `observacao`.

`Empresas_Alvo` controla buscas por empresas específicas com as colunas `empresa`, `prioridade`, `plataforma`, `site_carreiras`, `board_token`, `observacao` e `ativo`. Para Gupy, use `plataforma = Gupy` e preencha `site_carreiras` com a página pública de carreiras. `GUPY_API_TOKEN` é opcional e só será usado quando existir nos secrets.

### Inserir vaga por link

No app, abra `Radar de Vagas Estratégicas`, cole a URL no campo `URL da vaga` e clique em `Extrair dados da vaga`.

O sistema tenta identificar a plataforma pelo domínio, incluindo LinkedIn, Gupy, Greenhouse, Lever, Workable, Indeed, site próprio ou outro. Em seguida, tenta ler apenas conteúdo público da página, sem login, navegador, cookies, captcha ou sessão do usuário.

Quando houver texto suficiente, a OpenAI estrutura os campos da vaga. Quando a página bloquear leitura ou a descrição não estiver acessível, o app retorna `precisa_descricao` e pede revisão manual. O sistema nunca inventa descrição de vaga quando o conteúdo não puder ser extraído.

Antes de enviar para `Vagas_CRM`, revise a prévia editável com empresa, cargo, plataforma, local, modelo, regime, senioridade, área principal, descrição da vaga, score preliminar, red flags e observações.

Ao enviar, a vaga entra em `Vagas_CRM` com `Status = Avaliar`.

### Links pendentes

Também é possível cadastrar previamente uma linha na aba `Vagas_CRM` com `Link` e `Status = Link pendente`.
O processamento normaliza variações simples do status, como `link pendente`, espaços extras ou `Link pender`, e corrige a célula para `Link pendente` antes de tentar extrair a vaga.

Depois, no Radar, clique em `Processar links pendentes`. O app tenta extrair os dados do link, preenche apenas campos vazios e preserva qualquer campo já preenchido manualmente. Se a extração funcionar, o status muda para `Avaliar`. Se não houver descrição suficiente, o status muda para `Precisa descrição`.

Links pendentes nunca devem ficar sem desfecho após o processamento:

- se o link já existir em outra linha, o status muda para `Duplicada` e `Observações` recebe a linha original;
- se a página bloquear leitura ou não houver descrição suficiente, o status muda para `Precisa descrição`;
- se a extração for parcial, os campos encontrados são preenchidos e `Observações` lista o que precisa ser completado;
- se a extração for bem-sucedida, o status muda para `Avaliar`.

Ao processar um link pendente, o sistema sempre atualiza a própria linha existente. Ele não insere uma nova linha para resolver pendências.

### Limitações LinkedIn/Gupy

Links LinkedIn e Gupy são aceitos para entrada manual. O app só tenta ler metadados ou conteúdo público. Ele não usa login, navegador, cookies, captcha, automação ou scraping agressivo. Se a descrição completa não estiver pública, a vaga deve ser complementada manualmente.

Para Gupy, linhas em `Vagas_CRM` com `Status = Link pendente` e link em `gupy.io`, `jobs.gupy.io` ou `gupy.com.br` são processadas pelo runner. Se a página pública trouxer empresa, cargo e descrição suficiente, o status vira `Avaliar`. Se a descrição não puder ser extraída, o status vira `Precisa descrição` e `Observações` recebe a orientação para colar a descrição manualmente.

### Radar automático com GitHub Actions

O Radar também pode rodar automaticamente fora do Streamlit pelo script:

```bash
python scripts/radar_runner.py
```

O workflow `.github/workflows/radar.yml` permite rodar manualmente em **GitHub > Actions > Radar de Vagas > Run workflow** e também executa diariamente às `11:30 UTC`.

O runner automático:

- lê `Radar_Config`;
- busca Adzuna quando `ADZUNA_APP_ID` e `ADZUNA_APP_KEY` existem;
- lê `Empresas_Alvo`;
- busca Greenhouse, Lever e Gupy públicos quando `plataforma` for `Greenhouse`, `Lever` ou `Gupy`;
- usa `GUPY_API_TOKEN` apenas se ele existir; sem token, tenta leitura pública e segue sem falhar;
- busca Empregando Brasil e Recruit.net por HTTP/HTML público;
- usa Google Programmable Search opcional para descobrir links públicos, inclusive LinkedIn/Gupy, quando `GOOGLE_SEARCH_API_KEY` e `GOOGLE_SEARCH_CX` existem;
- filtra vagas por score preliminar, com padrão `RADAR_SCORE_MIN = 65`;
- remove duplicatas por `Link` ou `Empresa + Cargo`;
- insere novas vagas em `Vagas_CRM` com `Status = Avaliar`;
- registra logs no console da Action com nome da planilha conectada, abas encontradas, total de linhas em `Vagas_CRM`, contagem por `Status` e quantidade exata de `Link pendente`;
- processa linhas `Status = Link pendente`, imprimindo a linha, o link processado e o resultado: sucesso, duplicado, precisa descrição ou erro tratado.

Secrets necessários no GitHub Actions:

```text
GOOGLE_SHEET_ID
GOOGLE_SERVICE_ACCOUNT_JSON
```

Secrets opcionais:

```text
ADZUNA_APP_ID
ADZUNA_APP_KEY
GUPY_API_TOKEN
GOOGLE_SEARCH_API_KEY
GOOGLE_SEARCH_CX
OPENAI_API_KEY
OPENAI_MODEL
```

Variáveis opcionais:

```text
RADAR_SCORE_MIN=65
RADAR_ADZUNA_COUNTRY=br
RADAR_RESULTS_PER_QUERY=20
```

O runner não usa `st.secrets`; ele lê credenciais por variáveis de ambiente. O Streamlit continua usando os mesmos helpers com fallback para `st.secrets`.

## Estrutura

```text
app.py
requirements.txt
.streamlit/secrets.toml.example
.github/workflows/radar.yml
scripts/
  radar_runner.py
prompts/
  perfil_base_ricardo.md
  prompt_avaliacao.md
  prompt_cv.md
  prompt_carta.md
  prompt_formulario.md
  prompt_radar.md
utils/
  sheets.py
  openai_client.py
  pdf_generator.py
  scoring.py
  job_radar.py
  job_link_extractor.py
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

GOOGLE_SERVICE_ACCOUNT_JSON = '''
{
  "type": "service_account",
  "project_id": "...",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n",
  "client_email": "...",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "...",
  "universe_domain": "googleapis.com"
}
'''
```

Cole o JSON inteiro baixado no Google Cloud dentro de três aspas simples (`'''`). Esse formato evita erros de TOML com quebras de linha da chave privada.

O formato antigo com `[GOOGLE_SERVICE_ACCOUNT]` continua compatível, mas o formato `GOOGLE_SERVICE_ACCOUNT_JSON` é o recomendado.

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
- O app não deve gerar CV com placeholders ou dados inventados.
- O app usa respostas estruturadas em JSON para a análise da vaga.
- A geração de conteúdo depende da qualidade da descrição da vaga na planilha.
- Revise manualmente o pacote antes de enviar qualquer candidatura.
