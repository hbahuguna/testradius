from typing import List
from testsquad_shared.models import LLMRequest, LLMResponse, LLMModelInfo
from testsquad_core.intelligence.providers.base import BaseProvider

class MockProvider(BaseProvider):
    async def list_models(self) -> List[LLMModelInfo]:
        return [
            LLMModelInfo(name="mock-model-1", description="First mock model"),
            LLMModelInfo(name="mock-model-2", description="Second mock model")
        ]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=f"Mock response for {request.prompt}",
            model_name=request.model_name,
            provider_name=request.provider_name,
            token_usage={"total": 42}
        )
