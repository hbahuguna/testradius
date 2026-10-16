"""Story 11.6: TypeScript (Vitest) / Playwright parity — sharding + lift the cap.

Both pipelines are loaded by path so these tests run without importing the
``testsquad_core.instrumentation`` package ``__init__`` (Neo4j/FastAPI deps).

The per-file Vitest spawn is *intentional* and documented; what this story fixes
is the hardcoded 10-file cap and the sequential, un-sharded execution loop that
the Python path already has.
"""
import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORE = _REPO_ROOT / "services" / "core" / "testsquad_core"
_INSTR = _CORE / "instrumentation"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tsp():
    return _load("tsp_parity", _INSTR / "typescript_pipeline.py")


@pytest.fixture(scope="module")
def pwp():
    return _load("pwp_parity", _INSTR / "playwright_pipeline.py")


@pytest.fixture(scope="module")
def covparser():
    return _load("cp_parity", _INSTR / "coverage_parser.py")


# --------------------------------------------------------------------------- #
# TS (Vitest): cap lifted, files sharded
# --------------------------------------------------------------------------- #

class TestVitestCapAndSharding:
    def test_no_cap_by_default(self, tsp, monkeypatch, tmp_path):
        (tmp_path / "src").mkdir()
        for i in range(40):
            (tmp_path / "src" / f"test_{i}.test.ts").write_text("test('x', () => {});")

        monkeypatch.setattr(
            tsp, "find_test_files",
            lambda *a, **k: [str(tmp_path / "src" / f"test_{i}.test.ts") for i in range(40)],
        )
        seen = []

        def fake_single(repo_path, tf, cov_dir):
            seen.append(tf)
            rel = f"src/test_{len(seen) - 1}.test.ts"
            return {rel: {1}}

        monkeypatch.setattr(tsp, "run_single_vitest_test", fake_single)

        res = tsp.run_vitest_with_coverage(str(tmp_path), tsp.TypeScriptTestbedConfig(repo_url="x"))

        assert len(seen) == 40
        assert res["test_count"] == 40
        assert res["success"] is True

    def test_env_cap_limits_schedule(self, tsp, monkeypatch, tmp_path):
        monkeypatch.setenv("TIA_TS_MAX_FILES", "3")
        monkeypatch.setattr(
            tsp, "find_test_files",
            lambda *a, **k: [str(tmp_path / f"test_{i}.test.ts") for i in range(10)],
        )
        seen = []

        def fake_single(repo_path, tf, cov_dir):
            seen.append(tf)
            return {f"t{len(seen)}.test.ts": {1}}

        monkeypatch.setattr(tsp, "run_single_vitest_test", fake_single)

        res = tsp.run_vitest_with_coverage(str(tmp_path), tsp.TypeScriptTestbedConfig(repo_url="x"))

        assert len(seen) == 3
        assert res["test_count"] == 3

    def test_files_are_sharded(self, tsp, monkeypatch, tmp_path):
        monkeypatch.setenv("TIA_TS_SHARDS", "3")
        monkeypatch.setattr(
            tsp, "find_test_files",
            lambda *a, **k: [str(tmp_path / f"test_{i}.test.ts") for i in range(7)],
        )

        def fake_single(repo_path, tf, cov_dir):
            return {tf.rsplit("/", 1)[-1]: {1}}

        monkeypatch.setattr(tsp, "run_single_vitest_test", fake_single)

        res = tsp.run_vitest_with_coverage(str(tmp_path), tsp.TypeScriptTestbedConfig(repo_url="x"))

        assert res["test_count"] == 7
        assert res["shards"] == 3
        # every file executed exactly once, spread over 3 worker lists
        assert sum(len(w) for w in res["shard_assignments"]) == 7
        assert all(len(w) <= 3 for w in res["shard_assignments"])

    def test_explicit_max_files_still_wins(self, tsp, monkeypatch, tmp_path):
        monkeypatch.delenv("TIA_TS_MAX_FILES", raising=False)
        monkeypatch.setattr(
            tsp, "find_test_files",
            lambda *a, **k: [str(tmp_path / f"test_{i}.test.ts") for i in range(10)],
        )
        monkeypatch.setattr(
            tsp, "run_single_vitest_test", lambda *a, **k: {"x": {1}}
        )

        res = tsp.run_vitest_with_coverage(
            str(tmp_path), tsp.TypeScriptTestbedConfig(repo_url="x"), max_files=2,
        )
        assert res["test_count"] == 2

    def test_shard_count_env_defaults_to_cpu(self, tsp, monkeypatch, tmp_path):
        monkeypatch.delenv("TIA_TS_SHARDS", raising=False)
        monkeypatch.setattr(
            tsp, "find_test_files",
            lambda *a, **k: [str(tmp_path / f"test_{i}.test.ts") for i in range(4)],
        )
        monkeypatch.setattr(tsp, "run_single_vitest_test", lambda *a, **k: {"x": {1}})

        res = tsp.run_vitest_with_coverage(str(tmp_path), tsp.TypeScriptTestbedConfig(repo_url="x"))

        assert res["shards"] >= 1


