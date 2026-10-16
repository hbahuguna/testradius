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
    # A failed analysis must never be metered (D1).
    assert guard.recorded == []


def test_meter_failure_is_soft_and_keeps_result():
    """E7/E2: expiry mid-session / quota-at-record must not discard the analysis."""
    config, radius, guard = _make_runner()
    guard.record_error = LicenseError("Run completed but was not counted: subscription expired")
    runner = AnalyzeRunner(config, guard, radius)
    events = []
    res = runner.run(repo="owner/repo", pr_number=3, on_event=lambda k, d: events.append(k))
    assert res.total_affected_tests == 1  # analysis preserved
    assert any("not counted" in n for n in res.notes)
    assert "meter_warning" in events
    assert "metered" not in events


def test_meter_success_emits_metered_event():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    events = []
    runner.run(repo="owner/repo", pr_number=3, on_event=lambda k, d: events.append(k))
    assert "metered" in events
    assert "meter_warning" not in events


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


def _truncated_raw(dropped_tests):
    raw = _sample_raw()
    raw.update(
        {
            "truncated": True,
            "symbols_total": 25,
            "max_symbols": 10,
            "truncation_dropped_tests": dropped_tests,
        }
    )
    return raw


def test_analyze_result_round_trips_truncation():
    from tia_agent.tools.models import AnalyzeResult

    raw = _truncated_raw(dropped_tests=True)
    parsed = AnalyzeResult.from_raw(raw)
    assert parsed.truncated is True
    assert parsed.symbols_total == 25
    assert parsed.max_symbols == 10
    assert parsed.truncation_dropped_tests is True
    out = parsed.to_raw()
    assert out["truncated"] is True
    assert out["symbols_total"] == 25
    assert out["truncation_dropped_tests"] is True


def test_truncation_without_dropped_tests_is_reported_not_fatal():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    raw = _truncated_raw(dropped_tests=False)
    res = runner.to_result(raw, "owner/repo", 3)
    assert res.fallback_used is False
    assert any("truncated" in n and "25" in n for n in res.notes)


def test_truncation_that_drops_tests_forces_fallback():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    raw = _truncated_raw(dropped_tests=True)
    res = runner.to_result(raw, "owner/repo", 3)
    assert res.fallback_used is True
    assert res.fallback_reason and "full test suite" in res.fallback_reason
    assert any("forcing full-suite fallback" in n for n in res.notes)


def test_no_truncation_emits_no_truncation_note():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.to_result(_sample_raw(), "owner/repo", 3)
    assert not any("truncated" in n for n in res.notes)


def test_runner_surfaces_truncation_end_to_end():
    config, radius, guard = _make_runner()
    radius.raw = _truncated_raw(dropped_tests=True)
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.run(repo="owner/repo", pr_number=3)
    assert res.fallback_used is True
    assert any("truncated" in n for n in res.notes)


def _static_only_raw():
    return {
        "project_id": 7,
        "full_name": "owner/repo",
        "pr_number": 3,
        "commit_sha": "abc123",
        "pr_files_analyzed": 1,
        "symbols_selected": 1,
        "tests_selected": 1,
        "total_tests_reused": 1,
        "runtime_tests_reused": 0,
        "static_tests_reused": 1,
        "results": [
            {
                "symbol_name": "prepare_ttl",
                "symbol_file": "src/key_value/aio/_utils/time_to_live.py",
                "priority_risk_index": 5500.0,
                "existing_tests": [
                    {
                        "test_name": "test_prepare_ttl",
                        "test_file": "tests/test_ttl.py",
                        "confidence": "medium",
                        "reason": "static_import:tests/test_ttl.py->src/key_value/aio/_utils/time_to_live.py",
                    }
                ],
            }
        ],
    }


