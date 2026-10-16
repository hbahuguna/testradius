# Story 11.6: TS/Playwright Parity — Sharding, Lift Cap, Wire Vitest Plugin

**Status**: Backlog
**Epic**: 11 — Instrumentation Hardening
**Effort**: 3d
**Priority**: P1
**Depends on**: 11.3

---

## Summary

TypeScript (Vitest) and Playwright instrumentation must cover the whole suite, run in parallel, and (for Vitest) collect per-test coverage — matching the Python path.

## Current behaviour (the problem)

- Hardcoded `max_files: int = 10`: `typescript_pipeline.py:149,191` and `playwright_pipeline.py:178,214`. Only a fraction of the suite is instrumented.
- Execution is **sequential**, one process per test file (`for i, tf in enumerate(files_to_run)`), with no sharding — unlike the Python path (`per_test_analyzer.partition_test_files`, `:255`).
- The per-test V8 plugin in `packages/vitest-plugin/` (bin `testsquad-cov`) exists and is declared as `TypeScriptTestbedConfig.vitest_plugin` (`typescript_pipeline.py:21`) but is **never referenced**. The pipeline spawns one Vitest process per file instead.

## Acceptance criteria

- [ ] The 10-file cap is removed or made a configurable maximum (default: no cap).
- [ ] TypeScript/Playwright runs are sharded and parallelized across workers (bounded by CPU / an env var).
- [ ] Vitest coverage is collected **per test**, not just per file, using the Vitest plugin — or the unused plugin is removed and the per-file approach is documented as intentional.
- [ ] Full-suite instrumentation of a TS testbed produces evidence for all tests (verified against the collected count).
- [ ] Existing TS testbed runs still pass; the workspace-framework detection path (`pipeline_worker._detect_typescript_config`, `:127`) is preserved.

## Implementation notes

- Reuse the sharding helper pattern from `per_test_analyzer.run_tests_with_coverage` for the TS/Playwright per-file loop.
- Wire `packages/vitest-plugin` into the run: build/invoke `testsquad-cov` (or its programmatic API from `src/index.ts`) and parse the emitted Istanbul JSON through `CoverageParser.parse_istanbul` (`coverage_parser.py:25`). This replaces per-file process spawning for Vitest.
- For Playwright, keep the Istanbul merge from `.coverage-raw` (`run_single_playwright_file`, `playwright_pipeline.py:112`) but shard the file list.
- Make the cap env-configurable (`TIA_TS_MAX_FILES`, default 0 = none), mirroring `TIA_INSTRUMENT_MAX_TEST_FILES`.

## Tests (TDD — write first)

- Extend `packages/vitest-plugin` tests (or add one) — per-test coverage output maps to multiple test symbols in one file.
- New: `services/core/tests/test_typescript_pipeline_parity.py` — no cap by default; N files produce N scheduled entries.
- Assert sharding splits the file list across workers.

## Verification

```bash
npm --workspace @testsquad/vitest-plugin run build
pytest services/core/tests/test_typescript_pipeline_parity.py -v
```
