"""E3/T2: bundled backend launcher — compose rendering, repo mount/path
normalization, and the lifecycle manager (docker + HTTP injected)."""

import subprocess

import pytest

from tia_agent.backend.compose import DEFAULT_CORE_IMAGE, render_compose
from tia_agent.backend.launcher import (
    BackendManager,
    BackendStatus,
    docker_available,
    port_from_url,
)
from tia_agent.backend.repo import (
    normalize_repo_path,
    repo_mount,
    sanitize_name,
    to_container_path,
)
from tia_agent.errors import BackendLaunchError


# --------------------------------------------------------------------------- #
# compose rendering
# --------------------------------------------------------------------------- #

def test_render_compose_core_services_and_data_dirs(tmp_path):
    text = render_compose(str(tmp_path))
    assert "core:" in text and "db:" in text and "neo4j:" in text
    assert f"image: {DEFAULT_CORE_IMAGE}" in text
    assert '"8000:8000"' in text
    assert "postgres:16" in text and "neo4j:5" in text
    assert f"{tmp_path}/postgres:/var/lib/postgresql/data" in text
    assert f"{tmp_path}/neo4j:/data" in text
    assert "NEO4J_AUTH: neo4j/testsquad_password" in text
    assert 'DEMO_MODE: "1"' in text


def test_render_compose_repo_mount_and_local_path(tmp_path):
    mount = repo_mount("/srv/code/acme-shop")
    text = render_compose(str(tmp_path), repo=mount)
    assert f"TESTRADIUS_LOCAL_PATH: {mount.container_path}" in text
    assert f"- {mount.host_path}:{mount.container_path}" in text


def test_render_compose_no_repo_mount_omits_local_path(tmp_path):
    text = render_compose(str(tmp_path))
    assert "TESTRADIUS_LOCAL_PATH" not in text


def test_render_compose_build_context(tmp_path):
    text = render_compose(
        str(tmp_path), build_context="/src/testradius",
        build_dockerfile="services/core/Dockerfile",
    )
    assert "build:" in text
    assert "context: /src/testradius" in text
    assert "dockerfile: services/core/Dockerfile" in text
    assert f"image: {DEFAULT_CORE_IMAGE}" not in text


def test_render_compose_demo_mode_off(tmp_path):
    text = render_compose(str(tmp_path), demo_mode=False)
    assert 'DEMO_MODE: "0"' in text


# --------------------------------------------------------------------------- #
# repo mount + path normalization
# --------------------------------------------------------------------------- #

def test_repo_mount_sanitizes_name():
    mount = repo_mount("/Users/dev/My Repo!")
    assert mount.name == "My-Repo"
    assert mount.container_path == "/workdir/My-Repo"
    assert mount.host_path.endswith("My Repo!")


def test_sanitize_name_fallbacks():
    assert sanitize_name("!!!") == "repo"
    assert sanitize_name("a/b/c") == "a-b-c"


def test_normalize_repo_path_strips_prefixes():
    mount = repo_mount("/srv/acme-shop")
    assert normalize_repo_path("/workdir/acme-shop/src/cart.py", mount) == "src/cart.py"
    assert normalize_repo_path("/testradius/artifacts/tests/a.spec.ts", mount) == "artifacts/tests/a.spec.ts"
    assert normalize_repo_path("./src/x.py", mount) == "src/x.py"
    assert normalize_repo_path("src/y.py", mount) == "src/y.py"
    assert normalize_repo_path("/workdir/acme-shop", mount) == ""
    assert normalize_repo_path("", mount) == ""


def test_to_container_path_from_host_and_relative():
    mount = repo_mount("/srv/acme-shop")
    assert to_container_path("/srv/acme-shop/src/cart.py", mount) == "/workdir/acme-shop/src/cart.py"
    assert to_container_path("src/cart.py", mount) == "/workdir/acme-shop/src/cart.py"
    assert to_container_path("/srv/acme-shop", mount) == "/workdir/acme-shop"


def test_port_from_url():
    assert port_from_url("http://localhost:8000") == 8000
    assert port_from_url("http://localhost:9123/") == 9123
    assert port_from_url("not a url", default=8000) == 8000


# --------------------------------------------------------------------------- #
# launcher
# --------------------------------------------------------------------------- #