def test_statically_reached_test_selected_with_medium_confidence():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.to_result(_static_only_raw(), "owner/repo", 3)
    # Not fallback: the statically-reached test is a valid selection.
    assert res.fallback_used is False
    assert res.confidence == "medium"
    assert len(res.tests) == 1
    assert res.tests[0]["confidence"] == "medium"
    assert res.tests[0]["reason"].startswith("static_import:")
    assert any("static reachability" in n for n in res.notes)


def test_runtime_test_keeps_high_confidence():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.to_result(_sample_raw(), "owner/repo", 3)
    assert res.confidence == "high"
    assert res.tests[0]["confidence"] == "high"
    assert not any("static reachability" in n for n in res.notes)


def test_analyze_result_round_trips_fusion_counts():
    from tia_agent.tools.models import AnalyzeResult

    parsed = AnalyzeResult.from_raw(_static_only_raw())
    assert parsed.static_tests_reused == 1
    assert parsed.runtime_tests_reused == 0
    out = parsed.to_raw()
    assert out["static_tests_reused"] == 1
    assert out["results"][0]["existing_tests"][0]["confidence"] == "medium"


# ---------------------------------------------------------------------------
# V2: every selected test carries a reason path + confidence (no opaque
# selections). The reason is ``changed_symbol:<name>@<file> -> <source(s)> ->
# <test>``.
# ---------------------------------------------------------------------------

def _v2_raw():
    return {
        "project_id": 7,
        "full_name": "owner/repo",
        "pr_number": 3,
        "commit_sha": "abc123",
        "pr_files_analyzed": 2,
        "pr_files": ["src/cart.ts"],
        "symbols_selected": 1,
        "tests_selected": 1,
        "total_tests_reused": 1,
        "results": [
            {
                "symbol_name": "applyDiscount",
                "symbol_file": "src/cart.ts",
                "existing_tests": [
                    {
                        "test_name": "tests/cart.spec.ts::test_apply_discount",
                        "test_file": "tests/cart.spec.ts",
                        "confidence": "high",
                        "reason": (
                            "changed_symbol:applyDiscount@src/cart.ts -> "
                            "runtime_evidence -> tests/cart.spec.ts::test_apply_discount"
                        ),
                    }
                ],
            }
        ],
    }


def test_v2_backend_reason_path_round_trips():
    from tia_agent.output.schema import validate_output

    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.to_result(_v2_raw(), "owner/repo", 3)
    assert len(res.tests) == 1
    t = res.tests[0]
    assert t["confidence"] == "high"
    assert t["reason"] == (
        "changed_symbol:applyDiscount@src/cart.ts -> runtime_evidence "
        "-> tests/cart.spec.ts::test_apply_discount"
    )
    # No opaque selections: reason + confidence on every selected test.
    assert all(tt.get("reason") and tt.get("confidence") for tt in res.tests)
    assert validate_output(res.to_dict()) == []


def test_v2_reason_synthesized_when_backend_omits_it():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    raw = _v2_raw()
    entry = raw["results"][0]["existing_tests"][0]
    entry.pop("reason")
    entry.pop("confidence")
    res = runner.to_result(raw, "owner/repo", 3)
    assert res.tests[0]["reason"] == (
        "changed_symbol:applyDiscount@src/cart.ts -> selected "
        "-> tests/cart.spec.ts::test_apply_discount"
    )
    assert res.tests[0]["confidence"] == "high"


def test_v2_reason_synthesized_when_symbol_file_blank():
    # The AnalyzeResult round-trip writes an absent symbol_file as "" — the
    # synthesized path must not end up with an empty "@ " leg.
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    raw = _v2_raw()
    raw["results"][0]["symbol_file"] = ""
    raw["results"][0]["existing_tests"][0].pop("reason")
    res = runner.to_result(raw, "owner/repo", 3)
    assert res.tests[0]["reason"].startswith("changed_symbol:applyDiscount@?")
    assert "-> selected ->" in res.tests[0]["reason"]


