# E2B Manual QA Harness

This guide covers the E2B-backed execution path for the TestRadius manual QA harness. The harness reuses existing planning, approval, evidence, vision, bug-generation, and connector capabilities and adds self-hosted E2B sandbox execution/orchestration.

## Status and architecture

**Current (implemented):**
- E2B sandbox provider/connection plumbing and self-hosted proxy support.
- Compiled-plan/runtime-config delivery to sandboxes (`harness/sandbox/delivery.py`) with secret scanning.
- Optional Playwright execution path in E2B (`harness/execution/e2b.py`, `harness/adapters/playwright/*`) with runtime browser bootstrap for self-hosted templates.
- Artifact collection/normalization (`harness/e2b/artifacts.py`).
- Multi-model vision QA and self-inspection (`harness/vision/*`).
- Repro-ready bug generation, approval-gated filing workflow, and GitHub connector (`harness/bugs/*`, `harness/checkpoints/bug_filing.py`, `harness/connectors/github.py`).
- End-to-end orchestration, routines/scheduling, and seeded-bug evals (`harness/e2b/orchestrator.py`, `harness/orchestration/parallel.py`, `harness/routines/scheduler.py`, `evals/e2b_seeded_benchmark.py`).
- Harness UI settings/live-view support for executor selection and E2B sandbox metadata (EPIC-E2B-007).

**Primary roadmap direction (EPIC-E2B-008, not fully implemented):**
- Compile MCP/manual context into a detailed, self-contained `CompiledExecutionTestPlan`.
- Run **Gemini computer-use** in an E2B desktop sandbox using only the compiled plan + minimal runtime config.
- Playwright remains an optional deterministic adapter/fallback, not the primary path.

## Self-hosted E2B constraints (important)

The self-hosted E2B Embed/VM environment has practical constraints:

- Use `E2B_DOMAIN=<ip>.nip.io:3002` (HTTP sandbox proxy workaround; no wildcard DNS/TLS required for local validation).
- Prefer **>= 2 CPU / 2048 MB RAM** for GUI/browser/computer-use workloads. Smaller `base` sandboxes (e.g. 512 MB) can OOM Chromium/V8.
- Template finalization can be unreliable on self-hosted setups. Playwright execution is proven via runtime bootstrap (download browser/deps into `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`) rather than relying only on prebuilt templates.
- Live `testradius.dev` E2B end-to-end runs are environment-dependent (API credentials, domain/proxy, template/desktop readiness, network access).

## Configuration

Set environment variables in the **backend/API/executor environment** (never commit secrets):

```bash
# Executor selection (API/runtime dependent)
export EXECUTOR_TYPE=e2b          # or EXECUTOR=e2b
export EXECUTOR=e2b               # compatibility alias in some code paths

# E2B credentials/connectivity
export E2B_API_KEY=...            # required for live E2B access
export E2B_API_URL=...            # optional, if using a non-default API endpoint
export E2B_DOMAIN=8.231.230.69.nip.io:3002  # self-hosted sandbox proxy (example)

# Optional: model/provider credentials used by plan compilation/vision (do not commit)
# export GOOGLE_API_KEY=...
# export GEMINI_API_KEY=...
```

For the Harness UI:

```bash
cd apps/harness-ui
pnpm install
pnpm dev
# In another terminal, run the harness API as configured for your environment.
# The Settings page shows executor/E2B status and provides validation-only inputs.
# API keys entered in the UI are for validation only and are not persisted by the UI/API.
```

## Quick verification (safe demos)

Most demos use mocks/injected executors and do **not** require a live E2B sandbox:

```bash
# E2B orchestration demo (mock executor + vision/bug review/report)
python3 scripts/test_e2b_orchestration.py

# Routines/scheduling demo (history + notifications, mock runner)
python3 scripts/test_e2b_routines.py

# Seeded-bug evals/report
python3 scripts/test_e2b_seeded_benchmark.py

# Approval-gated bug filing workflow demo
python3 scripts/test_e2b_bug_filing_workflow.py

# Canonical example (safe mock by default; live mode is opt-in and env-dependent)
python3 scripts/example_e2b_manual_qa_run.py
```

## Live E2B checks (environment-dependent)

Only run these when `E2B_API_KEY` and self-hosted connectivity are configured:

```bash
export E2B_API_KEY=...
export E2B_DOMAIN=8.231.230.69.nip.io:3002
python3 scripts/test_e2b_connection.py
```

If using the E2B SDK from the dedicated environment, ensure dependencies are installed in the expected virtualenv (e.g. `apps/cell/.venv`) and run with that interpreter where applicable.

## Typical workflow

