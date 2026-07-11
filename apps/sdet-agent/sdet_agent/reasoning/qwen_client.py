"""Qwen SLM client (standalone mirror of apps/testradius/qwen/client.py).

The fine-tuned Qwen3-8B SDET model is served on Modal. This client is
self-contained so the sdet-agent package runs without the parent app
installed. Override the URL via env var QWEN_SDET_URL or constructor arg.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

DEFAULT_QWEN_URL = "https://hbahuguna--qwen-3-8b-sdet-qwensdet-generate.modal.run"


class QwenClient:
    """HTTP client for the fine-tuned Qwen3-8B SDET model on Modal."""

    def __init__(self, api_url: Optional[str] = None, timeout: int = 120):
        self.api_url = api_url or os.environ.get("QWEN_SDET_URL", DEFAULT_QWEN_URL)
        self._client = httpx.Client(timeout=timeout)

    def infer(self, prompt: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
        try:
            resp = self._client.post(
                f"{self.api_url}/generate",
                json={"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
        except httpx.RequestError as e:
            return f"[Qwen error: {e}]"

    def health(self) -> bool:
        try:
            resp = self._client.get(f"{self.api_url}/health")
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    def close(self) -> None:
        self._client.close()
