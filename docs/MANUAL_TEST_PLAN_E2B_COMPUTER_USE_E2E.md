# Manual E2E Test Plan — TestRadius Manual QA AI Harness (E2B + Gemini Computer-Use, LIVE)

> **Goal:** Manually execute the full harness **live** end-to-end like a real user —
> sandbox/template → MCP/manual context → normalized bundle → compiled plan (+ validation)
> → Gemini connection → E2B desktop primitives → spike → full computer-use runner
> → harness checkpoints/bug filing → safety/audit/metrics/evals — against
> `https://testradius.dev`, and record pass/fail evidence per story.
>
> **Live-only rule:** Every step below uses **real E2B + real Gemini** (where the step
> requires network/sandbox/model). No mock executors, no mocked proposals in the run
> path. Offline code-checks (file exists, `python -c "import …"`) are setup only.
> If a live step cannot run (missing key, template finalization failure, sandbox
> unreachable), mark it **BLOCKED (env)** with the exact error + evidence and stop
> downstream live steps that depend on it — do **not** substitute mocks to claim pass.

---

## 0. Test metadata (fill in before starting)

| Item | Value |
|---|---|
| Tester(s) | _e.g. Alex / QA_ |
| Date(s) | _YYYY-MM-DD_ |
| Branch/commit | _e.g. `main @ c1afb3f` (verify with `git log -1 --oneline`) |
| SUT | `https://testradius.dev` (staging) + fixtures below |
| E2B VM | `e2b-embed-9rnd` / project `marine-aria-504018-t8` / `us-west1-b` / static IP `8.231.230.69` |
| E2B services | API `:3000` · Dashboard `:3001` · Sandbox proxy `:3002` (`E2B_DOMAIN=8.231.230.69.nip.io:3002`) |
| Python venv | `apps/cell/.venv` (Python 3.12, pydantic 2.x, `google-genai` binary wheels) |
| Gemini model (configured) | `gemini-2.5-flash` (override via `GEMINI_COMPUTER_USE_MODEL`) |
| Gemini model (verified live) | _(record ID + date **only** after `test_gemini_connection.py` live probe passes)_ |
| Desktop template | `desktop-chromium` (2 CPU / 2048 MB) |
| Run prefix | `artifacts/manual-e2e-live-<YYYYMMDD>/` (all artifacts below are under this root) |

### Story coverage map (all live)

| Story | What this plan checks (live) | Primary scripts / code |
|---|---|---|
| 008.1 MCP intake | Jira/Figma/GitHub/demo → `context_bundle.json` (real normalizer code) | `scripts/normalize_context_bundle.py`, `harness/context/*`, `harness/integrations/mcp_context/*` |
| 008.2 Plan schema/gate | Golden plan passes live gate; vague/secret/draft-prod rejected | `scripts/validate_compiled_test_plan.py` |
| 008.3 Gemini compiler | Context → **live Gemini** → validated `compiled_test_plan.json` | `scripts/compile_test_plan.py --live` |
| 008.4 Spike + desktop | **Live** template build, Gemini probe, tiny-plan E2E in desktop sandbox | `scripts/build_e2b_desktop_template.py`, `scripts/test_gemini_connection.py`, `scripts/test_e2b_gemini_computer_use.py --live` |
| 008.5 Runner | Full golden plan **live** per-step (Option B) + trace/evidence | `scripts/run_computer_use_plan.py --live` |
| 008.6 Integration | **Live** executor factory, plan/bug checkpoints, findings, approval-gated filing | `scripts/run_computer_use_harness.py` (live when keys present) |
| 008.7 Safety/obs./evals | Live allowlist/domain/safety, injection guard, audit, metrics, evals | `evals/computer_use_eval.py`, safety/audit/metrics modules |
| 007 UI | Settings E2B validation + LiveRun E2B panel (live backend) | `apps/harness-ui/` |

---

## 1. Preconditions & environment checklist

### 1.1 Required tools / access

- [ ] Node 20+ / pnpm, Python 3.12, git, gcloud, curl.
- [ ] Self-hosted E2B Embed healthy: `e2b-embed-9rnd` reachable; dashboard/API/proxy responding. SSH (if needed, **never commit keys**):
  ```bash
  gcloud compute ssh e2b-embed-9rnd --zone=us-west1-b --project=marine-aria-504018-t8 --tunnel-through-iap
  ```
