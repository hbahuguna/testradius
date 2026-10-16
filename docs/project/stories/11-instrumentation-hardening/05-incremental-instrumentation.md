# Story 11.5: Incremental Instrumentation (Only Re-Run Affected Tests)

**Status**: Manual Test
**Epic**: 11 — Instrumentation Hardening
**Effort**: 3d
**Priority**: P1
**Depends on**: 11.1, 11.2

---

## Summary

When the graph already holds evidence, a re-instrumentation run should execute only the tests whose covered files changed since the previous anchor, and carry the rest forward.

## Current behaviour (the problem)

- Every run re-executes the **entire** suite and re-resolves every symbol (`per_test_analyzer.run_tests_with_coverage`, `:333`). For a 5k-test suite this is the dominant cost (~30 min for Pygments).
- The graph already knows which test covered which file/symbol, but that knowledge is not used to narrow the next run.

## Acceptance criteria

- [x] Given prior evidence and a diff between the prior anchor and the current commit, the run executes only tests that cover changed production files, plus any new/changed test files.
- [x] Evidence for unaffected tests is carried forward and re-stamped with the new `built_at_sha` (consistent with 11.1).
- [x] Coverage completeness is still computed and reported against the full suite denominator.
- [x] With no prior evidence, the run falls back to a full run.
- [x] A `run_fresh` / full-rebuild flag forces a full run when requested.
- [ ] Measured: a small diff reduces executed tests by an order of magnitude on the Pygments testbed. **(manual gate — needs network; procedure in the runbook §2f)**

## Implementation notes

- Compute the changed-file set from `git diff <old_sha> <new_sha>` in `pipeline_worker._run_python_pipeline` (`:425`); reuse `diff_parser` parsing.
- Query Neo4j for tests whose `[:EVIDENCE]` targets a `Symbol` in a changed file. Union with changed/new test files (which must always run). Feed that list to `analyze_per_test_coverage` / `run_tests_with_coverage`.
- Carry forward the untouched edges: re-stamp `built_at_sha` on all edges (write path), but only re-write edge *sets* for tests that ran.
- Guard: if the changed set is large (e.g. > X% of files), fall back to full.

## Tests (TDD — write first)

- New: `services/core/tests/test_incremental_instrumentation.py` — given a fake prior graph and a one-file diff, assert the scheduled test list excludes unaffected tests and includes all tests covering the changed file.
- Assert fallback to full when prior evidence is absent.

## Verification

```bash
pytest services/core/tests/test_incremental_instrumentation.py -v   # 56 passed
# Runbook check: instrument Pygments at anchor, change one lexer, re-run, compare scheduled count.
```

### Manual gate — live backend (2026-10-16)

Executed against the running `core-ml` container (bind-mounted source, so a
container restart loads new code). To advance the anchor without pushing to a
public repo, the testbed was a synthetic installable Python project (6 test
files over 4 source modules) on a bare `file://` origin; project
`gate-py-incremental` (id 10). Test plan §F records the full trace.

| Check | Result |
| --- | --- |
| Narrowed run | `Incremental run: 2 of 6 test files scheduled, 4 carried forward (1 source file(s) changed since ad83cd6b49b7)`; mappings emitted for `test_text_a.py` and `test_text_b.py` only |
| Full-suite denominator | `test_files_expected: 2, test_files_scheduled: 2, test_files_total: 6, test_files_carried_forward: 4, test_files_instrumented: 6, coverage_pct: 100.0` |
| `run_fresh=true` | all 6 scheduled, `carried_forward: 0`, no `Incremental run` line |
| Checkout advances | cached checkout moved to the pushed tip; `built_at_sha` advanced each run |
| One SHA project-wide | `DISTINCT r.built_at_sha` over all 10 edges → a single SHA, including the 4 carried-forward test files |
| No-change re-run | `Incremental run: 0 of 6 test files scheduled, 6 carried forward (0 source file(s) changed since ad83cd6b49b7)`, `scheduled: 0, coverage_pct: 100.0` |
| Order-of-magnitude (AC6) | **still open** — needs the real `hbahuguna/pygments` 5k-test suite; the synthetic testbed proves the behaviour, not the magnitude |

