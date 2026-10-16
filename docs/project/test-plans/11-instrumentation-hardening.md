# Epic 11: Instrumentation Hardening — Manual Test Plan

> Manual gate for Epic 11. Automated suites must pass first; then execute the checks below against a locally running instance.

---

## Prerequisites

- [ ] Backend running: `docker compose --profile ml up -d` (or local core service)
- [ ] Neo4j reachable: `docker compose exec -T neo4j cypher-shell -u neo4j -p testsquad_password "..."`
- [ ] `DEMO_MODE=1` on the backend; curl uses `Authorization: Bearer dev-admin-token`
- [ ] Helper:
  ```bash
  RADIUS=http://localhost:8000
  NEO() { docker compose exec -T neo4j cypher-shell -u neo4j -p testsquad_password "$1" 2>/dev/null | tail -n +2; }
  ```
- [ ] A registered project with `{"instrumentation": true, "test_mapping": true}`

---

## A. Regression: Unit Tests

- [ ] `pytest services/core/tests/ -v` — **all pass**
      **Not runnable as written on this machine**: the full directory sweep
      collects network/DB-backed modules that hang past 300s, and several
      files import `github`/PyGithub, which is not installed (the
      `cryptography` wheel needs Rust). Verified instead with the
      instrumentation-focused sweep (16 files, **194 passed**, including
      `test_incremental_instrumentation.py` and
      `test_typescript_pipeline_parity.py`). The 6 `test_pipeline_e2e.py`
      errors are the missing-`github` env limit, not regressions.
- [ ] `pytest services/executor/tests/ -q` — **all pass**
      **Not runnable here**: the executor test modules import `docker`,
      which is not installed in the host environment. No executor code was
      changed by Epic 11.
- [x] `cd packages/vitest-plugin && npm test` — **builds and passes (6 tests)**

---

## B. Story 11.1 — Purge/Version Evidence on Re-Run

- [ ] Instrument at commit X:
  ```bash
  curl -N -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
    -H "Authorization: Bearer dev-admin-token" -H "Content-Type: application/json" \
    -d '{"repo_url":"<repo>","language":"python","run_fresh":true}'
  ```
- [ ] Push a trivial change (new commit Y), instrument again.
- [ ] Exactly one SHA remains:
  ```bash
  NEO "MATCH (ts:TestSymbol {project_id:$PROJECT_ID}) WHERE ts.built_at_sha IS NOT NULL RETURN DISTINCT ts.built_at_sha;"
  ```
- [ ] `analyze-pr` at commit Y reports `stale_evidence=false`.

## C. Story 11.2 — Stable Symbol Identity

- [ ] In a testbed with two classes that both define `get`, instrument.
- [ ] Two distinct nodes exist:
  ```bash
  NEO "MATCH (s:Symbol {project_id:$PROJECT_ID}) WHERE s.name ENDS WITH '.get' RETURN s.name, s.file_path, s.start_line;"
  ```
- [ ] Change only `ClassB.get` → `analyze-pr` does not select `ClassA.get` tests.

## D. Story 11.3 — Unified Attribution

- [ ] Instrument a Python testbed and a TypeScript testbed with an equivalent method.
- [ ] A covered method line produces an edge to the method **only** (no class edge from that line).
- [ ] `analyze-pr` on a Python file uses the Python resolver (no parse errors).

## E. Story 11.4 — Clone/Install Cache

- [ ] Run instrumentation twice with no code change.
- [ ] Second run does not re-clone; `pip install` is skipped (check SSE output / timing).
- [ ] Second run duration is lower than the first.

## F. Story 11.5 — Incremental Instrumentation

Detailed procedure: `docs/runbooks/tia-py-key-value.md` §2f.

**Status: executed 2026-10-16 against a live backend** (core-ml container,
restart required to pick up the bind-mounted source). The build-backed
run used a synthetic installable Python testbed pushed to a bare
`file://` origin, so the anchor could be advanced without writing to a
public repo; project `gate-py-incremental` (id 10), 6 test files over 4
source modules.

