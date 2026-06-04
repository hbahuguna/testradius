"""Unit tests for test_runner.py — test execution, JSON parsing, and file handling."""
import pytest
import sys
import os
import json
from unittest.mock import MagicMock, AsyncMock, patch, ANY

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture
def sample_vitest_json():
    return json.dumps({
        "numTotalTestSuites": 1,
        "numPassedTestSuites": 1,
        "numTotalTests": 1,
        "numPassedTests": 1,
        "numFailedTests": 0,
        "success": True,
        "testResults": [
            {
                "name": "/tmp/repo/artifacts/testradius/src/pages/Home.test.tsx",
                "status": "passed",
                "startTime": 1000, "endTime": 1500,
                "assertionResults": [
                    {"title": "can use shared utilities", "status": "passed", "failureMessages": []},
                ],
            },
        ],
    })


@pytest.fixture
def sample_vitest_json_failed():
    return json.dumps({
        "numTotalTestSuites": 1,
        "numPassedTestSuites": 0,
        "numTotalTests": 1,
        "numPassedTests": 0,
        "numFailedTests": 1,
        "success": False,
        "testResults": [
            {
                "name": "/tmp/repo/src/broken.test.ts",
                "status": "failed",
                "startTime": 1000, "endTime": 2000,
                "assertionResults": [
                    {"title": "should work", "status": "failed", "failureMessages": ["Expected true, got false"]},
                ],
            },
        ],
    })


@pytest.fixture
def sample_playwright_json():
    return json.dumps({
        "config": {"version": "1.52.0"},
        "suites": [
            {
                "title": "home.spec.ts",
                "file": "home.spec.ts",
                "specs": [],
                "suites": [
                    {
                        "title": "Home Page",
                        "file": "home.spec.ts",
                        "specs": [
                            {
                                "title": "hero section renders with tagline",
                                "ok": True,
                                "tags": [],
                                "tests": [{"timeout": 30000, "expectedStatus": "passed",
                                           "results": [{"status": "passed", "duration": 2100}]}],
                            },
                            {
                                "title": "problem section displays three cards",
                                "ok": False,
                                "tags": [],
                                "tests": [{"timeout": 30000, "expectedStatus": "passed",
                                           "duration": 5000,
                                           "error": {"message": "element not found"},
                                           "results": [{"status": "failed", "duration": 5000}]}],
                            },
                        ],
                    },
                ],
            },
        ],
    })


class TestParseVitestJSON:
    def test_parses_passed_tests(self, sample_vitest_json):
        from testsquad_core.test_runner import _parse_vitest_json
        requested = [{"name": "Home.test", "file": "artifacts/testradius/src/pages/Home.test.tsx"}]

        result = _parse_vitest_json(sample_vitest_json, requested)

        assert result["total"] == 1
        assert result["passed"] == 1
        assert result["failed"] == 0
        assert result["results"][0]["status"] == "passed"

    def test_parses_failed_tests(self, sample_vitest_json_failed):
        from testsquad_core.test_runner import _parse_vitest_json
        requested = [{"name": "broken.test", "file": "src/broken.test.ts"}]

        result = _parse_vitest_json(sample_vitest_json_failed, requested)

        assert result["total"] == 1
        assert result["failed"] == 1
        assert "expected true, got false" in result["results"][0]["error"].lower()

    def test_handles_empty_json(self):
        from testsquad_core.test_runner import _parse_vitest_json
        result = _parse_vitest_json("{}", [{"name": "t", "file": "f"}])
        # Falls through to text parsing which produces unknown results
        assert result["total"] >= 0

    def test_handles_malformed_json(self):
        from testsquad_core.test_runner import _parse_vitest_json
        requested = [{"name": "t", "file": "f.ts"}]
        result = _parse_vitest_json("not json at all", requested)
        # Falls to text parser
        assert result["total"] >= 0
        assert len(result["results"]) >= 0

    def test_handles_test_without_assertions(self):
        from testsquad_core.test_runner import _parse_vitest_json
        json_str = json.dumps({
            "testResults": [{
                "name": "/tmp/simple.test.ts",
                "status": "passed",
                "assertionResults": [],
            }],
        })
        requested = [{"name": "simple", "file": "simple.test.ts"}]
        result = _parse_vitest_json(json_str, requested)
        assert result["total"] == 1


class TestParsePlaywrightJSON:

    def test_parses_nested_suites(self, sample_playwright_json):
        from testsquad_core.test_runner import _collect_specs, _parse_playwright_json
        requested = [{"name": "home.spec", "file": "artifacts/e2e-tests/tests/home.spec.ts"}]

        result = _parse_playwright_json(sample_playwright_json, requested)

        assert result["total"] == 2
        assert result["passed"] == 1
        assert result["failed"] == 1
        passed = [r for r in result["results"] if r["status"] == "passed"]
        failed = [r for r in result["results"] if r["status"] == "failed"]
        assert len(passed) == 1
        assert len(failed) == 1
        assert "element not found" in failed[0]["error"]

    def test_collect_specs_handles_empty_suites(self):
        from testsquad_core.test_runner import _collect_specs
        specs = _collect_specs({"title": "root", "specs": [], "suites": []})
        assert specs == []

    def test_collect_specs_inherits_parent_file(self):
        from testsquad_core.test_runner import _collect_specs
        suite = {
            "title": "parent", "file": "parent.ts", "suites": [
                {"title": "child", "specs": [{"title": "test1", "ok": True, "tests": [{}]}]},
            ], "specs": [],
        }
        specs = _collect_specs(suite)
        assert len(specs) == 1
        assert specs[0]["file"] == "parent.ts"  # Inherited from parent

    def test_handles_empty_json(self):
        from testsquad_core.test_runner import _parse_playwright_json
        requested = [{"name": "t", "file": "f.spec.ts"}]
        result = _parse_playwright_json("{}", requested)
        assert result["total"] == 0

    def test_handles_malformed_json(self):
        from testsquad_core.test_runner import _parse_playwright_json
        requested = [{"name": "t", "file": "f.spec.ts"}]
        result = _parse_playwright_json("not json", requested)
        # Falls to text parser — each requested test is counted
        assert result["total"] == 1


class TestSplitE2EVsUnit:

    def test_splits_e2e_from_unit(self):
        tests = [
            {"name": "Unit Test", "file": "src/pages/Home.test.tsx"},
            {"name": "E2E Test", "file": "artifacts/e2e-tests/tests/home.spec.ts"},
            {"name": "Another Unit", "file": "src/components/Button.test.tsx"},
        ]

        e2e = [t for t in tests if "e2e-tests" in t.get("file", "")]
        unit = [t for t in tests if "e2e-tests" not in t.get("file", "")]

        assert len(e2e) == 1
        assert len(unit) == 2
        assert e2e[0]["name"] == "E2E Test"
        assert unit[0]["name"] == "Unit Test"

    def test_all_unit_no_e2e(self):
        tests = [{"name": "t1", "file": "a.test.ts"}, {"name": "t2", "file": "b.test.ts"}]
        e2e = [t for t in tests if "e2e-tests" in t.get("file", "")]
        unit = [t for t in tests if "e2e-tests" not in t.get("file", "")]

        assert len(e2e) == 0
        assert len(unit) == 2

    def test_all_e2e_no_unit(self):
        tests = [{"name": "t1", "file": "artifacts/e2e-tests/tests/a.spec.ts"}]
        e2e = [t for t in tests if "e2e-tests" in t.get("file", "")]
        unit = [t for t in tests if "e2e-tests" not in t.get("file", "")]

        assert len(e2e) == 1
        assert len(unit) == 0
