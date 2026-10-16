"""Story 11.4: clone + dependency-install caching.

``testbed_manager`` and ``per_test_analyzer`` are loaded by path so these tests
run without importing the ``testsquad_core.instrumentation`` package ``__init__``.

The "remote" is a real local git repository on branch ``main``, so the clone
path is exercised for real without touching the network.
"""
import importlib.util
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORE = _REPO_ROOT / "services" / "core" / "testsquad_core"
_INSTR = _CORE / "instrumentation"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def testbed_manager():
    return _load("tbm_cache", _INSTR / "testbed_manager.py")


@pytest.fixture(scope="module")
def analyzer():
    return _load("pa_cache", _INSTR / "per_test_analyzer.py")


@pytest.fixture()
def remote(tmp_path):
    """A real local git repo on branch ``main`` (stands in for GitHub)."""
    import git

    src = tmp_path / "origin"
    src.mkdir()
    (src / "README.md").write_text("hi\n")
    (src / "requirements.txt").write_text("inline-snapshot\n")
    repo = git.Repo.init(str(src))
    repo.index.add(["README.md", "requirements.txt"])
    repo.index.commit("init")
    repo.git.branch("-M", "main")
    return str(src)


@pytest.fixture()
def manager(testbed_manager, tmp_path):
    return testbed_manager.TestbedManager(base_dir=str(tmp_path / "base"))


@pytest.fixture()
def clones(monkeypatch, testbed_manager):
    """Count every real ``git.Repo.clone_from`` call."""
    real_clone = testbed_manager.git.Repo.clone_from
    calls = []

    def spy(url, to_path, **kwargs):
        calls.append(to_path)
        return real_clone(url, to_path, **kwargs)

    monkeypatch.setattr(testbed_manager.git.Repo, "clone_from", staticmethod(spy))
    return calls


def _register_config(manager, testbed_manager, remote, install_command=""):
    config = testbed_manager.TestbedConfig(
        repo_url=remote,
        branch="main",
        test_command="true",
        install_command=install_command,
        test_dir="tests",
        coverage_output="coverage.json",
    )
    manager.register_testbed("demo", config)
    return config


# --- clone cache ------------------------------------------------------------

