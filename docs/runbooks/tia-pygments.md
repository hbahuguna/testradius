# Runbook: TIA on Pygments (5.3k-test Python suite) — Instrumentation → Analyze → Proof

This runbook demonstrates TestRadius Test Impact Analysis end-to-end on a real
OSS repo with a large test suite: **Pygments** (`pygments/pygments`, ~5.3k
tests, pure Python, no runtime deps). It covers:

1. Registering a fork as a TestRadius project.
2. Instrumenting the suite to build symbol→test evidence.
3. Verifying the evidence graph and commit-pinned freshness.
4. Running `analyze-pr` on a real PR and reading the reduced test set.
5. A **controlled regression** that proves the reduced set has no misses.

Every command and number below was verified against a locally running
TestRadius instance (`docker compose --profile ml up -d`).

---

## 0. Prerequisites

- TestRadius backend healthy: `curl -s http://localhost:8000/health` → `{"status":"ok"}`
- Neo4j reachable via compose: `docker compose exec -T neo4j cypher-shell -u neo4j -p testsquad_password "..."`
- TIA agent CLI: `cd apps/tia-agent && .venv/bin/python -m tia_agent ...`
- `DEMO_MODE=1` on the backend so the agent works with an empty `radius_token`
  (curl examples use `Authorization: Bearer dev-admin-token`).
- A fork of Pygments you can push to. Here: **`hbahuguna/pygments`**.
- A local checkout of the fork pinned to the anchor commit (see §2). The
  verified probe clone lives at
  `/var/folders/6v/tfg439pn4zz20w5hyvgcm69c0000gq/T/opencode/probe-pygments`.

Helper used throughout:

```bash
RADIUS=http://localhost:8000
NEO() { docker compose exec -T neo4j cypher-shell -u neo4j -p testsquad_password "$1" 2>/dev/null | tail -n +2; }
```

---

## 1. Register the project

The agent can resolve-or-create by repo name. If it already exists, skip the
create.

```bash
curl -s -X POST "$RADIUS/projects" -H "Authorization: Bearer dev-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"name":"hbahuguna/pygments","description":"TIA demo (pygments fork, 5k-test suite)"}' \
  | jq '{id,name,description}'
# -> {"id":8,"name":"hbahuguna/pygments","description":"TIA demo ..."}

# Enable the two features this runbook exercises:
curl -s -X PUT "$RADIUS/projects/8/features" -H "Authorization: Bearer dev-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"features":{"instrumentation":true,"test_mapping":true}}'
```

`PROJECT_ID=8` for the rest of this runbook.

---

## 2. Instrument the suite (build evidence)

Instrumentation clones the repo, freezes the current `HEAD` as the **anchor
commit**, runs the suite under per-test coverage, and writes `EVIDENCE` edges
(symbol → test) plus `TestSymbol` nodes into Neo4j.

> **Python custom-repo constraints** (`pipeline_worker.py`): the suite must live
> under a top-level `tests/` directory. Test files are discovered by **running
> pytest** (`pytest tests/ --collect-only`) through a tiny dump plugin, so
> conftest-generated items (Pygments' `snippets/` + `examplefiles/` golden
> tests) are included alongside ordinary `test_*.py` modules — a plain
> `tests/**/test_*.py` glob would miss them. Install = `pip install -e .` + the
> fixed pytest plugin set + any recognized `requirements*.txt` / `.[test]`
> extras. Pygments satisfies all of this (its only `requirements.txt` lists
> `tox`, which is harmless).

```bash
curl -N -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
  -H "Authorization: Bearer dev-admin-token" -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/hbahuguna/pygments.git","language":"python","run_fresh":true}'
```

Stream events until `{"event":"status","data":{"status":"COMPLETED",...}}`.

### 2a. Verify coverage completeness

Pygments' suite is large; one file needs an optional dependency the container
lacks. Instrumentation reports exactly how much of it produced evidence:

```bash
curl -s "$RADIUS/projects/$PROJECT_ID/instrumentation/coverage" | jq .
```

Verified result for this project:

```json
{"test_files_expected":1540,"test_files_collectable":1540,"test_files_scheduled":1540,
 "test_files_instrumented":1539,"coverage_pct":99.9,
 "missing_test_files":["tests/test_unistring.py"]}
```

`coverage_pct >= 95` → no low-coverage warning. The only miss is
`tests/test_unistring.py`, which needs the optional `unistring` package.

### 2b. Verify the graph

```bash
NEO "MATCH (ts:TestSymbol {project_id:8}) RETURN count(ts) AS test_symbols;"
NEO "MATCH (s:Symbol {project_id:8}) RETURN count(s) AS symbols;"
NEO "MATCH (:TestSymbol {project_id:8})-[e:EVIDENCE]->() RETURN count(e) AS edges;"
```

