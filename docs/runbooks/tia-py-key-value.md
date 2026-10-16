# Runbook: TIA on hbahuguna/py-key-value with Instrumentation + Test Reduction

This runbook shows (1) instrumenting py-key-value to build symbol→test evidence, and (2) using TIA to reduce tests for a PR vs. total tests in the repo. Commands are verified to work with a locally running TestRadius instance.

## Prerequisites
- TestRadius backend healthy at `http://localhost:8000`. Verify: `curl -s http://localhost:8000/health`
- TIA agent via Python module (preferred): `cd /Users/skaparwan/github/testradius/apps/tia-agent && .venv/bin/python -m tia_agent ...`
- Project for py-key-value exists (id 3). Verify:

```bash
export RADIUS=http://localhost:8000
curl -s "$RADIUS/projects" | jq '.[] | select(.name=="hbahuguna/py-key-value") | {id,name}'
```

## 1. Check current evidence (baseline)
```bash
PROJECT_ID=3
curl -s "$RADIUS/projects/$PROJECT_ID/test-mapping?limit=10000" | jq 'length'  # total evidence mappings
curl -s "$RADIUS/projects/$PROJECT_ID/test-mapping?limit=10000" | jq 'map(.test_symbol)|unique|length'  # distinct tests with evidence
curl -s "$RADIUS/projects/$PROJECT_ID/test-mapping?limit=10000" | jq 'map(.product_file)|unique'
```
Note: this project may already have prior instrumentation. The steps below show how to re-run instrumentation (fresh) and verify.

## 2. (Optional) Re-run instrumentation to cover all files/tests
To (re)build full evidence for the repo, run instrumentation via the backend. Use SSE to stream progress.

```bash
curl -N -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/hbahuguna/py-key-value.git","language":"python","run_fresh":true}'
```
Watch for events: `status` updates (e.g., `RESOLVING_SYMBOLS`, `STORING_IN_NEO4J`, `COMPLETED`) and `progress` messages. On success, the final event is `{"event":"status","data":{"status":"COMPLETED",...}}`. Instrumentation runs in the core-ml container; wait until COMPLETED.

After completion, verify evidence count increased:
```bash
curl -s "$RADIUS/projects/$PROJECT_ID/test-mapping?limit=10000" | jq 'length'
curl -s "$RADIUS/projects/$PROJECT_ID/test-mapping?limit=10000" | jq 'map(.product_file)|unique'
```

## 2a. Second-run clone + dependency cache (Epic 11.4)

A second instrumentation run against an **unchanged** testbed no longer re-clones the repo or re-installs its dependencies:

- `TestbedManager.clone_testbed` uses a stable checkout path `/tmp/testbed-cache/<repo>-<branch>-<sha1(repo@branch#install_command)[:8]>` instead of a fresh `testbed-<name>-YYYYmmdd_HHMMSS` directory every run, and skips cloning when the sidecar `<path>.meta.json` matches repo, branch, install command, TTL (default 24 h) and the checkout's `HEAD`.
- `per_test_analyzer._install_test_deps` writes `.tia-deps-installed` (SHA-256 of the install spec) into the checkout, so the `pip install` of the plugin set / `-e .` / `requirements*.txt` / extras is skipped **across processes** — the in-process `_DEPS_INSTALLED` set is no longer the only cache. The marker is only written when the core installs succeed, so a broken install is retried rather than cached.
- `typescript_pipeline` / `playwright_pipeline` `install_dependencies` skip `npm`/`yarn`/`pnpm install` when `node_modules` exists and the marker `node_modules/.tia-node-deps` matches the lockfiles + commands.

`run_fresh: true` bypasses all of it (clean clone + install), so a cached checkout can always be forced.

### Measure it

Run the same payload twice and compare wall clock:

```bash
# (a) cold — forces a fresh clone + install
/usr/bin/time -p curl -sN -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/hbahuguna/py-key-value.git","language":"python","run_fresh":true}' \
  > /dev/null

# (b) warm — same payload, reuses the checkout + deps
/usr/bin/time -p curl -sN -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/hbahuguna/py-key-value.git","language":"python","run_fresh":false}' \
  > /dev/null
```

