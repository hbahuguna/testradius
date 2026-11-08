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

import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logger = logging.getLogger("harness.api")

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


def _plan_target(plan: Dict[str, Any], data: Optional[Dict[str, Any]] = None) -> str:
    """Compiled plans carry target at sut.base_url (canonical); check common variants."""
    sut = plan.get("sut") if isinstance(plan.get("sut"), dict) else {}
    env = plan.get("environment") if isinstance(plan.get("environment"), dict) else {}
    md = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    cases = plan.get("cases") if isinstance(plan.get("cases"), list) else []
    fc = cases[0] if cases and isinstance(cases[0], dict) else {}
    return (
        sut.get("base_url") or sut.get("target_url")
        or env.get("base_url") or md.get("target_url") or md.get("base_url")
        or plan.get("base_url") or plan.get("target") or fc.get("target_url") or fc.get("base_url")
        or (str((data or {}).get("target") or "") if data else "")
        or "unknown"
    )


def _rel_path(p: Path) -> str:
    try:
        return str(p.relative_to(Path.cwd()))
    except Exception:
        return str(p)


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
            plan = _load_json(run_dir / "compiled_test_plan.json") or _load_json(run_dir / "compiled_test_plan.request.json") or {}
            target = _plan_target(plan, data)
            count = int(data.get("total_steps") or data.get("count") or len(data.get("steps") or []) or 0)
            status = str(data.get("status") or "UNKNOWN")
            rel_evidence = _rel_path(run_dir)
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
    target = _plan_target(plan, summary)
    rel_dir = _rel_path(run_dir)
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


