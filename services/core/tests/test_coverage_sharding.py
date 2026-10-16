"""Unit tests for full-suite sharded per-test coverage (C1).

``per_test_analyzer`` is loaded by path so these tests run without importing the
``testsquad_core.instrumentation`` package ``__init__`` (Neo4j/FastAPI deps).
"""
import importlib.util
import os
import sqlite3
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


def _encode(lines):
    if not lines:
        return b""
    nbytes = max(lines) // 8 + 1
    buf = bytearray(nbytes)
    for line in lines:
        idx, bit = divmod(line, 8)
        buf[idx] |= 1 << bit
    return bytes(buf)


def _make_db(path, data):
    """Create a coverage SQLite DB.

    ``data`` maps a pytest nodeid to ``{file_path: [executed_lines]}``.
    """
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE context (id integer primary key, context text)")
    cur.execute("CREATE TABLE file (id integer primary key, path text)")
    cur.execute("CREATE TABLE line_bits (file_id integer, context_id integer, numbits blob)")
    file_ids = {}
    for ctx_id, (nodeid, files) in enumerate(data.items(), start=1):
        cur.execute("INSERT INTO context VALUES (?, ?)", (ctx_id, f"{nodeid}|run"))
        for fpath, lines in files.items():
            if fpath not in file_ids:
                fid = len(file_ids) + 1
                file_ids[fpath] = fid
                cur.execute("INSERT INTO file VALUES (?, ?)", (fid, fpath))
            cur.execute(
                "INSERT INTO line_bits VALUES (?, ?, ?)",
                (file_ids[fpath], ctx_id, _encode(lines)),
            )
    conn.commit()
    conn.close()


class TestPartition:
    def test_all_files_covered(self, analyzer):
        files = [f"tests/test_{i}.py" for i in range(7)]
        parts = analyzer.partition_test_files(files, 3)
        flat = [f for p in parts for f in p]
        assert sorted(flat) == sorted(files)
        assert len(flat) == len(set(flat))
        assert len(parts) <= 3

    def test_single_shard_returns_one_bucket(self, analyzer):
        files = ["tests/a.py", "tests/b.py"]
        assert analyzer.partition_test_files(files, 1) == [files]

    def test_empty(self, analyzer):
        assert analyzer.partition_test_files([], 4) == []


class TestMerge:
    def test_extract_merges_shards_and_unions_lines(self, analyzer, tmp_path):
        a = tmp_path / "a.db"
        b = tmp_path / "b.db"
        _make_db(a, {"tests/test_a.py::test_one": {"/repo/src/a.py": [1, 2]}})
        _make_db(
            b,
            {
                "tests/test_a.py::test_one": {"/repo/src/a.py": [2, 3]},
                "tests/test_b.py::test_two": {"/repo/src/b.py": [5]},
            },
        )
        merged = analyzer.extract_per_test_lines(
            str(tmp_path), db_paths=[str(a), str(b)]
        )
        assert set(merged) == {"tests/test_a.py::test_one", "tests/test_b.py::test_two"}
        assert merged["tests/test_a.py::test_one"]["/repo/src/a.py"] == [1, 2, 3]
        assert merged["tests/test_b.py::test_two"]["/repo/src/b.py"] == [5]

    def test_missing_db_returns_empty(self, analyzer, tmp_path):
        assert analyzer.extract_per_test_lines(
            str(tmp_path), db_paths=[str(tmp_path / "nope.db")]
        ) == {}


class TestCompleteness:
    def test_reports_exact_shortfall(self, analyzer, tmp_path):
        scheduled = [
            str(tmp_path / "tests" / "test_a.py"),
            str(tmp_path / "tests" / "test_b.py"),
        ]
        per_test = {"tests/test_a.py::test_one": {"src/a.py": [1]}}
        c = analyzer._coverage_completeness(
            str(tmp_path), scheduled, per_test, original_count=2, collectable_count=2
        )
        assert c["test_files_scheduled"] == 2
        assert c["test_files_instrumented"] == 1
        assert c["coverage_pct"] == 50.0
        assert c["missing_test_files"] == ["tests/test_b.py"]
        assert c["missing_count"] == 1

    def test_full_coverage(self, analyzer, tmp_path):
        scheduled = [str(tmp_path / "tests" / "test_a.py")]
        per_test = {"tests/test_a.py::test_one": {"src/a.py": [1]}}
        c = analyzer._coverage_completeness(
            str(tmp_path), scheduled, per_test, original_count=1, collectable_count=1
        )
        assert c["coverage_pct"] == 100.0
        assert c["missing_count"] == 0

    def test_empty_scheduled(self, analyzer, tmp_path):
        c = analyzer._coverage_completeness(str(tmp_path), [], {}, 0, 0)
        assert c["coverage_pct"] == 0.0
        assert c["test_files_scheduled"] == 0