def test_v2_dedupe_keeps_strongest_confidence_and_its_reason():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    test = {"test_name": "tests/t.py::test_a", "test_file": "tests/t.py"}
    raw = {
        "pr_files_analyzed": 2,
        "pr_files": ["src/a.py", "src/b.py"],
        "symbols_selected": 2,
        "tests_selected": 2,
        "total_tests_reused": 2,
        "results": [
            {  # weaker occurrence: static-only, medium
                "symbol_name": "sym_a",
                "symbol_file": "src/a.py",
                "existing_tests": [
                    dict(
                        test,
                        confidence="medium",
                        reason="changed_symbol:sym_a@src/a.py -> static_import -> tests/t.py::test_a",
                    )
                ],
            },
            {  # stronger occurrence: runtime, high
                "symbol_name": "sym_b",
                "symbol_file": "src/b.py",
                "existing_tests": [
                    dict(
                        test,
                        confidence="high",
                        reason="changed_symbol:sym_b@src/b.py -> runtime_evidence -> tests/t.py::test_a",
                    )
                ],
            },
        ],
    }
    res = runner.to_result(raw, "owner/repo", 3)
    assert len(res.tests) == 1
    assert res.tests[0]["confidence"] == "high"
    # The reason path of the strongest occurrence wins.
    assert res.tests[0]["reason"].startswith("changed_symbol:sym_b@src/b.py")

    # Reverse order: high arrives first and is not downgraded.
    raw["results"].reverse()
    res2 = runner.to_result(raw, "owner/repo", 3)
    assert res2.tests[0]["confidence"] == "high"
    assert res2.tests[0]["reason"].startswith("changed_symbol:sym_b@src/b.py")


def _stale_raw(analyzed="b" * 40, built="a" * 40, stale=True, unversioned=False):
    raw = _sample_raw()
    raw.update(
        {
            "stale_evidence": stale,
            "stale_evidence_reason": (
                f"evidence built at {built[:12]} but analyzing {analyzed[:12]}"
                if stale else None
            ),
            "evidence_built_at_sha": built if not unversioned else None,
            "evidence_unversioned": unversioned,
        }
    )
    return raw


def test_stale_evidence_forces_fallback():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.to_result(_stale_raw(), "owner/repo", 3)
    assert res.fallback_used is True
    assert res.fallback_reason and "different commit" in res.fallback_reason
    assert res.confidence == "low"
    assert any("stale" in n or "built at" in n for n in res.notes)


def test_stale_evidence_note_carries_backend_reason():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.to_result(_stale_raw(), "owner/repo", 3)
    assert any("a" * 12 in n for n in res.notes)


def test_stale_evidence_round_trips_commit():
    from tia_agent.tools.models import AnalyzeResult

    raw = _stale_raw()
    parsed = AnalyzeResult.from_raw(raw)
    assert parsed.stale_evidence is True
    assert parsed.evidence_built_at_sha == "a" * 40
    out = parsed.to_raw()
    assert out["stale_evidence"] is True
    assert out["evidence_built_at_sha"] == "a" * 40


def test_matching_commit_is_fresh_and_pins_evidence():
    sha = "c" * 40
    raw = _sample_raw()
    raw.update(
        {
            "stale_evidence": False,
            "stale_evidence_reason": None,
            "evidence_built_at_sha": sha,
            "evidence_unversioned": False,
        }
    )
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.to_result(raw, "owner/repo", 3)
    assert res.fallback_used is False
    assert res.evidence_built_at_sha == sha
    assert not any("different commit" in n for n in res.notes)


def test_unversioned_evidence_warns_without_fallback():
    config, radius, guard = _make_runner()
    runner = AnalyzeRunner(config, guard, radius)
    res = runner.to_result(_stale_raw(stale=False, unversioned=True), "owner/repo", 3)
    assert res.fallback_used is False
    assert res.confidence == "high"
    assert any("no recorded build commit" in n for n in res.notes)

