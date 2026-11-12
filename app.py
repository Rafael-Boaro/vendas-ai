from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import charts
from analytics import brl, contexto_para_llm, evolucao_mensal, kpis, tem_dimensao
from data_processing import anonimizar_clientes, carregar_arquivos
from llm_agent import AgenteErro, AgenteFinanceiro
from llm_config import PROVEDORES, carregar_config, ConfigErro

load_dotenv()
st.set_page_config(page_title="Vendas + IA", layout="wide")

# Arquivo de exemplo — usa o primeiro CSV disponivel na pasta data/
_DATA_DIR = Path(__file__).parent / "data"
_EXEMPLOS = sorted(_DATA_DIR.glob("*.csv")) if _DATA_DIR.exists() else []
EXEMPLO = _EXEMPLOS[0] if _EXEMPLOS else None

PERGUNTAS_RAPIDAS = {
    "Melhores produtos": "Quais sao meus 5 melhores produtos e quanto cada um representa da receita?",
    "Mes mais fraco": "Qual foi o mes mais fraco e o que pode explicar isso?",
    "Ticket medio": "Explique o que e ticket medio e como o meu esta evoluindo.",
    "Curva ABC": "Explique a curva ABC e classifique meus produtos nela.",
    "Tendencias": "Quais produtos ou categorias estao crescendo e quais estao caindo?",
    "Clientes ABC": "Faca uma analise ABC dos meus clientes por receita.",
    "Comparar periodos": "Compare o ultimo mes com o mes anterior em receita, pedidos e ticket medio.",
}


# --------------------------------------------------------------- helpers de UI
def _plot(fig, key: str | None = None) -> None:
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key=key)


def _tabela(df: pd.DataFrame, **kw) -> None:
    try:
        st.dataframe(df, width="stretch", **kw)
    except TypeError:
        st.dataframe(df, use_container_width=True, **kw)


@st.cache_data(show_spinner="Higienizando e padronizando os dados...")
def _processar(fontes: tuple[tuple[str, bytes], ...]):
    return carregar_arquivos(list(fontes))


# --------------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("Vendas + IA")

    # ---- Secao 1: Dados ----
    st.subheader("1. Dados")
    uploads = st.file_uploader(
        "Planilhas CSV ou Excel (.csv, .xlsx)",
        type=["csv", "xlsx"],
        accept_multiple_files=True,
    )

    fontes: tuple[tuple[str, bytes], ...]
    if uploads:
        fontes_lista = []
        for u in uploads:
            conteudo = u.getvalue()
            if u.name.lower().endswith(".xlsx"):
                import io
                xls = pd.read_excel(io.BytesIO(conteudo), dtype=str)
                conteudo = xls.to_csv(index=False).encode("utf-8")
                nome = u.name.replace(".xlsx", ".csv")
            else:
                nome = u.name
            fontes_lista.append((nome, conteudo))
        fontes = tuple(fontes_lista)
    elif EXEMPLO and EXEMPLO.exists():
        fontes = ((EXEMPLO.name, EXEMPLO.read_bytes()),)
        st.caption(f"Usando '{EXEMPLO.name}' como exemplo. Envie seus arquivos para substituir.")
    else:
        st.info("Envie ao menos um arquivo .csv ou .xlsx para comecar.")
        st.stop()

try:
    df, relatorio = _processar(fontes)
except ValueError as e:
    st.error(f"Nao foi possivel processar os dados: {e}")
    st.stop()