### Defect found by the gate (fixed, `1ceda94`)

The first live attempt reported `Running full suite (large_diff)` instead of
narrowing, even though only one source file had changed. Root cause:
`changed_files_between()` includes untracked files so that newly added sources
get instrumented, but that sweep also picked up files the run itself leaves in
the checkout — the 11.4 dependency marker `.tia-deps-installed`, coverage
databases (`.coverage*`), pytest-cov's `coverage.json`, `.pytest_cache/` and
`node_modules`. Those phantom entries pushed
`changed_source_files / known_source_files` past the 0.5 large-diff guard, so
incremental silently degraded to a full run.

Fixed by filtering run artifacts out of the untracked sweep
(`RUN_ARTIFACTS` / `_is_run_artifact` in `incremental.py`), with the failing
test `test_ignores_run_artifacts_left_in_the_checkout` written first. Note the
marker is never git-ignored by any real testbed, so this affected production
repos too — most visibly small and medium ones, where a handful of phantom
files is enough to trip the guard.

---

## Done — implementation notes

### Wiring overview

```
main.py run_instrumentation_worker
  ├─ store = Neo4jStore(neo4j)                     # created BEFORE the pipeline
  └─ run_pipeline(..., evidence_store=store)
        └─ _run_python_pipeline
             1. clone_testbed(use_cache=not run_fresh)   # now refreshes to the tip
             2. discover test files                       # the full "universe"
             3. build_incremental_plan(...)               # reads prior evidence
             4. narrow → run_files (subset)               # plan.tests_to_run
             5. analyze_per_test_coverage(run_files, universe=test_files,
                                          carried_forward=plan.carried_forward)
             6. yield mappings event + `incremental` metadata
  └─ if event["incremental"]: store.apply_incremental_mappings(...)
     else:                    store.replace_mappings(...)
```

### New module: `instrumentation/incremental.py`

Pure planner plus isolated git helpers — nothing there touches Neo4j or pytest.

- `normalize_path(path, root)` — repo-relative posix form, matching the coverage/resolver path convention.
- `plan_incremental_run(...)` → `IncrementalPlan`. Returns `mode="full"` with a reason for every unsafe case:
  - `no_prior_evidence` (empty coverage index),
  - `no_anchor`, `no_current_sha`, `diff_unavailable`,
  - `large_diff` (changed source files / known source files > `fallback_fraction`,
    default `0.5`, overridable via `TIA_INCREMENTAL_MAX_CHANGED_FRACTION`).
  Otherwise `mode="incremental"` with `tests_to_run`, `carried_forward`,
  `changed_source_files`, `changed_test_files`, `removed_test_files`,
  `tests_to_drop`.
- `changed_files_between(repo_path, old_sha, new_ref=None)` — `git diff --name-only
  --no-renames` plus untracked files; `new_ref=None` diffs the **working tree** so
  uncommitted edits count. Returns `None` when the diff cannot be computed.
- `ensure_commit(repo_path, sha)` — fetches a missing anchor commit into a shallow
  clone (`git fetch --depth=1 origin <sha>`), because the pipeline clones `depth=1`
  and the previous anchor is normally absent. Returns `False` when the server
  refuses, which becomes `diff_unavailable` → full run.

### Checkout refresh: `testbed_manager._refresh_checkout` (behaviour change)

`use_cache` used to serve a checkout that **never moved** — the anchor could never
advance, and re-runs silently instrumented the first clone's commit. Per the design
decision on this story, a cache hit now fetches the branch tip
(`git fetch --depth=1 origin <branch>` + `git reset --hard FETCH_HEAD`) and rewrites
the sidecar `head_sha`. This is what makes `git diff <anchor>..HEAD` meaningful, and
it also fixes a latent staleness bug for every re-instrumentation run.

