"""E3/T1: TestRadius tool adapters, exercised end-to-end over httpx MockTransport.

These tests drive the real ``RadiusClient`` HTTP layer (routing, query params,
SSE streaming, error handling) and assert the parsed dataclasses.
"""

import json

import httpx
import pytest

from tia_agent.errors import AnalysisError, BackendError
from tia_agent.radius_client import ProjectInfo, RadiusClient
from tia_agent.tools import TestRadiusTools
from tia_agent.tools.models import (
    AnalyzeResult,
    InstrumentationResult,
    MappingEntry,
)


def _client(handler):
    return RadiusClient("http://backend", token="tok", transport=httpx.MockTransport(handler))


def _json(data, status=200):
    return httpx.Response(status, json=data)


_ANALYZE_RAW = {
    "project_id": 7,
    "full_name": "acme/shop",
    "pr_number": 42,
    "commit_sha": "abc123",
    "pr_files_analyzed": 2,
    "symbols_selected": 1,
    "tests_selected": 1,
    "total_tests_reused": 1,
    "total_tests_in_repo": 1308,
    "results": [
        {
            "symbol_name": "applyDiscount",
            "symbol_file": "src/cart.ts",
            "symbol_summary": "applies discount",
            "symbol_type": "function",
            "priority_risk_index": 5100.0,
            "existing_tests": [
                {"test_name": "test_apply_discount", "test_file": "tests/cart.spec.ts"}
            ],
        }
    ],
}


# --------------------------------------------------------------------------- #
# resolve_project
# --------------------------------------------------------------------------- #

def test_resolve_project_matches_full_name():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/projects"
        return _json([{"id": 7, "name": "acme/shop"}])

    with _client(handler) as radius:
        tools = TestRadiusTools(radius)
        assert tools.resolve_project("acme/shop").id == 7
        # a git remote URL resolves to the same project
        assert tools.resolve_project("https://github.com/acme/shop.git").id == 7


def test_resolve_project_suffix_match_prefers_specific():
    def handler(request):
        return _json([{"id": 1, "name": "shop"}, {"id": 7, "name": "acme/shop"}])

    with _client(handler) as radius:
        tools = TestRadiusTools(radius)
        assert tools.resolve_project("acme/shop").id == 7


def test_resolve_project_no_match_raises():
    with _client(lambda r: _json([])) as radius:
        tools = TestRadiusTools(radius)
        with pytest.raises(AnalysisError):
            tools.resolve_project("acme/shop")


def test_register_project_creates_when_missing():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return _json([])
        return _json({"id": 9, "name": "acme/new"})

    with _client(handler) as radius:
        tools = TestRadiusTools(radius)
        project = tools.register_project("acme/new")
    assert project.id == 9
    assert ("POST", "/projects") in calls


# --------------------------------------------------------------------------- #
# check_evidence (derived from test-mapping)
# --------------------------------------------------------------------------- #

def _mapping(product_file="src/cart.ts"):
    return {
        "product_symbol": "applyDiscount",
        "product_file": product_file,
        "test_symbol": "test_apply_discount",
        "test_file": "tests/cart.spec.ts",
        "confidence": 0.9,
        "reasoning": "covers discount",
        "status": "EVIDENCE",
    }


def test_check_evidence_no_mappings():
    def handler(request):
        assert request.url.path == "/projects/7/test-mapping"
        assert request.url.params.get("limit") == "1000"
        return _json([])

    with _client(handler) as radius:
        status = TestRadiusTools(radius).check_evidence(ProjectInfo(id=7, name="acme/shop"))
    assert (status.known, status.fresh, status.mapping_count) == (True, False, 0)
    assert "no test mappings" in status.reason
    assert status.needs_instrumentation is True


def test_check_evidence_fresh_when_mappings_cover_changed_paths():
    with _client(lambda r: _json([_mapping("src/cart.ts")])) as radius:
        tools = TestRadiusTools(radius)
        fresh = tools.check_evidence(ProjectInfo(id=7, name="acme/shop"), ["src/cart.ts"])
        stale = tools.check_evidence(ProjectInfo(id=7, name="acme/shop"), ["src/other.ts"])
    assert fresh.fresh is True and fresh.covered_files == ["src/cart.ts"]
    assert stale.fresh is False and stale.needs_instrumentation is True