with st.sidebar:
    # ---- Secao 2: Filtros ----
    st.subheader("2. Filtros do dashboard")
    d_min, d_max = df["data"].min().date(), df["data"].max().date()
    periodo = st.date_input("Periodo", (d_min, d_max), min_value=d_min, max_value=d_max)
    mask = pd.Series(True, index=df.index)
    if isinstance(periodo, (tuple, list)) and len(periodo) == 2:
        mask &= df["data"].between(pd.Timestamp(periodo[0]), pd.Timestamp(periodo[1]))
    for col, rotulo in [("categoria", "Categoria"), ("regiao", "Regiao"), ("vendedor", "Vendedor")]:
        if tem_dimensao(df, col):
            opcoes = sorted(df[col].unique())
            escolha = st.multiselect(rotulo, opcoes, default=opcoes)
            mask &= df[col].isin(escolha)
    filtrado = df[mask]

    # ---- Secao 3: Configuracao da IA ----
    st.subheader("3. Configuracao da IA")

    with st.expander("Configurar provedor e modelo", expanded=False):
        _prov_env = os.getenv("LLM_PROVIDER", "groq").lower()
        _prov_env = _prov_env if _prov_env in PROVEDORES else "groq"
        _modelo_env = os.getenv("LLM_MODEL", "")
        _chave_env = os.getenv("LLM_API_KEY", "")

        lista_provedores = list(PROVEDORES.keys())
        idx_prov = lista_provedores.index(_prov_env) if _prov_env in lista_provedores else 0
        provedor_ui = st.selectbox(
            "Provedor",
            lista_provedores,
            index=idx_prov,
            format_func=lambda p: PROVEDORES[p]["nome"],
        )
        preset = PROVEDORES[provedor_ui]

        sugestoes = preset.get("modelos_sugeridos", [])
        if sugestoes:
            modelo_padrao = _modelo_env if _modelo_env else sugestoes[0]
            modelo_ui = st.selectbox(
                "Modelo",
                ["(digitar manualmente)"] + sugestoes,
                index=(sugestoes.index(modelo_padrao) + 1
                       if modelo_padrao in sugestoes else 0),
            )
            if modelo_ui == "(digitar manualmente)":
                modelo_ui = st.text_input("Nome do modelo", value=_modelo_env or "")
        else:
            modelo_ui = st.text_input("Modelo", value=_modelo_env or "")

        if preset["exige_chave"]:
            chave_especifica = os.getenv(preset["chave_env"], "") if preset["chave_env"] else ""
            chave_padrao = _chave_env or chave_especifica
            chave_ui = st.text_input(
                f"Chave de API ({preset.get('chave_env', 'LLM_API_KEY')})",
                value=chave_padrao,
                type="password",
                placeholder="sk-... ou sua chave aqui",
            )
        else:
            chave_ui = ""

        base_url_padrao = os.getenv("LLM_BASE_URL", preset["base_url"])
        mostrar_url = provedor_ui in ("custom", "ollama", "lmstudio")
        if mostrar_url:
            base_url_ui = st.text_input("Base URL", value=base_url_padrao or preset["base_url"])
        else:
            base_url_ui = ""

        temperatura_ui = st.slider(
            "Temperatura", 0.0, 1.5,
            float(os.getenv("LLM_TEMPERATURE", "0.3")), 0.05,
        )

    _override: dict = {
        "provedor": provedor_ui,
        "modelo": modelo_ui,
        "api_key": chave_ui,
        "temperatura": temperatura_ui,
    }
    if base_url_ui:
        _override["base_url"] = base_url_ui

    try:
        config_llm = carregar_config(_override)
        st.success(f"Configuracao carregada: {config_llm.descricao}")
    except ConfigErro as e:
        st.error(str(e))
        st.stop()

    anonimizar = st.toggle(
        "Anonimizar clientes", value=True,
        help="Troca nomes por codigos (Cliente-0001) no que vai para a LLM.",
    )
    enviar_amostra = st.toggle("Enviar amostra de linhas", value=True)
    usar_streaming = st.toggle(
        "Resposta em tempo real", value=True,
        help="Exibe a resposta conforme ela e gerada (streaming).",
    )

df_agente = anonimizar_clientes(df) if anonimizar else df

# ------------------------------------------------------------------------ abas
st.title("Vendas + IA")
aba_dados, aba_dash, aba_chat = st.tabs(["Dados", "Dashboard", "Agente financeiro"])

# ------------------------------------------------------------------ aba Dados
with aba_dados:
    st.subheader("Resultado da higienizacao")
    c1, c2, c3 = st.columns(3)
    c1.metric("Linhas lidas", f"{relatorio.linhas_lidas:,}".replace(",", "."))
    c2.metric("Linhas finais", f"{relatorio.linhas_finais:,}".replace(",", "."))
    c3.metric("Removidas", f"{relatorio.linhas_lidas - relatorio.linhas_finais:,}".replace(",", "."))
    col_a, col_b = st.columns([1, 1])
    with col_a:
        _tabela(relatorio.resumo(), hide_index=True)
    with col_b:
        with st.expander("Mapeamento de colunas", expanded=True):
            st.write({orig: f"-> {padrao}" for orig, padrao in relatorio.colunas_mapeadas.items()})
            if relatorio.colunas_ignoradas:
                st.caption("Ignoradas: " + ", ".join(relatorio.colunas_ignoradas))
            if relatorio.colunas_criadas:
                st.caption("Criadas (ausentes no arquivo): " + ", ".join(relatorio.colunas_criadas))
            faltantes = {k: v for k, v in relatorio.nao_informado.items() if v}
            if faltantes:
                st.caption(
                    "Valores vazios marcados como 'Nao informado': "
                    + ", ".join(f"{k}={v}" for k, v in faltantes.items())
                )

    st.subheader("Dados padronizados")
    _tabela(df, height=380)
    st.download_button(
        "Baixar CSV limpo",
        df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name="vendas_limpo.csv",
        mime="text/csv",
    )

    with st.expander("O que e enviado a LLM como contexto"):
        st.caption(
            "Resumo agregado + amostra opcional de linhas. Os dados completos ficam "
            "no seu computador; a LLM consulta o restante por ferramentas (agregacoes)."
        )
        st.code(contexto_para_llm(df_agente, amostra=8 if enviar_amostra else 0), language="text")

