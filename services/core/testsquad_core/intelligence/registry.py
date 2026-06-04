import logging
from typing import Dict, List, Optional, Type
from testsquad_shared.models import ProviderConfig, LLMModelInfo

logger = logging.getLogger(__name__)
from testsquad_core.intelligence.providers.base import BaseProvider

class LLMRegistry:
    def __init__(self):
        self._providers: Dict[str, ProviderConfig] = {}
        self._clients: Dict[str, BaseProvider] = {}
        self._provider_classes: Dict[str, Type[BaseProvider]] = {}

    def register_provider_class(self, provider_name: str, cls: Type[BaseProvider]):
        """Register a class for a provider (e.g., GoogleClient)."""
        self._provider_classes[provider_name] = cls

    def add_provider(self, config: ProviderConfig):
        """Add a configured provider with its API key."""
        self._providers[config.provider_name] = config
        
        # Initialize the client if class is registered
        if config.provider_name in self._provider_classes:
            cls = self._provider_classes[config.provider_name]
            self._clients[config.provider_name] = cls(api_key=config.api_key)

    def get_provider_config(self, provider_name: str) -> Optional[ProviderConfig]:
        return self._providers.get(provider_name)

    def get_client(self, provider_name: str, api_key_override: Optional[str] = None) -> Optional[BaseProvider]:
        if api_key_override:
            if provider_name in self._provider_classes:
                cls = self._provider_classes[provider_name]
                return cls(api_key=api_key_override)
        return self._clients.get(provider_name)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())

    async def list_models(self, provider_name: str) -> List[LLMModelInfo]:
        client = self.get_client(provider_name)
        if not client:
            return []
        return await client.list_models()

# Global Registry Instance
llm_registry = LLMRegistry()

import os
from testsquad_shared.models import ProviderConfig, LLMModelInfo

def initialize_standard_providers():
    """Dynamically register and auto-configure standard providers."""
    # 1. Register Classes
    try:
        from testsquad_core.intelligence.providers.google import GoogleProvider
        llm_registry.register_provider_class("Google", GoogleProvider)
        
        # Auto-configure if GOOGLE_API_KEY is present
        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key:
            llm_registry.add_provider(ProviderConfig(provider_name="Google", api_key=api_key))
            logger.info("Auto-configured Google provider.")
    except ImportError as e:
        logger.warning(f"Google Generative AI support not available (missing dependencies): {e}")

    try:
        from testsquad_core.intelligence.providers.anthropic import AnthropicProvider
        llm_registry.register_provider_class("Anthropic", AnthropicProvider)
        
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            llm_registry.add_provider(ProviderConfig(provider_name="Anthropic", api_key=api_key))
            logger.info("Auto-configured Anthropic provider.")
    except ImportError as e:
        logger.warning(f"Anthropic support not available (missing dependencies): {e}")

    try:
        from testsquad_core.intelligence.providers.cloudflare import CloudflareProvider
        llm_registry.register_provider_class("Cloudflare", CloudflareProvider)

        api_key = os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CLOUDFLARE_AI_TOKEN")
        if api_key and os.getenv("CLOUDFLARE_ACCOUNT_ID"):
            llm_registry.add_provider(ProviderConfig(provider_name="Cloudflare", api_key=api_key))
            logger.info("Auto-configured Cloudflare provider.")
    except ImportError as e:
        logger.warning(f"Cloudflare support not available (missing dependencies): {e}")
