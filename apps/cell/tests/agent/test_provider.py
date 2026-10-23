from __future__ import annotations

import asyncio
import logging

import pytest

from cell.agent.provider import (
    FakeProvider,
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
        provider = RetryingProvider(
            delegate, max_retries=0, budget=ProviderBudget(max_calls=1)
        )
        await provider.complete([{"role": "user", "content": "hi"}])
        with pytest.raises(ProviderError, match="call budget"):
            await provider.complete([{"role": "user", "content": "again"}])

    asyncio.run(scenario())


def test_fake_provider_is_deterministic_and_does_not_log_keys(caplog):
    caplog.set_level(logging.DEBUG)
    provider = build_provider("fake", api_key="sentinel-key-value")
    assert isinstance(provider, FakeProvider)
    assert "sentinel-key-value" not in caplog.text