- A checkout with **tracked local modifications** is *not* refreshed (`reset --hard`
  would destroy work); incremental instrumentation then diffs the working tree.
  Untracked files survive `reset --hard` and do not block a refresh.
- A failed fetch (offline) falls back to the existing commit rather than re-cloning.
- Refresh happens under the existing `_slot_lock`, so concurrent refreshes serialize.
- `clone_testbed`'s two cache-hit branches collapsed into `_reuse_checkout`, which
  re-checks usability under the lock before refreshing (`get → refresh → return`).

### Neo4j store: three new methods (`neo4j_store.py`)

- `get_coverage_summary(project_id)` → `{"anchor_sha", "tests": [{name, file,
  source_file}]}`. `anchor_sha` is set only when the project has exactly one distinct
  `built_at_sha` (the 11.1 invariant); mixed/absent → `None` → full run. Read failures
  degrade to "no evidence", which can only cost optimality, never correctness.
- `apply_incremental_mappings(mappings, project_id, built_at_sha, rerun_test_names,
  drop_test_names)` — deletes coverage edges **only** for the named tests, writes the
  re-run edge sets (verified in-transaction, same contract as `replace_mappings`),
  then re-stamps **every** surviving coverage edge *and* `TestSymbol` node to the new
  `built_at_sha`. The restamp is skipped when `built_at_sha` is falsy so an omitted
  SHA can never clear anchors. Verified count is the number of edges written this
  round (0 when nothing re-ran).
- `count_coverage_edges(project_id)` — project total, used to report the honest
  post-run evidence size (carried-forward edges were not written this round).

### Coverage completeness (AC3)

`_coverage_completeness` / `analyze_per_test_coverage` gained `universe` and
`carried_forward`. When `universe` is given the denominator is the **full suite**,
and a file counts as covered when it produced coverage this round **or** its evidence
was carried forward. Two keys were added — `test_files_total` (the denominator) and
`test_files_carried_forward` — while `test_files_scheduled` keeps its old meaning
(files scheduled *this* round), so `run_models`/API consumers are unaffected. Full
runs pass `universe=None` and behave exactly as before.

### Deviations from the story's implementation notes

1. **`git diff`, not `diff_parser`.** The note says "reuse `diff_parser` parsing";
   a name-only diff needs no parsing, so `incremental.changed_files_between` shells
   out to `git` directly (and reuses `diff_parser`'s *path* normalization convention
   via `normalize_path`). `diff_parser` is for parsing *content* diffs into changed
   symbols; that is a different job.
2. **Diff target is the working tree**, not strictly `<new_sha>`. `new_ref=None`
   (`git diff <anchor>`) includes uncommitted edits, which is the correct thing to
   instrument. Committed-only changes are a subset of this.
3. **Deletion by test *name*, discovered from the graph.** The note does not say how
   to identify "tests that ran"; deleting by file path would hit Cypher string-equality
   against a path form we do not fully control, so the plan carries the prior
   `TestSymbol.name` values verbatim (`rerun_test_names` / `drop_test_names`).
4. **Zero-change fast path.** If nothing changed, the run executes **no** tests and
   just re-stamps carried-forward evidence (the analyzer errors on an empty file list).
   Completeness is reported as `100%` carried.

### Limitations / follow-ups

- **Orphaned `Symbol` nodes.** When a changed file's line spans move, the re-run
  writes new `Symbol` nodes and the old-span nodes lose their edges but are not
  deleted. `replace_mappings` already leaves such symbols behind, so this is
  pre-existing, but repeated incremental runs accumulate them. A "delete
  evidence-less project symbols" pass is a good follow-up (not done here to avoid
  touching ingestor-owned nodes).
- **Dirty working tree + anchor.** Evidence is stamped with `HEAD` even when the
  checkout is dirty, so a subsequent run re-derives the same working-tree diff and
  re-runs the same tests. Safe (idempotent in effect) but not a no-op.
