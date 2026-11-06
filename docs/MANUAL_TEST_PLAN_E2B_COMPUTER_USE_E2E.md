# Manual E2E Test Plan — TestRadius Manual QA AI Harness (E2B + Gemini Computer-Use)

> **Goal:** Manually execute the full harness end-to-end — from sandbox/template
> discovery → MCP/manual context → normalized bundle → compiled plan (+ validation)
> → Gemini connection → E2B desktop primitives → spike → full computer-use runner
> → harness checkpoints/bug filing → safety/audit/metrics/evals — against
> `https://testradius.dev`, and record pass/fail evidence per story.
>
> **Primary path:** `EPIC-E2B-008` (008.1–008.7). Mock paths prove offline
> correctness; **live paths** (`--live`) require self-hosted E2B + Gemini keys
> and are environment-dependent. Where live is not available, complete the mock
> steps and mark live steps as **BLOCKED (env)** with evidence (see §13).

---

## 0. Test metadata (fill in before starting)

| Item | Value |
|---|---|
| Tester(s) | _e.g. Alex / QA_ |
| Date(s) | _YYYY-MM-DD_ |
| Branch/commit | _e.g. `main @ 2cc527d` (verify with `git log -1 --oneline`) |
| SUT | `https://testradius.dev` (staging) + fixtures below |
| E2B VM | `e2b-embed-9rnd` / project `marine-aria-504018-t8` / `us-west1-b` / static IP `8.231.230.69` |
| E2B services | API `:3000` · Dashboard `:3001` · Sandbox proxy `:3002` (`E2B_DOMAIN=8.231.230.69.nip.io:3002`) |
| Python venv | `apps/cell/.venv` (Python 3.12, pydantic 2.x) |
| Gemini model (configured) | `gemini-2.5-flash` (override via `GEMINI_COMPUTER_USE_MODEL`) |
| Gemini model (verified live) | _(record ID + date **only** after `test_gemini_connection.py` live probe passes)_ |
| Run prefix | `artifacts/manual-e2e-<YYYYMMDD>/` (all artifacts below are under this root unless noted) |

### Story coverage map

| Story | What this plan checks | Primary scripts / code |
|---|---|---|
| 008.1 MCP intake | Jira/Figma/GitHub/manual → `context_bundle.json` | `scripts/normalize_context_bundle.py`, `harness/context/*`, `harness/integrations/mcp_context/*` |
| 008.2 Plan schema/gate | Golden plan passes; vague/secret/draft-prod rejected | `scripts/validate_compiled_test_plan.py`, `harness/testplan/{schema,validator}.py` |
| 008.3 Gemini compiler | Context → validated `compiled_test_plan.json` (mock; live when keyed) | `scripts/compile_test_plan.py`, `harness/testplan/compiler.py` |
| 008.4 Spike + desktop | Template spec/build, Gemini probe, tiny-plan E2E with screenshots | `scripts/build_e2b_desktop_template.py`, `scripts/test_gemini_connection.py`, `scripts/test_e2b_gemini_computer_use.py` |
| 008.5 Runner | Full golden plan, per-step loop (Option B), trace/evidence, guardrails | `scripts/run_computer_use_plan.py`, `harness/computer_use/runner.py` |
| 008.6 Integration | Executor factory, plan/bug checkpoints, findings, approval-gated filing | `scripts/run_computer_use_harness.py`, `harness/execution/computer_use.py`, `harness/computer_use/integration.py` |
| 008.7 Safety/obs./evals | Allowlist/domain/destructive, injection guard, audit, metrics, evals | `evals/computer_use_eval.py`, `harness/computer_use/{safety,audit,metrics}.py` |
| 007 UI (spot-check) | Settings executor + E2B validation; live E2B panel | `apps/harness-ui/src/pages/SettingsPage.tsx`, `LiveRunPage.tsx` |

---

## 1. Preconditions & environment checklist

### 1.1 Required tools / access

