# Story 11.8: Coverage Completeness for TS/Playwright

**Status**: Done
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

- [x] TypeScript and Playwright runs emit `coverage_completeness` with `test_files_expected`, `test_files_collectable`, `test_files_scheduled`, `test_files_instrumented`, `coverage_pct`, `missing_test_files`.
- [x] `GET /projects/{id}/instrumentation/coverage` returns real numbers for those languages.
- [x] `low_coverage` / `warning` appear only when the real percentage is below 95.
- [x] The zero-metric case is distinguishable from a genuine 0% run (e.g. a `not_reported` flag).

## Implementation notes

- Compute the metrics in `typescript_pipeline.run_typescript_pipeline` (`:188`) and `playwright_pipeline.run_playwright_pipeline` (`:211`) using the same shape as `per_test_analyzer._coverage_completeness` (`:637`).
- Yield the `coverage_completeness` event from `_run_typescript_pipeline` / `_run_playwright_pipeline` so `main.py` captures it (`main.py:1638`).
- Populate `missing_test_files` (tie-in: 11.9 adds reasons).

## Tests (TDD — write first)

- Extend `services/core/tests/test_instrumentation_coverage_api.py` — a TS run records non-zero metrics and no warning at 100%.
- Assert a genuine low-coverage TS run still warns.

## Verification

```bash
pytest services/core/tests/test_ts_pw_completeness.py -v
pytest services/core/tests/test_typescript_pipeline_parity.py -v
pytest services/core/tests/test_instrumentation_coverage_api.py -v   # needs PyGithub
```

---

## Done — implementation notes

### The shape has one home now

`per_test_analyzer._coverage_completeness` produced the Python metrics inline. Rather
than copy it, the metric shape moved to a new stdlib-only module,
`instrumentation/completeness.py`, whose `compute_completeness()` is now used by
the TypeScript and Playwright paths. The Python path keeps its own function (it
also resolves pytest nodeids and a collectability probe), but every field it
emits has the same meaning as here:

| Field | Meaning |
| --- | --- |
| `test_files_expected` / `test_files_collectable` | discovered; for TS/Playwright everything found is collectable, so both equal the discovered count |
| `test_files_scheduled` | executed this run (a cap or a Story 11.5 narrowing may make this smaller) |
| `test_files_total` | the denominator — the **full discovered suite**, never the narrowed subset |
| `test_files_instrumented` | files that produced evidence (carried-forward counts as covered) |
| `coverage_pct` | `instrumented / total` |
| `missing_test_files` / `missing_count` | the exact shortfall (list capped at 50) |

The denominator choice is the point: a capped run must report the truth instead
of a flattering 100% (verified live — see below).

### Wiring

```
typescript_pipeline.run_vitest_with_coverage   →  _vitest_completeness(...)
playwright_pipeline.run_playwright_coverage    →  _playwright_completeness(...)
run_typescript_pipeline / run_playwright_pipeline   →  result["coverage_completeness"]
_run_typescript_pipeline / _run_playwright_pipeline →  yield {"event": "coverage_completeness", ...}
main.py run_instrumentation_worker                  →  captures it, _record_instrumentation_run persists it
GET .../instrumentation/coverage                    →  build_coverage_payload(run)
```

Playwright keys its coverage relative to `test_dir`, so `_playwright_completeness`
re-attaches that prefix (`covered_prefix=config.test_dir`) before normalizing to
repo-relative paths — otherwise the keys would never match discovery and coverage
would silently read as 0%.

### `not_reported` (AC4)

Before this story a TS/Playwright row was all zeros with no way to tell it apart
from a genuine 0% run, so every such project warned. `_record_instrumentation_run`
now writes `details["not_reported"]`, and the payload exposes `not_reported` and
only warns when it is false. Rows written before this story carry no flag; the
payload falls back to a heuristic — a pipeline that reported has at least one of
an expected count, a scheduled count or a missing count, whereas an unreported
row is all zeros.

### Refactor

`_instrumentation_coverage_payload` moved to
`persistence/coverage_payload.py` (`build_coverage_payload`, `is_low_coverage`,
`was_coverage_reported`). `main.py` delegates to it. Two reasons: `main.py`
imports FastAPI and PyGithub, so the old test only ran in an environment that
has both; and the threshold now has exactly one definition.