- [ ] Secrets available **only via env** (do **not** paste into repo/docs/artifacts/logs, do **not** `echo` them):
  - `E2B_API_KEY` (required for any live E2B)
  - `GEMINI_API_KEY` **or** `GOOGLE_API_KEY` (required for live Gemini)
  - `E2B_API_URL` (default `http://8.231.230.69:3000`), `E2B_DOMAIN=8.231.230.69.nip.io:3002`
  - Optional: `GEMINI_COMPUTER_USE_MODEL`, `E2B_DESKTOP_TEMPLATE=desktop-chromium`, `EXECUTOR_TYPE=gemini_computer_use`

  Presence check (never prints values):
  ```bash
  test -n "$E2B_API_KEY" && echo "E2B_API_KEY present" || echo "EID NOT set"
  test -n "$GEMINI_API_KEY" && echo "GEMINI_API_KEY present" || test -n "$GOOGLE_API_KEY" && echo "GOOGLE_API_KEY present" || echo "GEMINI key NOT set"
  ```
  **If either is NOT set, stop live execution** — request keys from the E2B/Gemini owner and return here. Do not proceed mocked.
- [ ] `google-genai` importable (live SDK):
  ```bash
  apps/cell/.venv/bin/python -c "import google.genai; print('google-genai OK')"
  ```
  If missing (e.g. `No module named 'google'`), install **binary wheels only** (source build fails on `x86_64` macOS due to Rust/`cryptography`):
  ```bash
  uv pip install --python apps/cell/.venv/bin/python --only-binary=:all: google-genai cryptography
  apps/cell/.venv/bin/python -c "import google.genai; print('google-genai OK')"
  ```
- [ ] Golden fixtures present:
  ```bash
  ls docs/examples/context_bundle.normalized.008.1.json \
     docs/examples/compiled_test_plan.008.3.sample.json \
     evals/fixtures/compiled_test_plan.valid.json \
     evals/fixtures/computer_use_tiny_plan.json \
     evals/fixtures/computer_use_eval_cases.json
  ```

### 1.2 Git & venv hygiene

```bash
cd /Users/skaparwan/github/testradius   # adjust to your clone root
git pull --ff-only; git log -1 --oneline; git status --short
apps/cell/.venv/bin/python --version
apps/cell/.venv/bin/python -c "import pydantic, google.genai; print('pydantic', pydantic.__version__)"
```

- **Expected:** clean tree on `main`, pydantic 2.x, `google-genai OK`. Record commit hash above.

### 1.3 Shell setup (run in every new terminal)

```bash
export PYTHONPATH="$PWD"
export E2B_API_URL="http://8.231.230.69:3000"
export E2B_DOMAIN="8.231.230.69.nip.io:3002"
export E2B_DESKTOP_TEMPLATE="desktop-chromium"
export EXECUTOR_TYPE="gemini_computer_use"
export GEMINI_COMPUTER_USE_MODEL="gemini-2.5-flash"
# Set live keys in shell only (never commit):
# export E2B_API_KEY="..."
# export GEMINI_API_KEY="..."   # or GOOGLE_API_KEY
export RUN_ROOT="artifacts/manual-e2e-live-$(date +%Y%m%d)"
mkdir -p "$RUN_ROOT" && echo "RUN_ROOT=$RUN_ROOT"
```

> **Pass/Fail (PHASE 0):** All fixture files exist, `google-genai OK`, both keys present, `RUN_ROOT` created. Note whether `E2B_DOMAIN` HTTP-proxy patch applies (non-default port `:3002` → `E2B_SECURE=false` behavior is internal to `E2BSandboxProvider`).

### 1.4 Jira setup (real project + tickets — required for Phase 1 live)

> Full guide: **`docs/JIRA_SETUP_E2E.md`**. Complete it before Phase 1 so you drive the harness with **real** tickets, not demo payloads.
> **Your instance (this E2E):** Site `https://testsquadai.atlassian.net` · Email `testsquad.ai@gmail.com` · Project key `KAN` · Starter ticket `KAN-1` (`/jira/browse/KAN-1`).

