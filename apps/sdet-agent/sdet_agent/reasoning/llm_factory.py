# sdet_agent/reasoning/llm_factory.py
from __future__ import annotations
import logging
from typing import Any, Callable, List, Tuple, Type, Optional
from dataclasses import dataclass

from .qwen_client import QwenClient
from .hy3_client import Hy3Client # Import Hy3Client

logger = logging.getLogger("sdet_agent.llm_factory")

@dataclass
class LLMClientConfig:
    name: str
    client_class: Type[Any] # Type[QwenClient] or Type[Hy3Client]
    api_url: Optional[str] = None

class LLMFactory:
    def __init__(self, client_configs: List[LLMClientConfig]):
        self.clients = []
        for config in client_configs:
            try:
                client_instance = config.client_class(api_url=config.api_url)
                # Test health if possible
                if hasattr(client_instance, 'health'):
                    if client_instance.health():
                        self.clients.append((config.name, client_instance))
                        logger.info(f"Initialized LLM client: {config.name}")
                    else:
                        logger.warning(f"LLM client {config.name} is unhealthy, skipping.")
                else:
                    # If client has no health method, assume it's healthy for now
                    self.clients.append((config.name, client_instance))
                    logger.info(f"Initialized LLM client (no health check): {config.name}")
            except Exception as e:
                logger.error(f"Failed to initialize LLM client {config.name}: {e}")
        if not self.clients:
            logger.error("No LLM clients initialized. LLM-backed reasoning will fail.")

    def get_llm(self) -> Tuple[Optional[str], Optional[Any]]:
        """Returns the first healthy LLM client (name, instance) or (None, None)."""
        for name, client in self.clients:
            if hasattr(client, 'health'):
                if not client.health():
                    logger.warning(f"LLM client {name} became unhealthy, skipping.")
                    continue
            return name, client
        return None, None

    def infer(self, prompt: str, max_tokens: int = 1024, temperature: float = 0.3) -> Tuple[Optional[str], str]:
        """Attempts inference with the first healthy LLM, returns (llm_name, response)."""
        llm_name, client = self.get_llm()
        if client:
            response = client.infer(prompt, max_tokens, temperature)
            if response and not (response.startswith("[Qwen error") or response.startswith("[Hy3 error")):
                return llm_name, response
            logger.warning(f"LLM {llm_name} returned an error: {response}")
        return None, "" # No healthy LLM or inference failed

    def stream_infer(
        self,
        prompt: str,
        on_delta: Callable[[str, str], None],
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> Tuple[Optional[str], str]:
        """Streams inference from the first healthy LLM that supports streaming.

        ``on_delta(kind, text)`` is called per token (kind = "reasoning"|"content").
        Clients without a ``stream_infer`` method fall back to a single content
        delta built from their non-streaming ``infer``. Returns (llm_name, full_text).
        """
        llm_name, client = self.get_llm()
        if client and hasattr(client, "stream_infer"):
            full = client.stream_infer(prompt, on_delta, max_tokens, temperature)
            if full and not full.startswith("[Hy3 error") and not full.startswith("[Qwen error"):
                return llm_name, full
            logger.warning(f"LLM {llm_name} stream returned an error: {full[:120]}")
            return None, ""
        if client:
            # Non-streaming fallback: emit the whole response as one content delta.
            response = client.infer(prompt, max_tokens, temperature)
            if response and not (response.startswith("[Qwen error") or response.startswith("[Hy3 error")):
                on_delta("content", response)
                return llm_name, response
            logger.warning(f"LLM {llm_name} returned an error: {response}")
        return None, ""

    def close(self):
        for _, client in self.clients:
            if hasattr(client, 'close'):
                client.close()