# ---------------------------------------------------------------- aba Dashboard
with aba_dash:
    if filtrado.empty:
        st.warning("Nenhum dado para os filtros selecionados.")
    else:
        k = kpis(filtrado)
        mensal = evolucao_mensal(filtrado)
        delta = None
        if len(mensal) >= 2 and pd.notna(mensal["crescimento_pct"].iloc[-1]):
            delta = f"{mensal['crescimento_pct'].iloc[-1]:+.1f}% vs mes anterior"
        m = st.columns(5)
        m[0].metric("Receita", brl(k["receita"]), delta)
        m[1].metric("Pedidos", f"{k['pedidos']:,}".replace(",", "."))
        m[2].metric("Ticket medio", brl(k["ticket_medio"]))
        m[3].metric("Itens vendidos", f"{k['itens']:,}".replace(",", "."))
        m[4].metric("Desconto medio", f"{k['desconto_medio_pct']:.1f}%")

        _plot(charts.fig_evolucao(filtrado), "evolucao")

        esq, dir_ = st.columns(2)
        with esq:
            _plot(charts.fig_ranking(filtrado, "produto", "Top 10 produtos"), "top_prod")
        with dir_:
            if tem_dimensao(filtrado, "categoria"):
                _plot(charts.fig_donut(filtrado, "categoria", "Receita por categoria"), "cat")
            else:
                _plot(charts.fig_dia_semana(filtrado), "dia_a")

        esq, dir_ = st.columns(2)
        with esq:
            if tem_dimensao(filtrado, "regiao"):
                _plot(charts.fig_ranking(filtrado, "regiao", "Receita por regiao"), "reg")
            else:
                _plot(charts.fig_distribuicao(filtrado), "dist_a")
        with dir_:
            if tem_dimensao(filtrado, "vendedor"):
                _plot(charts.fig_ranking(filtrado, "vendedor", "Receita por vendedor"), "vend")
            else:
                _plot(charts.fig_dia_semana(filtrado), "dia_b")

        esq, dir_ = st.columns(2)
        with esq:
            if tem_dimensao(filtrado, "categoria"):
                _plot(charts.fig_treemap(filtrado), "tree")
            _plot(charts.fig_dia_semana(filtrado), "dia")
        with dir_:
            heat = charts.fig_heatmap(filtrado)
            if heat is not None:
                _plot(heat, "heat")
            _plot(charts.fig_distribuicao(filtrado), "dist")

# -------------------------------------------------------------------- aba Chat
with aba_chat:
    st.subheader("Converse com o Fin, seu agente financeiro")
    st.caption(f"Usando: **{config_llm.descricao}**")

    assinatura = (
        len(df_agente),
        round(float(df_agente["valor_total"].sum()), 2),
        anonimizar,
        enviar_amostra,
        config_llm.assinatura(),
    )

    if st.session_state.get("agente_sig") != assinatura:
        try:
            st.session_state.agente = AgenteFinanceiro(df_agente, config_llm, enviar_amostra)
            st.session_state.agente_sig = assinatura
            st.session_state.mensagens = []
        except AgenteErro as e:
            st.error(str(e))
            st.stop()

    agente: AgenteFinanceiro = st.session_state.agente

    # Botoes rapidos
    colunas_botoes = st.columns(len(PERGUNTAS_RAPIDAS) + 1)
    pergunta: str | None = None

    if colunas_botoes[0].button("Analise executiva"):
        pergunta = "__analise__"

    for i, (rotulo, texto) in enumerate(PERGUNTAS_RAPIDAS.items(), start=1):
        if colunas_botoes[i].button(rotulo):
            pergunta = texto

    col_limpar, col_exportar = st.columns([1, 1])
    with col_limpar:
        if st.button("Limpar conversa"):
            agente.reiniciar()
            st.session_state.mensagens = []
            st.rerun()
    with col_exportar:
        if st.session_state.get("mensagens"):
            historico_md = agente.exportar_historico()
            st.download_button(
                "Exportar conversa (.md)",
                historico_md.encode("utf-8"),
                file_name="conversa_fin.md",
                mime="text/markdown",
            )

    # Exibe historico
    for msg in st.session_state.mensagens:
        with st.chat_message(msg["papel"]):
            st.markdown(msg["texto"])

    digitada = st.chat_input("Pergunte sobre suas vendas ou peca uma explicacao financeira...")
    pergunta = digitada or pergunta

    if pergunta:
        visivel = (
            "Faca uma analise executiva dos meus dados."
            if pergunta == "__analise__"
            else pergunta
        )
        st.session_state.mensagens.append({"papel": "user", "texto": visivel})
        with st.chat_message("user"):
            st.markdown(visivel)

        with st.chat_message("assistant"):
            try:
                if usar_streaming:
                    gen = (
                        agente.analise_executiva_stream()
                        if pergunta == "__analise__"
                        else agente.perguntar_stream(pergunta)
                    )
                    resposta = st.write_stream(gen)
                    if not resposta:
                        resposta = "Nao consegui gerar uma resposta. Tente reformular a pergunta."
                else:
                    with st.spinner("Analisando os dados..."):
                        resposta = (
                            agente.analise_executiva()
                            if pergunta == "__analise__"
                            else agente.perguntar(pergunta)
                        )
                    st.markdown(resposta)
            except AgenteErro as e:
                resposta = f"Erro: {e}"
                st.error(resposta)
            except Exception as e:
                resposta = f"Falha inesperada ao falar com a LLM: {e}"
                st.error(resposta)

        st.session_state.mensagens.append({"papel": "assistant", "texto": resposta or ""})
