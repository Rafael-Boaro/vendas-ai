# Vendas AI

Aplicacao para analise de vendas com ETL automatizado, dashboard analitico e agente conversacional integrado para consultas e insights comerciais.

## Visao geral
Projeto pratico desenvolvido no contexto da formacao da DIO em parceria com o Santander. O objetivo e fornecer uma ferramenta completa em Python para higienizacao de bases comerciais (ETL tolerante a falhas), acompanhamento visual de indicadores de vendas e um agente de inteligencia artificial capaz de dialogar com os dados e fornecer analises em linguagem natural.

## Funcionalidades
- Higienizacao e padronizacao de dados (CSV e Excel) com deteccao automatica de formato, delimitador e codificacao.
- Dashboard comercial interativo com KPIs de receita, pedidos, itens, ticket medio e taxas de desconto.
- Agente financeiro conversacional (Fin) com function calling para agregacoes sob demanda, analise de tendencias, curvas ABC e comparacao de periodos.
- Suporte a multiplos provedores de LLM compativeis com a API OpenAI (Groq, OpenAI, Google Gemini, Anthropic, Mistral, DeepSeek, Together AI, Ollama e LM Studio).
- Configuracao flexivel de modelos e chaves tanto pela interface web quanto por arquivo de ambiente.
- Anonimizacao de clientes e modos de privacidade para controle de compartilhamento de dados com a LLM.
- Suporte a streaming de respostas e exportacao de dialogos em formato Markdown.

## Tecnologias
| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.12+ |
| Interface de Usuario | Streamlit |
| Processamento e ETL | Pandas, NumPy, OpenPyXL |
| Visualizacao Grafica | Plotly |
| Integracao com LLMs | OpenAI SDK (protocolo OpenAI-compativel) |
| Arquitetura do Agente | Function Calling com agregacoes deterministas no DataFrame |

## Instalacao e Execucao

### No Linux (Ubuntu / Linux Mint / Debian):
```bash
git clone https://github.com/Rafael-Boaro/vendas-ai.git
cd vendas-ai

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Configure sua chave e provedor no arquivo .env ou configure diretamente na barra lateral

streamlit run app.py
```

### No Windows (PowerShell):
```powershell
git clone https://github.com/Rafael-Boaro/vendas-ai.git
cd vendas-ai

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
# Configure sua chave e provedor no arquivo .env ou configure diretamente na barra lateral

streamlit run app.py
```

## Configuracao
Copie `.env.example` para `.env` e defina as variaveis necessarias:
- `LLM_PROVIDER`: Provedor desejado (`groq`, `openai`, `gemini`, `anthropic`, `ollama`, etc.).
- `LLM_MODEL`: Identificador do modelo no provedor escolhido.
- `LLM_API_KEY`: Chave de autenticacao da API.
- Os parametros tambem podem ser definidos ou sobrescritos dinamicamente pelo menu lateral da aplicacao.

## Decisoes tecnicas
- **Protocolo universal:** O uso do SDK oficial com base URLs compativeis unifica a integracao com mais de 10 provedores de IA sem introduzir multiplas bibliotecas proprietarias.
- **Seguranca de dados com function calling:** O agente nao executa codigo em tempo de execucao (`eval`/`exec`). As consultas sao mediadas por funcoes de agregacao predefinidas no Pandas, prevenindo ataques de injecao e garantindo consistencia numerica.
- **Higienizacao resiliente:** O modulo de extracao identifica variacoes entre padroes numericos (virgula e ponto decimal), formatos de data e codificacoes legadas (CP1252, Latin-1, UTF-8).