class FakeRunner:
    def __init__(self, info_ok=True, ps_stdout=""):
        self.info_ok = info_ok
        self.ps_stdout = ps_stdout
        self.calls = []

    def __call__(self, argv, check):
        argv = list(argv)
        self.calls.append(argv)
        if argv[:2] == ["docker", "info"]:
            if not self.info_ok:
                raise BackendLaunchError("docker info failed")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "ps" in argv:
            return subprocess.CompletedProcess(argv, 0, self.ps_stdout, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def has(self, *tokens):
        return any(all(t in call for t in tokens) for call in self.calls)


def _manager(tmp_path, runner, healthy=True):
    return BackendManager(
        data_root=tmp_path,
        runner=runner,
        http_ok=lambda url: healthy,
    )


def test_prepare_writes_compose_and_data_dirs(tmp_path):
    mgr = _manager(tmp_path, FakeRunner())
    mount = mgr.prepare(repo_path="/srv/acme-shop")
    assert mount.container_path == "/workdir/acme-shop"
    assert mgr.compose_path.exists()
    text = mgr.compose_path.read_text()
    assert f"- {mount.host_path}:{mount.container_path}" in text
    assert (tmp_path / "postgres").is_dir()
    assert (tmp_path / "neo4j").is_dir()


def test_up_runs_compose_and_waits_healthy(tmp_path):
    runner = FakeRunner()
    mgr = _manager(tmp_path, runner, healthy=True)
    status = mgr.up(timeout=5)
    assert status.healthy is True
    assert runner.has("docker", "compose", "up")
    assert not runner.has("pull")


def test_up_pull_when_requested(tmp_path):
    runner = FakeRunner()
    mgr = _manager(tmp_path, runner)
    mgr.up(pull=True, timeout=5)
    assert runner.has("docker", "compose", "pull")


def test_up_build_uses_build_context(tmp_path):
    runner = FakeRunner()
    mgr = BackendManager(
        data_root=tmp_path, runner=runner, http_ok=lambda url: True,
        build_source="/src/testradius",
    )
    mgr.up(timeout=5)
    assert "build:" in mgr.compose_path.read_text()
    assert not runner.has("pull")


def test_up_raises_when_docker_unavailable(tmp_path):
    mgr = _manager(tmp_path, FakeRunner(info_ok=False))
    with pytest.raises(BackendLaunchError):
        mgr.up(timeout=1)


def test_up_raises_when_never_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr("tia_agent.backend.launcher.time.sleep", lambda *_: None)
    mgr = _manager(tmp_path, FakeRunner(), healthy=False)
    with pytest.raises(BackendLaunchError):
        mgr.up(timeout=0.05)


def test_wait_healthy_polls_until_true(tmp_path, monkeypatch):
    monkeypatch.setattr("tia_agent.backend.launcher.time.sleep", lambda *_: None)
    answers = iter([False, False, True])
    mgr = BackendManager(
        data_root=tmp_path, runner=FakeRunner(), http_ok=lambda url: next(answers)
    )
    assert mgr.wait_healthy(timeout=5) is True


def test_down_runs_compose_down(tmp_path):
    runner = FakeRunner()
    mgr = _manager(tmp_path, runner)
    mgr.prepare()
    mgr.down()
    assert runner.has("docker", "compose", "down")


def test_status_running_from_compose_ps(tmp_path):
    runner = FakeRunner(ps_stdout="abc123\ndef456\n")
    mgr = _manager(tmp_path, runner, healthy=True)
    mgr.prepare()
    status = mgr.status()
    assert isinstance(status, BackendStatus)
    assert status.running is True and status.healthy is True
    assert status.ok is True
    assert "2 container" in status.detail


def test_status_not_launched(tmp_path):
    mgr = _manager(tmp_path, FakeRunner(), healthy=False)
    status = mgr.status()
    assert status.running is False and status.healthy is False
    assert status.detail == "not launched"


def test_ensure_running_skips_up_when_healthy(tmp_path):
    runner = FakeRunner()
    mgr = _manager(tmp_path, runner, healthy=True)
    mgr.prepare()
    mgr.ensure_running()
    assert not runner.has("up")


def test_docker_available_false_on_failure():
    assert docker_available(FakeRunner(info_ok=False)) is False
    assert docker_available(FakeRunner(info_ok=True)) is True
