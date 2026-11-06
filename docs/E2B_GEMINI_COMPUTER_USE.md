# E2B + Gemini Computer-Use — Setup, Run, Troubleshooting (EPIC-E2B-008)

End-to-end guide for running compiled plans with Gemini computer-use in E2B desktop sandboxes. Spike background: `docs/E2B_GEMINI_COMPUTER_USE_SPIKE.md`. Plan spec: `docs/COMPILED_TEST_PLAN_SPEC.md`.

## Setup (env only — never commit secrets)

```bash
export E2B_API_KEY=...                    # self-hosted E2B
export E2B_API_URL=http://8.231.230.69:3000
export E2B_DOMAIN=8.231.230.69.nip.io:3002  # HTTP sandbox proxy (no wildcard TLS)
export GEMINI_API_KEY=...                   # or GOOGLE_API_KEY
export GEMINI_COMPUTER_USE_MODEL=gemini-2.5-flash  # override as needed; verify live
export E2B_DESKTOP_TEMPLATE=desktop-chromium
export EXECUTOR_TYPE=gemini_computer_use  # or compiled_plan (alias)
```

Build desktop template (2 CPU / 2048 MB minimum; GUI OOMs on 512 MB `base`):
```bash
python scripts/build_e2b_desktop_template.py --dry-run   # inspect spec
python scripts/build_e2b_desktop_template.py            # live build
```
Self-hosted finalization can flake — retry; keep runtime bootstrap discipline from Playwright path.

Verify Gemini:
```bash
python scripts/test_gemini_connection.py
# Requires google-genai in active venv; record verified model + date when live.
```

## Run

```bash
# Safe mock (no keys): golden plan -> trace + screenshots + run_summary
python scripts/run_computer_use_plan.py

# Live (E2B desktop + Gemini)
python scripts/run_computer_use_plan.py --live --mode local_spike

# Harness integration (checkpoints + findings + bug review)
python scripts/run_computer_use_harness.py
python scripts/run_computer_use_harness.py --approve-bug  # after approval -> dry-run draft ticket
```

Through the standard executor factory:
```python
from harness.execution.factory import ExecutorFactory
from harness.execution.base import ExecutorConfig
ex = ExecutorFactory.create_executor(ExecutorConfig(run_id="run-x", target_url="https://testradius.dev", plan=plan, artifacts_dir="artifacts", metadata={"mock": True}), "gemini_computer_use")
# EXECUTOR_TYPE=gemini_computer_use|compiled_plan|local|cloudroom|e2b
```

Spike vs runner: `scripts/test_e2b_gemini_computer_use.py` (tiny 1–3 steps) vs `scripts/run_computer_use_plan.py` (full runner, Option B per-step default; `--loop whole_plan` = non-default Option A).

## Artifacts (`artifacts/run-<id>/`)
`compiled_test_plan.json`, `action_trace.jsonl` (audit: ts, case/step, screenshot refs, proposed/validation/executed/observation), `*_before.png`/`*_after.png`, `step_results.json`, `run_summary.json`, `manifest.json`, `findings.json`, `plan_checkpoint.json`/`checkpoint_log.json`, `bug_review_package.json`/`bug_report.md` (approval-gated).

## Troubleshooting
- `E2B_API_KEY`/sandbox errors: verify `E2B_API_URL`/`E2B_DOMAIN` reachability + API key; confirm services healthy.
- `google-genai` missing: install in active venv (`apps/cell/.venv` needs compatible wheel build); mock paths unaffected.
- Chromium OOM: raise to ≥2 CPU/2048 MB; avoid `base` for GUI.
- Runner `BLOCKED`: check `plan_checkpoint` (prod needs approved plan), `allowed_domains` vs `base_url`, destructive approval, secret refs (need approved resolver).
- `action_trace` gaps: re-run with `mode=local_spike`; audit check `validate_trace_file(trace)` should be `ok`.
- Bug stays draft: `file_after_approval` requires reviewer approval; GitHub connector defaults `dry_run=True`.
