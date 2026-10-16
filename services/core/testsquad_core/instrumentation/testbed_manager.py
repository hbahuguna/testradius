import os
import re
import shutil
import tempfile
import json
import hashlib
import contextlib
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import git
from datetime import datetime, timedelta


#: Sidecar written next to a cached checkout recording the commit it was cloned
#: at and whether ``install_command`` succeeded there.
CACHE_MARKER_SUFFIX = ".meta.json"


def _slug(value: str) -> str:
    """A filesystem-safe fragment of ``value`` (``"a/b c"`` -> ``"a-b-c"``)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-.")
    return cleaned[:80] or "repo"


def _canonical_clone_url(url: str) -> str:
    """Strip embedded credentials so a rotated token does not bust the cache."""
    return re.sub(r"(?<=://)[^/@\s]+@", "", (url or "").strip())


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
        #: Stable checkouts live under ``base_dir/testbed-cache`` and outlive a
        #: single run so a second run against an unchanged testbed reuses them.
        self.cache_dir = os.path.join(self.base_dir, "testbed-cache")

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

    def cache_path(self, config: TestbedConfig) -> str:
        """Stable checkout directory for ``config``, re-used across runs.

        Keyed on repo + branch + install command (never on the run timestamp —
        the old scheme minted a fresh directory every run, which defeated every
        downstream cache). The commit the checkout sits at is *not* encoded in
        the path: it is unknown before cloning, so it lives in the sidecar
        marker and is validated by :meth:`_cache_usable`.

        The install command is part of the key because a checkout prepared for
        one command (e.g. the ``install_command=""`` language-detection clone)
        must never be served to a config that needs a different one.
        """
        canonical = _canonical_clone_url(config.repo_url)
        slug = _slug(os.path.basename(canonical.rstrip("/")))
        if slug.endswith(".git"):
            slug = slug[:-4]
        fingerprint = f"{canonical}@{config.branch}#{config.install_command or ''}"
        digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:8]
        return os.path.join(self.cache_dir, f"{slug}-{_slug(config.branch)}-{digest}")

    def cache_meta_path(self, config: TestbedConfig) -> str:
        """Path of the sidecar marker describing a cached checkout."""
        return self.cache_path(config) + CACHE_MARKER_SUFFIX

    @staticmethod
    def _head_sha(testbed_path: str) -> Optional[str]:
        try:
            return str(git.Repo(testbed_path).head.commit.hexsha)
        except Exception:
            return None

    def _read_cache_meta(self, config: TestbedConfig) -> Optional[Dict[str, Any]]:
        try:
            with open(self.cache_meta_path(config)) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _write_cache_meta(self, config: TestbedConfig, installed: bool) -> None:
        meta = {
            "repo_url": _canonical_clone_url(config.repo_url),
            "branch": config.branch,
            "cloned_at": datetime.now().isoformat(timespec="seconds"),
            "head_sha": self._head_sha(self.cache_path(config)),
            "installed": bool(installed),
        }
        try:
            with open(self.cache_meta_path(config), "w") as fh:
                json.dump(meta, fh)
        except OSError as e:
            print(f"Warning: could not write cache marker: {e}")

    def _cache_usable(self, config: TestbedConfig, cache_ttl: timedelta) -> bool:
        """Whether the cached checkout may be served instead of re-cloning."""
        checkout = self.cache_path(config)
        if not os.path.isdir(os.path.join(checkout, ".git")):
            return False

        meta = self._read_cache_meta(config)
        if not meta:
            return False
        if meta.get("repo_url") != _canonical_clone_url(config.repo_url):
            return False
        if meta.get("branch") != config.branch:
            return False
        if not meta.get("installed"):
            return False

        try:
            age = datetime.now() - datetime.fromisoformat(meta["cloned_at"])
        except (TypeError, ValueError):
            return False
        if age > cache_ttl:
            return False

        # The working tree must still sit on the commit the marker recorded.
        head = self._head_sha(checkout)
        return bool(head) and head == meta.get("head_sha")

    @contextlib.contextmanager
    def _slot_lock(self, config: TestbedConfig):
        """Serialize clone + publish for one cache slot across processes.

        Without this, two concurrent runs for the same repo would each clone
        into the same slot and the loser's checkout would be removed from under
        it. With it, the loser blocks, then finds the finished checkout and
        reuses it. Best effort on platforms without ``fcntl``.
        """
        os.makedirs(self.cache_dir, exist_ok=True)
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX
            yield
            return

        lock_path = self.cache_path(config) + ".lock"
        with open(lock_path, "w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _publish(self, config: TestbedConfig, staging: str, installed: bool) -> None:
        """Atomically move a freshly prepared checkout into the cache slot.

        Publishing via ``os.rename`` means a concurrent run for the same repo
        never sees a half-cloned directory: it either finds the previous
        checkout or the finished new one.
        """
        testbed_path = self.cache_path(config)
        if os.path.isdir(testbed_path):
            shutil.rmtree(testbed_path, ignore_errors=True)
        os.rename(staging, testbed_path)
        self._write_cache_meta(config, installed)

    def _hit(self, testbed_path: str) -> TestbedResult:
        return TestbedResult(
            success=True,
            testbed_path=testbed_path,
            coverage_data=None,
            test_results=None,
            error_message=None,
            execution_time_seconds=0.0,
        )

    def _refresh_checkout(self, config: TestbedConfig) -> None:
        """Advance a reused checkout to the branch tip (Story 11.5).

        Before this, a cache hit returned a checkout that never moved — so a
        re-instrumentation run silently instrumented the commit from the *first*
        clone and the graph's anchor could never advance. Fetching keeps the
        cache (no re-clone, dependencies untouched) while letting
        ``git diff <anchor>..HEAD`` see new commits.

        A checkout with local modifications is left alone: ``reset --hard``
        would destroy someone's work, and incremental instrumentation can diff
        the working tree instead. A failed fetch (offline) falls back to the
        existing commit rather than forcing a re-clone.

        Must be called while holding the slot lock, since it mutates the
        checkout in place.
        """
        checkout = self.cache_path(config)
        try:
            repo = git.Repo(checkout)
            # Untracked files are kept by ``reset --hard`` and don't affect the
            # HEAD comparison, so only tracked edits block a refresh.
            if repo.is_dirty(untracked_files=False):
                print(f"Cached checkout has local modifications; not refreshing: {checkout}")
                return
            repo.git.fetch("--depth=1", "origin", config.branch)
            repo.git.reset("--hard", "FETCH_HEAD")
        except Exception as e:
            print(f"Warning: could not refresh cached checkout {checkout}: {e}")
            return

        # The sidecar must follow the moved HEAD (or _cache_usable rejects the
        # checkout on the next run). The install marker still holds.
        meta = self._read_cache_meta(config) or {}
        self._write_cache_meta(config, installed=bool(meta.get("installed", True)))

    def _reuse_checkout(
        self, config: TestbedConfig, cache_ttl: timedelta, locked: bool = False
    ) -> Optional[TestbedResult]:
        """Serve a usable cache entry, first advancing it to the branch tip.

        Re-checks usability under the slot lock before refreshing: a run that
        waited on the lock must not act on a checkout another run just replaced.
        """
        if not self._cache_usable(config, cache_ttl):
            return None
        if locked:
            self._refresh_checkout(config)
            return self._hit(self.cache_path(config))
        with self._slot_lock(config):
            if not self._cache_usable(config, cache_ttl):
                return None
            self._refresh_checkout(config)
            return self._hit(self.cache_path(config))

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
            use_cache: Reuse an existing checkout for the same repo+branch
                (with its dependencies already installed) instead of re-cloning.
                A reused checkout is first fetched up to the branch tip so a
                re-run instruments current code (Story 11.5).
            cache_ttl: How long a cached checkout stays fresh

        Returns:
            TestbedResult with setup status and path
        """
        config = self.get_testbed(name)
        testbed_path = self.cache_path(config)

        if use_cache:
            hit = self._reuse_checkout(config, cache_ttl)
            if hit:
                print(f"Reusing cached testbed checkout: {testbed_path}")
                return hit

        # Miss, stale marker, or run_fresh: fall back to a clean clone + install.
        # Clone into a private staging directory and publish it atomically, so
        # two concurrent runs for the same repo cannot clobber each other.
        with self._slot_lock(config):
            # A concurrent run may have finished a clone while we waited.
            if use_cache:
                hit = self._reuse_checkout(config, cache_ttl, locked=True)
                if hit:
                    print(f"Reusing cached testbed checkout: {testbed_path}")
                    return hit

            staging = tempfile.mkdtemp(
                prefix=os.path.basename(testbed_path) + ".staging-", dir=self.cache_dir
            )

            try:
                print(f"Cloning {config.repo_url} (branch: {config.branch})...")
                git.Repo.clone_from(
                    config.repo_url,
                    staging,
                    branch=config.branch,
                    depth=1
                )

                installed = True
                if config.install_command:
                    print(f"Installing dependencies: {config.install_command}")
                    result = subprocess.run(
                        config.install_command,
                        shell=True,
                        cwd=staging,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    if result.returncode != 0:
                        print(f"Warning: install failed: {result.stderr}")
                    installed = result.returncode == 0

                # A failed install is recorded as such so the next run retries it
                # rather than reusing a checkout whose deps are missing.
                self._publish(config, staging, installed)

                return TestbedResult(
                    success=True,
                    testbed_path=testbed_path,
                    coverage_data=None,
                    test_results=None,
                    error_message=None,
                    execution_time_seconds=0.0
                )

            except Exception as e:
                shutil.rmtree(staging, ignore_errors=True)
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