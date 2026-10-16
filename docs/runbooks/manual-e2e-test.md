# Manual End-to-End Test: `tia-agent` on a New Repo

This runbook walks you, by hand, through a complete end-to-end test of the
`tia-agent` binary against a **brand-new repository** you have never registered
with TestRadius before.

You will verify, in order:

1. The binary builds and runs standalone.
2. A license can be issued, activated, and enforced (E1).
3. A new repo can be registered as a TestRadius project.
4. Instrumentation collects per-test symbol evidence for the new repo (E4).
5. `tia-agent analyze` returns the impacted tests for a real PR (E2/E3).
6. Exactly one run is metered per successful analysis (E2).

Work through the sections top to bottom. Each section ends with a **Checkpoint**
that must pass before continuing.

> **Time**: ~15–30 min (most of it is instrumentation + your repo's install).
> **Cost**: none — everything runs locally except cloning your repo and, if you
> use one, the GitHub API.

---

## 0. What you need

| Requirement | Notes |
| --- | --- |
| Docker Desktop | For the TestRadius backend (core + Neo4j + Postgres). |
| Network access | To clone your repo and install its deps inside the backend container. |
| A GitHub repo **you own** that has tests | Python (`pytest`) is the best-supported path. |
| An open (or merged) **PR** in that repo | You will analyze it. |
| `gh` CLI (optional) | Only to mint a GitHub token / find a PR number. |
| A GitHub token (optional) | Only needed for **private** repos or when the backend must fetch PR files. |

The binary is macOS/Linux. This runbook assumes the repo is checked out at
`$ROOT` (default: `/Users/skaparwan/github/testradius`).

---

## 1. Set up your shell

Open **three terminals**. In **Terminal A** (control) export the shared
variables:

```bash
export ROOT="/Users/skaparwan/github/testradius"

# ---- EDIT THESE -----------------------------------------------------------
export REPO="OWNER/REPO"                       # the NEW repo, e.g. acme/widgets
export REPO_URL="https://github.com/OWNER/REPO.git"
export PR="1"                                  # an open/merged PR number
export REPO_LANG="python"                      # python | typescript | playwright
# ---------------------------------------------------------------------------

export RADIUS="http://localhost:8000"
export LICENSE_URL="http://localhost:8100"
export ADMIN_TOKEN="dev-admin-token"
export TIA="$ROOT/apps/tia-agent/dist/tia-agent"
```

Optionally authenticate GitHub so the backend/binary can fetch PR files and
clone private repos (never print the token):

```bash
export TIA_GITHUB_TOKEN="$(gh auth token)"     # optional
```

**Checkpoint**

```bash
echo "$REPO  pr#$PR  lang=$REPO_LANG"
```

---

## 2. Start the TestRadius backend

In **Terminal B**:

```bash
cd "$ROOT"
```

The backend needs a `.env` file (the compose service mounts it). The **only**
variable required to bypass auth for a local test is `DEMO_MODE`:

```bash
# Create .env if it does not exist. Do NOT commit real secrets.
[ -f .env ] || printf 'DEMO_MODE=1\n' > .env
grep -q '^DEMO_MODE=' .env || echo 'DEMO_MODE=1' >> .env
```

Start core (ML profile) + Neo4j + Postgres:

```bash
docker compose --profile ml up -d
```

> `--profile ml` starts `core-ml`, `neo4j` and `db`. The plain `core` service
> (profile `default`) is intentionally **not** started, so there is no port
> clash.

Wait for health, then confirm:

```bash
until curl -sf "$RADIUS/health" >/dev/null; do printf '.'; sleep 2; done; echo " backend OK"
docker compose ps
```

**Checkpoint**: `curl -s $RADIUS/health` returns a healthy JSON body, and
`testradius-core-ml-1` is `Up`.

> If port 8000 is already used by another checkout, pick different host ports in
> `docker-compose.yml` and set `RADIUS` accordingly.

---

## 3. Start the license server and issue a license

The license server issues keys and is the **meter** (each successful analysis
records one run here). Start it in **Terminal B** (a second tab) or a third
terminal:

```bash
cd "$ROOT/services/license"
rm -f /tmp/tia-e2e-license.db                # fresh meter for a clean test

LICENSE_DATABASE_URL="sqlite:////tmp/tia-e2e-license.db" \
LICENSE_ADMIN_TOKEN="$ADMIN_TOKEN" \
LICENSE_RUNS_PER_PERIOD=500 \
LICENSE_GRACE_DAYS=3 \
.venv/bin/python -m uvicorn license_server.app:app --host 127.0.0.1 --port 8100
```

> Uses the license service's own venv (`services/license/.venv`). Confirm it
> exists with `ls services/license/.venv/bin/python`; if missing, create it
> with `uv venv` and `uv pip install -e services/license` first.

In **Terminal A**, issue a key:

```bash
curl -s -X POST "$LICENSE_URL/v1/admin/licenses" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"runs_quota": 500}' | tee /tmp/tia-license.json
```

Extract and save the key:

```bash
export LICENSE_KEY="$(python3 -c 'import json;print(json.load(open("/tmp/tia-license.json"))["license_key"])')"
echo "LICENSE_KEY=$LICENSE_KEY"
```

**Checkpoint**: `/tmp/tia-license.json` contains a `license_key`.

---

## 4. Build the `tia-agent` binary

In **Terminal A**:

```bash
cd "$ROOT/apps/tia-agent"
./scripts/build_binary.sh
```

This creates `.venv-build`, runs PyInstaller, and smoke-tests the result under a
clean environment. When done:

```bash
export TIA="$ROOT/apps/tia-agent/dist/tia-agent"
"$TIA" --version
```

> **Shortcut**: if you already published/downloaded a release, set `TIA` to that
> binary and skip this step. Verify with `"$TIA" --version`.

**Checkpoint**: `"$TIA" --version` prints `tia-agent 0.1.0`.

---

## 5. Point the binary at the services and activate

Defaults already match local ports, but be explicit. In **Terminal A**:

```bash
export TIA_RADIUS_URL="$RADIUS"
export TIA_LICENSE_URL="$LICENSE_URL"
export TIA_CONFIG_HOME="/tmp/tia-e2e-home"   # isolate state for this test
mkdir -p "$TIA_CONFIG_HOME"
```

Activate:

```bash
"$TIA" activate --key "$LICENSE_KEY"
```

Expected:

```
Activated. subscription=active quota_remaining=500
```

Confirm:

```bash
"$TIA" status        # prints JSON; exit code 0 only when status == "valid"
"$TIA" doctor
```

`status` prints e.g.:

```json
{"status": "valid", "subscription_status": "active", "quota_remaining": 500}
```

`doctor` prints:

```
docker: OK
license: {'status': 'valid', 'subscription_status': 'active', 'quota_remaining': 500}
backend: OK at http://localhost:8000
projects: N registered
done.
```

**Checkpoint**: `status` reports `"status": "valid"`, and `doctor` reports the
backend `OK`.

---

## 6. Register your new repo as a TestRadius project

`analyze` resolves a repo to a **project by name**, so the project must exist
before instrumenting. The binary has no "create project" command; use the API.
In **Terminal A**:

```bash
curl -s -X POST "$RADIUS/projects" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"$REPO\", \"description\": \"Manual E2E ($REPO)\"}" \
  | tee /tmp/tia-project.json

export PROJECT_ID="$(python3 -c 'import json;print(json.load(open("/tmp/tia-project.json"))["id"])')"
echo "PROJECT_ID=$PROJECT_ID"
```

Enable instrumentation for it:

```bash
curl -s -X PUT "$RADIUS/projects/$PROJECT_ID/features" \
  -H "Content-Type: application/json" \
  -d '{"features": {"instrumentation": true}}'
```

**Checkpoint**: `PROJECT_ID` is a positive integer, and the second call returns
`{"status": "ok", "features": {"instrumentation": true}}`.

> Project `name` is unique. If you re-run this on an existing project you will
> get a uniqueness error; reuse the existing id instead:
> `PROJECT_ID=$(curl -s $RADIUS/projects | python3 -c 'import sys,json;print([p["id"] for p in json.load(sys.stdin) if p["name"]=="'"$REPO"'"][0])')`

---

## 7. Instrument the new repo (build symbol evidence)

Instrumentation clones the repo inside the backend container, installs it,
runs its test suite, and records which tests execute which product symbols.
This is what makes `analyze` return real answers instead of a fallback.

In **Terminal A** (this **streams** progress and can take several minutes):

```bash
curl -N -X POST "$RADIUS/projects/$PROJECT_ID/instrumentation/run" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Token: ${TIA_GITHUB_TOKEN:-}" \
  -d "{\"repo_url\": \"$REPO_URL\", \"language\": \"$REPO_LANG\", \"run_fresh\": true}"
```

> The `X-GitHub-Token` header is only needed for private repos. An empty value
> is ignored by the backend.

Watch the streamed lines for the clone, venv creation, pytest run, and mapping
storage. For a **Python** repo the pipeline:

- clones `$REPO_URL`,
- creates a venv inside the container and installs the package,
- runs the suite,
- computes per-test coverage for the **3 smallest test files** (a deliberate
  cost cap), storing **repo-relative** product paths.

> **Python install failures**: the container runs `pip install -e .` plus common
> extras. If your repo needs a toolchain not in the image (e.g. native libs),
> instrumentation will report errors. See Troubleshooting §14.
>
> **TypeScript / Playwright**: these need the repo mounted at
> `TESTRADIUS_LOCAL_PATH` (`/testradius`). Either use `docker compose` with an
> extra mount, or `tia-agent backend up --repo "$PWD"`. For a first run, prefer a
> Python repo.

**Checkpoint**: the stream ends with a success status and no error. The final
event looks like:

```
data: {"event": "status", "data": {"status": "COMPLETED", "edges": 41}}
```

There must be **no** `{"event": "error", ...}` line. `edges` is the number of
symbol↔test edges stored. Then the evidence is queryable:

```bash
curl -s "$RADIUS/projects/$PROJECT_ID/test-mapping?limit=1000" | head -c 500; echo
```

Each entry has `product_symbol`, `product_file`, `test_symbol`, `test_file` and
`confidence`. Count them:

```bash
curl -s "$RADIUS/projects/$PROJECT_ID/test-mapping?limit=1000" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print("entries:", len(d))'
```

---

## 8. Identify the PR's changed files

You need the list of files the PR changed so the analysis can scope symbols.

**Option A — let the binary/backend fetch them** (needs `TIA_GITHUB_TOKEN` or a
backend `GITHUB_TOKEN`). Just run §9 without `--file-paths`.

**Option B — pass them explicitly** (works offline, fully deterministic):

```bash
# Space-separated paths, relative to the repo root. EDIT these:
export FILES=(src/your/module.py tests/test_your_module.py)
```

**Checkpoint**: either a valid token is exported, or `FILES` lists real
repo-relative paths touched by PR #$PR.

---

## 9. Run the analysis with the binary

This is the actual product flow. In **Terminal A**:

```bash
"$TIA" analyze --repo "$REPO" --pr "$PR" \
  --file-paths "${FILES[@]}" \
  --json | tee /tmp/tia-result.json
```

> Omit `--file-paths "${FILES[@]}"` to let the agent fetch the PR's changed files
> from GitHub (requires `TIA_GITHUB_TOKEN`).
>
> `--file-paths` takes **space-separated** values (it is an argparse `nargs="*"`
> option), e.g. `--file-paths a.py b.py`, not `a.py,b.py`.

Expected output (shape):

```json
{
  "schema_version": "1.0",
  "repo": "OWNER/REPO",
  "pr_number": 1,
  "files_analyzed": 1,
  "changed_files": ["src/your/module.py"],
  "symbols_selected": 3,
  "tests_selected": 1,
  "total_affected_tests": 1,
  "fallback_used": false,
  "confidence": "medium",
  "tests": [ {"name": "test_thing", "file": "tests/test_your_module.py", "...": "..."} ],
  "run_commands": ["pytest tests/test_your_module.py::test_thing"],
  "tia_run_id": "…",
  "notes": []
}
```

**Checkpoint**:

- `"files_analyzed"` ≥ 1.
- `"fallback_used"` is `false` and `"tests"` is **non-empty** → real evidence was
  used.
- If `"fallback_used"` is `true` or `"tests"` is empty, the changed paths had no
  recorded coverage. Pick a changed file whose symbols are exercised by one of
  the instrumented tests (see §14).

You can also run the conversational REPL for the same test:

```bash
"$TIA"          # then: analyze OWNER/REPO 1
```

> On first run the REPL may ask you to pick an LLM provider. You can press
> **Enter** to skip it — analysis does not require an LLM key.

---

## 10. Verify metering (one run counted)

Each **successful** analysis records exactly one run against the license. Query
the license server's SQLite meter directly:

```bash
sqlite3 /tmp/tia-e2e-license.db \
  "SELECT COUNT(*) || ' run(s), ' || COUNT(DISTINCT run_id) || ' distinct run_id' FROM runs;"
```

**Checkpoint**: after one successful analysis you see `1 run(s), 1 distinct run_id`.
Run §9 again → `2 run(s), 2 distinct run_id`.

Now confirm a **failure is not counted**:

```bash
# A repo with no registered project and explicit files (so GitHub is not hit):
"$TIA" analyze --repo "ghost/nope" --pr 1 --file-paths README.md || true

sqlite3 /tmp/tia-e2e-license.db "SELECT COUNT(*) FROM runs;"
```

**Checkpoint**: the count is unchanged (failed/unresolved analyses are never
metered).

Finally, confirm the license reflects the usage:

```bash
"$TIA" status        # prints JSON: {"status":"valid",...,"quota_remaining":N}
```

**Checkpoint**: `quota_remaining` decreased by the number of successful runs.

---

## 11. (Optional) Enforce the quota

Prove the gate works by starving the quota:

```bash
# Issue a 1-run license and activate it.
curl -s -X POST "$LICENSE_URL/v1/admin/licenses" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" -d '{"runs_quota": 1}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["license_key"])' > /tmp/tiny.key

"$TIA" activate --key "$(cat /tmp/tiny.key)"
"$TIA" analyze --repo "$REPO" --pr "$PR" --file-paths "${FILES[@]}"   # run #1 OK
"$TIA" analyze --repo "$REPO" --pr "$PR" --file-paths "${FILES[@]}"   # blocked
```

**Checkpoint**: the second call exits non-zero with a quota/blocked message and
no run is recorded.

---

## 12. Teardown

```bash
cd "$ROOT"
docker compose --profile ml down          # add -v to wipe volumes
# Stop the license server with Ctrl-C in its terminal.
rm -rf /tmp/tia-e2e-home /tmp/tia-e2e-license.db /tmp/tia-*.json /tmp/tiny.key
```

---

## 13. What "pass" looks like (checklist)

- [ ] `"$TIA" --version` → `tia-agent 0.1.0`.
- [ ] `"$TIA" activate` → `subscription=active`.
- [ ] `"$TIA" doctor` → backend `OK`.
- [ ] Project created + `instrumentation=true`.
- [ ] Instrumentation stream completes; evidence is queryable.
- [ ] `"$TIA" analyze` → non-empty `tests`, `fallback=false`.
- [ ] Meter shows 1 run per successful analysis; failures add 0.
- [ ] `quota_remaining` decrements in lockstep.

---

## 14. Troubleshooting

**`No TestRadius project matches 'OWNER/REPO'`**
The project name must match the repo. Matching is by exact name, repo basename,
or suffix. Redo §6 with `"name"` set to exactly `$REPO`.

**`analyze` returns `fallback=true` / empty `tests`**
The PR's changed files weren't covered by the instrumented tests. Remember only
the **3 smallest test files** are instrumented. Choose a PR file that one of
those tests exercises. Inspect evidence via the `test-mapping` route (§7).

**Instrumentation errors during install (Python)**
The container installs the package with a fixed recipe. Repos needing native
build deps or unusual packaging can fail. First try a simpler repo (a small
library with a plain `pyproject.toml`/`setup.py` and a normal `pytest` suite).

**Instrumentation stream is silent for a long time**
Cloning + `pip install` + running the whole suite can take minutes. It is not
hung; watch `docker compose logs -f core-ml` in another terminal.

**Backend health fails / port 8000 busy**
Another checkout's `core` (profile `default`) may be running. `docker compose
--profile ml ps`, stop the conflicting stack, or remap host ports.

**TypeScript/Playwright repos produce no evidence**
They require the repo mounted at `TESTRADIUS_LOCAL_PATH`. Start the backend via
`tia-agent backend up --repo "$PWD"` (or add the mount in `docker-compose.yml`)
and re-run §7 with `language` = `typescript`/`playwright`.

**Binary can't reach the license server**
Ensure `$TIA_LICENSE_URL` is exported in the same shell as `"$TIA"`, and that the
uvicorn process is still running. `curl -s $LICENSE_URL/health` should succeed.

**Full agent test suite hangs (developer note)**
When running the Python test suite (not the binary) on a network-restricted
machine, real GitHub calls block for the HTTP timeout. Force fast failures:
`HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 NO_PROXY=127.0.0.1,localhost`.
