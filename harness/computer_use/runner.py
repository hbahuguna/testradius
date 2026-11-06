"""Full computer-use execution runner (008.5).

Default loop is **structured per-step (Option B)**: for each plan step, capture
screenshot → Gemini proposes ONE action for the step contract → harness validates →
execute → observe/assert → record + evidence. ``mode="whole_plan"`` (Option A,
whole-plan prompt) is a clearly labeled non-default spike mode kept for comparison.

Input is **only** ``compiled_test_plan.json`` + runtime config/env refs. No raw
Jira/Figma/PRD/context payloads enter the sandbox or the plan artifact.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from harness.policy.redaction import Redactor
from harness.testplan.schema import CompiledExecutionTestPlan, PlanStep
from harness.testplan.validator import CompiledPlanValidator

from .action_schema import SUPPORTED_ACTIONS, ProposedAction, execute_action
from .ref_resolver import build_test_data_index, redact_value, resolve_value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunnerStepResult:
    run_id: str
    case_id: str
    step_id: str
    ordinal: int
    intent: str
    action_type: str
    status: str  # pass | fail_product | fail_agent | blocked | infra_error
    detail: str = ""
    proposed: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    attempts: int = 0
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id, "case_id": self.case_id, "step_id": self.step_id,
            "ordinal": self.ordinal, "intent": self.intent, "action_type": self.action_type,
            "status": self.status, "detail": self.detail, "proposed": self.proposed,
            "validation": self.validation, "evidence": self.evidence, "attempts": self.attempts,
            "started_at": self.started_at, "ended_at": self.ended_at, "duration_ms": self.duration_ms,
        }


@dataclass
class RunSummary:
    run_id: str
    plan_id: str
    status: str  # COMPLETED | FAILED | BLOCKED | INCOMPLETE
    started_at: str
    ended_at: str
    total_steps: int = 0
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    infra_errors: int = 0
    steps: List[RunnerStepResult] = field(default_factory=list)
    progress: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    mode: str = "per_step"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id, "plan_id": self.plan_id, "status": self.status,
            "started_at": self.started_at, "ended_at": self.ended_at,
            "total_steps": self.total_steps, "passed": self.passed, "failed": self.failed,
            "blocked": self.blocked, "infra_errors": self.infra_errors,
            "steps": [s.to_dict() for s in self.steps], "progress": self.progress,
            "artifacts": self.artifacts, "mode": self.mode, "error": self.error,
        }


class StepActionValidator:
    """Harness gates for Gemini proposals: allowlist, domain/safety, step alignment, bounds."""

    def __init__(self, plan: CompiledExecutionTestPlan, *, width: int = 1440, height: int = 900):
        self.plan = plan
        self.width = width
        self.height = height
        self.allowed_domains = list(plan.constraints.allowed_domains or [])
        self.allowed_urls = list(plan.constraints.allowed_urls or [])

    def validate(self, step: PlanStep, action: ProposedAction) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        at = action.action_type
        if at not in SUPPORTED_ACTIONS:
            errors.append(f"unsupported action_type '{at}'")
        allowed_map = {
            "navigate": {"navigate", "screenshot", "wait", "assert"},
            "click": {"click", "double_click", "move", "screenshot", "wait", "assert"},
            "type": {"type", "keypress", "screenshot", "wait", "assert"},
            "select": {"click", "type", "keypress", "screenshot", "wait"},
            "scroll": {"scroll", "wait", "assert", "screenshot"},
            "hover": {"move", "screenshot", "wait"},
            "keypress": {"keypress", "type", "wait", "assert"},
            "wait": {"wait", "screenshot", "assert"},
            "assert": {"assert", "screenshot", "wait"},
            "upload_ref": {"screenshot", "wait", "assert"},
            "note": {"screenshot", "wait", "assert", "stop"},
        }
        step_at = str(step.action_type)
        if at not in allowed_map.get(step_at, {"navigate", "click", "type", "wait", "assert", "screenshot", "stop"}):
            warnings.append(f"proposed '{at}' differs from step action_type '{step_at}'")
        if at == "stop" and step_at != "note":
            warnings.append("model proposed stop before step completion")
        for axis, val, limit in (("x", action.x, self.width), ("y", action.y, self.height)):
            if val is not None and at in {"click", "double_click", "right_click", "move"}:
                try:
                    v = int(val)
                    if not (0 <= v < limit):
                        errors.append(f"{axis}={v} out of bounds [0,{limit})")
                except Exception:
                    errors.append(f"{axis} not an integer: {val!r}")
        if at == "navigate" and action.url:
            host = urlparse(action.url).netloc.lower().split("@")[-1].split(":")[0]
            if host and self.allowed_domains:
                ok = any(host == d.lower().split(":")[0] or host.endswith("." + d.lower().split(":")[0]) for d in self.allowed_domains)
                if not ok:
                    errors.append(f"navigate host '{host}' not in allowed_domains")
            elif host and self.allowed_urls and not any(action.url.startswith(u) for u in self.allowed_urls):
                errors.append(f"navigate URL not in allowed_urls")
        if getattr(step, "destructive", False) or step.requires_human_approval:
            errors.append("step requires human approval; blocked")
        ev = step.normalized_evidence()
        if not (ev.action_trace or ev.screenshot_on_failure or ev.screenshot_after or ev.screenshot_before):
            errors.append("step evidence requirements missing")
        return {"ok": not errors, "errors": errors, "warnings": warnings}


class ComputerUseRunner:
    """Execute a compiled plan step-by-step with Gemini computer-use."""

    def __init__(
        self, *, primitives: Any, gemini_client: Any, artifacts_dir: Path | str,
        width: int = 1440, height: int = 900,
        validator: Optional[CompiledPlanValidator] = None,
        redactor: Optional[Redactor] = None,
        env: Dict[str, Any] | None = None,
        secret_resolver: Optional[Callable[[str], str | None]] = None,
        mode: str = "production", max_actions_per_step: int = 6,
    ):
        self.primitives = primitives
        self.gemini_client = gemini_client
        self.artifacts_dir = Path(artifacts_dir)
        self.width = width
        self.height = height
        self.validator = validator or CompiledPlanValidator()
        self.redactor = redactor or Redactor()
        self.env = env
        self.secret_resolver = secret_resolver
        self.mode = mode
        self.max_actions_per_step = max(1, int(max_actions_per_step))

    def run(self, *, run_id: str, plan: CompiledExecutionTestPlan | Dict[str, Any], loop: str = "per_step") -> RunSummary:
        if loop not in {"per_step", "whole_plan"}:
            raise ValueError(f"Unknown loop mode '{loop}' (expected per_step|whole_plan)")
        started = _utc_now()
        t0 = time.time()
        obj = plan if isinstance(plan, CompiledExecutionTestPlan) else CompiledExecutionTestPlan.model_validate(plan)
        progress: List[Dict[str, Any]] = []
        validation = self.validator.validate(obj, mode=self.mode)
        progress.append({"ts": _utc_now(), "stage": "validate", "status": "completed" if validation.ok else "failed", "detail": f"validation_ok={validation.ok}"})
        if not validation.ok:
            return RunSummary(run_id=run_id, plan_id=obj.plan_id, status="FAILED", started_at=started, ended_at=_utc_now(), progress=progress, mode=loop, error="Compiled plan failed quality gate")
        # Run budget from plan constraints
        max_runtime = int((obj.constraints.max_runtime_s if obj.constraints else 600) or 600)
        # Spike-label for whole-plan mode (non-default).
        if loop == "whole_plan":
            progress.append({"ts": _utc_now(), "stage": "mode", "status": "started", "detail": "Option A whole-plan prompt (non-default spike mode)"})
        run_dir = self.artifacts_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        run_dir.joinpath("compiled_test_plan.json").write_text(json.dumps(obj.to_json(), indent=2))
        trace_path = run_dir / "action_trace.jsonl"
        trace = trace_path.open("w", encoding="utf-8")
        trace.close()
        artifacts: List[str] = [str(run_dir / "compiled_test_plan.json")]

        def emit_trace(rec: Dict[str, Any]) -> None:
            safe = json.loads(json.dumps(rec, default=str))
            with trace_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(safe, ensure_ascii=False) + "\n")

        test_data = build_test_data_index(obj)
        action_validator = StepActionValidator(obj, width=self.width, height=self.height)
        results: List[RunnerStepResult] = []
        history: List[Dict[str, Any]] = []
        stopped = False
        for case in obj.cases:
            if stopped:
                break
            for step in case.steps:
                if stopped:
                    break
                if time.time() - t0 > max_runtime:
                    progress.append({"ts": _utc_now(), "stage": "run", "status": "failed", "detail": "per-run timeout exceeded"})
                    results.append(RunnerStepResult(run_id=run_id, case_id=case.case_id, step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status="blocked", detail="per-run timeout exceeded"))
                    stopped = True
                    break
                result = self._run_step(run_id=run_id, plan=obj, case=case, step=step, run_dir=run_dir, test_data=test_data, action_validator=action_validator, history=history, loop=loop, emit_trace=emit_trace, artifacts=artifacts, progress=progress)
                results.append(result)
                history.append({"step_id": step.step_id, "status": result.status, "attempts": result.attempts})
                # Repeated-failure stop: fail_agent twice in a row on same step handled in step; here stop_case handling:
                if result.status in {"fail_product", "fail_agent"} and str(step.on_fail) == "stop_case":
                    progress.append({"ts": _utc_now(), "stage": case.case_id, "status": "stopped", "detail": f"stop_case after {step.step_id}"})
                    stopped = True
                    break
        # Summarize
        passed = sum(1 for r in results if r.status == "pass")
        blocked = sum(1 for r in results if r.status == "blocked")
        infra = sum(1 for r in results if r.status == "infra_error")
        failed = sum(1 for r in results if r.status in {"fail_product", "fail_agent"})
        status = "COMPLETED" if passed == len(results) and results else ("BLOCKED" if blocked and not passed and not failed else ("FAILED" if failed or infra else ("INCOMPLETE" if not results else "BLOCKED")))
        if all(r.status in {"pass", "fail_product"} for r in results) and results:
            status = "COMPLETED"
        summary = RunSummary(run_id=run_id, plan_id=obj.plan_id, status=status, started_at=started, ended_at=_utc_now(), total_steps=len(obj.all_steps()), passed=passed, failed=failed, blocked=blocked, infra_errors=infra, steps=results, progress=progress, artifacts=artifacts, mode=loop)
        run_dir.joinpath("step_results.json").write_text(json.dumps([r.to_dict() for r in results], indent=2))
        run_dir.joinpath("run_summary.json").write_text(json.dumps(summary.to_dict(), indent=2))
        summary.artifacts = sorted(set(artifacts + [str(run_dir / "action_trace.jsonl"), str(run_dir / "step_results.json"), str(run_dir / "run_summary.json")]))
        run_dir.joinpath("run_summary.json").write_text(json.dumps(summary.to_dict(), indent=2))
        return summary

    def _run_step(self, *, run_id: str, plan: CompiledExecutionTestPlan, case: Any, step: PlanStep, run_dir: Path, test_data: Dict[str, Any], action_validator: StepActionValidator, history: List[Dict[str, Any]], loop: str, emit_trace: Any, artifacts: List[str], progress: List[Dict[str, Any]]) -> RunnerStepResult:
        step_t0 = time.time()
        started = _utc_now()
        ev = step.normalized_evidence()
        resolved_input, blocked_secret = resolve_value(step.input, test_data=test_data, env=self.env, secret_resolver=self.secret_resolver, redactor=self.redactor)
        if blocked_secret:
            progress.append({"ts": _utc_now(), "stage": step.step_id, "status": "blocked", "detail": "secret ref requires approved resolver"})
            return RunnerStepResult(run_id=run_id, case_id=case.case_id, step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status="blocked", detail="Secret ref without approved resolver", attempts=0, started_at=started, ended_at=_utc_now(), duration_ms=int((time.time() - step_t0) * 1000))
        max_actions = min(self.max_actions_per_step, max(int(getattr(step, "max_attempts", 2) or 2), 1) + 2)
        last_detail, last_check = "", {}
        for attempt in range(1, max_actions + 1):
            if time.time() - step_t0 > int(getattr(step, "timeout_s", 30) or 30):
                last_detail = "per-step timeout exceeded"
                break
            before_path = None
            try:
                shot = self.primitives.screenshot()
                if ev.screenshot_before or attempt == 1:
                    before_path = run_dir / f"{step.step_id}_attempt{attempt}_before.png"
                    before_path.write_bytes(shot if isinstance(shot, bytes) else bytes(shot))
                    artifacts.append(str(before_path))
                contract = {
                    "step_id": step.step_id, "ordinal": step.ordinal, "intent": step.intent,
                    "action_type": str(step.action_type), "loop": loop,
                    "target": step.normalized_target().model_dump(),
                    "input": redact_value(resolved_input, self.redactor),
                    "success_criteria": step.success_criteria, "failure_signals": step.failure_signals,
                    "fallback_instructions": step.fallback_instructions if attempt == 1 else (step.fallback_instructions + [f"Previous attempt {attempt-1} failed: {last_detail}"]),
                    "execution_hints": plan.execution_hints_for_computer_use,
                }
                proposed = self.gemini_client.propose_action(screenshot_png=shot if isinstance(shot, bytes) else bytes(shot), step_contract=contract, history=history)
                check = action_validator.validate(step, proposed)
                last_check = check
                emit_trace({"ts": _utc_now(), "run_id": run_id, "case_id": case.case_id, "step_id": step.step_id, "attempt": attempt, "proposed": proposed.to_dict(), "validation": check, "screenshot_before": str(before_path) if before_path else None, "screenshot_after": None, "executed": False, "observation": {"stage": "proposed"}, "loop": loop})
                if not check["ok"]:
                    last_detail = "; ".join(check["errors"]) or "validation blocked"
                    # Validation-blocked retries count as agent failure; continue to fallback.
                    if attempt >= max_actions:
                        status = "blocked" if any("human approval" in e.lower() or "allowed_domains" in e for e in check["errors"]) else "fail_agent"
                        return RunnerStepResult(run_id=run_id, case_id=case.case_id, step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status=status, detail=last_detail, proposed=proposed.to_dict(), validation=check, evidence=[str(before_path)] if before_path else [], attempts=attempt, started_at=started, ended_at=_utc_now(), duration_ms=int((time.time() - step_t0) * 1000))
                    continue
                exec_ok = execute_action(proposed, self.primitives)
                after_path = None
                observe_bytes = None
                try:
                    observe_bytes = self.primitives.screenshot()
                    if ev.screenshot_after or not exec_ok:
                        after_path = run_dir / f"{step.step_id}_attempt{attempt}_after.png"
                        after_path.write_bytes(observe_bytes if isinstance(observe_bytes, bytes) else bytes(observe_bytes))
                        artifacts.append(str(after_path))
                except Exception:
                    observe_bytes = shot
                emit_trace({"ts": _utc_now(), "run_id": run_id, "case_id": case.case_id, "step_id": step.step_id, "attempt": attempt, "executed": exec_ok, "screenshot_after": str(after_path) if after_path else None, "observation": {"passed": bool(exec_ok), "detail": "primitive executed" if exec_ok else "primitive failed"}})
                if not exec_ok:
                    last_detail = "primitive execution failed"
                    if attempt >= max_actions:
                        return RunnerStepResult(run_id=run_id, case_id=case.case_id, step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status="infra_error", detail=last_detail, proposed=proposed.to_dict(), validation=check, evidence=[str(after_path)] if after_path else [], attempts=attempt, started_at=started, ended_at=_utc_now(), duration_ms=int((time.time() - step_t0) * 1000))
                    continue
                # Observe/assert: mock defaults to pass; live assess via optional hook if provided.
                passed = True
                if observe_bytes is not None and hasattr(self.gemini_client, "assess"):
                    try:
                        passed = bool(self.gemini_client.assess(screenshot_png=observe_bytes if isinstance(observe_bytes, bytes) else bytes(observe_bytes), step_contract=contract, history=history))
                    except Exception:
                        passed = False
                emit_trace({"ts": _utc_now(), "run_id": run_id, "case_id": case.case_id, "step_id": step.step_id, "attempt": attempt, "observation": {"passed": passed, "detail": "observe/assert passed" if passed else "observe/assert failed: success_criteria not met"}, "result": "pass" if passed else "fail_product"})
                if passed:
                    evidence = [str(before_path)] if before_path else []
                    if after_path:
                        evidence.append(str(after_path))
                    progress.append({"ts": _utc_now(), "stage": step.step_id, "status": "completed", "detail": f"attempt {attempt} passed"})
                    return RunnerStepResult(run_id=run_id, case_id=case.case_id, step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status="pass", detail="Executed and observed", proposed=proposed.to_dict(), validation=check, evidence=evidence, attempts=attempt, started_at=started, ended_at=_utc_now(), duration_ms=int((time.time() - step_t0) * 1000))
                last_detail = "observe/assert did not meet success_criteria"
                if attempt >= max_actions:
                    return RunnerStepResult(run_id=run_id, case_id=case.case_id, step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status="fail_product", detail=last_detail, proposed=proposed.to_dict(), validation=check, evidence=[str(after_path)] if after_path else [], attempts=attempt, started_at=started, ended_at=_utc_now(), duration_ms=int((time.time() - step_t0) * 1000))
            except Exception as e:
                last_detail = f"{type(e).__name__}: {e}"
                emit_trace({"ts": _utc_now(), "run_id": run_id, "step_id": step.step_id, "attempt": attempt, "exception": str(e)})
                if attempt >= max_actions:
                    return RunnerStepResult(run_id=run_id, case_id=case.case_id, step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status="infra_error", detail=last_detail, attempts=attempt, started_at=started, ended_at=_utc_now(), duration_ms=int((time.time() - step_t0) * 1000))
        return RunnerStepResult(run_id=run_id, case_id=case.case_id, step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status="fail_agent", detail=last_detail or "exhausted retries", validation=last_check, attempts=max_actions, started_at=started, ended_at=_utc_now(), duration_ms=int((time.time() - step_t0) * 1000))