1. **Prepare context** (manual and/or MCP sources; EPIC-E2B-008 expands MCP intake): requirements, Jira/Figma/GitHub refs, target URL, credentials policy.
2. **Compile a detailed execution plan** (roadmap/008): produce a self-contained plan with steps, assertions, evidence requirements, and safety constraints.
3. **Review/approve** the compiled plan before autonomous execution.
4. **Execute in E2B**:
   - Current implemented paths: orchestration with E2B/local executors (mockable), optional Playwright E2B execution.
   - Target primary path: Gemini computer-use runner consumes only compiled plan + minimal runtime config.
5. **Collect artifacts** (screenshots, traces/logs, manifest) and run vision/self-inspection.
6. **Generate repro-ready bugs** and require human approval before filing (GitHub connector supports safe `dry_run`).
7. **Schedule routines** for regression runs and track history/notifications.

## Example: E2B-oriented orchestration

```python
from pathlib import Path
from harness.e2b.orchestrator import E2BOrchestrationOptions, E2BOrchestrator
from harness.execution.factory import ExecutorFactory  # use a real or mock executor factory

plan = {
    "plan_id": "PLAN-SMOKE",
    "title": "Homepage smoke",
    "target": {"url": "https://testradius.dev"},
    "steps": [
        {"step_id": "S1", "intent": "Open homepage", "action_type": "navigate"},
        {"step_id": "S2", "intent": "Verify hero CTA", "action_type": "assert"},
    ],
}

# For safe local demos, inject a mock executor factory as in scripts/test_e2b_orchestration.py.
# For live runs, wire the E2B executor/factory and environment config.
orch = E2BOrchestrator(executor_factory=ExecutorFactory.create)
report = orch.run(E2BOrchestrationOptions(
    run_id="run-e2b-smoke",
    target_url="https://testradius.dev",
    plan=plan,
    artifacts_dir=Path("artifacts"),
    enable_vision=True,
    enable_bug_review=True,
))
print(report.status)
```

## Troubleshooting

### `E2B_API_KEY not configured` / validation fails
- Set `E2B_API_KEY` in the backend environment (recommended).
- UI validation inputs are **not persisted**; use them only for connectivity checks.
- Confirm the API process/environment can see the variable.

### Sandbox creation/connectivity errors (self-hosted)
- Verify `E2B_DOMAIN` (e.g. `8.231.230.69.nip.io:3002`) and network reachability.
- Confirm the self-hosted E2B API/proxy services are healthy.
- Check auth token validity and API URL/domain alignment.

### Chromium/V8 crashes or browser startup failures in sandbox
- Use **>= 2 CPU / 2048 MB** sandbox resources.
- Prefer the runtime Playwright bootstrap path (downloads headless shell to `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`) when templates are incomplete.
- Ensure Chromium args include sandbox-safe flags as used by the Playwright adapter (`--no-sandbox`, `--disable-dev-shm-usage`, `--disable-gpu`).

### Template finalization fails
- Treat as a known self-hosted constraint; use runtime bootstrap for Playwright.
- For desktop/computer-use (EPIC-E2B-008), validate/build the desktop template separately and record the verified template name.

### UI shows E2B status but live run has no sandbox metadata
- Live sandbox metadata appears when the execution path reports `executorType`/`sandboxId`/`template` in live state.
- Mock demo: open a live run whose ID contains `e2b` to see sample E2B metadata.
- Real runs depend on backend executor lifecycle reporting.

### Bugs filed unexpectedly
- Use `dry_run` (default in connector examples) and the approval-gated bug filing workflow.
- Never auto-file bugs from unreviewed vision output; require human approval/checkpoint.

### Secrets appear in logs/artifacts
- Do not pass raw API keys/tokens in plan files or prompts.
- Delivery/vision/bug paths should use redaction/secret scanning; report and fix any leakage immediately.

## Relevant code and scripts

- `harness/sandbox/delivery.py` — compiled plan/runtime config delivery
- `harness/execution/e2b.py` — E2B executor
- `harness/adapters/playwright/*` — optional Playwright conversion/bootstrap/execution
- `harness/e2b/orchestrator.py`, `harness/orchestration/parallel.py` — orchestration
- `harness/routines/scheduler.py` — routines/scheduling
- `harness/vision/*` — vision QA and self-inspection
- `harness/bugs/*`, `harness/checkpoints/bug_filing.py`, `harness/connectors/github.py` — bug filing workflow
- `scripts/example_e2b_manual_qa_run.py` — canonical safe example
- `scripts/test_e2b_orchestration.py`, `scripts/test_e2b_routines.py`, `scripts/test_e2b_seeded_benchmark.py` — demos/evals
- `planning/AGILE_BOARD_E2B_MANUAL_QA_HARNESS.md` — roadmap and story status