1. **Account + token:** Jira Cloud site above + API token (`JIRA_API_TOKEN`, env only). **Include `https://` in `JIRA_SITE`** — omitting it is why `curl … | python3 -m json.tool` previously returned `Expecting value: line 1 column 1` (empty/non-JSON redirect, not a JSON body). **Do not reuse any token pasted into chat/logs** — revoke it and export a fresh rotated value in shell only:
   ```bash
   export JIRA_SITE="https://testsquadai.atlassian.net"
   export JIRA_EMAIL="testsquad.ai@gmail.com"
   # export JIRA_API_TOKEN="..."  # NEW rotated token, shell only, never commit
   test -n "$JIRA_API_TOKEN" && echo "JIRA token present" || echo "JIRA token NOT set"
   ```
2. **Create project + tickets (UI):** Project key `KAN` (`TestRadius Manual QA`, Team-managed, Software template). `KAN-1` already exists — verify its summary/description still carry the `## Acceptance Criteria` header below; create 2 more tickets (mobile-nav edge, contact-form validation) with copy-paste content from `docs/JIRA_SETUP_E2E.md §3`. Each ticket **must** contain a `## Acceptance Criteria` header (the adapter extracts ACs only from that section):
   ```markdown
   ## Acceptance Criteria
   - Clicking primary CTA navigates to /contact
   - Form renders with name/email/message
   - Mobile viewport preserves CTA visibility
   Design: https://www.figma.com/file/demo123/Homepage?node-id=10-20
   ```
   Labels/components: `smoke,homepage,web` (Ticket 1); `mobile,edge` (Ticket 2); `validation,negative` (Ticket 3).
3. **Verify `KAN-1` via REST (show HTTP status, not just JSON):**
   ```bash
   curl -s -o /tmp/jira-KAN-1.json -w "HTTP %{http_code}\n" \
     -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -H "Accept: application/json" \
     "$JIRA_SITE/rest/api/3/issue/KAN-1?fields=*all"
   cat /tmp/jira-KAN-1.json | python3 -m json.tool | head -100
   ```
   - **Expected:** `HTTP 200`; `key=KAN-1`, `fields.summary` set, `fields.description` (ADF) containing the AC bullets + a `figma.com` link. If `HTTP 401` → re-export rotated token (Cloud = Basic `email:token`); `HTTP 404` → re-check browse URL `https://testsquadai.atlassian.net/jira/browse/KAN-1`; empty body → re-check `https://` prefix.
4. **Record** in §0: Jira site `https://testsquadai.atlassian.net`, account `testsquad.ai@gmail.com`, project key `KAN`, issue keys (`KAN-1` + any you add). Never record the token.

> **Pass/Fail (PHASE 0.5):** `KAN` project exists; `KAN-1` (plus follow-ups) carry `## Acceptance Criteria` headers; REST fetch returns `HTTP 200` for `KAN-1`.

---

## 2. Ground rules (live-only)

1. **No mocks in the run path.** `MockComputerUsePrimitives` / `MockGeminiComputerUseClient` must **not** be used. Every live run uses `--live` (compiler/spike/runner) or keyed env (harness integration), and `metadata.mock=false` semantics (executor auto-selects live when both keys present).
2. **Sandbox gets plan only.** Live sandbox receives **only** `compiled_test_plan.json` + minimal runtime config. If any run uploads raw Jira/Figma/PRD payloads, **FAIL** the phase (§12 G9).
3. **Run IDs unique.** Use `run-live-<phase>-<n>`. Never reuse a prior `run-<id>` dir.
4. **No secrets in evidence.** Before sharing artifacts, `grep -rE 'sk-|AIza|ghp_' "$RUN_ROOT" || echo clean` — remove/redact any hit. Traces must show `[REDACTED]`.
5. **Stop on red.** Capture exact command + stderr, open a defect (§14), mark phase BLOCKED/FAIL. Do **not** fall back to mock to claim pass.
6. **Keep run dirs per phase** under `$RUN_ROOT/`:
   ```
   $RUN_ROOT/
     01-mcp/context_bundle.json
     02-compile/run-live-compile-001/compiled_test_plan.json
     03-gemini/probe.txt
     04-template/spec.json + build.log
     05-spike/run-live-spike-001/
     06-runner/run-live-runner-001/
     07-harness/run-live-harness-001/
     08-evals/computer-use-eval.json (copy of evals/reports/)
     09-guardrails/
   ```

