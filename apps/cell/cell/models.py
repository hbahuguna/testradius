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


class RunCreateRequest(BaseModel):
    repo: str = Field(min_length=1)
    commit: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    policy: dict[str, Any] = Field(default_factory=dict)
    goal: str | None = None


class RunResponse(BaseModel):
    run_id: str
    status: RunStatus
    phase: Phase | None = None
    created_at: str
    updated_at: str
    repo: str
    commit: str
    scope: str


class CreateRunResponse(BaseModel):
    run_id: str
    run_token: str
    expires_at: str
    status: RunStatus
    phase: Phase | None = None


class EvidenceItem(BaseModel):
    evidence_id: str
    run_id: str
    kind: str
    key: str
    sha256: str
    content_type: str
    size_bytes: int
    created_at: str


class EvidenceListResponse(BaseModel):
    run_id: str
    evidence: list[EvidenceItem] = Field(default_factory=list)


class PolicyReloadResponse(BaseModel):
    reloaded: bool
    version: int