# --------------------------------------------------------------------------- #
# Playwright: cap lifted, file list sharded (executed serially)
# --------------------------------------------------------------------------- #

class TestPlaywrightCapAndSharding:
    def test_no_cap_by_default(self, pwp, monkeypatch, tmp_path):
        (tmp_path / "tests").mkdir()
        for i in range(25):
            (tmp_path / "tests" / f"a_{i}.spec.ts").write_text("test('x');")

        monkeypatch.setattr(
            pwp, "find_playwright_test_files",
            lambda *a, **k: [str(tmp_path / "tests" / f"a_{i}.spec.ts") for i in range(25)],
        )
        monkeypatch.setattr(pwp, "run_single_playwright_file", lambda *a, **k: {"a.js": [1]})

        res = pwp.run_playwright_coverage(
            str(tmp_path), pwp.PlaywrightTestbedConfig(repo_url="x"),
        )

        assert res["test_count"] == 25
        assert res["success"] is True

    def test_env_cap_limits_schedule(self, pwp, monkeypatch, tmp_path):
        monkeypatch.setenv("TIA_PW_MAX_FILES", "4")
        monkeypatch.setattr(
            pwp, "find_playwright_test_files",
            lambda *a, **k: [str(tmp_path / f"a_{i}.spec.ts") for i in range(10)],
        )
        seen = []

        def fake_single(repo_path, tf, config):
            seen.append(tf)
            return {f"a{len(seen)}.js": [1]}

        monkeypatch.setattr(pwp, "run_single_playwright_file", fake_single)

        res = pwp.run_playwright_coverage(
            str(tmp_path), pwp.PlaywrightTestbedConfig(repo_url="x"),
        )

        assert len(seen) == 4
        assert res["test_count"] == 4

    def test_files_are_sharded(self, pwp, monkeypatch, tmp_path):
        monkeypatch.setenv("TIA_PW_SHARDS", "2")
        monkeypatch.setattr(
            pwp, "find_playwright_test_files",
            lambda *a, **k: [str(tmp_path / f"a_{i}.spec.ts") for i in range(5)],
        )
        monkeypatch.setattr(pwp, "run_single_playwright_file", lambda *a, **k: {"a.js": [1]})

        res = pwp.run_playwright_coverage(
            str(tmp_path), pwp.PlaywrightTestbedConfig(repo_url="x"),
        )

        assert res["test_count"] == 5
        assert res["shards"] == 2
        assert sum(len(w) for w in res["shard_assignments"]) == 5

    def test_execution_is_serial(self, pwp, monkeypatch, tmp_path):
        # The shared <test_dir>/.coverage-raw dir makes threads unsafe, so files
        # must run one after another (no overlap) even with multiple shards.
        monkeypatch.setenv("TIA_PW_SHARDS", "4")
        files = [str(tmp_path / f"a_{i}.spec.ts") for i in range(6)]
        monkeypatch.setattr(pwp, "find_playwright_test_files", lambda *a, **k: files)
        order = []
        running = {"now": 0, "max": 0}

        def fake_single(repo_path, tf, config):
            running["now"] += 1
            running["max"] = max(running["max"], running["now"])
            order.append(tf)
            running["now"] -= 1
            return {"a.js": [1]}

        monkeypatch.setattr(pwp, "run_single_playwright_file", fake_single)

        res = pwp.run_playwright_coverage(
            str(tmp_path), pwp.PlaywrightTestbedConfig(repo_url="x"),
        )

        assert running["max"] == 1          # never two at once
        assert set(order) == set(files)      # every file ran exactly once
        assert res["test_count"] == 6


