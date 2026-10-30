"""FastAPI application wiring the orchestrator API to the UI."""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="TestRadius Harness API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateRunRequest(BaseModel):
    target: str
    goal: str
    context: Optional[str] = None
    model: str = "gemini-2.5-flash-lite"


@dataclass
class RunRecord:
    id: str
    target: str
    goal: str
    context: Optional[str]
    model: str
    status: str = "PLANNING"
    count: int = 0
    evidence: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    approved: bool = False
    plan_id: Optional[str] = None
    live: Dict[str, Any] = field(default_factory=dict)


runs: Dict[str, RunRecord] = {}


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "runs": len(runs)}


@app.get("/api/runs")
async def list_runs() -> List[Dict[str, Any]]:
    items = []
    for r in sorted(runs.values(), key=lambda x: x.created_at, reverse=True):
        items.append({
            "id": r.id,
            "target": r.target,
            "status": r.status,
            "count": r.count,
            "evidence": r.evidence,
            "createdAt": r.created_at,
            "approved": r.approved,
            "planId": r.plan_id,
        })
    return items


@app.post("/api/runs")
async def create_run(req: CreateRunRequest) -> Dict[str, Any]:
    run_id = str(int(datetime.now(timezone.utc).timestamp()))
    record = RunRecord(
        id=run_id,
        target=req.target,
        goal=req.goal,
        context=req.context,
        model=req.model,
        status="PLANNING",
        plan_id="1793353092",
    )
    runs[run_id] = record
    return {
        "id": record.id,
        "target": record.target,
        "status": record.status,
        "count": record.count,
        "evidence": record.evidence,
        "createdAt": record.created_at,
        "approved": record.approved,
        "planId": record.plan_id,
    }


@app.post("/api/runs/{run_id}/approve")
async def approve_run(run_id: str) -> Dict[str, Any]:
    record = runs.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    record.approved = True
    record.status = "APPROVED"
    return {
        "id": record.id,
        "target": record.target,
        "status": record.status,
        "count": record.count,
        "evidence": record.evidence,
        "createdAt": record.created_at,
        "approved": record.approved,
        "planId": record.plan_id,
    }


@app.post("/api/runs/{run_id}/start")
async def start_run(run_id: str) -> Dict[str, Any]:
    record = runs.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    if not record.approved:
        raise HTTPException(status_code=400, detail="Run must be approved before execution")
    record.status = "RUNNING"
    record.live = {
        "runId": record.id,
        "target": record.target,
        "status": "RUNNING",
        "currentStepId": None,
        "progress": {"completed": 0, "total": 9, "failed": 0},
        "steps": [
            {"id": f"s{i}", "testCaseId": tc, "title": tc, "status": "PENDING"}
            for i, tc in enumerate(["TC_NAV_01", "TC_NAV_02", "TC_CTA_01", "TC_CTA_02", "TC_HP_01", "TC_HP_02", "TC_RESP_01", "TC_RESP_02", "TC_A11Y_01"])
        ],
        "logs": [
            {"id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc).isoformat(), "level": "info", "message": "Execution started by orchestrator API"}
        ],
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "id": record.id,
        "target": record.target,
        "status": record.status,
        "count": record.count,
        "evidence": record.evidence,
        "createdAt": record.created_at,
        "approved": record.approved,
        "planId": record.plan_id,
    }


@app.get("/api/runs/{run_id}/live")
async def get_live_state(run_id: str) -> Dict[str, Any]:
    record = runs.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    if record.live:
        return record.live
    return {
        "runId": record.id,
        "target": record.target,
        "status": record.status,
        "currentStepId": None,
        "progress": {"completed": 0, "total": record.count or 0, "failed": 0},
        "steps": [],
        "logs": [],
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/plans")
async def list_plans() -> List[Dict[str, Any]]:
    return [{"id": "1793353092", "target": "https://testradius.dev", "status": "PASS"}]


@app.get("/api/plans/{plan_id}")
async def get_plan(plan_id: str) -> Dict[str, Any]:
    if plan_id == "1793353092":
        plan_path = Path("reports/testradius-e2e-run-1793353092.json")
        if plan_path.exists():
            with plan_path.open() as f:
                return json.load(f)
    raise HTTPException(status_code=404, detail="Plan not found")


@app.get("/api/runs/{run_id}/evidence")
async def get_evidence(run_id: str) -> Dict[str, Any]:
    manifest_path = Path("artifacts/run-1793356725/manifest.json")
    if manifest_path.exists():
        with manifest_path.open() as f:
            data = json.load(f)
            data["run_id"] = run_id
            return data
    raise HTTPException(status_code=404, detail="Evidence not found")


def create_app() -> FastAPI:
    return app
