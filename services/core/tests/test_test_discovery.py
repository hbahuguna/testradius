"""Unit tests for pytest-driven test discovery (G3).

``per_test_analyzer`` is loaded by path so these tests run without importing the
``testsquad_core.instrumentation`` package ``__init__`` (Neo4j/FastAPI deps).
"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

_ANALYZER_PATH = (
    Path(__file__).resolve().parents[1]
    / "testsquad_core"
    / "instrumentation"
    / "per_test_analyzer.py"
)


def _load_analyzer():
    spec = importlib.util.spec_from_file_location("per_test_analyzer", _ANALYZER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def analyzer():
    return _load_analyzer()


class TestNormalizeNodeid:
    def test_strips_trailing_separator(self, analyzer):
        assert analyzer._normalize_nodeid("tests/snippets/scheme/numbers.txt::") == (
            "tests/snippets/scheme/numbers.txt"
        )

    def test_preserves_named_nodeid(self, analyzer):
        nid = "tests/test_a.py::TestX::test_y[1]"
        assert analyzer._normalize_nodeid(nid) == nid

    def test_preserves_plain_file(self, analyzer):
        assert analyzer._normalize_nodeid("tests/test_a.py") == "tests/test_a.py"


class TestReadCollectedFiles:
    def test_parses_and_absolutizes(self, analyzer, tmp_path):
        out = tmp_path / "collected.json"
        out.write_text(json.dumps([
            {"nodeid": "tests/test_a.py::test_one"},
            {"nodeid": "tests/test_a.py::test_two"},
            {"nodeid": "tests/snippets/scheme/numbers.txt::"},
        ]))
        got = analyzer._read_collected_files(str(out), str(tmp_path))
        assert got == [
            str(tmp_path / "tests/snippets/scheme/numbers.txt"),
            str(tmp_path / "tests/test_a.py"),
        ]

    def test_empty_file_returns_empty(self, analyzer, tmp_path):
        out = tmp_path / "collected.json"
        out.write_text("")
        assert analyzer._read_collected_files(str(out), str(tmp_path)) == []

    def test_missing_file_returns_empty(self, analyzer, tmp_path):
        assert analyzer._read_collected_files(
            str(tmp_path / "nope.json"), str(tmp_path)
        ) == []

    def test_malformed_returns_empty(self, analyzer, tmp_path):
        out = tmp_path / "collected.json"
        out.write_text("{not json")
        assert analyzer._read_collected_files(str(out), str(tmp_path)) == []


class TestDiscoverCollectedFiles:
    def test_runs_plugin_and_reads_output(self, analyzer, monkeypatch, tmp_path):
        captured = {}

        def fake_run(cmd, cwd=None, env=None, capture_output=None, text=None, timeout=None):
            captured["cmd"] = cmd
            captured["cwd"] = cwd
            captured["env"] = env
            out = env["TIA_COLLECT_OUT"]
            with open(out, "w") as fh:
                json.dump([{"nodeid": "tests/test_a.py::test_one"}], fh)

            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            return R()

        monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
        files = analyzer.discover_collected_files(str(tmp_path), "tests")
        assert files == [str(tmp_path / "tests/test_a.py")]
        assert "tests" in captured["cmd"]
        assert "--collect-only" in captured["cmd"]
        assert analyzer._COLLECT_PLUGIN_MODULE in captured["cmd"]
        assert captured["cwd"] == str(tmp_path)

    def test_timeout_returns_empty(self, analyzer, monkeypatch, tmp_path):
        def fake_run(*a, **k):
            raise analyzer.subprocess.TimeoutExpired(cmd="pytest", timeout=1)

        monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
        assert analyzer.discover_collected_files(str(tmp_path), "tests") == []

    def test_no_output_file_returns_empty(self, analyzer, monkeypatch, tmp_path):
        def fake_run(*a, **k):
            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            return R()

        monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
        assert analyzer.discover_collected_files(str(tmp_path), "tests") == []


class TestInstallDepsCache:
    def test_second_call_is_cached(self, analyzer, monkeypatch, tmp_path):
        analyzer._DEPS_INSTALLED.clear()
        calls = []

        def fake_run(*a, **k):
            calls.append(a)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
        analyzer._install_test_deps("/venv/bin/python", str(tmp_path))
        first = len(calls)
        analyzer._install_test_deps("/venv/bin/python", str(tmp_path))
        assert first > 0
        assert len(calls) == first


class TestAlreadyCollected:
    def test_skips_collectability_probe(self, analyzer, monkeypatch, tmp_path):
        monkeypatch.setattr(analyzer, "_install_test_deps", lambda *a, **k: None)
        probed = []

        def fake_filter(vp, tb, files):
            probed.append(list(files))
            return []

        monkeypatch.setattr(analyzer, "_filter_collectable_files", fake_filter)

        def fake_shard(vp, tb, shard_files, idx, cov_flag, timeout):
            p = os.path.join(tb, f".coverage.shard{idx}")
            with open(p, "wb") as fh:
                fh.write(b"data")
            return {
                "shard": idx,
                "returncode": 0,
                "output": "ok",
                "coverage_file": p,
                "files": shard_files,
            }

        monkeypatch.setattr(analyzer, "_run_coverage_shard", fake_shard)
        files = [str(tmp_path / "tests" / "snippets" / "a.txt")]
        res = analyzer.run_tests_with_coverage(
            str(tmp_path), files, shards=1, already_collected=True
        )
        assert probed == []
        assert res["collectable_count"] == 1
        assert res["scheduled_files"] == files

    def test_probe_runs_when_not_precollected(self, analyzer, monkeypatch, tmp_path):
        monkeypatch.setattr(analyzer, "_install_test_deps", lambda *a, **k: None)
        probed = []

        def fake_filter(vp, tb, files):
            probed.append(list(files))
            return list(files)

        monkeypatch.setattr(analyzer, "_filter_collectable_files", fake_filter)

        def fake_shard(vp, tb, shard_files, idx, cov_flag, timeout):
            p = os.path.join(tb, f".coverage.shard{idx}")
            with open(p, "wb") as fh:
                fh.write(b"data")
            return {
                "shard": idx,
                "returncode": 0,
                "output": "ok",
                "coverage_file": p,
                "files": shard_files,
            }

        monkeypatch.setattr(analyzer, "_run_coverage_shard", fake_shard)
        files = [str(tmp_path / "tests" / "test_a.py")]
        analyzer.run_tests_with_coverage(str(tmp_path), files, shards=1)
        assert probed == [files]

    def test_analyze_forwards_already_collected(self, analyzer, monkeypatch, tmp_path):
        seen = {}

        def fake_run(tb, files, shards=None, already_collected=False):
            seen["already_collected"] = already_collected
            return {
                "success": True,
                "output": "",
                "collectable_count": len(files),
                "original_count": len(files),
                "coverage_files": [],
                "scheduled_files": list(files),
            }

        monkeypatch.setattr(analyzer, "run_tests_with_coverage", fake_run)
        monkeypatch.setattr(analyzer, "resolve_to_symbols", lambda tb, ptc: [])
        analyzer.analyze_per_test_coverage(
            str(tmp_path), [str(tmp_path / "tests" / "a.txt")], already_collected=True
        )
        assert seen["already_collected"] is True


class TestShardCommand:
    def test_continues_past_collection_errors(self, analyzer, monkeypatch, tmp_path):
        seen = {}

        def fake_run(cmd, cwd=None, env=None, capture_output=None, text=None, timeout=None):
            seen["cmd"] = cmd

            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            return R()

        monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
        analyzer._run_coverage_shard(
            "/venv/bin/python", str(tmp_path),
            [str(tmp_path / "tests" / "examplefiles" / "python" / "switch_case.py")],
            0, "--cov", 60,
        )
        assert "--continue-on-collection-errors" in seen["cmd"]

