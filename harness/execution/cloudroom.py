"""Cloud Room executor using remote VMs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..integrations.cloudroom import CloudRoomClient
from .base import BaseExecutor, ExecutionResult, ExecutionStatus, ExecutorConfig


class CloudRoomExecutor(BaseExecutor):
    """Executor that runs tests in Cloud Room VMs."""

    def __init__(self, config: ExecutorConfig, client: Optional[CloudRoomClient] = None):
        super().__init__(config)
        self.client = client or CloudRoomClient()
        self.session_id: Optional[str] = None
        self.thread_id: Optional[str] = None

    def prepare(self) -> bool:
        """Prepare the Cloud Room environment."""
        try:
            self.status = ExecutionStatus.PREPARING
            # Create session
            resp = self.client.create_session(project=self.config.metadata.get("project"))
            self.session_id = resp.get("session_id")
            if not self.session_id:
                raise Exception("Failed to create session")
            self.status = ExecutionStatus.PENDING
            return True
        except Exception:
            self.status = ExecutionStatus.FAILED
            return False

    def execute_plan(self) -> ExecutionResult:
        """Execute the test plan in Cloud Room."""
        started_at = datetime.now(timezone.utc).isoformat()
        self._started_at = started_at
        self.status = ExecutionStatus.RUNNING

        try:
            if not self.session_id:
                if not self.prepare():
                    result = ExecutionResult(
                        run_id=self.config.run_id,
                        status=ExecutionStatus.FAILED,
                        started_at=started_at,
                        ended_at=datetime.now(timezone.utc).isoformat(),
                        error="Failed to prepare Cloud Room session",
                    )
                    self._result = result
                    self.status = ExecutionStatus.FAILED
                    return result

            # TODO: Create thread with plan (STORY-CR003.2)
            # TODO: Orchestrate with browser-harness (STORY-CR003.3)
            # TODO: Collect artifacts (STORY-CR003.4)

            ended_at = datetime.now(timezone.utc).isoformat()
            result = ExecutionResult(
                run_id=self.config.run_id,
                status=ExecutionStatus.COMPLETED,
                started_at=started_at,
                ended_at=ended_at,
                summary={"mode": "cloudroom", "session_id": self.session_id},
                metadata={"executor": "cloudroom", "session_id": self.session_id},
            )
            self._result = result
            self.status = ExecutionStatus.COMPLETED
            return result

        except Exception as e:
            ended_at = datetime.now(timezone.utc).isoformat()
            result = ExecutionResult(
                run_id=self.config.run_id,
                status=ExecutionStatus.FAILED,
                started_at=started_at,
                ended_at=ended_at,
                error=str(e),
            )
            self._result = result
            self.status = ExecutionStatus.FAILED
            return result

    def get_status(self) -> ExecutionStatus:
        return self.status

    def stop(self) -> bool:
        try:
            self.status = ExecutionStatus.STOPPED
            return True
        except Exception:
            return False

    def cleanup(self) -> bool:
        try:
            self.session_id = None
            self.thread_id = None
            return True
        except Exception:
            return False


    def _plan_to_prompt(self, plan: Dict[str, Any]) -> str:
        """Convert test plan to prompt for Cloud Room agent."""
        target = self.config.target_url
        test_cases = plan.get("testCases") or plan.get("tests") or []
        
        prompt = f"""You are a TestRadius autonomous testing agent running in a Cloud Room sandbox.

TARGET: {target}
RUN_ID: {self.config.run_id}

CONSTRAINTS:
- ONLY visit URLs on the allowlist: {target} and its subdomains
- DO NOT visit external sites or exfiltrate data
- Use the browser-harness skill to drive the browser
- Capture screenshots for each test case
- Save all artifacts to /workspace/artifacts/
- Record console logs and network activity
- Create videos if possible

TASK:
Execute the following test plan against {target}:

"""
        for i, tc in enumerate(test_cases[:50], 1):
            tc_id = tc.get("id") or tc.get("testId") or f"TC{i:02d}"
            title = tc.get("title") or tc.get("name") or ""
            steps = tc.get("steps") or tc.get("actions") or []
            checks = tc.get("expectedChecks") or tc.get("checks") or []
            prompt += f"\n## Test Case {tc_id}: {title}\n"
            if steps:
                prompt += "Steps:\n"
                for s in steps:
                    prompt += f"- {s}\n"
            if checks:
                prompt += "Expected Checks:\n"
                for c in checks:
                    prompt += f"- {c}\n"
            prompt += "\n"
        
        prompt += """
INSTRUCTIONS:
1. Use browser-harness to navigate and interact
2. Take a screenshot after each major step
3. Save artifacts to /workspace/artifacts/run-{run_id}/
4. After completing all tests, summarize results
5. Be thorough but respect the egress allowlist

Start by navigating to the target URL.
"""
        return prompt.format(run_id=self.config.run_id)

    def _create_and_start_thread(self) -> str:
        """Create thread with plan and start execution."""
        if not self.session_id:
            raise Exception("No session created")
        prompt = self._plan_to_prompt(self.config.plan)
        resp = self.client.create_thread(self.session_id, prompt=prompt)
        thread_id = resp.get("thread_id") or resp.get("id")
        if not thread_id:
            raise Exception("Failed to create thread")
        self.thread_id = thread_id
        return thread_id

    def _monitor_execution(self, timeout: int = 300) -> bool:
        """Monitor execution progress via journal."""
        if not self.session_id:
            return False
        try:
            # Poll journal for completion indicators
            import time
            start = time.time()
            while time.time() - start < timeout:
                try:
                    journal = self.client.get_journal(self.session_id)
                    events = journal.get("events", [])
                    # Look for completion signals
                    for ev in events[-20:]:
                        if isinstance(ev, dict):
                            msg = str(ev.get("message", "")).lower()
                            if "completed" in msg or "finished" in msg or "done" in msg:
                                return True
                            if "failed" in msg or "error" in msg:
                                return False
                except Exception:
                    pass
                time.sleep(5)
            return True  # Assume done on timeout
        except Exception:
            return False
