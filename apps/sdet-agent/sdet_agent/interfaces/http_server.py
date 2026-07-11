"""HTTP interface (textbook Ch.3: expose the agent as a service).

FastAPI app with:
  POST /v1/generate   -> run the agent, return generated code + trace
  GET  /health        -> liveness
  WS   /v1/stream     -> stream node-by-node progress (observability)

Run:  uvicorn sdet_agent.interfaces.http_server:app --port 8000
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core.agent import Agent
from ..core.multiagent import MultiAgentOrchestrator
from ..core.tracer import Tracer
from ..tools import build_registry

logger = logging.getLogger("sdet_agent.http")
app = FastAPI(title="SDET Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    url: str
    scenario: str
    session_id: str = ""
    use_qwen: bool = True
    multi_agent: bool = False


class GenerateResponse(BaseModel):
    success: bool
    generated_code: str
    final_node: str
    trace_summary: dict[str, Any]
    error: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "sdet-agent"}


@app.post("/v1/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    tracer = Tracer(enabled=False)
    if req.multi_agent:
        orch = MultiAgentOrchestrator(tracer=tracer)
        r = orch.run(req.url, req.scenario, req.session_id)
        return GenerateResponse(
            success=r["success"],
            generated_code=r["generated_code"],
            final_node=r["final_node"],
            trace_summary=r["trace_summary"],
            error=r.get("error"),
        )
    agent = Agent(tracer=tracer, use_qwen=req.use_qwen)
    res = agent.run(req.url, req.scenario, req.session_id)
    return GenerateResponse(
        success=res.success,
        generated_code=res.generated_code,
        final_node=res.final_node,
        trace_summary=res.trace_summary,
        error=res.error,
    )


@app.websocket("/v1/stream")
async def stream(websocket: WebSocket) -> None:
    """Stream agent node progress over WebSocket (live observability)."""
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        url = data.get("url", "")
        scenario = data.get("scenario", "")
        use_qwen = data.get("use_qwen", True)

        tracer = Tracer(enabled=True)
        agent = Agent(tracer=tracer, use_qwen=use_qwen)
        # Monkeypatch span finish to stream each completed step
        orig_finish = tracer.finish

        def _streaming_finish(span, output=None, **meta):
            orig_finish(span, output, **meta)
            try:
                websocket.send_json(
                    {"event": "span", "name": span.name, "kind": span.kind,
                     "duration_ms": span.duration_ms, "output": str(span.output)[:300]}
                )
            except Exception:  # noqa: BLE001
                pass

        tracer.finish = _streaming_finish  # type: ignore[assignment]
        res = agent.run(url, scenario, data.get("session_id", ""))
        await websocket.send_json(
            {"event": "done", "success": res.success, "generated_code": res.generated_code}
        )
    except Exception as exc:  # noqa: BLE001
        await websocket.send_json({"event": "error", "message": str(exc)})
    finally:
        await websocket.close()


@app.get("/v1/tools")
def list_tools() -> dict[str, Any]:
    """Expose the tool registry (same surface as MCP tools/list)."""
    reg = build_registry()
    return {"tools": [t.to_mcp() for t in reg.list_specs()]}
