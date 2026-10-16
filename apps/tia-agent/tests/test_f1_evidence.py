"""E4/F1: evidence-first analysis, deterministic fallback, dedupe, existence."""

import pytest

from tia_agent.analyze import AnalyzeRunner
from tia_agent.config import TiaConfig
from tia_agent.radius_client import ProjectInfo
from tia_agent.tools import fs


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class _FakeRadius:
    base_url = "http://radius:8000"

    def __init__(self, raw):
        self.raw = raw
        self.analyzed = []

    def list_projects(self):
        return [ProjectInfo(id=1, name="acme/shop")]

    def analyze_pr(self, **kwargs):
        self.analyzed.append(kwargs)
        return self.raw


class _FakeGuard:
    def __init__(self):
        self.recorded = []

    def ensure_valid(self):
        pass

    def record_run(self, run_id, repo_hash, metadata):
        self.recorded.append((run_id, repo_hash, metadata))


def _runner(raw):
    return AnalyzeRunner(TiaConfig(), _FakeGuard(), _FakeRadius(raw))


# py-key-value TTL shape: evidence maps an existing symbol to a real test file.
TTL_RAW = {
    "pr_files_analyzed": 1,
    "pr_files": ["src/key_value/aio/_utils/time_to_live.py"],
    "symbols_selected": 2,
    "tests_selected": 1,
    "total_tests_reused": 1,
    "results": [
        {
            "symbol_name": "prepare_ttl",
            "existing_tests": [
                {"test_name": "test_prepare_ttl", "test_file": "tests/utils/test_time_to_live.py"}
            ],
        }
    ],
}

# New-file shape: no symbols, no mappings.
NEW_FILE_RAW = {
    "pr_files_analyzed": 1,
    "pr_files": ["src/key_value/aio/new_module.py"],
    "symbols_selected": 0,
    "tests_selected": 0,
    "total_tests_reused": 0,
    "results": [],
}


def _write(repo, rel, text=""):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ---------------------------------------------------------------------------
# acceptance: TTL case (no fallback) / new-file case (fallback)
# ---------------------------------------------------------------------------

def test_ttl_case_valid_impacted_tests_without_fallback(tmp_path):
    _write(tmp_path, "src/key_value/aio/_utils/time_to_live.py", "def prepare_ttl(): ...")
    _write(tmp_path, "tests/utils/test_time_to_live.py", "def test_prepare_ttl(): ...")

    res = _runner(TTL_RAW).to_result(
        TTL_RAW, "hbahuguna/py-key-value", 1, repo_path=str(tmp_path)
    )
    assert res.fallback_used is False
    assert res.fallback_reason is None
    assert res.total_affected_tests == 1
    assert [t["file"] for t in res.tests] == ["tests/utils/test_time_to_live.py"]
    assert res.confidence == "high"
    assert res.run_commands == ["pytest tests/utils/test_time_to_live.py::test_prepare_ttl"]
    assert not any("dropped" in n for n in res.notes)


def test_new_file_case_returns_fallback_used(tmp_path):
    _write(tmp_path, "tests/test_store.py", "def test_store(): ...")
    _write(tmp_path, "tests/utils/test_misc.py", "def test_misc(): ...")

    res = _runner(NEW_FILE_RAW).to_result(
        NEW_FILE_RAW, "hbahuguna/py-key-value", 2, repo_path=str(tmp_path)
    )
    assert res.fallback_used is True
    assert res.fallback_reason and "full test suite" in res.fallback_reason
    assert res.total_affected_tests == len(res.tests) == 2
    assert res.confidence == "low"
    assert res.run_commands  # discovered tests produce runnable commands


def test_new_file_case_without_repo_path_still_flags_fallback():
    res = _runner(NEW_FILE_RAW).to_result(NEW_FILE_RAW, "acme/shop", 2)
    assert res.fallback_used is True
    assert res.tests == []


def test_run_threads_repo_path_from_config(tmp_path):
    _write(tmp_path, "tests/test_a.py", "")
    cfg = TiaConfig()
    cfg.repo_path = str(tmp_path)
    runner = AnalyzeRunner(cfg, _FakeGuard(), _FakeRadius(NEW_FILE_RAW))
    res = runner.run(repo="acme/shop", pr_number=1)
    assert res.fallback_used is True
    assert [t["file"] for t in res.tests] == ["tests/test_a.py"]


# ---------------------------------------------------------------------------
# existence check
# ---------------------------------------------------------------------------

def test_missing_reported_test_is_dropped_and_flags_fallback(tmp_path):
    raw = {
        "pr_files_analyzed": 1,
        "pr_files": ["src/x.py"],
        "symbols_selected": 1,
        "tests_selected": 1,
        "total_tests_reused": 1,
        "results": [
            {"symbol_name": "f", "existing_tests": [
                {"test_name": "t", "test_file": "tests/test_gone.py"}]}
        ],
    }
    _write(tmp_path, "src/x.py", "def f(): ...")  # test file does NOT exist

    res = _runner(raw).to_result(raw, "acme/shop", 3, repo_path=str(tmp_path))
    assert res.tests == []
    assert res.fallback_used is True
    assert "not found in the repo" in res.fallback_reason
    assert any("dropped" in n for n in res.notes)