---

## 3. Phase 1 — MCP Context Intake (008.1, live, Jira-only)

**Real-Jira-only (no demo merge):** the E2E bundle must contain **only** your ticket `KAN-1` (`https://testsquadai.atlassian.net/jira/browse/KAN-1`, `testradius signup with google`). Demo values (`QA-812`, `demo123`, `web#128`, CTA/`data-testid` ACs) must **not** appear. You achieve this with `--jira-file /tmp/jira-KAN-1.json --jira-only` (or `fetch_jira_context.py`, which is Jira-only by definition).

### Steps
1. **(Required, live) Normalize your real ticket → bundle (Jira-only):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/normalize_context_bundle.py \
     --jira-file /tmp/jira-KAN-1.json --jira-only \
     --out "$RUN_ROOT/01-mcp/context_bundle.json" 2>&1 | tee "$RUN_ROOT/01-mcp/stdout.txt"
   ```
   - **Expected:** `ticket_id=KAN-1`, `source_types=[jira]`, `acceptance_criteria_count=2`, `provenance_adapters=[mcp.jira]`:
     ```json
     ["Clicking “Signup with Google” shows Google account chooser",
     "No error on valid chooser selection"]
     ```
   - **Fallback (if `/tmp/jira-KAN-1.json` is stale):** re-fetch it first (see §1.4 step 3), or fetch directly:
     ```bash
     PYTHONPATH=. apps/cell/.venv/bin/python scripts/fetch_jira_context.py \
       --jira-url "$JIRA_SITE" --issue-key KAN-1 \
       --out "$RUN_ROOT/01-mcp/context_bundle.json"
     ```
     Both produce the identical Jira-only bundle; values never written include tokens.
2. **Verify real bundle shows only KAN-1 values:**
   ```bash
   python3 - <<'PY'
   import json, pathlib
   d = json.loads(pathlib.Path("artifacts/manual-e2e-20261106/01-mcp/context_bundle.json").read_text())
   # NOTE: use the literal path (or $RUN_ROOT via os.environ); single-quoted '$RUN_ROOT' never expands.
   assert d["ticket_id"] == "KAN-1", d["ticket_id"]
   assert [s["source_type"] for s in d["source_refs"]] == ["jira"]
   assert len(d["acceptance_criteria"]) == 2, d["acceptance_criteria"]
   assert "Signup with Google" in " ".join(d["acceptance_criteria"])
   assert not any("data-testid" in a or "demo123" in str(u) for a in d["acceptance_criteria"] for u in d["figma_links"])
   print("real Jira bundle OK:", d["title"], "| ACs:", d["acceptance_criteria"])
   PY
   ```
   - **Expected:** prints `testradius signup with google` + the 2 Google ACs. No `QA-812`/`demo123`/`data-testid` strings anywhere in the bundle.
3. **Multi-source merge (optional):** only add **real** Figma/GitHub payloads via `ContextIntake` (guide §6) and overwrite the same file. Provenance must list each real tool. Never append demo mocks.

**Pass (P1):** `context_bundle.json` has `ticket_id=KAN-1` with **exactly** the 2 Google ACs, `source_types=[jira]`, no demo values; redaction holds (no token-shaped values).

---

## 4. Phase 2 — Live Gemini Compile + Validate (008.3 → 008.2)

### Steps
1. **Live compile (real Gemini → validated plan):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/compile_test_plan.py \
     --context "$RUN_ROOT/01-mcp/context_bundle.json" \
     --out-dir "$RUN_ROOT/02-compile" --run-id run-live-compile-001 \
     --base-url https://testradius.dev --mode local_spike --live 2>&1 | tee "$RUN_ROOT/02-compile/stdout.txt"
   ```
   - **Expected:** `ok=true`, `artifact_path=$RUN_ROOT/02-compile/run-live-compile-001/compiled_test_plan.json`. Requires `GEMINI_API_KEY` + `google-genai`. Record latency + model from stdout.
