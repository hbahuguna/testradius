# E2B Gemini Computer-Use Spike & Desktop Foundation (EPIC-E2B-008.4)

This spike proves the **testplan-first computer-use loop** on self-hosted E2B: compiled plan (+ minimal runtime config) → Gemini proposes desktop actions → harness validates → primitives execute → screenshots/evidence. It is the foundation for the full runner (008.5).

## Reference evaluated: `e2b-dev/open-computer-use`

**Repo:** <https://github.com/e2b-dev/open-computer-use> (2.4k★, Apache-2.0, E2B Desktop Sandbox + open LLMs).

**What it does:**
- Creates an E2B **desktop sandbox** (Ubuntu, live screen streaming) and controls it via keyboard/mouse/shell.
- Agent loop in `os_computer_use/sandbox_agent.py`: `screenshot()` → vision model describes screen → action model emits tool calls (`run_command`, `click`/`double_click`/`type_text`/`send_key`, `stop`) → `sandbox.move_mouse()/left_click()/write()/press()` execute.
- Providers include **Google Gemini 2.0 Flash** (vision + action) via OpenAI-compat endpoint, plus OS-Atlas/ShowUI grounding, Groq/OpenAI/Anthropic, etc. Config in `os_computer_use/config.py` + `providers.py`.

**Reuse/wrap decision: wrap, don't fork.**
- **Reuse** the sandbox-action surface (`screenshot`, mouse, keyboard, shell) and provider pattern as a *reference*, implemented behind `harness/computer_use/primitives.py`:
  - `E2BDesktopPrimitives` prefers `e2b-desktop` SDK methods (`screenshot`, `move_mouse`, `left_click`, `write`, `press`) and falls back to `xdotool`/`scrot` shell commands via `E2BSandboxProvider.run_command`.
  - `GeminiComputerUseClient` uses `google-genai` directly (vs OpenAI-compat) to keep the harness provider boundary explicit and testable.
- **Why not fork:** open-computer-use is an interactive web/Gradio agent (streaming UI, threading, `webview`), not a compiled-plan runner. Our harness needs deterministic step contracts, allowlist/domain validation, and evidence artifacts — implemented in `harness/computer_use/spike.py` (008.5 precursor). Forking would add unrelated UI and complicate dependency/version upgrades.

## Self-hosted E2B desktop template (008.4.1)

**Script:** `scripts/build_e2b_desktop_template.py` (`--dry-run` prints spec; live build needs `E2B_API_KEY`).

**Template (`desktop-chromium`):**
- Base: `python:3.11` + `xvfb`, `openbox`, `xterm`, **`xdotool`** (mouse/keyboard), **`scrot`** + `imagemagick` (screenshots), `chromium`, `fonts-liberation/noto`, `pillow` (PIL), `playwright==1.49.0`.
- Env: `DISPLAY=:99`; helper `~/start-desktop.sh` starts `Xvfb :99 -screen 0 1440x900x24 +extension RANDR` + `openbox`.
- **Resources: 2 CPU / 2048 MB** (GUI/browser OOMs on 512 MB `base`).
- **Connectivity:** `E2B_DOMAIN=8.231.230.69.nip.io:3002` + HTTP proxy patch (existing `_patch_e2b_http_for_self_hosted`). Template finalization on self-hosted Embed can be flaky; keep runtime bootstrap fallback (Playwright path proved this; desktop needs the same retry/verify discipline).

## Primitive proof status

| Primitive | Mock (this repo, CI-safe) | Live E2B desktop |
|---|---|---|
| screenshot | ✅ `MockComputerUsePrimitives.screenshot()` (PNG bytes + per-shot artifact) | 🟡 `E2BDesktopPrimitives.screenshot()` via `e2b-desktop` or `scrot`/`import` |
| mouse move | ✅ recorded | 🟡 `move_mouse` SDK / `xdotool mousemove` |
| click | ✅ recorded | 🟡 `left_click` SDK / `xdotool click` |
| keyboard/type | ✅ recorded | 🟡 `write`/`press` SDK / `xdotool type/key` |
| scroll | ✅ recorded | 🟡 SDK / `xdotool click` wheel |
| wait | ✅ recorded (no sleep) | 🟡 `sleep` in sandbox |
| navigate | ✅ sets `current_url` | 🟡 launches Chrome on `:99` |

**Live proof is environment-dependent** (requires self-hosted E2B services healthy, `E2B_API_KEY`, template built, `GEMINI_API_KEY`). The spike harness is structured so the same tests run against mocks and live primitives without code change.

## Tiny compiled-plan spike (008.4.3)

**Fixture:** `evals/fixtures/computer_use_tiny_plan.json` — 2 steps (navigate → assert hero), `review_status=draft`, passes `local_spike` quality gate.

**Runner:** `harness/computer_use/spike.py` (`ComputerUseSpikeRunner`):
- Input: **only** compiled plan + runtime config. No raw Jira/Figma/PRD payloads sent to sandbox.
- Per step: screenshot → Gemini proposes JSON action → `ActionValidator` (step alignment, coord bounds, **allowed-domains**, approval/destructive, evidence) → primitive execute → after-screenshot + `spike_report.json`.
- Invalid proposals are **BLOCKED** with evidence, not executed.

**Run (safe, no keys):**
```bash
PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_e2b_gemini_computer_use.py
```

**Run (live, env-dependent):**
```bash
export E2B_API_KEY=... E2B_API_URL=http://8.231.230.69:3000 E2B_DOMAIN=8.231.230.69.nip.io:3002
export GEMINI_API_KEY=...  # or GOOGLE_API_KEY
python scripts/build_e2b_desktop_template.py  # if template missing
python scripts/test_e2b_gemini_computer_use.py --live
```

## Gemini config & model verification (008.4.2)

**Script:** `scripts/test_gemini_connection.py` — checks key presence (value never printed), SDK import (`google-genai`), and (live) a trivial `COMPUSE_OK` probe with latency.

**Configured models (env-overridable, see `ComputerUseConfig`):**
- `GEMINI_COMPUTER_USE_MODEL` → `GEMINI_MODEL` → default `gemini-2.5-flash` (spike default; verify before production — model IDs change).
- `GEMINI_API_KEY` or `GOOGLE_API_KEY` (either accepted; never logged/persisted).

**Verification status:** 🟡 **Not verified live in this environment** (no keys/SDK present when this spike was authored). The harness ships mock-verified code paths and records `TODO-record-on-live-verification`; run `scripts/test_gemini_connection.py` and record the **verified model ID + date** when live credentials are available. Do not block 008.5 on unverified production model IDs — keep them configurable.

## Tests

```bash
PYTHONPATH=. apps/cell/.venv/bin/python -m pytest harness/computer_use/tests/test_spike.py -v
# 5 passed (tiny-plan gate, mock E2E, domain/bounds blocks, blocked-step evidence)
```

## Key files

- `harness/computer_use/{config,primitives,gemini_client,spike}.py` — spike foundation (008.5 will generalize)
- `scripts/build_e2b_desktop_template.py`, `scripts/test_gemini_connection.py`, `scripts/test_e2b_gemini_computer_use.py`
- `evals/fixtures/computer_use_tiny_plan.json`
