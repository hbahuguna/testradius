"""FastAPI application wiring the orchestrator API to the UI."""
from __future__ import annotations

import asyncio
import json
import os
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
    executor_type: Optional[str] = None
    sandbox_id: Optional[str] = None
    template: Optional[str] = None


runs: Dict[str, RunRecord] = {}


def _artifact_roots() -> List[Path]:
    roots = [Path("artifacts"), Path.cwd() / "artifacts"]
    # common override
    run_root = os.environ.get("RUN_ROOT")
    if run_root:
        roots.append(Path(run_root))
    seen, out = set(), []
    for r in roots:
        try:
            rp = r.resolve()
        except Exception:
            continue
        if rp not in seen and rp.exists():
            seen.add(rp)
            out.append(rp)
    return out


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open() as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _cu_step_status(raw: str) -> str:
    m = {"pass": "COMPLETED", "passed": "COMPLETED", "fail_product": "FAILED", "fail_agent": "FAILED", "failed": "FAILED", "blocked": "SKIPPED", "skipped": "SKIPPED", "infra_error": "FAILED"}
    return m.get(str(raw or "").lower(), "PENDING")


def _discover_artifact_runs() -> List[Dict[str, Any]]:
    """Discover CLI/artifact runs (e.g. computer-use runner) from run_summary.json files.
    Read-only; does not register into in-memory `runs`. In-memory runs take precedence by id.
    """
    found: Dict[str, Dict[str, Any]] = {}
    for root in _artifact_roots():
        try:
            candidates = list(root.rglob("run_summary.json"))
        except Exception:
            continue
        for sp in candidates:
            data = _load_json(sp)
            if not data:
                continue
            run_id = str(data.get("run_id") or "").strip()
            if not run_id:
                continue
            run_dir = sp.parent
            # computer-use runner shape: has plan_id/steps/total_steps or step_results.json sibling
            is_cu = ("plan_id" in data and ("steps" in data or "total_steps" in data)) or (run_dir / "step_results.json").exists()
            if not is_cu:
                continue
            plan = _load_json(run_dir / "compiled_test_plan.json") or {}
            env = plan.get("environment") if isinstance(plan.get("environment"), dict) else {}
            md = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
            cases = plan.get("cases") if isinstance(plan.get("cases"), list) else []
            first_case = cases[0] if cases and isinstance(cases[0], dict) else {}
            target = (
                env.get("base_url") or md.get("target_url") or md.get("base_url")
                or plan.get("base_url") or plan.get("target") or first_case.get("target_url") or first_case.get("base_url")
                or str(data.get("target") or "unknown")
            )
            count = int(data.get("total_steps") or data.get("count") or len(data.get("steps") or []) or 0)
            status = str(data.get("status") or "UNKNOWN")
            try:
                rel_evidence = str(run_dir.relative_to(Path.cwd()))
            except Exception:
                rel_evidence = str(run_dir)
            found[run_id] = {
                "id": run_id,
                "target": target,
                "status": status,
                "count": count,
                "evidence": rel_evidence,
                "createdAt": data.get("started_at") or data.get("ended_at"),
                "approved": True,
                "planId": data.get("plan_id"),
                "executorType": "gemini_computer_use",
            }
    return sorted(found.values(), key=lambda x: x.get("createdAt") or "", reverse=True)


def _find_artifact_run_dir(run_id: str) -> Optional[Path]:
    rid = str(run_id)
    for root in _artifact_roots():
        try:
            for sp in root.rglob("run_summary.json"):
                data = _load_json(sp)
                if data and str(data.get("run_id") or "") == rid:
                    run_dir = sp.parent
                    if (run_dir / "step_results.json").exists() or "plan_id" in data:
                        return run_dir
        except Exception:
            continue
    return None


