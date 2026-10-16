# Runbook: Test Impact Analysis end-to-end (reproduce the accuracy improvements)

This is a **from-scratch, repeatable runbook** for running the entire TIA
pipeline on a repository and verifying the accuracy/trust improvements
(evidence coverage, method-level edges, commit-pinned freshness, per-test
reason + confidence, deterministic selection, no silent fallback, and the
shadow-validation miss gate).

Run it top to bottom on a clean machine. Every command is copy-pasteable and
uses a **worked example** — `hbahuguna/py-key-value` (project id `3`) — but the
parameters are all variables you can point at any repo.

> Time: ~20–40 min (most of it is the one-time instrumentation + testbed install).
> Cost: none — everything is local except cloning repos / hitting GitHub.

Legend: ✅ = checkpoint you must pass before continuing.

---

## 0. What you need

| Requirement | Notes |
| --- | --- |
| Docker Desktop | Runs the TestRadius backend (core-ml, Neo4j, Postgres). |
| `uv` | Fast, lock-faithful Python env for the testbed (`brew install uv`). |
| Python 3.10–3.13 | For the testbed venv (`uv` can fetch one). |
| Network | Cloning the target repo + installing its deps. |
| `jq`, `curl`, `git` | Inspection / API calls. |
| A repo with a `pytest` suite | Best-supported path. |

