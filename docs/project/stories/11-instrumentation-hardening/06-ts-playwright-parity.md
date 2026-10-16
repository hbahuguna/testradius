# Story 11.6: TS/Playwright Parity — Sharding, Lift Cap, Wire Vitest Plugin

**Status**: Manual Test
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

- [x] The 10-file cap is removed or made a configurable maximum (default: no cap).
- [x] TypeScript/Playwright file lists are partitioned into shards bounded by an env var / CPU.
      **Refined from the original AC** after discovering Playwright's coverage output is a
      single shared directory — see *Deviations* below.
- [x] TypeScript/Vitest runs are **sharded and parallelized** across worker threads (bounded by
      `TIA_TS_SHARDS`, default ~CPU capped at 4).
- [x] Vitest coverage is collected per test using the Vitest plugin (`testsquad-cov`), wired as
      the preferred path with the per-file spawn loop retained as a fallback when the plugin
      is not installed in the testbed.
- [ ] Full-suite instrumentation of a TS testbed produces evidence for all tests (verified
      against the collected count) — **pending manual gate** (§G of the test plan).
- [x] Existing TS testbed runs still pass; the workspace-framework detection path
      (`pipeline_worker._detect_typescript_config`, `:127`) is preserved.

## Implementation notes

- Reuse the sharding helper pattern from `per_test_analyzer.run_tests_with_coverage` for the TS/Playwright per-file loop.
- Wire `packages/vitest-plugin` into the run: build/invoke `testsquad-cov` (or its programmatic API from `src/index.ts`) and parse the emitted Istanbul JSON through `CoverageParser.parse_istanbul` (`coverage_parser.py:25`). This replaces per-file process spawning for Vitest.
- For Playwright, keep the Istanbul merge from `.coverage-raw` (`run_single_playwright_file`, `playwright_pipeline.py:112`) but shard the file list.
- Make the cap env-configurable (`TIA_TS_MAX_FILES`, default 0 = none), mirroring `TIA_INSTRUMENT_MAX_TEST_FILES`.

### What was built

**Cap removed (AC1)** — `max_files` now defaults to `None` in `run_vitest_with_coverage`,
`run_typescript_pipeline`, `run_playwright_coverage` and `run_playwright_pipeline`; the cap is
resolved as *explicit argument → env var → no cap*:

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `TIA_TS_MAX_FILES` | `0` (none) | Cap on Vitest test files |
| `TIA_TS_SHARDS` | ~CPU, ≤4 | Vitest worker threads |
| `TIA_PW_MAX_FILES` | `0` (none) | Cap on Playwright test files |
| `TIA_PW_SHARDS` | `1` | Playwright shard count (executed serially) |
| `TIA_TS_PLUGIN` | `1` (on) | `0` disables the plugin path |
| `TIA_TS_PLUGIN_CLI` | — | Override the plugin CLI path (tests) |

**Sharding (AC2/AC3)** — shared helpers `_shard_files` / `_pw_shard_files` round-robin partition
the file list; `_apply_file_cap` / `_pw_apply_file_cap` resolve the cap. TypeScript runs each
shard in a `ThreadPoolExecutor` (each file writes coverage into a **unique**
`cov_dir/<basename>` dir, so workers never touch each other's output). Both pipelines now
return `shards` and `shard_assignments` so callers/tests can observe the distribution.

**Vitest plugin wired (AC3)** — `run_vitest_plugin()` locates
`node_modules/@testsquad/vitest-plugin/dist/cli.js` inside the testbed and runs
`node <cli> run <root> <testDir> <covDir> --max=N`. The plugin's emitted JSON has exactly the
`{test_file: {source_file: [lines]}}` shape the pipeline already consumes, so it drops in for
the per-file loop. If the CLI is absent or fails, the code falls back to the per-file spawn
loop — so nothing breaks for testbeds that don't install the plugin. The result carries an
`engine` field (`vitest-plugin` or `per-file`).

`packages/vitest-plugin/src/cli.ts` now guards `main()` behind an ESM entry-point check so the
module can be imported by tests without triggering the CLI.

### Tests (TDD — written first)

- `services/core/tests/test_typescript_pipeline_parity.py` (new, 19 tests): no cap by default,
  env cap, explicit cap wins, shard splitting, shard default, Playwright cap + serial
  execution, Istanbul parse parity, plugin wiring (used / falls back / disabled / absent,
  package-name resolution), workspace-detection preserved.
- `packages/vitest-plugin/test/cli.test.mjs` (new, 6 tests): `parseIstanbul` line mapping,
  multi-line statement expansion, de-dup/sorting, `findTestFiles` discovery + `node_modules`
  exclusion. Runs via `npm test` (builds first).

## Done / Verification

```bash
cd packages/vitest-plugin && npm test            # 6 passed
PYTHONPATH="services/core:packages/shared" python3.10 -m pytest \
  services/core/tests/test_typescript_pipeline_parity.py -q   # 19 passed
# full 20-file regression sweep -> 259 passed
```

### Deviations

1. **Playwright executes serially, not in parallel.** The testbed's browser coverage collector
   dumps `window.__coverage__` into one fixed `<test_dir>/.coverage-raw` directory, and
   `run_single_playwright_file` clears that directory before each file and reads it after. Two
   concurrent workers would therefore delete each other's output. The file list is still
   sharded (`TIA_PW_SHARDS`) for bookkeeping and progress, but shards run one after another —
   asserted by `test_execution_is_serial`. Making Playwright parallel needs per-worker coverage
   directories in the *testbed* (outside this repo), so it is deferred rather than faked here.

2. **The plugin's per-file granularity is unchanged.** `testsquad-cov` runs Vitest once per
   test file and aggregates that file's coverage — the same granularity the Python path uses
   (one coverage entry per test file). The story's phrasing "per test" means per test *file*
   throughout this codebase; no finer granularity was introduced.

3. **`packages/vitest-plugin` is wired but optional.** It must be installed into the testbed's
   `node_modules` for the plugin path to activate; otherwise the per-file fallback runs. The
   package is not part of an npm workspace root, so the original plan's
   `npm --workspace @testsquad/vitest-plugin run build` was replaced by `cd packages/vitest-plugin && npm test`.

## Limitations (follow-ups)

- Playwright parallel shards (needs per-worker coverage dirs in the testbed).
- `run_single_vitest_test` derives its output dir from the file *basename*, so two test files
  with the same basename in different directories would collide in parallel runs (pre-existing;
  harmless when basenames are unique).
- The plugin's `runSingleTest` inherits Vitest's default 120s per-file timeout.

## Dependencies

None (builds on 11.3).

## Test plan reference

`docs/project/test-plans/11-instrumentation-hardening.md` §G
