"""End-to-end E2B orchestration (STORY-E2B-006.1).

Coordinates: plan/input -> E2B execution (delivery/artifacts via executor) ->
optional vision inspection -> optional bug review package -> report, with
progress tracking and guaranteed sandbox cleanup.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from ..bugs import BugReportGenerator
from ..checkpoints import BugFilingWorkflow
from ..execution.base import BaseExecutor, ExecutionResult, ExecutionStatus, ExecutorConfig
from ..execution.e2b import E2BExecutor
from ..vision.client import VisionClient
from ..vision.inspector import SelfInspector

ProgressCallback = Callable[[Dict[str, Any]], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonish(src: Union[str, Path, Dict[str, Any], None]) -> Optional[Dict[str, Any]]:
    if src is None:
        return None
    if isinstance(src, dict):
        return src
    try:
        p = Path(src)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


@dataclass
class E2BOrchestrationOptions:
    run_id: str
    target_url: str
    plan: Union[Dict[str, Any], str, Path]
    artifacts_dir: Union[str, Path] = "artifacts"
    timeout_seconds: int = 600
    template: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    enable_vision: bool = True
    vision_model: str = "mock"
    vision_rounds: int = 2
    vision_limit: int = 10
    enable_bug_review: bool = True  # generates review package; does NOT auto-file
    bug_review_approval_id: Optional[str] = None


@dataclass
class OrchestrationReport:
    run_id: str
    status: str
    started_at: str
    ended_at: str
    duration_ms: int
    progress: List[Dict[str, Any]] = field(default_factory=list)
    execution: Optional[Dict[str, Any]] = None
    vision: Optional[Dict[str, Any]] = None
    bug_review: Optional[Dict[str, Any]] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "progress": self.progress,
            "execution": self.execution,
            "vision": self.vision,
            "bug_review": self.bug_review,
            "artifacts": self.artifacts,
            "error": self.error,
            "errors": self.errors,
            "metadata": self.metadata,
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path


class E2BOrchestrator:
    """Coordinates full E2B run: execute -> artifacts -> vision -> bug review/report."""

    def __init__(
        self,
        *,
        executor: Optional[BaseExecutor] = None,
        executor_factory: Optional[Callable[[ExecutorConfig], BaseExecutor]] = None,
        vision_client: Optional[VisionClient] = None,
        inspector: Optional[SelfInspector] = None,
        bug_generator: Optional[BugReportGenerator] = None,
        bug_workflow: Optional[BugFilingWorkflow] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ):
        self.executor = executor
        self.executor_factory = executor_factory
        self.vision_client = vision_client
        self.inspector = inspector
        self.bug_generator = bug_generator or BugReportGenerator()
        self.bug_workflow = bug_workflow
        self.progress_callback = progress_callback

    def run(self, options: E2BOrchestrationOptions) -> OrchestrationReport:
        started = time.time()
        started_at = _utc_now()
        progress: List[Dict[str, Any]] = []
        errors: List[str] = []
        execution_dict: Optional[Dict[str, Any]] = None
        vision_dict: Optional[Dict[str, Any]] = None
        bug_review: Optional[Dict[str, Any]] = None
        executor: Optional[BaseExecutor] = None
        final_status = "FAILED"

        def emit(stage: str, status: str, detail: str = "", **extra: Any) -> None:
            event = {"ts": _utc_now(), "stage": stage, "status": status, "detail": detail, **extra}
            progress.append(event)
            if self.progress_callback:
                try:
                    self.progress_callback(event)
                except Exception:
                    pass

        artifacts_root = Path(options.artifacts_dir)
        run_dir = artifacts_root / options.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            emit("init", "started", "Loading plan and preparing orchestration")
            plan = _load_jsonish(options.plan)
            if not isinstance(plan, dict):
                raise ValueError("Plan must be a dict or path to a JSON plan file")

            config = ExecutorConfig(
                run_id=options.run_id,
                target_url=options.target_url,
                plan=plan,
                artifacts_dir=artifacts_root,
                timeout_seconds=options.timeout_seconds,
                metadata={**dict(options.metadata), **({"template": options.template} if options.template else {})},
            )
            if self.executor is not None:
                executor = self.executor
                # Align injected executor with this run (useful for tests/custom executors)
                try:
                    executor.config = config
                except Exception:
                    pass
            elif self.executor_factory:
                executor = self.executor_factory(config)
            else:
                executor = E2BExecutor(config)

            emit("execute", "started", "Executing plan in E2B sandbox", executor=type(executor).__name__)
            try:
                executor.prepare()
                exec_result = executor.execute_plan()
            finally:
                emit("cleanup", "started", "Cleaning up sandbox/executor")
                try:
                    executor.cleanup()
                    emit("cleanup", "completed", "Sandbox/executor cleaned up")
                except Exception as e:
                    errors.append(f"cleanup: {e}")
                    emit("cleanup", "failed", str(e))
            execution_dict = exec_result.to_dict() if isinstance(exec_result, ExecutionResult) else {"result": exec_result}
            emit(
                "execute",
                "completed" if exec_result.status == ExecutionStatus.COMPLETED else "failed",
                exec_result.error or f"Execution status={exec_result.status.value}",
                status_value=exec_result.status.value,
            )

            # Vision inspection from collected artifacts (004.1 manifest/run dir)
            if options.enable_vision:
                emit("vision", "started", "Running vision inspection on collected artifacts")
                try:
                    vision_dict = self._run_vision(run_dir=run_dir, options=options)
                    emit("vision", "completed", vision_dict.get("summary", "Vision inspection complete"))
                except Exception as e:
                    errors.append(f"vision: {e}")
                    vision_dict = {"error": str(e)}
                    emit("vision", "failed", str(e))

            # Bug review package (005.1/005.2) - never auto-files without explicit approval flow
            if options.enable_bug_review:
                emit("bug_review", "started", "Generating bug review package (approval required before filing)")
                try:
                    bug_review = self._run_bug_review(run_dir=run_dir, options=options, vision=vision_dict)
                    emit("bug_review", "completed", "Bug review package generated" if bug_review else "No actionable findings for bug review")
                except Exception as e:
                    errors.append(f"bug_review: {e}")
                    bug_review = {"error": str(e)}
                    emit("bug_review", "failed", str(e))

            if exec_result.status == ExecutionStatus.COMPLETED and not any("execute" in e for e in errors):
                final_status = "COMPLETED"
            elif exec_result.status == ExecutionStatus.COMPLETED:
                final_status = "COMPLETED_WITH_WARNINGS"
            else:
                final_status = exec_result.status.value
                if exec_result.error:
                    errors.append(f"execution: {exec_result.error}")

        except Exception as e:
            errors.append(str(e))
            emit("orchestration", "failed", str(e))
            # Best-effort cleanup if executor created but not cleaned
            if executor is not None:
                try:
                    executor.cleanup()
                except Exception:
                    pass

        ended_at = _utc_now()
        report = OrchestrationReport(
            run_id=options.run_id,
            status=final_status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=int((time.time() - started) * 1000),
            progress=progress,
            execution=execution_dict,
            vision=vision_dict,
            bug_review=bug_review,
            artifacts={
                "run_dir": str(run_dir),
                "manifest": str(run_dir / "manifest.json") if (run_dir / "manifest.json").exists() else None,
                "step_results": str(run_dir / "step_results.json") if (run_dir / "step_results.json").exists() else None,
                "orchestration_report": str(run_dir / "orchestration_report.json"),
            },
            error=errors[0] if errors else None,
            errors=errors,
            metadata={"target_url": options.target_url, **dict(options.metadata)},
        )
        report.save(run_dir / "orchestration_report.json")
        emit("orchestration", "completed" if final_status.startswith("COMPLETED") else "failed", f"status={final_status}")
        # append final event to saved report? report already saved; acceptable for MVP.
        return report

    def _run_vision(self, *, run_dir: Path, options: E2BOrchestrationOptions) -> Dict[str, Any]:
        client = self.vision_client or VisionClient(model=options.vision_model)
        screenshots = client.analyze_artifacts(run_dir=run_dir, limit=options.vision_limit)
        if not screenshots:
            # analyze_artifacts returns VisionAnalysisResult list
            pass
        # Build per-screenshot inspection reports for stronger 004.3-style output when screenshots exist
        manifest = run_dir / "manifest.json"
        paths: List[Path] = []
        if manifest.exists():
            try:
                m = json.loads(manifest.read_text(encoding="utf-8"))
                for a in m.get("artifacts") or []:
                    if (a.get("type") or "").lower() == "screenshot":
                        p = Path(a.get("path") or a.get("filename") or "")
                        cand = run_dir / p.name
                        if cand.exists():
                            paths.append(cand)
            except Exception:
                pass
        if not paths:
            paths = sorted([p for p in run_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}])
        paths = paths[: max(0, options.vision_limit)]
        inspections = []
        inspector = self.inspector or SelfInspector(rounds=options.vision_rounds, client=client)
        for shot in paths:
            inspections.append(inspector.inspect(str(shot), url=options.target_url, run_id=options.run_id))
        out = {
            "schema_version": "1.0",
            "run_id": options.run_id,
            "screenshots_analyzed": len(paths),
            "inspections": inspections,
            "summary": {
                "screenshots_analyzed": len(paths),
                "total_actionable_findings": sum(i.get("summary", {}).get("actionable_deduped_findings", 0) for i in inspections),
            },
        }
        (run_dir / "vision_inspection_report.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    def _run_bug_review(self, *, run_dir: Path, options: E2BOrchestrationOptions, vision: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        inspection = run_dir / "vision_inspection_report.json"
        # Flatten actionable findings presence check
        findings = []
        if inspection.exists():
            try:
                data = json.loads(inspection.read_text(encoding="utf-8"))
                for ins in data.get("inspections") or []:
                    findings.extend(ins.get("deduped") or [])
            except Exception:
                pass
        actionable = [f for f in findings if str(f.get("issue", "")).lower() not in {"", "none", "ok", "pass", "no issue"} and str(f.get("severity", "")).lower() not in {"info", ""}]
        if not actionable:
            return None
        workflow = self.bug_workflow or BugFilingWorkflow(generator=self.bug_generator)
        approval_id = options.bug_review_approval_id or f"bug-{options.run_id}"
        pkg = workflow.prepare_review(
            approval_id=approval_id,
            run_dir=run_dir,
            inspection_report=inspection if inspection.exists() else None,
            step_results=run_dir / "step_results.json" if (run_dir / "step_results.json").exists() else None,
            url=options.target_url,
            environment={"executor": "e2b", "template": options.template},
            save=True,
        )
        return {"approval_id": approval_id, "actionable_findings": len(actionable), "review_package": pkg.get("saved")}