def test_existing_test_kept_and_missing_dropped(tmp_path):
    raw = {
        "pr_files_analyzed": 1,
        "symbols_selected": 2,
        "tests_selected": 2,
        "total_tests_reused": 2,
        "results": [
            {"symbol_name": "a", "existing_tests": [
                {"test_name": "t1", "test_file": "tests/test_here.py"}]},
            {"symbol_name": "b", "existing_tests": [
                {"test_name": "t2", "test_file": "tests/test_missing.py"}]},
        ],
    }
    _write(tmp_path, "tests/test_here.py", "def t1(): ...")

    res = _runner(raw).to_result(raw, "acme/shop", 4, repo_path=str(tmp_path))
    assert [t["file"] for t in res.tests] == ["tests/test_here.py"]
    assert res.total_affected_tests == 1
    assert res.fallback_used is False  # one valid test remains


def test_container_absolute_paths_are_resolved(tmp_path):
    raw = {
        "pr_files_analyzed": 1,
        "symbols_selected": 1,
        "tests_selected": 1,
        "total_tests_reused": 1,
        "results": [
            {"symbol_name": "a", "existing_tests": [
                {"test_name": "t", "test_file": "/workdir/repo/tests/test_x.py"}]}
        ],
    }
    _write(tmp_path, "tests/test_x.py", "def t(): ...")
    res = _runner(raw).to_result(raw, "acme/shop", 5, repo_path=str(tmp_path))
    assert res.fallback_used is False
    assert res.tests[0]["file"] == "/workdir/repo/tests/test_x.py"


# ---------------------------------------------------------------------------
# dedupe
# ---------------------------------------------------------------------------

def test_duplicate_tests_are_deduped():
    raw = {
        "pr_files_analyzed": 1,
        "symbols_selected": 2,
        "tests_selected": 2,
        "total_tests_reused": 2,
        "results": [
            {"symbol_name": "a", "existing_tests": [
                {"test_name": "t", "test_file": "tests/test_x.py"}]},
            {"symbol_name": "b", "existing_tests": [
                {"test_name": "t", "test_file": "tests/test_x.py"}]},
        ],
    }
    res = _runner(raw).to_result(raw, "acme/shop", 6)
    assert len(res.tests) == 1


# ---------------------------------------------------------------------------
# fallback discovery (read-only fs)
# ---------------------------------------------------------------------------

def test_discover_prefers_related_tests(tmp_path):
    _write(tmp_path, "tests/utils/test_time_to_live.py", "")
    _write(tmp_path, "tests/other/test_unrelated.py", "")
    found = fs.discover_tests_fallback(
        ["src/key_value/aio/_utils/time_to_live.py"], str(tmp_path)
    )
    assert [t["file"] for t in found] == ["tests/utils/test_time_to_live.py"]
    assert "related" in found[0]["reason"]


def test_discover_falls_back_to_full_suite(tmp_path):
    _write(tmp_path, "tests/test_a.py", "")
    _write(tmp_path, "tests/test_b.py", "")
    found = fs.discover_tests_fallback(["src/brand_new.py"], str(tmp_path))
    assert {t["file"] for t in found} == {"tests/test_a.py", "tests/test_b.py"}
    assert all("full local test suite" in t["reason"] for t in found)


def test_discover_fallback_tests_carry_reason_and_confidence(tmp_path):
    # V2: even fallback selections are not opaque — each carries a reason
    # and a confidence (no evidence -> low).
    _write(tmp_path, "tests/test_a.py", "")
    found = fs.discover_tests_fallback(["src/brand_new.py"], str(tmp_path))
    assert found
    assert all(t["confidence"] == "low" for t in found)
    assert all(t["reason"] for t in found)


def test_iter_test_files_skips_dependency_dirs(tmp_path):
    _write(tmp_path, "tests/test_real.py", "")
    _write(tmp_path, "node_modules/pkg/test_junk.py", "")
    _write(tmp_path, "src/app.spec.ts", "")
    found = fs.iter_test_files(str(tmp_path))
    assert found == ["src/app.spec.ts", "tests/test_real.py"]


def test_repo_relative_and_exists():
    assert fs.repo_relative("/workdir/myrepo/tests/test_x.py") == "tests/test_x.py"
    assert fs.repo_relative("/testradius/tests/test_x.py") == "tests/test_x.py"
    assert fs.repo_relative("tests/test_x.py") == "tests/test_x.py"


@pytest.mark.parametrize("path", ["tests/test_a.py", "a_test.py", "src/app.spec.ts",
                                   "tests/__tests__/x.test.tsx", "spec/util.js"])
def test_is_test_file_true(path):
    assert fs.is_test_file(path)


@pytest.mark.parametrize("path", ["src/app.py", "src/index.ts", "README.md", "lib/util.js"])
def test_is_test_file_false(path):
    assert not fs.is_test_file(path)
