"""The cell's external surface: health + run lifecycle (Sprint 2)."""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .health import is_ready, probe_dependencies
from .models import (
    CreateRunResponse,
    EvidenceListResponse,
    HealthResponse,
    PolicyReloadResponse,
    RunCreateRequest,
    RunResponse,
    RunStatus,
)
from .runs.state import Run
from .runs.tokens import extract_bearer_token

router = APIRouter()


def _auth(request: Request, run_id: str) -> None:
    token = extract_bearer_token(request.headers.get("authorization"))
    if not request.app.state.tokens.validate(token or "", run_id):
        raise HTTPException(status_code=401, detail="unauthorized")


@router.get("/v1/health", response_model=HealthResponse, tags=["contract"])
async def health(request: Request, response: Response) -> HealthResponse:
    settings = request.app.state.settings
    aut, graph = await probe_dependencies(
        request.app.state.probe, settings.aut_health_url, settings.graph_health_url
    )
    ready = is_ready(aut, graph)
    response.status_code = 200 if ready else 503
    return HealthResponse(
        ready=ready,
        aut_status=aut,
        graph_status=graph,
        version=settings.version,
    )


@router.post("/v1/runs", response_model=CreateRunResponse)
async def create_run(request: Request, body: RunCreateRequest) -> CreateRunResponse:
    run_id = f"run_{secrets.token_hex(8)}"
    run = Run(
        run_id=run_id,
        repo=body.repo,
        commit=body.commit,
        scope=body.scope,
        policy=body.policy,
        goal=body.goal,
        status=RunStatus.QUEUED,
    )
    request.app.state.store.create(run)
    request.app.state.policy.load(body.policy)
    run_token, expires_at = request.app.state.tokens.issue(run_id)
    request.app.state.orchestrator.start(run)
    return CreateRunResponse(
        run_id=run_id,
        run_token=run_token,
        expires_at=expires_at.isoformat().replace("+00:00", "Z"),
        status=run.status,
        phase=run.phase,
    )


@router.get("/v1/runs/{run_id}", response_model=RunResponse)
async def get_run(
    request: Request,
    run_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> RunResponse:
    _auth(request, run_id)
    run = request.app.state.store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="not_found")
    return RunResponse(
        run_id=run.run_id,
        status=run.status,
        phase=run.phase,
        created_at=run.created_at,
        updated_at=run.updated_at,
        repo=run.repo,
        commit=run.commit,
        scope=run.scope,
    )


@router.get("/v1/runs/{run_id}/events")
async def stream_events(
    request: Request,
    run_id: str,
    authorization: Annotated[str | None, Header()] = None,
):
    _auth(request, run_id)
    run = request.app.state.store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="not_found")

    async def event_generator():
        orchestrator = request.app.state.orchestrator
        initial = orchestrator.get_events(run_id, 0)
        for event in initial:
            yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"

        last_seq = initial[-1]["seq"] if initial else 0
        for _ in range(3000):
            fresh = orchestrator.get_events(run_id, last_seq)
            for event in fresh:
                last_seq = event["seq"]
                yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
            if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
                break
            await asyncio.sleep(0.01)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/v1/runs/{run_id}/cancel")
async def cancel_run(
    request: Request,
    run_id: str,
    authorization: Annotated[str | None, Header()] = None,
):
    _auth(request, run_id)
    if not request.app.state.store.get(run_id):
        raise HTTPException(status_code=404, detail="not_found")
    cancelled = await request.app.state.orchestrator.cancel(run_id)
    return {"run_id": run_id, "cancelled": cancelled}


@router.get("/v1/runs/{run_id}/evidence", response_model=EvidenceListResponse)
async def list_evidence(
    request: Request,
    run_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> EvidenceListResponse:
    _auth(request, run_id)
    if not request.app.state.store.get(run_id):
        raise HTTPException(status_code=404, detail="not_found")
    return EvidenceListResponse(run_id=run_id, evidence=[])


@router.post("/v1/policy/reload", response_model=PolicyReloadResponse)
async def reload_policy(request: Request) -> PolicyReloadResponse:
    version = request.app.state.policy.reload()
    return PolicyReloadResponse(reloaded=True, version=version)
