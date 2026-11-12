"""Configuração da IA — TUDO vem do .env (ou das variáveis de ambiente).
Suporta também override em tempo real via dicionário (para configuração pela UI).

Como funciona "qualquer provedor": quase todos os provedores atuais (Groq, OpenAI,
OpenRouter, Gemini, Anthropic, Mistral, DeepSeek, Together, Ollama, LM Studio...)
expõem o mesmo protocolo "OpenAI-compatível" (`/chat/completions` com function
calling). Então o app fala esse protocolo com o SDK `openai`, apontando para o
`base_url` do provedor escolhido. Se o seu provedor não está na lista abaixo, use
LLM_PROVIDER=custom e informe LLM_BASE_URL.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).parent


class ConfigErro(RuntimeError):
    """Configuração da IA ausente ou inválida (mensagem apresentável)."""


# nome -> (rótulo, base_url, variável da chave, exige chave?, modelos sugeridos)
PROVEDORES: dict[str, dict] = {
    "groq": dict(
        nome="Groq",
        base_url="https://api.groq.com/openai/v1",
        chave_env="GROQ_API_KEY",
        exige_chave=True,
        modelos=["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        modelos_sugeridos=[
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
    ),
    "openai": dict(
        nome="OpenAI",
        base_url="https://api.openai.com/v1",
        chave_env="OPENAI_API_KEY",
        exige_chave=True,
        modelos=[],
        modelos_sugeridos=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1-mini"],
    ),
    "openrouter": dict(
        nome="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        chave_env="OPENROUTER_API_KEY",
        exige_chave=True,
        modelos=[],
        modelos_sugeridos=[
            "openai/gpt-4o",
            "google/gemini-flash-1.5",
            "meta-llama/llama-3.3-70b-instruct",
            "anthropic/claude-3.5-sonnet",
        ],
    ),
    "gemini": dict(
        nome="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        chave_env="GEMINI_API_KEY",
        exige_chave=True,
        modelos=[],
        modelos_sugeridos=["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    ),
    "anthropic": dict(
        nome="Anthropic",
        base_url="https://api.anthropic.com/v1/",
        chave_env="ANTHROPIC_API_KEY",
        exige_chave=True,
        modelos=[],
        modelos_sugeridos=[
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-haiku-20240307",
        ],
    ),
    "mistral": dict(
        nome="Mistral",
        base_url="https://api.mistral.ai/v1",
        chave_env="MISTRAL_API_KEY",
        exige_chave=True,
        modelos=[],
        modelos_sugeridos=["mistral-large-latest", "mistral-small-latest", "open-mixtral-8x22b"],
    ),
    "deepseek": dict(
        nome="DeepSeek",
        base_url="https://api.deepseek.com",
        chave_env="DEEPSEEK_API_KEY",
        exige_chave=True,
        modelos=[],
        modelos_sugeridos=["deepseek-chat", "deepseek-reasoner"],
    ),
    "together": dict(
        nome="Together AI",
        base_url="https://api.together.xyz/v1",
        chave_env="TOGETHER_API_KEY",
        exige_chave=True,
        modelos=[],
        modelos_sugeridos=[
            "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
            "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
            "mistralai/Mixtral-8x7B-Instruct-v0.1",
        ],
    ),
    "ollama": dict(
        nome="Ollama (local)",
        base_url="http://localhost:11434/v1",
        chave_env="",
        exige_chave=False,
        modelos=[],
        modelos_sugeridos=["llama3.3", "qwen2.5", "gemma3", "mistral", "phi4"],
    ),
    "lmstudio": dict(
        nome="LM Studio (local)",
        base_url="http://localhost:1234/v1",
        chave_env="",
        exige_chave=False,
        modelos=[],
        modelos_sugeridos=["(use o nome do modelo carregado no LM Studio)"],
    ),
    "custom": dict(
        nome="Provedor personalizado",
        base_url="",
        chave_env="",
        exige_chave=False,
        modelos=[],
        modelos_sugeridos=[],
    ),
}


@dataclass(frozen=True)
class ConfigLLM:
    provedor: str
    nome: str
    base_url: str
    api_key: str = field(repr=False)  # nunca aparece em logs/prints
    modelos: tuple[str, ...]          # [principal, fallback1, fallback2, ...]
    temperatura: float
    timeout: float
    arquivo_instrucoes: Path

    @property
    def descricao(self) -> str:
        return f"{self.nome} • {self.modelos[0]}"

    def assinatura(self) -> int:
        """Muda quando qualquer parte da configuração muda (para recriar o agente)."""
        return hash((self.provedor, self.base_url, self.api_key, self.modelos,
                     self.temperatura, self.timeout, str(self.arquivo_instrucoes)))

    def instrucoes_mtime(self) -> int:
        """Data de modificação do agents.md: editar o arquivo recria o agente."""
        try:
            return self.arquivo_instrucoes.stat().st_mtime_ns
        except OSError:
            return 0


def _env(nome: str, padrao: str = "") -> str:
    valor = os.getenv(nome, "")
    return valor.strip().strip("\"'").strip() or padrao


def _numero(nome: str, padrao: float, minimo: float, maximo: float) -> float:
    bruto = _env(nome)
    if not bruto:
        return padrao
    try:
        valor = float(bruto.replace(",", "."))
    except ValueError:
        raise ConfigErro(f"{nome}='{bruto}' não é um número válido.") from None
    if not minimo <= valor <= maximo:
        raise ConfigErro(f"{nome} deve estar entre {minimo:g} e {maximo:g}.")
    return valor


def carregar_config(override: dict | None = None) -> ConfigLLM:
    """Lê o .env e devolve a configuração da IA ou levanta ConfigErro.

    Args:
        override: dicionário com valores que sobrescrevem o .env (usado pela UI).
                  Chaves aceitas: provedor, modelo, api_key, base_url, temperatura, timeout.
    """
    ov = override or {}

    provedor = ov.get("provedor") or _env("LLM_PROVIDER", "groq")
    provedor = provedor.lower().strip()
    preset = PROVEDORES.get(provedor)
    if preset is None:
        raise ConfigErro(
            f"LLM_PROVIDER='{provedor}' não é reconhecido. Use um de: "
            f"{', '.join(PROVEDORES)}."
        )

    base_url = ov.get("base_url") or _env("LLM_BASE_URL", preset["base_url"])
    if not base_url:
        raise ConfigErro("Com LLM_PROVIDER=custom, defina também LLM_BASE_URL "
                         "(ex.: https://meu-provedor.com/v1).")

    api_key = (ov.get("api_key") or _env("LLM_API_KEY")
               or (_env(preset["chave_env"]) if preset["chave_env"] else ""))
    if not api_key:
        if preset["exige_chave"]:
            raise ConfigErro(
                f"Chave de API não encontrada. Defina {preset['chave_env']} "
                "(ou LLM_API_KEY) no arquivo .env ou na barra lateral."
            )
        api_key = "sem-chave"  # servidores locais ignoram, mas o SDK exige um texto

    principal = ov.get("modelo") or _env("LLM_MODEL")
    fallbacks_env = _env("LLM_FALLBACK_MODELS")
    if fallbacks_env:
        fallbacks = [m.strip() for m in fallbacks_env.split(",") if m.strip()]
    else:
        fallbacks = [] if principal else list(preset["modelos"][1:])
    modelos = [principal] if principal else list(preset["modelos"][:1])
    if not modelos:
        raise ConfigErro(f"Defina LLM_MODEL no .env ou selecione um modelo na barra lateral.")
    modelos = tuple(dict.fromkeys(modelos + fallbacks))  # sem repetidos, mantém a ordem

    arquivo = Path(_env("AGENTS_FILE", "agents.md"))
    if not arquivo.is_absolute():
        arquivo = RAIZ / arquivo

    return ConfigLLM(
        provedor=provedor,
        nome=preset["nome"],
        base_url=base_url,
        api_key=api_key,
        modelos=modelos,
        temperatura=float(ov.get("temperatura", _numero("LLM_TEMPERATURE", 0.3, 0.0, 2.0))),
        timeout=float(ov.get("timeout", _numero("LLM_TIMEOUT", 60.0, 5.0, 600.0))),
        arquivo_instrucoes=arquivo,
    )
