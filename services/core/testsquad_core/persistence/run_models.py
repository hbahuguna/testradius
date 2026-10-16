from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, JSON
from testsquad_shared.api import TaskStatus

class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int
    commit_sha: str
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    run_metadata: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)

class InstrumentationRun(SQLModel, table=True):
    """One instrumentation run's coverage completeness, for GET/API + UI warnings."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    status: str = "COMPLETED"
    edge_count: int = 0
    test_files_expected: int = 0
    test_files_collectable: int = 0
    test_files_scheduled: int = 0
    test_files_instrumented: int = 0
    coverage_pct: float = 0.0
    missing_count: int = 0
    details: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class RunResult(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    symbol_name: str
    file_path: str
    status: TaskStatus
    test_code: Optional[str] = None
    exit_code: Optional[int] = None
    log_stream: Optional[str] = None
    error_message: Optional[str] = None
    coverage_delta: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
