"""Gráficos Plotly do dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from analytics import brl, evolucao_mensal, tem_dimensao
from data_processing import DIAS_SEMANA

COR = "#4F46E5"
COR_2 = "#F59E0B"
PALETA = px.colors.qualitative.Set2


def _layout(fig: go.Figure, titulo: str, altura: int = 380) -> go.Figure:
    fig.update_layout(
        title=dict(text=titulo, x=0.01, font=dict(size=16)),
        template="plotly_white",
        height=altura,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


def fig_evolucao(df: pd.DataFrame) -> go.Figure:
    m = evolucao_mensal(df)
    fig = go.Figure()
    fig.add_bar(x=m["ano_mes"], y=m["receita"], name="Receita", marker_color=COR,
                hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>")
    fig.add_scatter(x=m["ano_mes"], y=m["media_movel_3m"], name="Média móvel 3m",
                    mode="lines+markers", line=dict(color=COR_2, width=3),
                    hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>")
    fig.update_yaxes(tickprefix="R$ ", separatethousands=True)
    fig.update_xaxes(type="category")
    return _layout(fig, "Receita mensal", 400)


def fig_ranking(df: pd.DataFrame, dim: str, titulo: str, n: int = 10) -> go.Figure:
    r = df.groupby(dim)["valor_total"].sum().sort_values(ascending=False).head(n).reset_index()
    r = r.sort_values("valor_total")
    fig = go.Figure(go.Bar(
        x=r["valor_total"], y=r[dim], orientation="h", marker_color=COR,
        text=[brl(v) for v in r["valor_total"]], textposition="auto",
        hovertemplate="%{y}<br>R$ %{x:,.2f}<extra></extra>",
    ))
    fig.update_xaxes(tickprefix="R$ ", separatethousands=True)
    return _layout(fig, titulo)


def fig_donut(df: pd.DataFrame, dim: str, titulo: str) -> go.Figure:
    r = df.groupby(dim)["valor_total"].sum().reset_index()
    fig = px.pie(r, names=dim, values="valor_total", hole=0.55, color_discrete_sequence=PALETA)
    fig.update_traces(textposition="outside", textinfo="percent+label",
                      hovertemplate="%{label}<br>R$ %{value:,.2f}<extra></extra>")
    fig.update_layout(showlegend=False)
    return _layout(fig, titulo)


def fig_treemap(df: pd.DataFrame) -> go.Figure:
    r = df.groupby(["categoria", "produto"])["valor_total"].sum().reset_index()
    fig = px.treemap(r, path=["categoria", "produto"], values="valor_total",
                     color_discrete_sequence=PALETA)
    fig.update_traces(hovertemplate="%{label}<br>R$ %{value:,.2f}<extra></extra>")
    return _layout(fig, "Categoria → Produto")


def fig_dia_semana(df: pd.DataFrame) -> go.Figure:
    r = df.groupby("dia_semana")["valor_total"].sum().reindex(DIAS_SEMANA).fillna(0).reset_index()
    fig = px.bar(r, x="dia_semana", y="valor_total", color_discrete_sequence=[COR])
    fig.update_yaxes(tickprefix="R$ ", separatethousands=True, title=None)
    fig.update_xaxes(title=None)
    fig.update_traces(hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>")
    return _layout(fig, "Receita por dia da semana")


def fig_distribuicao(df: pd.DataFrame) -> go.Figure:
    fig = px.histogram(df, x="valor_total", nbins=40, marginal="box",
                       color_discrete_sequence=[COR])
    fig.update_xaxes(tickprefix="R$ ", title="Valor da venda")
    fig.update_yaxes(title="Vendas")
    return _layout(fig, "Distribuição do valor das vendas")


def fig_heatmap(df: pd.DataFrame) -> go.Figure | None:
    if not (tem_dimensao(df, "regiao") and tem_dimensao(df, "categoria")):
        return None
    p = df.pivot_table(index="regiao", columns="categoria", values="valor_total",
                       aggfunc="sum", fill_value=0)
    fig = px.imshow(p, aspect="auto", color_continuous_scale="Purples", text_auto=".2s")
    fig.update_layout(coloraxis_showscale=False)
    return _layout(fig, "Receita: região × categoria")