The warm run still executes the suite + coverage (the dominant, unchanged cost). What it skips is the clone and both dependency installs:

| Measured component | First (cold) | Second (warm) |
|---|---|---|
| `clone_testbed` (local 1-file repo, `test_testbed_cache.py`) | 177.6 ms — clone + install | **40.4 ms** — cache hit, 0 clones, 0 installs |
| `git clone` of a real testbed (network) | tens of seconds … minutes | **0 calls** |
| `_install_test_deps` (11 packages + `-e .` + requirements + extras) | runs | **0 calls** (marker matches) |

The first two rows are unit-level measurements from `services/core/tests/test_testbed_cache.py`, which *asserts* the warm path performs zero clone/install invocations (so the property is regression-tested, not just observed). **End-to-end py-key-value figure:** record the `real` line of both `/usr/bin/time -p` invocations above when running against a live backend.

## 2b. Verify coverage completeness (C2)
Instrumentation reports how much of the suite actually produced per-test evidence. The final SSE `status` event carries it, and it is persisted for non-streaming clients:

```bash
# In the SSE stream, look for:
#   {"event":"coverage_completeness","data":{...}}
#   {"event":"status","data":{"status":"COMPLETED","edges":40242,"coverage":{...}}}

# Or fetch the last run's completeness (404 until a run is recorded):
curl -s "$RADIUS/projects/$PROJECT_ID/instrumentation/coverage" | jq .
```

Fields: `test_files_expected`, `test_files_collectable`, `test_files_scheduled`, `test_files_instrumented`, `coverage_pct`, `missing_count`, `missing_test_files`, plus `low_coverage`/`warning` when `coverage_pct < 95`.

Example (fresh full-suite run on py-key-value): `expected=52`, `collectable=31`, `scheduled=31`, `instrumented=30`, `coverage_pct=96.8`, `missing=[tests/stores/windows_registry/test_windows_registry.py]` (Windows-only, skipped on Linux). The 21 non-collectable files are test files that cannot import in this environment — they are counted in `test_files_expected` and surfaced as the gap between `expected` and `collectable`.

The `tia-agent` also surfaces low coverage: `InstrumentationResult.coverage_pct` / `.coverage_warning`, printed as `[warning] coverage …% is below 95%…` after instrumentation.

## 2c. Verify persistence (D1)
Mapping writes are **transactional and verified**. `Neo4jStore.store_mappings` writes all EVIDENCE edges in a single transaction, then re-counts the stored edges inside that transaction; if the count does not equal the number of distinct mapping edges (or the write raises), it raises `PersistenceError` and the run is recorded as `ERROR` — it can never "COMPLETE" with 0 persisted mappings.

The final SSE `status` event now reports the **verified** edge count:
```bash
# {"event":"status","data":{"status":"COMPLETED","edges":40295,"coverage":{...}}}
```
Cross-check the reported count against the graph (they must match):
```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p testsquad_password \
  "MATCH (:TestSymbol {project_id:3})-[e:EVIDENCE]->(:Symbol) RETURN count(e) AS evidence;"
```
If persistence fails you instead get an `error` event and `InstrumentationRun.status = "ERROR"` (see `GET "$RADIUS/projects/$PROJECT_ID/instrumentation/coverage"`), not a silent zero-edge `COMPLETED`.

## 2d. Verify commit-pinned evidence freshness (D2)

Each instrumentation run stamps the testbed commit it was built against on the
`TestSymbol` nodes and `EVIDENCE` edges (`built_at_sha`). At analyze time the
backend compares that against the requested `commit_sha` and reports drift:

```bash
# 1. Confirm the stamp == the repo's HEAD (one distinct SHA expected):
docker compose exec -T neo4j cypher-shell -u neo4j -p testsquad_password \
  "MATCH (ts:TestSymbol {project_id:3}) WHERE ts.built_at_sha IS NOT NULL \
   RETURN collect(DISTINCT ts.built_at_sha);"
git ls-remote https://github.com/hbahuguna/py-key-value.git HEAD

# 2. Analyze against the SAME SHA -> fresh (NOT stale):
curl -s -X POST "http://localhost:8000/projects/3/analyze-pr" \
  -H "Authorization: Bearer dev-admin-token" -H "Content-Type: application/json" \
  -d '{"full_name":"hbahuguna/py-key-value","pr_number":1,
       "commit_sha":"<the SHA from step 1>","file_paths":[]}'
#  -> "evidence_built_at_sha": "<sha>", "stale_evidence": false

# 3. Analyze against a DRIFTED 40-hex SHA -> stale + reason:
#    "stale_evidence": true, "stale_evidence_reason":
#    "evidence built at <12> but analyzing <12>"

# 4. Branch ref ("main") is not comparable -> not stale, not unversioned.
#    Anything that predates SHA stamping reports evidence_unversioned=true
#    (no build commit recorded) rather than stale.
```

