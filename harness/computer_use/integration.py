"""Harness integration: checkpoints, findings, normalization, bug filing (008.6).

High-level orchestration that wires compiled-plan / computer-use runs into the
standard harness workflow:

1. Plan checkpoint (prod requires human approval before execution).
2. Orchestration lifecycle (run IDs, ``artifacts/run-<id>/``, status, logs).
3. Artifact normalization (``manifest.json`` + ``run_report.json``).
4. Findings with expected-vs-observed, screenshots, trace excerpt, source refs.
5. Bug-filing checkpoint (``BugFilingWorkflow.prepare_review``; filing only
   after explicit approval — no auto-file).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from harness.checkpoints.approval import ApprovalRegistry
from harness.checkpoints.bug_filing import BugFilingWorkflow
from harness.e2b.artifacts import ArtifactManifest, ArtifactRecord, classify_artifact
from harness.execution.base import ExecutionStatus
from harness.testplan.schema import CompiledExecutionTestPlan
from harness.testplan.validator import CompiledPlanValidator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


class PlanCheckpoint:
    """Human-review gate for compiled plans before execution (prod)."""

    def __init__(self, *, registry: Optional[ApprovalRegistry] = None):
        self.registry = registry or ApprovalRegistry()

    def review(self, *, run_id: str, plan: Any, mode: str, artifacts_dir: Path | str = "artifacts") -> Dict[str, Any]:
        obj = plan if isinstance(plan, CompiledExecutionTestPlan) else CompiledExecutionTestPlan.model_validate(plan)
        status = str((obj.quality_gate.review_status if obj.quality_gate else "draft") or "draft")
        approval_id = f"plan-{run_id}"
        state = self.registry.get(approval_id)
        allowed = True
        reason = ""
        if mode == "production":
            if status != "approved":
                allowed = False
                reason = f"production requires review_status='approved' (got '{status}')"
            elif not state.approved:
                allowed = True  # validator already enforces approved; registry approval is additional audit
                # Do not block if plan itself approved but registry lacks entry; record warning.
                reason = "plan approved via quality_gate; registry approval optional audit"
        else:
            reason = "local_spike: draft/human_reviewed allowed"
        checkpoint = {
            "approval_id": approval_id,
            "run_id": run_id,
            "plan_id": obj.plan_id,
            "mode": mode,
            "review_status": status,
            "allowed": allowed,
            "reason": reason,
            "registry_approved": bool(state.approved),
            "checked_at": _utc_now(),
        }
        run_dir = Path(artifacts_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "plan_checkpoint.json").write_text(json.dumps(checkpoint, indent=2))
        return checkpoint

    def approve(self, *, run_id: str, actor: str, detail: str = "") -> Dict[str, Any]:
        state = self.registry.get(f"plan-{run_id}")
        if not state.approved:
            state.approve(actor=actor, detail=detail)
        return {"approval_id": state.run_id, "approved": True, "approved_by": state.approved_by}


def build_findings_from_run(*, summary: Any, plan: Any, run_dir: Path) -> List[Dict[str, Any]]:
    """Map non-pass step results to bug-filing findings with full traceability."""
    obj = plan if isinstance(plan, CompiledExecutionTestPlan) else CompiledExecutionTestPlan.model_validate(plan)
    steps = summary.steps if hasattr(summary, "steps") else (summary.get("steps") or [])
    trace_path = Path(run_dir) / "action_trace.jsonl"
    trace_lines: List[Dict[str, Any]] = []
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    trace_lines.append(json.loads(line))
                except Exception:
                    continue
    # Index plan steps for expected criteria + source refs
    step_by_id = {}
    for case in (obj.cases or []):
        for st in (case.steps or []):
            step_by_id[st.step_id] = st
    source_refs = [r.model_dump() if hasattr(r, "model_dump") else dict(r) for r in (obj.source_refs or [])]
    findings: List[Dict[str, Any]] = []
    severity_map = {"fail_product": "high", "fail_agent": "low", "blocked": "medium", "infra_error": "medium"}
    for s in steps:
        status = str(getattr(s, "status", "") or s.get("status") or "pass") if isinstance(s, dict) else str(getattr(s, "status"))
        if status == "pass":
            continue
        step_id = getattr(s, "step_id", None) if not isinstance(s, dict) else s.get("step_id")
        plan_step = step_by_id.get(step_id)
        expected = list(getattr(plan_step, "success_criteria", []) or []) if plan_step else []
        observed = getattr(s, "detail", "") if not isinstance(s, dict) else (s.get("detail") or "")
        evidence = getattr(s, "evidence", []) if not isinstance(s, dict) else (s.get("evidence") or [])
        screenshots = [p for p in evidence if str(p).lower().endswith((".png", ".jpg", ".jpeg"))]
        excerpt = [t for t in trace_lines if t.get("step_id") == step_id][-3:]
        findings.append({
            "category": "computer_use",
            "issue": f"Step {step_id} {status}: {observed or 'failed'}",
            "severity": severity_map.get(status, "medium"),
            "confidence": 0.85,
            "description": observed,
            "location": step_id,
            "step_id": step_id,
            "expected": expected,
            "observed": observed,
            "screenshots": screenshots,
            "trace_excerpt": excerpt,
            "source_refs": source_refs,
            "suggestion": "Review action trace + screenshots; promote to bug only after human approval.",
        })
    return findings


def normalize_artifacts(*, run_id: str, run_dir: Path, summary: Any, plan: Any, checkpoints: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write manifest.json + run_report.json + findings.json + checkpoint_log.json."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    # Manifest via harness ArtifactManifest (compatible with evidence layout)
    records: List[ArtifactRecord] = []
    for p in sorted(run_dir.iterdir()):
        if p.is_file() and p.name not in {"manifest.json", "run_report.json", "findings.json", "checkpoint_log.json", "run_summary.json", "step_results.json"}:
            # Include runner artifacts + compiled plan + trace
            typ = "screenshot" if p.suffix.lower() in {".png", ".jpg", ".jpeg"} else ("trace" if p.name == "action_trace.jsonl" else classify_artifact(p.name))
            records.append(ArtifactRecord(type=typ, path=f"artifacts/{run_id}/{p.name}", filename=p.name, size_bytes=p.stat().st_size))
    # Ensure key files listed even if written after manifest creation in caller order
    for name, typ in [("compiled_test_plan.json", "json"), ("action_trace.jsonl", "trace"), ("step_results.json", "result"), ("run_summary.json", "json")]:
        p = run_dir / name
        if p.exists() and not any(r.filename == name for r in records):
            records.append(ArtifactRecord(type=typ, path=f"artifacts/{run_id}/{name}", filename=name, size_bytes=p.stat().st_size))
    manifest = ArtifactManifest(
        run_id=run_id,
        source={"executor": "gemini_computer_use", "plan_id": getattr(plan, "plan_id", (plan.get("plan_id") if isinstance(plan, dict) else None)), "executor_type": "gemini_computer_use"},
        artifacts=records,
    )
    manifest.save(run_dir / "manifest.json")
    findings = build_findings_from_run(summary=summary, plan=plan, run_dir=run_dir)
    (run_dir / "findings.json").write_text(json.dumps(findings, indent=2))
    (run_dir / "checkpoint_log.json").write_text(json.dumps({"run_id": run_id, "checkpoints": checkpoints, "updated_at": _utc_now()}, indent=2))
    report = {
        "run_id": run_id,
        "plan_id": getattr(plan, "plan_id", (plan.get("plan_id") if isinstance(plan, dict) else None)),
        "status": getattr(summary, "status", (summary.get("status") if isinstance(summary, dict) else None)),
        "started_at": getattr(summary, "started_at", None),
        "ended_at": getattr(summary, "ended_at", None),
        "summary": summary.to_dict() if hasattr(summary, "to_dict") else (summary or {}),
        "checkpoints": checkpoints,
        "findings": findings,
        "manifest": str(run_dir / "manifest.json"),
        "artifacts": [r.to_manifest_entry() for r in records],
    }
    (run_dir / "run_report.json").write_text(json.dumps(report, indent=2))
    return report


class ComputerUseHarnessRunner:
    """Orchestrated harness run: checkpoint → execute → normalize → bug review."""

    def __init__(
        self, *, artifacts_dir: Path | str = "artifacts",
        registry: Optional[ApprovalRegistry] = None,
        bug_workflow: Optional[BugFilingWorkflow] = None,
        executor_factory: Optional[Callable[..., Any]] = None,
    ):
        self.artifacts_dir = Path(artifacts_dir)
        self.plan_checkpoint = PlanCheckpoint(registry=registry)
        self.registry = self.plan_checkpoint.registry
        self.bug_workflow = bug_workflow or BugFilingWorkflow(registry=self.registry)
        self.executor_factory = executor_factory

    def run_compiled_plan(
        self, *, run_id: str, plan: Any, target_url: Optional[str] = None,
        mode: str = "local_spike", loop: str = "per_step",
        bug_approval_id: Optional[str] = None, enable_bug_review: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        obj = plan if isinstance(plan, CompiledExecutionTestPlan) else CompiledExecutionTestPlan.model_validate(plan)
        run_dir = self.artifacts_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        # 1) Plan checkpoint (prod requires human review)
        checkpoint = self.plan_checkpoint.review(run_id=run_id, plan=obj, mode=mode, artifacts_dir=self.artifacts_dir)
        checkpoints: List[Dict[str, Any]] = [{"kind": "plan_review", **checkpoint}]
        if not checkpoint.get("allowed"):
            report = {
                "run_id": run_id, "plan_id": obj.plan_id, "status": "BLOCKED",
                "checkpoints": checkpoints, "summary": {"error": checkpoint.get("reason")},
                "artifacts": [str(run_dir / "plan_checkpoint.json")],
            }
            (run_dir / "run_report.json").write_text(json.dumps(report, indent=2))
            return report
        # 2) Execute via standard executor lifecycle
        from harness.execution.base import ExecutorConfig
        from harness.execution.factory import ExecutorFactory

        cfg = ExecutorConfig(
            run_id=run_id,
            target_url=target_url or obj.sut.base_url,
            plan=obj.to_json(),
            artifacts_dir=self.artifacts_dir,
            timeout_seconds=int((obj.constraints.max_runtime_s if obj.constraints else 600) or 600),
            metadata={"mode": mode, "loop": loop, **(metadata or {})},
        )
        factory = self.executor_factory or ExecutorFactory.create_executor
        try:
            executor = factory(cfg, "gemini_computer_use")
        except TypeError:
            executor = factory(cfg)
        exec_result = executor.execute_plan()
        # 3) Load runner summary for normalization (artifacts/run-<id>/run_summary.json)
        summary_data = _load_json(run_dir / "run_summary.json")
        status = exec_result.status.value if hasattr(exec_result.status, "value") else str(exec_result.status)
        summary_obj = summary_data or {"status": status}
        # 4) Normalize artifacts + findings
        report = normalize_artifacts(run_id=run_id, run_dir=run_dir, summary=summary_obj, plan=obj, checkpoints=checkpoints)
        # Attach executor status
        report["executor_status"] = status
        report["execution_summary"] = exec_result.summary if hasattr(exec_result, "summary") else {}
        # 5) Bug-filing checkpoint (prepare only — never auto-file)
        if enable_bug_review:
            findings = report.get("findings") or []
            if findings:
                # BugReportGenerator._build_steps expects {"steps": [...]} shape.
                steps_payload = _load_json(run_dir / "step_results.json")
                wrapped_steps = steps_payload if isinstance(steps_payload, dict) else {"steps": steps_payload}
                pkg = self.bug_workflow.prepare_review(
                    approval_id=bug_approval_id or f"bug-{run_id}",
                    run_dir=run_dir,
                    findings=findings,
                    step_results=wrapped_steps,
                    environment={"executor": "gemini_computer_use", "plan_id": obj.plan_id, "target": target_url or obj.sut.base_url},
                    url=target_url or obj.sut.base_url,
                    title=f"Computer-use run {run_id}: {len(findings)} finding(s)",
                    save=True,
                )
                report["bug_review"] = {"approval_id": pkg["approval_id"], "approved": pkg["approved"], "saved": pkg.get("saved"), "report_title": (pkg.get("report") or {}).get("title")}
                checkpoints.append({"kind": "bug_review", "approval_id": pkg["approval_id"], "approved": pkg["approved"]})
                report["checkpoints"] = checkpoints
                (run_dir / "run_report.json").write_text(json.dumps(report, indent=2))
                (run_dir / "checkpoint_log.json").write_text(json.dumps({"run_id": run_id, "checkpoints": checkpoints, "updated_at": _utc_now()}, indent=2))
        return report