2. **Verify saved plan (contract):**
   ```bash
   python3 - <<'PY'
   import json, pathlib
   d = json.loads(pathlib.Path("$RUN_ROOT/02-compile/run-live-compile-001/compiled_test_plan.json").read_text())
   assert d["schema_version"] == "1.0.0"
   assert d["sut"]["base_url"] == "https://testradius.dev"
   assert "testradius.dev" in d["constraints"]["allowed_domains"]
   assert d["cases"][0]["steps"][0]["success_criteria"]
   assert d["generator"]["prompt_version"] == "testplan-compiler-v1"
   print("live compiled plan OK; model =", d["generator"].get("model"))
   PY
   ```
3. **Quality-gate regimes (validator, no mock execution needed — validator is the gate):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/validate_compiled_test_plan.py 2>&1 | tee "$RUN_ROOT/02-compile/validator.txt"
   ```
   - **Expected:** valid/`local_spike` passes; draft/`production` blocked (`review_not_approved`); invalid/vague/secret rejected (`inline_secret`, `vague_success_criteria`, etc.).

> If live compile fails on SDK/network, you are blocked for live phases. Fix env (keys/SDK) — do **not** fall back to mock compile and claim P2 pass.

**Pass (P2):** Live `ok=true` with validated artifact; three validator regimes observed.

---

## 5. Phase 3 — Gemini Connection (008.4.2, live probe)

```bash
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_gemini_connection.py 2>&1 | tee "$RUN_ROOT/03-gemini/probe.txt"
```

- **Required (live):** `sdk: google-genai import OK` + `live probe: OK — … COMPUSE_OK …` within seconds. Then record verified model + date in §0.
- **Blocked (env) if:** `key present: False` or SDK missing or probe `FAILED` — fix keys/SDK and re-run; record error in `probe.txt`.

**Pass (P3):** Probe `OK`. No secret in `probe.txt` (`grep -c "$GEMINI_API_KEY"`-style check is manual — just verify file contains no token).

---

## 6. Phase 4 — Live E2B Desktop Template (008.4.1)

### Steps
1. **Spec (offline inspection):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/build_e2b_desktop_template.py --dry-run 2>&1 | tee "$RUN_ROOT/04-template/spec.json"
   ```
   - **Expected:** `alias=desktop-chromium`, `cpu=2`, `memory_mb=2048`, `apt` includes `xvfb,xdotool,scrot,chromium`, `DISPLAY=:99`.
2. **Live build (requires `E2B_API_KEY`):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/build_e2b_desktop_template.py 2>&1 | tee "$RUN_ROOT/04-template/build.log"
   ```
   - **Expected:** `Build finished: …`. **Finalization may fail on self-hosted Embed** — retry once. If still failing, mark **BLOCKED (env)** with the exact log attached; do **not** proceed to live spike/runner on a broken template.
3. **Verify resources:** Confirm the build actually requested 2 CPU/2048 MB (build log). Reject `base`/512 MB for GUI runs.

**Pass (P4):** Spec correct; live build succeeded (or BLOCKED with log). Do not start live sandbox runs until this passes.

---

## 7. Phase 5 — Live Spike: Tiny Compiled Plan (008.4.3)

```bash
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_e2b_gemini_computer_use.py --live \
  --plan evals/fixtures/computer_use_tiny_plan.json \
  --artifacts-dir "$RUN_ROOT/05-spike" --run-id run-live-spike-001 2>&1 | tee "$RUN_ROOT/05-spike/stdout.txt"
```

- **Expected:** sandbox created (ID printed), desktop started via `~/start-desktop.sh`, `COMPLETED` (2/2 steps) with `spike_report.json` + `CU1-S1/S2_before/after.png` under `$RUN_ROOT/05-spike/run-live-spike-001/`. Sandbox killed at teardown (verify no orphans in dashboard/API).
- **Primitives in trace:** `screenshot`, `navigate`, `move`/`click`, `type`/`keypress`, `scroll`, `wait` — each recorded with validation.

> **Live budget:** Each `--live` spike/runner call creates a real sandbox + Gemini vision calls. Keep `max_steps=3` for spike; expect 30–120s wall time depending on network/template cold-start.

**Pass (P5):** Live `COMPLETED` + screenshots + report. If sandbox/Gemini error, record BLOCKED with log — do not substitute mock.

---

## 8. Phase 6 — Live Full Runner (008.5)

```bash
PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_plan.py --live \
  --plan evals/fixtures/compiled_test_plan.valid.json \
  --artifacts-dir "$RUN_ROOT/06-runner" --run-id run-live-runner-001 \
  --mode local_spike --loop per_step 2>&1 | tee "$RUN_ROOT/06-runner/stdout.txt"
