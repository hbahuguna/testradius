# sdet_agent/reasoning/llm_factory.py
from __future__ import annotations
import logging
from typing import Any, Callable, List, Tuple, Type, Optional
from dataclasses import dataclass

from .qwen_client import QwenClient
from .hy3_client import Hy3Client # Import Hy3Client
from .byok_client import ByokAuthError, ByokError

logger = logging.getLogger("sdet_agent.llm_factory")

_ERROR_PREFIXES = ("[Qwen error", "[Hy3 error", "[Byok error", "[Byok auth error", "[Byok ")


def _is_error_text(text: str) -> bool:
    """True when ``text`` is an error sentinel rather than a real LLM response."""
    return any(text.startswith(p) for p in _ERROR_PREFIXES)


@dataclass
class LLMClientConfig:
    name: str
    client_class: Type[Any] # Type[QwenClient] or Type[Hy3Client]
    api_url: Optional[str] = None

class LLMFactory:
    def __init__(self, client_configs: List[LLMClientConfig]):
        self.clients = []
        self.last_error: Optional[str] = None
        for config in client_configs:
            try:
                client_instance = config.client_class(api_url=config.api_url)
                # Test health if possible
                if hasattr(client_instance, 'health'):
                    if client_instance.health():
                        self.clients.append((config.name, client_instance))
                        logger.info(f"Initialized LLM client: {config.name}")
                    else:
                        logger.debug(f"LLM client {config.name} is unavailable, skipping.")
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
        """Attempts inference with the first healthy LLM that succeeds.

        Iterates through every healthy client (in configured order) and returns
        as soon as one returns a non-error response, so a failing primary (e.g.
        an unreachable Qwen endpoint) does not block a working secondary (e.g.
        hy3-free on OpenCode Zen). Returns (None, "") only if all fail.
        """
        for name, client in self.clients:
            if hasattr(client, "health") and not client.health():
                continue
            # A BYOK auth/key error is fatal — never retry or fall through to
            # another client (there is none in BYOK mode), and let it bubble up.
            try:
                # Retry once on transient errors (e.g. endpoint read timeouts),
                # so a single blip does not abort the whole agentic run.
                for attempt in range(2):
                    response = client.infer(prompt, max_tokens, temperature)
                    if response and not _is_error_text(response):
                        return name, response
                    self.last_error = f"{name}: {response[:300]}"
                    logger.warning(f"LLM {name} returned an error (attempt {attempt + 1}): {response[:120]}")
            except (ByokAuthError, ByokError):
                raise
        return None, "" # No healthy LLM or all inference failed

    def stream_infer(
        self,
        prompt: str,
        on_delta: Callable[[str, str], None],
        max_tokens: int = 1024,
        temperature: float = 0.3,
        system: Optional[str] = None,
    ) -> Tuple[Optional[str], str]:
        """Streams inference from the first healthy LLM that succeeds.

        ``on_delta(kind, text)`` is called per chunk (kind = "reasoning"|"content").
        Iterates through every healthy client (in configured order) so a failing
        primary does not block a working secondary. Clients without a
        ``stream_infer`` method fall back to a single content delta built from
        their non-streaming ``infer``. Returns (llm_name, full_text).
        """
        for name, client in self.clients:
            if hasattr(client, "health") and not client.health():
                continue
            if hasattr(client, "stream_infer"):
                try:
                    full = client.stream_infer(
                        prompt, on_delta, max_tokens, temperature, system=system
                    )
                except (ByokAuthError, ByokError):
                    raise
                if full and not _is_error_text(full):
                    return name, full
                logger.warning(f"LLM {name} stream returned an error: {full[:120]}")
                continue
            # Non-streaming fallback: emit the whole response as one content delta.
            try:
                response = client.infer(prompt, max_tokens, temperature)
            except (ByokAuthError, ByokError):
                raise
            if response and not _is_error_text(response):
                on_delta("content", response)
                return name, response
            logger.warning(f"LLM {name} returned an error: {response[:120]}")
        return None, ""

    def close(self):
        for _, client in self.clients:
            if hasattr(client, 'close'):
                client.close()

    def get_last_error(self) -> Optional[str]:
        """Return the most recent LLM failure detail (for surfacing in results)."""
        return self.last_error
