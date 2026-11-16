# Vendas AI

Aplicacao analitica de vendas desenvolvida em Python que combina pipeline de engenharia de dados (ETL), dashboard executivo interativo e um agente financeiro conversacional baseado em IA generativa com suporte a multiplos provedores.

## Contexto do Projeto
Projeto pratico desenvolvido no âmbito do bootcamp **Santander Bootcamp 2026** em parceria com a **Digital Innovation One (DIO)**. O projeto integra conceitos de Engenharia de Dados, Analise de Negocios e Inteligencia Artificial Aplicada, construindo uma solucao orientada a resolver problemas reais de ingestao de dados desestruturados e extracao automatizada de insights comerciais.

## Visao Geral
Em cenarios comerciais cotidianos, dados de vendas costumam ser dispersos em planilhas com inconsistencias de formato monetario, tipos de data, valores ausentes e codificacoes conflitantes. Esta aplicacao resolve esse problema em tres camadas:
1. **Pipeline de ETL:** Higieniza, valida e padroniza arquivos CSV e Excel automaticamente.
2. **Dashboard Interativo:** Centraliza indicadores de desempenho (KPIs), distribuicao geografica, sazonalidade e rankings.
3. **Agente de IA (Fin):** Agente conversacional que consulta o conjunto de dados sob demanda via function calling, garantindo que as respostas sejam embasadas estritamente nos dados reais, sem alucinacoes.

## Demonstração Online

A aplicação interativa está publicada e acessível no Streamlit Community Cloud:
- Link da aplicação: [vendas-ai-bjr7gzhrrkdjsbd6ve6qth.streamlit.app](https://vendas-ai-bjr7gzhrrkdjsbd6ve6qth.streamlit.app/)

## Funcionalidades
- **Ingestao e Higienizacao de Dados:**
  - Leitura tolerante a falhas para arquivos `.csv` e `.xlsx`.
  - Deteccao automatica de codificacao (UTF-8, Latin-1, CP1252) e separadores (`,`, `;`, `\t`, `|`).
  - Tratamento de padroes monetarios brasileiros (`R$ 1.234,56`) e americanos (`1234.56`).
  - Deduplicacao, deteccao de outliers e geracao de relatorio de qualidade dos dados.
- **Dashboard Executivo:**
  - Metricas principais: Receita Total, Pedidos, Itens Vendidos, Ticket Medio e Desconto Medio.
  - Graficos interativos Plotly: Evolucao temporal com media movel, distribuicao por categoria, regiao, dia da semana e ranking de produtos.
- **Agente Financeiro Inteligente (Fin):**
  - Consultas deterministas via chamadas de funcoes seguras (Function Calling).
  - Capacidades analiticas: Consulta sob demanda, analise executiva automatica, comparacao entre periodos, curvas ABC de clientes e calculo de tendencias.
  - Suporte a streaming em tempo real das respostas.
  - Opcao de anonimizacao de dados de clientes para preservacao de privacidade.
  - Exportacao do historico de conversas em Markdown.
- **Interoperabilidade de IA:**
  - Suporte a multiplos provedores de ponta: Anthropic (Claude), OpenAI (GPT), Groq (Llama), Google Gemini e endpoints compativeis com OpenAI (como Ollama ou LM Studio locais).
  - Gerenciamento seguro de credenciais via backend (`.streamlit/secrets.toml` ou `.env`), sem exposicao de chaves na interface.

## Tecnologias Utilizadas
| Camada | Tecnologia | Finalidade |
|---|---|---|
| Linguagem | Python 3.12+ | Linguagem base da aplicacao |
| Frontend / Interface | Streamlit | Interface web unificada e interativa |
| Manipulacao de Dados | Pandas, NumPy | Pipeline de ETL, transformacoes e agregacoes |
| Ingestao de Planilhas | OpenPyXL | Leitura e conversao de planilhas Excel (.xlsx) |
| Visualizacao de Dados | Plotly | Graficos analiticos interativos |
| Integracao com LLMs | OpenAI SDK, Anthropic SDK | Protocolo unificado e SDK nativo para comunicacao com APIs de IA |
| Agente Conversacional | Function Calling | Agregacoes seguras sem execucao de codigo arbitrario |

## Instalacao e Execucao

### No Linux (Ubuntu / Linux Mint / Debian):
```bash
git clone https://github.com/Rafael-Boaro/vendas-ai.git
cd vendas-ai

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Preencha a chave do provedor escolhido no secrets.toml (ou copie .env.example para .env)

streamlit run app.py
```

### No Windows (PowerShell):
```powershell
git clone https://github.com/Rafael-Boaro/vendas-ai.git
cd vendas-ai

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
# Preencha a chave do provedor escolhido no secrets.toml (ou copie .env.example para .env)

streamlit run app.py
```

## Configuracao
As credenciais e modelos podem ser definidos em `.streamlit/secrets.toml` (recomendado para Streamlit Cloud e local) ou em variáveis de ambiente / `.env`:
- `GROQ_API_KEY`: Chave de API para o provedor Groq.
- `ANTHROPIC_API_KEY`: Chave de API para Anthropic Claude.
- `OPENAI_API_KEY`: Chave de API para OpenAI GPT.
- `GEMINI_API_KEY`: Chave de API para Google Gemini.
- `LLM_PROVIDER`: Provedor padrao a ser utilizado (`groq`, `openai`, `anthropic`, `gemini` ou `compativel`).

A interface gráfica permite selecionar entre os provedores que tiverem credenciais válidas configuradas no backend, sem expor as chaves de acesso.

## Decisoes de Arquitetura e Engenharia
- **Sem execucao de codigo arbitrario:** O agente de IA nao executa interpretador Python ou queries SQL dinamicas geradas pelo modelo. As ferramentas expostas ao modelo sao metodos restritos com validacao estrita de parametros, garantindo seguranca contra injecoes.
- **Protocolo OpenAI-compativel:** Utilizar a especificacao do OpenAI SDK permitiu conectar modelos comerciais em nuvem e modelos open-source locais (via Ollama e LM Studio) com a mesma base de codigo.
- **Normalizacao de dados na ingestao:** O processo de limpeza unifica siglas e grafias de estados, converte percentuais e recalcula colunas faltantes (ex.: derivar valor total atraves de quantidade, preco unitario e desconto).

## Autor
Desenvolvido por **Rafael Paolielo Boaro**  
GitHub: [Rafael-Boaro](https://github.com/Rafael-Boaro)  
Estudante de Analise e Desenvolvimento de Sistemas - FATEC Mococa  
Participante do Santander Bootcamp / Digital Innovation One (DIO)

## Licenca
Distribuido sob a licenca MIT. Consulte o arquivo [LICENSE](LICENSE) para mais informacoes.
