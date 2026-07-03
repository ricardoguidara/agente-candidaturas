Gere o campo `cv_texto_final` como texto final de currículo para Ricardo Guidara, adaptado à vaga.

O resultado deve parecer um documento final enviado a recrutadores, não uma explicação sobre o documento.

Regras rígidas de veracidade:
- Não criar campos inexistentes.
- Não gerar endereço, telefone ou e-mail se esses dados não estiverem explicitamente no perfil-base.
- Não inventar certificações.
- Não inventar formações.
- Não inventar empresas, cargos, datas ou métricas.
- Não criar placeholders.
- Não usar textos como [Seu Endereço], [Seu Telefone], [Seu E-mail], [Nome da Universidade], [Data] ou semelhantes.
- Se um dado não existir no perfil-base, omita o campo.
- Adaptar o CV à vaga, mas preservar veracidade.

Regras rígidas de limpeza:
- Não usar markdown.
- Não usar **negrito**.
- Não usar [links](url).
- Não usar separadores como ---.
- Não usar títulos com #.
- Não incluir frases meta como "Este CV foi elaborado para...".
- Não incluir "CV direcionado", "documento adaptado", observações sobre a vaga ou notas finais explicativas.
- Não incluir expectativa salarial no CV.
- Salário deve ficar apenas em `respostas_formulario` ou no campo `expectativa_salarial` da análise.
- Para LinkedIn, escrever exatamente: LinkedIn: https://www.linkedin.com/in/ricardo-guidara/
- Para portfólio, escrever exatamente: Portfolio: https://ricardoguidara.com/

Regras de idioma:
- Para vagas brasileiras, gerar CV em português.
- Para vagas internacionais ou descrição em inglês, gerar CV em inglês.
- Em inglês, usar apenas "Fluent English". Não escrever "near-native English", "native-like English" ou claims equivalentes.

Regras de adaptação por tipo de vaga:
- Evite frases genéricas ou operacionais como "campanhas impactantes", "mídias sociais como canal de marca" ou "identidade de marca" quando não estiverem conectadas a escopo estratégico real.
- Para Creative Leader / Creative Director: priorizar linguagem estratégica como "Creative direction for brand storytelling, campaigns and content platforms", "Brand expression and narrative systems", "Customer-facing creative leadership", "Multidisciplinary team direction", "Concept development and creative quality control" e "Scalable creative production". Em português, adaptar como direção criativa para storytelling de marca, campanhas e plataformas de conteúdo; sistemas narrativos e expressão de marca; liderança criativa voltada ao público; direção de equipes multidisciplinares; desenvolvimento conceitual e controle de qualidade criativa; produção criativa escalável.
- Para AI Creative Director: priorizar IA generativa, creative operations, escala, automação criativa, workflows e liderança.
- Para Gerente de Marketing/Conteúdo: priorizar estratégia, conteúdo, marca, stakeholders, canais e resultados.
- Para Coordenador/Gerente audiovisual: priorizar produção, operação, qualidade, cronograma, fornecedores e entrega.
- Para Superside / AI Creative Director: priorizar IA, Creative Operations, Generative AI workflows, brand storytelling, escala, automação criativa e liderança.

Regras de formato do currículo:
- O CV deve ser limpo, profissional, ATS-friendly e orientado a liderança, estratégia, IA, conteúdo, criação, audiovisual e operações criativas, conforme a vaga.
- Não gerar DOCX.
- Estruture com seções claras e texto final, sem tabelas complexas.
- Use bullets objetivos e específicos, aproveitando os dados canônicos do perfil-base.
- Evite texto genérico. Conecte experiências reais, clientes, ferramentas e conquistas do perfil aos requisitos da vaga.

Estrutura recomendada:
- Ricardo Guidara
- Headline alinhada à vaga
- Local, LinkedIn e Portfolio
- Resumo profissional
- Competências-chave
- Experiência profissional relevante
- Clientes e projetos selecionados, quando aderente à vaga
- Formação
- Ferramentas
- Idiomas

Perfil base:
{{PERFIL_BASE}}

Vaga:
{{DESCRICAO_VAGA}}

Análise:
{{ANALISE_JSON}}
