"""Extração, higienização e padronização de planilhas de vendas (.csv).

Fluxo: bytes do CSV -> leitura tolerante (encoding/separador) -> nomes de colunas
padronizados -> tipos corrigidos (números em formato BR, datas) -> texto unificado
-> remoção de duplicadas/linhas inválidas -> colunas derivadas (ano, mês, etc.).
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

NAO_INFORMADO = "Não informado"
COLUNAS_TEXTO = ["produto", "categoria", "cliente", "regiao", "vendedor"]
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

ORDEM_COLUNAS = [
    "data", "pedido_id", "produto", "categoria", "cliente", "regiao", "vendedor",
    "quantidade", "preco_unitario", "desconto", "valor_total",
    "ano", "mes", "ano_mes", "dia_semana", "outlier", "arquivo_origem",
]

# nome padrão -> apelidos aceitos (já em snake_case, sem acento)
ALIASES: dict[str, list[str]] = {
    "data": ["data", "date", "dt", "data_venda", "data_da_venda", "data_pedido",
             "data_do_pedido", "dt_venda", "order_date"],
    "pedido_id": ["pedido_id", "pedido", "id_pedido", "order_id", "n_pedido",
                  "numero_pedido", "id"],
    "produto": ["produto", "product", "item", "descricao", "nome_produto"],
    "categoria": ["categoria", "category", "grupo", "tipo", "departamento"],
    "cliente": ["cliente", "customer", "nome_cliente", "comprador"],
    "regiao": ["regiao", "region", "estado", "uf"],
    "vendedor": ["vendedor", "seller", "salesperson", "representante", "atendente"],
    "quantidade": ["quantidade", "qtd", "qtde", "quantity", "qty", "unidades"],
    "preco_unitario": ["preco_unitario", "preco", "valor_unitario", "unit_price",
                       "price", "preco_unit", "vl_unitario"],
    "desconto": ["desconto", "discount", "desc", "perc_desconto"],
    "valor_total": ["valor_total", "total", "valor", "receita", "faturamento",
                    "revenue", "amount", "vl_total", "venda_total"],
}
_ALIAS_REVERSO = {a: padrao for padrao, lista in ALIASES.items() for a in lista}

# nome do estado (sem acento, minúsculo) -> sigla; usado para unificar "São Paulo" e "SP"
UF_POR_NOME = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI",
    "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}

TOKENS_NULOS = {
    "", "nan", "none", "null", "n/a", "na", "-", "--", "#n/d", "#n/a",
    "sem informacao", "nao informado", "nao se aplica",
}


# ----------------------------------------------------------------------------
# Relatório
# ----------------------------------------------------------------------------
@dataclass
class RelatorioLimpeza:
    arquivos: list[str] = field(default_factory=list)
    linhas_lidas: int = 0
    linhas_finais: int = 0
    sem_data_removidas: int = 0
    invalidas_removidas: int = 0
    duplicadas_removidas: int = 0
    valores_recalculados: int = 0
    quantidades_assumidas: int = 0
    outliers: int = 0
    colunas_mapeadas: dict[str, str] = field(default_factory=dict)
    colunas_ignoradas: list[str] = field(default_factory=list)
    colunas_criadas: list[str] = field(default_factory=list)
    nao_informado: dict[str, int] = field(default_factory=dict)

    def resumo(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Etapa": [
                    "Linhas lidas",
                    "Removidas: sem data válida",
                    "Removidas: valor/quantidade inválidos (≤ 0 ou vazios)",
                    "Removidas: duplicadas",
                    "Valores totais recalculados (qtd × preço × desconto)",
                    "Quantidades assumidas como 1",
                    "Outliers sinalizados (mantidos)",
                    "Linhas finais",
                ],
                "Linhas": [
                    self.linhas_lidas, self.sem_data_removidas, self.invalidas_removidas,
                    self.duplicadas_removidas, self.valores_recalculados,
                    self.quantidades_assumidas, self.outliers, self.linhas_finais,
                ],
            }
        )


# ----------------------------------------------------------------------------
# Utilitários de texto/números/datas
# ----------------------------------------------------------------------------
def sem_acento(txt: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(txt)) if not unicodedata.combining(c))


def _snake(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", sem_acento(nome).lower().strip()).strip("_")


def _limpar_numero(s: pd.Series) -> pd.Series:
    """Converte 'R$ 1.234,56', '1234.56', '(10,00)' etc. em float."""
    t = s.astype("string").str.strip()
    t = t.str.replace(r"(?i)\s*(unidades?|unid|und|un|pcs?)\.?$", "", regex=True)  # "3 un" -> "3"
    t = t.str.replace(r"(?i)r\$|\s|%", "", regex=True)
    parenteses = t.str.match(r"^\(.*\)$").fillna(False).astype(bool)
    t = t.str.strip("()")

    # Decide o formato POR VALOR (colunas podem misturar '1.234,56' e '1234.56'):
    #  - vírgula é o último separador  -> BR: ponto = milhar, vírgula = decimal
    #  - ponto é o último separador, com vírgula antes -> US: vírgula = milhar
    #  - só pontos: vários -> milhar; um ponto com 3 dígitos depois ('1.250') só é
    #    milhar se a coluna tiver valores no formato BR; senão é decimal.
    tem_virgula = t.str.contains(",", na=False)
    tem_ponto = t.str.contains(r"\.", na=False)
    br = tem_virgula & t.str.contains(r",[^.]*$", na=False)
    us = tem_virgula & ~br
    coluna_br = bool(br.any())
    so_ponto = tem_ponto & ~tem_virgula
    milhar = so_ponto & (
        (t.str.count(r"\.").fillna(0) > 1)
        | (coluna_br & t.str.match(r"^-?\d{1,3}\.\d{3}$").fillna(False).astype(bool))
    )
    sem_pontos = t.str.replace(".", "", regex=False)
    t = t.mask(br, sem_pontos.str.replace(",", ".", regex=False))
    t = t.mask(us, t.str.replace(",", "", regex=False))
    t = t.mask(milhar, sem_pontos)
    out = pd.to_numeric(t, errors="coerce").astype("float64")
    return out.mask(parenteses, -out)


def _limpar_desconto(s: pd.Series) -> pd.Series:
    d = _limpar_numero(s)
    if d.max(skipna=True) > 1:  # veio como 10 ou "10%" -> 0.10
        d = d / 100
    return d.fillna(0.0).clip(0, 1)


def _limpar_data(s: pd.Series) -> pd.Series:
    """Datas ISO (AAAA-MM-DD) são lidas como ISO; as demais (31/12/2026) como dia/mês/ano."""
    t = s.astype("string").str.strip()
    iso = t.str.match(r"^\d{4}-\d{1,2}-\d{1,2}", na=False).fillna(False).astype(bool)
    out = pd.Series(pd.NaT, index=t.index, dtype="datetime64[us]")
    if iso.any():
        out[iso] = pd.to_datetime(t[iso], errors="coerce", dayfirst=False, format="mixed")
    if (~iso).any():
        out[~iso] = pd.to_datetime(t[~iso], errors="coerce", dayfirst=True, format="mixed")
    return out.dt.normalize()


def _padronizar_texto(s: pd.Series) -> pd.Series:
    """Remove espaços extras, trata nulos, aplica Title Case e unifica variantes
    que diferem só por acento/caixa (fica a grafia mais frequente)."""
    t = s.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    chave_nulo = t.map(lambda x: sem_acento(x).lower() if isinstance(x, str) else None)
    nulo = t.isna() | chave_nulo.isin(TOKENS_NULOS)
    t = t.mask(nulo, NAO_INFORMADO).astype(object)

    def titulo(x: str) -> str:
        if x == NAO_INFORMADO:
            return x
        return x.upper() if len(x) <= 2 else x.title()

    t = t.map(titulo)
    chave = t.map(lambda x: sem_acento(x).lower())
    mais_frequente = t.groupby(chave).agg(lambda x: x.value_counts().idxmax())
    return chave.map(mais_frequente)


# ----------------------------------------------------------------------------
# Leitura
# ----------------------------------------------------------------------------
def ler_csv(conteudo: bytes, nome: str = "arquivo.csv") -> pd.DataFrame:
    """Lê um CSV detectando encoding e separador; tudo entra como texto."""
    texto = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError(f"'{nome}': não foi possível decodificar o arquivo.")

    primeira = next((ln for ln in texto.splitlines() if ln.strip()), "")
    sep = max([";", ",", "\t", "|"], key=primeira.count)
    if primeira.count(sep) == 0:
        raise ValueError(f"'{nome}': não foi possível identificar o separador de colunas.")

    df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, skipinitialspace=True,
                     on_bad_lines="skip")
    df = df.dropna(how="all")
    return df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]


def _padronizar_colunas(df: pd.DataFrame, rel: RelatorioLimpeza) -> pd.DataFrame:
    novos: dict[str, str] = {}
    usados: set[str] = set()
    for col in df.columns:
        alvo = _ALIAS_REVERSO.get(_snake(col))
        if alvo and alvo not in usados:
            novos[col] = alvo
            usados.add(alvo)
            rel.colunas_mapeadas[str(col)] = alvo
        elif str(col) not in rel.colunas_ignoradas:
            rel.colunas_ignoradas.append(str(col))
    return df[list(novos)].rename(columns=novos)


# ----------------------------------------------------------------------------
# Higienização
# ----------------------------------------------------------------------------
def _higienizar(df: pd.DataFrame, rel: RelatorioLimpeza) -> pd.DataFrame:
    cols = set(df.columns)
    if "data" not in cols or not ("valor_total" in cols or {"quantidade", "preco_unitario"} <= cols):
        raise ValueError(
            "Não encontrei as colunas mínimas: uma de DATA e uma de VALOR TOTAL "
            "(ou QUANTIDADE + PREÇO UNITÁRIO). "
            f"Colunas reconhecidas: {sorted(cols)}. Ignoradas: {rel.colunas_ignoradas}."
        )
    df = df.copy()

    # texto
    for c in COLUNAS_TEXTO:
        if c in df:
            df[c] = _padronizar_texto(df[c])
            if c == "regiao":  # "São Paulo", "Sao Paulo", "sp" -> "SP"
                chave = df[c].map(lambda x: sem_acento(x).lower().strip())
                df[c] = chave.map(UF_POR_NOME).fillna(df[c]).astype(object)
        else:
            df[c] = NAO_INFORMADO
            rel.colunas_criadas.append(c)

    # números
    nan = pd.Series(np.nan, index=df.index)
    q = _limpar_numero(df["quantidade"]) if "quantidade" in df else nan.copy()
    p = _limpar_numero(df["preco_unitario"]) if "preco_unitario" in df else nan.copy()
    v = _limpar_numero(df["valor_total"]) if "valor_total" in df else nan.copy()
    d = _limpar_desconto(df["desconto"]) if "desconto" in df else pd.Series(0.0, index=df.index)

    calc = q * p * (1 - d)
    falta_v = v.isna() & calc.notna()
    v = v.fillna(calc)
    rel.valores_recalculados = int(falta_v.sum())

    base = (p * (1 - d)).replace(0, np.nan)
    derivada = (v / base).round()
    q = q.fillna(derivada.where(derivada > 0))
    rel.quantidades_assumidas = int(q.isna().sum())
    q = q.fillna(1)
    p = p.fillna(v / (q * (1 - d)).replace(0, np.nan))

    df["quantidade"] = q
    df["preco_unitario"] = p.round(2)
    df["desconto"] = d
    df["valor_total"] = v.round(2)

    # datas
    df["data"] = _limpar_data(df["data"])
    sem_data = df["data"].isna()
    rel.sem_data_removidas = int(sem_data.sum())
    df = df[~sem_data]

    invalidas = df["valor_total"].isna() | (df["valor_total"] <= 0) | (df["quantidade"] <= 0)
    rel.invalidas_removidas = int(invalidas.sum())
    df = df[~invalidas]

    # pedido_id (limpa antes de deduplicar; ids automáticos vêm depois)
    if "pedido_id" in df:
        pid = df["pedido_id"].astype("string").str.strip()
        df["pedido_id"] = pid.mask(pid.str.lower().isin(TOKENS_NULOS))

    # duplicadas (ignora o arquivo de origem)
    subset = [c for c in df.columns if c != "arquivo_origem"]
    antes = len(df)
    df = df.drop_duplicates(subset=subset).reset_index(drop=True)
    rel.duplicadas_removidas = antes - len(df)

    ids_auto = "L" + pd.Series(np.arange(1, len(df) + 1), index=df.index).astype(str).str.zfill(5)
    if "pedido_id" in df:
        df["pedido_id"] = df["pedido_id"].fillna(ids_auto).astype(str)
    else:
        df["pedido_id"] = ids_auto
        rel.colunas_criadas.append("pedido_id")

    if df.empty:
        raise ValueError("Nenhuma linha válida restou após a higienização.")

    # colunas derivadas
    df["ano"] = df["data"].dt.year.astype(int)
    df["mes"] = df["data"].dt.month.astype(int)
    df["ano_mes"] = df["data"].dt.strftime("%Y-%m")
    df["dia_semana"] = df["data"].dt.dayofweek.map(dict(enumerate(DIAS_SEMANA)))

    q1, q3 = df["valor_total"].quantile([0.25, 0.75])
    df["outlier"] = df["valor_total"] > q3 + 3 * (q3 - q1)
    rel.outliers = int(df["outlier"].sum())

    rel.nao_informado = {c: int((df[c] == NAO_INFORMADO).sum()) for c in COLUNAS_TEXTO}
    rel.linhas_finais = len(df)

    return df[ORDEM_COLUNAS].sort_values(["data", "pedido_id"]).reset_index(drop=True)


def carregar_arquivos(fontes: list[tuple[str, bytes]]) -> tuple[pd.DataFrame, RelatorioLimpeza]:
    """Recebe [(nome, bytes_do_csv), ...] e devolve (DataFrame limpo, relatório)."""
    rel = RelatorioLimpeza()
    quadros = []
    for nome, conteudo in fontes:
        bruto = ler_csv(conteudo, nome)
        rel.arquivos.append(nome)
        rel.linhas_lidas += len(bruto)
        quadro = _padronizar_colunas(bruto, rel)
        quadro["arquivo_origem"] = nome
        quadros.append(quadro)
    if not quadros:
        raise ValueError("Nenhum arquivo informado.")
    df = pd.concat(quadros, ignore_index=True)
    return _higienizar(df, rel), rel


def anonimizar_clientes(df: pd.DataFrame) -> pd.DataFrame:
    """Troca nomes de clientes por códigos (Cliente-0001...) antes de enviar à LLM."""
    codigos, unicos = pd.factorize(df["cliente"])
    rotulos = np.array(
        [NAO_INFORMADO if u == NAO_INFORMADO else f"Cliente-{i + 1:04d}" for i, u in enumerate(unicos)],
        dtype=object,
    )
    out = df.copy()
    out["cliente"] = rotulos[codigos]
    return out
