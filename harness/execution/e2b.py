"""E2B executor implementation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from .base import BaseExecutor, ExecutionResult, ExecutionStatus, StepResult
from ..sandbox.e2b_provider import E2BSandboxProvider


class E2BExecutor(BaseExecutor):
    """Executor that runs tests in E2B sandbox."""

    def __init__(self, config):
        super().__init__(config)
        self.provider = E2BSandboxProvider()
        self.sandbox_id = None

    def prepare(self) -> bool:
        try:
            template = self.config.extra.get("template", "base") if hasattr(self.config, "extra") else "base"
            self.sandbox_id = self.provider.create(template=template, timeout=600)
            self.status = ExecutionStatus.PREPARING
            return bool(self.sandbox_id)
        except Exception as e:
            self.status = ExecutionStatus.FAILED
            return False

    def execute_plan(self) -> ExecutionResult:
        try:
            self.status = ExecutionStatus.RUNNING
            if not self.sandbox_id:
                self.prepare()
            
            # Upload plan
            plan_json = json.dumps(self.config.plan).encode()
            self.provider.upload_file(self.sandbox_id, "/home/user/plan.json", plan_json)
            
            # Generate and run Playwright script
            script = self._generate_playwright_script()
            self.provider.upload_file(self.sandbox_id, "/home/user/test_script.py", script.encode())
            
            result = self.provider.run_command(
                self.sandbox_id, 
                "cd /app && python /home/user/test_script.py",
                timeout=300
            )
            
            artifacts = self._collect_artifacts()
            self.status = ExecutionStatus.COMPLETED
            
            return ExecutionResult(
                run_id=self.config.run_id,
                status=self.status,
                steps=[],
                artifacts=artifacts,
                logs=[result.get("stdout", ""), result.get("stderr", "")],
            )
        except Exception as e:
            self.status = ExecutionStatus.FAILED
            return ExecutionResult(
                run_id=self.config.run_id,
                status=self.status,
                steps=[],
                artifacts={},
                error=str(e),
            )

    def _generate_playwright_script(self) -> str:
        target_url = self.config.target_url
        return f'''import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('{target_url}')
        await page.screenshot(path='/home/user/screenshot.png')
        await browser.close()

asyncio.run(main())
'''

    def _collect_artifacts(self) -> Dict[str, Any]:
        artifacts = {"screenshots": [], "video_path": None, "trace_path": None}
        try:
            if self.sandbox_id:
                data = self.provider.download_file(self.sandbox_id, "/home/user/screenshot.png")
                if data:
                    out = Path(self.config.artifacts_dir) / self.config.run_id
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "screenshot.png").write_bytes(data)
                    artifacts["screenshots"].append(str(out / "screenshot.png"))
        except Exception:
            pass
        return artifacts

    def get_status(self) -> ExecutionStatus:
        return self.status

    def stop(self) -> bool:
        if self.sandbox_id:
            return self.provider.kill(self.sandbox_id)
        return True

    def cleanup(self) -> bool:
        return self.stop()
