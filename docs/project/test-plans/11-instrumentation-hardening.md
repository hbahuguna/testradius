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
- [ ] `pytest services/executor/tests/ -q` — **all pass**
- [ ] `npm --workspace @testsquad/vitest-plugin run build` — **builds**

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

- [ ] With prior evidence, change one production file and re-run.
- [ ] Only tests covering the changed file run (compare scheduled count in SSE:
      `"Incremental run: N of M test files scheduled ... carried forward"`).
- [ ] Coverage completeness still reports against the full-suite denominator
      (`test_files_total` == the full suite; carried-forward files counted as covered).
- [ ] `run_fresh=true` forces a full run (no `incremental` metadata in the stream).
- [ ] The cached checkout advances to the branch tip before the diff (the anchor moves);
      a checkout with tracked local edits is left un-refreshed.
- [ ] After the run, exactly one `built_at_sha` remains project-wide (carried-forward
      edges were re-stamped — same invariant as §B).
- [ ] Re-run with **no** change: nothing is scheduled and completeness reports 100%
      carried forward.
- [ ] Measure: a one-file change on a ~5k-test suite schedules tens (not thousands) of
      test files and drops wall-clock by an order of magnitude.

## G. Story 11.6 — TS/Playwright Parity

- [ ] Instrument a TS testbed with more than 10 test files.
- [ ] All test files are scheduled (no 10-file cap).
- [ ] Runs execute in parallel shards.
- [ ] Vitest per-test coverage yields multiple test symbols per file.

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
