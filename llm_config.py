"""Configuração da IA — chave e provedor vêm exclusivamente do backend.

A API key NUNCA é informada pelo usuário na interface.
Ela deve ser configurada via st.secrets (Streamlit Community Cloud ou
.streamlit/secrets.toml local) ou via variável de ambiente.

Provedores suportados (mesmo conjunto do cofre-estoque-inteligente):
  anthropic | openai | groq | gemini | openrouter | compativel

Como configurar (veja .streamlit/secrets.toml.example):
  - st.secrets: adicione as variáveis em Settings > Secrets (nuvem)
    ou em .streamlit/secrets.toml (local).
  - Variáveis de ambiente: defina as variáveis no sistema ou em .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

RAIZ = Path(__file__).parent

# ---------------------------------------------------------------------------
# Registro central de provedores suportados (mesmo padrão do cofre).
# ---------------------------------------------------------------------------
REGISTRO_PROVEDORES: Dict[str, Dict[str, Any]] = {
    "anthropic": {
        "nome": "Anthropic (Claude)",
        "tipo_cliente": "anthropic",
        "base_url": None,
        "var_chave": "ANTHROPIC_API_KEY",
        "var_modelo": "ANTHROPIC_MODEL",
        "modelo_padrao": "claude-3-5-sonnet-20241022",
        "modelos_sugeridos": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-haiku-20240307",
        ],
        "var_base_url": None,
        "exige_chave": True,
    },
    "openai": {
        "nome": "OpenAI (GPT)",
        "tipo_cliente": "openai",
        "base_url": "https://api.openai.com/v1",
        "var_chave": "OPENAI_API_KEY",
        "var_modelo": "OPENAI_MODEL",
        "modelo_padrao": "gpt-4o-mini",
        "modelos_sugeridos": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "var_base_url": None,
        "exige_chave": True,
    },
    "groq": {
        "nome": "Groq",
        "tipo_cliente": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "var_chave": "GROQ_API_KEY",
        "var_modelo": "GROQ_MODEL",
        "modelo_padrao": "llama-3.3-70b-versatile",
        "modelos_sugeridos": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
        "var_base_url": None,
        "exige_chave": True,
    },
    "gemini": {
        "nome": "Google Gemini (OpenAI compatível)",
        "tipo_cliente": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "var_chave": "GEMINI_API_KEY",
        "var_modelo": "GEMINI_MODEL",
        "modelo_padrao": "gemini-2.5-flash",
        "modelos_sugeridos": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
        "var_base_url": None,
        "exige_chave": True,
    },
    "openrouter": {
        "nome": "OpenRouter",
        "tipo_cliente": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "var_chave": "OPENROUTER_API_KEY",
        "var_modelo": "OPENROUTER_MODEL",
        "modelo_padrao": "meta-llama/llama-3.3-70b-instruct",
        "modelos_sugeridos": [
            "meta-llama/llama-3.3-70b-instruct",
            "openai/gpt-4o",
            "google/gemini-flash-1.5",
            "anthropic/claude-3.5-sonnet",
        ],
        "var_base_url": None,
        "exige_chave": True,
    },
    "compativel": {
        "nome": "Compatível com OpenAI (Ollama / Local)",
        "tipo_cliente": "openai",
        "base_url": "http://localhost:11434/v1",
        "var_chave": "LLM_API_KEY",
        "var_modelo": "LLM_MODEL",
        "modelo_padrao": "llama3",
        "modelos_sugeridos": ["llama3.3", "qwen2.5", "gemma3", "mistral", "phi4"],
        "var_base_url": "LLM_BASE_URL",
        "exige_chave": False,
    },
}

# Provedores expostos na UI (mapeamento nome → rótulo legível)
PROVEDORES: Dict[str, str] = {pid: info["nome"] for pid, info in REGISTRO_PROVEDORES.items()}


# ---------------------------------------------------------------------------
# Leitura de segredos — st.secrets tem prioridade sobre os.environ
# ---------------------------------------------------------------------------
def obter_segredo(chave: str, padrao: str = "") -> str:
    """Recupera configuração com prioridade: st.secrets > os.environ > padrão."""
    try:
        import streamlit as st

        if hasattr(st, "secrets") and chave in st.secrets:
            valor = st.secrets[chave]
            if valor is not None:
                return str(valor).strip()
    except Exception:
        pass

    valor_env = os.environ.get(chave)
    if valor_env is not None and str(valor_env).strip():
        return str(valor_env).strip()

    return padrao


# ---------------------------------------------------------------------------
# Resolução de credenciais por provedor
# ---------------------------------------------------------------------------
def obter_credenciais_provedor(pid: str) -> Optional[Dict[str, Any]]:
    """Retorna credenciais de um provedor se sua chave estiver configurada no backend."""
    pid = (pid or "").strip().lower()
    if pid not in REGISTRO_PROVEDORES:
        return None

    info = REGISTRO_PROVEDORES[pid]
    chave = obter_segredo(info["var_chave"])
    modelo = obter_segredo(info["var_modelo"])

    # Compatibilidade reversa com LLM_PROVIDER + LLM_API_KEY genéricos
    provedor_legado = obter_segredo("LLM_PROVIDER", "").lower()
    if not chave:
        if pid == "compativel" and obter_segredo("LLM_BASE_URL"):
            chave = obter_segredo("LLM_API_KEY", "sem-chave")
        elif provedor_legado == pid:
            chave = obter_segredo("LLM_API_KEY")
        elif not provedor_legado and pid == "anthropic":
            chave = obter_segredo("LLM_API_KEY")

    if not chave or chave.startswith("sua-chave") or chave == "sua-chave-aqui":
        # Provedores locais não exigem chave real
        if not info["exige_chave"]:
            chave = "sem-chave"
        else:
            return None

    if not modelo:
        if (provedor_legado == pid or (not provedor_legado and pid == "anthropic")) and obter_segredo("LLM_MODEL"):
            modelo = obter_segredo("LLM_MODEL")
        else:
            modelo = info["modelo_padrao"]

    base_url = info["base_url"]
    if info.get("var_base_url"):
        base_url = obter_segredo(info["var_base_url"], base_url or "")

    return {
        "id": pid,
        "nome": info["nome"],
        "tipo_cliente": info["tipo_cliente"],
        "base_url": base_url,
        "api_key": chave,
        "modelo": modelo,
        "modelos_sugeridos": info.get("modelos_sugeridos", []),
    }


def provedores_configurados() -> Dict[str, Dict[str, Any]]:
    """Retorna apenas os provedores com chave de API configurada no backend."""
    configurados = {}
    for pid in REGISTRO_PROVEDORES:
        creds = obter_credenciais_provedor(pid)
        if creds:
            configurados[pid] = creds
    return configurados


def ordem_de_tentativa(provedor_preferido: Optional[str] = None) -> List[str]:
    """
    Calcula a lista ordenada de provedores a tentar, sem duplicatas.
    Prioridade:
    1. Provedor preferido (se especificado e configurado)
    2. Provedor principal em LLM_PROVIDER
    3. Fallbacks em LLM_FALLBACKS (separados por vírgula)
    4. Demais provedores configurados
    """
    disponiveis = provedores_configurados()
    if not disponiveis:
        return []

    ordem: List[str] = []

    if provedor_preferido:
        pref = provedor_preferido.strip().lower()
        if pref in disponiveis and pref not in ordem:
            ordem.append(pref)

    provedor_principal = obter_segredo("LLM_PROVIDER", "").lower()
    if provedor_principal in disponiveis and provedor_principal not in ordem:
        ordem.append(provedor_principal)

    fallbacks_raw = obter_segredo("LLM_FALLBACKS", "")
    if fallbacks_raw:
        for f in fallbacks_raw.split(","):
            f_clean = f.strip().lower()
            if f_clean in disponiveis and f_clean not in ordem:
                ordem.append(f_clean)

    for pid in REGISTRO_PROVEDORES:
        if pid in disponiveis and pid not in ordem:
            ordem.append(pid)

    return ordem


# ---------------------------------------------------------------------------
# ConfigLLM — dataclass imutável usada pelo AgenteFinanceiro
# ---------------------------------------------------------------------------
class ConfigErro(RuntimeError):
    """Configuração da IA ausente ou inválida (mensagem apresentável ao usuário)."""


@dataclass(frozen=True)
class ConfigLLM:
    provedor: str
    nome: str
    base_url: str
    api_key: str = field(repr=False)   # nunca aparece em logs/prints
    modelos: Tuple[str, ...]            # (principal, fallback1, ...)
    temperatura: float
    timeout: float
    arquivo_instrucoes: Path

    @property
    def descricao(self) -> str:
        return f"{self.nome} • {self.modelos[0]}"

    def assinatura(self) -> int:
        """Muda quando qualquer parte da configuração muda (força recriação do agente)."""
        return hash((self.provedor, self.base_url, self.api_key, self.modelos,
                     self.temperatura, self.timeout, str(self.arquivo_instrucoes)))

    def instrucoes_mtime(self) -> int:
        try:
            return self.arquivo_instrucoes.stat().st_mtime_ns
        except OSError:
            return 0


def _numero(nome: str, padrao: float, minimo: float, maximo: float) -> float:
    bruto = obter_segredo(nome)
    if not bruto:
        return padrao
    try:
        valor = float(bruto.replace(",", "."))
    except ValueError:
        raise ConfigErro(f"{nome}='{bruto}' não é um número válido.") from None
    if not minimo <= valor <= maximo:
        raise ConfigErro(f"{nome} deve estar entre {minimo:g} e {maximo:g}.")
    return valor


def carregar_config(provedor_preferido: Optional[str] = None, modelo_preferido: Optional[str] = None) -> ConfigLLM:
    """
    Lê st.secrets / variáveis de ambiente e devolve a ConfigLLM do primeiro
    provedor disponível.

    Args:
        provedor_preferido: ID do provedor selecionado na UI (sem chave — só escolha).
        modelo_preferido:   Nome do modelo selecionado na UI.
    """
    ordem = ordem_de_tentativa(provedor_preferido)
    if not ordem:
        raise ConfigErro(
            "Nenhum provedor de IA configurado. "
            "Adicione as chaves de API em .streamlit/secrets.toml "
            "(veja .streamlit/secrets.toml.example)."
        )

    pid = ordem[0]
    creds = obter_credenciais_provedor(pid)
    if not creds:
        raise ConfigErro(f"Não foi possível carregar as credenciais do provedor '{pid}'.")

    # Modelo: preferência da UI > secret/env > padrão do provedor
    modelo_principal = modelo_preferido or creds["modelo"]
    fallbacks_raw = obter_segredo("LLM_FALLBACKS", "")
    modelos = tuple(dict.fromkeys([modelo_principal]))  # sem repetidos

    arquivo = Path(obter_segredo("AGENTS_FILE", "agents.md"))
    if not arquivo.is_absolute():
        arquivo = RAIZ / arquivo

    return ConfigLLM(
        provedor=pid,
        nome=creds["nome"],
        base_url=creds["base_url"] or "",
        api_key=creds["api_key"],
        modelos=modelos,
        temperatura=_numero("LLM_TEMPERATURE", 0.3, 0.0, 2.0),
        timeout=_numero("LLM_TIMEOUT", 60.0, 5.0, 600.0),
        arquivo_instrucoes=arquivo,
    )
