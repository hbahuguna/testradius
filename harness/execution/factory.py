"""Factory for creating executor instances."""
from __future__ import annotations

import os
from typing import Optional

from .base import BaseExecutor, ExecutorConfig
from .local import LocalPlaywrightExecutor


class ExecutorFactory:
    """Factory to create executor instances based on configuration."""

    @staticmethod
    def create_executor(
        config: ExecutorConfig,
        executor_type: Optional[str] = None,
    ) -> BaseExecutor:
        """
        Create an executor instance.

        Args:
            config: Executor configuration
            executor_type: Type of executor ('local', 'cloudroom'). If None, uses env/config

        Returns:
            Instance of BaseExecutor
        """
        if executor_type is None:
            executor_type = os.environ.get("EXECUTOR_TYPE") or os.environ.get("EXECUTOR") or "local"

        executor_type = executor_type.lower().strip()

        if executor_type == "local":
            return LocalPlaywrightExecutor(config)
        elif executor_type == "cloudroom":
            # Will be implemented in STORY-CR003
            try:
                from .cloudroom import CloudRoomExecutor

                return CloudRoomExecutor(config)
            except ImportError:
                raise NotImplementedError(
                    "CloudRoomExecutor not yet implemented. "
                    "Use EXECUTOR_TYPE=local or wait for STORY-CR003."
                )
        else:
            raise ValueError(f"Unknown executor type: {executor_type}. Must be 'local' or 'cloudroom'.")


def create_executor(
    config: ExecutorConfig,
    executor_type: Optional[str] = None,
) -> BaseExecutor:
    """Convenience function to create an executor."""
    return ExecutorFactory.create_executor(config, executor_type)


def get_executor_mode() -> str:
    """Get current executor mode from environment."""
    return (os.environ.get("EXECUTOR_TYPE") or os.environ.get("EXECUTOR") or "local").lower().strip()