```

- **Expected:** `COMPLETED`, `loop=per_step`. Artifacts:
  ```
  run-live-runner-001/
    compiled_test_plan.json   action_trace.jsonl
    C1-S1_attempt1_before.png  C1-S1_attempt1_after.png
    C1-S2_attempt1_before.png  C1-S2_attempt1_after.png
    C1-S3_attempt1_before.png  C1-S3_attempt1_after.png
    step_results.json  run_summary.json
  ```
- **Audit check:**
  ```bash
  PYTHONPATH=. apps/cell/.venv/bin/python - <<'PY'
  from pathlib import Path
  from harness.computer_use.audit import validate_trace_file
  print(validate_trace_file(Path("$RUN_ROOT/06-runner/run-live-runner-001/action_trace.jsonl")))
  PY
  ```
  - **Expected:** `{"ok": true, ...}`. And `grep -c source_refs …/action_trace.jsonl` must be **0**.
- **Option A check (optional):** re-run with `--loop whole_plan` on a throwaway `run-live-runner-002` and confirm progress labels it “Option A (non-default)”. Do not treat A as the shipping default.

**Pass (P6):** Live `COMPLETED` (or reasoned `BLOCKED`/`FAILED` with trace — a product fail is still a valid live execution if screenshots/trace prove it; an env error is BLOCKED, not pass).

---

## 9. Phase 7 — Live Harness Integration (008.6)

> With both keys exported, `ComputerUseExecutor` automatically selects the **live** path. `metadata.mock=true` must **not** be set.

### Steps
1. **Factory names (live-capable):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python - <<'PY'
   from harness.execution.factory import ExecutorFactory
   from harness.execution.base import ExecutorConfig
   import json
   plan = json.loads(open("evals/fixtures/compiled_test_plan.valid.json").read())
   for et in ("gemini_computer_use", "compiled_plan"):
       cfg = ExecutorConfig(run_id=f"run-live-factory-{et}", target_url=plan["sut"]["base_url"], plan=plan, artifacts_dir="artifacts/manual-e2e-live-verify")
       ex = ExecutorFactory.create_executor(cfg, et)
       print(et, type(ex).__name__, ex._use_mock())
   PY
   ```
   - **Expected:** both `ComputerUseExecutor`, `mock=False` (both keys present).
2. **Live integration run (checkpoints + findings + bug review):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_harness.py \
     --artifacts-dir "$RUN_ROOT/07-harness" --run-id run-live-harness-001 2>&1 | tee "$RUN_ROOT/07-harness/stdout.txt"
   ```
   - **Expected:** `run_report.json` + `manifest.json` + `findings.json` (each: `step_id`, `expected`, `observed`, `screenshots`, `trace_excerpt`, `source_refs`) + `plan_checkpoint.json` + `checkpoint_log.json` + `bug_review_package.json`/`bug_report.md` (`approved=false`). To get a guaranteed finding, first confirm `assess_pass=false` behavior? No — live findings depend on real execution; if all steps pass, findings may be empty (also valid — record “no findings, execution passed”). Use `--approve-bug` only after reviewing the package in a browser/editor:
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/computer_use/tests/test_integration.py -v
   # confirms filing blocked before approval (PermissionError) and dry_run after
   ```
   - **Expected:** prod-draft block verified (no `action_trace.jsonl` when blocked), filing blocked → dry-run draft.
3. **Approval-gated live filing (if findings exist):**
   ```bash
   # Review bug_review_package.json + screenshots FIRST, then:
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_harness.py \
     --artifacts-dir "$RUN_ROOT/07-harness" --run-id run-live-harness-002 --approve-bug 2>&1 | tee "$RUN_ROOT/07-harness/stdout-approve.txt"
   ```
   - **Expected:** `{"filed": "dry_run", "approved": true}` — no real GitHub issue unless `dry_run=False` is deliberately set with a repo + `gh` CLI (do **not** do this in this manual plan).

**Pass (P7):** Live `run_report` + manifest + findings + bug review present; filing blocked before approval.

---

## 10. Phase 8 — Live Safety / Observability / Evals (008.7)

