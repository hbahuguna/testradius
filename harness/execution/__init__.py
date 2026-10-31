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

from .local import LocalPlaywrightExecutor

__all__ = [
    "BaseExecutor",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutorConfig",
    "StepResult",
    "LocalPlaywrightExecutor",
]

from .factory import ExecutorFactory, create_executor

__all__ = [
    "BaseExecutor",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutorConfig",
    "StepResult",
    "LocalPlaywrightExecutor",
    "ExecutorFactory",
    "create_executor",
]

try:
    from .cloudroom import CloudRoomExecutor

    __all__.append("CloudRoomExecutor")
except ImportError:
    pass
