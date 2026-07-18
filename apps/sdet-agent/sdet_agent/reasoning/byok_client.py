# sdet_agent/reasoning/byok_client.py
from __future__ import annotations

import json
import logging
from typing import Callable, Optional

import httpx

logger = logging.getLogger("sdet_agent.byok_client")


class ByokError(Exception):
    """Raised when a BYOK provider call fails in a way the agent must not
    silently swallow (e.g. an invalid API key)."""


class ByokAuthError(ByokError):
    """Raised specifically for 401/403 — the user's API key is invalid."""


PROVIDER_ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
}

# Default models per provider (override via model= if needed).
# NOTE: gemini-1.5-flash was retired by Google and now 404s on the
# OpenAI-compatible endpoint; 2.5-flash is the current stable default.
PROVIDER_DEFAULT_MODEL = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "google": "gemini-2.5-flash",
}


class ByokClient:
    """BYOK (bring-your-own-key) LLM client.

    Routes to the user's own provider using an OpenAI-compatible chat
    completions endpoint. Supports OpenAI, Anthropic, and Google. No credits
    are charged by TestRadius when a user supplies their own key.
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: Optional[str] = None,
        api_url: Optional[str] = None,
        timeout: int = 150,
    ):
        self.provider = provider
        self.model = model or PROVIDER_DEFAULT_MODEL.get(provider, "gpt-4o-mini")
        base = api_url or PROVIDER_ENDPOINTS.get(provider)
        if not base:
            raise ValueError(f"Unknown BYOK provider: {provider}")
        self.base_url = base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        headers = {"Authorization": f"Bearer {api_key}"}
        if provider == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
        self._client = httpx.Client(timeout=timeout, headers=headers)
        logger.info("ByokClient initialized for provider=%s model=%s", provider, self.model)

    def infer(self, prompt: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
        if not self.api_key:
            raise ByokError(f"no API key for {self.provider}")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        try:
            resp = self._client.post(f"{self.base_url}/chat/completions", json=payload)
            if resp.status_code in (401, 403):
                raise ByokAuthError(
                    f"{self.provider} rejected the API key (HTTP {resp.status_code}). "
                    "Check the key in Settings."
                )
            if resp.status_code != 200:
                raise ByokError(
                    f"{self.provider} API returned HTTP {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()
            try:
                message = data["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as e:
                return f"[Byok error: unexpected {self.provider} response shape: {e} | {str(data)[:300]}]"
            content = message.get("content")
            if content is None:
                return f"[Byok error: {self.provider} returned null content]"
            return content
        except (ByokAuthError, ByokError):
            raise
        except httpx.HTTPError as e:
            return f"[Byok error: request to {self.provider} failed: {e}]"
        except Exception as e:  # noqa: BLE001
            return f"[Byok unexpected error during inference: {e}]"

    def health(self) -> bool:
        return bool(self.api_key)

    def stream_infer(
        self,
        prompt: str,
        on_delta: Callable[[str, str], None],
        max_tokens: int = 1024,
        temperature: float = 0.3,
        system: Optional[str] = None,
    ) -> str:
        if not self.api_key:
            on_delta("reasoning", f"[Byok error: no API key for {self.provider}]")
            return ""
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        try:
            with self._client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as resp:
                if resp.status_code in (401, 403):
                    try:
                        resp.read()
                    except Exception:
                        pass
                    on_delta(
                        "reasoning",
                        f"[Byok error: {self.provider} rejected the API key (HTTP {resp.status_code})]",
                    )
                    raise ByokAuthError(
                        f"{self.provider} rejected the API key (HTTP {resp.status_code}). "
                        "Check the key in Settings."
                    )
                if resp.status_code != 200:
                    try:
                        resp.read()
                        body = resp.text
                    except Exception:
                        body = ""
                    on_delta("reasoning", f"[Byok error: {self.provider} API returned HTTP {resp.status_code}: {body[:400]}]")
                    raise ByokError(
                        f"{self.provider} API returned HTTP {resp.status_code}: {body[:400]}"
                    )
                full: list[str] = []
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        on_delta("content", content)
                        full.append(content)
                return "".join(full)
        except (ByokAuthError, ByokError):
            raise
        except httpx.HTTPError as e:
            on_delta("reasoning", f"[Byok error: request to {self.provider} failed: {e}]")
            raise ByokError(f"request to {self.provider} failed: {e}")
        except Exception as e:  # noqa: BLE001
            on_delta("reasoning", f"[Byok unexpected error during streaming: {e}]")
            raise ByokError(f"unexpected error during streaming: {e}")

    def close(self) -> None:
        self._client.close()