class TestRunTestsWithCoverage:
    def test_schedules_all_files_and_shards(self, analyzer, monkeypatch, tmp_path):
        monkeypatch.setattr(analyzer, "_install_test_deps", lambda *a, **k: None)
        monkeypatch.setattr(
            analyzer, "_filter_collectable_files", lambda vp, tb, files: list(files)
        )
        seen = []

        def fake_shard(vp, tb, shard_files, idx, cov_flag, timeout):
            seen.extend(shard_files)
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
        files = [str(tmp_path / "tests" / f"test_{i}.py") for i in range(7)]
        res = analyzer.run_tests_with_coverage(str(tmp_path), files, shards=3)

        assert res["original_count"] == 7
        assert res["collectable_count"] == 7
        assert res["scheduled_files"] == files
        assert sorted(seen) == sorted(files)
        assert len(res["coverage_files"]) == 3
        assert res["success"] is True

    def test_max_files_cap_limits_schedule(self, analyzer, monkeypatch, tmp_path):
        monkeypatch.setenv("TIA_INSTRUMENT_MAX_TEST_FILES", "2")
        monkeypatch.setattr(analyzer, "_install_test_deps", lambda *a, **k: None)
        monkeypatch.setattr(
            analyzer, "_filter_collectable_files", lambda vp, tb, files: list(files)
        )

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
        files = [str(tmp_path / "tests" / f"test_{i}.py") for i in range(5)]
        res = analyzer.run_tests_with_coverage(str(tmp_path), files, shards=1)
        assert len(res["scheduled_files"]) == 2
        assert res["collectable_count"] == 5


class TestAnalyzeWiring:
    def test_analyze_includes_completeness(self, analyzer, monkeypatch, tmp_path):
        db = tmp_path / "coverage.db"
        _make_db(db, {"tests/test_a.py::test_one": {"/repo/src/a.py": [1]}})
        scheduled = [
            str(tmp_path / "tests" / "test_a.py"),
            str(tmp_path / "tests" / "test_b.py"),
        ]

        monkeypatch.setattr(
            analyzer,
            "run_tests_with_coverage",
            lambda tb, files, shards=None, already_collected=False: {
                "success": True,
                "output": "",
                "collectable_count": 2,
                "original_count": 2,
                "coverage_files": [str(db)],
                "scheduled_files": scheduled,
            },
        )
        monkeypatch.setattr(analyzer, "resolve_to_symbols", lambda tb, ptc: [])

        out = analyzer.analyze_per_test_coverage(str(tmp_path), scheduled)
        c = out["coverage_completeness"]
        assert c["test_files_scheduled"] == 2
        assert c["test_files_instrumented"] == 1
        assert c["coverage_pct"] == 50.0
        assert c["missing_test_files"] == ["tests/test_b.py"]


class TestBitsToLines:
    def test_matches_coverage_py_encoding(self, analyzer):
        # coverage.py stores line L at byte L//8, bit L%8 (see
        # coverage.numbits.numbits_to_nums). byte 0 bit 1 == line 1.
        assert analyzer._bits_to_lines(b"") == []
        assert analyzer._bits_to_lines(_encode([1])) == [1]
        assert analyzer._bits_to_lines(_encode([7])) == [7]
        assert analyzer._bits_to_lines(_encode([8])) == [8]
        assert analyzer._bits_to_lines(_encode([9])) == [9]
        assert analyzer._bits_to_lines(_encode([1, 8, 9, 80])) == [1, 8, 9, 80]

    def test_no_off_by_one(self, analyzer):
        # Regression: decoder previously returned decoded+1, so a DB recorded
        # for line 140 decoded as 141 (a blank line) and leaked into the parent
        # class span.
        assert analyzer._bits_to_lines(_encode([140])) == [140]
        assert 141 not in analyzer._bits_to_lines(_encode([140]))

    def test_roundtrip_extract(self, analyzer, tmp_path):
        db = tmp_path / "coverage.db"
        _make_db(db, {"tests/test_a.py::test_one": {"/repo/src/a.py": [3, 8, 141]}})
        merged = analyzer.extract_per_test_lines(str(tmp_path), db_paths=[str(db)])
        assert merged["tests/test_a.py::test_one"]["/repo/src/a.py"] == [3, 8, 141]


class TestEnvInt:
    def test_default_when_unset(self, analyzer, monkeypatch):
        monkeypatch.delenv("TIA_X_TEST_KNOB", raising=False)
        assert analyzer._env_int("TIA_X_TEST_KNOB", 7) == 7

    def test_parse_and_bad_value(self, analyzer, monkeypatch):
        monkeypatch.setenv("TIA_X_TEST_KNOB", "3")
        assert analyzer._env_int("TIA_X_TEST_KNOB", 7) == 3
        monkeypatch.setenv("TIA_X_TEST_KNOB", "abc")
        assert analyzer._env_int("TIA_X_TEST_KNOB", 7) == 7
