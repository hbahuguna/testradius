"""E2B executor implementation."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .base import BaseExecutor, ExecutionResult, ExecutionStatus, StepResult
from ..adapters.playwright.bootstrap import ensure_playwright_ready
from ..adapters.playwright.generator import PlaywrightScriptGenerator
from ..e2b.artifacts import SandboxArtifactCollector, classify_artifact
from ..sandbox.delivery import RuntimeConfig, deliver_plan_and_config
from ..sandbox.e2b_provider import E2BSandboxProvider


class E2BExecutor(BaseExecutor):
    """Executor that runs tests in E2B sandbox."""

    def __init__(self, config):
        super().__init__(config)
        self.provider = E2BSandboxProvider()
        self.sandbox_id = None

    def prepare(self) -> bool:
        try:
            template = (
                self.config.metadata.get("template")
                if hasattr(self.config, "metadata")
                else None
            ) or os.environ.get("E2B_PLAYWRIGHT_TEMPLATE", "playwright-chromium")
            self.sandbox_id = self.provider.create(template=template, timeout=600)
            if self.config.metadata.get("auto_bootstrap", True):
                ensure_playwright_ready(self.provider, self.sandbox_id)
            self.status = ExecutionStatus.PREPARING
            return bool(self.sandbox_id)
        except Exception as e:
            self.status = ExecutionStatus.FAILED
            return False

    def execute_plan(self) -> ExecutionResult:
        started_at = datetime.now(timezone.utc).isoformat()
        self._started_at = started_at
        self.status = ExecutionStatus.RUNNING

        try:
            if not self.sandbox_id:
                if not self.prepare():
                    result = ExecutionResult(
                        run_id=self.config.run_id,
                        status=ExecutionStatus.FAILED,
                        started_at=started_at,
                        ended_at=datetime.now(timezone.utc).isoformat(),
                        error="Failed to prepare E2B sandbox",
                    )
                    self._result = result
                    self.status = ExecutionStatus.FAILED
                    return result

            # Deliver compiled test plan and minimal runtime config safely
            runtime_config = RuntimeConfig(
                run_id=self.config.run_id,
                target_url=self.config.target_url,
                env=str(self.config.metadata.get("env", "staging")),
                allowed_domains=list(self.config.metadata.get("allowed_domains", [])),
                timeout_s=self.config.timeout_seconds,
                metadata=self.config.metadata,
            )
            self.delivery_result = deliver_plan_and_config(
                provider=self.provider,
                sandbox_id=self.sandbox_id,
                plan=self.config.plan,
                runtime_config=runtime_config,
                destination_dir="/home/user",
                verify=True,
                alias_legacy_plan=True,
            )

            # Generate and run Playwright script from compiled plan schema
            script = self._generate_playwright_script()
            self.provider.upload_file(self.sandbox_id, "/home/user/test_script.py", script.encode("utf-8"))

            result = self.provider.run_command(
                self.sandbox_id,
                "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python3 /home/user/test_script.py",
                timeout=self.config.timeout_seconds,
            )

            artifacts, steps = self._collect_artifacts()
            ended_at = datetime.now(timezone.utc).isoformat()
            self.status = ExecutionStatus.COMPLETED

            result_obj = ExecutionResult(
                run_id=self.config.run_id,
                status=self.status,
                started_at=started_at,
                ended_at=ended_at,
                steps=steps,
                screenshots=[Path(p) for p in artifacts.get("screenshots", [])],
                video_path=Path(artifacts["video_path"]) if artifacts.get("video_path") else None,
                trace_path=Path(artifacts["trace_path"]) if artifacts.get("trace_path") else None,
                console_logs=[{"source": "sandbox", "message": result.get("stdout", "")}],
                summary={
                    "mode": "e2b",
                    "sandbox_id": self.sandbox_id,
                    "plan_id": getattr(self.delivery_result, "plan_id", None),
                    "total_steps": len(steps),
                    "passed_steps": sum(1 for s in steps if s.status == "PASSED"),
                    "failed_steps": sum(1 for s in steps if s.status == "FAILED"),
                },
                metadata={
                    "executor": "e2b",
                    "sandbox_id": self.sandbox_id,
                    "delivery": asdict(self.delivery_result) if hasattr(self, "delivery_result") else {},
                },
            )
            self._result = result_obj
            return result_obj
        except Exception as e:
            self.status = ExecutionStatus.FAILED
            ended_at = datetime.now(timezone.utc).isoformat()
            result_obj = ExecutionResult(
                run_id=self.config.run_id,
                status=self.status,
                started_at=started_at,
                ended_at=ended_at,
                error=str(e),
                metadata={"executor": "e2b", "sandbox_id": self.sandbox_id},
            )
            self._result = result_obj
            return result_obj

    def _generate_playwright_script(self) -> str:
        generator = PlaywrightScriptGenerator()
        return generator.generate(
            plan=self.config.plan,
            target_url=self.config.target_url,
            artifacts_dir="/home/user/artifacts",
            record_trace=self.config.capture_traces,
            record_video=self.config.record_video,
        )

    def _collect_artifacts(self) -> tuple[Dict[str, Any], List[StepResult]]:
        artifacts: Dict[str, Any] = {"screenshots": [], "video_path": None, "trace_path": None, "manifest_path": None}
        steps: List[StepResult] = []
        if not self.sandbox_id:
            return artifacts, steps

        out_dir = Path(self.config.artifacts_dir) / self.config.run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # Collect/download evidence from sandbox and write manifest (STORY-E2B-004.1).
        collector = SandboxArtifactCollector(
            provider=self.provider,
            sandbox_id=self.sandbox_id,
            run_id=self.config.run_id,
            artifacts_root=Path(self.config.artifacts_dir),
            include_extended_manifest=True,
        )
        manifest = collector.collect(
            remote_paths=[
                "/home/user/artifacts/step_results.json",
                "/home/user/artifacts/trace.zip",
                "/home/user/screenshot.png",
            ],
            discover_dirs=["/home/user/artifacts", "/home/user"],
        )
        artifacts["manifest_path"] = str(out_dir / "manifest.json")

        # Build artifacts summary and steps from collected/local files.
        by_remote = {rec.remote_path: rec for rec in manifest.artifacts if rec.remote_path}
        by_name = {rec.filename: rec for rec in manifest.artifacts}

        step_results_local = out_dir / "step_results.json"
        parsed: Dict[str, Any] = {}
        if step_results_local.exists():
            try:
                parsed = json.loads(step_results_local.read_text(encoding="utf-8"))
            except Exception:
                parsed = {}

        for s in parsed.get("steps", []) or []:
            screenshot_remote = s.get("screenshot")
            step_screenshots: List[str] = []
            if screenshot_remote:
                rec = by_remote.get(str(screenshot_remote))
                if rec:
                    local_img = out_dir / rec.filename
                    if local_img.exists():
                        step_screenshots.append(str(local_img))
                else:
                    local_fallback = out_dir / Path(str(screenshot_remote)).name
                    if local_fallback.exists():
                        step_screenshots.append(str(local_fallback))
            for extra in s.get("screenshots") or []:
                rec = by_remote.get(str(extra))
                local_extra = (out_dir / rec.filename) if rec else (out_dir / Path(str(extra)).name)
                if local_extra.exists() and str(local_extra) not in step_screenshots:
                    step_screenshots.append(str(local_extra))

            steps.append(
                StepResult(
                    step_id=str(s.get("step_id", "")),
                    test_case_id=str(s.get("case_id", "TC")),
                    title=str(s.get("intent", s.get("step_id", ""))),
                    status=str(s.get("status", "COMPLETED")),
                    duration_ms=s.get("duration_ms"),
                    error=s.get("error"),
                    screenshots=step_screenshots,
                )
            )

        for rec in manifest.artifacts:
            local = out_dir / rec.filename
            if not local.exists():
                continue
            local_str = str(local)
            if rec.type == "screenshot" and local_str not in artifacts["screenshots"]:
                artifacts["screenshots"].append(local_str)
            elif rec.type == "video" and not artifacts.get("video_path"):
                artifacts["video_path"] = local_str
            elif rec.type == "trace" and not artifacts.get("trace_path"):
                # Prefer trace.zip naming
                if rec.filename == "trace.zip" or artifacts.get("trace_path") is None:
                    artifacts["trace_path"] = local_str

        # Preserve legacy/fallback expectations
        legacy = out_dir / "screenshot.png"
        if legacy.exists() and str(legacy) not in artifacts["screenshots"]:
            artifacts["screenshots"].append(str(legacy))
        trace = out_dir / "trace.zip"
        if trace.exists():
            artifacts["trace_path"] = str(trace)

        return artifacts, steps

    def get_status(self) -> ExecutionStatus:
        return self.status

    def stop(self) -> bool:
        if self.sandbox_id:
            return self.provider.kill(self.sandbox_id)
        return True

    def cleanup(self) -> bool:
        return self.stop()
