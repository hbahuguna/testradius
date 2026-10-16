# Story 11.8: Coverage Completeness for TS/Playwright

**Status**: Backlog
**Epic**: 11 — Instrumentation Hardening
**Effort**: 1d
**Priority**: P2
**Depends on**: 11.6

---

## Summary

TypeScript and Playwright runs must report real coverage-completeness metrics, so the coverage endpoint does not raise a false warning.

## Current behaviour (the problem)

- Only the Python path emits a `coverage_completeness` event (`pipeline_worker.py:516`); `_run_typescript_pipeline` and `_run_playwright_pipeline` do not.
- `_record_instrumentation_run` (`main.py:246`) therefore stores all-zero metrics, and `_instrumentation_coverage_payload` (`main.py:220`) computes `low_coverage = coverage_pct < 95.0` (`main.py:67`) — a spurious warning for every TS/Playwright project.

## Acceptance criteria

- [ ] TypeScript and Playwright runs emit `coverage_completeness` with `test_files_expected`, `test_files_collectable`, `test_files_scheduled`, `test_files_instrumented`, `coverage_pct`, `missing_test_files`.
- [ ] `GET /projects/{id}/instrumentation/coverage` returns real numbers for those languages.
- [ ] `low_coverage` / `warning` appear only when the real percentage is below 95.
- [ ] The zero-metric case is distinguishable from a genuine 0% run (e.g. a `not_reported` flag).

## Implementation notes

- Compute the metrics in `typescript_pipeline.run_typescript_pipeline` (`:188`) and `playwright_pipeline.run_playwright_pipeline` (`:211`) using the same shape as `per_test_analyzer._coverage_completeness` (`:637`).
- Yield the `coverage_completeness` event from `_run_typescript_pipeline` / `_run_playwright_pipeline` so `main.py` captures it (`main.py:1638`).
- Populate `missing_test_files` (tie-in: 11.9 adds reasons).

## Tests (TDD — write first)

- Extend `services/core/tests/test_instrumentation_coverage_api.py` — a TS run records non-zero metrics and no warning at 100%.
- Assert a genuine low-coverage TS run still warns.

## Verification

```bash
pytest services/core/tests/test_instrumentation_coverage_api.py -v
```