Use **two terminals**: **A** = control (run every command here unless noted —
the full-suite runs block the shell, that's expected); **B** = the long-running
licence server (§3). The backend (§2) starts detached so it can also live in A.

---

## 1. Configure the shell (Terminal A)

```bash
export ROOT="/Users/skaparwan/github/testradius"

# ---- target repo (edit these) --------------------------------------------
export REPO="hbahuguna/py-key-value"
export REPO_URL="https://github.com/hbahuguna/py-key-value.git"
export REPO_LANG="python"
export PRODUCT_DIR="src"                 # where product code lives (history corpus)
export PROJECT_ID="3"                     # py-key-value project id; create it in §4 if new
# --------------------------------------------------------------------------

export RADIUS="http://localhost:8000"
export LICENSE_URL="http://localhost:8100"
export ADMIN_TOKEN="dev-admin-token"
export AGENT="$ROOT/apps/tia-agent"
export AGENT_PY="$AGENT/.venv/bin/python"
export TIA_CONFIG_HOME="/tmp/tia-run-home"     # isolate agent state per run
mkdir -p "$TIA_CONFIG_HOME"
```

Reference values used by this runbook (verified on `74be46a`):

```bash
export TOTAL_TESTS=1308        # canonical suite size (distinct collected nodeids)
export STAMP="74be46a56ae99a8671460b730d42766d561127e3"   # evidence build commit
```

✅ `echo "$REPO $PROJECT_ID $RADIUS"`

---

## 2. Start the TestRadius backend (Terminal A)

```bash
cd "$ROOT"
[ -f .env ] || printf 'DEMO_MODE=1\n' > .env
grep -q '^DEMO_MODE=' .env || echo 'DEMO_MODE=1' >> .env     # auth bypass for local use
docker compose --profile ml up -d
```

`--profile ml` brings up `core-ml` (+ `db`, `neo4j`). `DEMO_MODE=1` makes the
agent work with an **empty** radius token while `curl` can still send
`Bearer dev-admin-token`.

Wait for health:

```bash
until curl -sf "$RADIUS/health" >/dev/null; do printf '.'; sleep 2; done; echo " backend OK"
curl -s "$RADIUS/health"; echo
```

✅ `testradius-core-ml-1` is `Up` and `/health` returns 200.

> Restart the backend after any `services/core/testsquad_core/**` edit:
> `docker compose --profile ml restart core-ml` (the source dir is bind-mounted).

---

## 3. Start the licence server + activate (Terminal B)

The agent's `analyze` gate calls `ensure_valid()` before doing any work, so the
licence server must be reachable and this machine activated.

```bash
cd "$ROOT/services/license"
# stop any previous instance
pkill -f "uvicorn license_server.app:app" 2>/dev/null || true
rm -f /tmp/tia-license.db

LICENSE_DATABASE_URL="sqlite:////tmp/tia-license.db" \
LICENSE_ADMIN_TOKEN="$ADMIN_TOKEN" \
LICENSE_RUNS_PER_PERIOD=500 \
LICENSE_GRACE_DAYS=3 \
.venv/bin/python -m uvicorn license_server.app:app --host 127.0.0.1 --port 8100
```

> `services/license/.venv` must exist (`ls services/license/.venv/bin/python`).
> If missing: `cd services/license && uv venv && uv pip install -e .`.

Leave it running. Back in **Terminal A**, issue a key and activate:

```bash
curl -s -X POST "$LICENSE_URL/v1/admin/licenses" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"runs_quota": 500}' | tee /tmp/tia-license.json
export LICENSE_KEY="$(python3 -c 'import json;print(json.load(open("/tmp/tia-license.json"))["license_key"])')"

cd "$AGENT"
TIA_CONFIG_HOME="$TIA_CONFIG_HOME" "$AGENT_PY" -m tia_agent activate --key "$LICENSE_KEY"
TIA_CONFIG_HOME="$TIA_CONFIG_HOME" "$AGENT_PY" -m tia_agent status
TIA_CONFIG_HOME="$TIA_CONFIG_HOME" "$AGENT_PY" -m tia_agent doctor
```

✅ `status` prints `"status": "valid"` and `doctor` prints `backend: OK`.

---

## 4. Ensure the project exists + features on

```bash
# Existing project id?
curl -s "$RADIUS/projects" | python3 -c '
import sys,json
name="'"$REPO"'"
m=[p["id"] for p in json.load(sys.stdin) if p["name"]==name]
print(m[0] if m else "")'
```

If empty, create it (name is unique):

```bash
curl -s -X POST "$RADIUS/projects" -H "Content-Type: application/json" \
  -d "{\"name\": \"$REPO\", \"description\": \"TIA e2e ($REPO)\"}" | tee /tmp/tia-project.json
export PROJECT_ID="$(python3 -c 'import json;print(json.load(open("/tmp/tia-project.json"))["id"])')"
```

Turn on the features the pipeline needs:

```bash
curl -s -X PUT "$RADIUS/projects/$PROJECT_ID/features" \
  -H "Content-Type: application/json" \
  -d '{"features": {"instrumentation": true, "test_mapping": true}}'; echo
```

✅ `PROJECT_ID` is a positive integer and the features call returns `status: ok`.

---

## 5. Instrument the repo — build symbol → test evidence

> Skip to §5b if you only want to *consume* existing evidence. Run this to
> (re)build evidence from scratch.

```bash
curl -N -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Token: ${TIA_GITHUB_TOKEN:-}" \
  -d "{\"repo_url\": \"$REPO_URL\", \"language\": \"$REPO_LANG\", \"run_fresh\": true}" \
  | tee /tmp/tia-instrumentation.sse
```

Watch for `status` events (`RESOLVING_SYMBOLS`, …) ending in
`{"event":"status","data":{"status":"COMPLETED","edges":<N>}}`. There must be
**no** `{"event":"error"}` line. This clones, installs, runs the suite, and
stores the EVIDENCE edges — it can take several minutes.

### 5b. Verify evidence (persistence D1, coverage C2, freshness D2)

```bash
# Persistence (D1): edges reported == edges stored
curl -s "$RADIUS/projects/$PROJECT_ID/instrumentation/coverage" | jq .
docker compose -f "$ROOT/docker-compose.yml" exec -T neo4j cypher-shell -u neo4j -p testsquad_password \
  "MATCH (:TestSymbol {project_id:$PROJECT_ID})-[e:EVIDENCE]->(:Symbol) RETURN count(e) AS evidence;"
```

Coverage fields: `test_files_expected`, `test_files_collectable`,
`test_files_instrumented`, `coverage_pct`, `missing_test_files`,
`low_coverage`/`warning` (when `< 95`). py-key-value expected:
`expected=52, collectable=31, instrumented=30, coverage_pct=96.8`.

```bash
# Freshness (D2): the single build SHA stamped on the test symbols
export STAMP="$(docker compose -f "$ROOT/docker-compose.yml" exec -T neo4j cypher-shell -u neo4j -p testsquad_password \
  "MATCH (ts:TestSymbol {project_id:$PROJECT_ID}) WHERE ts.built_at_sha IS NOT NULL \
   RETURN collect(DISTINCT ts.built_at_sha)[0];" 2>/dev/null | tail -n +2 | tr -d '"' | tr -d '\r')"
echo "anchor STAMP=$STAMP"
git ls-remote "$REPO_URL" HEAD
```

The stamped SHA is the **anchor** — use it as `commit_sha` for every analyze in
this runbook so evidence is fresh (`stale_evidence=false`). A drifted SHA forces
a full-suite fallback and makes the run vacuous. (The `$STAMP` in §1 was the
literal value for the py-key-value example; this query overrides it with the
real anchor for whatever project you instrumented.)

✅ The stamped SHA is a single value and matches the commit you will analyze.

---

## 6. Prepare the testbed (Terminal A) — to run the real suite

This gives you the ground truth (which tests actually fail) and lets the
shadow harness run. It must be checked out **at the evidence anchor**.

```bash
export TB="/tmp/tia-tb-$(date +%Y%m%d_%H%M%S)"
git clone --quiet "$REPO_URL" "$TB"
cd "$TB" && git checkout --quiet "$STAMP" && git rev-parse HEAD

# Reproducible env from the repo's lock
uv sync --python 3.11 --frozen        # creates ./.venv
```

Some repos pull in cloud/network test extras that hang on non-CI machines
(AWS/GCP clients + native DBs). If your suite stalls, remove the offenders and
force docker-gated tests to skip:

```bash
uv pip uninstall aioboto3 aiobotocore boto3 botocore s3transfer \
  google-cloud-firestore google-auth aerospike rocksdict duckdb pytz 2>/dev/null || true
```

Docker-gated integration tests auto-run when Docker is detected on macOS; set
`CI=true` to skip them deterministically.

Full-suite ground truth (py-key-value, clean env: ~77 s):

```bash
cd "$TB"
CI=true .venv/bin/python -m pytest tests/ -q \
  -p no:cacheprovider -p no:xdist -o addopts= \
  --continue-on-collection-errors --tb=no -rf | tail -3
# expected: 1884 passed, 2630 skipped, 4 errors, 0 failed
```

✅ The suite completes (record the pass/fail/error line — this is your oracle).

---

## 7. Inspect evidence quality (the graph-level improvements)

```bash
NEO="docker compose -f $ROOT/docker-compose.yml exec -T neo4j cypher-shell -u neo4j -p testsquad_password"

# (a) Canonical suite size + method-level coverage
$NEO "MATCH (ts:TestSymbol {project_id:$PROJECT_ID})-[:EVIDENCE]->(s:Symbol)
      RETURN count(DISTINCT ts) AS tests_mapped, count(DISTINCT s) AS symbols, count(*) AS edges;"
# py-key-value: 1308 tests, 223 symbols, 40295 edges

# (b) Product files with evidence (vs total src files)
$NEO "MATCH (t:TestSymbol {project_id:$PROJECT_ID})-[:EVIDENCE]->(s:Symbol)
      WHERE s.file_path STARTS WITH '$PRODUCT_DIR/'
      RETURN count(DISTINCT s.file_path) AS files_with_evidence;"
$NEO "MATCH (s:Symbol) WHERE s.file_path STARTS WITH '$PRODUCT_DIR/'
      RETURN count(DISTINCT s.file_path) AS total_files;"
# py-key-value: 36 of 73

# (c) Class-level (parent) edges must be 0 (method-level only)
$NEO "MATCH (t:TestSymbol {project_id:$PROJECT_ID})-[:EVIDENCE]->(s:Symbol)
      WHERE s.type='class' RETURN count(DISTINCT s) AS class_level_edges;"
# expected: 0  (baseline was 31)
```

✅ 1308 tests mapped, class-level edges = 0.

---

## 8. Run TIA — backend and agent

### 8a. Raw backend response (authoritative counts)

```bash
curl -s -X POST "$RADIUS/projects/$PROJECT_ID/analyze-pr" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "{\"full_name\":\"$REPO\",\"pr_number\":1,\"commit_sha\":\"$STAMP\",
       \"file_paths\":[\"$PRODUCT_DIR/key_value/aio/_utils/wait.py\"],\"max_symbols\":0}" \
  | jq '{symbols_selected, total_affected_tests, total_tests_in_repo, impacted_ratio,
         stale_evidence, truncated, tests_selected}'
```

> `max_symbols: 0` = no cap. **The default cap is 10** (§11); files with more
> risky symbols hit the safe full-suite fallback unless you raise it.

### 8b. Full product flow via the agent (per-test detail)

```bash
cd "$AGENT"
TIA_CONFIG_HOME="$TIA_CONFIG_HOME" "$AGENT_PY" -m tia_agent analyze \
  --repo "$REPO" --pr 1 --commit "$STAMP" \
  --file-paths "$PRODUCT_DIR/key_value/aio/_utils/wait.py" \
  --json | tee /tmp/tia-wait.json \
  | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("total_tests_in_repo :", d["total_tests_in_repo"])
print("total_affected_tests:", d["total_affected_tests"])
print("impacted_ratio      :", d["impacted_ratio"])
print("reduction           :", round((1-(d["impacted_ratio"] or 0))*100, 2), "%")
print("confidence / fallback:", d["confidence"], "/", d["fallback_used"])
print("owner sha           :", d["evidence_built_at_sha"], "| stale:", d["stale_evidence"])
for t in d["tests"]:
    print("  -", t["nodeid"], "|", t["confidence"])
    print("      reason:", t["reason"])
print("run_commands:", d["run_commands"])
'
```

Expected (fresh evidence): `total_tests_in_repo=1308`, `total_affected_tests=2`,
reduction ~99.85 %, `fallback=False`, and two tests each with a reason path
`changed_symbol:async_wait_for_true@…/wait.py -> runtime_evidence -> …::<test>`.

### 8c. Verify per-test reason + confidence (V2)

```bash
TIA_CONFIG_HOME="$TIA_CONFIG_HOME" "$AGENT_PY" -m tia_agent analyze \
  --repo "$REPO" --pr 1 --commit "$STAMP" \
  --file-paths "$PRODUCT_DIR/key_value/aio/_utils/retry.py" --json \
  | python3 -c '
import sys, json, collections
from tia_agent.output.schema import validate_output
d = json.load(sys.stdin)
opaque = [t for t in d["tests"] if not t.get("reason") or not t.get("confidence")]
path   = [t for t in d["tests"] if t["reason"].startswith("changed_symbol:")]
print("tests:", len(d["tests"]), "| opaque:", len(opaque), "| path-form:", len(path))
print("confidence mix:", dict(collections.Counter(t["confidence"] for t in d["tests"])))
print("schema errors:", validate_output(d))
'
# retry.py -> 77 tests, 0 opaque, path-form 77, schema errors: []
```

### 8d. Determinism (same inputs → identical set)

```bash
for i in 1 2; do
  TIA_CONFIG_HOME="$TIA_CONFIG_HOME" "$AGENT_PY" -m tia_agent analyze \
    --repo "$REPO" --pr 1 --commit "$STAMP" \
    --file-paths "$PRODUCT_DIR/key_value/aio/_utils/retry.py" --json \
  | python3 -c 'import sys,json; d=json.load(sys.stdin);
print(len(d["tests"]), d["impacted_ratio"], d["tests"][0]["nodeid"])'
done
```

✅ Two runs print identical lines.

### 8e. Fallback + truncation safety (never silently under-select)

```bash
# A file with > default-cap symbols -> truncation -> safe full-suite fallback
TIA_CONFIG_HOME="$TIA_CONFIG_HOME" "$AGENT_PY" -m tia_agent analyze \
  --repo "$REPO" --pr 1 --commit "$STAMP" \
  --file-paths "$PRODUCT_DIR/key_value/aio/stores/memory/store.py" --json \
  | python3 -c 'import sys,json; d=json.load(sys.stdin);
print("fallback:", d["fallback_used"]); print("reason:", d["fallback_reason"]);
print("affected/repo:", d["total_affected_tests"], "/", d["total_tests_in_repo"])'
# -> fallback=True, reason mentions "truncated ... dropped symbols with test mappings",
#    affected == repo (no reduction claimed)
```

✅ Fallback is reported with a reason; `total_affected_tests == total_tests_in_repo`.

---

## 9. Controlled regression — the end-to-end proof

This is the strongest demonstration: introduce a real bug into a symbol that has
evidence, run the **full suite** once (oracle), then let TIA pick the tests and
run **only those**.

### 9a. Inject a regression

```bash
cd "$TB"
# Pick any product symbol with evidence (see §7b). Example: async_wait_for_true
sed -i.bak 's/            return True/            return False/' \
  "$PRODUCT_DIR/key_value/aio/_utils/wait.py"
grep -n "return False" "$PRODUCT_DIR/key_value/aio/_utils/wait.py" \
  || echo "PATTERN NOT FOUND — open the file and flip a return/assert by hand"
git --no-pager diff --stat
```

> Tip: to make TIA's selection obvious, pick a symbol that only a *few* tests
> exercise (inspect `test-mapping?query=<file>` to see the fan-out first).

### 9b. Ground truth (full suite)

```bash
CI=true .venv/bin/python -m pytest tests/ -q \
  -p no:cacheprovider -p no:xdist -o addopts= \
  --continue-on-collection-errors --tb=no -rf | tail -3
# expected: 1 failed, 1883 passed, ...   (FAILED ...::test_async_wait_for_true_succeeds)
```

### 9c. TIA selection + run only the selected tests

```bash
cd "$AGENT"
TIA_CONFIG_HOME="$TIA_CONFIG_HOME" "$AGENT_PY" -m tia_agent analyze \
  --repo "$REPO" --pr 1 --commit "$STAMP" \
  --file-paths "$PRODUCT_DIR/key_value/aio/_utils/wait.py" --json \
  > /tmp/tia-wait.json
python3 -c 'import json; d=json.load(open("/tmp/tia-wait.json"));
print("TIA selected", len(d["tests"]), "of", d["total_tests_in_repo"], "tests");
[print(" -", t["nodeid"]) for t in d["tests"]]'

# Run EXACTLY what TIA selected (its canonical nodeids):
cd "$TB"
NODEIDS=$(python3 -c 'import json; d=json.load(open("/tmp/tia-wait.json"));
print(" ".join(t["nodeid"] for t in d["tests"]))')
CI=true .venv/bin/python -m pytest $NODEIDS \
  -q -p no:cacheprovider -o addopts= --tb=line -rf | tail -4
# expected: 2 selected -> 1 failed, 1 passed  (the regression is caught)
```

### 9d. Revert

```bash
cd "$TB" && mv "$PRODUCT_DIR/key_value/aio/_utils/wait.py.bak" \
  "$PRODUCT_DIR/key_value/aio/_utils/wait.py" && git status --porcelain
```

✅ 2/1308 tests run (99.85 % reduction) and the injected failure is **not
missed**.

---

## 10. Shadow validation — miss rate over a change corpus (V1)

Runs the full suite and TIA selection **on the same commit** for every change in
a corpus and asserts `selected ⊇ failing`. Stdlib-only; run it from the host.

```bash
cd "$ROOT"
export SV_PY="$TB/.venv/bin/python"     # any python3 works; use the testbed's
CI=true "$SV_PY" scripts/tia_agent/shadow_validate.py \
  --checkout "$TB" \
  --venv-python "$TB/.venv/bin/python" \
  --backend "$RADIUS" --token "$ADMIN_TOKEN" \
  --project-id "$PROJECT_ID" --full-name "$REPO" \
  --anchor-sha "$STAMP" \
  --corpus history --product-dir "$PRODUCT_DIR" \
  --max-prs 12 --min-prs 10 \
  --report /tmp/shadow-report.json
```

Prove the gate can fail (`--self-test` injects one attributable miss):

```bash
CI=true "$SV_PY" scripts/tia_agent/shadow_validate.py \
  --checkout "$TB" --venv-python "$TB/.venv/bin/python" \
  --backend "$RADIUS" --token "$ADMIN_TOKEN" \
  --project-id "$PROJECT_ID" --anchor-sha "$STAMP" \
  --corpus history --product-dir "$PRODUCT_DIR" --max-prs 12 --min-prs 10 \
  --report /tmp/shadow-selftest.json --self-test
```

Exit codes: **0** pass · **1** an attributable failing test was unselected ·
**2** harness error · **3** corpus < `--min-prs`. A miss only counts when the
failing test has a real EVIDENCE edge into a changed file, so environment-only
failures don't pollute the metric. On a clean env (no failures) the run exits 0
with `coverage: None`; the artifact capturing the historical 2-failure case lives
at `/tmp/shadow-report.json`.

✅ `missed: 0` (or `coverage: None` when the suite is green) and `exit: 0`.

---

## 11. Interpreting the results / what improved

| Metric | Baseline | After |
| --- | --- | --- |
| Product files with evidence | 2–3 | py-key-value: 36 / 73 |
| Test nodeids mapped | partial | 1308 / 1308 |
| Class-level evidence edges | 31 | **0** (method-level only) |
| Failing-test miss rate (shadow corpus) | unknown | **0** attributable missed; coverage 1.0 |
| Silent fallback when evidence exists | occurs | **0** — always a reason |
| Selection determinism | partial | **100 %** (identical repeats) |
| Truncated selections without signal | yes | **0** — surfaced + safe fallback |
| Selected tests without reason + confidence | some (`"runtime"`) | **0** (path-form reasons) |

- **Reduction** = `(1 − total_affected_tests / total_tests_in_repo) × 100 %`.
  Both use the same unit (distinct collected pytest nodeids).
- **Reason path** = `changed_symbol:<name>@<file> -> <source(s)> -> <test>`;
  sources are `runtime_evidence` (executed, `high`) and/or `static_import`
  (statically reached only, `medium`); fallback discovery is `low`.
- **Symbol cap**: default `max_symbols = 10` (`analysis/selection.py`). Any file
  with more risky symbols forces the full-suite fallback unless you pass
  `max_symbols: 0` (API) — the agent CLI cannot raise it. Lifting it for
  `memory/store.py` selects 1065/1308 (81.4 % reduction).
- **Freshness**: analyze at the stamped anchor, or the result is `stale_evidence`
  and falls back.

---

## 12. Teardown

```bash
cd "$ROOT"
docker compose --profile ml down          # add -v to wipe volumes
pkill -f "uvicorn license_server.app:app" 2>/dev/null || true
rm -rf "$TIA_CONFIG_HOME" "$TB" /tmp/tia-license.db /tmp/tia-*.json /tmp/tia-*.sse
```

---

## 13. Troubleshooting

- **`License server unreachable`** — §3 server not running or `TIA_CONFIG_HOME`
  differs between `activate` and `analyze`; `curl -s $LICENSE_URL/health`.
- **`No project matches`** — §4 name must equal `$REPO`; matching is exact
  name / basename / suffix.
- **`fallback_used=true` on a file you expect to work** — the file is beyond the
  symbol cap (pass `max_symbols: 0`) or has no evidence (check §7b; re-instrument
  §5).
- **Suite hangs** — a cloud/network test extra is installed; run the §6
  `uv pip uninstall ...` line and export `CI=true`.
- **`stale_evidence=true`** — your `commit_sha` ≠ the stamped anchor; re-read
  `$STAMP` in §5b.
- **Evidence is 0 edges** — instrumentation failed (native build deps); check the
  SSE stream for an `error` event and `docker compose logs -f core-ml`.
- **Port 8000 busy** — another checkout's `core` (profile `default`) is running;
  `docker compose --profile ml ps` and stop the clash.
- **`WARN ... "VITE_SUPABASE_URL" ... not set`** — harmless compose noise from the
  frontend env vars; commands still succeed. Append `2>/dev/null` when you only
  want stdout (as the §5b `STAMP` capture does).
- **`cypher-shell: error: unrecognized arguments: '-N'`** — `-N` is not a valid
  `cypher-shell` flag; to capture a single scalar use the default format and drop
  the header with `| tail -n +2` (see §5b).