def test_check_evidence_fresh_without_paths_when_any_mapping_exists():
    with _client(lambda r: _json([_mapping()])) as radius:
        status = TestRadiusTools(radius).check_evidence(ProjectInfo(id=7, name="acme/shop"))
    assert status.fresh is True and status.mapping_count == 1


def test_check_evidence_propagates_backend_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with _client(handler) as radius:
        with pytest.raises(BackendError):
            TestRadiusTools(radius).check_evidence(ProjectInfo(id=7, name="acme/shop"))


def test_list_test_mappings_parsed():
    with _client(lambda r: _json([_mapping()])) as radius:
        mappings = radius.list_test_mappings(7)
    assert isinstance(mappings[0], MappingEntry)
    assert mappings[0].test_symbol == "test_apply_discount"
    assert mappings[0].confidence == 0.9


# --------------------------------------------------------------------------- #
# analyze_pr
# --------------------------------------------------------------------------- #

def test_analyze_pr_parsed():
    seen = {}

    def handler(request):
        assert request.url.path == "/projects/7/analyze-pr"
        seen.update(json.loads(request.content))
        return _json(_ANALYZE_RAW)

    with _client(handler) as radius:
        result = TestRadiusTools(radius).analyze_pr(
            ProjectInfo(id=7, name="acme/shop"),
            full_name="acme/shop",
            pr_number=42,
            commit_sha="abc123",
            file_paths=["src/cart.ts"],
        )
    assert isinstance(result, AnalyzeResult)
    assert result.total_tests_reused == 1
    assert result.results[0].existing_tests[0].test_name == "test_apply_discount"
    assert result.pr_files == ["src/cart.ts"]
    assert seen["pr_number"] == 42 and seen["file_paths"] == ["src/cart.ts"]


def test_analyze_result_round_trips_suite_size():
    """S3: the backend's canonical suite size must survive from_raw -> to_raw,
    otherwise the pipeline reports `total_tests_in_repo=None`, cannot compute
    the reduction, and the E5 safety cap is silently disabled."""
    parsed = AnalyzeResult.from_raw(_ANALYZE_RAW)
    assert parsed.total_tests_in_repo == 1308
    assert parsed.to_raw()["total_tests_in_repo"] == 1308

    # Older backend / absent field stays None rather than crashing or inventing 0.
    legacy = AnalyzeResult.from_raw({k: v for k, v in _ANALYZE_RAW.items() if k != "total_tests_in_repo"})
    assert legacy.total_tests_in_repo is None
    assert legacy.to_raw()["total_tests_in_repo"] is None

    # Garbage from an upstream is tolerated.
    assert AnalyzeResult.from_raw({**_ANALYZE_RAW, "total_tests_in_repo": "nope"}).total_tests_in_repo is None


# --------------------------------------------------------------------------- #
# run_instrumentation (SSE)
# --------------------------------------------------------------------------- #

def _sse(*events):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def test_run_instrumentation_parses_completed_stream():
    seen = {}

    def handler(request):
        assert request.url.path == "/projects/7/instrumentation/run"
        seen.update(json.loads(request.content))
        return _sse(
            {"event": "progress", "data": "cloning"},
            {"event": "status", "data": {"status": "COMPLETED", "edges": 12}},
        )

    with _client(handler) as radius:
        result = TestRadiusTools(radius).run_instrumentation(
            ProjectInfo(id=7, name="acme/shop"), language="typescript", ensure_feature=False
        )
    assert isinstance(result, InstrumentationResult)
    assert result.ok is True and result.edges == 12
    assert len(result.events) == 2
    assert seen["language"] == "typescript"


def test_run_instrumentation_parses_coverage_completeness():
    coverage = {
        "test_files_expected": 52,
        "test_files_collectable": 31,
        "test_files_scheduled": 31,
        "test_files_instrumented": 30,
        "coverage_pct": 96.8,
        "missing_count": 1,
        "missing_test_files": ["tests/stores/windows_registry/test_windows_registry.py"],
    }
    events = [
        {"event": "coverage_completeness", "data": coverage},
        {"event": "status", "data": {"status": "COMPLETED", "edges": 40242, "coverage": coverage}},
    ]
    with _client(lambda r: _sse(*events)) as radius:
        result = TestRadiusTools(radius).run_instrumentation(
            ProjectInfo(id=7, name="x"), ensure_feature=False
        )
    assert result.coverage == coverage
    assert result.coverage_pct == 96.8
    assert result.coverage_warning is None


