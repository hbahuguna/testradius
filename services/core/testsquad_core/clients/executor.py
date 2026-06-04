import httpx
import json
from typing import AsyncGenerator, Optional
from uuid import UUID
from testsquad_shared.api import ExecutionRequest, ExecutionStatusResponse

class ExecutorClient:
    def __init__(self, base_url: str = "http://executor:8001"):
        self.base_url = base_url
        self._timeout = httpx.Timeout(60.0)

    async def execute_task(self, request: ExecutionRequest) -> ExecutionStatusResponse:
        """Trigger a test run on the executor."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout) as client:
            response = await client.post("/execute", json=request.model_dump())
            response.raise_for_status()
            return ExecutionStatusResponse(**response.json())

    async def get_run_status(self, run_id: UUID) -> ExecutionStatusResponse:
        """Fetch the current status of a run."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout) as client:
            response = await client.get(f"/run/{run_id}")
            response.raise_for_status()
            return ExecutionStatusResponse(**response.json())

    async def stream_logs(self, run_id: UUID) -> AsyncGenerator[str, None]:
        """Subscribe to the SSE stream for real-time logs."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=None) as client:
            async with client.stream("GET", f"/run/{run_id}/stream") as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield line[6:]

    async def abort_run(self, run_id: UUID) -> bool:
        """Terminate a running task."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout) as client:
            response = await client.delete(f"/run/{run_id}")
            return response.status_code == 200
