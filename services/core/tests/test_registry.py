import pytest
from testsquad_shared.models import ProviderConfig, LLMRequest
from testsquad_core.intelligence.registry import LLMRegistry
from testsquad_core.intelligence.providers.mock import MockProvider

@pytest.mark.anyio
async def test_llm_registry_hierarchy():
    registry = LLMRegistry()
    registry.register_provider_class("Mock", MockProvider)
    
    # 1. Add Provider
    config = ProviderConfig(provider_name="Mock", api_key="sk-mock-123")
    registry.add_provider(config)
    
    # 2. List Providers
    assert "Mock" in registry.list_providers()
    
    # 3. List Models
    models = await registry.list_models("Mock")
    assert len(models) == 2
    assert models[0].name == "mock-model-1"
    
    # 4. Execute Completion
    request = LLMRequest(
        prompt="Hello World",
        provider_name="Mock",
        model_name="mock-model-1"
    )
    client = registry.get_client("Mock")
    response = await client.complete(request)
    
    assert response.content == "Mock response for Hello World"
    assert response.provider_name == "Mock"
