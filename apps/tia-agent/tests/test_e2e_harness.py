"""Unit tests for the E7 live E2E harness's pure helpers.

The live three-repo run needs a real backend + license server, so it lives in
``scripts/e2e_three_repos.py``. These tests cover the backend-independent logic:
deriving changed files / expected tests from evidence, and judging a result.
"""

from __future__ import annotations

from scripts.e2e_three_repos import RepoSpec, _derive_changed_files, check_result
from tia_agent.tools.models import MappingEntry


class _FakeRadius:
    def __init__(self, mappings):
        self._mappings = mappings

    def list_test_mappings(self, project_id, limit=1000):
        return self._mappings


def _entry(product_file, test_file, test_symbol, product_symbol="sym"):
    return MappingEntry.from_raw(
        {
            "product_symbol": product_symbol,
            "product_file": product_file,
            "test_symbol": test_symbol,
            "test_file": test_file,
        }
    )


MAPPINGS = [
    _entry("src/key_value/aio/_utils/wait.py", "tests/test_wait.py", "tests/test_wait.py::t1"),
    _entry("src/key_value/aio/_utils/retry.py", "tests/test_retry.py", "tests/test_retry.py::t2"),
    _entry("/testradius/src/lib/auth.tsx", "artifacts/e2e-tests/tests/navigation.spec.ts", "navigation"),
]


def test_derive_uses_explicit_changed_files():
    spec = RepoSpec("psf/requests", "psf/requests", 7502, instrument={}, changed_files=["src/key_value/aio/_utils/retry.py"])
    changed, expected = _derive_changed_files(_FakeRadius(MAPPINGS), 1, spec)
    assert changed == ["src/key_value/aio/_utils/retry.py"]
    assert expected == {("tests/test_retry.py", "tests/test_retry.py::t2")}


def test_derive_filters_product_files():
    spec = RepoSpec(
        "hbahuguna/Test-Radius",
        "Test-Radius",
        30,
        instrument={},
        file_filter=lambda f: f.startswith("/testradius/"),
    )
    changed, expected = _derive_changed_files(_FakeRadius(MAPPINGS), 1, spec)
    assert changed == ["/testradius/src/lib/auth.tsx"]
    assert expected == {("artifacts/e2e-tests/tests/navigation.spec.ts", "navigation")}


def test_check_result_ok():
    expected = {("t.py", "t.py::x")}
    assert check_result("r", expected, expected, False) == []


def test_check_result_no_tests_fails():
    failures = check_result("r", set(), {("t.py", "t.py::x")}, False)
    assert any("no tests" in f for f in failures)


def test_check_result_fabricated_tests_fail():
    expected = {("t.py", "t.py::x")}
    returned = expected | {("other.py", "other.py::y")}
    failures = check_result("r", returned, expected, False)
    assert any("fabricated" in f for f in failures)


def test_check_result_fallback_fails():
    failures = check_result("r", {("t.py", "t.py::x")}, {("t.py", "t.py::x")}, True, "because")
    assert any("fell back" in f for f in failures)