The agent treats `stale_evidence` like truncation-drop safety: it **forces a
full-suite fallback** with reason "built against a different commit" and keeps
the backend's reason in `notes`, so drift can never silently drive selection.

## 2e. Run the shadow-validation harness (V1)

`scripts/tia_agent/shadow_validate.py` runs the **full suite** and TIA
**selection on the same commit** and asserts `selected ⊇ failing`, exiting
non-zero on any attributable miss. It is stdlib-only, so drop it into `core-ml`
next to a checkout whose `.venv` has pytest (a testbed under `/tmp/testbed-*`).
Use the **anchor = the evidence `built_at_sha`** so the run is fresh (see §2d);
if the checkout has moved past the stamp, either analyze the stamped commit or
re-instrument first, otherwise `stale_evidence` would force full-suite
fallback and make the run vacuous.

```bash
# 0. Which commit is the evidence pinned to? (also the stamp uses this)
STAMP=$(docker compose exec -T neo4j cypher-shell -u neo4j -p testsquad_password \
  "MATCH (ts:TestSymbol {project_id:3}) WHERE ts.built_at_sha IS NOT NULL \
   RETURN collect(DISTINCT ts.built_at_sha)[0];" 2>/dev/null | tail -n +2 | tr -d '"' | tr -d '\r')

# 1. Drop the harness into the container
docker compose cp scripts/tia_agent/shadow_validate.py core-ml:/app/shadow_validate.py

# 2. Corpus of >=10 changes. Real merged PRs (<10 here) can't satisfy the AC,
#    so --corpus history treats each non-merge commit touching src/ as a PR.
docker compose exec -T core-ml env PYTHONPATH=/app python /app/shadow_validate.py \
  --checkout /tmp/testbed-py-key-value-<ts> \
  --venv-python .venv/bin/python \
  --project-id 3 --full-name hbahuguna/py-key-value \
  --anchor-sha "$STAMP" \
  --corpus history --max-prs 12 --min-prs 10 \
  --report /tmp/shadow-report.json

# Expected (project 3, 74be46a):
#   [suite] 2 failing test(s): [...test_valkey_cluster.py::TestValkeyClusterClientSupport...]
#   failing: 2  attributable: 2  missed: 0  coverage: 1.0  gaps: 22  exit: 0

# 3. Prove the gate actually fails: force one real attributable failing test
#    to be unselected; the harness must return exit 1.
docker compose exec -T core-ml env PYTHONPATH=/app python /app/shadow_validate.py \
  --checkout /tmp/testbed-py-key-value-<ts> --venv-python .venv/bin/python \
  --project-id 3 --anchor-sha "$STAMP" --corpus history --max-prs 12 --min-prs 10 \
  --report /tmp/shadow-selftest.json --self-test
#   SELF-TEST OK: injected miss on ...::test_cluster_client_type_accepted -> exit 1
#   missed: 2  coverage: 0.0  exit: 1

# 4. Pull the report out for inspection / CI artifacts
docker compose cp core-ml:/tmp/shadow-report.json ./shadow-report.json
```

