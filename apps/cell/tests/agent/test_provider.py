from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from cell.agent.provider import (
    AnthropicProvider,
    FakeProvider,
    OpenAICompatibleProvider,
    ProviderBudget,
    ProviderError,
    RetryingProvider,
    build_provider,
)
from cell.agent.types import Completion, Usage


class FlakyProvider:
    def __init__(self, failures: int, retryable: bool = True):
        self.failures = failures
        self.retryable = retryable
        self.calls = 0

    async def complete(self, messages, *, tools=None, max_tokens=1024):
        self.calls += 1
        if self.calls <= self.failures:
            raise ProviderError("rate_limited", "try later", retryable=self.retryable)
        return Completion(text="ok", usage=Usage(input_tokens=3, output_tokens=2))


def test_retry_uses_backoff_and_returns_completion():
    async def scenario():
        delegate = FlakyProvider(failures=2)
        provider = RetryingProvider(delegate, max_retries=3, base_delay=0.001)
        result = await provider.complete([{"role": "user", "content": "hi"}])
        assert result.text == "ok"
        assert delegate.calls == 3
        assert provider._budget.used_tokens == 5

    asyncio.run(scenario())


def test_non_retryable_error_is_not_retried():
    async def scenario():
        delegate = FlakyProvider(failures=1, retryable=False)
        provider = RetryingProvider(delegate, max_retries=3, base_delay=0.001)
        with pytest.raises(ProviderError, match="try later"):
            await provider.complete([{"role": "user", "content": "hi"}])
        assert delegate.calls == 1

    asyncio.run(scenario())


def test_budget_stops_calls_before_dispatch():
    async def scenario():
        delegate = FakeProvider([Completion(text="one"), Completion(text="two")])
        provider = RetryingProvider(delegate, max_retries=0, budget=ProviderBudget(max_calls=1))
        await provider.complete([{"role": "user", "content": "hi"}])
        with pytest.raises(ProviderError, match="call budget"):
            await provider.complete([{"role": "user", "content": "again"}])

    asyncio.run(scenario())


def test_fake_provider_is_deterministic_and_does_not_log_keys(caplog):
    caplog.set_level(logging.DEBUG)
    provider = build_provider("fake", api_key="sentinel-key-value")
    assert isinstance(provider, FakeProvider)
    assert "sentinel-key-value" not in caplog.text


def test_anthropic_provider_accepts_transport_and_omits_key_from_logs(caplog):
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("x-api-key") == "anthro-test-key"
            payload = json.loads(request.content)
            assert payload["max_tokens"] == 256
            assert payload["messages"]
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "hello"}],
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                },
            )

        caplog.set_level(logging.DEBUG)
        provider = AnthropicProvider(
            "anthro-test-key",
            model="claude-test",
            transport=httpx.MockTransport(handler),
        )
        result = await provider.complete([{"role": "user", "content": "hi"}], max_tokens=256)
        assert result.text == "hello"
        assert result.usage.total == 3
        assert "anthro-test-key" not in caplog.text

    asyncio.run(scenario())


def test_openai_provider_parses_tool_calls_without_logging_key(caplog):
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("authorization") == "Bearer openai-test-key"
            payload = json.loads(request.content)
            assert payload["tools"][0]["function"]["name"] == "browser.navigate"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "browser.navigate",
                                            "arguments": '{"url":"http://aut/"}',
                                        }
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                },
            )

        caplog.set_level(logging.DEBUG)
        provider = OpenAICompatibleProvider(
            "openai-test-key",
            model="gpt-test",
            transport=httpx.MockTransport(handler),
        )
        result = await provider.complete(
            [{"role": "user", "content": "hi"}],
            tools=[
                {
                    "name": "browser.navigate",
                    "description": "nav",
                    "input_schema": {"type": "object"},
                }
            ],
        )
        assert result.tool_calls[0].tool == "browser.navigate"
        assert result.tool_calls[0].arguments == {"url": "http://aut/"}
        assert result.usage.total == 3
        assert "openai-test-key" not in caplog.text

    asyncio.run(scenario())


def test_anthropic_stream_yields_text_and_usage():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"type":"message_start","message":{"usage":{"input_tokens":5}}}\n\n'
                'data: {"type":"content_block_delta","delta":{"type":"text_delta",'
                '"text":"hello"}}\n\n'
                'data: {"type":"message_delta","usage":{"output_tokens":3}}\n\n'
            )
            return httpx.Response(200, content=body.encode())

        provider = AnthropicProvider(
            "k",
            transport=httpx.MockTransport(handler),
        )
        chunks = []
        async for chunk in provider.stream([{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
        assert "".join(c.text for c in chunks) == "hello"
        assert chunks[-1].usage.total == 8

    asyncio.run(scenario())


def test_openai_stream_yields_deltas_and_usage():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
                'data: {"usage":{"prompt_tokens":2,"completion_tokens":4}}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, content=body.encode())

        provider = OpenAICompatibleProvider(
            "k",
            transport=httpx.MockTransport(handler),
        )
        chunks = []
        async for chunk in provider.stream([{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
        assert "".join(c.text for c in chunks) == "hi"
        assert chunks[-1].usage.total == 6

    asyncio.run(scenario())