# --------------------------------------------------------------------------- #
# the Istanbul parse the Vitest plugin feeds (per-test → multiple symbols)
# --------------------------------------------------------------------------- #

class TestVitestCoverageParse:
    def test_parse_istanbul_maps_hit_statements_to_lines(self, covparser):
        data = {
            "./src/a.ts": {
                "s": {"1": 1, "2": 0},
                "statementMap": {
                    "1": {"start": {"line": 10}, "end": {"line": 11}},
                    "2": {"start": {"line": 20}, "end": {"line": 20}},
                },
            }
        }
        parsed = covparser.CoverageParser.parse_istanbul(data)
        assert parsed == {"./src/a.ts": [10, 11]}

    def test_parse_istanbul_skips_files_without_statement_maps(self, covparser):
        assert covparser.CoverageParser.parse_istanbul({"./src/b.ts": {"f": {}}}) == {}

    def test_parse_istanbul_expands_multi_line_statements(self, covparser):
        data = {
            "./src/c.ts": {
                "s": {"1": 3},
                "statementMap": {"1": {"start": {"line": 1}, "end": {"line": 4}}},
            }
        }
        parsed = covparser.CoverageParser.parse_istanbul(data)
        assert parsed["./src/c.ts"] == [1, 2, 3, 4]


# --------------------------------------------------------------------------- #
# Vitest plugin wiring (AC3): preferred when present, per-file fallback
# --------------------------------------------------------------------------- #

