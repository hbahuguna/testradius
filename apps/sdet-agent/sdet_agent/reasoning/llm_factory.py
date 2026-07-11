# sdet_agent/reasoning/llm_factory.py
from __future__ import annotations
import logging
from typing import Any, List, Tuple, Type, Optional
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

    def close(self):
        for _, client in self.clients:
            if hasattr(client, 'close'):
                client.close()