### Steps
1. **Unit safety/metrics (offline code, validates live gates):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/computer_use/tests/test_safety_metrics.py harness/computer_use/tests/test_runner.py -v
   ```
   - **Expected:** allowlist/domains/bounds, injection detect + guard fragment, audit schema, auditable trace + metrics, injected domain blocked — all pass.
2. **Live evals (seeded variants still exercise live code paths; mock detector is the eval harness, not the run path):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python evals/computer_use_eval.py 2>&1 | tee "$RUN_ROOT/08-evals/stdout.txt"
   cp evals/reports/computer-use-eval.json "$RUN_ROOT/08-evals/computer-use-eval.json"
   ```
   - **Expected:** 3 cases × 3 repeats (`cu-golden-pass` → pass, `cu-seeded-layout` → `fail_product`, `cu-agent-block` → `blocked`), `flake_rate=0.0`.
3. **Docs skim:** `docs/COMPILED_TEST_PLAN_SPEC.md`, `docs/E2B_GEMINI_COMPUTER_USE.md`, `docs/MCP_CONTEXT_INTAKE.md`, `docs/E2B_GEMINI_COMPUTER_USE_SPIKE.md` — confirm executor names, artifact list, BLOCKED causes match your observations.

**Pass (P8):** Tests green; eval report matches expected seeded outcomes; `grep -rE 'sk-|AIza|ghp_' "$RUN_ROOT" || echo clean`.

---

## 11. Phase 9 — UI (007, live backend)

1. **Start UI + API** (per `docs/E2B_MANUAL_QA_HARNESS.md`):
   ```bash
   cd apps/harness-ui && pnpm install && pnpm dev
   # harness API in another terminal (harness/api/app.py) with live env exported
   ```
2. **Settings:** executor options include **Local / Cloud Room / E2B**; system config JSON visible; “Validate E2B Connection” returns checks + not-persisted warning (no sandbox creation).
3. **Live Run:** open a `*e2b*` run ID → **E2B Sandbox** panel shows sandbox ID, template, executor status, artifacts link; polling updates.

**Pass (P9):** Both pages as above against live backend.

---

## 12. Negative / guardrail matrix (live where applicable)

| # | Attack / misuse | Command / fixture | Required result |
|---|---|---|---|
| G1 | Vague assertions | `scripts/validate_compiled_test_plan.py` | Rejected (`vague_success_criteria`) |
| G2 | Inline secret | Mutate golden `input.password` → validate | Rejected (`inline_secret`) |
| G3 | Draft in prod | Live harness run `mode=production` + draft plan | `BLOCKED`, **no** `action_trace.jsonl` |
| G4 | Out-of-domain navigate | Live/inject evil-domain proposal | `blocked`, never executed in sandbox |
| G5 | Destructive w/o approval | `destructive=true` step | Validator error |
| G6 | Secret ref w/o resolver | `{{secret.X}}` | `blocked=True`, `[REDACTED_SECRET]` |
| G7 | Prompt injection | Page “ignore rules” text | Detected; evil action **blocked** by domain gate |
| G8 | File w/o approval | `file_after_approval` before approve | `PermissionError` |
| G9 | Raw context in sandbox | `grep source_refs …/action_trace.jsonl` (live runner) | **0 hits** |

---

## 13. Result recording & sign-off

| Phase | Result (P/F/B) | Evidence paths | Notes |
|---|---|---|---|
| 0 Pre-flight | | `$RUN_ROOT/` + §0 | |
| 1 MCP intake | | `$RUN_ROOT/01-mcp/` | |
| 2 Live compile+validate | | `$RUN_ROOT/02-compile/` | |
| 3 Gemini live probe | | `$RUN_ROOT/03-gemini/probe.txt` | |
| 4 Template build | | `$RUN_ROOT/04-template/` | |
| 5 Live spike | | `$RUN_ROOT/05-spike/run-live-*/` | |
| 6 Live runner | | `$RUN_ROOT/06-runner/run-live-*/` | |
| 7 Live integration | | `$RUN_ROOT/07-harness/run-live-*/` | |
| 8 Safety/evals | | `$RUN_ROOT/08-evals/` | |
| 9 UI | | screenshots / notes | |
| 12 Guardrails G1–G9 | | §12 table | |