- [ ] Machine with **Node 20+ / pnpm** (UI), **Python 3.12** (harness), **git**, **gcloud** (VM ops), **curl**.
- [ ] Self-hosted E2B Embed healthy (operator-confirmed): `e2b-embed-9rnd` reachable; dashboard/API/proxy responding. SSH (if needed, **never commit keys**):
  ```bash
  gcloud compute ssh e2b-embed-9rnd --zone=us-west1-b --project=marine-aria-504018-t8 --tunnel-through-iap
  ```
- [ ] Secrets available **only via env** (do **not** paste into repo/docs/artifacts/logs):
  - `E2B_API_KEY` (required for any live E2B)
  - `GEMINI_API_KEY` **or** `GOOGLE_API_KEY` (required for live Gemini)
  - `E2B_API_URL` (default `http://8.231.230.69:3000`), `E2B_DOMAIN=8.231.230.69.nip.io:3002`
  - Optional: `GEMINI_COMPUTER_USE_MODEL`, `E2B_DESKTOP_TEMPLATE=desktop-chromium`, `EXECUTOR_TYPE=gemini_computer_use`
- [ ] `google-genai` importable in the venv (needed for live compiler/Gemini paths; mock paths work without it):
  ```bash
  apps/cell/.venv/bin/python -c "import google.genai; print('google-genai OK')"
  ```
  If this fails, note **“SDK missing — mock only”** and continue with mocks; live steps become BLOCKED (env). Do **not** install `cryptography` wheels on broken toolchains blindly — file a defect instead.
- [ ] Golden fixtures present ( Spot-check):
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
git pull --ff-only && git log -1 --oneline && git status --short
apps/cell/.venv/bin/python --version
apps/cell/.venv/bin/python -c "import pydantic; print(pydantic.__version__)"
```

- **Expected:** clean tree on `main`, pydantic 2.x. Record commit hash above.
- **Do not stage/commit** secret-bearing files. `pnpm-lock.yaml` and local `artifacts/` (untracked) are expected to exist — leave them alone.

### 1.3 Shell setup (run in every new terminal)

```bash
export PYTHONPATH="$PWD"
export E2B_API_URL="http://8.231.230.69:3000"
export E2B_DOMAIN="8.231.230.69.nip.io:3002"
export E2B_DESKTOP_TEMPLATE="desktop-chromium"
export EXECUTOR_TYPE="gemini_computer_use"
export GEMINI_COMPUTER_USE_MODEL="gemini-2.5-flash"
# Only if you have live keys — do NOT echo/commit these:
# export E2B_API_KEY="..."
# export GEMINI_API_KEY="..."   # or GOOGLE_API_KEY
export RUN_ROOT="artifacts/manual-e2e-$(date +%Y%m%d)"
mkdir -p "$RUN_ROOT" && echo "RUN_ROOT=$RUN_ROOT"
```

> **Pass/Fail (PHASE 0):** All fixture files exist, pydantic OK, `RUN_ROOT` created. Record whether live keys/SDK are present (mock-only vs live-capable).

---

## 2. Ground rules (read once)

1. **Mock first, live second.** For every `--live` step, first run the safe mock twin and confirm green. Live is incremental proof, not a substitute for mock.
2. **Run IDs are unique.** Use `run-manual-<phase>-<n>` (e.g. `run-manual-mcp-001`). Never reuse a prior `run-<id>` dir without clearing it.
3. **Sandbox gets plan only.** Live sandbox must receive **only** `compiled_test_plan.json` + minimal runtime config. If a run uploads raw Jira/Figma/PRD payloads, **FAIL** the phase (§12).
4. **No secrets in evidence.** Before committing/sharing artifacts, grep for token shapes (`sk-`, `ghp_`, `AIza`, `password=`) and remove. Redacted traces must show `[REDACTED]`.
5. **Stop on red.** If a step fails, capture the exact command + stderr, open a defect (§14), and continue only if the plan says safe to skip (usually: mark phase BLOCKED and move on).
6. **Keep run dirs per phase.** Structure under `$RUN_ROOT/`:
   ```
   $RUN_ROOT/
     01-mcp/context_bundle.json          # 008.1
     02-compile/compiled_test_plan.json  # 008.3
     03-gemini/                          # 008.4.2 probe notes
     04-template/                        # 008.4.1 dry-run / build log
     05-spike/run-*/                     # 008.4.3 (tiny plan)
     06-runner/run-*/                    # 008.5 (golden full run)
     07-harness/run-*/                   # 008.6 (integration + bug review)
     08-evals/computer-use-eval.json     # 008.7 (copied from evals/reports/)
     09-guardrails/                      # 008.7 negative proofs
   ```

---

## 3. Phase 1 — MCP Context Intake (008.1)

**Objective:** Prove mocked Jira/Figma/GitHub/manual payloads normalize into a safe, provenance-rich `ContextBundle` and save as `context_bundle.json`.

### Steps
1. **Run demo normalization (mocked sources):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/normalize_context_bundle.py \
     --out "$RUN_ROOT/01-mcp/context_bundle.json"
   ```
   - **Expected:** stdout JSON with `ticket_id=QA-812`, `source_types=[jira, figma, github, manual]`, `acceptance_criteria_count` ≥ 5, `provenance_adapters=[mcp.jira, mcp.figma, mcp.github, manual]` (order may vary), `redacted=false`.