Exit codes: **0** pass · **1** a failing test was unselected · **2** harness
error · **3** corpus smaller than `--min-prs`. Other corpora: `--corpus github
--full-name <owner/repo>` (fetches merged PRs + their files) and `--corpus
file --corpus-file corpus.json`. A miss only counts when the failing test has a
real `EVIDENCE` edge into one of the change's files (`test-mapping?query=<nodeid>`),
so environment-only failures don't pollute the metric; the report still lists
**gaps with suggested new EVIDENCE edges** (`test-mapping?query=<file>` → symbols
in the changed files). Scope (board open question #2): V1 runs in our CI corpus,
not in-product.

## 2f. Incremental re-instrumentation (Epic 11.5)

A re-run against a **changed** repo no longer re-executes the whole suite. When the
graph already holds evidence, the run narrows to the test files that cover files
changed since the evidence's anchor commit; everything else is carried forward and
re-stamped with the new `built_at_sha`.

How it decides (all inside `_run_python_pipeline`):

1. `clone_testbed` **refreshes the cached checkout** to the branch tip
   (`git fetch --depth=1 origin <branch>` + `git reset --hard FETCH_HEAD`) — unless the
   checkout has tracked local edits, in which case it is left alone and the working
   tree is instrumented as-is. This is what lets the anchor move; a failed fetch falls
   back to the existing commit.
2. `build_incremental_plan` reads the prior evidence via `Neo4jStore.get_coverage_summary`
   (anchor SHA + `source file → test files`) and diffs (`git diff <anchor>`, plus
   untracked files).
3. `incremental.plan_incremental_run` picks: tests covering changed source files ∪
   changed/new test files. Falls back to a **full run** with a reason whenever that
   could be wrong: `no_prior_evidence`, `no_anchor`, `no_current_sha`,
   `diff_unavailable`, `large_diff` (> `TIA_INCREMENTAL_MAX_CHANGED_FRACTION`, default 0.5).
4. Writes go through `Neo4jStore.apply_incremental_mappings`: only the re-run tests'
   edges are replaced (removed test files' edges are dropped), then **every** surviving
   coverage edge/node is re-stamped to the new anchor (one `built_at_sha`, per §2d).

`run_fresh: true` always forces a full run (and a clean clone).

### What to look for in the SSE stream

```
{"event":"progress","data":"Incremental run: 3 of 52 test files scheduled, 49 carried forward (1 source file(s) changed since 74be46a0c1d2)"}
{"event":"coverage_completeness","data":{"test_files_total":52,"test_files_scheduled":3,"test_files_carried_forward":49,"test_files_instrumented":52,"coverage_pct":100.0,"...":...}}
{"event":"status","data":{"status":"COMPLETED","edges":40242,"coverage":{...}}}
```

`test_files_total` is the **full-suite denominator** even though only
`test_files_scheduled` files ran; carried-forward files count as covered. With no
change at all, no tests run and the run reports `100%` carried. `edges` is the project
total (`count_coverage_edges`), not just the edges written this round.

### Measure it (AC6 — order-of-magnitude reduction)

```bash
# 1. Instrument at an anchor (full run), note the anchor SHA in the status event.
curl -sN -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/<owner>/<repo>.git","language":"python","run_fresh":true}' \
  | grep -o 'built_at_sha[^,]*'

# 2. Advance one file (e.g. one lexer) in the cached checkout and commit, so the
#    refreshed checkout sits one commit ahead of the anchor:
CHECKOUT=$(ls -d /tmp/testbed-cache/<slug>-<branch>-* | head -1)
cd "$CHECKOUT" && $EDITOR src/.../one_file.py && git commit -am "tweak"

# 3. Re-run (run_fresh:false) and compare the scheduled count with the first run.
/usr/bin/time -p curl -sN -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/<owner>/<repo>.git","language":"python","run_fresh":false}' \
  | grep -E '"Incremental run|"data":\{"test_files_total'
```

Expected on a ~5k-test suite (Pygments): a one-file change schedules **tens**, not
thousands, of test files, and wall clock drops from ~30 min to well under a minute for
the coverage run. **End-to-end figure: record both `/usr/bin/time -p` `real` lines when
running against a live backend** — the automated tests assert the *behaviour*
(narrowed list, full denominator, no re-run) but cannot measure the Pygments scale here.

The planner/refresh behaviour is regression-tested in
`services/core/tests/test_incremental_instrumentation.py` (incl. an end-to-end
`_run_python_pipeline` case with a fake analyzer) and
`services/core/tests/test_testbed_cache.py::TestCacheRefresh`.

## 3. Total test count in the repo (canonical unit)

The canonical unit is a **collected pytest nodeid** (parametrizations and
inherited methods are distinct tests). The backend reports it as
`total_tests_in_repo`, and the agent uses the same unit for
`total_affected_tests`; `impacted_ratio = total_affected_tests /
total_tests_in_repo` and the reduction is `(1 - impacted_ratio) * 100%`.

The old "297" figure is the raw `def test_*` count (no nodeid expansion),
kept only as a sanity floor — it undercounts because base test classes are
inherited by many subclasses (e.g. `tests/stores/base.py::test_delete_many_delete_many`
is collected once per wrapper) and parametrized cases expand. On the instrumented
graph, `total_tests_in_repo` for py-key-value is currently **1308** distinct
nodeids across the 30 collectable test files (52 expected; the rest need
optional deps).

```bash
# Canonical denominator straight from analyze-pr (or the graph):
curl -s -X POST "$RADIUS/projects/$PROJECT_ID/analyze-pr" -H "Authorization: Bearer dev-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"full_name":"hbahuguna/py-key-value","pr_number":1,"commit_sha":"main","file_paths":["src/key_value/aio/_utils/wait.py"]}' \
  | jq '{total_affected_tests, total_tests_in_repo, impacted_ratio,
         reduction_pct: ((1 - .impacted_ratio) * 100)}'
```

Local `def test_*` count (approximation only):
```bash
mkdir -p /tmp && cd /tmp && git clone --depth 1 https://github.com/hbahuguna/py-key-value.git pykv-test >/dev/null 2>&1
cd /tmp/pykv-test && PYTHONPATH=. python3 -c "
import glob
total=0
for tf in glob.glob('tests/**/*.py', recursive=True):
    if '__init__' in tf: continue
    try:
        with open(tf) as f:
            total += sum(1 for line in f if line.strip().startswith('def test_') or line.strip().startswith('async def test_'))
    except: pass
print(total)
"
```
For this repo: **297** test *functions* (not collected nodeids).

## 3b. Verify canonical test nodeids (O1)

Each test in the `--json` output must carry **one canonical pytest nodeid**
`path::Class::method[param]` — never `path::path::Class::method`. The backend
stores the full collected nodeid as `TestSymbol.name` (`path::...`) and also
returns the file path, so the agent canonicalizes before emitting. Verify:
```bash
.venv/bin/python -m tia_agent analyze \
  --repo hbahuguna/py-key-value --pr 1 \
  --file-paths src/key_value/aio/_utils/retry.py \
  --json | python3 -c "
import sys, json
d = json.load(sys.stdin)
n = [t['nodeid'] for t in d['tests']]
print('nodeids:', len(n), 'unique:', len(set(n)))
print('doubled:', [x for x in n if x.split('::')[0] in x.split('::', 1)[1]][:3] or 'NONE')
print('sample:', n[:3])
print('commands:', d['run_commands'][:2])
"
```
Every nodeid is unique per test and the class/method/`[param]` suffix appears
exactly once (spot-check a parametrized one like
`tests/stores/wrappers/test_statistics.py::TestStatisticsWrapper::test_get_large_put_get[large-data-string]`).
`run_commands` reference the same canonical nodeids, so
`pytest tests/<file>::<Class>::<method>` runs the exact test.

## 3c. Verify per-test reason paths + confidence (V2)

Every selected test carries a **reason path**
`changed_symbol:<name>@<file> -> <source(s)> -> <test nodeid>` and a
**confidence** (`high` = executed the changed symbol, `medium` = static
reachability only, `low` = fallback discovery). No selection is opaque: the
output contract rejects a test with a blank reason or an unknown confidence,
and when one test is selected for several symbols the strongest confidence
wins and carries its reason.

```bash
# Backend: every existing_tests row in analyze-pr carries the path + confidence
curl -s -X POST "http://localhost:8000/projects/3/analyze-pr" \
  -H "Authorization: Bearer dev-admin-token" -H "Content-Type: application/json" \
  -d '{"full_name":"hbahuguna/py-key-value","pr_number":1,
       "commit_sha":"74be46a56ae99a8671460b730d42766d561127e3",
       "file_paths":["src/key_value/aio/_utils/time_to_live.py"],"max_symbols":0}' \
  | python3 -c "
import sys, json
rows = [t for r in json.load(sys.stdin)['results'] for t in r['existing_tests']]
print('rows:', len(rows))
print('empty reason/conf:', sum(1 for t in rows if not t.get('reason') or not t.get('confidence')))
print('path-form:', sum(1 for t in rows if t['reason'].startswith('changed_symbol:')))
print('sample:', rows[0]['reason'])
"
# time_to_live.py -> 4309 rows, 0 empty, 4309 path-form (4188 high + 121 medium)

# Agent: same fields survive the flatten + dedupe, and the output validates
cd apps/tia-agent
.venv/bin/python -m tia_agent analyze \
  --repo hbahuguna/py-key-value --pr 1 \
  --file-paths src/key_value/aio/_utils/retry.py \
  --json | python3 -c "
import sys, json
from tia_agent.output.schema import validate_output
d = json.load(sys.stdin)
opaque = [t for t in d['tests'] if not t.get('reason') or not t.get('confidence')]
print('tests:', len(d['tests']), 'opaque:', len(opaque))
print('schema errors:', validate_output(d))
print('sample:', d['tests'][0]['reason'])
"
# retry.py -> 77 tests, 0 opaque, schema errors: []
```

Note the LLM never sees the nodeid leg of a reason: the conversational flow
forwards only the `symbol@file (source)` prefix (`llm_safe_symbols`), keeping
the D11 privacy contract intact while the CLI/JSON output keeps the full path.

## 4. Run TIA analyze on PR #1 and compare reduction
PR #1 changes `src/key_value/aio/stores/memory/store.py`. With the current evidence in this environment, that file has no mappings → fallback.

```bash
cd /Users/skaparwan/github/testradius/apps/tia-agent
.venv/bin/python -m tia_agent analyze \
  --repo hbahuguna/py-key-value \
  --pr 1 \
  --file-paths src/key_value/aio/stores/memory/store.py \
  --json | jq '{fallback_used, files_analyzed, symbols_selected, tests_selected, total_affected_tests, total_tests_in_repo: .total_tests_in_repo, tests: (.tests|length), note: (.notes|join("; "))}'
```
Expected: `fallback_used=true`, `tests_selected=0`, `total_affected_tests=0`. TIA cannot safely reduce tests (no evidence for the changed file).

Now test with files that DO have evidence:
```bash
.venv/bin/python -m tia_agent analyze \
  --repo hbahuguna/py-key-value \
  --pr 1 \
  --file-paths src/key_value/aio/_utils/wait.py \
  --json | jq '{fallback_used, total_affected_tests, total_tests_in_repo, impacted_ratio, reduction_pct: ((1 - .impacted_ratio) * 100), tests: (.tests|length), test_files: ([.tests[].file]|unique)}'

.venv/bin/python -m tia_agent analyze \
  --repo hbahuguna/py-key-value \
  --pr 1 \
  --file-paths src/key_value/aio/_utils/retry.py \
  --json | jq '{fallback_used, total_affected_tests, total_tests_in_repo, impacted_ratio, reduction_pct: ((1 - .impacted_ratio) * 100), tests: (.tests|length), test_files: ([.tests[].file]|unique)}'
```
Examples (with current evidence): wait.py → 2 tests (~99.8% reduction from 1308), retry.py → 77 tests (~94.1% reduction). Actual numbers depend on what instrumentation stored.

## 5. Interpretation
- Suite size = `total_tests_in_repo` = distinct collected test nodeids (1308 on py-key-value with current coverage). `total_affected_tests` uses the same unit.
- With complete symbol→test evidence in TestRadius, TIA analyzes changed files in the PR and returns only impacted tests (`fallback_used=false`). 
- The reduction is: `(1 - impacted_ratio) * 100%` where `impacted_ratio = total_affected_tests / total_tests_in_repo` (e.g. 2/1308 → 99.8% reduction). All three fields share one unit and are internally consistent.
- If a changed file has no evidence, TIA falls back (returns empty impacted set with `fallback_used=true`) — this indicates instrumentation coverage gap, not a failure. On fallback, `total_affected_tests == total_tests_in_repo` (ratio 1.0, no reduction claimed).

If instrumentation completes successfully and you analyze a file with stored mappings, you will see non-zero `tests_selected` and a large reduction vs. total tests.
