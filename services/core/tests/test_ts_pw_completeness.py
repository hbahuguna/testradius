"""Story 11.8 — coverage completeness for the TypeScript/Playwright pipelines.

Only the Python path emitted ``coverage_completeness``, so ``_record_instrumentation_run``
stored all-zero metrics for TS/Playwright projects and ``low_coverage`` fired
spuriously on every one of them.

These tests cover the shared metric shape, the two pipelines' wiring of it, and
the ``not_reported`` flag that separates "never measured" from "measured 0%".
"""
import os

from testsquad_core.instrumentation.completeness import (
    compute_completeness, normalize_test_file,
)
from testsquad_core.persistence.coverage_payload import (
    LOW_COVERAGE_PCT, build_coverage_payload, is_low_coverage,
)


def _files(root, count, prefix="src", suffix=".test.ts"):
    return [os.path.join(root, prefix, f"t{i}{suffix}") for i in range(1, count + 1)]


class TestNormalizeTestFile:
    def test_strips_leading_dot_slash(self):
        assert normalize_test_file("./src/a.test.ts", "/repo") == "src/a.test.ts"

    def test_makes_absolute_paths_repo_relative(self):
        assert normalize_test_file("/repo/src/a.test.ts", "/repo") == "src/a.test.ts"

    def test_leaves_paths_outside_the_testbed_alone(self):
        assert normalize_test_file("/elsewhere/a.test.ts", "/repo") == "/elsewhere/a.test.ts"

    def test_empty_input_is_empty(self):
        assert normalize_test_file("", "/repo") == ""

    def test_plugin_keys_carry_a_test_name_after_the_file(self):
        # The Vitest plugin keys coverage by "<file> > <test name>".
        assert normalize_test_file("src/a.test.ts > sorts ascending", "/repo") == "src/a.test.ts"

    def test_backslashes_are_normalized(self):
        assert normalize_test_file("src\\a.test.ts", "/repo") == "src/a.test.ts"


class TestComputeCompleteness:
    def test_full_run_at_100_percent(self):
        root = "/repo"
        discovered = _files(root, 12)

        metrics = compute_completeness(
            discovered=discovered, scheduled=discovered,
            covered=[os.path.relpath(f, root) for f in discovered],
            testbed_path=root,
        )

        assert metrics["test_files_expected"] == 12
        assert metrics["test_files_collectable"] == 12
        assert metrics["test_files_scheduled"] == 12
        assert metrics["test_files_total"] == 12
        assert metrics["test_files_instrumented"] == 12
        assert metrics["coverage_pct"] == 100.0
        assert metrics["missing_test_files"] == []
        assert metrics["missing_count"] == 0

    def test_capped_run_is_measured_against_the_whole_suite(self):
        """The 11.6 cap must show up as a shortfall, not as a silent 100%."""
        root = "/repo"
        discovered = _files(root, 12)
        scheduled = discovered[:10]

        metrics = compute_completeness(
            discovered=discovered, scheduled=scheduled,
            covered=[os.path.relpath(f, root) for f in scheduled],
            testbed_path=root,
        )

        assert metrics["test_files_scheduled"] == 10
        assert metrics["test_files_total"] == 12
        assert metrics["test_files_instrumented"] == 10
        assert metrics["coverage_pct"] == 83.3
        assert metrics["missing_count"] == 2
        assert metrics["missing_test_files"] == ["src/t11.test.ts", "src/t12.test.ts"]

    def test_scheduled_but_no_coverage_counts_as_missing(self):
        root = "/repo"
        discovered = _files(root, 3)

        metrics = compute_completeness(
            discovered=discovered, scheduled=discovered[:2],
            covered=[os.path.relpath(discovered[0], root)],
            testbed_path=root,
        )

        assert metrics["test_files_scheduled"] == 2
        assert metrics["test_files_instrumented"] == 1
        assert metrics["coverage_pct"] == 33.3
        assert metrics["missing_count"] == 2

    def test_playwright_keys_are_relative_to_the_test_dir(self):
        """Playwright coverage keys are relative to ``test_dir``, not the repo."""
        root = "/repo"
        discovered = [os.path.join(root, "e2e", n) for n in ("a.spec.ts", "b.spec.ts")]

        metrics = compute_completeness(
            discovered=discovered, scheduled=discovered,
            covered=["a.spec.ts", "b.spec.ts"],
            covered_prefix="e2e",
            testbed_path=root,
        )

        assert metrics["coverage_pct"] == 100.0
        assert metrics["test_files_instrumented"] == 2

    def test_plugin_keys_with_test_names_are_matched_by_file(self):
        root = "/repo"
        discovered = _files(root, 2)

        metrics = compute_completeness(
            discovered=discovered, scheduled=discovered,
            covered=[
                "src/t1.test.ts > sorts ascending",
                "src/t2.test.ts > handles empty",
            ],
            testbed_path=root,
        )

        assert metrics["coverage_pct"] == 100.0

    def test_duplicate_covered_entries_are_deduped(self):
        root = "/repo"
        discovered = _files(root, 2)

        metrics = compute_completeness(
            discovered=discovered, scheduled=discovered,
            covered=["src/t1.test.ts", "src/t1.test.ts", "./src/t1.test.ts"],
            testbed_path=root,
        )

        assert metrics["test_files_instrumented"] == 1

    def test_missing_list_is_capped_at_fifty(self):
        root = "/repo"
        discovered = _files(root, 60)

        metrics = compute_completeness(
            discovered=discovered, scheduled=[], covered=[], testbed_path=root,
        )

        assert metrics["missing_count"] == 60
        assert len(metrics["missing_test_files"]) == 50

    def test_empty_suite_is_zero_not_a_division_error(self):
        metrics = compute_completeness(
            discovered=[], scheduled=[], covered=[], testbed_path="/repo",
        )

        assert metrics["coverage_pct"] == 0.0
        assert metrics["missing_count"] == 0

    def test_falls_back_to_scheduled_when_nothing_was_discovered(self):
        root = "/repo"
        scheduled = _files(root, 4)

        metrics = compute_completeness(
            discovered=[], scheduled=scheduled,
            covered=[os.path.relpath(f, root) for f in scheduled],
            testbed_path=root,
        )

        assert metrics["test_files_total"] == 4
        assert metrics["coverage_pct"] == 100.0

    def test_carried_forward_files_count_as_covered(self):
        root = "/repo"
        discovered = _files(root, 4)

        metrics = compute_completeness(
            discovered=discovered, scheduled=discovered[:2],
            covered=[os.path.relpath(discovered[0], root)],
            carried_forward=[discovered[1]],
            testbed_path=root,
        )

        assert metrics["test_files_carried_forward"] == 1
        assert metrics["test_files_instrumented"] == 2
        assert metrics["coverage_pct"] == 50.0