2. **Verify bundle content:**
   ```bash
   python3 - <<'PY'
   import json, pathlib
   p = pathlib.Path("$RUN_ROOT/01-mcp/context_bundle.json")
   d = json.loads(p.read_text())
   assert d["ticket_id"] == "QA-812"
   assert any(s["source_type"] == "jira" for s in d["source_refs"])
   assert any(s["source_type"] == "figma" for s in d["source_refs"])
   assert any("figma.com/file/demo123" in str(u) for u in d["figma_links"])
   assert d["provenance"]["adapters"]
   print("bundle OK:", d["title"])
   PY
   ```
   - **Expected:** prints `bundle OK: Homepage hero CTA routes to contact form`.
3. **Verify library directly (MCP/Jira/Figma/GitHub/manual adapters + fallback + redaction):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/integrations/mcp_context/tests/ -v
   ```
   - **Expected:** all tests pass (manual text sections, Jira mapping, Figma frames, GitHub AC, docs adapter, merged provenance, MCP-unavailable fallback, mocked MCP resource, secret redaction, compiler-input JSON-safe).

### Evidence to capture
- Save stdout to `$RUN_ROOT/01-mcp/stdout.txt` (re-run with `| tee` or redirect).
- Keep `$RUN_ROOT/01-mcp/context_bundle.json` (compare with committed `docs/examples/context_bundle.normalized.008.1.json`).

**Pass criteria (P1):** Exit 0; bundle has all four source types + provenance; tests green. **Fail:** missing provenance, secrets in bundle, or fallback crashes.

---

## 4. Phase 2 — Compile + Validate (008.3 → 008.2)

**Objective:** Prove normalized context compiles into a validated `CompiledExecutionTestPlan` and the quality gate rejects bad plans.

### Steps
1. **Validate golden plan (schema + quality gate):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/validate_compiled_test_plan.py
   ```
   - **Expected:** valid/`local_spike` passes; draft/`production` blocked (`review_not_approved`); invalid/vague/secret rejected (codes include `inline_secret`, `missing_target`/`invalid_target`, `missing_allowed_domains`, `vague_success_criteria`, `missing_evidence`, `missing_preconditions`).
2. **Compile from 008.1 bundle (mocked Gemini, offline-safe):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/compile_test_plan.py \
     --context "$RUN_ROOT/01-mcp/context_bundle.json" \
     --out-dir "$RUN_ROOT/02-compile" --run-id run-manual-compile-001
   ```
   - **Expected:** `ok=true`, `validation.ok=true`, `artifact_path=$RUN_ROOT/02-compile/run-manual-compile-001/compiled_test_plan.json` with `generator.prompt_version=testplan-compiler-v1`, `review_status=draft`.
3. **Inspect saved plan (contract):**
   ```bash
   python3 - <<'PY'
   import json, pathlib
   p = pathlib.Path("$RUN_ROOT/02-compile/run-manual-compile-001/compiled_test_plan.json")
   d = json.loads(p.read_text())
   assert d["schema_version"] == "1.0.0"
   assert d["sut"]["base_url"] == "https://testradius.dev"
   assert "testradius.dev" in d["constraints"]["allowed_domains"]
   assert d["cases"][0]["steps"][0]["success_criteria"]
   assert d["generator"]["prompt_version"] == "testplan-compiler-v1"
   print("compiled plan OK")
   PY
   ```
4. **Compiler unit tests (validate/repair loop with mocked Gemini):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/testplan/tests/test_compiler.py harness/testplan/tests/test_compiled_test_plan.py -v
   ```
   - **Expected:** valid compile+save, repair loop (invalid → good), bounded failure, fenced JSON, env-ref preservation — all pass.