class TestVitestPluginWiring:
    def test_uses_plugin_when_present(self, tsp, monkeypatch, tmp_path):
        monkeypatch.setattr(
            tsp, "find_test_files",
            lambda *a, **k: [str(tmp_path / f"t{i}.test.ts") for i in range(5)],
        )
        monkeypatch.setattr(
            tsp, "resolve_vitest_plugin_cli", lambda repo, cfg: "/fake/vitest-plugin/cli.js"
        )

        out_path = tmp_path / "testsquad-per-test-coverage.json"

        def fake_run(args, **kwargs):
            assert args[0] == "node"
            assert "--max=5" in args
            out_path.write_text(json.dumps({"src/t0.test.ts": {"src/a.ts": [1, 2]}}))

            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            return R()

        monkeypatch.setattr(tsp.subprocess, "run", fake_run)
        # If the per-file loop is reached, this would blow up:
        monkeypatch.setattr(tsp, "run_single_vitest_test", lambda *a, **k: (_ for _ in ()).throw(AssertionError("per-file loop used")))

        cfg = tsp.TypeScriptTestbedConfig(repo_url="x")
        res = tsp.run_vitest_with_coverage(str(tmp_path), cfg)

        assert res["engine"] == "vitest-plugin"
        assert res["coverage"] == {"src/t0.test.ts": {"src/a.ts": [1, 2]}}
        assert res["test_count"] == 1

    def test_falls_back_when_plugin_fails(self, tsp, monkeypatch, tmp_path):
        monkeypatch.setattr(
            tsp, "find_test_files",
            lambda *a, **k: [str(tmp_path / "t0.test.ts")],
        )
        monkeypatch.setattr(
            tsp, "resolve_vitest_plugin_cli", lambda repo, cfg: "/fake/cli.js"
        )

        def fake_run(args, **kwargs):
            class R:
                returncode = 1
                stdout = ""
                stderr = "boom"

            return R()

        monkeypatch.setattr(tsp.subprocess, "run", fake_run)
        monkeypatch.setattr(tsp, "run_single_vitest_test", lambda *a, **k: {"src/a.ts": [1]})

        res = tsp.run_vitest_with_coverage(str(tmp_path), tsp.TypeScriptTestbedConfig(repo_url="x"))

        assert res["engine"] == "per-file"
        assert res["test_count"] == 1

    def test_plugin_disabled_by_env(self, tsp, monkeypatch, tmp_path):
        monkeypatch.setenv("TIA_TS_PLUGIN", "0")
        monkeypatch.setattr(
            tsp, "find_test_files",
            lambda *a, **k: [str(tmp_path / "t0.test.ts")],
        )
        called = {"plugin": False}

        def fake_plugin(*a, **k):
            called["plugin"] = True
            return {"src/t0.test.ts": {"src/a.ts": [1]}}

        monkeypatch.setattr(tsp, "run_vitest_plugin", fake_plugin)
        monkeypatch.setattr(tsp, "run_single_vitest_test", lambda *a, **k: {"src/a.ts": [1]})

        res = tsp.run_vitest_with_coverage(str(tmp_path), tsp.TypeScriptTestbedConfig(repo_url="x"))

        assert called["plugin"] is False
        assert res["engine"] == "per-file"

    def test_plugin_absent_uses_per_file(self, tsp, monkeypatch, tmp_path):
        monkeypatch.delenv("TIA_TS_PLUGIN", raising=False)
        monkeypatch.delenv("TIA_TS_PLUGIN_CLI", raising=False)
        monkeypatch.setattr(
            tsp, "find_test_files",
            lambda *a, **k: [str(tmp_path / "t0.test.ts")],
        )
        monkeypatch.setattr(tsp, "run_single_vitest_test", lambda *a, **k: {"src/a.ts": [1]})

        res = tsp.run_vitest_with_coverage(str(tmp_path), tsp.TypeScriptTestbedConfig(repo_url="x"))

        # No node_modules in tmp_path -> plugin CLI absent -> per-file loop.
        assert res["engine"] == "per-file"

    def test_cli_resolves_from_config_package_name(self, tsp, tmp_path, monkeypatch):
        monkeypatch.delenv("TIA_TS_PLUGIN_CLI", raising=False)
        pkg = tmp_path / "node_modules" / "@acme" / "cov"
        (pkg / "dist").mkdir(parents=True)
        cli = pkg / "dist" / "cli.js"
        cli.write_text("")

        cfg = tsp.TypeScriptTestbedConfig(repo_url="x", vitest_plugin="@acme/cov")
        assert tsp.resolve_vitest_plugin_cli(str(tmp_path), cfg) == str(cli)

    def test_cli_absent_when_not_installed(self, tsp, tmp_path, monkeypatch):
        monkeypatch.delenv("TIA_TS_PLUGIN_CLI", raising=False)
        cfg = tsp.TypeScriptTestbedConfig(repo_url="x")
        assert tsp.resolve_vitest_plugin_cli(str(tmp_path), cfg) is None


# --------------------------------------------------------------------------- #
# the workspace-detection path must be preserved (AC5)
# --------------------------------------------------------------------------- #

class TestWorkspaceDetectionPreserved:
    def test_detect_typescript_config_is_still_reachable(self):
        pw = _load("pw_detect", _INSTR / "pipeline_worker.py")
        assert hasattr(pw, "_detect_typescript_config")
        assert hasattr(pw, "detect_project_language")
