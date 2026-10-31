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