> **Live compiler (optional):** `scripts/compile_test_plan.py --live` requires `GEMINI_API_KEY` + `google-genai`. Record model + date; output must still pass the same gate. If SDK/key missing, mark **BLOCKED (env)** — do not fail the phase.

**Pass criteria (P2):** Mock compile exits 0 with validated artifact; validator demo shows exactly the three regimes above; compiler tests green.

---

## 5. Phase 3 — Gemini Connection (008.4.2)

**Objective:** Prove env/SDK detection and (live) model probe **without ever printing key values**.

```bash
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_gemini_connection.py | tee "$RUN_ROOT/03-gemini/probe.txt"
```

- **Mock/offline expected:** `key present: False` (or True if you exported a key), `sdk: google-genai not importable…` (or OK), `result: SKIP-live …`.
- **Live expected:** `live probe: OK — … COMPUSE_OK …` within a few seconds. Then **record** the verified model + date in §0 table (`GEMINI_COMPUTER_USE_MODEL` value + `date -u +%Y-%m-%d`).

**Pass criteria (P3):** Script exits cleanly in both modes; no secret leaked (check `probe.txt` contains no key substring). Live probe OK is required only for live phases; otherwise note BLOCKED (env).

---

## 6. Phase 4 — E2B Desktop Template (008.4.1)

**Objective:** Prove the `desktop-chromium` template spec (X11 + browser + input) at **2 CPU / 2048 MB** and the `~/start-desktop.sh` startup contract.

### Steps
1. **Inspect spec (always safe):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/build_e2b_desktop_template.py --dry-run | tee "$RUN_ROOT/04-template/spec.json"
   ```
   - **Expected:** JSON with `alias=desktop-chromium`, `cpu=2`, `memory_mb=2048`, `apt` includes `xvfb,xdotool,scrot,chromium`, `env.DISPLAY=:99`, `self_hosted_constraints.E2B_DOMAIN` set.
2. **Live build (only if `E2B_API_KEY` set):**
   ```bash
   export E2B_API_KEY="..."  # env only
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/build_e2b_desktop_template.py 2>&1 | tee "$RUN_ROOT/04-template/build.log"
   ```
   - **Expected:** `Build finished: …`, then `~/start-desktop.sh` + browser/toolchain checks OK. **Finalization may fail on self-hosted Embed** — retry once; if still failing, record the exact error, mark **BLOCKED (env)** and continue with runtime-bootstrap note (Playwright path proved the workaround; desktop needs the same discipline).
3. **Resource guardrail (manual):** Confirm the build request really was `cpu_count=2`, `memory_mb=2048` (build log/console). Do **not** accept `base`/512 MB for GUI runs (Chromium OOM risk).

**Pass criteria (P4):** Dry-run spec correct; live build succeeded **or** explicitly blocked with build log attached.

---

## 7. Phase 5 — Spike Runner: Tiny Compiled Plan (008.4.3)

**Objective:** Execute a 2-step plan end-to-end (screenshot → propose → validate → execute → evidence) and prove E2B connectivity primitives.

### Mock (always)
```bash
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_e2b_gemini_computer_use.py \
  --plan evals/fixtures/computer_use_tiny_plan.json \
  --artifacts-dir "$RUN_ROOT/05-spike" --run-id run-manual-spike-001 2>&1 | tee "$RUN_ROOT/05-spike/stdout.txt"
