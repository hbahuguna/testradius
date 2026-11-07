"""Computer-use executor bridging compiled plans to the standard harness (008.6).

Executor type names (finalized): ``gemini_computer_use`` (canonical) and
``compiled_plan`` (alias). Both resolve to :class:`ComputerUseExecutor` via
``harness/execution/factory.py`` (API/CLI ``EXECUTOR_TYPE`` / ``EXECUTOR``).

Lifecycle matches other executors (``BaseExecutor``): ``prepare`` (sandbox/mock),
``execute_plan`` (plan → artifacts/run-<id>/ + ``ExecutionResult``), ``cleanup``.
Live E2B/Gemini paths are env-dependent; mock paths run offline for tests/demos.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseExecutor, ExecutionResult, ExecutionStatus, StepResult


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ComputerUseExecutor(BaseExecutor):
    """Execute a compiled test plan with Gemini computer-use in E2B desktop."""

    def __init__(self, config: Any, **kwargs: Any):
        super().__init__(config)
        self.provider = None
        self.sandbox_id: Optional[str] = None
        self.primitives = None
        self.gemini_client = None
        self._mock = bool((getattr(config, "metadata", None) or {}).get("mock", True))

    def _mode(self) -> str:
        return str((self.config.metadata or {}).get("mode", self.config.metadata.get("mode", "local_spike")))

    def _loop(self) -> str:
        return str((self.config.metadata or {}).get("loop", "per_step"))

    def _use_mock(self) -> bool:
        meta = self.config.metadata or {}
        if meta.get("mock") is True:
            return True
        if meta.get("mock") is False:
            return False
        # Default to mock when live credentials absent (offline-safe).
        import os
        has_e2b = bool(os.environ.get("E2B_API_KEY"))
        has_gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        return not (has_e2b and has_gemini)

    def prepare(self) -> bool:
        try:
            self.status = ExecutionStatus.PREPARING
            if self._use_mock():
                from harness.computer_use.gemini_client import MockGeminiComputerUseClient
                from harness.computer_use.primitives import MockComputerUsePrimitives

                meta = self.config.metadata or {}
                script = meta.get("mock_script") or [
                    {"action_type": "navigate", "url": (self.config.plan or {}).get("sut", {}).get("base_url") or self.config.target_url, "reason": "Open target"},
                    {"action_type": "assert", "reason": "Observe success criteria"},
                    {"action_type": "click", "x": 720, "y": 420, "reason": "Click primary CTA"},
                ]
                self.primitives = MockComputerUsePrimitives(width=int(meta.get("width", 1440)), height=int(meta.get("height", 900)))
                self.gemini_client = MockGeminiComputerUseClient(script=list(script), assess_pass=bool(meta.get("assess_pass", True)))
                self.status = ExecutionStatus.PREPARING
                return True
            # Live path (env-dependent).
            from harness.computer_use.config import ComputerUseConfig
            from harness.computer_use.gemini_client import GeminiComputerUseClient
            from harness.computer_use.primitives import E2BDesktopPrimitives
            from harness.sandbox.e2b_provider import E2BSandboxProvider

            cfg = ComputerUseConfig()
            self.provider = E2BSandboxProvider()
            self.sandbox_id = self.provider.create(template=cfg.e2b_template, timeout=cfg.sandbox_timeout_s)
            try:
                self.provider.run_command(self.sandbox_id, "bash ~/start-desktop.sh 2>&1 || true", timeout=60)
            except Exception:
                pass
            self.primitives = E2BDesktopPrimitives(provider=self.provider, sandbox_id=self.sandbox_id, display=cfg.display, width=cfg.screen_width, height=cfg.screen_height)
            self.gemini_client = GeminiComputerUseClient(model=cfg.gemini_model, api_key=cfg.resolve_gemini_key())
            return bool(self.sandbox_id)
        except Exception:
            self.status = ExecutionStatus.FAILED
            return False

    def execute_plan(self) -> ExecutionResult:
        started_at = _utc_now()
        self._started_at = started_at
        self.status = ExecutionStatus.RUNNING
        try:
            if self.primitives is None or self.gemini_client is None:
                if not self.prepare():
                    return ExecutionResult(run_id=self.config.run_id, status=ExecutionStatus.FAILED, started_at=started_at, ended_at=_utc_now(), error="Failed to prepare computer-use executor", metadata={"executor": "gemini_computer_use"})
            from harness.computer_use.runner import ComputerUseRunner

            runner = ComputerUseRunner(
                primitives=self.primitives,
                gemini_client=self.gemini_client,
                artifacts_dir=self.config.artifacts_dir,
                mode=self._mode(),
                max_actions_per_step=int((self.config.metadata or {}).get("max_actions_per_step", 6)),
            )
            summary = runner.run(run_id=self.config.run_id, plan=self.config.plan, loop=self._loop())
            ended_at = _utc_now()
            status_map = {"COMPLETED": ExecutionStatus.COMPLETED, "FAILED": ExecutionStatus.FAILED, "BLOCKED": ExecutionStatus.FAILED, "INCOMPLETE": ExecutionStatus.FAILED}
            result_status = status_map.get(summary.status, ExecutionStatus.FAILED)
            steps = [
                StepResult(
                    step_id=s.step_id,
                    test_case_id=s.case_id,
                    title=s.intent,
                    status="PASSED" if s.status == "pass" else ("FAILED" if s.status in {"fail_product", "fail_agent"} else ("SKIPPED" if s.status == "blocked" else "FAILED")),
                    duration_ms=s.duration_ms or None,
                    started_at=s.started_at or None,
                    ended_at=s.ended_at or None,
                    error=s.detail if s.status not in {"pass"} else None,
                    screenshots=list(s.evidence or []),
                    assertions=[{"criteria": s.proposed, "validation": s.validation}] if s.proposed else [],
                )
                for s in summary.steps
            ]
            screenshots = [Path(p) for art in summary.artifacts if str(p).endswith(".png") for p in [art]]
            run_dir = Path(self.config.artifacts_dir) / self.config.run_id
            self.status = result_status
            result = ExecutionResult(
                run_id=self.config.run_id,
                status=result_status,
                started_at=started_at,
                ended_at=ended_at,
                steps=steps,
                evidence_dir=run_dir,
                screenshots=screenshots,
                trace_path=run_dir / "action_trace.jsonl",
                summary={
                    "mode": summary.mode,
                    "status": summary.status,
                    "plan_id": summary.plan_id,
                    "total_steps": summary.total_steps,
                    "passed_steps": summary.passed,
                    "failed_steps": summary.failed,
                    "blocked_steps": summary.blocked,
                    "infra_errors": summary.infra_errors,
                },
                metadata={
                    "executor": "gemini_computer_use",
                    "executor_type": "gemini_computer_use",
                    "sandbox_id": self.sandbox_id,
                    "mock": self._use_mock(),
                    "run_summary_path": str(run_dir / "run_summary.json"),
                    "step_results_path": str(run_dir / "step_results.json"),
                },
            )
            self._result = result
            return result
        except Exception as e:
            self.status = ExecutionStatus.FAILED
            result = ExecutionResult(run_id=self.config.run_id, status=ExecutionStatus.FAILED, started_at=started_at, ended_at=_utc_now(), error=str(e), metadata={"executor": "gemini_computer_use"})
            self._result = result
            return result

    def get_status(self) -> ExecutionStatus:
        return self.status

    def stop(self) -> bool:
        return True

    def cleanup(self) -> bool:
        try:
            if self.provider is not None and self.sandbox_id:
                self.provider.kill(self.sandbox_id)
        except Exception:
            pass
        return True