**Overall verdict:** ☐ **GO** (P1–P8 all live pass) ☐ **NO-GO** (list failing phases).

### Evidence index
- [ ] `$RUN_ROOT/01-mcp/context_bundle.json`
- [ ] `$RUN_ROOT/02-compile/run-live-compile-001/compiled_test_plan.json` (+ validator regime log)
- [ ] `$RUN_ROOT/03-gemini/probe.txt` (verified model + date)
- [ ] `$RUN_ROOT/04-template/spec.json` + `build.log`
- [ ] `$RUN_ROOT/05-spike/run-live-spike-001/spike_report.json` + screenshots
- [ ] `$RUN_ROOT/06-runner/run-live-runner-001/{action_trace.jsonl,run_summary.json,step_results.json}`
- [ ] `$RUN_ROOT/07-harness/run-live-*/{manifest,run_report,findings,bug_report}.json/md` + `bug_filing_audit.json`
- [ ] `$RUN_ROOT/08-evals/computer-use-eval.json`

### Cleanup
```bash
# Confirm no orphaned live sandboxes (dashboard/API), keep $RUN_ROOT for audit
# git status — do NOT commit $RUN_ROOT (artifacts/ policy); verify before exit
```

---

## 14. Defect log template

```markdown
### DEFECT-<n>: <title>
- **Phase/step:** P<> / <>
- **Command (live):** `<exact>`
- **Expected:** <> **Actual:** <>
- **Evidence:** `$RUN_ROOT/<...>/...`
- **Severity:** P0/P1/P2 · **Retest:** re-run live command after fix
```

---

## 15. Quick-reference (live-only)

```bash
export PYTHONPATH="$PWD"
export E2B_API_URL="http://8.231.230.69:3000" E2B_DOMAIN="8.231.230.69.nip.io:3002"
export E2B_DESKTOP_TEMPLATE="desktop-chromium" EXECUTOR_TYPE="gemini_computer_use"
export GEMINI_COMPUTER_USE_MODEL="gemini-2.5-flash"
# export E2B_API_KEY="..." GEMINI_API_KEY="..."   # live keys, shell only
export RUN_ROOT="artifacts/manual-e2e-live-$(date +%Y%m%d)"; mkdir -p "$RUN_ROOT"

# P1 normalize (Jira-only real ticket, no demo merge)
PYTHONPATH=. apps/cell/.venv/bin/python scripts/normalize_context_bundle.py --jira-file /tmp/jira-KAN-1.json --jira-only --out "$RUN_ROOT/01-mcp/context_bundle.json"
# P2 live compile + gate
PYTHONPATH=. apps/cell/.venv/bin/python scripts/compile_test_plan.py --context "$RUN_ROOT/01-mcp/context_bundle.json" --out-dir "$RUN_ROOT/02-compile" --run-id run-live-compile-001 --base-url https://testradius.dev --mode local_spike --live
PYTHONPATH=. apps/cell/.venv/bin/python scripts/validate_compiled_test_plan.py
# P3-P5 live
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_gemini_connection.py
PYTHONPATH=. apps/cell/.venv/bin/python scripts/build_e2b_desktop_template.py --dry-run
PYTHONPATH=. apps/cell/.venv/bin/python scripts/build_e2b_desktop_template.py
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_e2b_gemini_computer_use.py --live --plan evals/fixtures/computer_use_tiny_plan.json --artifacts-dir "$RUN_ROOT/05-spike" --run-id run-live-spike-001
# P6-P7 live
PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_plan.py --live --plan evals/fixtures/compiled_test_plan.valid.json --artifacts-dir "$RUN_ROOT/06-runner" --run-id run-live-runner-001 --mode local_spike --loop per_step
PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_harness.py --artifacts-dir "$RUN_ROOT/07-harness" --run-id run-live-harness-001
PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_harness.py --artifacts-dir "$RUN_ROOT/07-harness" --run-id run-live-harness-002 --approve-bug
# P8
PYTHONPATH=. apps/cell/.venv/bin/python evals/computer_use_eval.py && cp evals/reports/computer-use-eval.json "$RUN_ROOT/08-evals/"
```

---

*End of plan. Execute top-to-bottom; check each ✅ box and file evidence as you go. When every phase is P (live pass), sign off in §13 and link the run dir to the release/merge evidence.*