class TestCloneCache:
    def test_second_run_reuses_path_without_cloning(
        self, manager, testbed_manager, remote, clones
    ):
        config = _register_config(manager, testbed_manager, remote)

        first = manager.clone_testbed("demo", use_cache=True)
        second = manager.clone_testbed("demo", use_cache=True)

        assert first.success and second.success
        assert first.testbed_path == second.testbed_path
        assert len(clones) == 1

        # The path is stable (no timestamp) and derived from repo + branch.
        assert manager.cache_path(config) == first.testbed_path
        assert os.path.isdir(first.testbed_path)

    def test_cache_path_contains_repo_slug_and_not_a_timestamp(
        self, manager, testbed_manager, remote
    ):
        config = _register_config(manager, testbed_manager, remote)
        path = manager.cache_path(config)
        basename = os.path.basename(path)

        # Stable slug derived from the repo (the old path was
        # `testbed-<name>-YYYYmmdd_HHMMSS`, a new directory every run).
        assert "origin" in basename
        assert not basename.startswith("testbed-")
        assert manager.cache_path(config) == path

    def test_run_fresh_reclones_clean(
        self, manager, testbed_manager, remote, clones
    ):
        _register_config(manager, testbed_manager, remote)
        first = manager.clone_testbed("demo", use_cache=True)
        second = manager.clone_testbed("demo", use_cache=False)
        assert len(clones) == 2
        assert second.testbed_path == first.testbed_path
        assert second.success

    def test_expired_cache_falls_back_to_clone(
        self, manager, testbed_manager, remote, clones
    ):
        config = _register_config(manager, testbed_manager, remote)
        ttl = timedelta(hours=1)
        first = manager.clone_testbed("demo", use_cache=True, cache_ttl=ttl)
        assert first.success

        # Age the marker past the TTL.
        meta_path = manager.cache_meta_path(config)
        meta = json.loads(Path(meta_path).read_text())
        meta["cloned_at"] = (datetime.now() - timedelta(hours=48)).isoformat()
        Path(meta_path).write_text(json.dumps(meta))

        second = manager.clone_testbed("demo", use_cache=True, cache_ttl=ttl)
        assert len(clones) == 2
        assert second.success
        assert second.testbed_path == first.testbed_path

    def test_cache_hit_skips_dependency_install(
        self, manager, testbed_manager, remote, clones
    ):
        _register_config(
            manager, testbed_manager, remote,
            install_command="echo installed > install.log",
        )
        first = manager.clone_testbed("demo", use_cache=True)
        assert first.success
        install_log = os.path.join(first.testbed_path, "install.log")
        assert os.path.isfile(install_log)

        # A hit must not re-run the install command.
        os.remove(install_log)
        second = manager.clone_testbed("demo", use_cache=True)
        assert second.testbed_path == first.testbed_path
        assert not os.path.exists(install_log)
        assert len(clones) == 1

    def test_head_mismatch_invalidates_cache(
        self, manager, testbed_manager, remote, clones
    ):
        config = _register_config(manager, testbed_manager, remote)
        manager.clone_testbed("demo", use_cache=True)

        meta_path = manager.cache_meta_path(config)
        meta = json.loads(Path(meta_path).read_text())
        meta["head_sha"] = "0" * 40  # checkout no longer at the recorded commit
        Path(meta_path).write_text(json.dumps(meta))

        result = manager.clone_testbed("demo", use_cache=True)
        assert result.success
        assert len(clones) == 2

    def test_missing_checkout_invalidates_cache(
        self, manager, testbed_manager, remote, clones
    ):
        _register_config(manager, testbed_manager, remote)
        first = manager.clone_testbed("demo", use_cache=True)
        import shutil

        shutil.rmtree(first.testbed_path)
        second = manager.clone_testbed("demo", use_cache=True)
        assert second.success
        assert len(clones) == 2
        assert os.path.isdir(second.testbed_path)

    def test_failed_install_is_not_marked_installed(
        self, manager, testbed_manager, remote, clones
    ):
        _register_config(manager, testbed_manager, remote, install_command="false")
        first = manager.clone_testbed("demo", use_cache=True)
        assert first.success  # a failed install must not break the run

        config = manager.get_testbed("demo")
        meta = json.loads(Path(manager.cache_meta_path(config)).read_text())
        assert meta["installed"] is False

        # ... so the next run does a clean clone + install instead of reusing it.
        manager.clone_testbed("demo", use_cache=True)
        assert len(clones) == 2

    def test_different_install_command_gets_its_own_checkout(
        self, manager, testbed_manager, remote, clones
    ):
        """The language-detection clone (``install_command=""``) must not be
        served to the pipeline testbed that actually needs a venv."""
        manager.register_testbed("detect-lang", testbed_manager.TestbedConfig(
            repo_url=remote, branch="main", test_command="true",
            install_command="", test_dir=".",
        ))
        detect = manager.clone_testbed("detect-lang", use_cache=True)

        manager.register_testbed("custom", testbed_manager.TestbedConfig(
            repo_url=remote, branch="main", test_command="true",
            install_command="echo installed > install.log", test_dir="tests",
        ))
        custom = manager.clone_testbed("custom", use_cache=True)

        assert custom.testbed_path != detect.testbed_path
        assert len(clones) == 2
        assert os.path.isfile(os.path.join(custom.testbed_path, "install.log"))

    def test_no_staging_directories_left_behind(
        self, manager, testbed_manager, remote, clones
    ):
        _register_config(manager, testbed_manager, remote)
        manager.clone_testbed("demo", use_cache=True)
        leftovers = [p for p in os.listdir(manager.cache_dir) if ".staging-" in p]
        assert leftovers == []

    def test_concurrent_cold_starts_clone_only_once(
        self, manager, testbed_manager, remote, clones
    ):
        """Two simultaneous cold starts for one slot must not clobber each other."""
        from concurrent.futures import ThreadPoolExecutor

        _register_config(manager, testbed_manager, remote)

        def run(_):
            return manager.clone_testbed("demo", use_cache=True)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))

        assert all(r.success for r in results)
        assert results[0].testbed_path == results[1].testbed_path
        assert len(clones) == 1

    def test_failed_clone_cleans_up_staging(
        self, manager, testbed_manager, remote, monkeypatch
    ):
        _register_config(manager, testbed_manager, remote)
        os.makedirs(manager.cache_dir, exist_ok=True)

        def boom(*a, **k):
            raise RuntimeError("clone exploded")

        monkeypatch.setattr(testbed_manager.git.Repo, "clone_from", staticmethod(boom))
        result = manager.clone_testbed("demo", use_cache=True)

        assert result.success is False
        assert "clone exploded" in result.error_message
        leftovers = [p for p in os.listdir(manager.cache_dir) if ".staging-" in p]
        assert leftovers == []


# --- node dependency-install marker -----------------------------------------

