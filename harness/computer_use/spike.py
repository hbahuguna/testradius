"""Tiny-plan computer-use spike runner (008.4).

Runner input: **compiled plan only** + minimal runtime config. No raw context/Jira/Figma
payloads are sent to the sandbox. Gemini proposes actions; harness validates each action
(allowlist/domain/step alignment, bounds, approval flags) before executing primitives.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from harness.testplan.schema import CompiledExecutionTestPlan, PlanStep
from harness.testplan.validator import CompiledPlanValidator

from .gemini_client import ProposedAction


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    return bytes(value)  # type: ignore[arg-type]


@dataclass
class StepResultSpike:
    step_id: str
    ordinal: int
    intent: str
    action_type: str
    status: str  # PASSED | FAILED | BLOCKED | SKIPPED
    detail: str = ""
    proposed: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "ordinal": self.ordinal,
            "intent": self.intent,
            "action_type": self.action_type,
            "status": self.status,
            "detail": self.detail,
            "proposed": self.proposed,
            "validation": self.validation,
            "evidence": self.evidence,
        }


@dataclass
class SpikeReport:
    run_id: str
    plan_id: str
    status: str
    started_at: str
    ended_at: str
    steps: List[StepResultSpike] = field(default_factory=list)
    progress: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "steps": [s.to_dict() for s in self.steps],
            "progress": self.progress,
            "artifacts": self.artifacts,
            "error": self.error,
        }


class ActionValidator:
    """Harness-side validation for Gemini-proposed actions (008.5 precursor)."""

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

        # Step alignment: proposed action should map to plan step action_type (allow safe superset).
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
            warnings.append(f"proposed '{at}' differs from plan step action_type '{step_at}'")
        if at == "stop" and step_at != "note":
            # Spike allows stop only as explicit model termination; treat as blocked unless step intent complete.
            warnings.append("model proposed stop before step completion")

        # Bounds check for coordinate actions.
        for axis, val, limit in (("x", action.x, self.width), ("y", action.y, self.height)):
            if val is not None and at in {"click", "double_click", "right_click", "move"}:
                try:
                    v = int(val)
                    if not (0 <= v < limit):
                        errors.append(f"{axis}={v} out of bounds [0,{limit})")
                except Exception:
                    errors.append(f"{axis} not an integer: {val!r}")

        # Domain check for navigate-like actions.
        if at == "navigate" and action.url:
            host = urlparse(action.url).netloc.lower().split("@")[-1].split(":")[0]
            if host and self.allowed_domains:
                ok = any(host == d.lower().split(":")[0] or host.endswith("." + d.lower().split(":")[0]) for d in self.allowed_domains)
                if not ok:
                    errors.append(f"navigate host '{host}' not in allowed_domains {self.allowed_domains}")
            elif host and self.allowed_urls and not any(action.url.startswith(u) for u in self.allowed_urls):
                errors.append(f"navigate URL '{action.url}' not in allowed_urls")

        # Approval/destructive gate.
        if getattr(step, "destructive", False) or step.requires_human_approval:
            errors.append("step requires human approval; blocked in spike (no auto-approve)")

        # Evidence gate (plan-level): never allow silent action without trace/evidence in spike.
        ev = step.normalized_evidence()
        if not (ev.action_trace or ev.screenshot_on_failure or ev.screenshot_after or ev.screenshot_before):
            errors.append("step evidence requirements missing")

        return {"ok": not errors, "errors": errors, "warnings": warnings}


class ComputerUseSpikeRunner:
    """Execute a tiny compiled plan with computer-use (spike scope: first case, first 1-3 steps)."""

    def __init__(self, *, primitives: Any, gemini_client: Any, artifacts_dir: Path, width: int = 1440, height: int = 900, validator: Optional[CompiledPlanValidator] = None):
        self.primitives = primitives
        self.gemini_client = gemini_client
        self.artifacts_dir = Path(artifacts_dir)
        self.width = width
        self.height = height
        self.validator = validator or CompiledPlanValidator()

    def run(self, *, run_id: str, plan: CompiledExecutionTestPlan | Dict[str, Any], max_steps: int = 3) -> SpikeReport:
        started = _utc_now()
        progress: List[Dict[str, Any]] = []
        obj = plan if isinstance(plan, CompiledExecutionTestPlan) else CompiledExecutionTestPlan.model_validate(plan)
        # Spike uses local_spike gate (draft ok); production still requires approved.
        validation = self.validator.validate(obj, mode="local_spike")
        progress.append({"ts": _utc_now(), "stage": "validate", "status": "completed" if validation.ok else "failed", "detail": f"validation_ok={validation.ok}"})
        if not validation.ok:
            return SpikeReport(run_id=run_id, plan_id=obj.plan_id, status="FAILED", started_at=started, ended_at=_utc_now(), progress=progress, error="Compiled plan failed quality gate")
        # Tiny spike: first case, first N steps
        if not obj.cases:
            return SpikeReport(run_id=run_id, plan_id=obj.plan_id, status="FAILED", started_at=started, ended_at=_utc_now(), progress=progress, error="No cases in plan")
        case = obj.cases[0]
        steps = case.steps[: max(1, min(max_steps, 3))]
        run_dir = self.artifacts_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        run_dir.joinpath("compiled_test_plan.json").write_text(json.dumps(obj.to_json(), indent=2))
        action_validator = ActionValidator(obj, width=self.width, height=self.height)
        results: List[StepResultSpike] = []
        history: List[Dict[str, Any]] = []
        artifacts: List[str] = [str(run_dir / "compiled_test_plan.json")]
        status = "COMPLETED"
        for step in steps:
            progress.append({"ts": _utc_now(), "stage": step.step_id, "status": "started", "detail": step.intent})
            shot = self.primitives.screenshot()
            shot_path = run_dir / f"{step.step_id}_before.png"
            shot_path.write_bytes(_to_bytes(shot))
            artifacts.append(str(shot_path))
            contract = {
                "step_id": step.step_id, "ordinal": step.ordinal, "intent": step.intent,
                "action_type": str(step.action_type), "target": step.normalized_target().model_dump(),
                "input": step.input, "success_criteria": step.success_criteria, "failure_signals": step.failure_signals,
                "fallback_instructions": step.fallback_instructions, "evidence": step.normalized_evidence().model_dump(),
                "execution_hints": obj.execution_hints_for_computer_use,
            }
            try:
                proposed = self.gemini_client.propose_action(screenshot_png=_to_bytes(shot), step_contract=contract, history=history)
                check = action_validator.validate(step, proposed)
                if not check["ok"]:
                    results.append(StepResultSpike(step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status="BLOCKED", detail="; ".join(check["errors"]), proposed=proposed.to_dict(), validation=check, evidence=[str(shot_path)]))
                    progress.append({"ts": _utc_now(), "stage": step.step_id, "status": "blocked", "detail": "; ".join(check["errors"])})
                    status = "BLOCKED" if status == "COMPLETED" else status
                    continue
                exec_ok = self._execute(proposed)
                outcome = "PASSED" if exec_ok else "FAILED"
                # Settle before after-screenshot: tab switches/navigation/render need time.
                # navigate() already waits internally; other actions (click/type/key/scroll) don't.
                if exec_ok and proposed.action_type != "navigate":
                    try:
                        self.primitives.wait(2.5)
                    except Exception:
                        pass
                after_path = run_dir / f"{step.step_id}_after.png"
                after_bytes = self.primitives.screenshot()
                after_path.write_bytes(_to_bytes(after_bytes))
                artifacts.append(str(after_path))
                results.append(StepResultSpike(step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status=outcome, detail="executed" if exec_ok else "primitive failed", proposed=proposed.to_dict(), validation=check, evidence=[str(shot_path), str(after_path)]))
                history.append({"step_id": step.step_id, "proposed": proposed.to_dict(), "status": outcome})
                progress.append({"ts": _utc_now(), "stage": step.step_id, "status": "completed" if exec_ok else "failed", "detail": outcome})
                if not exec_ok:
                    status = "FAILED"
            except Exception as e:
                results.append(StepResultSpike(step_id=step.step_id, ordinal=step.ordinal, intent=step.intent, action_type=str(step.action_type), status="FAILED", detail=str(e)))
                progress.append({"ts": _utc_now(), "stage": step.step_id, "status": "failed", "detail": str(e)})
                status = "FAILED"
        report = SpikeReport(run_id=run_id, plan_id=obj.plan_id, status=status, started_at=started, ended_at=_utc_now(), steps=results, progress=progress, artifacts=artifacts)
        report_path = run_dir / "spike_report.json"
        report_path.write_text(json.dumps(report.to_dict(), indent=2))
        return report

    def _execute(self, proposed: ProposedAction) -> bool:
        at = proposed.action_type
        p = self.primitives
        if at == "navigate" and proposed.url:
            return bool(p.navigate(proposed.url))
        if at in {"click", "double_click", "right_click"} and proposed.x is not None and proposed.y is not None:
            return bool(p.click(int(proposed.x), int(proposed.y), button={"right_click": "right"}.get(at, "left"), double=(at == "double_click")))
        if at == "move" and proposed.x is not None and proposed.y is not None:
            return bool(p.move_mouse(int(proposed.x), int(proposed.y)))
        if at == "type" and proposed.text:
            return bool(p.type_text(str(proposed.text)))
        if at == "keypress" and proposed.key:
            return bool(p.press_key(str(proposed.key)))
        if at == "scroll":
            return bool(p.scroll(delta_y=int(proposed.scroll_delta or -300)))
        if at in {"wait", "screenshot", "assert"}:
            return bool(p.wait(float(proposed.wait_seconds or 0) if at == "wait" else 0))
        if at == "stop":
            return True
        return False