@app.get("/api/runs/{run_id}")
async def get_run_report(run_id: str) -> Dict[str, Any]:
    # Prefer artifact reports (incl. UI-started computer-use runs that also have an
    # in-memory record); in-memory-only runs have no persisted report yet.
    run_dir = _find_artifact_run_dir(run_id)
    if not run_dir:
        raise HTTPException(status_code=404, detail="Run report not found")
    summary = _load_json(run_dir / "run_summary.json") or {}
    plan = _load_json(run_dir / "compiled_test_plan.json") or _load_json(run_dir / "compiled_test_plan.request.json") or {}
    sr = _load_json(run_dir / "step_results.json")
    step_results = sr if isinstance(sr, list) else (sr.get("steps") if isinstance(sr, dict) else None) or summary.get("steps") or []
    executed = []
    for s in step_results:
        if not isinstance(s, dict):
            continue
        ev = s.get("evidence") or []
        shots = [str(x) for x in ev if isinstance(x, str) and x.lower().endswith(".png")]
        status_raw = str(s.get("status") or "")
        ui_status = "ERROR" if status_raw in {"fail_product", "fail_agent", "failed", "infra_error"} else "EXECUTED"
        executed.append({
            "id": str(s.get("step_id") or ""),
            "title": str(s.get("intent") or s.get("step_id") or ""),
            "category": "computer_use",
            "status": ui_status,
            "steps": [str(s.get("action_type") or ""), str(s.get("detail") or "")],
            "expectedChecks": [str(s.get("detail") or status_raw)],
            "screenshots": shots,
            "assertions": [{"check": str(s.get("detail") or status_raw), "status": "PASS" if status_raw in {"pass", "passed"} else ("FAIL" if ui_status == "ERROR" else "RECORDED")}],
            "error": str(s.get("detail") or "") if ui_status == "ERROR" else None,
        })
    target = _plan_target(plan, summary)
    rel_dir = _rel_path(run_dir)
    video = run_dir / "run_video.mp4"
    trace = run_dir / "action_trace.jsonl"
    return {
        "source_plan": str(summary.get("plan_id") or plan.get("plan_id") or ""),
        "target": target,
        "test_plan_title": str(plan.get("title") or plan.get("name") or summary.get("plan_id") or "Computer Use Run"),
        "mode": "gemini_computer_use",
        "executed": executed,
        "count": int(summary.get("total_steps") or len(executed)),
        "status": str(summary.get("status") or "UNKNOWN"),
        "video": str(video.relative_to(Path.cwd())) if video.exists() else None,
        "trace": str(trace.relative_to(Path.cwd())) if trace.exists() else None,
        "evidence": rel_dir,
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
        # Prefer incremental artifact state for active/completed CU runs.
        if record.executor_type == "gemini_computer_use" or str(record.id).startswith("ui-cu-"):
            discovered = _discovered_live_state(record.id)
            if discovered and discovered.get("updatedAt"):
                # keep in-memory sandbox/logs but take progress/steps/status from artifacts when richer
                if len(discovered.get("steps") or []) >= len(merged.get("steps") or []):
                    merged["steps"] = discovered.get("steps") or merged.get("steps")
                    merged["progress"] = discovered.get("progress") or merged.get("progress")
                    if discovered.get("status") and discovered.get("status") != "UNKNOWN":
                        merged["status"] = discovered["status"]
                        record.status = discovered["status"]
                    merged["video"] = discovered.get("video") or merged.get("video")
                    merged["trace"] = discovered.get("trace") or merged.get("trace")
                    merged["updatedAt"] = discovered.get("updatedAt") or merged.get("updatedAt")
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
    # 1) discovered/computer-use run dir: synthesize manifest from artifacts
    run_dir = _find_artifact_run_dir(run_id)
    if run_dir:
        for mp in (run_dir / "manifest.json", run_dir / "evidence_manifest.json"):
            if mp.exists():
                data = _load_json(mp) or {}
                data["run_id"] = run_id
                data.setdefault("evidenceDir", _rel_path(run_dir))
                return data
        artifacts: List[Dict[str, Any]] = []
        video = run_dir / "run_video.mp4"
        if video.exists():
            artifacts.append({"type": "video", "path": _rel_path(video)})
        trace = run_dir / "action_trace.jsonl"
        if trace.exists():
            artifacts.append({"type": "trace", "path": _rel_path(trace)})
        try:
            for png in sorted(run_dir.glob("*.png")):
                artifacts.append({"type": "screenshot", "path": _rel_path(png)})
        except Exception:
            pass
        # only return synthesized manifest if we found real CU artifacts; else fall through
        if artifacts:
            return {"run_id": run_id, "artifacts": artifacts, "evidenceDir": _rel_path(run_dir)}
    # 2) conventional layout
    candidates = [
        Path("artifacts") / f"run-{run_id}" / "manifest.json",
        Path("artifacts") / run_id / "manifest.json",
        Path("artifacts/run-1793356725/manifest.json"),
    ]
    for mp in candidates:
        if mp.exists():
            data = _load_json(mp) or {}
            data["run_id"] = run_id
            if run_dir and "evidenceDir" not in data:
                data["evidenceDir"] = _rel_path(run_dir)
            return data
    raise HTTPException(status_code=404, detail="Evidence not found")


# ---- UI-driven computer-use E2E flow (Jira -> compile -> E2B/Gemini CU) ----

class JiraFetchRequest(BaseModel):
    jira_url: Optional[str] = None
    issue_key: str = Field(..., min_length=1)
    # Optional transient creds (used only for this request; never stored/returned).
    email: Optional[str] = None
    api_token: Optional[str] = None
    pat: Optional[str] = None
    save: bool = True
    run_id: Optional[str] = None


class CompilePlanRequest(BaseModel):
    context_bundle: Dict[str, Any]
    sut: Dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None
    mode: str = "local_spike"
    provided_acs: Optional[List[str]] = None
    save: bool = True


class StartComputerUseRequest(BaseModel):
    compiled_plan: Optional[Dict[str, Any]] = None
    compiled_plan_path: Optional[str] = None
    run_id: Optional[str] = None
    target_url: Optional[str] = None
    mode: str = "local_spike"
    loop: str = "per_step"
    live: bool = True  # require real E2B+Gemini; fails clearly if env missing
    max_actions_per_step: int = 6


UI_CU_ROOT = Path("artifacts") / "ui-computer-use"
UI_CU_ROOT.mkdir(parents=True, exist_ok=True)


def _safe_ui_run_id(prefix: str = "ui-cu") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _fetch_jira_issue(jira_url: str, issue_key: str, *, email: str = "", api_token: str = "", pat: str = "") -> dict:
    jira_url = (jira_url or "").rstrip("/")
    if not jira_url:
        raise ValueError("jira_url is required")
    api = "3" if "atlassian.net" in jira_url else "2"
    url = f"{jira_url}/rest/api/{api}/issue/{issue_key}?fields=*all"
    headers = {"Accept": "application/json"}
    # Prefer request-scoped creds if provided, else env. Never log/return them.
    token = api_token or os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_API_KEY") or ""
    pat_token = pat or os.environ.get("JIRA_PAT") or ""
    req_email = email or os.environ.get("JIRA_EMAIL", "")
    if not token and not pat_token:
        raise ValueError("Jira credentials missing: set JIRA_API_TOKEN(+JIRA_EMAIL)/JIRA_PAT in backend env, or provide transient creds in request")
    try:
        import httpx  # type: ignore
    except ImportError:
        httpx = None  # type: ignore
    if httpx is not None:
        if token:
            r = httpx.get(url, headers=headers, auth=httpx.BasicAuth(req_email, token), timeout=30.0)
        else:
            headers["Authorization"] = f"Bearer {pat_token}"
            r = httpx.get(url, headers=headers, timeout=30.0)
        r.raise_for_status()
        return r.json()
    # urllib fallback (no httpx dependency).
    import base64
    import urllib.request
    from urllib.error import HTTPError

    req_headers = dict(headers)
    if token:
        req_headers["Authorization"] = "Basic " + base64.b64encode(f"{req_email}:{token}".encode()).decode()
    else:
        req_headers["Authorization"] = f"Bearer {pat_token}"
    req = urllib.request.Request(url, headers=req_headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        raise ValueError(f"Jira fetch failed: HTTP {e.code} {e.reason}")


@app.post("/api/context/jira/fetch")
async def fetch_jira_context(req: JiraFetchRequest) -> Dict[str, Any]:
    jira_url = req.jira_url or os.environ.get("JIRA_SITE") or os.environ.get("JIRA_URL") or ""
    try:
        payload = _fetch_jira_issue(jira_url, req.issue_key, email=req.email or "", api_token=req.api_token or "", pat=req.pat or "")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Jira fetch failed: {e}")
    try:
        from harness.integrations.mcp_context import ContextIntake, ContextSourceConfig

        intake = ContextIntake()
        bundle = intake.ingest([
            ContextSourceConfig(type="jira", ref=req.issue_key, payload=payload, tool="mcp.jira/get_issue", uri=payload.get("self")),
        ])
        bundle_dict = json.loads(json.dumps(bundle.model_dump(mode="json"), default=str))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Context normalization failed: {e}")
    saved = None
    if req.save:
        rid = req.run_id or _safe_ui_run_id("jira")
        out = UI_CU_ROOT / rid / "context_bundle.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bundle_dict, indent=2), encoding="utf-8")
        saved = str(out)
    return {
        "ok": True,
        "issue_key": req.issue_key,
        "jira_url": jira_url.rstrip("/"),
        "context_bundle": bundle_dict,
        "saved": saved,
        "acceptance_criteria_count": len((bundle_dict.get("acceptance_criteria") or [])),
    }


@app.post("/api/testplans/compile")
async def compile_testplan(req: CompilePlanRequest) -> Dict[str, Any]:
    rid = req.run_id or _safe_ui_run_id("compile")
    try:
        from harness.testplan.compiler import GeminiTestPlanCompiler

        compiler = GeminiTestPlanCompiler()
        res = compiler.compile(
            context_bundle=req.context_bundle,
            sut_config=req.sut or {},
            run_id=rid,
            provided_acs=req.provided_acs,
            artifacts_dir=str(UI_CU_ROOT),
            mode=req.mode,
            save=req.save,
        )
    except Exception as e:
        logger.exception("Compile failed")
        raise HTTPException(status_code=500, detail=f"Compile failed: {e}")
    out = res.to_dict()
    if res.plan is not None:
        try:
            out["compiled_plan"] = json.loads(json.dumps(res.plan.model_dump(mode="json"), default=str))
        except Exception:
            pass
    return out


@app.get("/api/testplans/compiled")
async def get_compiled_testplan(path: str) -> Dict[str, Any]:
    p = Path(path)
    # allow only under artifacts/
    try:
        rp = p.resolve()
        arts = (Path.cwd() / "artifacts").resolve()
        if arts not in rp.parents and rp != arts:
            raise HTTPException(status_code=403, detail="path must be under artifacts/")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    data = _load_json(rp)
    if not data:
        raise HTTPException(status_code=404, detail="compiled plan not found")
    return data


def _cu_live_state(run_id: str, status: str, detail: str = "", *, target: str = "", plan_id: str = "", evidence: str = "", sandbox_id: str = None, template: str = None) -> Dict[str, Any]:
    working = status in ("QUEUED", "PREPARING", "RUNNING")
    return {
        "runId": run_id, "target": target or "unknown", "status": status, "currentStepId": None,
        "progress": {"completed": 0, "total": 0, "failed": 0}, "steps": [],
        "logs": [{"id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc).isoformat(), "level": "info" if status != "FAILED" else "error", "message": detail or status}],
        "updatedAt": datetime.now(timezone.utc).isoformat(), "evidenceDir": evidence,
        "executorType": "gemini_computer_use", "sandboxId": sandbox_id, "template": template,
        "planId": plan_id, "stage": status, "working": working,
    }


def _run_computer_use_background(run_id: str, compiled_plan: Dict[str, Any], target_url: str, mode: str, loop: str, live: bool, max_actions: int) -> None:
    record = runs.get(run_id)
    run_dir = UI_CU_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        from harness.execution.base import ExecutorConfig
        from harness.execution.computer_use import ComputerUseExecutor

        has_e2b = bool(os.environ.get("E2B_API_KEY"))
        has_gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        if live and not (has_e2b and has_gemini):
            raise RuntimeError("Live run requires backend env: E2B_API_KEY and GEMINI_API_KEY/GOOGLE_API_KEY")
        cfg = ExecutorConfig(
            run_id=run_id,
            target_url=target_url or "",
            plan=compiled_plan,
            artifacts_dir=UI_CU_ROOT,
            metadata={"mock": False if live else True, "mode": mode, "loop": loop, "max_actions_per_step": max_actions, "assess_pass": not live},
        )
        ex = ComputerUseExecutor(cfg)
        if record:
            record.status = "PREPARING"
            record.live = _cu_live_state(run_id, "PREPARING", "Preparing E2B sandbox... (creating desktop-chromium sandbox; first run can take 1-3 minutes)", target=target_url, plan_id=str(compiled_plan.get("plan_id") or ""), evidence=str(run_dir), template=os.environ.get("E2B_DESKTOP_TEMPLATE", "desktop-chromium"))
        if not ex.prepare():
            raise RuntimeError("ComputerUseExecutor.prepare() failed" + (f": {ex.last_error}" if getattr(ex, "last_error", None) else ""))
        if record:
            record.sandbox_id = getattr(ex, "sandbox_id", None)
            record.template = os.environ.get("E2B_DESKTOP_TEMPLATE", "desktop-chromium")
            record.live = _cu_live_state(run_id, "RUNNING", f"Executing compiled plan (sandbox={record.sandbox_id or 'mock'})", target=target_url, plan_id=str(compiled_plan.get("plan_id") or ""), evidence=str(run_dir), sandbox_id=record.sandbox_id, template=record.template)
        result = ex.execute_plan()
        if record:
            record.status = getattr(result.status, "value", str(result.status))
            record.sandbox_id = (result.metadata or {}).get("sandbox_id") or record.sandbox_id
            # final live will be served from artifact discovery; keep summary
            record.live = _cu_live_state(run_id, record.status, result.error or "Run finished", target=target_url, plan_id=str(compiled_plan.get("plan_id") or ""), evidence=str(run_dir), sandbox_id=record.sandbox_id, template=record.template)
        try:
            ex.cleanup()
        except Exception:
            pass
    except Exception as e:
        logger.exception("Computer-use background run %s failed", run_id)
        if record:
            record.status = "FAILED"
            record.live = _cu_live_state(run_id, "FAILED", str(e), target=target_url, plan_id=str(compiled_plan.get("plan_id") or ""), evidence=str(run_dir), sandbox_id=record.sandbox_id, template=record.template)


@app.post("/api/computer-use/runs/start")
async def start_computer_use_run(req: StartComputerUseRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    compiled = req.compiled_plan
    if not compiled and req.compiled_plan_path:
        compiled = _load_json(Path(req.compiled_plan_path))
    if not compiled or not isinstance(compiled, dict):
        raise HTTPException(status_code=400, detail="compiled_plan (dict) or valid compiled_plan_path required")
    if req.live:
        missing = []
        if not os.environ.get("E2B_API_KEY"):
            missing.append("E2B_API_KEY")
        if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
            missing.append("GEMINI_API_KEY/GOOGLE_API_KEY")
        if missing:
            raise HTTPException(status_code=400, detail=f"Live run blocked: backend env missing {', '.join(missing)}. Export them in the API terminal and restart uvicorn.")
    run_id = req.run_id or _safe_ui_run_id("ui-cu")
    target = req.target_url or (((compiled.get("environment") or {}).get("base_url")) if isinstance(compiled.get("environment"), dict) else None) or ""
    plan_id = str(compiled.get("plan_id") or "")
    evidence = str(UI_CU_ROOT / run_id)
    record = RunRecord(id=run_id, target=target, goal=f"Computer use: {plan_id}", context=None, model=os.environ.get("GEMINI_COMPUTER_USE_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash", status="QUEUED", count=int(len(((compiled.get("cases") or [{}])[0] or {}).get("steps") or [])) or len(compiled.get("cases") or []), evidence=evidence, approved=True, plan_id=plan_id, executor_type="gemini_computer_use", template=os.environ.get("E2B_DESKTOP_TEMPLATE", "desktop-chromium"))
    record.live = _cu_live_state(run_id, "QUEUED", "Queued for E2B/Gemini computer-use execution", target=target, plan_id=plan_id, evidence=evidence)
    runs[run_id] = record
    # persist compiled plan in run dir for traceability
    run_dir = UI_CU_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "compiled_test_plan.request.json").write_text(json.dumps(compiled, indent=2, default=str), encoding="utf-8")
    # Seed QUEUED snapshot so /live + discovery work before the runner starts
    # (and survive API restarts even if prepare() fails before the runner runs).
    if not (run_dir / "run_summary.json").exists():
        started = datetime.now(timezone.utc).isoformat()
        (run_dir / "step_results.json").write_text("[]", encoding="utf-8")
        (run_dir / "run_summary.json").write_text(json.dumps({
            "run_id": run_id, "plan_id": plan_id, "status": "QUEUED", "started_at": started,
            "ended_at": started, "total_steps": record.count, "passed": 0, "failed": 0,
            "blocked": 0, "infra_errors": 0, "steps": [], "progress": [],
            "artifacts": [str(run_dir / "compiled_test_plan.request.json")], "mode": req.loop,
        }, indent=2), encoding="utf-8")
    background_tasks.add_task(_run_computer_use_background, run_id, compiled, target, req.mode, req.loop, req.live, req.max_actions_per_step)
    return {"id": run_id, "status": "QUEUED", "target": target, "planId": plan_id, "evidence": evidence, "executorType": "gemini_computer_use"}


# Static artifact serving for UI (video/screenshots/trace). Read-only.
_artifacts_dir = (Path.cwd() / "artifacts").resolve()
_artifacts_dir.mkdir(parents=True, exist_ok=True)
try:
    app.mount("/artifacts", StaticFiles(directory=str(_artifacts_dir)), name="artifacts")
except Exception:
    pass


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
            # Prefer the real `e2b` SDK (used by E2BSandboxProvider); fall back to e2b_code_interpreter.
            try:
                from e2b import Sandbox  # type: ignore
                sdk_name = "e2b"
            except ImportError:
                from e2b_code_interpreter import Sandbox  # type: ignore
                sdk_name = "e2b_code_interpreter"
            # Try lightweight API interaction without creating a sandbox.
            if hasattr(Sandbox, "list"):
                try:
                    _ = Sandbox.list()  # may raise on auth/connectivity
                    result["checks"].append({"name": "sdk_list", "ok": True, "detail": f"{sdk_name}: Sandbox.list() succeeded"})
                except Exception as e:
                    result["checks"].append({"name": "sdk_list", "ok": False, "detail": str(e)})
                    result["message"] = f"E2B SDK reachable but connectivity/auth check failed: {e}"
                    return result
            else:
                result["checks"].append({"name": "sdk_import", "ok": True, "detail": f"{sdk_name} imported"})
            result["ok"] = True
            result["message"] = "E2B configuration looks valid (SDK import/probe succeeded)."
        except Exception as e:
            result["checks"].append({"name": "sdk", "ok": False, "detail": str(e)})
            result["message"] = f"E2B SDK check failed: {e}. Ensure the e2b SDK is installed in the API environment and credentials/domain are correct."
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


@app.get("/api/system/integrations")
async def get_system_integrations() -> Dict[str, Any]:
    return {
        "jira_configured": bool((os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_API_KEY")) and (os.environ.get("JIRA_EMAIL") or os.environ.get("JIRA_SITE"))) or bool(os.environ.get("JIRA_PAT")),
        "jira_site": os.environ.get("JIRA_SITE") or os.environ.get("JIRA_URL") or "",
        "gemini_configured": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
        "gemini_model": os.environ.get("GEMINI_COMPUTER_USE_MODEL") or os.environ.get("GEMINI_MODEL") or os.environ.get("GEMINI_TESTPLAN_MODEL") or "",
        "e2b_configured": bool(os.environ.get("E2B_API_KEY")),
        "e2b_template": os.environ.get("E2B_DESKTOP_TEMPLATE") or "desktop-chromium",
    }


@app.get("/api/system/executor")
async def get_system_executor() -> Dict[str, Any]:
    executor_type = os.environ.get("EXECUTOR_TYPE") or os.environ.get("EXECUTOR", "local")
    return {
        "executor_type": executor_type.lower(),
        "supported": ["local", "cloudroom", "e2b", "gemini_computer_use"],
        "cloudroom_configured": bool(os.environ.get("CLOUDROOM_TOKEN") or os.environ.get("CLOUDROOM_API_TOKEN")),
        "cloudroom_url": os.environ.get("CLOUDROOM_URL"),
        "e2b_configured": bool(os.environ.get("E2B_API_KEY")),
        "e2b_api_url": os.environ.get("E2B_API_URL"),
        "e2b_domain": os.environ.get("E2B_DOMAIN"),
    }
