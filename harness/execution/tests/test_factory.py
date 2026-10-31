"""Tests for executor factory."""
import os
from pathlib import Path
from harness.execution import (
    create_executor,
    ExecutorFactory,
    ExecutorConfig,
    LocalPlaywrightExecutor,
)
from harness.execution.base import BaseExecutor


def test_create_local_executor(tmp_path):
    config = ExecutorConfig(
        run_id="r1",
        target_url="https://example.com",
        plan={"testCases": []},
        artifacts_dir=tmp_path,
    )
    executor = create_executor(config, executor_type="local")
    assert isinstance(executor, LocalPlaywrightExecutor)
    assert isinstance(executor, BaseExecutor)


def test_factory_with_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTOR_TYPE", "local")
    config = ExecutorConfig(
        run_id="r2",
        target_url="https://example.com",
        plan={"testCases": []},
        artifacts_dir=tmp_path,
    )
    executor = ExecutorFactory.create_executor(config)
    assert isinstance(executor, LocalPlaywrightExecutor)


def test_factory_default_local(tmp_path, monkeypatch):
    monkeypatch.delenv("EXECUTOR_TYPE", raising=False)
    monkeypatch.delenv("EXECUTOR", raising=False)
    config = ExecutorConfig(
        run_id="r3",
        target_url="https://example.com",
        plan={"testCases": []},
        artifacts_dir=tmp_path,
    )
    executor = create_executor(config)
    assert isinstance(executor, LocalPlaywrightExecutor)


def test_factory_invalid_type(tmp_path):
    config = ExecutorConfig(
        run_id="r4",
        target_url="https://example.com",
        plan={"testCases": []},
        artifacts_dir=tmp_path,
    )
    try:
        create_executor(config, executor_type="invalid")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown executor type" in str(e)