def test_run_instrumentation_warns_on_low_coverage():
    coverage = {"coverage_pct": 60.0, "missing_count": 4}
    with _client(lambda r: _sse(
        {"event": "status", "data": {"status": "COMPLETED", "edges": 1, "coverage": coverage}}
    )) as radius:
        result = TestRadiusTools(radius).run_instrumentation(
            ProjectInfo(id=7, name="x"), ensure_feature=False
        )
    assert result.coverage_pct == 60.0
    assert result.coverage_warning is not None
    assert "60.0%" in result.coverage_warning
    assert "4 test file(s)" in result.coverage_warning


def test_run_instrumentation_missing_coverage_has_no_warning():
    with _client(lambda r: _sse(
        {"event": "status", "data": {"status": "COMPLETED", "edges": 1}}
    )) as radius:
        result = TestRadiusTools(radius).run_instrumentation(
            ProjectInfo(id=7, name="x"), ensure_feature=False
        )
    assert result.coverage is None
    assert result.coverage_pct is None
    assert result.coverage_warning is None


def test_run_instrumentation_parses_error_event():
    with _client(lambda r: _sse({"event": "error", "data": "clone failed"})) as radius:
        result = TestRadiusTools(radius).run_instrumentation(
            ProjectInfo(id=7, name="x"), ensure_feature=False
        )
    assert result.status == "ERROR" and result.error == "clone failed"
    assert result.ok is False


def test_run_instrumentation_error_is_terminal_over_trailing_status():
    events = [
        {"event": "error", "data": "clone failed"},
        {"event": "status", "data": {"status": "CANCELLED"}},
    ]
    with _client(lambda r: _sse(*events)) as radius:
        result = TestRadiusTools(radius).run_instrumentation(
            ProjectInfo(id=7, name="x"), ensure_feature=False
        )
    assert result.status == "ERROR" and result.error == "clone failed"


def test_run_instrumentation_parses_cancelled_status():
    with _client(lambda r: _sse({"event": "status", "data": {"status": "CANCELLED"}})) as radius:
        result = TestRadiusTools(radius).run_instrumentation(
            ProjectInfo(id=7, name="x"), ensure_feature=False
        )
    assert result.status == "CANCELLED" and result.ok is False


def test_run_instrumentation_ignores_malformed_sse_lines():
    body = "data: not-json\n\ndata: {\"event\": \"status\", \"data\": {\"status\": \"COMPLETED\"}}\n\n"
    response = httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    with _client(lambda r: response) as radius:
        result = TestRadiusTools(radius).run_instrumentation(
            ProjectInfo(id=7, name="x"), ensure_feature=False
        )
    assert result.ok is True


def test_run_instrumentation_enables_feature_flag():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.content))
        if request.url.path == "/projects/7/features" and request.method == "GET":
            return _json({"instrumentation": False})
        if request.url.path == "/projects/7/features" and request.method == "PUT":
            return _json({"status": "ok"})
        return _sse({"event": "status", "data": {"status": "COMPLETED", "edges": 1}})

    with _client(handler) as radius:
        result = TestRadiusTools(radius).run_instrumentation(ProjectInfo(id=7, name="x"))
    assert result.ok is True
    put = [c for c in calls if c[0] == "PUT"]
    assert put and json.loads(put[0][2]) == {"features": {"instrumentation": True}}


def test_run_instrumentation_skips_feature_call_when_already_enabled():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/features"):
            return _json({"instrumentation": True})
        return _sse({"event": "status", "data": {"status": "COMPLETED"}})

    with _client(handler) as radius:
        TestRadiusTools(radius).run_instrumentation(ProjectInfo(id=7, name="x"))
    assert ("PUT", "/projects/7/features") not in calls


def test_run_instrumentation_backend_error_raises():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    with _client(handler) as radius:
        with pytest.raises(BackendError):
            TestRadiusTools(radius).run_instrumentation(
                ProjectInfo(id=7, name="x"), ensure_feature=False
            )