```

- **Expected:** `COMPLETED`, 2/2 steps `PASSED`, `RECORDED` evidence under `$RUN_ROOT/05-spike/run-manual-spike-001/`:
  ```
  compiled_test_plan.json  spike_report.json
  CU1-S1_before.png  CU1-S1_after.png
  CU1-S2_before.png  CU1-S2_after.png
  ```

### Live (only with §5/§6 green)
```bash
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_e2b_gemini_computer_use.py --live \
  --plan evals/fixtures/computer_use_tiny_plan.json \
  --artifacts-dir "$RUN_ROOT/05-spike" --run-id run-manual-spike-live-001
```
- **Expected:** sandbox created (ID printed), desktop started, `COMPLETED`/`BLOCKED`/`FAILED` with `spike_report.json` + screenshots; sandbox killed at teardown (no orphans: check dashboard/sandbox list empty afterward).

**Primitives to confirm in trace:** `screenshot`, `navigate`, `move`/`click`, `type`/`keypress`, `scroll`, `wait` — each recorded in `MockComputerUsePrimitives.actions` (mock) or `action_trace.jsonl` (live).

**Pass criteria (P5):** Mock `COMPLETED` + screenshots + report. Live `COMPLETED` (or reasoned `BLOCKED` with log) when env allows.

---

## 8. Phase 6 — Full Computer-Use Runner (008.5)

**Objective:** Run the **golden full plan** (3 steps vs `https://testradius.dev`) via the structured per-step loop (Option B), with action trace + summaries.

### Steps
1. **Mock run (golden plan, per-step):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_plan.py \
     --plan evals/fixtures/compiled_test_plan.valid.json \
     --artifacts-dir "$RUN_ROOT/06-runner" --run-id run-manual-runner-001 \
     --mode local_spike --loop per_step 2>&1 | tee "$RUN_ROOT/06-runner/stdout.txt"
   ```
   - **Expected:** `COMPLETED` (or `FAILED`/`BLOCKED` only if mock script dictates — default mock must be `COMPLETED`), `loop=per_step`. Artifacts:
     ```
     run-manual-runner-001/
       compiled_test_plan.json   action_trace.jsonl
       C1-S1_attempt1_before.png  C1-S1_attempt1_after.png
       C1-S2_attempt1_before.png  C1-S2_attempt1_after.png
       C1-S3_attempt1_before.png  C1-S3_attempt1_after.png
       step_results.json  run_summary.json
     ```
2. **Verify audit completeness:**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python - <<'PY'
   from pathlib import Path
   from harness.computer_use.audit import validate_trace_file
   print(validate_trace_file(Path("$RUN_ROOT/06-runner/run-manual-runner-001/action_trace.jsonl")))
   PY
   ```
   - **Expected:** `{"ok": true, ...}` — every attempt carries proposed + validation + executed + observation (see `harness/computer_use/audit.py`).
   - **Additionally:** `grep -c source_refs $RUN_ROOT/06-runner/run-manual-runner-001/action_trace.jsonl` must be **0** (no raw context in sandbox trace).
3. **Runner tests (retries/fallback/classification):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/computer_use/tests/test_runner.py -v
   ```
   - **Expected:** golden per-step+evidence, ref resolution, domain-block classification, retry/fallback, whole-plan labeling — all pass.

### Live variant
```bash
PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_plan.py --live \
  --artifacts-dir "$RUN_ROOT/06-runner" --run-id run-manual-runner-live-001 --mode local_spike
```
- **Expected:** same artifact set, live sandbox ID in output, kill in `finally`. Record status + screenshots.

**Pass criteria (P6):** Exit 0; `run_summary.json` + `action_trace.jsonl` auditable; `compiled_test_plan.json` present and is the **only** plan input.

---

## 9. Phase 7 — Harness Integration, Checkpoints & Bug Filing (008.6)

**Objective:** Run through the standard executor lifecycle with plan checkpoint, findings, and **approval-gated** bug filing.

### Steps
1. **Executor factory (names finalized):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python - <<'PY'
   from harness.execution.factory import ExecutorFactory
   from harness.execution.base import ExecutorConfig
   import json
   plan = json.loads(open("evals/fixtures/compiled_test_plan.valid.json").read())
   for et in ("gemini_computer_use", "compiled_plan"):
       cfg = ExecutorConfig(run_id=f"run-manual-factory-{et}", target_url=plan["sut"]["base_url"],
                            plan=plan, artifacts_dir="artifacts/manual-e2e-verify", metadata={"mock": True})
       ex = ExecutorFactory.create_executor(cfg, et)
       print(et, type(ex).__name__)
   PY
   ```
   - **Expected:** both print `ComputerUseExecutor`.
