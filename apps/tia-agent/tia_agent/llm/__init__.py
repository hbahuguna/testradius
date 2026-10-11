"""LLM facade: provider registry, key resolution, one-call chat().

Key resolution order (never stored in config or code):
  1. provider env var (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, ...)
  2. OS keychain / credentials store (see tia_agent.creds)
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..config import TiaConfig
from ..creds import CredentialStore
from .adapters import ADAPTERS
from .base import LLMAdapter, LLMError, LLMResponse, LLMAuthError, LLMUnavailableError

PROVIDERS = tuple(ADAPTERS.keys())
DEFAULT_MODELS = {name: cls.default_model for name, cls in ADAPTERS.items()}

# ollama is local — no key required.
ENV_KEYS: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "ollama": "",
}
GOOGLE_FALLBACK_ENV = "GOOGLE_API_KEY"
_KEY_REQUIRED = {"openai", "anthropic", "google"}


def resolve_api_key(provider: str, store: Optional[CredentialStore] = None) -> str:
    if provider not in ADAPTERS:
        raise LLMError(f"unknown provider '{provider}' (choose from: {', '.join(PROVIDERS)})")
    env_name = ENV_KEYS.get(provider, "")
    if env_name:
        import os

        val = os.environ.get(env_name, "")
        if not val and provider == "google":
            val = os.environ.get(GOOGLE_FALLBACK_ENV, "")
        if val:
            return val
    if provider not in _KEY_REQUIRED:
        return ""
    store = store or CredentialStore()
    return store.get(provider) or ""


def get_adapter(
    config: TiaConfig,
    store: Optional[CredentialStore] = None,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMAdapter:
    provider = provider or config.llm_provider
    if not provider:
        raise LLMError("no LLM provider configured — run `tia-agent llm set`")
    if provider not in ADAPTERS:
        raise LLMError(f"unknown provider '{provider}' (choose from: {', '.join(PROVIDERS)})")
    key = resolve_api_key(provider, store)
    if provider in _KEY_REQUIRED and not key:
        env = ENV_KEYS[provider]
        raise LLMError(
            f"no API key for {provider} — set ${env} or run `tia-agent llm set`"
        )
    return ADAPTERS[provider](api_key=key, model=model or config.llm_model)


def chat(
    config: TiaConfig,
    messages: List[Dict[str, str]],
    store: Optional[CredentialStore] = None,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 60.0,
) -> LLMResponse:
    adapter = get_adapter(config, store, provider=provider, model=model)
    adapter.timeout = timeout
    if adapter._client is not None:
        adapter._client.close()
        adapter._client = None
    return adapter.chat(messages)


def llm_status(config: TiaConfig, store: Optional[CredentialStore] = None) -> Dict[str, object]:
    """Provider/model/key-source summary. Never includes the key itself."""
    import os

    store = store or CredentialStore()
    provider = config.llm_provider
    info: Dict[str, object] = {
        "provider": provider or "(not configured)",
        "model": config.llm_model or (DEFAULT_MODELS.get(provider, "") if provider else ""),
        "key_source": "none",
        "key_present": False,
        "credential_backend": store.backend_name,
    }
    if not provider:
        return info
    env_name = ENV_KEYS.get(provider, "")
    if env_name and os.environ.get(env_name):
        info["key_source"] = f"env:{env_name}"
        info["key_present"] = True
    elif provider == "ollama":
        info["key_source"] = "none (local runtime)"
        info["key_present"] = True
    elif store.get(provider):
        info["key_source"] = store.backend_name
        info["key_present"] = True
    else:
        info["key_source"] = "MISSING"
    return info


__all__ = [
    "PROVIDERS",
    "DEFAULT_MODELS",
    "LLMAdapter",
    "LLMError",
    "LLMAuthError",
    "LLMResponse",
    "LLMUnavailableError",
    "chat",
    "get_adapter",
    "llm_status",
    "resolve_api_key",
]