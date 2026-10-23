from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Phase(StrEnum):
    ISOLATE = "isolate"
    SELECT = "select"
    GENERATE = "generate"
    EXECUTE = "execute"
    PROVE = "prove"
    GATE = "gate"
    REPORT = "report"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class DependencyStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    NOT_CONFIGURED = "not_configured"


class HealthResponse(BaseModel):
    ready: bool
    aut_status: DependencyStatus
    graph_status: DependencyStatus
    version: str


class RunEvent(BaseModel):
    """Wire contract shared with the control plane (see packages/shared-types)."""

    schema_version: Literal["1"] = "1"
    run_id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    ts: str
    type: Literal["phase", "step", "tool", "verdict", "log", "stream_lagged"]
    phase: Phase | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