2. **Integration run (failing step → reviewable finding):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_harness.py \
     --artifacts-dir "$RUN_ROOT/07-harness" --run-id run-manual-harness-001 2>&1 | tee "$RUN_ROOT/07-harness/stdout.txt"
   ```
   - **Expected:** report `status=COMPLETED`, `findings≥1`, `bug_review.approved=false`, files present:
     `plan_checkpoint.json`, `manifest.json`, `run_report.json`, `findings.json`, `checkpoint_log.json`, `bug_review_package.json`, `bug_report.md`, `bug_filing_audit.json`.
     First finding must contain `step_id`, `expected`, `observed`, `screenshots`, `trace_excerpt`, `source_refs` (non-empty).
3. **No-filing-without-approval proof (automated + manual):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/computer_use/tests/test_integration.py -v
   ```
   - **Expected:** factory aliases, executor artifacts, prod-draft block, failing-step finding + bug review, **prod-blocked draft runs zero steps** (`action_trace.jsonl` absent) — all pass. Filing raises `PermissionError` without approval.

   Manual approve flow **only** if you want the demo:
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_harness.py \
     --artifacts-dir "$RUN_ROOT/07-harness" --run-id run-manual-harness-002 --approve-bug 2>&1 | tee "$RUN_ROOT/07-harness/stdout-approve.txt"
   ```
   - **Expected:** `{"filed": "dry_run", "url": "https://github.com/testradius/web/issues/(dry-run)", "approved": true}` — no real issue created (dry-run default).

**Pass criteria (P7):** All above files exist; filing blocked before approval and `dry_run` after; `manifest.json` lists `compiled_test_plan.json` + `action_trace.jsonl`.

---

## 10. Phase 8 — Safety, Observability & Evals (008.7)

**Objective:** Prove allowlist/domain/destructive gates, injection resistance, metrics, and seeded evals.

### Steps
1. **Safety/metrics/audit unit tests:**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/computer_use/tests/test_safety_metrics.py -v
   ```
   - **Expected:** `SafetyPolicy` allowlist/domains/bounds, injection detect+sanitize + guard fragment in prompt, audit schema required fields, trace is auditable + metrics computed, validator pass, **injected domain blocked**.
2. **Computer-use evals (golden + seeded variants, flake tracking):**
   ```bash
   PYTHONPATH=. apps/cell/.venv/bin/python evals/computer_use_eval.py 2>&1 | tee "$RUN_ROOT/08-evals/stdout.txt"
   cp evals/reports/computer-use-eval.json "$RUN_ROOT/08-evals/computer-use-eval.json"
   ```
   - **Expected:** 3 cases × 3 repeats (`cu-golden-pass`, `cu-seeded-layout` → `fail_product`, `cu-agent-block` → `blocked`), `flake_rate=0.0`, `overall_pass_rate` ≈ 0.55 (step-level: 1 seeded blocked + 1 seeded product-fail by design), `total_retries` > 0.
3. **Docs check (manual):** Open and skim:
   - `docs/COMPILED_TEST_PLAN_SPEC.md` (schema/validator/compiler)
   - `docs/E2B_GEMINI_COMPUTER_USE.md` (setup/run/artifacts/troubleshooting)
   - `docs/MCP_CONTEXT_INTAKE.md` (§3) and `docs/E2B_GEMINI_COMPUTER_USE_SPIKE.md` (template/primitives/open-computer-use decision)
   - **Verify:** executor names (`gemini_computer_use`/`compiled_plan`), artifact list, and BLOCKED causes (plan checkpoint, domains, secrets) match what you observed in P6–P7.

