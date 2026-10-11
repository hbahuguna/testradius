"""Concrete provider adapters: openai / anthropic / google / ollama.

All speak raw HTTP through httpx. Base URLs honor each provider's standard
env overrides (OPENAI_BASE_URL, ANTHROPIC_BASE_URL, OLLAMA_HOST) so users can
point at proxies or local runtimes without code changes.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx

from .base import LLMAdapter, LLMError, LLMUnavailableError, LLMResponse


class OpenAIAdapter(LLMAdapter):
    provider = "openai"
    default_model = "gpt-4o-mini"

    def chat(self, messages: List[Dict[str, str]]) -> LLMResponse:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
        try:
            resp = self.client.post(
                f"{base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages},
            )
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"openai unreachable: {e}") from e
        self._raise_for_status(resp)
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"openai returned unexpected payload: {resp.text[:300]}") from e
        return LLMResponse(text=text, model=data.get("model", self.model), provider=self.provider,
                           usage=data.get("usage", {}))


class AnthropicAdapter(LLMAdapter):
    provider = "anthropic"
    default_model = "claude-sonnet-4-5"

    def chat(self, messages: List[Dict[str, str]]) -> LLMResponse:
        base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        convo = [m for m in messages if m.get("role") in ("user", "assistant")]
        try:
            resp = self.client.post(
                f"{base}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "max_tokens": 4096,
                    "system": "\n\n".join(system_parts) if system_parts else "",
                    "messages": convo,
                },
            )
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"anthropic unreachable: {e}") from e
        self._raise_for_status(resp)
        data = resp.json()
        text = self._content_of({"content": data.get("content", [])})
        return LLMResponse(text=text, model=data.get("model", self.model), provider=self.provider,
                           usage=data.get("usage", {}))


class GoogleAdapter(LLMAdapter):
    provider = "google"
    default_model = "gemini-2.5-flash"

    def chat(self, messages: List[Dict[str, str]]) -> LLMResponse:
        base = os.environ.get(
            "GOOGLE_BASE_URL", "https://generativelanguage.googleapis.com"
        ).rstrip("/")
        contents: List[Dict[str, Any]] = []
        system_parts: List[Dict[str, Any]] = []
        for m in messages:
            role = m.get("role", "user")
            part = {"text": m.get("content", "")}
            if role == "system":
                system_parts.append(part)
            else:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": [part]})
        body: Dict[str, Any] = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {"parts": system_parts}
        try:
            resp = self.client.post(
                f"{base}/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json=body,
            )
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"google unreachable: {e}") from e
        self._raise_for_status(resp)
        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"google returned unexpected payload: {resp.text[:300]}") from e
        return LLMResponse(text=text, model=self.model, provider=self.provider,
                           usage=data.get("usageMetadata", {}))


class OllamaAdapter(LLMAdapter):
    provider = "ollama"
    default_model = "llama3.2"

    def chat(self, messages: List[Dict[str, str]]) -> LLMResponse:
        base = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        try:
            resp = self.client.post(
                f"{base}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
            )
        except httpx.HTTPError as e:
            raise LLMUnavailableError(
                f"ollama unreachable at {base} — is it running? (`ollama serve`)"
            ) from e
        self._raise_for_status(resp)
        data = resp.json()
        text = data.get("message", {}).get("content", "")
        return LLMResponse(text=text, model=data.get("model", self.model), provider=self.provider,
                           usage={
                               "prompt_tokens": data.get("prompt_eval_count", 0),
                               "completion_tokens": data.get("eval_count", 0),
                           })


ADAPTERS = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "google": GoogleAdapter,
    "ollama": OllamaAdapter,
}