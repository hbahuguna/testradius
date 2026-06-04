import asyncio
from typing import List
from testsquad_shared.models import LLMRequest, LLMResponse
from testsquad_core.intelligence.registry import llm_registry

class SymbolBatcher:
    """Orchestrates parallel LLM requests for symbol mapping or analysis."""

    def __init__(self, batch_size: int = 10):
        self.batch_size = batch_size

    async def process_parallel(self, requests: List[LLMRequest]) -> List[LLMResponse]:
        """Split requests into batches and execute in parallel."""
        results = []
        for i in range(0, len(requests), self.batch_size):
            batch = requests[i : i + self.batch_size]
            tasks = [self._execute_single(req) for req in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            results.extend(batch_results)
        return results

    async def _execute_single(self, request: LLMRequest) -> LLMResponse:
        client = llm_registry.get_client(request.provider_name)
        if not client:
            raise ValueError(f"Provider {request.provider_name} not found in repository.")
        return await client.complete(request)
