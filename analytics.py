"""Métricas e agregações reutilizadas pelo dashboard e pelas ferramentas da LLM."""
from __future__ import annotations

import pandas as pd

from data_processing import NAO_INFORMADO, sem_acento

DIMENSOES = ["produto", "categoria", "cliente", "regiao", "vendedor",
             "ano_mes", "ano", "mes", "dia_semana"]
METRICAS = ["valor_total", "quantidade", "pedidos", "desconto", "preco_unitario"]
FUNCOES = ["sum", "mean", "count", "max", "min", "median"]
_DIMENSOES_TEMPO = {"ano_mes", "ano", "mes"}


def brl(v: float) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def tem_dimensao(df: pd.DataFrame, dim: str) -> bool:
    """True se a coluna tem informação útil (mais de um valor real)."""
    valores = df[dim].unique()
    return len([x for x in valores if x != NAO_INFORMADO]) > 1


def kpis(df: pd.DataFrame) -> dict:
    receita = float(df["valor_total"].sum())
    pedidos = int(df["pedido_id"].nunique())
    return {
        "receita": receita,
        "pedidos": pedidos,
        "itens": int(df["quantidade"].sum()),
        "ticket_medio": receita / pedidos if pedidos else 0.0,
        "desconto_medio_pct": float(df["desconto"].mean() * 100),
        "clientes": int(df.loc[df["cliente"] != NAO_INFORMADO, "cliente"].nunique()),
    }


def evolucao_mensal(df: pd.DataFrame) -> pd.DataFrame:
    m = (
        df.groupby("ano_mes")
        .agg(receita=("valor_total", "sum"), pedidos=("pedido_id", "nunique"),
             itens=("quantidade", "sum"))
        .reset_index()
        .sort_values("ano_mes")
    )
    m["crescimento_pct"] = m["receita"].pct_change() * 100
    m["media_movel_3m"] = m["receita"].rolling(3, min_periods=1).mean()
    return m


def ranking(df: pd.DataFrame, dim: str, n: int = 10) -> pd.DataFrame:
    r = (
        df.groupby(dim)["valor_total"].sum().sort_values(ascending=False)
        .head(n).rename("receita").reset_index()
    )
    total = df["valor_total"].sum()
    r["participacao_pct"] = (r["receita"] / total * 100).round(1) if total else 0.0
    return r


def agregar(
    df: pd.DataFrame,
    agrupar_por: str,
    metrica: str = "valor_total",
    funcao: str = "sum",
    top_n: int = 10,
    data_inicio: str = "",
    data_fim: str = "",
    filtro_coluna: str = "",
    filtro_valor: str = "",
) -> pd.DataFrame:
    """Agregação segura (sem executar código arbitrário) usada pelo agente."""
    if agrupar_por not in DIMENSOES:
        raise ValueError(f"agrupar_por inválido '{agrupar_por}'. Use um de: {DIMENSOES}")
    if metrica not in METRICAS:
        raise ValueError(f"metrica inválida '{metrica}'. Use uma de: {METRICAS}")
    if funcao not in FUNCOES:
        raise ValueError(f"funcao inválida '{funcao}'. Use uma de: {FUNCOES}")

    base = df
    if data_inicio:
        base = base[base["data"] >= pd.to_datetime(data_inicio)]
    if data_fim:
        base = base[base["data"] <= pd.to_datetime(data_fim)]
    if filtro_coluna and filtro_valor:
        if filtro_coluna not in DIMENSOES:
            raise ValueError(f"filtro_coluna inválida '{filtro_coluna}'. Use uma de: {DIMENSOES}")
        chave = sem_acento(filtro_valor).lower()
        base = base[base[filtro_coluna].astype(str).map(lambda x: chave in sem_acento(x).lower())]
    if base.empty:
        raise ValueError("Nenhum dado encontrado para esses filtros.")

    g = base.groupby(agrupar_por)
    res = g["pedido_id"].nunique() if metrica == "pedidos" else g[metrica].agg(funcao)
    res = res.rename("resultado").reset_index()
    top_n = max(1, min(int(top_n), 100))
    if agrupar_por in _DIMENSOES_TEMPO:
        res = res.sort_values(agrupar_por).tail(top_n)
    else:
        res = res.sort_values("resultado", ascending=False).head(top_n)
    res["resultado"] = res["resultado"].round(2)
    return res.reset_index(drop=True)


def contexto_para_llm(df: pd.DataFrame, amostra: int = 8) -> str:
    """Resumo textual do dataset que é enviado à LLM como contexto."""
    k = kpis(df)
    linhas = [
        f"PERÍODO: {df['data'].min():%d/%m/%Y} a {df['data'].max():%d/%m/%Y}",
        f"LINHAS: {len(df)}",
        f"COLUNAS: {', '.join(df.columns)}",
        "",
        "KPIs GERAIS:",
        f"- Receita total: {brl(k['receita'])}",
        f"- Pedidos: {k['pedidos']}",
        f"- Itens vendidos: {k['itens']}",
        f"- Ticket médio: {brl(k['ticket_medio'])}",
        f"- Desconto médio: {k['desconto_medio_pct']:.1f}%",
        f"- Clientes distintos: {k['clientes']}",
        "",
        "EVOLUÇÃO MENSAL (ano_mes,receita,pedidos,itens,crescimento_pct):",
        evolucao_mensal(df).tail(24)[["ano_mes", "receita", "pedidos", "itens", "crescimento_pct"]]
        .round(2).to_csv(index=False),
    ]
    for dim, titulo in [("produto", "TOP 10 PRODUTOS"), ("categoria", "CATEGORIAS"),
                        ("regiao", "REGIÕES"), ("vendedor", "VENDEDORES")]:
        if tem_dimensao(df, dim):
            linhas += [f"{titulo} ({dim},receita,participacao_pct):",
                       ranking(df, dim, 10).to_csv(index=False)]
    if amostra > 0:
        linhas += ["AMOSTRA DE LINHAS:",
                   df.sample(min(amostra, len(df)), random_state=1)
                   .drop(columns=["outlier", "arquivo_origem"])
                   .assign(data=lambda x: x["data"].dt.strftime("%Y-%m-%d"))
                   .to_csv(index=False)]
    return "\n".join(linhas)
