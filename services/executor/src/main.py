from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import Optional
from uuid import UUID
from testsquad_shared.api import ExecutionRequest, ExecutionStatusResponse, TaskStatus
from testsquad_shared.logging_config import setup_logging
from testsquad_executor.sandbox.manager import SandboxManager

app = FastAPI(title="TestSquad Executor", version="0.1.0")
setup_logging(app)

def get_sandbox():
    return SandboxManager()

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "executor"}

@app.post("/execute", response_model=ExecutionStatusResponse)
async def execute_task(request: ExecutionRequest, sandbox: SandboxManager = Depends(get_sandbox)):
    """
    Start a new isolated test run.
    """
    return await sandbox.create_run(request)

@app.get("/run/{run_id}", response_model=ExecutionStatusResponse)
async def get_run_status(run_id: UUID, sandbox: SandboxManager = Depends(get_sandbox)):
    """
    Get the current status of a run.
    """
    try:
        return sandbox.get_run_status(run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/run/{run_id}/stream")
async def stream_run_logs(run_id: UUID, sandbox: SandboxManager = Depends(get_sandbox)):
    """
    Stream logs for a specific run via SSE.
    """
    return StreamingResponse(
        sandbox.stream_logs(run_id),
        media_type="text/event-stream"
    )

@app.delete("/run/{run_id}")
async def abort_run(run_id: UUID, sandbox: SandboxManager = Depends(get_sandbox)):
    """
    Terminate and cleanup a run.
    """
    sandbox.cleanup_run(run_id)
    return {"status": "aborted", "run_id": run_id}
