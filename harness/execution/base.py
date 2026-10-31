"""Abstract base class for test executors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class ExecutionStatus(str, Enum):
    """Status of an execution."""

    PENDING = "PENDING"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    TIMEOUT = "TIMEOUT"


@dataclass
class StepResult:
    """Result of executing a single test step."""

    step_id: str
    test_case_id: str
    title: str
    status: str = "PENDING"
    duration_ms: Optional[int] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    error: Optional[str] = None
    screenshots: List[str] = field(default_factory=list)
    assertions: List[Dict[str, Any]] = field(default_factory=list)
    logs: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ExecutionResult:
    """Result of a complete execution."""

    run_id: str
    status: ExecutionStatus
    started_at: str
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    steps: List[StepResult] = field(default_factory=list)
    evidence_dir: Optional[Path] = None
    screenshots: List[Path] = field(default_factory=list)
    video_path: Optional[Path] = None
    trace_path: Optional[Path] = None
    console_logs: List[Dict[str, Any]] = field(default_factory=list)
    network_logs: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "steps": [
                {
                    "step_id": s.step_id,
                    "test_case_id": s.test_case_id,
                    "title": s.title,
                    "status": s.status,
                    "duration_ms": s.duration_ms,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "error": s.error,
                    "screenshots": s.screenshots,
                    "assertions": s.assertions,
                    "logs": s.logs,
                }
                for s in self.steps
            ],
            "evidence_dir": str(self.evidence_dir) if self.evidence_dir else None,
            "screenshots": [str(s) for s in self.screenshots],
            "video_path": str(self.video_path) if self.video_path else None,
            "trace_path": str(self.trace_path) if self.trace_path else None,
            "console_logs": self.console_logs,
            "network_logs": self.network_logs,
            "summary": self.summary,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class ExecutorConfig:
    """Configuration for an executor."""

    run_id: str
    target_url: str
    plan: Dict[str, Any]
    artifacts_dir: Path = field(default_factory=lambda: Path("artifacts"))
    timeout_seconds: int = 600
    headless: bool = True
    record_video: bool = True
    capture_screenshots: bool = True
    capture_traces: bool = True
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure artifacts_dir is a Path."""
        if isinstance(self.artifacts_dir, str):
            self.artifacts_dir = Path(self.artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


class BaseExecutor(ABC):
    """Abstract base class for all test executors."""

    def __init__(self, config: ExecutorConfig):
        self.config = config
        self.status = ExecutionStatus.PENDING
        self._started_at: Optional[str] = None
        self._result: Optional[ExecutionResult] = None

    @abstractmethod
    def prepare(self) -> bool:
        pass

    @abstractmethod
    def execute_plan(self) -> ExecutionResult:
        pass

    @abstractmethod
    def get_status(self) -> ExecutionStatus:
        pass

    @abstractmethod
    def stop(self) -> bool:
        pass

    @abstractmethod
    def cleanup(self) -> bool:
        pass

    def get_result(self) -> Optional[ExecutionResult]:
        return self._result

    def is_running(self) -> bool:
        return self.status in (ExecutionStatus.PREPARING, ExecutionStatus.RUNNING)

    def is_complete(self) -> bool:
        return self.status in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.STOPPED,
            ExecutionStatus.TIMEOUT,
        )