**Pass criteria (P8):** Unit tests green; eval report exists and matches expected seeded outcomes; no secrets in report (`grep -rE 'sk-|AIza|ghp_' "$RUN_ROOT" || echo clean`).

---

## 11. Phase 9 — UI Spot-Check (EPIC-E2B-007, optional but recommended)

> Requires UI/API running. Skip (mark N/A) if unavailable — core harness proof is P1–P8.

1. **Start UI + API** (follow `docs/E2B_MANUAL_QA_HARNESS.md` / README):
   ```bash
   cd apps/harness-ui && pnpm install && pnpm dev
   # In another terminal, run harness API as configured (see harness/api/app.py)
   ```
2. **Settings page:** Open Settings → confirm executor options include **Local / Cloud Room / E2B**; system executor/config JSON is visible; E2B validation button returns `ok/configured/checks/message` (no sandbox creation, key not persisted).
   - **Expected:** Selecting E2B + “Validate E2B Connection” shows checks (`api_key`, `domain`, `sdk_list` when SDK present) and a **not-persisted** warning.
3. **Live Run page:** Open a run whose ID contains `e2b` (mock) or a live computer-use run → confirm **E2B Sandbox** panel shows sandbox ID, template, executor status, artifacts link; polling updates status.
   - **Expected:** Panel appears only when E2B metadata present; artifacts link resolves to `$RUN_ROOT/...` files.

**Pass criteria (P9):** Either both pages render as above **or** N/A with reason recorded.

---

## 12. Negative / guardrail matrix (must all hold)

| # | Attack / misuse | Command / fixture | Required result |
|---|---|---|---|
| G1 | Vague assertions | `scripts/validate_compiled_test_plan.py` (invalid leg) | Rejected (`vague_success_criteria`) |
| G2 | Inline secret | Same (mutate golden `input.password=plaintext`) | Rejected (`inline_secret`) |
| G3 | Draft plan in prod | `PlanCheckpoint` / prod run with `review_status=draft` | `BLOCKED`, **no** `action_trace.jsonl` |
| G4 | Out-of-domain navigate | `MockGemini…(evil.example.com)` | `blocked`/`fail_agent`, never executed |
| G5 | Destructive without approval | Step `destructive=true, requires_human_approval=false` | Validator error `destructive_requires_approval` |
| G6 | Secret ref without resolver | `resolve_value("{{secret.X}}")` | `blocked=True`, value `[REDACTED_SECRET]` |
| G7 | Prompt injection | Page text “ignore previous instructions…” → mock proposes evil domain | Detected by `detect_prompt_injection`; proposed action **blocked** by domain gate |
| G8 | File without approval | `BugFilingWorkflow.file_after_approval` before `approve()` | `PermissionError`, audit `FILE_BLOCKED` |
| G9 | Raw context in sandbox | `grep source_refs $RUN_ROOT/06-runner/run-*/action_trace.jsonl` | **0 hits** |

---

## 13. Result recording & sign-off

### Per-phase checklist (copy to your regression tracker)

| Phase | Result (P/F/B) | Evidence paths | Notes |
|---|---|---|---|
| 0 Pre-flight | | `$RUN_ROOT/` + §0 table | |
| 1 MCP intake (008.1) | | `$RUN_ROOT/01-mcp/` | |
| 2 Compile+validate (008.3/008.2) | | `$RUN_ROOT/02-compile/` | |
| 3 Gemini probe (008.4.2) | | `$RUN_ROOT/03-gemini/probe.txt` | |
| 4 Template (008.4.1) | | `$RUN_ROOT/04-template/` | |
| 5 Spike (008.4.3) | | `$RUN_ROOT/05-spike/run-*/` | |
| 6 Runner (008.5) | | `$RUN_ROOT/06-runner/run-*/` | |
| 7 Integration (008.6) | | `$RUN_ROOT/07-harness/run-*/` | |
| 8 Safety/evals (008.7) | | `$RUN_ROOT/08-evals/` | |
| 9 UI (007) | | screenshots/manual notes | |
| 12 Guardrails G1–G9 | | §12 table | |

