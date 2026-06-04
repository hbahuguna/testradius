from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExecutionMode(str, Enum):
    """Execution mode for test runs."""
    STANDARD = "standard"
    INSTRUMENTED = "instrumented"


class CoverageConfig(BaseModel):
    """Configuration for coverage instrumentation."""
    enabled: bool = True
    output_format: str = "json"
    output_file: str = ".coverage.json"
    sources: Optional[List[str]] = None
    include_patterns: Optional[List[str]] = None
    omit_patterns: Optional[List[str]] = None


class ExecutionRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    commit_sha: Optional[str] = None
    command: str
    env_vars: Dict[str, str] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.STANDARD
    coverage_config: Optional[CoverageConfig] = None


class InstrumentationRequest(BaseModel):
    """Request to run instrumentation-based TIA on a repository."""
    testbed_name: str = "py-key-value"
    project_id: int
    run_instrumented_tests: bool = True
    store_in_neo4j: bool = True
    use_cache: bool = True
    cache_ttl_hours: int = 24


class InstrumentationResponse(BaseModel):
    """Response from instrumentation run."""
    run_id: UUID
    status: TaskStatus
    testbed_name: str
    testbed_path: Optional[str] = None
    coverage_data: Optional[Dict[str, Any]] = None
    test_symbol_mappings: int = 0
    execution_time_seconds: float = 0.0
    error_message: Optional[str] = None

class ExecutionStatusResponse(BaseModel):
    run_id: UUID
    status: TaskStatus
    exit_code: Optional[int] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None

class RunResponse(BaseModel):
    id: int
    project_id: int
    commit_sha: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    run_metadata: Dict[str, Any] = Field(default_factory=dict)

class RunResultResponse(BaseModel):
    id: int
    run_id: int
    symbol_name: str
    file_path: str
    status: TaskStatus
    test_code: Optional[str] = None
    exit_code: Optional[int] = None
    log_stream: Optional[str] = None
    error_message: Optional[str] = None
    coverage_delta: Optional[float] = None

class LogEvent(BaseModel):
    run_id: UUID
    timestamp: datetime
    stream: str  # stdout or stderr
    content: str
