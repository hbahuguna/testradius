from anthropic import AsyncAnthropic
from typing import List
from testsquad_shared.models import LLMRequest, LLMResponse, LLMModelInfo
from testsquad_core.intelligence.providers.base import BaseProvider

class AnthropicProvider(BaseProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = AsyncAnthropic(api_key=self.api_key)

    async def list_models(self) -> List[LLMModelInfo]:
        return [
            LLMModelInfo(name="claude-3-5-sonnet-20240620", description="Anthropic Balanced Model", context_window=200000),
            LLMModelInfo(name="claude-3-opus-20240229", description="Anthropic Flagship Model", context_window=200000)
        ]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await self.client.messages.create(
            model=request.model_name,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            messages=[{"role": "user", "content": request.prompt}]
        )
        
        return LLMResponse(
            content=response.content[0].text,
            model_name=request.model_name,
            provider_name="Anthropic",
            token_usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        )