class TestNodeDepsInstallCache:
    """TS/Playwright paths: a reused checkout keeps its ``node_modules``."""

    def _load(self, name, filename):
        return _load(name, _INSTR / filename)

    def test_typescript_install_skipped_when_marker_matches(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.syspath_prepend(str(_INSTR))
        tsp = self._load("tsp_node", "typescript_pipeline.py")

        repo = tmp_path / "repo"
        (repo / "node_modules").mkdir(parents=True)
        (repo / "package-lock.json").write_text('{"lockfileVersion": 3}\n')

        calls = []

        def fake_run(*a, **k):
            calls.append(a)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(tsp.subprocess, "run", fake_run)
        config = tsp.TypeScriptTestbedConfig(repo_url="x", package_manager="npm")

        assert tsp.install_dependencies(str(repo), config) is True
        first = len(calls)
        assert first > 0

        # A fresh process (nothing memoized) still skips via the marker.
        assert tsp.install_dependencies(str(repo), config) is True
        assert len(calls) == first

    def test_typescript_install_reruns_when_lockfile_changes(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.syspath_prepend(str(_INSTR))
        tsp = self._load("tsp_node2", "typescript_pipeline.py")

        repo = tmp_path / "repo"
        (repo / "node_modules").mkdir(parents=True)
        (repo / "package-lock.json").write_text('{"lockfileVersion": 3}\n')

        calls = []

        def fake_run(*a, **k):
            calls.append(a)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(tsp.subprocess, "run", fake_run)
        config = tsp.TypeScriptTestbedConfig(repo_url="x", package_manager="npm")

        tsp.install_dependencies(str(repo), config)
        first = len(calls)

        # Dependencies actually moved -> the marker is stale.
        (repo / "package-lock.json").write_text('{"lockfileVersion": 3, "x": 1}\n')
        tsp.install_dependencies(str(repo), config)
        assert len(calls) > first

    def test_typescript_install_reruns_without_node_modules(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.syspath_prepend(str(_INSTR))
        tsp = self._load("tsp_node3", "typescript_pipeline.py")

        repo = tmp_path / "repo"
        repo.mkdir()  # no node_modules -> nothing to reuse

        calls = []

        def fake_run(*a, **k):
            calls.append(a)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(tsp.subprocess, "run", fake_run)
        config = tsp.TypeScriptTestbedConfig(repo_url="x", package_manager="npm")

        tsp.install_dependencies(str(repo), config)
        tsp.install_dependencies(str(repo), config)
        assert len(calls) == 2

    def test_playwright_install_skipped_when_marker_matches(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.syspath_prepend(str(_INSTR))
        pwp = self._load("pwp_node", "playwright_pipeline.py")

        repo = tmp_path / "repo"
        (repo / "node_modules").mkdir(parents=True)
        (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")

        calls = []

        def fake_run(*a, **k):
            calls.append(a)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(pwp.subprocess, "run", fake_run)
        config = pwp.PlaywrightTestbedConfig(package_manager="pnpm")

        assert pwp.install_dependencies(str(repo), config) is True
        first = len(calls)
        assert first > 0
        assert pwp.install_dependencies(str(repo), config) is True
        assert len(calls) == first

    def test_marker_lives_inside_node_modules(self, monkeypatch, tmp_path):
        """The marker must not pollute the checkout's git status."""
        monkeypatch.syspath_prepend(str(_INSTR))
        tsp = self._load("tsp_node4", "typescript_pipeline.py")

        repo = tmp_path / "repo"
        (repo / "node_modules").mkdir(parents=True)
        (repo / "package-lock.json").write_text("{}\n")

        def fake_run(*a, **k):
            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(tsp.subprocess, "run", fake_run)
        config = tsp.TypeScriptTestbedConfig(repo_url="x", package_manager="npm")
        tsp.install_dependencies(str(repo), config)

        assert (repo / "node_modules" / ".tia-node-deps").is_file()
        assert not (repo / ".tia-node-deps").exists()


# --- dependency-install marker ---------------------------------------------

class TestDepsInstallMarker:
    def test_marker_short_circuits_install(
        self, analyzer, monkeypatch, tmp_path
    ):
        analyzer._DEPS_INSTALLED.clear()
        calls = []

        def fake_run(*a, **k):
            calls.append(a)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
        tb = str(tmp_path / "tb")
        os.makedirs(tb, exist_ok=True)

        analyzer._install_test_deps("/venv/bin/python", tb)
        first = len(calls)
        assert first > 0
        marker = os.path.join(tb, analyzer.DEPS_MARKER)
        assert os.path.isfile(marker)

        # Simulate a NEW process: the in-process set is empty, marker remains.
        analyzer._DEPS_INSTALLED.clear()
        analyzer._install_test_deps("/venv/bin/python", tb)
        assert len(calls) == first

    def test_marker_written_only_on_successful_install(
        self, analyzer, monkeypatch, tmp_path
    ):
        analyzer._DEPS_INSTALLED.clear()
        calls = []

        def fake_run(*a, **k):
            calls.append(a)

            class R:
                returncode = 1  # the hard deps install fails

            return R()

        monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
        tb = str(tmp_path / "tb")
        os.makedirs(tb, exist_ok=True)

        analyzer._install_test_deps("/venv/bin/python", tb)
        assert not os.path.isfile(os.path.join(tb, analyzer.DEPS_MARKER))

        # Without a marker a fresh process installs again -> more calls.
        analyzer._DEPS_INSTALLED.clear()
        before = len(calls)
        analyzer._install_test_deps("/venv/bin/python", tb)
        assert len(calls) > before

    def test_stale_marker_is_rejected(self, analyzer, monkeypatch, tmp_path):
        """A marker whose spec hash no longer matches triggers a reinstall."""
        analyzer._DEPS_INSTALLED.clear()
        calls = []

        def fake_run(*a, **k):
            calls.append(a)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
        tb = str(tmp_path / "tb")
        os.makedirs(tb, exist_ok=True)

        marker = os.path.join(tb, analyzer.DEPS_MARKER)
        Path(marker).write_text("some-old-spec-hash")

        analyzer._install_test_deps("/venv/bin/python", tb)
        assert len(calls) > 0

        # ... and a matching marker now short-circuits again.
        analyzer._DEPS_INSTALLED.clear()
        before = len(calls)
        analyzer._install_test_deps("/venv/bin/python", tb)
        assert len(calls) == before


# --- cache refresh (Story 11.5: reach the new commit to diff against) ------

def _advance_remote(remote):
    """Add a commit to the local ``remote`` repo, returning the new HEAD."""
    import git
    Path(remote, "core.py").write_text("x = %s\n" % os.getpid())
    repo = git.Repo(remote)
    repo.index.add(["core.py"])
    return str(repo.index.commit("advance").hexsha)


class TestCacheRefresh:
    def test_reused_checkout_advances_to_new_remote_commit(
        self, manager, testbed_manager, remote, clones
    ):
        config = _register_config(manager, testbed_manager, remote)

        first = manager.clone_testbed("demo", use_cache=True)
        assert first.success
        old_head = str(__import__("git").Repo(first.testbed_path).head.commit.hexsha)

        new_head = _advance_remote(remote)

        second = manager.clone_testbed("demo", use_cache=True)

        assert second.success
        assert second.testbed_path == first.testbed_path
        assert str(__import__("git").Repo(second.testbed_path).head.commit.hexsha) == new_head
        # Still a *cache* hit: no re-clone, deps still installed.
        assert len(clones) == 1
        # The sidecar follows the moved HEAD so _cache_usable still matches.
        meta = json.loads(Path(manager.cache_meta_path(config)).read_text())
        assert meta["head_sha"] == new_head
        assert meta["installed"] is True

    def test_dirty_checkout_is_not_refreshed(
        self, manager, testbed_manager, remote
    ):
        config = _register_config(manager, testbed_manager, remote)
        first = manager.clone_testbed("demo", use_cache=True)
        assert first.success

        # Someone is editing the checkout: resetting would destroy their work.
        local = Path(first.testbed_path, "README.md")
        local.write_text("local work in progress\n")

        _advance_remote(remote)
        second = manager.clone_testbed("demo", use_cache=True)

        assert second.success
        assert local.read_text() == "local work in progress\n"
        assert json.loads(
            Path(manager.cache_meta_path(config)).read_text()
        )["head_sha"] == str(__import__("git").Repo(first.testbed_path).head.commit.hexsha)

    def test_refresh_failure_falls_back_to_existing_commit(
        self, manager, testbed_manager, remote
    ):
        config = _register_config(manager, testbed_manager, remote)
        first = manager.clone_testbed("demo", use_cache=True)
        old_head = str(__import__("git").Repo(first.testbed_path).head.commit.hexsha)

        # Remote unreachable (offline): the cached checkout must still be served.
        import shutil
        shutil.move(remote, remote + ".gone")

        second = manager.clone_testbed("demo", use_cache=True)

        assert second.success
        assert second.testbed_path == first.testbed_path
        assert str(__import__("git").Repo(second.testbed_path).head.commit.hexsha) == old_head

    def test_run_fresh_is_not_refreshed_after_reclone(
        self, manager, testbed_manager, remote, clones
    ):
        config = _register_config(manager, testbed_manager, remote)
        first = manager.clone_testbed("demo", use_cache=True)
        assert first.success

        new_head = _advance_remote(remote)

        # run_fresh -> clean clone, which naturally lands on the new tip.
        fresh = manager.clone_testbed("demo", use_cache=False)

        assert fresh.success
        assert str(__import__("git").Repo(fresh.testbed_path).head.commit.hexsha) == new_head
        assert len(clones) == 2
