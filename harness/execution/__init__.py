"""Executor abstraction for running tests in different environments."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import (
    BaseExecutor,
    ExecutionResult,
    ExecutionStatus,
    ExecutorConfig,
    StepResult,
)
from .factory import ExecutorFactory, create_executor, get_executor_mode

if TYPE_CHECKING:
    from .cloudroom import CloudRoomExecutor
    from .computer_use import ComputerUseExecutor
    from .e2b import E2BExecutor
    from .local import LocalPlaywrightExecutor

__all__ = [
    "BaseExecutor",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutorConfig",
    "StepResult",
    "ExecutorFactory",
    "create_executor",
    "get_executor_mode",
    "LocalPlaywrightExecutor",
    "CloudRoomExecutor",
    "E2BExecutor",
    "ComputerUseExecutor",
]


def __getattr__(name: str) -> Any:
    if name == "LocalPlaywrightExecutor":
        from .local import LocalPlaywrightExecutor
        return LocalPlaywrightExecutor
    if name == "CloudRoomExecutor":
        from .cloudroom import CloudRoomExecutor
        return CloudRoomExecutor
    if name == "E2BExecutor":
        from .e2b import E2BExecutor
        return E2BExecutor
    if name == "ComputerUseExecutor":
        from .computer_use import ComputerUseExecutor
        return ComputerUseExecutor
    raise AttributeError(name)

