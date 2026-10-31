"""Executor abstraction for running tests in different environments."""
from .base import (
    BaseExecutor,
    ExecutionResult,
    ExecutionStatus,
    ExecutorConfig,
    StepResult,
)

__all__ = [
    "BaseExecutor",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutorConfig",
    "StepResult",
]
