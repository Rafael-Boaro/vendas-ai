"""Agente financeiro conversacional — independente de provedor de IA.

- O provedor, o modelo e a chave vêm do .env ou da UI (veja `llm_config.py`).
- A personalidade e as regras do agente vêm do arquivo `agents.md`.
- Fala o protocolo OpenAI-compatível (`/chat/completions` + function calling) com o
  SDK `openai`, que funciona com Groq, OpenAI, OpenRouter, Gemini, Anthropic,
  Mistral, DeepSeek, Together, Ollama, LM Studio e qualquer endpoint compatível.
- Ferramentas disponíveis (consultam o DataFrame com segurança):
    • consultar_vendas    — agrega por dimensão
    • resumo_geral        — KPIs de um período
    • comparar_periodos   — variação entre dois períodos
    • tendencia_produto   — ranking de crescimento por produto/categoria
    • clientes_abc        — curva ABC de clientes por receita
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Generator

import pandas as pd
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from analytics import DIMENSOES, FUNCOES, METRICAS, agregar, brl, contexto_para_llm, kpis
from llm_config import ConfigLLM

MAX_PASSOS_FERRAMENTAS = 8      # idas e voltas modelo <-> ferramentas por pergunta
MAX_TURNOS_HISTORICO = 16       # perguntas lembradas (controla o gasto de tokens)
MAX_CHARS_RESULTADO = 10_000    # tamanho máximo de uma resposta de ferramenta
TENTATIVAS_POR_MODELO = 3


class AgenteErro(RuntimeError):
    """Erro apresentável ao usuário (chave inválida, limite, etc.)."""


# --------------------------------------------------------------------------
# Ferramentas (schema JSON enviado ao modelo)
# --------------------------------------------------------------------------
_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_vendas",
            "description": (
                "Agrega as vendas por uma dimensão e devolve uma tabela CSV com a coluna do "
                "grupo e a coluna 'resultado'. Use para qualquer número que não esteja no resumo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agrupar_por": {
                        "type": "string", "enum": list(DIMENSOES),
                        "description": "Dimensão do agrupamento.",
                    },
                    "metrica": {
                        "type": "string", "enum": list(METRICAS),
                        "description": ("valor_total (receita, padrão), quantidade, pedidos "
                                        "(nº de pedidos distintos), desconto (fração: 0.10 = 10%) "
                                        "ou preco_unitario."),
                    },
                    "funcao": {
                        "type": "string", "enum": list(FUNCOES),
                        "description": "sum (padrão), mean, count, max, min ou median. "
                                       "Ignorada quando metrica='pedidos'.",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": ("Máximo de linhas (1 a 100, padrão 10). Em ano_mes/ano/mes "
                                        "devolve os N períodos mais recentes em ordem cronológica."),
                    },
                    "data_inicio": {"type": "string", "description": "AAAA-MM-DD (opcional)."},
                    "data_fim": {"type": "string", "description": "AAAA-MM-DD (opcional)."},
                    "filtro_coluna": {
                        "type": "string", "enum": list(DIMENSOES),
                        "description": "Dimensão usada para filtrar (opcional; omita se não usar).",
                    },
                    "filtro_valor": {
                        "type": "string",
                        "description": "Texto que o valor da dimensão deve conter "
                                       "(ignora acentos e maiúsculas).",
                    },
                },
                "required": ["agrupar_por"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resumo_geral",
            "description": ("KPIs de vendas (receita, pedidos, itens, ticket médio, desconto médio, "
                            "clientes) no período informado ou em todo o histórico."),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_inicio": {"type": "string", "description": "AAAA-MM-DD (opcional)."},
                    "data_fim": {"type": "string", "description": "AAAA-MM-DD (opcional)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comparar_periodos",
            "description": (
                "Compara os KPIs de dois períodos e devolve a variação absoluta e percentual "
                "de receita, pedidos, ticket médio, itens e desconto. Use quando o usuário "
                "pedir comparação entre meses, trimestres, anos ou qualquer dois intervalos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "inicio_a": {"type": "string", "description": "Início do período A (AAAA-MM-DD)."},
                    "fim_a": {"type": "string", "description": "Fim do período A (AAAA-MM-DD)."},
                    "inicio_b": {"type": "string", "description": "Início do período B (AAAA-MM-DD)."},
                    "fim_b": {"type": "string", "description": "Fim do período B (AAAA-MM-DD)."},
                    "rotulo_a": {"type": "string", "description": "Nome do período A (ex.: 'jan/2025'). Opcional."},
                    "rotulo_b": {"type": "string", "description": "Nome do período B (ex.: 'jan/2026'). Opcional."},
                },
                "required": ["inicio_a", "fim_a", "inicio_b", "fim_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tendencia_produto",
            "description": (
                "Calcula a variação de receita de cada produto (ou categoria) entre dois "
                "sub-períodos consecutivos do histórico disponível, mostrando quem mais cresceu "
                "e quem mais caiu. Use quando o usuário perguntar sobre tendências, crescimento "
                "ou queda por produto/categoria."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dimensao": {
                        "type": "string",
                        "enum": ["produto", "categoria", "vendedor", "regiao"],
                        "description": "Dimensão a analisar (padrão: produto).",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Quantos itens retornar (padrão 10, máx 50).",
                    },
                    "data_inicio": {"type": "string", "description": "AAAA-MM-DD (opcional). Define o início do histórico a considerar."},
                    "data_fim": {"type": "string", "description": "AAAA-MM-DD (opcional). Define o fim do histórico a considerar."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clientes_abc",
            "description": (
                "Classifica os clientes na curva ABC por receita: classe A (~80% da receita "
                "acumulada), B (~80-95%) e C (cauda). Devolve a tabela com cliente, receita, "
                "participação, acumulado e classe. Use quando o usuário pedir análise de clientes, "
                "concentração de receita em clientes ou curva ABC de clientes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "top_n": {
                        "type": "integer",
                        "description": "Quantos clientes retornar (padrão 20, máx 100).",
                    },
                    "data_inicio": {"type": "string", "description": "AAAA-MM-DD (opcional)."},
                    "data_fim": {"type": "string", "description": "AAAA-MM-DD (opcional)."},
                },
                "required": [],
            },
        },
    },
]


# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------
def carregar_instrucoes(caminho: Path) -> str:
    """Lê o agents.md (personalidade e regras do agente)."""
    if not caminho.is_file():
        raise AgenteErro(
            f"Arquivo de instruções do agente não encontrado: '{caminho.name}'. "
            "Mantenha o agents.md na pasta do app (ou aponte AGENTS_FILE no .env)."
        )
    texto = caminho.read_text(encoding="utf-8").strip()
    if not texto:
        raise AgenteErro(f"O arquivo '{caminho.name}' está vazio.")
    return texto


def _limpar_resposta(texto: str | None) -> str:
    """Remove blocos <think>…</think> que alguns modelos de raciocínio devolvem."""
    return re.sub(r"<think>.*?</think>", "", texto or "", flags=re.DOTALL | re.IGNORECASE).strip()


def _erro_de_modelo(texto: str) -> bool:
    texto = texto.lower()
    return any(t in texto for t in ("model_not_found", "does not exist", "decommissioned",
                                    "model_permission", "not supported", "unknown model",
                                    "invalid model", "no longer supported", "not found"))


def _filtrar_periodo(df: pd.DataFrame, inicio: str, fim: str) -> pd.DataFrame:
    """Aplica filtros de data ao DataFrame."""
    base = df
    if inicio:
        base = base[base["data"] >= pd.to_datetime(inicio)]
    if fim:
        base = base[base["data"] <= pd.to_datetime(fim)]
    return base


# --------------------------------------------------------------------------
# Agente
# --------------------------------------------------------------------------
class AgenteFinanceiro:
    def __init__(self, df: pd.DataFrame, config: ConfigLLM, incluir_amostra: bool = True):
        self.df = df
        self.config = config
        self.client = OpenAI(base_url=config.base_url, api_key=config.api_key,
                             timeout=config.timeout, max_retries=2)
        base = carregar_instrucoes(config.arquivo_instrucoes)
        contexto = contexto_para_llm(df, amostra=8 if incluir_amostra else 0)
        self._instrucoes = f"{base}\n\n=== RESUMO DOS DADOS CARREGADOS ===\n{contexto}"
        self._funcoes = self._criar_funcoes()
        self.historico: list[dict] = []
        self._indisponiveis: set[str] = set()   # modelos que o provedor recusou (404 etc.)
        self._sem_temperatura: set[str] = set()  # modelos que não aceitam `temperature`

    @property
    def descricao(self) -> str:
        return self.config.descricao

    # ------------------------------------------------------------ ferramentas
    def _criar_funcoes(self) -> dict:
        df = self.df

        def consultar_vendas(agrupar_por: str, metrica: str = "valor_total", funcao: str = "sum",
                             top_n: int = 10, data_inicio: str = "", data_fim: str = "",
                             filtro_coluna: str = "", filtro_valor: str = "") -> str:
            try:
                return agregar(df, agrupar_por, metrica, funcao, top_n, data_inicio,
                               data_fim, filtro_coluna, filtro_valor).to_csv(index=False)
            except ValueError as e:
                return f"ERRO: {e}"

        def resumo_geral(data_inicio: str = "", data_fim: str = "") -> str:
            try:
                base = _filtrar_periodo(df, data_inicio, data_fim)
            except ValueError as e:
                return f"ERRO: {e}"
            if base.empty:
                return "ERRO: nenhum dado nesse período."
            k = kpis(base)
            return (
                f"receita={brl(k['receita'])}; pedidos={k['pedidos']}; itens={k['itens']}; "
                f"ticket_medio={brl(k['ticket_medio'])}; desconto_medio={k['desconto_medio_pct']:.1f}%; "
                f"clientes={k['clientes']}"
            )

        def comparar_periodos(inicio_a: str, fim_a: str, inicio_b: str, fim_b: str,
                               rotulo_a: str = "", rotulo_b: str = "") -> str:
            try:
                a = _filtrar_periodo(df, inicio_a, fim_a)
                b = _filtrar_periodo(df, inicio_b, fim_b)
            except ValueError as e:
                return f"ERRO: {e}"
            if a.empty:
                return f"ERRO: nenhum dado para o período {rotulo_a or inicio_a + ' a ' + fim_a}."
            if b.empty:
                return f"ERRO: nenhum dado para o período {rotulo_b or inicio_b + ' a ' + fim_b}."
            ka, kb = kpis(a), kpis(b)
            la = rotulo_a or f"{inicio_a} a {fim_a}"
            lb = rotulo_b or f"{inicio_b} a {fim_b}"

            def var(va: float, vb: float) -> str:
                diff = vb - va
                pct = (diff / va * 100) if va else float("inf")
                sinal = "+" if diff >= 0 else ""
                return f"{sinal}{diff:,.2f} ({sinal}{pct:.1f}%)"

            linhas = [
                f"Comparação: [{la}] vs [{lb}]",
                f"receita: {brl(ka['receita'])} → {brl(kb['receita'])} | variação: {var(ka['receita'], kb['receita'])}",
                f"pedidos: {ka['pedidos']} → {kb['pedidos']} | variação: {var(ka['pedidos'], kb['pedidos'])}",
                f"ticket_medio: {brl(ka['ticket_medio'])} → {brl(kb['ticket_medio'])} | variação: {var(ka['ticket_medio'], kb['ticket_medio'])}",
                f"itens: {ka['itens']} → {kb['itens']} | variação: {var(ka['itens'], kb['itens'])}",
                f"desconto_medio_pct: {ka['desconto_medio_pct']:.1f}% → {kb['desconto_medio_pct']:.1f}%",
                f"clientes: {ka['clientes']} → {kb['clientes']}",
            ]
            return "\n".join(linhas)

        def tendencia_produto(dimensao: str = "produto", top_n: int = 10,
                              data_inicio: str = "", data_fim: str = "") -> str:
            try:
                base = _filtrar_periodo(df, data_inicio, data_fim)
            except ValueError as e:
                return f"ERRO: {e}"
            if base.empty:
                return "ERRO: nenhum dado nesse período."
            if dimensao not in ("produto", "categoria", "vendedor", "regiao"):
                return f"ERRO: dimensão inválida '{dimensao}'. Use: produto, categoria, vendedor, regiao."

            top_n = max(1, min(int(top_n), 50))
            datas = base["data"].sort_values()
            meio = datas.iloc[len(datas) // 2]
            a = base[base["data"] < meio]
            b = base[base["data"] >= meio]
            if a.empty or b.empty:
                return "ERRO: dados insuficientes para calcular tendência."

            ra = a.groupby(dimensao)["valor_total"].sum().rename("periodo_a")
            rb = b.groupby(dimensao)["valor_total"].sum().rename("periodo_b")
            merged = pd.concat([ra, rb], axis=1).fillna(0)
            merged["variacao_abs"] = merged["periodo_b"] - merged["periodo_a"]
            merged["variacao_pct"] = (
                (merged["variacao_abs"] / merged["periodo_a"].replace(0, float("nan"))) * 100
            ).round(1)
            merged = merged.sort_values("variacao_abs", ascending=False)
            crescendo = merged.head(top_n).reset_index()
            caindo = merged.tail(top_n).sort_values("variacao_abs").reset_index()
            resultado = [
                f"Período A: {a['data'].min().date()} a {a['data'].max().date()}",
                f"Período B: {b['data'].min().date()} a {b['data'].max().date()}",
                "",
                f"TOP {top_n} QUE MAIS CRESCERAM:",
                crescendo.to_csv(index=False),
                f"TOP {top_n} QUE MAIS CAÍRAM:",
                caindo.to_csv(index=False),
            ]
            return "\n".join(resultado)

        def clientes_abc(top_n: int = 20, data_inicio: str = "", data_fim: str = "") -> str:
            try:
                base = _filtrar_periodo(df, data_inicio, data_fim)
            except ValueError as e:
                return f"ERRO: {e}"
            if base.empty:
                return "ERRO: nenhum dado nesse período."
            top_n = max(1, min(int(top_n), 100))

            from data_processing import NAO_INFORMADO
            clientes_df = (
                base[base["cliente"] != NAO_INFORMADO]
                .groupby("cliente")["valor_total"]
                .sum()
                .sort_values(ascending=False)
                .head(top_n)
                .reset_index()
            )
            if clientes_df.empty:
                return "ERRO: sem dados de clientes identificados."

            total = clientes_df["valor_total"].sum()
            clientes_df["participacao_pct"] = (clientes_df["valor_total"] / total * 100).round(2)
            clientes_df["acumulado_pct"] = clientes_df["participacao_pct"].cumsum().round(2)
            clientes_df["classe"] = clientes_df["acumulado_pct"].apply(
                lambda x: "A" if x <= 80 else ("B" if x <= 95 else "C")
            )
            clientes_df["valor_total"] = clientes_df["valor_total"].round(2)
            resumo = (
                f"Total de clientes: {clientes_df.shape[0]} | "
                f"Classe A: {(clientes_df['classe']=='A').sum()} | "
                f"Classe B: {(clientes_df['classe']=='B').sum()} | "
                f"Classe C: {(clientes_df['classe']=='C').sum()}"
            )
            return resumo + "\n\n" + clientes_df.to_csv(index=False)

        return {
            "consultar_vendas": consultar_vendas,
            "resumo_geral": resumo_geral,
            "comparar_periodos": comparar_periodos,
            "tendencia_produto": tendencia_produto,
            "clientes_abc": clientes_abc,
        }

    def _executar_ferramenta(self, nome: str, argumentos: str | None) -> str:
        funcao = self._funcoes.get(nome)
        if funcao is None:
            return f"ERRO: ferramenta desconhecida '{nome}'."
        try:
            args = json.loads(argumentos or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            return "ERRO: os argumentos da ferramenta não são um JSON válido."
        permitidos = inspect.signature(funcao).parameters
        args = {k: v for k, v in args.items() if k in permitidos and v not in (None, "")}
        try:
            resultado = funcao(**args)
        except TypeError as e:
            return f"ERRO: argumentos inválidos ({e})."
        except Exception as e:  # nunca derruba a conversa por falha de uma consulta
            return f"ERRO: falha ao consultar os dados ({type(e).__name__})."
        if len(resultado) > MAX_CHARS_RESULTADO:
            resultado = resultado[:MAX_CHARS_RESULTADO] + "\n[... resultado truncado ...]"
        return resultado

    # --------------------------------------------------------------- chamadas
    def _traduzir_erro(self, e: Exception) -> str:
        nome = self.config.nome
        msg = str(getattr(e, "message", None) or e)
        baixo = msg.lower()
        if isinstance(e, AuthenticationError):
            return (f"O provedor {nome} recusou a chave de API. Confira a chave no arquivo .env "
                    "ou na barra lateral e reinicie o app.")
        if isinstance(e, RateLimitError):
            return (f"Limite de uso do provedor {nome} atingido (requisições ou tokens por "
                    "minuto/dia). Aguarde cerca de 1 minuto e tente novamente.")
        if isinstance(e, APIStatusError) and e.status_code == 413:
            return ("A requisição ficou grande demais para o limite do provedor. Desative "
                    "'Enviar amostra de linhas' na barra lateral ou use um modelo com mais contexto.")
        if "tool_use_failed" in baixo or "failed to call a function" in baixo:
            return ("O modelo não conseguiu usar as ferramentas desta vez. Tente reformular a "
                    "pergunta ou defina um modelo maior.")
        if isinstance(e, APIStatusError) and e.status_code >= 500:
            return f"O provedor {nome} está instável no momento. Tente novamente em instantes."
        status = getattr(e, "status_code", "?")
        return f"Erro do provedor {nome} ({status}): {msg[:300]}"

    def _chamar(self, stream: bool = False):
        """Chama o provedor, com retentativas e fallback automático entre modelos."""
        mensagens = [{"role": "system", "content": self._instrucoes}] + self.historico
        candidatos = [m for m in self.config.modelos if m not in self._indisponiveis]
        if not candidatos:  # todos foram recusados: tenta de novo do começo
            self._indisponiveis.clear()
            candidatos = list(self.config.modelos)

        ultimo_erro: Exception | None = None
        for modelo in candidatos:
            for _ in range(TENTATIVAS_POR_MODELO):
                params = dict(model=modelo, messages=mensagens, tools=_SCHEMAS,
                              tool_choice="auto", stream=stream)
                if modelo not in self._sem_temperatura:
                    params["temperature"] = self.config.temperatura
                try:
                    return self.client.chat.completions.create(**params)
                except AuthenticationError as e:
                    raise AgenteErro(self._traduzir_erro(e)) from e
                except APIConnectionError as e:
                    raise AgenteErro(
                        f"Não consegui conectar ao provedor {self.config.nome} "
                        f"({self.config.base_url}). Verifique a internet e o LLM_BASE_URL."
                    ) from e
                except NotFoundError as e:
                    self._indisponiveis.add(modelo)
                    ultimo_erro = e
                    break
                except RateLimitError as e:
                    ultimo_erro = e
                    break
                except (BadRequestError, PermissionDeniedError) as e:
                    texto = str(e).lower()
                    if "temperature" in texto and modelo not in self._sem_temperatura:
                        self._sem_temperatura.add(modelo)
                        continue
                    if "tool_use_failed" in texto or "failed to call a function" in texto:
                        ultimo_erro = e
                        continue
                    if _erro_de_modelo(texto):
                        self._indisponiveis.add(modelo)
                        ultimo_erro = e
                        break
                    raise AgenteErro(self._traduzir_erro(e)) from e
                except APIStatusError as e:
                    if e.status_code == 413 or e.status_code >= 500:
                        ultimo_erro = e
                        break
                    raise AgenteErro(self._traduzir_erro(e)) from e

        if ultimo_erro is not None:
            raise AgenteErro(self._traduzir_erro(ultimo_erro)) from ultimo_erro
        raise AgenteErro(
            "Nenhum dos modelos configurados está disponível. Defina LLM_MODEL no .env "
            f"com um modelo válido do provedor {self.config.nome}."
        )

    def _ciclo(self) -> str:
        """Loop não-streaming: executa ferramentas e retorna a resposta final."""
        for _ in range(MAX_PASSOS_FERRAMENTAS):
            resp = self._chamar(stream=False)
            if not resp.choices:
                raise AgenteErro("O provedor devolveu uma resposta vazia. Tente novamente.")
            msg = resp.choices[0].message
            chamadas = msg.tool_calls or []
            texto = _limpar_resposta(msg.content)

            entrada: dict = {"role": "assistant", "content": texto or (None if chamadas else "")}
            if chamadas:
                for i, c in enumerate(chamadas):
                    if not c.id:
                        c.id = f"call_{len(self.historico)}_{i}"
                entrada["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
                    for c in chamadas
                ]
            self.historico.append(entrada)

            if not chamadas:
                return texto or "Não consegui gerar uma resposta. Tente reformular a pergunta."
            for c in chamadas:
                self.historico.append({
                    "role": "tool", "tool_call_id": c.id,
                    "content": self._executar_ferramenta(c.function.name, c.function.arguments),
                })
        raise AgenteErro("O agente fez consultas demais sem concluir. Tente uma pergunta mais objetiva.")

    def _ciclo_stream(self) -> Generator[str, None, None]:
        """Loop com streaming: executa ferramentas internamente, faz yield dos chunks de texto."""
        for _ in range(MAX_PASSOS_FERRAMENTAS):
            stream = self._chamar(stream=True)

            # Acumula o stream para detectar tool_calls
            texto_acc = ""
            tool_calls_acc: dict[int, dict] = {}  # índice -> dados parciais

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # Texto normal → emitir ao vivo
                if delta.content:
                    texto_acc += delta.content
                    yield delta.content

                # Tool calls chegam fragmentados
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.id or "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["function"]["arguments"] += tc.function.arguments

            chamadas = list(tool_calls_acc.values())
            texto = _limpar_resposta(texto_acc)

            # Adiciona turno do assistente ao histórico
            entrada: dict = {"role": "assistant", "content": texto or (None if chamadas else "")}
            if chamadas:
                for i, c in enumerate(chamadas):
                    if not c["id"]:
                        c["id"] = f"call_{len(self.historico)}_{i}"
                entrada["tool_calls"] = chamadas
            self.historico.append(entrada)

            if not chamadas:
                return  # fim do fluxo — texto já foi emitido via yield

            # Executa ferramentas (sem yield — são internas)
            for c in chamadas:
                self.historico.append({
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "content": self._executar_ferramenta(
                        c["function"]["name"], c["function"]["arguments"]
                    ),
                })
        raise AgenteErro("O agente fez consultas demais sem concluir. Tente uma pergunta mais objetiva.")

    def _podar_historico(self) -> None:
        """Mantém só as últimas perguntas (sem separar chamada de ferramenta e resposta)."""
        inicios = [i for i, m in enumerate(self.historico) if m["role"] == "user"]
        if len(inicios) > MAX_TURNOS_HISTORICO:
            del self.historico[:inicios[-MAX_TURNOS_HISTORICO]]

    # ------------------------------------------------------------- interface
    def reiniciar(self) -> None:
        self.historico.clear()

    def perguntar(self, texto: str) -> str:
        """Envia uma pergunta e retorna a resposta completa (sem streaming)."""
        texto = (texto or "").strip()
        if not texto:
            raise AgenteErro("Digite uma pergunta.")
        ponto_seguro = len(self.historico)
        self.historico.append({"role": "user", "content": texto})
        try:
            resposta = self._ciclo()
        except BaseException:
            del self.historico[ponto_seguro:]
            raise
        self._podar_historico()
        return resposta

    def perguntar_stream(self, texto: str) -> Generator[str, None, None]:
        """Envia uma pergunta e faz yield dos chunks de texto conforme chegam."""
        texto = (texto or "").strip()
        if not texto:
            raise AgenteErro("Digite uma pergunta.")
        ponto_seguro = len(self.historico)
        self.historico.append({"role": "user", "content": texto})
        try:
            yield from self._ciclo_stream()
        except BaseException:
            del self.historico[ponto_seguro:]
            raise
        self._podar_historico()

    def analise_executiva(self) -> str:
        return self.perguntar(
            "Faça uma análise executiva dos dados de vendas: (1) visão geral do desempenho, "
            "(2) tendências e sazonalidade, (3) concentração por produto/categoria/região, "
            "(4) 3 riscos ou alertas e (5) 3 ações recomendadas. Use as ferramentas para confirmar números."
        )

    def analise_executiva_stream(self) -> Generator[str, None, None]:
        yield from self.perguntar_stream(
            "Faça uma análise executiva dos dados de vendas: (1) visão geral do desempenho, "
            "(2) tendências e sazonalidade, (3) concentração por produto/categoria/região, "
            "(4) 3 riscos ou alertas e (5) 3 ações recomendadas. Use as ferramentas para confirmar números."
        )

    def exportar_historico(self) -> str:
        """Exporta o histórico da conversa em Markdown."""
        linhas = [f"# Histórico da conversa — {self.config.descricao}\n"]
        for msg in self.historico:
            role = msg.get("role", "")
            if role == "user":
                linhas.append(f"## 👤 Usuário\n{msg.get('content', '')}\n")
            elif role == "assistant":
                conteudo = msg.get("content") or ""
                tool_calls = msg.get("tool_calls", [])
                if conteudo:
                    linhas.append(f"## 🤖 Assistente\n{conteudo}\n")
                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        linhas.append(
                            f"*[Consultou ferramenta: `{fn.get('name', '?')}`]*\n"
                        )
            # Ignora mensagens role=tool (resultados brutos de ferramentas)
        return "\n".join(linhas)
