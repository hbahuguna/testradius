"""Bundled backend launcher: `docker compose up -d` + health wait (E3/T2).

Owns the lifecycle of the local TestRadius stack (core + db + neo4j):

    manager = BackendManager()
    manager.up(repo_path="/path/to/repo")   # writes compose, starts, waits
    manager.status()                         # -> BackendStatus
    manager.down()

All external effects (docker CLI, HTTP health probe) are injectable so the
launcher is unit-testable without docker.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from ..config import data_dir as default_data_dir
from ..errors import BackendLaunchError
from .compose import DEFAULT_CORE_IMAGE, render_compose
from .repo import RepoMount, repo_mount

Runner = Callable[[Sequence[str], bool], subprocess.CompletedProcess]


@dataclass
class BackendStatus:
    running: bool
    healthy: bool
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.running and self.healthy

    def to_dict(self) -> dict:
        return {"running": self.running, "healthy": self.healthy, "detail": self.detail}


def _default_runner(argv: Sequence[str], check: bool) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            list(argv), check=check, capture_output=True, text=True
        )
    except FileNotFoundError as e:  # docker not installed
        raise BackendLaunchError(f"docker not found: {e}") from e
    except subprocess.CalledProcessError as e:
        raise BackendLaunchError(
            f"command failed ({' '.join(argv)}): {(e.stderr or e.stdout or '').strip()[:300]}"
        ) from e


def _default_http_ok(url: str) -> bool:
    import httpx

    try:
        return httpx.get(url, timeout=3.0).status_code == 200
    except httpx.HTTPError:
        return False


def docker_available(runner: Optional[Runner] = None) -> bool:
    runner = runner or _default_runner
    if shutil.which("docker") is None and runner is _default_runner:
        return False
    try:
        runner(["docker", "info"], True)
        return True
    except BackendLaunchError:
        return False


@dataclass
class BackendManager:
    data_root: Optional[Path] = None
    core_port: int = 8000
    core_image: str = ""
    project: str = "tia-agent"
    demo_mode: bool = True
    build_source: Optional[str] = None
    build_dockerfile: str = "services/core/Dockerfile"
    runner: Optional[Runner] = None
    http_ok: Optional[Callable[[str], bool]] = None

    def __post_init__(self) -> None:
        if self.data_root is None:
            self.data_root = default_data_dir()
        self.data_root = Path(self.data_root)

    # -- paths --------------------------------------------------------------
    @property
    def compose_path(self) -> Path:
        return self.data_root / "docker-compose.yml"

    @property
    def health_url(self) -> str:
        return f"http://localhost:{self.core_port}/health"

    def _run(self, argv: Sequence[str], check: bool = True) -> subprocess.CompletedProcess:
        return (self.runner or _default_runner)(argv, check)

    def _ok(self, url: str) -> bool:
        return (self.http_ok or _default_http_ok)(url)

    def _compose(self, *args: str) -> List[str]:
        return [
            "docker", "compose", "-f", str(self.compose_path),
            "--project-name", self.project, *args,
        ]

    # -- lifecycle ----------------------------------------------------------
    def prepare(self, repo_path: Optional[str] = None) -> Optional[RepoMount]:
        """Create data dirs, render + write the compose file. Returns the mount."""
        self.data_root.mkdir(parents=True, exist_ok=True)
        (self.data_root / "postgres").mkdir(exist_ok=True)
        (self.data_root / "neo4j").mkdir(exist_ok=True)

        mount = repo_mount(repo_path) if repo_path else None
        text = render_compose(
            str(self.data_root),
            core_image=self.core_image or DEFAULT_CORE_IMAGE,
            core_port=self.core_port,
            repo=mount,
            demo_mode=self.demo_mode,
            build_context=self.build_source,
            build_dockerfile=self.build_dockerfile if self.build_source else None,
        )
        self.compose_path.write_text(text)
        return mount

    def up(
        self,
        repo_path: Optional[str] = None,
        *,
        timeout: float = 600.0,
        wait: bool = True,
        pull: bool = False,
    ) -> BackendStatus:
        if not docker_available(self.runner):
            raise BackendLaunchError(
                "Docker is not available — install/start Docker Desktop and retry."
            )
        self.prepare(repo_path)
        if pull:
            self._run(self._compose("pull", "--quiet"), check=False)
        self._run(self._compose("up", "-d"))
        if wait and not self.wait_healthy(timeout=timeout):
            raise BackendLaunchError(
                f"backend did not become healthy within {timeout:.0f}s at {self.health_url}"
            )
        return self.status()

    def down(self) -> None:
        self._run(self._compose("down"), check=False)

    def wait_healthy(self, timeout: float = 600.0, interval: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if self._ok(self.health_url):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)

    def status(self) -> BackendStatus:
        healthy = self._ok(self.health_url)
        running = False
        detail = ""
        if self.compose_path.exists():
            try:
                proc = self._run(self._compose("ps", "-q"), check=False)
                ids = (proc.stdout or "").split()
                running = bool(ids)
                detail = f"{len(ids)} container(s)"
            except BackendLaunchError as e:
                detail = str(e)
        else:
            detail = "not launched"
        return BackendStatus(running=running, healthy=healthy, detail=detail)

    def ensure_running(self, repo_path: Optional[str] = None, timeout: float = 600.0) -> BackendStatus:
        current = self.status()
        if current.healthy:
            return current
        return self.up(repo_path, timeout=timeout)


def port_from_url(url: str, default: int = 8000) -> int:
    """Extract the port from a backend URL (e.g. http://localhost:8000)."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.port or default
    except ValueError:
        return default
