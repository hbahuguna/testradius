# sdet_agent/reasoning/hy3_client.py
from __future__ import annotations

import json
import logging
import os
from typing import Callable, Optional

import httpx

logger = logging.getLogger("sdet_agent.hy3_client")

# opencode/hy3-free is served by OpenCode Zen, an OpenAI-compatible endpoint.
# Docs: base URL https://opencode.ai/zen/v1, auth via OPENCODE_API_KEY.
ZEN_DEFAULT_BASE_URL = "https://opencode.ai/zen/v1"


class Hy3Client:
    """Client for the opencode/hy3-free model via the OpenCode Zen API.

    OpenCode Zen exposes an OpenAI-compatible chat-completions endpoint. This
    client authenticates with ``OPENCODE_API_KEY`` (or ``OPENCODE_ZEN_API_KEY``)
    and calls ``model="hy3-free"``. The key is provided by the user via the
    environment; OpenCode does not manage it for external callers.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: str = "hy3-free",
        timeout: int = 150,
    ):
        self.base_url = (api_url or os.environ.get("OPENCODE_ZEN_BASE_URL") or ZEN_DEFAULT_BASE_URL).rstrip("/")
        self.model = os.environ.get("OPENCODE_MODEL") or model
        self.timeout = timeout
        self.api_key = api_key or os.environ.get("OPENCODE_API_KEY") or os.environ.get("OPENCODE_ZEN_API_KEY")
        self._client = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {self.api_key or ''}"})
        logger.info("Hy3Client initialized for %s via OpenCode Zen (%s).", self.model, self.base_url)

    def infer(self, prompt: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
        """Runs a chat-completions call against OpenCode Zen and returns the text."""
        if not self.api_key:
            return "[Hy3 error: OPENCODE_API_KEY (or OPENCODE_ZEN_API_KEY) is not set. Get one at https://opencode.ai/zen]"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            # hy3-free is a reasoning model that returns the answer in `content`
            # only after completing a (long) chain-of-thought. With thinking
            # enabled, `content` comes back null and the budget is spent on the
            # `reasoning` field, so structured outputs (JSON, code) never appear.
            # Disabling thinking makes `content` the direct answer.
            "enable_thinking": False,
            "stream": False,
        }
        try:
            logger.info("Calling OpenCode Zen %s. Prompt len: %d", self.model, len(prompt))
            resp = self._client.post(f"{self.base_url}/chat/completions", json=payload)
            if resp.status_code != 200:
                return f"[Hy3 error: Zen API returned HTTP {resp.status_code}: {resp.text[:300]}]"
            data = resp.json()
            try:
                message = data["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as e:
                return f"[Hy3 error: unexpected Zen response shape: {e} | {str(data)[:300]}]"
            content = message.get("content")
            if content is None:
                # opencode/hy3-free (tencent/hy3) is a reasoning model: it returns the
                # actual answer in `reasoning` and leaves `content` null for non-trivial
                # prompts. Use reasoning as the model output so downstream code
                # extraction still works (the reasoning contains the fenced code block).
                reasoning = message.get("reasoning")
                if reasoning:
                    return reasoning
                return "[Hy3 error: Zen returned null content and null reasoning]"
            return content
        except httpx.HTTPError as e:
            return f"[Hy3 error: request to OpenCode Zen failed: {e}]"
        except Exception as e:  # noqa: BLE001
            return f"[Hy3 unexpected error during inference: {e}]"

    def health(self) -> bool:
        """Healthy only when an API key is configured."""
        return bool(self.api_key)

    def stream_infer(
        self,
        prompt: str,
        on_delta: Callable[[str, str], None],
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """Streams a chat-completions call, invoking ``on_delta(kind, text)``.

        ``kind`` is ``"reasoning"`` for think tokens or ``"content"`` for answer
        tokens (OpenCode Zen streams reasoning for hy3-free; content may be empty).
        Returns the assembled full text. Errors are surfaced via ``on_delta`` and
        returned as an empty string.
        """
        if not self.api_key:
            on_delta("reasoning", "[Hy3 error: OPENCODE_API_KEY (or OPENCODE_ZEN_API_KEY) is not set. Get one at https://opencode.ai/zen]")
            return ""

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "enable_thinking": False,
            "stream": True,
        }
        try:
            logger.info("Streaming OpenCode Zen %s. Prompt len: %d", self.model, len(prompt))
            with self._client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as resp:
                if resp.status_code != 200:
                    on_delta("reasoning", f"[Hy3 error: Zen API returned HTTP {resp.status_code}: {resp.text[:300]}]")
                    return ""
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
                    reasoning = delta.get("reasoning")
                    if reasoning:
                        on_delta("reasoning", reasoning)
                        full.append(reasoning)
                    content = delta.get("content")
                    if content:
                        on_delta("content", content)
                        full.append(content)
                return "".join(full)
        except httpx.HTTPError as e:
            on_delta("reasoning", f"[Hy3 error: request to OpenCode Zen failed: {e}]")
            return ""
        except Exception as e:  # noqa: BLE001
            on_delta("reasoning", f"[Hy3 unexpected error during streaming: {e}]")
            return ""

    def close(self) -> None:
        self._client.close()
