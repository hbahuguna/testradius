"""Model provider abstraction (E2-S1).

The cell is model-agnostic: the planner and executor only see the ``Provider``
protocol. Tests use ``FakeProvider``; the live adapters are thin HTTP clients.
API keys are passed to the adapter, never to logs or events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .types import Completion, ToolCall, Usage

logger = logging.getLogger("cell.agent.provider")


class ProviderError(Exception):
    """Typed provider failure with a stable, non-secret ``kind``."""

    def __init__(self, kind: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


class Provider(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> Completion: ...

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> AsyncIterator[Completion]: ...


@dataclass
class ProviderBudget:
    """Per-run cap shared by all calls to one provider wrapper."""

    max_tokens: int = 0
    max_calls: int = 0
    used_tokens: int = 0
    calls: int = 0

    def reserve_call(self) -> None:
        if self.max_calls and self.calls >= self.max_calls:
            raise ProviderError("budget_exhausted", "provider call budget exhausted")
        self.calls += 1

    def charge(self, usage: Usage) -> None:
        self.used_tokens += usage.total
        if self.max_tokens and self.used_tokens > self.max_tokens:
            raise ProviderError("budget_exhausted", "provider token budget exhausted")


class RetryingProvider:
    """Retry retryable failures with exponential backoff and jitter."""

    def __init__(
        self,
        delegate: Provider,
        *,
        max_retries: int = 3,
        base_delay: float = 0.05,
        max_delay: float = 1.0,
        budget: ProviderBudget | None = None,
    ):
        self._delegate = delegate
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._budget = budget or ProviderBudget()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> Completion:
        last: ProviderError | None = None
        for attempt in range(self._max_retries + 1):
            self._budget.reserve_call()
            try:
                completion = await self._delegate.complete(
                    messages, tools=tools, max_tokens=max_tokens
                )
            except ProviderError as exc:
                last = exc
                if not exc.retryable or attempt >= self._max_retries:
                    raise
                delay = min(self._max_delay, self._base_delay * (2**attempt))
                await asyncio.sleep(delay + random.uniform(0, delay / 2))
                continue
            self._budget.charge(completion.usage)
            return completion
        raise last or ProviderError("provider_failed", "provider failed")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> AsyncIterator[Completion]:
        """Stream chunks, retrying only when no chunk has been yielded yet."""

        last: ProviderError | None = None
        for attempt in range(self._max_retries + 1):
            self._budget.reserve_call()
            yielded = False
            usage = Usage()
            try:
                async for chunk in self._delegate.stream(
                    messages, tools=tools, max_tokens=max_tokens
                ):
                    if chunk.usage.total:
                        usage = chunk.usage
                    yielded = True
                    yield chunk
                self._budget.charge(usage)
                return
            except ProviderError as exc:
                last = exc
                if yielded or not exc.retryable or attempt >= self._max_retries:
                    raise
                delay = min(self._max_delay, self._base_delay * (2**attempt))
                await asyncio.sleep(delay + random.uniform(0, delay / 2))
        raise last or ProviderError("provider_failed", "provider failed")


class FakeProvider:
    """Deterministic provider used by agent tests and offline demos."""

    def __init__(
        self,
        responses: list[Completion] | None = None,
        *,
        default: Completion | None = None,
    ):
        self._responses = list(responses or [])
        self._default = default or Completion(text="")
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> Completion:
        self.calls.append({"messages": messages, "tools": tools, "max_tokens": max_tokens})
        if self._responses:
            return self._responses.pop(0)
        return self._default

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> AsyncIterator[Completion]:
        yield await self.complete(messages, tools=tools, max_tokens=max_tokens)


class AnthropicProvider:
    """Anthropic Messages API adapter."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "claude-3-5-sonnet-latest",
        base_url: str = "https://api.anthropic.com",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> Completion:
        system_parts = [
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        ]
        request_messages = [message for message in messages if message.get("role") != "system"]
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": request_messages,
        }
        if system_parts:
            body["system"] = "\n".join(system_parts)
        if tools:
            body["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", {"type": "object"}),
                }
                for tool in tools
            ]

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "provider timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("transport", "provider transport failed", retryable=True) from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError("rate_limited", "provider unavailable", retryable=True)
        if response.status_code >= 400:
            raise ProviderError("bad_request", "provider rejected the request")

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("invalid_response", "provider returned invalid JSON") from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        tool=str(block.get("name", "")),
                        arguments=block.get("input") or {},
                    )
                )
        usage = data.get("usage") or {}
        return Completion(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> AsyncIterator[Completion]:
        """Yield text deltas from the Messages streaming API.

        The planner uses ``complete`` because it needs the whole JSON plan. This
        method exists for streaming-aware consumers and yields a final usage-only
        completion when the provider reports token counts.
        """

        system_parts = [
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        ]
        request_messages = [message for message in messages if message.get("role") != "system"]
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": request_messages,
            "stream": True,
        }
        if system_parts:
            body["system"] = "\n".join(system_parts)
        if tools:
            body["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", {"type": "object"}),
                }
                for tool in tools
            ]

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=body,
                ) as response:
                    _raise_status(response.status_code)
                    usage = Usage()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload:
                            continue
                        try:
                            event = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        kind = event.get("type")
                        if kind == "message_start":
                            raw = (event.get("message") or {}).get("usage") or {}
                            usage = Usage(
                                input_tokens=int(raw.get("input_tokens", 0)),
                                output_tokens=usage.output_tokens,
                            )
                        elif kind == "content_block_delta":
                            delta = event.get("delta") or {}
                            if delta.get("type") == "text_delta" and delta.get("text"):
                                yield Completion(text=str(delta["text"]))
                        elif kind == "message_delta":
                            raw = event.get("usage") or {}
                            usage = Usage(
                                input_tokens=usage.input_tokens,
                                output_tokens=int(raw.get("output_tokens", usage.output_tokens)),
                            )
                    if usage.total:
                        yield Completion(usage=usage)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "provider timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("transport", "provider transport failed", retryable=True) from exc


