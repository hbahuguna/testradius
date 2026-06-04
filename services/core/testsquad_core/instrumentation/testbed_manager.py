import os
import shutil
import tempfile
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import git
from datetime import datetime, timedelta


@dataclass
class TestbedConfig:
    """Configuration for a testbed repository."""
    repo_url: str
    branch: str = "main"
    test_command: str = "pytest tests/ -v"
    install_command: str = "pip install -e ."
    dependencies: List[str] = None
    test_dir: str = "tests"
    coverage_output: str = ".coverage.json"


@dataclass
class TestbedResult:
    """Result of testbed setup and execution."""
    success: bool
    testbed_path: str
    coverage_data: Optional[Dict[str, Any]] = None
    test_results: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    execution_time_seconds: float = 0.0


class TestbedManager:
    """
    Manages testbed repositories for instrumentation-based TIA.
    
    Responsibilities:
    - Clone and setup external repositories
    - Install dependencies
    - Run instrumented test suites
    - Collect and parse coverage data
    """

    DEFAULT_TESTBEDS = {
        "py-key-value": TestbedConfig(
            repo_url="https://github.com/strawgate/py-key-value.git",
            branch="main",
            test_command=".venv/bin/python -m pytest tests/ -v --cov --cov-report=json --cov-report=term",
            install_command="python3.11 -m venv .venv && .venv/bin/pip install -e \".[memory,pydantic]\" && .venv/bin/pip install dirty-equals inline-snapshot testcontainers pytest-cov pytest-asyncio pytest-xdist cachetools",
            test_dir="tests",
            coverage_output="coverage.json"
        )
    }

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or tempfile.gettempdir()
        self._testbeds: Dict[str, TestbedConfig] = {}

    def register_testbed(self, name: str, config: TestbedConfig) -> None:
        """Register a new testbed configuration."""
        self._testbeds[name] = config

    def get_testbed(self, name: str) -> TestbedConfig:
        """Get testbed configuration by name."""
        if name in self._testbeds:
            return self._testbeds[name]
        if name in self.DEFAULT_TESTBEDS:
            return self.DEFAULT_TESTBEDS[name]
        raise ValueError(f"Unknown testbed: {name}")

    def clone_testbed(
        self,
        name: str,
        use_cache: bool = True,
        cache_ttl: timedelta = timedelta(hours=24)
    ) -> TestbedResult:
        """
        Clone and setup a testbed repository.
        
        Args:
            name: Name of the testbed (e.g., 'py-key-value')
            use_cache: Whether to use cached clone if available
            cache_ttl: Time-to-live for cached repos
            
        Returns:
            TestbedResult with setup status and path
        """
        config = self.get_testbed(name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        testbed_path = os.path.join(self.base_dir, f"testbed-{name}-{timestamp}")

        try:
            os.makedirs(testbed_path, exist_ok=True)

            print(f"Cloning {config.repo_url} (branch: {config.branch})...")
            repo = git.Repo.clone_from(
                config.repo_url,
                testbed_path,
                branch=config.branch,
                depth=1
            )

            if config.install_command:
                print(f"Installing dependencies: {config.install_command}")
                result = subprocess.run(
                    config.install_command,
                    shell=True,
                    cwd=testbed_path,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode != 0:
                    print(f"Warning: install failed: {result.stderr}")

            return TestbedResult(
                success=True,
                testbed_path=testbed_path,
                coverage_data=None,
                test_results=None,
                error_message=None,
                execution_time_seconds=0.0
            )

        except Exception as e:
            return TestbedResult(
                success=False,
                testbed_path=testbed_path,
                error_message=str(e)
            )

    def run_instrumented_tests(
        self,
        testbed_path: str,
        config: TestbedConfig,
        test_pattern: Optional[str] = None
    ) -> TestbedResult:
        """
        Run tests with instrumentation (coverage collection).
        
        Args:
            testbed_path: Path to the cloned testbed
            config: Testbed configuration
            test_pattern: Optional specific test pattern to run
            
        Returns:
            TestbedResult with coverage data and test results
        """
        start_time = datetime.now()

        try:
            test_command = config.test_command
            if test_pattern:
                # Use venv python for test pattern
                venv_python = os.path.join(testbed_path, ".venv", "bin", "python")
                if os.path.exists(venv_python):
                    test_command = f"{venv_python} -m pytest {test_pattern}"
                else:
                    # Fallback to config command if no venv
                    test_command = f"{config.test_command} {test_pattern}"

            print(f"Running instrumented tests: {test_command}")
            result = subprocess.run(
                test_command,
                shell=True,
                cwd=testbed_path,
                capture_output=True,
                text=True,
                timeout=3600
            )

            coverage_path = os.path.join(testbed_path, config.coverage_output)
            coverage_data = None
            if os.path.exists(coverage_path):
                with open(coverage_path, 'r') as f:
                    coverage_data = json.load(f)

            execution_time = (datetime.now() - start_time).total_seconds()

            return TestbedResult(
                success=result.returncode == 0,
                testbed_path=testbed_path,
                coverage_data=coverage_data,
                test_results={
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                },
                execution_time_seconds=execution_time
            )

        except subprocess.TimeoutExpired:
            return TestbedResult(
                success=False,
                testbed_path=testbed_path,
                error_message="Test execution timed out after 1 hour",
                execution_time_seconds=3600.0
            )
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            return TestbedResult(
                success=False,
                testbed_path=testbed_path,
                error_message=str(e),
                execution_time_seconds=execution_time
            )

    def cleanup_testbed(self, testbed_path: str) -> bool:
        """Clean up a testbed directory."""
        try:
            if os.path.exists(testbed_path):
                shutil.rmtree(testbed_path)
            return True
        except Exception as e:
            print(f"Warning: cleanup failed: {e}")
            return False