Verified:

| metric | value |
|---|---|
| `TestSymbol` nodes | **5329** |
| `Symbol` nodes | **1285** |
| `EVIDENCE` edges | **66138** |

`TestSymbol` (5,329) now equals the number of **passing** tests at the anchor
(see §3), and it includes all 1,508 generated golden tests (836 `snippets/` +
672 `examplefiles/`).

### 2c. Verify commit-pinned freshness (D2)

```bash
NEO "MATCH (ts:TestSymbol {project_id:8}) WHERE ts.built_at_sha IS NOT NULL RETURN DISTINCT ts.built_at_sha;"
# -> "156d85fdd18d34427fe893527e71da91dcfb0eb5"
```

This SHA is the **anchor**. `analyze-pr` compares it to the requested
`commit_sha`: a mismatching 40-hex SHA → `stale_evidence=true` → the agent forces
a full-suite fallback. A branch ref (e.g. `master`) is not comparable and is
treated as not-stale. To stay fresh, analyze at the anchor (or the PR's
merge-base — see §4).

---

## 3. Know your denominator

The canonical unit is a **collected pytest nodeid**. The backend's
`total_tests_in_repo` is the number of distinct `TestSymbol` nodeids in the
project's evidence.

Instrumentation now discovers test files by **asking pytest** rather than
globbing `tests/**/test_*.py`, so the evidence graph models the full collected
suite:

```bash
cd <checkout>   # anchor commit
# Full suite, excluding the contrast file that errors on import:
.venv/bin/python -m pytest tests/ --collect-only -q --ignore=tests/contrast \
  --continue-on-collection-errors -o addopts= -p no:cacheprovider | tail -1
# -> 5345 tests collected

# Generated, data-driven lexer golden tests:
.venv/bin/python -m pytest tests/ --collect-only -q --continue-on-collection-errors \
  -o addopts= -p no:cacheprovider | grep "::" | grep -c "snippets/"
# -> 836
.venv/bin/python -m pytest tests/ --collect-only -q --continue-on-collection-errors \
  -o addopts= -p no:cacheprovider | grep "::" | grep -c "examplefiles/"
# -> 672
```

Of the **5,345** collected tests at the anchor, the evidence graph models
**5,329** — the number of *passing* tests:

- **1,508** are generated lexer golden tests parametrized from sample files
  under `tests/snippets/**` and `tests/examplefiles/**` by `tests/conftest.py`.
  Their nodeids are sample-file paths (e.g.
  `tests/snippets/python/test_floats.txt`), not `test_*.py` paths. They are now
  discovered and scheduled.
- The **16** that are not modelled are `skipped` tests: they execute no code,
  so they never emit a per-test coverage context (this is correct, not a gap).
  Two of them live in `tests/test_unistring.py`, which is the one *file* the
  coverage report flags as having no coverage — its tests need the optional
  `unistring` package, which the container image doesn't provide.

