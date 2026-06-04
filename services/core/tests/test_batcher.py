import pytest
from testsquad_shared.models import LLMRequest, ProviderConfig
from testsquad_core.intelligence.batcher import SymbolBatcher
from testsquad_core.intelligence.registry import llm_registry
from testsquad_core.intelligence.providers.mock import MockProvider

@pytest.fixture(autouse=True)
def setup_registry():
    llm_registry.register_provider_class("Mock", MockProvider)
    llm_registry.add_provider(ProviderConfig(provider_name="Mock", api_key="test"))

@pytest.mark.anyio
async def test_symbol_batcher_parallel():
    batcher = SymbolBatcher(batch_size=2)
    requests = [
        LLMRequest(prompt=f"Symbol {i}", provider_name="Mock", model_name="model")
        for i in range(5)
    ]
    
    results = await batcher.process_parallel(requests)
    
    assert len(results) == 5
    assert results[0].content == "Mock response for Symbol 0"
    assert results[4].content == "Mock response for Symbol 4"
