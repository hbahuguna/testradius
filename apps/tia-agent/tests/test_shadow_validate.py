"""E6/V1: shadow-validation harness — pure logic + corpus discovery.

Loads ``scripts/tia_agent/shadow_validate.py`` by path (it is a standalone,
stdlib-only CI artifact, not an installed package) and exercises the pure
functions plus the corpus parser against a real temporary git repo.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_PATH = REPO_ROOT / "scripts" / "tia_agent" / "shadow_validate.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("shadow_validate", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["shadow_validate"] = module
    spec.loader.exec_module(module)
    return module


sv = _load_harness()


# ---------------------------------------------------------------------------
# parse_pytest_failures
# ---------------------------------------------------------------------------

def test_parse_failures_extracts_nodeids():
    text = (
        "tests/a/test_x.py::TestA::test_one PASSED\n"
        "FAILED tests/a/test_x.py::TestA::test_two - AssertionError: nope\n"
        "FAILED tests/b/test_y.py::test_three - ValueError\n"
        "2 failed, 5 passed\n"
    )
    assert sv.parse_pytest_failures(text) == [
        "tests/a/test_x.py::TestA::test_two",
        "tests/b/test_y.py::test_three",
    ]


def test_parse_failures_ignores_errors_and_dedupes():
    text = (
        "ERROR tests/c/test_z.py - ImportError: no botocore\n"
        "FAILED tests/a/test_x.py::test_two - AssertionError\n"
        "FAILED tests/a/test_x.py::test_two - AssertionError\n"
    )
    assert sv.parse_pytest_failures(text) == ["tests/a/test_x.py::test_two"]


def test_parse_failures_empty():
    assert sv.parse_pytest_failures("1322 passed, 82 skipped") == []


# ---------------------------------------------------------------------------
# path + edge helpers
# ---------------------------------------------------------------------------

def test_normalize_path():
    assert sv.normalize_path("./src/a.py") == "src/a.py"
    assert sv.normalize_path("src\\a.py") == "src/a.py"
    assert sv.normalize_path("  src/a.py  ") == "src/a.py"


def test_run_full_suite_requests_failed_summary(monkeypatch, tmp_path):
    captured = {}

    class _Result:
        returncode = 1
        stdout = "FAILED tests/a/test_x.py::TestA::test_two - AssertionError\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Result()

    monkeypatch.setattr(sv.subprocess, "run", fake_run)
    result = sv.run_full_suite(str(tmp_path), "py", "tests/")
    # `-rN` would suppress the FAILED summary lines the parser depends on.
    assert "-rf" in captured["cmd"]
    assert "-rN" not in captured["cmd"]
    assert result["failures"] == ["tests/a/test_x.py::TestA::test_two"]


def test_edges_for_test_keeps_only_evidence_and_normalizes():
    rows = [
        {
            "test_symbol": "tests/t.py::test_a",
            "product_symbol": "find_spec",
            "product_file": "./src/key_value/__init__.py",
            "status": "EVIDENCE",
        },
        {
            "test_symbol": "tests/t.py::test_a",
            "product_symbol": "Other",
            "product_file": "src/other.py",
            "status": "APPROVED_TEST",
        },
    ]
    edges = sv.edges_for_test(rows)
    assert len(edges) == 1
    assert edges[0].symbol == "find_spec"
    assert edges[0].symbol_file == "src/key_value/__init__.py"


# ---------------------------------------------------------------------------
# attribution + misses + gaps
# ---------------------------------------------------------------------------

def _edges(test, files):
    return [sv.TestEdge(test=test, symbol="s", symbol_file=f) for f in files]


def test_attributable_failures_matches_edits_file():
    failing = ["tests/t.py::test_a", "tests/t.py::test_b"]
    edges = {
        "tests/t.py::test_a": _edges("tests/t.py::test_a", ["src/key_value/__init__.py"]),
        "tests/t.py::test_b": _edges("tests/t.py::test_b", ["src/other.py"]),
    }
    got = sv.attributable_failures(failing, ["./src/key_value/__init__.py"], edges)
    assert got == ["tests/t.py::test_a"]


def test_evaluate_entry_flags_miss_and_gap():
    entry = sv.CorpusEntry(label="c", files=["src/key_value/__init__.py", "src/v/x.py"], sha="abc")
    failing = ["tests/t.py::test_a", "tests/t.py::test_b"]
    edges = {
        "tests/t.py::test_a": _edges("tests/t.py::test_a", ["src/key_value/__init__.py"]),
        "tests/t.py::test_b": _edges("tests/t.py::test_b", ["src/unrelated.py"]),
    }
    # test_a is attributable but NOT selected -> a miss; test_b is a gap.
    selected = ["tests/t.py::test_b"]
    report = sv.evaluate_entry(
        entry, selected, failing, edges, {"src/v/x.py": ["ValkeyStore"]}
    )
    assert report["attributable_failures"] == ["tests/t.py::test_a"]
    assert report["missed"] == ["tests/t.py::test_a"]
    assert report["unselected_failures"] == ["tests/t.py::test_a"]
    assert report["gaps"][0]["test"] == "tests/t.py::test_a"
    assert report["gaps"][0]["attributable"] is True
    assert {"test": "tests/t.py::test_a", "symbol": "ValkeyStore", "symbol_file": "src/v/x.py"} in (
        report["gaps"][0]["suggested_edges"]
    )


def test_evaluate_entry_selected_failing_test_is_not_a_miss():
    entry = sv.CorpusEntry(label="c", files=["src/key_value/__init__.py"])
    failing = ["tests/t.py::test_a"]
    edges = {"tests/t.py::test_a": _edges("tests/t.py::test_a", ["src/key_value/__init__.py"])}
    report = sv.evaluate_entry(entry, failing, failing, edges, {})
    assert report["missed"] == []
    assert report["gaps"] == []


def test_suggested_edges_dedupes_and_limits():
    by_file = {"a.py": ["S1", "S2"], "b.py": ["S2", "S3"]}
    got = sv.suggested_edges("t", by_file, ["a.py", "b.py"], limit=2)
    assert got == [
        {"test": "t", "symbol": "S1", "symbol_file": "a.py"},
        {"test": "t", "symbol": "S2", "symbol_file": "a.py"},
    ]


# ---------------------------------------------------------------------------
# summary + exit codes
# ---------------------------------------------------------------------------

def test_summarize_coverage_and_counts():
    reports = [
        {"attributable_failures": ["a", "b"], "missed": ["b"], "gaps": [{}, {}]},
        {"attributable_failures": ["c"], "missed": [], "gaps": [{}]},
    ]
    summary = sv.summarize(reports, ["a", "b", "c", "d"])
    assert summary["entries_run"] == 2
    assert summary["failing_tests_total"] == 4
    assert summary["attributable_total"] == 3
    assert summary["missed_total"] == 1
    assert summary["gaps_total"] == 3
    assert summary["coverage"] == 0.6667


def test_summarize_coverage_none_without_attributable():
    summary = sv.summarize([{"attributable_failures": [], "missed": [], "gaps": []}], ["x"])
    assert summary["coverage"] is None


@pytest.mark.parametrize(
    "missed,size,min_prs,expected",
    [
        (0, 12, 10, 0),
        (1, 12, 10, 1),
        (0, 3, 10, 3),
    ],
)
def test_resolve_exit_code(missed, size, min_prs, expected):
    summary = {"missed_total": missed}
    assert sv.resolve_exit_code(summary, size, min_prs) == expected


# ---------------------------------------------------------------------------
# corpus discovery
# ---------------------------------------------------------------------------

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def test_discover_history_corpus_parses_git_log(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.io")
    _git(repo, "config", "user.name", "T")
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    for i in range(3):
        (repo / "src" / f"mod{i}.py").write_text(f"x = {i}\n")
        (repo / "tests" / f"test{i}.py").write_text("def test_x():\n    assert True\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"change {i}")

    entries = sv.discover_history_corpus(str(repo), product_dir="src/", max_entries=10)
    assert len(entries) == 3
    # newest first, and only product files are listed
    assert entries[0].label.startswith(entries[0].sha[:8])
    assert all(f.startswith("src/") for e in entries for f in e.files)
    assert entries[0].files == ["src/mod2.py"]


def test_discover_file_corpus(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text(
        json.dumps([{"label": "e1", "files": ["./src/a.py"], "pr_number": 7}])
    )
    entries = sv.discover_file_corpus(str(path))
    assert len(entries) == 1
    assert entries[0].files == ["src/a.py"]
    assert entries[0].pr_number == 7


# ---------------------------------------------------------------------------
# orchestration (fake backend)
# ---------------------------------------------------------------------------

class FakeBackend:
    def __init__(self, selections, edges, symbols=None):
        self.selections = selections
        self.edges = edges
        self.symbols = symbols or {}

    def select_tests(self, entry, anchor):
        return {"selected_tests": self.selections.get(entry.label, [])}

    def edges_for_test(self, nodeid, limit=1000):
        return self.edges.get(nodeid, [])

    def symbols_in_file(self, path, limit=500):
        return self.symbols.get(sv.normalize_path(path), [])


def test_run_shadow_clean_pass():
    entries = [
        sv.CorpusEntry(label="c1", files=["src/key_value/__init__.py"], sha="a"),
        sv.CorpusEntry(label="c2", files=["src/v/store.py"], sha="b"),
    ]
    failing = ["tests/t.py::test_a"]
    edges = {"tests/t.py::test_a": _edges("tests/t.py::test_a", ["src/key_value/__init__.py"])}
    backend = FakeBackend(
        selections={"c1": ["tests/t.py::test_a"], "c2": []},
        edges=edges,
        symbols={"src/v/store.py": ["ValkeyStore"]},
    )
    report = sv.run_shadow(entries, failing, backend, "anchor", corpus_source="file")
    assert report["summary"]["missed_total"] == 0
    assert report["summary"]["attributable_total"] == 1
    assert report["summary"]["coverage"] == 1.0
    # c2 has a gap (failing test unselected against a valkey change, no edge)
    assert report["entries"][1]["gaps"][0]["suggested_edges"][0]["symbol"] == "ValkeyStore"


def test_run_shadow_detects_miss():
    entries = [sv.CorpusEntry(label="c1", files=["src/key_value/__init__.py"], sha="a")]
    failing = ["tests/t.py::test_a"]
    edges = {"tests/t.py::test_a": _edges("tests/t.py::test_a", ["src/key_value/__init__.py"])}
    backend = FakeBackend(selections={"c1": []}, edges=edges)
    report = sv.run_shadow(entries, failing, backend, "anchor", corpus_source="file")
    assert report["summary"]["missed_total"] == 1
    assert sv.resolve_exit_code(report["summary"], 1, 0) == 1


def test_self_test_backend_injects_miss_and_run_shadow_returns_nonzero():
    entries = [sv.CorpusEntry(label="c1", files=["src/key_value/__init__.py"], sha="a")]
    failing = ["tests/t.py::test_a"]
    edges = {"tests/t.py::test_a": _edges("tests/t.py::test_a", ["src/key_value/__init__.py"])}
    inner = FakeBackend(selections={"c1": ["tests/t.py::test_a"]}, edges=edges)
    backend = sv.SelfTestBackend(inner, failing)
    assert backend.marker_test == "tests/t.py::test_a"
    assert backend.marker_file == "src/key_value/__init__.py"
    report = sv.run_shadow(entries, failing, backend, "anchor", corpus_source="file")
    assert report["summary"]["missed_total"] == 1
    assert sv.resolve_exit_code(report["summary"], 1, 0) == 1


def test_self_test_backend_no_edges_is_inert():
    backend = sv.SelfTestBackend(FakeBackend({}, {}), ["tests/t.py::test_a"])
    assert backend.marker_file is None


def test_main_rejects_small_corpus(tmp_path):
    path = tmp_path / "small.json"
    path.write_text(json.dumps([{"label": "e1", "files": ["src/a.py"]}]))
    code = sv.main(
        [
            "--checkout",
            str(tmp_path),
            "--project-id",
            "3",
            "--corpus",
            "file",
            "--corpus-file",
            str(path),
            "--min-prs",
            "10",
        ]
    )
    assert code == 3