## Tests

`services/core/tests/test_ts_pw_completeness.py` (new, 25 tests) — pure logic, no
FastAPI/PyGithub needed:

- `TestNormalizeTestFile` (6) — `./` prefixes, absolute→repo-relative, paths
  outside the testbed, the plugin's `"<file> > <test name>"` keys, backslashes.
- `TestComputeCompleteness` (9) — full run; a capped run measured against the
  whole suite (83.3%); scheduled-but-no-coverage; Playwright's `test_dir` keys;
  plugin keys; dedup; the 50-entry cap; the empty suite; fallback to scheduled
  when discovery is empty; carried-forward counting as covered.
- `TestCoveragePayload` (10) — high coverage, genuine low coverage (with the
  warning text), the exact threshold, all-zeros→`not_reported`, a genuine 0% run
  still reported, the explicit flag winning over the heuristic, and
  `is_low_coverage`.

`services/core/tests/test_typescript_pipeline_parity.py` (+6 tests) — the Vitest
cap reports 30%, a full run reports 100%, Playwright reports 33.3% with
`test_dir`-relative keys, and both workers emit the `coverage_completeness` event.

`services/core/tests/test_instrumentation_coverage_api.py` (+2 tests, runs in CI
where PyGithub exists) — an unreported run stores `not_reported` and does not
warn; a reported run is marked reported.

## Verification — manual gate (live backend, 2026-10-16)

Executed against the running `core-ml` container using the synthetic TS testbed
(`gate-ts`, 12 test files, project id 8).

| Check | Result |
| --- | --- |
| TS emits the event | `coverage_completeness: {expected: 12, scheduled: 12, total: 12, instrumented: 12, coverage_pct: 100.0, missing_count: 0}` |
| Endpoint returns real numbers | `coverage_pct: 100.0`, `not_reported: false`, `low_coverage: false` |
| Genuine shortfall is not flattered | with `TIA_TS_MAX_FILES=6`: `scheduled: 6 of total: 12`, `coverage_pct: 50.0`, `missing_test_files` names the six, endpoint `low_coverage: true` + `warning: "coverage 50.0% is below 95%; 6 test file(s) produced no evidence"` |
| Unreported run does not warn (AC4) | a failing run (bad repo) stored `coverage_pct: 0.0` with `not_reported: true`, `low_coverage: false` |
| Python path unaffected | project 10 endpoint still reports `6/6 100%`, `not_reported: false` |

The cap override was reverted after the check (`docker-compose.yml` is clean) and
project 8 was restored to 12/12.

## Deviations from the story's implementation notes

1. **The metrics are computed in `run_vitest_with_coverage` /
   `run_playwright_coverage`, not in `run_typescript_pipeline` /
   `run_playwright_pipeline`.** Those inner functions are the only place that has
   both the discovered list and the scheduled list in hand, so computing there
   avoids threading two lists back out. The outer functions pass the result
   through unchanged.
2. **A shared `completeness.py` module was added** rather than re-deriving the
   shape at each call site, so the field names and the denominator rule have one
   definition.
3. **The payload moved out of `main.py`** (see Refactor) — a testability-driven
   change, not called for by the story.
4. **`test_instrumentation_coverage_api.py` cannot run on the dev host** (it
   imports `main.py`, which imports PyGithub, whose wheel needs Rust here). The
   new tests there run in CI; the logic they exercise is also covered by the
   pure `test_ts_pw_completeness.py`.

## Limitations / follow-ups

- `test_files_expected` and `test_files_collectable` are identical for
  TypeScript/Playwright: discovery is filename-based (a glob), with no separate
  collection probe, so there is no equivalent of pytest's "collected vs
  expected" gap. If a TS test file is discovered but cannot be collected, it
  currently shows up as scheduled-but-uncovered rather than uncollectable.
- `missing_test_files` carries paths only; Story 11.9 adds per-file reasons.
- The Playwright pipeline still cannot run its browser shards in parallel
  (Story 11.6 deviation), which does not affect completeness accounting.