- [x] With prior evidence, change one production file and re-run.
- [x] Only tests covering the changed file run (compare scheduled count in SSE:
      `"Incremental run: N of M test files scheduled ... carried forward"`).
      Observed `Incremental run: 2 of 6 test files scheduled, 4 carried
      forward (1 source file(s) changed since ad83cd6b49b7)`; the stream
      emitted mappings for `tests/test_text_a.py` and `tests/test_text_b.py`
      only.
- [x] Coverage completeness still reports against the full-suite denominator
      (`test_files_total` == the full suite; carried-forward files counted as covered).
      Observed `test_files_expected: 2, test_files_scheduled: 2,
      test_files_total: 6, test_files_carried_forward: 4,
      test_files_instrumented: 6, coverage_pct: 100.0` — the denominator
      stayed at the full 6 and the 4 carried files count as instrumented.
- [x] `run_fresh=true` forces a full run (no `incremental` metadata in the stream).
      Observed all 6 scheduled, `carried_forward: 0`, no `Incremental run`
      line.
- [x] The cached checkout advances to the branch tip before the diff (the anchor moves);
      a checkout with tracked local edits is left un-refreshed.
      Observed the cached checkout move to the pushed tip and
      `built_at_sha` advance on every run.
- [x] After the run, exactly one `built_at_sha` remains project-wide (carried-forward
      edges were re-stamped — same invariant as §B).
      `MATCH (t:TestSymbol)-[r]->(s:Symbol) WHERE t.project_id = 10
      RETURN DISTINCT r.built_at_sha` → a single SHA across all 10 edges,
      including the 4 carried-forward test files.
- [x] Re-run with **no** change: nothing is scheduled and completeness reports 100%
      carried forward.
      Observed `Incremental run: 0 of 6 test files scheduled, 6 carried
      forward (0 source file(s) changed since ad83cd6b49b7)` with
      `scheduled: 0, carried_forward: 6, coverage_pct: 100.0`.
- [ ] Measure: a one-file change on a ~5k-test suite schedules tens (not thousands) of
      test files and drops wall-clock by an order of magnitude.
      **Still open** — needs the real `hbahuguna/pygments` 5k-test suite
      (project 8); the synthetic testbed above proves the behaviour, not
      the magnitude.

> **Defect found and fixed during this gate.** `changed_files_between()`
> sweeps untracked files so newly added sources get instrumented, but it
> also counted files the run itself leaves in the checkout — the 11.4
> dependency marker `.tia-deps-installed`, coverage databases
> (`.coverage*`), pytest-cov's `coverage.json`, `.pytest_cache/` and
> `node_modules`. On the first live attempt that pushed
> `changed_source_files / known_source_files` past the 0.5 large-diff
> guard and the run silently fell back to the full suite, so AC1 never
> fired. Fixed by excluding run artifacts from the diff
> (`1ceda94`, test
> `test_ignores_run_artifacts_left_in_the_checkout`); re-running the same
> sequence then narrowed as specified. Repos whose `.gitignore` covers
> these artifacts are unaffected only by luck — the marker is never
> ignored by any testbed.

## G. Story 11.6 — TS/Playwright Parity

The built-in TS testbeds all have more than 10 test files (`blacktrigram`, `zod`,
`hono` — see `TYPESCRIPT_TESTBEDS`), so they expose the old cap.

- [x] Instrument a TS testbed with more than 10 test files:
  ```bash
  curl -sN -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
    -H "Authorization: Bearer dev-admin-token" -H "Content-Type: application/json" \
    -d '{"repo_url":"https://github.com/Hack23/blacktrigram.git","language":"typescript","run_fresh":true}' \
    | grep -E 'Running .*/.* vitest test files|shard|Coverage collected'
  ```
  **Status: executed 2026-10-16.** Used a synthetic custom TS testbed
  (12 test files over one source module) pushed to a bare `file://`
  origin rather than `blacktrigram`, because a custom `repo_url` takes
  the `_detect_typescript_config` path and still exercises the cap, the
  sharder and both engines — without a multi-minute clone + `npm ci` of
  a large real repo. Same project (id 8) as the earlier TS runs.