class TestCoveragePayload:
    def _row(self, **over):
        row = {
            "project_id": 8, "run_id": 1, "status": "COMPLETED", "edges": 72,
            "test_files_expected": 12, "test_files_collectable": 12,
            "test_files_scheduled": 12, "test_files_instrumented": 12,
            "coverage_pct": 100.0, "missing_count": 0, "missing_test_files": [],
            "details": {}, "created_at": None,
        }
        row.update(over)
        return row

    def test_full_coverage_has_no_warning(self):
        payload = build_coverage_payload(self._row())

        assert payload["coverage_pct"] == 100.0
        assert payload["low_coverage"] is False
        assert "warning" not in payload
        assert payload["not_reported"] is False

    def test_genuine_low_coverage_still_warns(self):
        payload = build_coverage_payload(
            self._row(test_files_scheduled=12, test_files_instrumented=10,
                      coverage_pct=83.3, missing_count=2,
                      missing_test_files=["src/t11.test.ts", "src/t12.test.ts"]),
        )

        assert payload["low_coverage"] is True
        assert "83.3" in payload["warning"]
        assert payload["not_reported"] is False

    def test_exactly_at_threshold_is_not_low(self):
        payload = build_coverage_payload(self._row(coverage_pct=LOW_COVERAGE_PCT))

        assert payload["low_coverage"] is False

    def test_all_zero_metrics_are_marked_not_reported(self):
        """A TS/Playwright run before 11.8 stored zeros: that is not a 0% run."""
        payload = build_coverage_payload(
            self._row(test_files_expected=0, test_files_collectable=0,
                      test_files_scheduled=0, test_files_instrumented=0,
                      coverage_pct=0.0, missing_count=0),
        )

        assert payload["not_reported"] is True
        assert payload["low_coverage"] is False
        assert "warning" not in payload

    def test_genuine_zero_percent_run_is_still_reported(self):
        payload = build_coverage_payload(
            self._row(test_files_expected=12, test_files_scheduled=12,
                      test_files_instrumented=0, coverage_pct=0.0, missing_count=12,
                      missing_test_files=["src/t1.test.ts"]),
        )

        assert payload["not_reported"] is False
        assert payload["low_coverage"] is True

    def test_explicit_details_flag_wins_over_the_heuristic(self):
        payload = build_coverage_payload(
            self._row(details={"not_reported": False}, coverage_pct=50.0,
                      missing_count=1),
        )

        assert payload["not_reported"] is False
        assert payload["low_coverage"] is True

    def test_explicit_not_reported_flag_suppresses_the_warning(self):
        payload = build_coverage_payload(
            self._row(details={"not_reported": True}, coverage_pct=0.0),
        )

        assert payload["not_reported"] is True
        assert payload["low_coverage"] is False

    def test_missing_test_files_come_from_details(self):
        payload = build_coverage_payload(
            self._row(details={"missing_test_files": ["src/a.test.ts"]}),
        )

        assert payload["missing_test_files"] == ["src/a.test.ts"]

    def test_is_low_coverage_rejects_unreported_runs(self):
        assert is_low_coverage(0.0, not_reported=True) is False
        assert is_low_coverage(0.0, not_reported=False) is True
        assert is_low_coverage(100.0, not_reported=False) is False