**Overall verdict:** ☐ **GO** (all P1–P8 pass; live P3–P6 passed or explicitly BLOCKED-env with logs) ☐ **NO-GO** (list failing phases below).

### Evidence index (attach to defect/merge notes)
- [ ] `$RUN_ROOT/01-mcp/context_bundle.json`
- [ ] `$RUN_ROOT/02-compile/run-*/compiled_test_plan.json`
- [ ] `$RUN_ROOT/03-gemini/probe.txt` (no keys)
- [ ] `$RUN_ROOT/04-template/spec.json` (+ `build.log` if live)
- [ ] `$RUN_ROOT/05-spike/run-*/spike_report.json` + screenshots
- [ ] `$RUN_ROOT/06-runner/run-*/action_trace.jsonl` + `run_summary.json`
- [ ] `$RUN_ROOT/07-harness/run-*/{manifest,run_report,findings,bug_report}.json/md`
- [ ] `$RUN_ROOT/08-evals/computer-use-eval.json`

### Cleanup
```bash
# Kill any orphaned live sandboxes (check dashboard/API first)
# Remove temp dirs you created outside $RUN_ROOT (e.g. /tmp/cu-*), keep $RUN_ROOT for audit
# Do NOT commit $RUN_ROOT (artifacts/ is git-ignored by policy; verify with `git status`)
```

---

## 14. Defect log template (file one per failure)

```markdown
### DEFECT-<n>: <short title>
- **Phase / step:** P<#> / <step name>
- **Command:** `<exact command>`
- **Expected:** <plan expectation>
- **Actual:** <stdout/stderr/status>
- **Evidence:** `$RUN_ROOT/<phase>/...`
- **Severity:** P0/P1/P2 (blocker / major / minor)
- **Repro:** <minimal steps> · **Retest:** <after fix, re-run phase commands>
```

---

## 15. Quick-reference command card

```bash
export PYTHONPATH="$PWD"; export RUN_ROOT="artifacts/manual-e2e-$(date +%Y%m%d)"; mkdir -p "$RUN_ROOT"

# 008.1 MCP -> bundle
PYTHONPATH=. apps/cell/.venv/bin/python scripts/normalize_context_bundle.py --out "$RUN_ROOT/01-mcp/context_bundle.json"
PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/integrations/mcp_context/tests/ -v

# 008.2/008.3 validate + compile
PYTHONPATH=. apps/cell/.venv/bin/python scripts/validate_compiled_test_plan.py
PYTHONPATH=. apps/cell/.venv/bin/python scripts/compile_test_plan.py --context "$RUN_ROOT/01-mcp/context_bundle.json" --out-dir "$RUN_ROOT/02-compile" --run-id run-manual-compile-001

# 008.4 Gemini + template + spike
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_gemini_connection.py
PYTHONPATH=. apps/cell/.venv/bin/python scripts/build_e2b_desktop_template.py --dry-run
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_e2b_gemini_computer_use.py --plan evals/fixtures/computer_use_tiny_plan.json --artifacts-dir "$RUN_ROOT/05-spike" --run-id run-manual-spike-001
# live: append --live (needs E2B_API_KEY + GEMINI_API_KEY + template)

# 008.5 full runner
PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_plan.py --plan evals/fixtures/compiled_test_plan.valid.json --artifacts-dir "$RUN_ROOT/06-runner" --run-id run-manual-runner-001 --mode local_spike --loop per_step
# live: append --live

# 008.6 harness integration
PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_harness.py --artifacts-dir "$RUN_ROOT/07-harness" --run-id run-manual-harness-001
PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_harness.py --artifacts-dir "$RUN_ROOT/07-harness" --run-id run-manual-harness-002 --approve-bug

# 008.7 safety/evals
PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/computer_use/tests/test_safety_metrics.py -v
PYTHONPATH=. apps/cell/.venv/bin/python evals/computer_use_eval.py && cp evals/reports/computer-use-eval.json "$RUN_ROOT/08-evals/"
```

---

*End of plan. Execute top-to-bottom; check each ✅ box and file evidence as you go. When every phase is P (pass) or explicitly B (blocked-env with logs), sign off in §13 and link the run dir to the release/merge evidence.*