- [x] All test files are scheduled (`Running N/M` with **N == M**, no truncation at 10).
      Observed `Running 12/12 vitest test files with per-test coverage...`
      — the old cap would have scheduled 10.
- [x] Vitest files run in parallel shards (log shows the shard split;
      `TIA_TS_SHARDS` bounds it, default ~CPU capped at 4).
      Observed `sharding 12 files across 4 workers: w0=3, w1=3, w2=3, w3=3`
      and `Coverage collected: 12/12 test files`; status `COMPLETED`,
      72 edges (12 files x 6 symbols).
- [ ] Playwright file list is sharded but executed **serially** (shared
      `<test_dir>/.coverage-raw` — see story deviation); every file still runs.
      **Not manually exercised** — needs a live browser + dev server. The
      serial/parallel contract is pinned by
      `test_typescript_pipeline_parity.py::test_execution_is_serial`, and
      the shared-`coverage-raw` reason is recorded in the story's
      Deviations.
- [x] With `@testsquad/vitest-plugin` installed in the testbed, coverage is
      collected via the plugin (`"engine": "vitest-plugin"`); without it the
      per-file fallback is used (`"engine": "per-file"`).
      Both verified on the same testbed: the cold run (`run_fresh=true`,
      plugin absent) logged `Coverage collected: 12/12 test files`; the
      plugin was then `docker cp`-ed into the cached checkout's
      `node_modules/@testsquad/vitest-plugin` and a warm run
      (`run_fresh=false`, cache reused, deps marker hit) logged
      `Coverage collected via vitest-plugin: 12 test files`.
- [x] Vitest per-test coverage yields multiple test symbols per file.
      Each of the 12 mappings reported 6 symbols
      (`add, sub, mul, Calc, inc, dec`) for the single source module.
- [ ] `cd packages/vitest-plugin && npm test` — **6 passed** (local gate).

## H. Story 11.7 — Confidence Gradation

- [ ] A partially covered symbol has `confidence < 1.0`:
  ```bash
  NEO "MATCH (:TestSymbol)-[e:EVIDENCE]->(s:Symbol) WHERE s.project_id=$PROJECT_ID RETURN s.name, e.confidence, e.covered_line_count LIMIT 10;"
  ```
- [ ] Re-running updates confidence/metadata (no stale first value).

## I. Story 11.8 — TS/Playwright Coverage Completeness

- [ ] `curl -s "$RADIUS/projects/$PROJECT_ID/instrumentation/coverage" | jq .` returns non-zero metrics for a TS/Playwright project.
- [ ] No `low_coverage` warning at 100%; a genuine low-coverage run still warns.

## J. Story 11.9 — Failure Reasons

- [ ] A test file needing a missing optional package reports `reason=dependency_missing`.
- [ ] Skipped tests report `reason=skipped`.
- [ ] An install failure is visible as a structured error, not silently ignored.

## K. Story 11.10 — Auto Re-Instrumentation

- [ ] A push to the default branch triggers one instrumentation run.
- [ ] A second rapid push is coalesced (no concurrent duplicate run).
- [ ] A project with `instrumentation: false` is not triggered.

## L. Story 11.11 — Dead-Code Cleanup

- [ ] `grep -rn "InstrumentationService\|CoverageTransformer\|InstrumentationTransformer\|_find_coverage_db" services/core --include=*.py` returns only intended references.
- [ ] Full suite still green.

---

## Result

- [ ] **All pass** — Epic 11 Done
- [ ] **Some failed** — note which story/steps for fixing
