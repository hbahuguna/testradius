import pytest
from tia_agent.analyze import AnalyzeRunner, TiaResult
from tia_agent.config import TiaConfig
from tia_agent.errors import AnalysisError, BackendError, LicenseError
from tia_agent.radius_client import ProjectInfo


class _FakeRadius:
    def __init__(self, projects=None, raw=None, error=None, base_url="http://radius:8000"):
        self.projects = projects if projects is not None else [ProjectInfo(id=7, name="owner/repo")]
        self.raw = raw if raw is not None else _sample_raw()
        self.error = error
        self.base_url = base_url
        self.analyzed = []

    def list_projects(self):
        return self.projects

    def analyze_pr(self, **kwargs):
        self.analyzed.append(kwargs)
        if self.error:
            raise self.error
        return self.raw

    def run_instrumentation(self, payload):
        return {"status": "COMPLETED"}


class _FakeGuard:
    def __init__(self, valid=True, record_error=None, blocked_msg=""):
        self.valid = valid
        self.record_error = record_error
        self.blocked_msg = blocked_msg
        self.recorded = []

    def ensure_valid(self):
        if not self.valid:
            raise LicenseError(self.blocked_msg or "License expired")

    def activate(self, key):
        return {"subscription_status": "active", "quota_remaining": 10}

    def status(self):
        return {"status": "valid"}

    def record_run(self, run_id, repo_hash, metadata):
        if self.record_error:
            raise self.record_error
        self.recorded.append((run_id, repo_hash, metadata))


def _sample_raw():
    return {
        "project_id": 7,
        "full_name": "owner/repo",
        "pr_number": 3,
        "commit_sha": "abc123",
        "pr_files_analyzed": 2,
        "symbols_selected": 2,
        "tests_selected": 1,
        "total_tests_reused": 1,
        "results": [
            {
                "symbol_name": "prepare_ttl",
                "symbol_file": "src/key_value/aio/_utils/time_to_live.py",
                "symbol_summary": "",
                "symbol_type": "function",
                "priority_risk_index": 5500.0,
                "existing_tests": [{"test_name": "test_prepare_ttl", "test_file": "tests/test_ttl.py"}],
            }
        ],
    }


def _make_runner():
    config = TiaConfig()
    radius = _FakeRadius()
    guard = _FakeGuard()
    return config, radius, guard


def test_runner_maps_response_to_schema():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.run(repo="owner/repo", pr_number=3)
    assert isinstance(res, TiaResult)
    d = res.to_dict()
    assert d["repo"] == "owner/repo"
    assert d["pr_number"] == 3
    assert d["symbols_selected"] == 2
    assert d["tests_selected"] == 1
    assert d["total_affected_tests"] == 1
    assert d["confidence"] == "high"
    assert len(d["tests"]) == 1
    assert d["tests"][0]["name"] == "test_prepare_ttl"
    assert d["tests"][0]["file"] == "tests/test_ttl.py"
    assert d["tests"][0]["language"] == "python"
    assert d["tests"][0]["nodeid"] == "tests/test_ttl.py::test_prepare_ttl"


def test_runner_returns_language_for_typescript():
    raw = _sample_raw()
    raw["results"][0]["existing_tests"] = [
        {"test_name": "a test", "test_file": "tests/home.spec.ts"}
    ]
    config, radius, guard = _make_runner()
    radius.raw = raw
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.run(repo="owner/repo", pr_number=3)
    assert res.tests[0]["language"] == "typescript"
    assert "npx playwright test" in res.run_commands[0]


def test_runner_meters_after_success():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.run(repo="owner/repo", pr_number=3)
    assert len(guard.recorded) == 1
    run_id, repo_hash, metadata = guard.recorded[0]
    assert run_id == res.tia_run_id
    assert repo_hash  # sha256 hex
    assert len(repo_hash) == 64


def test_metering_metadata_is_summary_only():
    """D12: license server sees counts/timing only — never test names or paths."""
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    runner.run(repo="owner/repo", pr_number=3)
    _, _, metadata = guard.recorded[0]
    allowed = {
        "file_count", "test_count", "language",
        "duration_seconds", "os", "agent_version",
    }
    assert set(metadata) <= allowed
    # The repo content itself must not leak either
    blob = str(metadata)
    assert "prepare_ttl" not in blob
    assert "test_prepare_ttl" not in blob


def test_runner_blocks_when_license_invalid():
    config, radius, guard = _make_runner()
    guard.valid = False
    runner = AnalyzeRunner(config, guard, radius)
    with pytest.raises(LicenseError):
        runner.run(repo="owner/repo", pr_number=3)


def test_runner_no_analysis_when_license_blocked():
    config, radius, guard = _make_runner()
    guard.valid = False
    runner = AnalyzeRunner(config, guard, radius)
    try:
        runner.run(repo="owner/repo", pr_number=3)
    except LicenseError:
        pass
    assert radius.analyzed == []


def test_resolve_project_not_found_raises_guidance():
    config = TiaConfig()
    radius = _FakeRadius(projects=[ProjectInfo(id=1, name="other/repo")])
    guard = _FakeGuard()
    runner = AnalyzeRunner(config, guard, radius)
    with pytest.raises(AnalysisError):
        runner.run(repo="missing/repo", pr_number=1)


def test_backend_error_propagates():
    config, radius, guard = _make_runner()
    radius.error = BackendError("analyze-pr failed: HTTP 500")
    runner = AnalyzeRunner(config, guard, radius)
    with pytest.raises(BackendError):
        runner.run(repo="owner/repo", pr_number=3)


def test_resolve_matches_url_and_suffix():
    from tia_agent.radius_client import RadiusClient, ProjectInfo
    from tia_agent.tools.project import resolve_project_for_repo

    class _R:
        def __init__(self, projects):
            self._p = projects

        def list_projects(self):
            return self._p

    r = _R(
        [
            ProjectInfo(id=1, name="org/other"),
            ProjectInfo(id=2, name="owner/repo"),
        ]
    )
    assert resolve_project_for_repo(r, "https://github.com/owner/repo.git").id == 2
    assert resolve_project_for_repo(r, "owner/repo").id == 2


def test_fallback_flag_when_no_symbols():
    raw = _sample_raw()
    raw["symbols_selected"] = 0
    raw["tests_selected"] = 0
    raw["total_tests_reused"] = 0
    raw["results"] = []
    config, radius, guard = _make_runner()
    radius.raw = raw
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.run(repo="owner/repo", pr_number=3)
    assert res.fallback_used is True
    assert res.fallback_reason and "full test suite" in res.fallback_reason
    assert res.confidence == "low"