> **Why this matters.** Before pytest-driven discovery, the pipeline used a
> `tests/**/test_*.py` glob, which saw only **33** files and modelled **3,820**
> tests — every one of the 1,508 generated golden tests was invisible. For a
> change that touches a *lexer*, that glob-based graph would under-select. The
> fix (`per_test_analyzer.discover_collected_files`) plus a shard-level
> `--continue-on-collection-errors` (so a sample file pytest can't import as a
> Python module doesn't abort its shard) raises the model to the full suite.

**Quoting guidance.** State the reduction against the graph denominator
(`5,329`) and separately report the full-suite pass/fail from the controlled
regression (§5), which runs *all* 5,345 tests. That way the "we ran 5 tests"
claim is backed by "the other 5,340 all pass on this change".


---

## 4. Analyze the PR

This runbook's showcase change is

- PR: **https://github.com/hbahuguna/pygments/pull/1**
  (`tia/irc-unknown-color-fix` → `master`)
- head `325028ddde43c7ec8b908e1e6a09699e7d091dad`, base/merge-base
  `156d85fdd18d34427fe893527e71da91dcfb0eb5` (**= the anchor**, so evidence is
  fresh)
- files: `pygments/formatters/irc.py`, `tests/test_irc_formatter.py`

The change makes `ircformat()` tolerate a custom `colorscheme` that names a
color missing from `IRC_COLOR_MAP`, instead of raising `KeyError`.

```bash
cd apps/tia-agent
.venv/bin/python -m tia_agent analyze \
  --repo hbahuguna/pygments --pr 1 \
  --commit 156d85fdd18d34427fe893527e71da91dcfb0eb5 \
  --file-paths pygments/formatters/irc.py tests/test_irc_formatter.py \
  --json
```

Verified result (deterministic across repeated runs):

```json
{
  "symbols_selected": 5,
  "tests_selected": 5,
  "total_affected_tests": 5,
  "total_tests_in_repo": 5329,
  "impacted_ratio": 0.0009,
  "confidence": "high",
  "fallback_used": false,
  "stale_evidence": false,
  "evidence_built_at_sha": "156d85fdd18d34427fe893527e71da91dcfb0eb5"
}
```

Selected tests (each carries a full reason path and `high` confidence):

```
tests/test_cmdline.py::test_L_opt
tests/test_basic_api.py::test_formatter_unicode_handling[IRCFormatter]
tests/test_basic_api.py::test_formatter_public_api[IRCFormatter]
tests/test_irc_formatter.py::test_correct_output
tests/test_irc_formatter.py::test_linecount_output
```

Reduction: `(1 - 0.0009) * 100 ≈ 99.9%` — **5 of 5,329** modeled tests.
`safety_flag=false` (ratio well under the 0.30 cap).

Reasons (evidence-first path per test):

```
changed_symbol:ircformat@pygments/formatters/irc.py -> runtime_evidence -> <nodeid>
```

### 4a. Freshening / staleness checks

```bash
# Analyzing the PR head SHA (40-hex, != anchor) instead of the base:
.venv/bin/python -m tia_agent analyze --repo hbahuguna/pygments --pr 1 \
  --commit 325028ddde43c7ec8b908e1e6a09699e7d091dad \
  --file-paths pygments/formatters/irc.py --json \
  | jq '{stale_evidence, stale_evidence_reason, fallback_used}'
# -> stale_evidence=true, fallback_used=true  (TIA refuses to select on drifted evidence)
```

This is the fail-safe: drifted evidence never silently reduces the run.

---

## 5. Controlled regression — prove no misses

Building evidence is only half the story; the reduction must still *catch* a
real bug. Inject a deliberate regression into the changed symbol on a throwaway
branch, then compare the full suite against TIA's selection.

```bash
cd <checkout>
git checkout -b tia/irc-regression-check tia/irc-unknown-color-fix
# Break the color-code emission (off-by-one on every mapped colour):
sed -i '' 's/str(color_code).zfill(2)/str((color_code or 0) + 1).zfill(2)/' \
  pygments/formatters/irc.py

echo "=== FULL SUITE (what a naive CI runs) ==="
.venv/bin/python -m pytest tests/ -q --ignore=tests/contrast -p no:cacheprovider \
  | grep -E "^FAILED|passed|failed"
# -> FAILED tests/test_irc_formatter.py::test_correct_output
# -> FAILED tests/test_irc_formatter.py::test_linecount_output
# -> 2 failed, 5328 passed, 16 skipped in 25.59s

echo "=== TIA-SELECTED 5 (from §4) ==="
.venv/bin/python -m pytest -q -p no:cacheprovider \
  "tests/test_cmdline.py::test_L_opt" \
  "tests/test_basic_api.py::test_formatter_unicode_handling[IRCFormatter]" \
  "tests/test_basic_api.py::test_formatter_public_api[IRCFormatter]" \
  "tests/test_irc_formatter.py::test_correct_output" \
  "tests/test_irc_formatter.py::test_linecount_output" \
  | grep -E "^FAILED|passed|failed"
# -> 2 failed, 3 passed in 0.58s   (both failing tests are IN the selection)

git checkout -q tia/irc-unknown-color-fix && git branch -D tia/irc-regression-check
```

Result: the reduced set (5) is a **superset of the failing set (2)** →
**zero misses**, at **0.58s instead of 25.6s**.

---

## 6. Interpretation

- `total_tests_in_repo` (5,329) and `total_affected_tests` (5) share one unit
  (collected nodeids), so `impacted_ratio = 5/5329 = 0.0009` is internally
  consistent; the reduction is `(1 - impacted_ratio) * 100%`.
- `confidence=high` requires `symbols_selected > 0` **and** `tests_selected > 0`
  **and** no fallback; every selected test here carries runtime evidence
  (`high`), so no static-only `medium` caveat applies.
- `fallback_used=false` means the backend found real mappings for the changed
  symbol — not the "no evidence → run everything" path.
- The `tests/snippets` / `tests/examplefiles` golden tests **are** in the graph
  (1,508 of them, §3). They exercise lexers rather than the IRC formatter, so
  they don't appear in this selection, but for a change that touches a lexer
  they are now selectable evidence rather than an invisible blind spot.

## 7. Cleanup

```bash
git push fork --delete tia/irc-regression-check 2>/dev/null || true
# PR #1 stays: https://github.com/hbahuguna/pygments/pull/1
```
