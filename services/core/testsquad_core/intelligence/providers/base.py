from abc import ABC, abstractmethod
from typing import List, Optional
from testsquad_shared.models import LLMRequest, LLMResponse, LLMModelInfo

class BaseProvider(ABC):
    def __init__(self, api_key: str):
        self.api_key = api_key

    @abstractmethod
    async def list_models(self) -> List[LLMModelInfo]:
        """List all models supported by this provider."""
        pass

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute a completion request."""
        pass