- **TypeScript / Playwright pipelines remain full runs.** `evidence_store` is only
  plumbed through the Python pipeline; the TS/Playwright generators are untouched.
- **Concurrent runs sharing a checkout.** The refresh is serialized by the slot lock,
  but a run that is *already executing tests* can still have its checkout reset by a
  later run for the same repo. This is the 11.4 follow-up ("run-scoped lock /
  already-running guard") and is unchanged here.
- **AC6 (order-of-magnitude measurement) is not yet taken** — it needs the Pygments
  remote and a full cold run; the procedure is in `docs/runbooks/tia-py-key-value.md` §2f.

### Tests

`services/core/tests/test_incremental_instrumentation.py` (new, 56 tests):

- `TestPlanIncrementalRun` (16) — narrowing, union of source/test changes, removed
  test files, empty diff, unknown sources, every fallback reason, the configurable
  large-diff guard (incl. env override), sorting/dedup.
- `TestNormalizePath` (5).
- `TestChangedFilesBetween` (7) — committed diff, working-tree edit, untracked file,
  identical commits, unknown anchor, a real `file://` **shallow clone** whose
  anchor is fetched back in by `ensure_commit`, and
  `test_ignores_run_artifacts_left_in_the_checkout` (added by the live gate —
  run artifacts must not count as source changes).
- `TestGetCoverageSummary` (4) / `TestApplyIncrementalMappings` (9) /
  `TestCountCoverageEdges` (3) — store contract: anchor selection, delete-only-rerun,
  drop names, restamp-all (not scoped to reruns), empty-mappings restamp,
  verification mismatch raises, failure tolerance.
- `TestIncrementalCompleteness` (3) — full-suite denominator, carried-forward
  counting, and the "behaves exactly as before" guard.
- `TestBuildIncrementalPlan` (6) — plan built from a real local repo + fake store.
- `TestRunPythonPipelineNarrowsTheRun` (5) — end-to-end through
  `_run_python_pipeline` with a fake analyzer/TestbedManager: only covering tests
  scheduled, full-suite denominator passed, `run_fresh` runs everything, no store
  runs everything, nothing-changed skips execution, error path preserved.

`services/core/tests/test_testbed_cache.py` (+4, `TestCacheRefresh`): reused checkout
advances to the new remote commit (without re-cloning, sidecar follows), dirty
checkout is left alone, fetch failure falls back to the existing commit, and
`run_fresh` lands on the new tip via a clean clone.

### Verification

```bash
PYTHONPATH="services/core:packages/shared" DATABASE_URL="sqlite+aiosqlite:////tmp/tr_test.db" \
python3.10 -m pytest services/core/tests/test_incremental_instrumentation.py \
  services/core/tests/test_testbed_cache.py services/core/tests/test_test_discovery.py \
  services/core/tests/test_coverage_sharding.py services/core/tests/test_resolver_parity.py \
  services/core/tests/test_innermost_symbols.py services/core/tests/test_diff_parser_qualified.py \
  services/core/tests/test_symbol_resolver.py services/core/tests/test_symbol_identity.py \
  services/core/tests/test_neo4j_store.py services/core/tests/test_persistence_verification.py \
  services/core/tests/test_freshness.py services/core/tests/test_instrumentation_transformer.py \
  services/core/tests/test_per_test_coverage_integration.py services/core/tests/test_static_fusion.py \
  services/core/tests/test_import_resolver.py services/core/tests/test_diff_parser.py \
  services/core/tests/test_selection_limits.py services/core/tests/test_counting.py \
  --override-ini='addopts=' --noconftest -p no:cacheprovider -q
# 240 passed, 0 failed
```

Bugs found and fixed during the work: `carried_rel & universe_by_rel` (set ∩ dict
`TypeError`) in `_coverage_completeness`; and the mixed absolute/relative form of
`universe` passed to the analyzer (the analyzer normalizes, but the pipeline now
passes the untouched `test_files` as `universe` so the two arguments agree).
