"""LLM adapter base: provider contract + shared errors.

Adapters are intentionally thin HTTP clients (httpx only — no vendor SDKs) so
the shipped artifact stays small and contains no provider credentials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from ..errors import TiaError


class LLMError(TiaError):
    exit_code = 7


class LLMAuthError(LLMError):
    """401/403 — the user's key was rejected."""


class LLMUnavailableError(LLMError):
    """Provider unreachable (network, 5xx, rate limit)."""


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    usage: Dict[str, Any] = field(default_factory=dict)


class LLMAdapter(ABC):
    provider: str = ""
    default_model: str = ""

    def __init__(self, api_key: str = "", model: str = "", timeout: float = 60.0,
                 client: Optional[httpx.Client] = None):
        self.api_key = api_key
        self.model = model or self.default_model
        self.timeout = timeout
        self._client = client

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """Run one chat completion. messages = [{role, content}, ...]."""

    # -- shared helpers -----------------------------------------------------
    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise LLMAuthError(
                f"{self.provider} rejected your API key (HTTP {resp.status_code}). "
                "Run `tia-agent llm set` to update it."
            )
        if resp.status_code == 429:
            raise LLMUnavailableError(
                f"{self.provider} rate limit reached (HTTP 429). Try again shortly."
            )
        if resp.status_code >= 500:
            raise LLMUnavailableError(f"{self.provider} server error (HTTP {resp.status_code}).")
        if resp.status_code >= 400:
            detail = resp.text[:300]
            raise LLMError(f"{self.provider} request failed (HTTP {resp.status_code}): {detail}")

    @staticmethod
    def _content_of(message: Dict[str, Any]) -> str:
        """Anthropic returns content as a list of blocks; OpenAI as a string."""
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        return str(content)