def _discovered_live_state(run_id: str) -> Optional[Dict[str, Any]]:
    run_dir = _find_artifact_run_dir(run_id)
    if not run_dir:
        return None
    summary = _load_json(run_dir / "run_summary.json") or {}
    plan = _load_json(run_dir / "compiled_test_plan.json") or {}
    step_results = _load_json(run_dir / "step_results.json")
    if not isinstance(step_results, list):
        # step_results.json may be written as list; handle dict wrapper
        sr = step_results if isinstance(step_results, dict) else {}
        step_results = sr.get("steps") if isinstance(sr.get("steps"), list) else summary.get("steps") or []
    steps = []
    passed = failed = 0
    for i, s in enumerate(step_results or [], 1):
        if not isinstance(s, dict):
            continue
        st = _cu_step_status(str(s.get("status") or ""))
        if st == "COMPLETED":
            passed += 1
        elif st == "FAILED":
            failed += 1
        ev = s.get("evidence") or []
        shots = [str(x) for x in ev if isinstance(x, str) and x.lower().endswith(".png")]
        steps.append({
            "id": str(s.get("step_id") or f"s{i}"),
            "testCaseId": str(s.get("case_id") or ""),
            "title": str(s.get("intent") or s.get("step_id") or f"Step {i}"),
            "status": st,
            "startedAt": s.get("started_at"),
            "endedAt": s.get("ended_at"),
            "durationMs": s.get("duration_ms"),
            "currentAction": str(s.get("action_type") or ""),
            "screenshots": shots,
        })
    env = plan.get("environment") if isinstance(plan.get("environment"), dict) else {}
    md = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    target = env.get("base_url") or md.get("target_url") or md.get("base_url") or plan.get("base_url") or plan.get("target") or "unknown"
    try:
        rel_dir = str(run_dir.relative_to(Path.cwd()))
    except Exception:
        rel_dir = str(run_dir)
    video = run_dir / "run_video.mp4"
    trace = run_dir / "action_trace.jsonl"
    return {
        "runId": run_id,
        "target": target,
        "status": str(summary.get("status") or "UNKNOWN"),
        "currentStepId": None,
        "progress": {"completed": passed, "total": int(summary.get("total_steps") or len(steps)), "failed": failed},
        "steps": steps,
        "logs": [{"id": str(uuid.uuid4()), "ts": str(summary.get("ended_at") or summary.get("started_at") or ""), "level": "info", "message": f"Discovered artifact run ({summary.get('mode') or 'computer_use'}): {rel_dir}"}],
        "updatedAt": str(summary.get("ended_at") or summary.get("started_at") or datetime.now(timezone.utc).isoformat()),
        "evidenceDir": rel_dir,
        "video": str(video.relative_to(Path.cwd())) if video.exists() else None,
        "trace": str(trace.relative_to(Path.cwd())) if trace.exists() else None,
        "executorType": "gemini_computer_use",
        "sandboxId": None,
        "template": os.environ.get("E2B_DESKTOP_TEMPLATE"),
        "artifactsUrl": None,
    }


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "runs": len(runs), "artifactRuns": len(_discover_artifact_runs())}


@app.get("/api/runs")
async def list_runs() -> List[Dict[str, Any]]:
    items = []
    seen = set()
    for r in sorted(runs.values(), key=lambda x: x.created_at, reverse=True):
        seen.add(r.id)
        items.append({
            "id": r.id,
            "target": r.target,
            "status": r.status,
            "count": r.count,
            "evidence": r.evidence,
            "createdAt": r.created_at,
            "approved": r.approved,
            "planId": r.plan_id,
            "executorType": r.executor_type,
        })
    for dr in _discover_artifact_runs():
        if dr["id"] not in seen:
            items.append(dr)
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
        discovered = _discovered_live_state(run_id)
        if discovered:
            return discovered
        raise HTTPException(status_code=404, detail="Run not found")
    base = {
        "runId": record.id,
        "target": record.target,
        "status": record.status,
        "currentStepId": None,
        "progress": {"completed": 0, "total": record.count or 0, "failed": 0},
        "steps": [],
        "logs": [],
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "executorType": record.executor_type,
        "sandboxId": record.sandbox_id,
        "template": record.template,
        "evidenceDir": record.evidence or f"artifacts/{record.id}",
    }
    if record.live:
        merged = {**base, **record.live}
        merged.setdefault("executorType", record.executor_type)
        merged.setdefault("sandboxId", record.sandbox_id)
        merged.setdefault("template", record.template)
        return merged
    return base


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
    # 1) discovered/computer-use run dir
    run_dir = _find_artifact_run_dir(run_id)
    candidates = []
    if run_dir:
        candidates.append(run_dir / "manifest.json")
        candidates.append(run_dir / "evidence_manifest.json")
    # 2) conventional layout
    candidates.append(Path("artifacts") / f"run-{run_id}" / "manifest.json")
    candidates.append(Path("artifacts") / run_id / "manifest.json")
    # 3) legacy demo fallback
    candidates.append(Path("artifacts/run-1793356725/manifest.json"))
    for mp in candidates:
        if mp.exists():
            data = _load_json(mp) or {}
            data["run_id"] = run_id
            if run_dir and "evidenceDir" not in data:
                try:
                    data["evidenceDir"] = str(run_dir.relative_to(Path.cwd()))
                except Exception:
                    data["evidenceDir"] = str(run_dir)
            return data
    raise HTTPException(status_code=404, detail="Evidence not found")


def create_app() -> FastAPI:
    return app


# Executor integration
from ..execution import create_executor, ExecutorConfig
from ..config import executor_settings
import os


class E2BValidateRequest(BaseModel):
    api_key: Optional[str] = None  # validation-only; never persisted by API
    api_url: Optional[str] = None
    domain: Optional[str] = None


@app.get("/api/executor/config")
async def get_executor_config() -> Dict[str, Any]:
    return {
        "executor_type": os.environ.get("EXECUTOR_TYPE") or os.environ.get("EXECUTOR", "local"),
        "cloudroom_url": os.environ.get("CLOUDROOM_URL"),
        "has_cloudroom_token": bool(os.environ.get("CLOUDROOM_TOKEN") or os.environ.get("CLOUDROOM_API_TOKEN")),
        "has_e2b_key": bool(os.environ.get("E2B_API_KEY")),
        "e2b_url": os.environ.get("E2B_API_URL"),
        "e2b_domain": os.environ.get("E2B_DOMAIN"),
    }