class OpenAICompatibleProvider:
    """OpenAI-compatible chat-completions adapter."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> Completion:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {"type": "object"}),
                    },
                }
                for tool in tools
            ]

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "authorization": f"Bearer {self._api_key}",
                        "content-type": "application/json",
                    },
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "provider timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("transport", "provider transport failed", retryable=True) from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError("rate_limited", "provider unavailable", retryable=True)
        if response.status_code >= 400:
            raise ProviderError("bad_request", "provider rejected the request")

        try:
            data = response.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("invalid_response", "provider returned invalid JSON") from exc

        tool_calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw_args = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError as exc:
                raise ProviderError("invalid_response", "tool arguments are not JSON") from exc
            tool_calls.append(ToolCall(tool=str(function.get("name", "")), arguments=arguments))

        usage = data.get("usage") or {}
        return Completion(
            text=str(message.get("content") or ""),
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
            ),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> AsyncIterator[Completion]:
        """Yield text deltas from an OpenAI-compatible streaming response."""

        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {"type": "object"}),
                    },
                }
                for tool in tools
            ]

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    headers={
                        "authorization": f"Bearer {self._api_key}",
                        "content-type": "application/json",
                    },
                    json=body,
                ) as response:
                    _raise_status(response.status_code)
                    usage = Usage()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload:
                            continue
                        if payload == "[DONE]":
                            break
                        try:
                            event = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        raw_usage = event.get("usage") or {}
                        if raw_usage:
                            usage = Usage(
                                input_tokens=int(raw_usage.get("prompt_tokens", 0)),
                                output_tokens=int(raw_usage.get("completion_tokens", 0)),
                            )
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        text = delta.get("content")
                        if text:
                            yield Completion(text=str(text))
                    if usage.total:
                        yield Completion(usage=usage)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "provider timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("transport", "provider transport failed", retryable=True) from exc


def _raise_status(status_code: int) -> None:
    if status_code == 429 or status_code >= 500:
        raise ProviderError("rate_limited", "provider unavailable", retryable=True)
    if status_code >= 400:
        raise ProviderError("bad_request", "provider rejected the request")


def build_provider(
    name: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    max_retries: int = 3,
    budget: ProviderBudget | None = None,
) -> Provider:
    """Construct a provider from policy without logging any credential."""

    normalized = (name or "fake").lower()
    logger.info("provider_selected provider=%s", normalized)
    if normalized == "fake":
        return FakeProvider()
    if not api_key:
        raise ProviderError("missing_credential", "provider credential is not configured")
    if normalized == "anthropic":
        delegate: Provider = AnthropicProvider(
            api_key,
            model=model or "claude-3-5-sonnet-latest",
            base_url=base_url or "https://api.anthropic.com",
        )
    elif normalized in {"openai", "openai-compatible", "openai_compatible"}:
        delegate = OpenAICompatibleProvider(
            api_key,
            model=model or "gpt-4o-mini",
            base_url=base_url or "https://api.openai.com/v1",
        )
    else:
        raise ProviderError("unknown_provider", f"unknown provider: {name}")
    return RetryingProvider(delegate, max_retries=max_retries, budget=budget)