@app.post("/api/system/e2b/validate")
async def validate_e2b_connection(req: E2BValidateRequest) -> Dict[str, Any]:
    """Validate E2B configuration/connectivity (best-effort). Secrets are not persisted."""
    api_key = req.api_key or os.environ.get("E2B_API_KEY")
    api_url = req.api_url or os.environ.get("E2B_API_URL")
    domain = req.domain or os.environ.get("E2B_DOMAIN")
    configured = bool(api_key)
    result: Dict[str, Any] = {
        "ok": False,
        "configured": configured,
        "has_api_key": bool(api_key),
        "api_url": api_url,
        "domain": domain,
        "checks": [],
        "message": "",
        "warning": "API key/URL submitted here are used only for validation and are not stored by the harness UI/API.",
    }
    if not api_key:
        result["message"] = "E2B API key not configured. Set E2B_API_KEY in the environment (recommended) or provide a key for validation only."
        result["checks"].append({"name": "api_key", "ok": False, "detail": "missing"})
        return result
    result["checks"].append({"name": "api_key", "ok": True, "detail": "present"})
    if domain:
        result["checks"].append({"name": "domain", "ok": True, "detail": domain})
    if api_url:
        result["checks"].append({"name": "api_url", "ok": True, "detail": api_url})

    # Best-effort SDK/connectivity probe. Do not create sandboxes.
    old_env = {k: os.environ.get(k) for k in ("E2B_API_KEY", "E2B_API_URL", "E2B_DOMAIN")}
    try:
        os.environ["E2B_API_KEY"] = api_key
        if api_url:
            os.environ["E2B_API_URL"] = api_url
        if domain:
            os.environ["E2B_DOMAIN"] = domain
        try:
            from e2b_code_interpreter import Sandbox  # type: ignore
            # Try lightweight API interaction where available without creating a sandbox.
            if hasattr(Sandbox, "list"):
                try:
                    # Some SDK versions accept api_key; keep defensive.
                    _ = Sandbox.list()  # may raise on auth/connectivity
                    result["checks"].append({"name": "sdk_list", "ok": True, "detail": "Sandbox.list() succeeded"})
                except Exception as e:
                    result["checks"].append({"name": "sdk_list", "ok": False, "detail": str(e)})
                    result["message"] = f"E2B SDK reachable but connectivity/auth check failed: {e}"
                    return result
            else:
                result["checks"].append({"name": "sdk_import", "ok": True, "detail": "e2b_code_interpreter imported"})
            result["ok"] = True
            result["message"] = "E2B configuration looks valid (SDK import/probe succeeded)."
        except Exception as e:
            result["checks"].append({"name": "sdk", "ok": False, "detail": str(e)})
            result["message"] = f"E2B SDK check failed: {e}. Ensure e2b-code-interpreter is installed in the API environment and credentials/domain are correct."
            # Still consider configured=true
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return result


@app.post("/api/runs/{run_id}/start-executor")
async def start_run_with_executor(run_id: str) -> Dict[str, Any]:
    record = runs.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    if not record.approved:
        raise HTTPException(status_code=400, detail="Run must be approved before execution")
    
    record.status = "RUNNING"
    
    # Load plan
    plan_data = {}
    if record.plan_id:
        try:
            plan_path = Path("reports/testradius-e2e-run-1793353092.json")
            if plan_path.exists():
                with plan_path.open() as f:
                    plan_data = json.load(f)
        except Exception:
            pass
    
    config = ExecutorConfig(
        run_id=run_id,
        target_url=record.target,
        plan=plan_data.get("plan") or plan_data,
        artifacts_dir=Path("artifacts"),
        model=record.model,
    )
    
    try:
        executor = create_executor(config)
        executor_type = (os.environ.get("EXECUTOR_TYPE") or "local").lower()
        record.status = "RUNNING_EXECUTOR"
        record.executor_type = executor_type
        record.template = (plan_data.get("metadata") or {}).get("template") if isinstance(plan_data, dict) else None
        record.sandbox_id = getattr(executor, "sandbox_id", None)
        return {
            "id": record.id,
            "status": record.status,
            "executor_type": executor_type,
            "sandbox_id": record.sandbox_id,
            "template": record.template,
            "message": "Executor started",
        }
    except Exception as e:
        record.status = "FAILED"
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/executor")
async def get_system_executor() -> Dict[str, Any]:
    executor_type = os.environ.get("EXECUTOR_TYPE") or os.environ.get("EXECUTOR", "local")
    return {
        "executor_type": executor_type.lower(),
        "supported": ["local", "cloudroom", "e2b"],
        "cloudroom_configured": bool(os.environ.get("CLOUDROOM_TOKEN") or os.environ.get("CLOUDROOM_API_TOKEN")),
        "cloudroom_url": os.environ.get("CLOUDROOM_URL"),
        "e2b_configured": bool(os.environ.get("E2B_API_KEY")),
        "e2b_api_url": os.environ.get("E2B_API_URL"),
        "e2b_domain": os.environ.get("E2B_DOMAIN"),
    }
