# AGILE_BOARD_E2B_MANUAL_QA_HARNESS.md — Manual QA AI Harness on E2B (GCP)

## 1. Overview
Build a production-ready Manual QA AI Harness using E2B Embed on GCP as the sandbox engine. Leverage existing TestRadius harness infrastructure (API/UI/orchestration/approvals/evidence/Cloud Room integration) where possible.

**Core strategy (testplan-first):** the **compiled test plan** is the primary execution contract. In Phase 1 (control plane), we gather requirement context (manual and/or via MCP connectors such as Jira/Figma/GitHub/docs), normalize it, and use Gemini to compile a **self-contained, execution-grade test plan** with sufficient detail that **Gemini computer-use can execute each step without additional user instructions and without uploading raw context into the sandbox**. In Phase 2, the harness sends the compiled test plan to an E2B desktop sandbox run driven by Gemini computer-use (screenshot → reason → proposed action → validated execution → evidence).

**Execution modes:**
1. **Gemini computer-use (primary):** executes the compiled test plan in an E2B desktop sandbox (agentic/visual, human-like). Preferred default.
2. **Playwright/script adapter (optional):** deterministic execution generated *from the same compiled test plan* for stable regression/evals/fallback when selectors or environments are well-known. **Not required** for the primary workflow.

## 2. Goals and Non-Goals
### Goals
- Deploy/connect to E2B Embed instance on GCP (marine-aria-504018-t8)
- Abstract sandbox provider (E2B) alongside existing sandbox/executor backends
- **Testplan-first compilation:** produce a versioned, schema-validated, human-reviewable **Compiled Execution TestPlan** from requirement context; quality-gated before execution
- **MCP-based context intake (control plane):** connect to Jira/Figma/GitHub/docs/other sources via MCP servers where available to fetch context; support manual paste/upload fallback; normalize into a context bundle for the compiler
- **Gemini computer-use QA agent (primary):** execute the compiled test plan in an E2B desktop sandbox via Gemini vision+action agentic loop (screenshot → reason → `function_call`/action → validate → execute → observe → evidence)
- **Sandbox receives only what it needs:** compiled test plan + runtime config/env references (no secrets, no mandatory raw PRD/Figma dump in sandbox)
- Support model/provider flexibility (Gemini primary; pluggable where practical) while keeping credentials in env vars
- Vision/QA analysis and self-inspection over screenshots and action traces
- Evidence capture (screenshots, action trace, logs, optional video) in `artifacts/run-<id>/`
- Human-in-the-loop checkpoints before bug filing; every run/plan reviewable
- Bug filing integration (GitHub/Jira/Linear) with deduplication and evidence
- Routines/scheduling for automated QA runs
- Eval framework with seeded-bug/known-flow benchmarks (including computer-use)
- Integrate with existing TestRadius UI/API where beneficial

### Non-Goals
- Rebuilding entire UI from scratch (extend existing)
- Mobile app testing first
- Full exploratory testing replacement
- Storing secrets in repo, test plans, or sandbox artifacts
- Hard dependency on OpenAI APIs (Gemini-first for this initiative)
- Mandatory raw-context upload to execution sandbox when a compiled test plan is sufficient

## 3. Architecture
```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Control Plane (Local/Laptop)                                                         │
│ - TestRadius API/UI (existing) OR standalone harness CLI                            │
│ - Context intake: manual input OR MCP connectors (Jira/Figma/GitHub/docs/...)        │
│ - Phase 1 (critical): normalize context → Gemini COMPILED TEST PLAN compiler          │
│   => schema-validated, human-reviewable, self-contained execution contract            │
│ - Orchestration, approvals, bug filing, evals                                        │
└──────────────┬──────────────────────────────────────┬────────────────────────────────┘
               │ E2B SDK                              │ Google Gen AI SDK (Gemini)
               │ (send compiled plan + runtime config) │ planning + vision+action
┌──────────────▼──────────────────────────────────────▼────────────────────────────────┐
│ E2B API (GCP VM - marine-aria-504018-t8)                                             │
│ - Sandbox lifecycle (desktop; optional script sandbox)                                │
└──────────────┬───────────────────────────────────────────────────────────────────────┘
               │ Firecracker microVMs
┌──────────────▼───────────────────────────────────────────────────────────────────────┐
│ Primary: E2B Desktop/Computer-Use Sandbox                                             │
│ - Receives: compiled test plan JSON + minimal runtime config (env refs, no secrets)   │
│ - Harness agentic loop: screenshot/state → Gemini action → validate → execute → obs   │
│ - Evidence: step screenshots, action trace, logs, assertions/results                  │
│                                                                                       │
│ Optional: Playwright/script sandbox (deterministic adapter from same compiled plan)   │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

## 4. E2B Instance Details
- Project: marine-aria-504018-t8
- Instance: e2b-embed (us-west1-b)
- API Key: e2b_a4839a085a860c188a85b4b956820783 (from terraform state)
- Terraform outputs available via `terraform output`

## 5. Epics
| Epic ID | Name | Outcome | Depends On |
|---|---|---|---|
| EPIC-E2B-001 | E2B Infrastructure & Connection | Connect to E2B, verify sandbox creation & browser/desktop runtime | - |
| EPIC-E2B-002 | E2B Sandbox Provider Integration | Abstract E2B as provider/executor in harness | EPIC-E2B-001 |
| EPIC-E2B-003 | Playwright Adapter (Optional) | Optional deterministic Playwright execution from a compiled test plan (regression/evals/fallback) | EPIC-E2B-002, EPIC-E2B-008 (compiled plan schema) |
| EPIC-E2B-004 | Vision QA & Evidence Capture | Screenshot/action-trace analysis, self-inspection, evidence sync | EPIC-E2B-008 |
| EPIC-E2B-005 | Human Checkpoints & Bug Filing | Approval gates, ticket generation, dedup | EPIC-E2B-004 |
| EPIC-E2B-006 | Orchestration, Routines & Evals | Scheduling, seeded-bug benchmarks across execution modes | EPIC-E2B-005 |
| EPIC-E2B-007 | UI Integration & Polish | Integrate testplan-first/Gemini computer-use flows into TestRadius UI/API | EPIC-E2B-006 |
| EPIC-E2B-008 | Compiled Test Plans + Gemini Computer-Use (Primary) | **Testplan-first**: compile context (MCP/manual) into a self-contained execution plan; Gemini computer-use executes it in E2B desktop sandbox | EPIC-E2B-001, EPIC-E2B-002 |

## 6. Stories & Tasks

### EPIC-E2B-001: E2B Infrastructure & Connection
#### STORY-E2B-001.1 — Configure E2B SDK & Environment
- **Epic:** EPIC-E2B-001 | **Status:** Done | **Priority:** P0 | **Estimate:** S
- **User story:** As a developer, I need to configure the E2B SDK to connect to my GCP instance.
- **AC:**
  - [x] E2B SDK installed (`pip install e2b`)
  - [x] Environment variables configured (`E2B_API_KEY`, `E2B_API_URL` or domain)
  - [x] Connection tested from local machine
  - [x] Credentials stored securely (env vars, not committed)
- **Tasks:**
  - [ ] TASK-E2B-001.1.1: Get E2B API URL from terraform outputs
  - [ ] TASK-E2B-001.1.2: Set up env vars in .env.example
  - [ ] TASK-E2B-001.1.3: Test connection script
- **Capability:** Infrastructure
- **Demo:** `python scripts/test_e2b_connection.py` succeeds
- **Evidence:** scripts/test_e2b_connection.py, .env.example updates

#### STORY-E2B-001.2 — Hello World Sandbox Test
- **Epic:** EPIC-E2B-001 | **Status:** Done | **Priority:** P0 | **Estimate:** S
- **User story:** As a developer, I want to create/kill a sandbox and run a command to verify connectivity.
- **AC:**
  - [x] Can create sandbox via SDK
  - [x] Can run command and get output (fixed: `E2B_DOMAIN=8.231.230.69.nip.io:3002` + HTTP patch for self-hosted proxy; VM `/opt/e2b/compose.yaml` updated for client-proxy/api domain env)
  - [x] Can kill/cleanup sandbox
  - [x] No resource leaks
- **Tasks:**
  - [x] TASK-E2B-001.2.1: Create test script
  - [x] TASK-E2B-001.2.2: Test with default template
  - [x] TASK-E2B-001.2.3: Add error handling
- **Capability:** Sandboxing
- **Demo:** `scripts/test_e2b_hello.py` prints `Hello from the Manual QA Harness!`
- **Evidence:** `scripts/test_e2b_hello.py`

#### STORY-E2B-001.3 — Verify Playwright Template Availability
- **Epic:** EPIC-E2B-001 | **Status:** Done | **Priority:** P0 | **Estimate:** S
- **User story:** As a developer, I need to confirm Playwright template is available for browser automation.
- **AC:**
  - [x] Templates checked via API (initially only `base`; `playwright-chromium` now created)
  - [x] Command execution works in base sandbox (envd connectivity fixed)
  - [x] Playwright/Chromium launch verified headless in `playwright-chromium` template (2CPU/2048MB). **Self-hosted E2B note:** template builds with baked browsers hit an E2B Embed finalization internal error; browsers are installed at runtime via the proven manual path (direct headless-shell download, correct cache layout, apt deps). Default `base` (512MB) is insufficient for Chromium (V8 OOM).
- **Tasks:**
  - [x] TASK-E2B-001.3.1: Test playwright template availability
  - [x] TASK-E2B-001.3.2: Probe base template environment
  - [x] TASK-E2B-001.3.3: Build `playwright-chromium` (2GB) template and verify browser launch (`TITLE: Example Domain`)
- **Capability:** UI Driving
- **Demo:** `scripts/e2b_playwright_runtime_verify.py` → `✓ Playwright + Chromium launch verification PASSED`
- **Evidence:** `scripts/build_e2b_playwright_template_manual.py`, `scripts/e2b_playwright_runtime_verify.py`, `scripts/verify_e2b_playwright_browser.py`

### EPIC-E2B-002: E2B Sandbox Provider Integration
#### STORY-E2B-002.1 — Create E2BSandboxProvider
- **Epic:** EPIC-E2B-002 | **Status:** Done | **Priority:** P0 | **Estimate:** M
- **User story:** As the harness, I need an abstraction for sandbox providers.
- **AC:**
  - [x] `BaseSandboxProvider` interface defined (create/start/stop/exec/upload/download)
  - [x] `E2BSandboxProvider` implements interface
  - [x] Provider factory for selecting backend
  - [x] Configurable via env vars
- **Tasks:**
  - [ ] TASK-E2B-002.1.1: Define base interface in `harness/sandbox/base.py`
  - [ ] TASK-E2B-002.1.2: Implement E2B provider in `harness/sandbox/e2b_provider.py`
  - [ ] TASK-E2B-002.1.3: Create factory in `harness/sandbox/factory.py`
- **Capability:** Sandboxing
- **Demo:** Provider creates/destroys sandboxes
- **Evidence:** harness/sandbox/base.py, harness/sandbox/e2b_provider.py, harness/sandbox/factory.py

#### STORY-E2B-002.2 — Add E2B to Executor Abstraction
- **Epic:** EPIC-E2B-002 | **Status:** Done | **Priority:** P0 | **Estimate:** M
- **User story:** As the harness, I want to use E2B via the existing executor framework.
- **AC:**
  - [x] `E2BExecutor` extends `BaseExecutor`
  - [x] Integrates with E2BSandboxProvider
  - [x] Works with ExecutorFactory
  - [x] Can be selected via `EXECUTOR_TYPE=e2b`
- **Tasks:**
  - [ ] TASK-E2B-002.2.1: Create `harness/execution/e2b.py`
  - [ ] TASK-E2B-002.2.2: Update factory to support e2b
  - [ ] TASK-E2B-002.2.3: Add config in `harness/config.py`
- **Capability:** Sandboxing, Execution
- **Demo:** Create executor with executor_type='e2b'
- **Evidence:** harness/execution/e2b.py, updated factory/config

#### STORY-E2B-002.3 — E2B Client & Error Handling
- **Epic:** EPIC-E2B-002 | **Status:** Done | **Priority:** P0 | **Estimate:** S
- **User story:** As the harness, I need robust E2B client with retries and errors.
- **AC:**
  - [x] Client wrapper with connection validation
  - [ ] Retry logic for transient failures
  - [x] Proper error types
  - [ ] Timeout handling
- **Tasks:**
  - [ ] TASK-E2B-002.3.1: Create `harness/integrations/e2b/client.py`
  - [ ] TASK-E2B-002.3.2: Add exception classes
  - [ ] TASK-E2B-002.3.3: Tests
- **Capability:** Infrastructure
- **Demo:** Graceful error handling
- **Evidence:** harness/integrations/e2b/

### EPIC-E2B-003: Playwright Adapter (Optional)
*PM direction:* Gemini computer-use + a compiled test plan is the **primary** path. EPIC-E2B-003 is an **optional deterministic adapter** for regression/evals/fallback. Do not block EPIC-E2B-008 on this. Raw requirement context should not be uploaded to sandboxes; only the compiled test plan and minimal runtime config.

#### STORY-E2B-003.1 — Compiled Plan & Runtime Config Delivery to Sandbox
- **Epic:** EPIC-E2B-003 | **Status:** Done | **Priority:** P1 | **Estimate:** S
- **User story:** As the harness, I need to deliver the compiled test plan and minimal runtime config to any E2B execution sandbox safely.
- **AC:**
  - [x] Upload compiled test plan JSON via `sandbox.files.write()` (delivered as `/home/user/compiled_test_plan.json`, with legacy `/home/user/plan.json` alias)
  - [x] Upload only minimal runtime config (`/home/user/runtime_config.json`: non-secret env references, target URL, run ID, allowed domains, timeouts); **no raw PRD/tickets/Figma dumps required**
  - [x] Verify files exist (`test -s` and fallback download check); redact secrets from logs/artifacts (`strict_secrets=True` raises `SecretExposureError`, `strict_secrets=False` auto-redacts via `Redactor`)
  - [x] Reusable by computer-use and optional Playwright adapters (`deliver_plan_and_config` integrated into `E2BExecutor` and standalone delivery module)
- **Tasks:**
  - [x] TASK-E2B-003.1.1: Plan/config upload helper in `harness/sandbox/delivery.py`
  - [x] TASK-E2B-003.1.2: Secret-redaction checks (strict mode + auto-redaction)
  - [x] TASK-E2B-003.1.3: Tests in `harness/sandbox/tests/test_plan_delivery.py` and live smoke demo
- **Capability:** Execution plumbing
- **Demo:** `python scripts/test_e2b_plan_delivery.py` → `✓ STORY-E2B-003.1 DEMO PASSED: Sandbox received and parsed compiled plan and config.`
- **Evidence:** `harness/sandbox/delivery.py`, `harness/sandbox/tests/test_plan_delivery.py`, `scripts/test_e2b_plan_delivery.py`

#### STORY-E2B-003.2 — Playwright Script Generation & Execution (Optional Adapter)
- **Epic:** EPIC-E2B-003 | **Status:** Done | **Priority:** P2 | **Estimate:** L
- **User story:** As the harness, I may generate and run Playwright tests from the compiled test plan for deterministic regression/fallback.
- **AC:**
  - [x] Generate Playwright script **from compiled test plan schema** (`PlaywrightScriptGenerator`: maps cases, atomic steps, actions `navigate/click/type/select/scroll/keypress/wait/assert`, semantic hints, observable criteria, timeouts)
  - [x] Upload/run in appropriate sandbox template (`playwright-chromium`, 2CPU/2048MB); aligned with proven runtime/browser bootstrap (`harness/adapters/playwright/bootstrap.py` checks and installs `playwright==1.49.0` + headless shell + apt deps if missing; runs via `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python3 /home/user/test_script.py` with `--no-sandbox --disable-dev-shm-usage --disable-gpu`)
  - [x] Capture stdout/stderr, step results (`step_results.json`), step screenshots, and Playwright tracing (`trace.zip`)
  - [x] Handle timeouts and cleanup (`executor.cleanup()`, sandbox kill)
- **Tasks:**
  - [x] TASK-E2B-003.2.1: Script generator aligned to compiled plan (`harness/adapters/playwright/generator.py`)
  - [x] TASK-E2B-003.2.2: Execution logic in `harness/execution/e2b.py` + runtime bootstrap in `harness/adapters/playwright/bootstrap.py`
  - [x] TASK-E2B-003.2.3: Smoke test (`scripts/test_e2b_playwright_execution.py`) and unit test suite
- **Capability:** Deterministic UI Driving (optional)
- **Demo:** `python scripts/test_e2b_playwright_execution.py --mock` → `✓ STORY-E2B-003.2 DEMO PASSED: Playwright script generated from compiled plan executed successfully.`
- **Evidence:** `harness/adapters/playwright/generator.py`, `harness/adapters/playwright/bootstrap.py`, `harness/execution/e2b.py`, `scripts/test_e2b_playwright_execution.py`, `harness/adapters/playwright/tests/test_generator.py`

#### STORY-E2B-003.3 — Compiled Test Plan to Playwright Converter (Optional)
- **Epic:** EPIC-E2B-003 | **Status:** Done | **Priority:** P2 | **Estimate:** M
- **User story:** As the harness, I need a best-effort converter from compiled test plan steps to Playwright actions where selectors/hints are present.
- **AC:**
  - [x] Parse compiled test plan JSON (dict / JSON string / `.json` path), preserving `cases`/`steps`/`sut` schema
  - [x] Map actions (`navigate/click/double_click/type/fill/select/scroll/keypress/wait/assert`) using explicit selectors/hints when available; mark steps as `computer_use_only` when not safely automatable (e.g., locator-required actions without `selector`/`test_id`/`role+name`/`placeholder`/`label`, missing assert criteria, unsupported actions like `drag`). Per-step reasons + `used_hints` recorded.
  - [x] Add screenshots at key points and error handling in generated runner (reuses generator semantics; `computer_use_only` steps capture a screenshot and record `COMPUTER_USE_ONLY` status)
  - [x] Report conversion coverage (% automated vs computer-use-only) overall and `by_action`, with full per-step report serialized to JSON and embedded in script output
- **Tasks:**
  - [x] TASK-E2B-003.3.1: Converter in `harness/adapters/playwright/converter.py` (`PlaywrightPlanConverter`, `ConversionResult`/`ConversionReport`/`StepConversion`)
  - [x] TASK-E2B-003.3.2: Action mapping + coverage report (`coverage_pct`, `by_action`, per-step classification/reasons/hints; script outputs `AUTOMATION_COVERAGE_PCT`/`COMPUTER_USE_ONLY`)
  - [x] TASK-E2B-003.3.3: Tests with realistic mixed/compiled plans
- **Capability:** Optional deterministic adapter
- **Demo:** `python scripts/test_e2b_playwright_converter.py` → conversion report (4/6 automated, 66.67% coverage) + valid runnable script for supported steps; `✓ STORY-E2B-003.3 DEMO PASSED`
- **Evidence:** `harness/adapters/playwright/converter.py`, `harness/adapters/playwright/__init__.py`, `harness/adapters/playwright/tests/test_converter.py`, `scripts/test_e2b_playwright_converter.py`

### EPIC-E2B-004: Vision QA & Evidence Capture
#### STORY-E2B-004.1 — Screenshot & Artifact Collection
- **Epic:** EPIC-E2B-004 | **Status:** Done | **Priority:** P0 | **Estimate:** M
- **User story:** As the harness, I need to download artifacts from sandbox.
- **AC:**
  - [x] Download files via sandbox provider abstraction (`provider.download_file` / files.read API path), with best-effort discovery (`find` via `run_command`) and known-path hints
  - [x] Collect screenshots, videos, traces (+ console/network/results evidence types) with extension/name classification; pulls step screenshot paths from `step_results.json`
  - [x] Save to `artifacts/run-<id>/` structure (normalized filenames, disambiguation for basename collisions)
  - [x] Create `manifest.json` (legacy-compatible `type`/`path` + extended `remote_path`, `filename`, `size_bytes`, `sha256`, `collected_at`, `source`/sandbox metadata)
- **Tasks:**
  - [x] TASK-E2B-004.1.1: Artifact downloader/collector (`harness/e2b/artifacts.py`: `SandboxArtifactCollector`, `collect_sandbox_artifacts`)
  - [x] TASK-E2B-004.1.2: Normalize to harness structure + manifest
  - [x] TASK-E2B-004.1.3: Integration with evidence pipeline/executor (`harness/execution/e2b.py` uses collector; manifest written to `artifacts/run-<id>/manifest.json`)
- **Capability:** Evidence capture
- **Demo:** `python scripts/test_e2b_artifact_collection.py` → artifacts synced locally with manifest; `✓ STORY-E2B-004.1 DEMO PASSED`
- **Evidence:** `harness/e2b/artifacts.py`, `harness/e2b/__init__.py`, `harness/execution/e2b.py`, `harness/e2b/tests/test_artifacts.py`

#### STORY-E2B-004.2 — Vision QA Analysis
- **Epic:** EPIC-E2B-004 | **Status:** Done | **Priority:** P0 | **Estimate:** L
- **User story:** As the agent, I want to analyze screenshots with vision models.
- **AC:**
  - [x] Send screenshots to vision model via provider adapters (Gemini, OpenAI, Anthropic) with image+prompt payloads; mock provider for deterministic tests/demos (real calls require provider API keys/SDKs)
  - [x] QA-focused prompt for `layout`/`contrast`/`clipping`/`overlap`/`responsive` issues (`harness/vision/prompts.py`), requests JSON findings with severity/confidence/location/suggestion
  - [x] Parse findings into structured format (`VisionFinding`, `VisionAnalysisResult` with `passed`, `summary`, raw response/error handling, confidence normalization)
  - [x] Support multiple models via `provider:model` specs + aliases (`gemini:*`, `gpt-*`/`openai:*`, `claude-*`/`anthropic:*`, `mock`; legacy `gpt-vision-default` preserved)
- **Tasks:**
  - [x] TASK-E2B-004.2.1: Extend vision client for sandbox artifacts (`VisionClient.analyze_artifacts` reads run dir/`manifest.json` from 004.1; backward-compatible `inspect()`)
  - [x] TASK-E2B-004.2.2: QA-focused prompts (`harness/vision/prompts.py`)
  - [x] TASK-E2B-004.2.3: Tests with mock provider + structured parsing + manifest integration (`harness/vision/tests/test_vision_qa.py`); real screenshot/model test supported via `scripts/test_e2b_vision_qa.py --model gemini:... --run-dir artifacts/run-<id>`
- **Capability:** Vision QA
- **Demo:** `python scripts/test_e2b_vision_qa.py` → structured QA findings generated from manifest screenshots (`vision_report.json`); `✓ STORY-E2B-004.2 DEMO PASSED`
- **Evidence:** `harness/vision/{client,models,prompts,inspector}.py`, `harness/vision/providers/*`, `harness/vision/tests/test_vision_qa.py`, `scripts/test_e2b_vision_qa.py`

#### STORY-E2B-004.3 — Multi-Round Self-Inspection
- **Epic:** EPIC-E2B-004 | **Status:** Done | **Priority:** P1 | **Estimate:** M
- **User story:** As the agent, I want to self-inspect and iterate.
- **AC:**
  - [x] Round 1: Initial inspection (`purpose=initial_inspection`)
  - [x] Round 2: Verify fixes/check additional areas (`purpose=verify_fixes_and_check_additional_areas`; round 2+ context includes prior actionable findings)
  - [x] Deduplicate findings by fingerprint (`category|issue|location`), keeping highest severity/confidence; summary includes `actionable_deduped_findings`
  - [x] Log inspection rounds with timestamps, purpose, screenshot, findings, actionable findings, model/provider, errors; persistable inspection report (`schema_version`, `rounds`, `deduped`, `analyses`, `summary`)
- **Tasks:**
  - [x] TASK-E2B-004.3.1: Inspector loop for E2B workflow (`SelfInspector.inspect`, `inspect_and_save`; uses `VisionClient`/artifact-compatible screenshot paths)
  - [x] TASK-E2B-004.3.2: Dedupe logic (fingerprint + severity/confidence ranking)
  - [x] TASK-E2B-004.3.3: Logging + report persistence (`SelfInspector.save_report`, `scripts/test_e2b_vision_inspection.py`)
- **Capability:** Vision QA
- **Demo:** `python scripts/test_e2b_vision_inspection.py` → 2 inspection rounds logged, deduped findings, `vision_inspection_report.json`; `✓ STORY-E2B-004.3 DEMO PASSED`
- **Evidence:** `harness/vision/inspector.py`, `harness/vision/tests/test_inspector_multiround.py`, `scripts/test_e2b_vision_inspection.py`, inspection report JSON

### EPIC-E2B-005: Human Checkpoints & Bug Filing
#### STORY-E2B-005.1 — Checkpoint Integration
- **Epic:** EPIC-E2B-005 | **Status:** Done | **Priority:** P0 | **Estimate:** M
- **User story:** As a tester, I want to approve findings before filing bugs.
- **AC:**
  - [x] Use existing checkpoint system (`ApprovalState`/`ApprovalRegistry`/`AuditEntry` audit primitives; integrated via `BugFilingWorkflow`)
  - [x] Block bug filing until approved (`PermissionError`/`FILE_BLOCKED` audit; connector filing only after `ApprovalState.require_approval()`)
  - [x] Show findings with screenshots (CLI review text + `bug_review_package.json`/`bug_report.md` include findings, screenshot paths/existence, traces/logs/manifest/inspection refs, repro steps)
  - [x] Audit log (`REVIEW_PREPARED`, `APPROVE`/`REVOKE` via `ApprovalState`, `FILE_BLOCKED`/`FILE_DUPLICATE`/`FILE_*`; exportable JSON)
- **Tasks:**
  - [x] TASK-E2B-005.1.1: Integrate with `harness/checkpoints` (`harness/checkpoints/bug_filing.py`, exports in `__init__`)
  - [x] TASK-E2B-005.1.2: CLI approval/review workflow (`render_review_package`, `BugFilingWorkflow.prepare_review/approve/file_after_approval`)
  - [x] TASK-E2B-005.1.3: Test flow (`harness/checkpoints/tests/test_bug_filing.py`)
- **Capability:** Human checkpoints
- **Demo:** `python scripts/test_e2b_bug_filing_workflow.py` → review shows findings/screenshots, filing blocked without approval, approved with audit; `✓ 005.1...`
- **Evidence:** `harness/checkpoints/bug_filing.py`, `harness/checkpoints/{__init__,approval}.py`, `bug_review_package.json`/`bug_filing_audit.json` outputs, tests/demo

#### STORY-E2B-005.2 — Bug Generation from E2B Findings
- **Epic:** EPIC-E2B-005 | **Status:** Done | **Priority:** P0 | **Estimate:** M
- **User story:** As the harness, I want to generate repro-ready bug tickets.
- **AC:**
  - [x] Combine vision findings + logs + evidence (ingests 004.2/004.3 findings, 004.1 manifest/run artifacts, console/network logs, traces, step/vision/inspection reports)
  - [x] Generate steps to reproduce (from `step_results` intents/status + URL/primary finding; fallback repro steps)
  - [x] Include screenshots/videos (and traces/log refs) in structured evidence + Markdown ticket
  - [x] Severity/priority inference (max actionable finding severity → `critical/high/medium/low/info`, mapped to `P0-P4`)
- **Tasks:**
  - [x] TASK-E2B-005.2.1: Use/extend existing bug generator (`harness/bugs/generator.py`: `BugReportGenerator`, `BugReport`, `BugEvidence`; backward-compatible `BugFiler.generate/file`)
  - [x] TASK-E2B-005.2.2: Enrich with E2B artifacts (manifest/run-dir discovery, step results, vision/inspection report loading)
  - [x] TASK-E2B-005.2.3: Template customization (`BugReport.render_markdown()` repro-ready ticket with summary, severity/priority, steps, expected/actual, suspected cause, findings, evidence, environment)
- **Capability:** Bug filing
- **Demo:** `python scripts/test_e2b_bug_filing_workflow.py` → repro-ready bug report (e.g. `[Overlap]...` high/P1, 4 repro steps, screenshots/traces/manifest linked); `✓ 005.2...`
- **Evidence:** `harness/bugs/{__init__,generator}.py`, `harness/bugs/tests/test_bug_generation.py`, generated `bug_report.md`/review package, demo script

#### STORY-E2B-005.3 — Connector Integration & Dedup
- **Epic:** EPIC-E2B-005 | **Status:** Done | **Priority:** P0 | **Estimate:** M
- **User story:** As a tester, I want bugs filed to GitHub/Jira/Linear with dedup.
- **AC:**
  - [x] File to configured connector via pluggable interface (`BaseIssueConnector`); **GitHub connector implemented** (`GitHubConnector`, safe `dry_run` default; optional real filing via `gh issue create` when `dry_run=False` + repo/CLI available). Jira/Linear connectors not implemented yet (follow-up), architecture supports adding them.
  - [x] Dedup against existing issues (normalized title + fingerprint match; accepts provided existing issues and optional best-effort `gh issue list` lookup)
  - [x] Requires checkpoint approval (integrated with 005.1 `BugFilingWorkflow`/`ApprovalState`; filing blocked without approval)
  - [x] Links evidence (ticket body includes screenshots/videos/traces/logs/manifest/report paths; connector result carries structured evidence)
- **Tasks:**
  - [x] TASK-E2B-005.3.1: Connector package (`harness/connectors/{base,github,__init__}.py`); integrates with bug generator/workflow (no pre-existing connector package found)
  - [x] TASK-E2B-005.3.2: Dedup logic (`BaseIssueConnector.is_duplicate`, `BugFiler.dedup/dedup_report`, fingerprint)
  - [x] TASK-E2B-005.3.3: Test filing (`harness/checkpoints/tests/test_bug_filing.py`, `harness/bugs/tests/test_bug_generation.py`; GitHub dry-run + dedup + approval)
- **Capability:** Bug filing
- **Demo:** `python scripts/test_e2b_bug_filing_workflow.py` → GitHub dry-run ticket result (`dry_run`, repo URL placeholder, labels, evidence links) + explicit dedup detection; `✓ 005.3...`
- **Evidence:** `harness/connectors/{base,github,__init__}.py`, `harness/checkpoints/bug_filing.py`, `scripts/test_e2b_bug_filing_workflow.py`, tests

### EPIC-E2B-006: Orchestration, Routines & Evals
#### STORY-E2B-006.1 — End-to-End Orchestration
- **Epic:** EPIC-E2B-006 | **Status:** Done | **Priority:** P0 | **Estimate:** L
- **User story:** As the harness, I need full orchestration: context → plan → execute in E2B → evidence → vision → report.
- **AC:**
  - [x] Orchestrator coordinates all steps (plan load/dict or file → E2B executor execution+delivery/artifacts → vision inspection → bug review package generation [approval required, no auto-file] → orchestration report)
  - [x] Error handling and cleanup (per-stage isolation/errors recorded; report saved; best-effort cleanup on orchestration exceptions)
  - [x] Progress tracking (structured progress events + optional callback; stages: init/execute/vision/bug_review/cleanup/orchestration)
  - [x] Sandbox cleanup on completion/failure (executor cleanup runs in `finally` after execution path; cleanup progress logged)
- **Tasks:**
  - [x] TASK-E2B-006.1.1: Create `harness/e2b/orchestrator.py` (`E2BOrchestrator`, `E2BOrchestrationOptions`, `OrchestrationReport`; exported from `harness.e2b`)
  - [x] TASK-E2B-006.1.2: Wire all components (E2B executor, 004.1 artifacts, 004.2/004.3 vision/inspection, 005.x bug review generation; injectable executor/vision/inspector/workflow for tests)
  - [x] TASK-E2B-006.1.3: E2E orchestration test (component-wired mock E2B executor + vision/bug-review path; `harness/e2b/tests/test_orchestrator.py`, `scripts/test_e2b_orchestration.py`). **Live testradius.dev E2B E2E remains environment-dependent** (self-hosted E2B/template/desktop readiness and 008 Gemini computer-use primary path).
- **Capability:** All core
- **Demo:** `python scripts/test_e2b_orchestration.py` → full mock run completes with progress, execution/vision/report, cleanup; also `python scripts/test_e2b_parallel_orchestration.py` shows parallel E2B-oriented orchestration (concurrency/aggregation/failure isolation)
- **Evidence:** `harness/e2b/orchestrator.py`, `harness/orchestration/parallel.py`, `harness/e2b/tests/test_orchestrator.py`, `harness/orchestration/tests/test_parallel.py`, `scripts/test_e2b_orchestration.py`, `scripts/test_e2b_parallel_orchestration.py`, `artifacts/*/orchestration_report.json` / `artifacts/demo_parallel_e2b.json` (generated by demos)

#### STORY-E2B-006.2 — Routines & Scheduling
- **Epic:** EPIC-E2B-006 | **Status:** Done | **Priority:** P1 | **Estimate:** M
- **User story:** As an operator, I want scheduled QA runs.
- **AC:**
  - [x] Use existing scheduler or simple cron (extended `harness/routines/scheduler.py`; simple in-process cadence checks `@hourly/@daily/@weekly/interval:<s>`; raw cron strings stored for external cron integration)
  - [x] Config for E2B runs (`RoutineConfig`: executor_type=e2b, target_url, plan/plan_path, timeout, metadata; default runner can execute via `E2BOrchestrator`; injectable runner for tests)
  - [x] Run history (`RoutineHistory` JSONL append/query; registered/started/completed/failed events)
  - [x] Notifications (callback notifiers for run_started/run_completed/run_failed; failures isolated from routine execution)
- **Tasks:**
  - [x] TASK-E2B-006.2.1: Integrate with harness/routines (`Scheduler`, `RoutineConfig`, `RoutineHistory`; legacy `schedule`/`run_now` preserved)
  - [x] TASK-E2B-006.2.2: E2B-specific config (`RoutineConfig` + default E2B orchestration path)
  - [x] TASK-E2B-006.2.3: Test scheduling (`harness/routines/tests/test_scheduler.py`)
- **Capability:** Routines
- **Demo:** `python scripts/test_e2b_routines.py` → E2B routine registered, cadence due-check, run executes, history+notifications recorded; `✓ 006.2 demo passed`
- **Evidence:** `harness/routines/{__init__,scheduler}.py`, `harness/routines/tests/test_scheduler.py`, `scripts/test_e2b_routines.py`, routine history JSONL (demo)

#### STORY-E2B-006.3 — Seeded-Bug Benchmark
- **Epic:** EPIC-E2B-006 | **Status:** Done | **Priority:** P1 | **Estimate:** L
- **User story:** As an engineer, I want to measure detection rate.
- **AC:**
  - [x] Use existing benchmark framework (adapted existing top-level `evals/` benchmark framework; added `evals/e2b_seeded_benchmark.py` alongside legacy `evals/benchmark.py`; harness evals remain intact)
  - [x] Run against seeded bugs (`evals/fixtures/e2b_seeded_bugs.json`: seeded positives + clean negative; injectable/mock detector supports E2B/vision-adapted detection path; repeated runs per case)
  - [x] Metrics: detection rate, FP rate, reproducibility (also TP/FP/TN/FN, precision/recall/F1, per-case detections/outcomes; majority-vote classification + per-repeat consistency)
  - [x] Report generation (`evals/reports/e2b-benchmark.json`)
- **Tasks:**
  - [x] TASK-E2B-006.3.1: Adapt benchmark for E2B (`evals/e2b_seeded_benchmark.py`, E2B-seeded fixture schema)
  - [x] TASK-E2B-006.3.2: Run benchmark (`scripts/test_e2b_seeded_benchmark.py`, `E2BSeededBugBenchmark.run_and_save()`)
  - [x] TASK-E2B-006.3.3: Analyze results (report summary/case outcomes with detection/FP/reproducibility metrics)
- **Capability:** Evals
- **Demo:** `python scripts/test_e2b_seeded_benchmark.py` → metrics computed (detection/FP/reproducibility), case outcomes shown, report saved; `✓ 006.3 demo passed`
- **Evidence:** `evals/fixtures/e2b_seeded_bugs.json`, `evals/e2b_seeded_benchmark.py`, `harness/evals/tests/test_seeded_benchmark.py`, `scripts/test_e2b_seeded_benchmark.py`, `evals/reports/e2b-benchmark.json`

### EPIC-E2B-007: UI Integration & Polish
#### STORY-E2B-007.1 — Add E2B to UI Settings
- **Epic:** EPIC-E2B-007 | **Status:** Done | **Priority:** P1 | **Estimate:** M
- **User story:** As a user, I want to select E2B as executor in UI.
- **AC:**
  - [x] Add E2B option to executor selection (Settings page shows Local/Cloud Room/E2B options with descriptions; reflects system executor config)
  - [x] Show E2B connection status (configured/validated status pill, system executor status JSON, validation checks)
  - [x] Configure API key/URL (inputs for E2B API URL + self-hosted domain/proxy + API key for validation only; clear env-var/preferred-secret messaging; key not persisted by UI/API)
  - [x] Validate connection (`POST /api/system/e2b/validate` best-effort SDK/probe checks; UI displays checks/message/warning)
- **Tasks:**
  - [x] TASK-E2B-007.1.1: Update SettingsPage (`apps/harness-ui/src/pages/SettingsPage.tsx`)
  - [x] TASK-E2B-007.1.2: Update API types/client/mock/backend (`apps/harness-ui/src/types.ts`, `api/client.ts`, `api/mock.ts`; `harness/api/app.py` adds E2B config fields + validation endpoint)
  - [x] TASK-E2B-007.1.3: Test UI (`cd apps/harness-ui && ./node_modules/.bin/tsc --noEmit` passes; backend `harness/api/app.py` parses)
- **Capability:** UI
- **Demo:** Start UI/API (`cd apps/harness-ui && pnpm dev` / `harness` API as configured), open Settings, select E2B, review status, enter env/validation values, click “Validate E2B Connection”.
- **Evidence:** `SettingsPage.tsx`, `types.ts`, `api/{client,mock}.ts`, `harness/api/app.py`, TypeScript typecheck; screenshot can be captured when running UI locally/browser (environment-dependent)

#### STORY-E2B-007.2 — E2B-Specific Live View
- **Epic:** EPIC-E2B-007 | **Status:** Done | **Priority:** P2 | **Estimate:** M
- **User story:** As a user, I want to see E2B sandbox status.
- **AC:**
  - [x] Show sandbox ID (Live Run shows E2B Sandbox panel with `sandboxId`/pending state when executor is E2B or metadata present)
  - [x] Show template used (panel displays `template` from live state)
  - [x] Link to artifacts (opens `artifactsUrl` when available; falls back to `evidenceDir` path)
  - [x] Status updates (existing live polling continues; executor status badge and updated live metadata shown)
- **Tasks:**
  - [x] TASK-E2B-007.2.1: Enhance live view (`apps/harness-ui/src/pages/LiveRunPage.tsx` adds E2B sandbox panel + executor badge)
  - [x] TASK-E2B-007.2.2: Add sandbox info (`LiveExecutionState` metadata fields; mock E2B live state for `*e2b*` run IDs; `harness/api/app.py` carries executor/sandbox/template in live/start-executor responses)
  - [x] TASK-E2B-007.2.3: Test (`python3 -c "import ast; ast.parse(...harness/api/app.py...)"` OK; `cd apps/harness-ui && ./node_modules/.bin/tsc --noEmit` passes)
- **Capability:** UI
- **Demo:** Live Run shows E2B Sandbox panel (sandbox ID, template, executor status, artifacts link) when live state reports E2B metadata; mock demo via `getLiveState` for run IDs containing `e2b`.
- **Evidence:** `LiveRunPage.tsx`, `mock.ts`, `harness/api/app.py`, `types.ts` metadata fields, TypeScript/API parse checks

#### STORY-E2B-007.3 — Documentation & Examples
- **Epic:** EPIC-E2B-007 | **Status:** Done | **Priority:** P1 | **Estimate:** S
- **User story:** As a user, I want docs to use E2B harness.
- **AC:**
  - [x] Update README with E2B setup (new “E2B Manual QA Harness” section with env config, safe examples, links)
  - [x] Create E2B usage guide (`docs/E2B_MANUAL_QA_HARNESS.md` — status, architecture, self-hosted constraints, config, workflow, examples)
  - [x] Add example scripts (`scripts/example_e2b_manual_qa_run.py`, safe mock by default; references existing `test_e2b_*` demos)
  - [x] Troubleshooting section (API key/validation, self-hosted connectivity/domain, browser/OOM/template issues, live metadata, bug filing safety, secret hygiene)
- **Tasks:**
  - [x] TASK-E2B-007.3.1: Write docs/E2B_MANUAL_QA_HARNESS.md
  - [x] TASK-E2B-007.3.2: Update README
  - [x] TASK-E2B-007.3.3: Add examples (`scripts/example_e2b_manual_qa_run.py`; mock-mode verified)
- **Capability:** Documentation
- **Demo:** `python3 scripts/example_e2b_manual_qa_run.py` runs a safe mock E2B orchestration; README + `docs/E2B_MANUAL_QA_HARNESS.md` provide setup/usage/troubleshooting.
- **Evidence:** `docs/E2B_MANUAL_QA_HARNESS.md`, README E2B section, `scripts/example_e2b_manual_qa_run.py`, supporting lazy-import fixes in `harness/execution/{__init__,factory}.py` and `harness/e2b/orchestrator.py` for mock/example resilience

### EPIC-E2B-008: Compiled Test Plans + Gemini Computer-Use (Primary)
**Goal:** Make the **compiled test plan** the single source of truth for execution. Phase 1 compiles requirement context (manual and/or **MCP-sourced** from Jira/Figma/GitHub/docs) into a **self-contained, execution-grade test plan**. Phase 2 sends **only the compiled plan + minimal runtime config** to Gemini computer-use in an E2B desktop sandbox; no additional user steps and no mandatory raw-context upload to the sandbox.

**Key design decisions (PM):**
- **Test plan quality is the top priority.** If the compiled plan is good, execution becomes a controlled agentic loop. Invest in schema, compiler prompts, validation, and human review gates.
- **MCP for context intake (control plane):** use MCP servers/connectors to fetch Jira issues, Figma frames/links metadata, GitHub issues/PRDs/docs where configured; fall back to manual paste/upload. MCP data is normalized into a `ContextBundle`-like structure and **compiled into the plan** — raw MCP payloads are not sent to the execution sandbox.
- **Gemini-first, credits-aware:** use Google Gen AI SDK/Gemini models for (a) plan compilation and (b) computer-use action selection. Verify current model/tool support (vision, function/tool calling or computer-use) before implementation; record verified models.
- **Harness is the hands; plan is the contract.** Gemini proposes actions; harness validates actions against the current test step, allowlists, bounds, and safety policy before executing in E2B.
- **No separate Playwright sandbox required** for the primary path. Keep Playwright as an optional adapter from the same compiled plan (EPIC-E2B-003).
- **Self-hosted E2B Embed constraints:** desktop template on `marine-aria-504018-t8` must be verified/built (spike). Reuse `E2B_DOMAIN=8.231.230.69.nip.io:3002` HTTP proxy patch and >=2CPU/2048MB for desktop/browser workloads.

#### Compiled Execution TestPlan — required schema (implementation contract)
The compiler must produce JSON that is sufficient for Gemini computer-use execution. Minimum fields:
- `schema_version`, `plan_id`, `title`, `objective`, `source_refs[]` (ticket/doc/figma identifiers; no secrets), `generated_at`, `generator` (model/prompt version)
- `sut`: `base_url`, `environment`, `build_version?`, `browser/device/profile`, `locale/timezone`, `viewport`, `auth_mode` (`none|manual_prelogin|test_account_ref` — **reference env vars/secret names, never values**)
- `preconditions[]`: required state/data/feature flags, setup steps completed before step 1
- `test_data[]`: named fixtures/inputs (non-secret); secret refs by env var name only
- `constraints`: allowed domains/URLs, destructive-action policy, max runtime/steps, stop conditions, data handling/redaction rules
- `cases[]` (or `flows[]`) each with: `case_id`, `title`, `priority`, `type` (happy/edge/negative/regression/accessibility/visual), `tags`, `steps[]`
- `steps[]` each with: `step_id`, `ordinal`, `intent` (human), `action_type` (`navigate|click|type|select|scroll|hover|keypress|wait|assert|upload_ref|note`), `target` (semantic description + optional hints: text/role/label/region/selector_if_known/css_xpath_optional), `input` (value or `{{test_data.x}}` / `{{env.VAR_NAME}}` ref — never inline secret), `success_criteria` (observable UI/result states, **specific and testable**), `failure_signals`, `evidence` (`screenshot_before|after|on_failure`, `dom_text?`, `action_trace`), `max_attempts`, `timeout_s`, `fallback_instructions` (what to try if target not found), `on_fail` (`stop_case|continue_and_report|mark_blocked`), `requires_human_approval` (bool)
- `postconditions[]`, `cleanup[]`
- `oracle_notes`: what constitutes pass/fail; known acceptable variations; accessibility/visual checks
- `execution_hints_for_computer_use`: global prompt hints (e.g., “prefer visible labels over coordinates”, “verify page loaded before acting”, “if modal blocks, close or report”), app-specific navigation cues distilled from context
- `quality_gate`: `compiled_by`, `review_status` (`draft|human_reviewed|approved`), `validation_errors[]`, `coverage_notes`

#### STORY-E2B-008.1 — MCP Context Intake & Normalization (Control Plane)
- **Epic:** EPIC-E2B-008 | **Status:** Done | **Priority:** P0 | **Estimate:** M
- **User story:** As a QA engineer, I want the harness to gather requirements from Jira/Figma/GitHub/docs (via MCP where available) and normalize them for test-plan compilation.
- **AC:**
  - [x] Define normalized context schema extending `harness/context/schema.py` patterns (`ContextBundle`: source refs, title/summary, description, acceptance criteria, user flows, UI/design refs/Figma links+notes, API/data constraints, env/build info, risk areas, out-of-scope)
  - [x] MCP integration design: configurable MCP servers/tools for Jira, Figma, GitHub, docs; fetch/read resources and map to normalized context. If MCP server unavailable, fall back to manual input/URL paste/file upload (`ContextIntake`, `MCPServerConfig`, adapter registry, explicit/manual fallback)
  - [x] Secrets/tokens only via env/config; never persisted in plan or artifacts (env ref names only; `ContextNormalizer` + `harness/policy/redaction.py` redact before save)
  - [x] Provenance recorded (`source_refs`, timestamps, tool/adapter used, warnings, redaction status)
  - [x] Unit/integration tests with mocked MCP/resource payloads (`harness/integrations/mcp_context/tests/test_mcp_context_intake.py`)
- **Tasks:**
  - [x] TASK-E2B-008.1.1: `harness/context/` normalization + compiler input schema (`schema.py`, `normalization.py`, `loader.py` save/load helpers)
  - [x] TASK-E2B-008.1.2: MCP context adapters (`harness/integrations/mcp_context/`): Jira/Figma/GitHub/docs + MCP resource + manual adapters
  - [x] TASK-E2B-008.1.3: Manual fallback + provenance/redaction (`ContextIntake` fallback, `ContextNormalizer.redact_data/save_bundle`)
  - [x] TASK-E2B-008.1.4: `docs/MCP_CONTEXT_INTAKE.md`
- **Capability:** Context intake, MCP integration
- **Demo:** `PYTHONPATH=. apps/cell/.venv/bin/python scripts/normalize_context_bundle.py --out artifacts/examples/008.1/context_bundle.json` (mocked Jira/Figma/GitHub/manual → normalized bundle)
- **Evidence:** Schema/adapters (`harness/context/*`, `harness/integrations/mcp_context/*`), tests (10 passed), docs (`docs/MCP_CONTEXT_INTAKE.md`), committed sample (`docs/examples/context_bundle.normalized.008.1.json`), demo script (`scripts/normalize_context_bundle.py`)

#### STORY-E2B-008.2 — Compiled Test Plan Schema & Quality Gate (Most Important)
- **Epic:** EPIC-E2B-008 | **Status:** Done | **Priority:** P0 | **Estimate:** M
- **User story:** As the harness, I need a strict schema and quality gate so compiled test plans are executable by Gemini computer-use without extra human instructions.
- **AC:**
  - [x] Implement `CompiledExecutionTestPlan` schema (Pydantic/JSON Schema) per contract above; versioned (`schema_version=1.0.0`) — `harness/testplan/schema.py`
  - [x] Validator rejects plans missing: `base_url`/target, preconditions, per-step `success_criteria`, evidence requirements, timeouts, allowed domains, or containing inline secrets
  - [x] Lint/quality checks: atomic-step heuristic warning, observable/non-vague assertions, fallback-instruction warning, destructive-step approval flag, provided-AC coverage warning
  - [x] Human review status required before autonomous execution in production mode (`quality_gate.review_status='approved'`; `draft` allowed for local spike only)
  - [x] Golden sample plans committed under `evals/fixtures/compiled_test_plan.valid.json` (sanitized)
- **Tasks:**
  - [x] TASK-E2B-008.2.1: `harness/testplan/schema.py` (compiled plan contract models: SUT, constraints, cases/steps, evidence, quality gate)
  - [x] TASK-E2B-008.2.2: `harness/testplan/validator.py` + quality lint rules (`CompiledPlanValidator`, structured `ValidationResult`/issues)
  - [x] TASK-E2B-008.2.3: Golden samples + schema tests (`evals/fixtures/compiled_test_plan.valid.json`, `harness/testplan/tests/test_compiled_test_plan.py`)
- **Capability:** Planning, Quality gate
- **Demo:** `PYTHONPATH=. apps/cell/.venv/bin/python scripts/validate_compiled_test_plan.py` — valid plan passes, draft blocked in production, invalid/vague/secret plan rejected
- **Evidence:** `harness/testplan/{schema,validator,__init__}.py`, `harness/testplan/tests/test_compiled_test_plan.py` (9 passed), `evals/fixtures/compiled_test_plan.valid.json`, `scripts/validate_compiled_test_plan.py`

#### STORY-E2B-008.3 — Gemini Test Plan Compiler (Context → Compiled Execution Plan)
- **Epic:** EPIC-E2B-008 | **Status:** Done | **Priority:** P0 | **Estimate:** L
- **User story:** As a QA engineer, I want Gemini to compile normalized context into a detailed, execution-grade test plan for computer-use.
- **AC:**
  - [x] Compiler takes normalized context bundle + SUT/runtime config and produces `CompiledExecutionTestPlan` JSON (`GeminiTestPlanCompiler.compile`, pluggable text generator)
  - [x] Prompt strategy uses role + strict schema contract + few-shot/golden excerpt + hard constraints (no missing steps/vague assertions/secrets; fallbacks/evidence/allowed domains/review draft) — `harness/testplan/prompts/v1.py`
  - [x] Prompt/compiler instructs expansion of ACs into concrete cases/steps and relevant happy/negative/edge/visual/UX checks; output is validated by 008.2 quality gate (mock tests use golden context/valid plans; live quality depends on model and env)
  - [x] Distills Figma/design intent and ticket nuances into textual step targets/oracles via normalized context + prompt instructions (sandbox does not load raw Figma)
  - [x] Output passes schema/quality validator via bounded validate/repair loop before save (`max_repair_attempts`, validation errors fed back to model)
  - [x] Plan artifact saved to `artifacts/run-<id>/compiled_test_plan.json` (configurable artifacts dir/run id) with prompt/model/attempt/validation metadata (redacted); generator records `model_verification.verified_live=false` note when live verification not executed
- **Tasks:**
  - [x] TASK-E2B-008.3.1: Versioned prompt templates in `harness/testplan/prompts/` (`v1.py`, `testplan-compiler-v1`, schema/golden excerpt, compile+repair builders)
  - [x] TASK-E2B-008.3.2: `harness/testplan/compiler.py` (Gemini + validate/repair loop; lazy `google-genai` import; env model IDs/keys only)
  - [x] TASK-E2B-008.3.3: Tests with mocked Gemini + golden normalized contexts (`harness/testplan/tests/test_compiler.py`, 5 passed)
- **Capability:** Planning (critical)
- **Demo:** `PYTHONPATH=. apps/cell/.venv/bin/python scripts/compile_test_plan.py --live` requires `GEMINI_API_KEY/GOOGLE_API_KEY` (env-dependent). Default demo uses mocked generator: `scripts/compile_test_plan.py` compiles `docs/examples/context_bundle.normalized.008.1.json` into a validated plan.
- **Evidence:** `harness/testplan/{compiler,prompts/*}.py`, `test_compiler.py` (5 passed), `scripts/compile_test_plan.py`, `docs/examples/compiled_test_plan.008.3.sample.json`; `apps/cell/pyproject.toml` declares `google-genai` (install in this env failed due `cryptography` build toolchain; live SDK call remains lazy/import-guarded and model/tool support must be verified with keys/network)

#### STORY-E2B-008.4 — Gemini Computer-Use Spike & E2B Desktop Foundation
- **Epic:** EPIC-E2B-008 | **Status:** Done (spike: mock-verified + live-ready; live E2B/Gemini verification env-dependent) | **Priority:** P0 | **Estimate:** M
- **User story:** As a developer, I need a working E2B desktop sandbox + Gemini vision/action loop on our self-hosted GCP instance.
- **AC:**
  - [x] Evaluate `e2b-dev/open-computer-use` as reference (Gemini provider patterns) and document reuse/wrap decision (wrap sandbox-action surface; don't fork interactive agent) — `docs/E2B_GEMINI_COMPUTER_USE_SPIKE.md`
  - [x] Verify/build **desktop-capable template** on self-hosted E2B Embed; record image, resources (>=2CPU/2048MB), startup/browser availability (`desktop-chromium`: python:3.11 + Xvfb/openbox/xdotool/scrot/chromium, 2CPU/2048MB, `~/start-desktop.sh`; live build via `scripts/build_e2b_desktop_template.py` — env-dependent)
  - [x] Prove primitives: screenshot, mouse click/move, keyboard/type, scroll/wait; self-hosted connectivity via `E2B_DOMAIN` nip.io:3002 HTTP proxy patch (mock-proven + live `E2BDesktopPrimitives` via `e2b-desktop`/xdotool-scrot; docs include mock/live status table)
  - [x] Spike runs a tiny compiled plan (1–3 steps) end-to-end using `GEMINI_API_KEY` (mock E2E implemented + tested; live path env-dependent via `--live`)
  - [x] Model/tool support verified against current Google docs (IDs/date recorded) — **pending live verification**: configured default `gemini-2.5-flash`/`GEMINI_COMPUTER_USE_MODEL` (env-overridable); `scripts/test_gemini_connection.py` records probe when keys present; docs mark TODO-record-on-live-verification (no keys in authoring env)
- **Tasks:**
  - [x] TASK-E2B-008.4.1: Desktop template discovery/build (`scripts/build_e2b_desktop_template.py`, `--dry-run` + live Template build)
  - [x] TASK-E2B-008.4.2: Gemini config + `scripts/test_gemini_connection.py` (key/SDK/probe checks, no secret output)
  - [x] TASK-E2B-008.4.3: `scripts/test_e2b_gemini_computer_use.py` (compiled-plan-driven spike; mock default, live `--live`)
  - [x] TASK-E2B-008.4.4: `docs/E2B_GEMINI_COMPUTER_USE_SPIKE.md`
- **Capability:** Sandboxing, Gemini computer-use, Infrastructure
- **Demo:** `PYTHONPATH=. apps/cell/.venv/bin/python scripts/test_e2b_gemini_computer_use.py` (mock spike: 2-step tiny plan → screenshots + `spike_report.json`); live: `scripts/test_e2b_gemini_computer_use.py --live` (requires E2B + Gemini keys)
- **Evidence:** `harness/computer_use/{config,primitives,gemini_client,spike}.py` (5 tests passed), `evals/fixtures/computer_use_tiny_plan.json`, spike scripts, `docs/E2B_GEMINI_COMPUTER_USE_SPIKE.md`

#### STORY-E2B-008.5 — Computer-Use Execution Runner (Compiled Plan → Actions → Evidence)
- **Epic:** EPIC-E2B-008 | **Status:** Done (mock-verified + live-ready; live E2B/Gemini env-dependent) | **Priority:** P0 | **Estimate:** L
- **User story:** As the harness, I need to execute a compiled test plan step-by-step with Gemini computer-use, without extra user input or raw context uploads.
- **AC:**
  - [x] Runner input is **only** `compiled_test_plan.json` + runtime config/env refs; sandbox receives no raw Jira/Figma/PRD content (runner artifact is compiled plan only; trace carries step contracts, never raw context)
  - [x] For each step: capture screenshot/state → send **current step contract** (`intent`, `target`, `input` refs resolved safely, `success_criteria`, `fallback_instructions`, `execution_hints`) + recent history to Gemini → receive proposed action → **validate** (allowlist, domain/safety, step alignment) → execute → observe/assert → record result
  - [x] Resolve safe runtime refs (e.g., `{{env.VAR_NAME}}` for non-secret config; secret refs handled by approved mechanism, never logged) — `ref_resolver.py` (test_data/env resolved; secrets blocked without approved resolver, redacted in traces)
  - [x] Supported actions (minimum): screenshot, click, double_click, type, keypress, scroll, wait, navigate/open URL (within allowed domains), assert/observe (+ right_click/move/stop) — `action_schema.py` + primitive mapping
  - [x] Guardrails: per-step/per-case/per-run timeouts (step `timeout_s`, `max_runtime_s`), max actions, retry with fallback instructions, stop_case handling, classification (`pass|fail_product|fail_agent|blocked|infra_error`)
  - [x] Evidence: per-step before/after screenshots (as configured), `action_trace.jsonl`, step results, final run summary
  - [x] Default: **structured per-step loop** (Option B). Optional spike mode: whole-plan prompt (Option A) clearly labeled non-default (`loop="whole_plan"` progress note)
- **Tasks:**
  - [x] TASK-E2B-008.5.1: Action schema + validator/executor mapping to E2B desktop primitives (`action_schema.py`, `StepActionValidator` in `runner.py`)
  - [x] TASK-E2B-008.5.2: Gemini computer-use client (vision + tool/function or structured action parsing) with step-scoped prompting (`gemini_client.py` step prompt + `ACTION_FUNCTION_SCHEMA`, `assess` hook)
  - [x] TASK-E2B-008.5.3: `harness/computer_use/runner.py` (loop, refs, assertions, evidence) + `ref_resolver.py`
  - [x] TASK-E2B-008.5.4: E2E run against `https://testradius.dev` using a golden compiled plan (`scripts/run_computer_use_plan.py`, mock-verified; live `--live` env-dependent)
- **Capability:** UI Driving (agentic), Evidence capture
- **Demo:** `PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_plan.py` (mock: golden plan → action trace + screenshots + run summary)
- **Evidence:** `harness/computer_use/{runner,action_schema,ref_resolver,gemini_client}.py`, `harness/computer_use/tests/test_runner.py` (5 passed; full EPIC-008 suite 34 passed), `scripts/run_computer_use_plan.py`

#### STORY-E2B-008.6 — Harness Integration, Checkpoints & Bug Filing
- **Epic:** EPIC-E2B-008 | **Status:** Done | **Priority:** P0 | **Estimate:** M
- **User story:** As a tester, I want compiled-plan/computer-use runs in the standard harness workflow with approval before bug filing.
- **AC:**
  - [x] Integrate with orchestration lifecycle (run IDs, `artifacts/run-<id>/`, status, logs) — `ComputerUseExecutor` (BaseExecutor) + `ComputerUseHarnessRunner.run_compiled_plan`
  - [x] Checkpoint: human reviews compiled plan before execution (prod `review_status='approved'` required; spike `local_spike` allowed) and reviews findings before bug filing — `PlanCheckpoint` + `BugFilingWorkflow.prepare_review`
  - [x] Findings include step ID, expected vs. observed, screenshots, action trace excerpt, source refs — `build_findings_from_run` → `findings.json`
  - [x] Reuse bug generator/connectors/dedup; no filing without approval — `BugReportGenerator` + `BugFilingWorkflow` + `GitHubConnector(dry_run=True)`; `PermissionError` without approval verified
  - [x] API/CLI mode for `compiled_plan` + `gemini_computer_use` (names finalized in implementation) — executor types `gemini_computer_use` (canonical) + `compiled_plan` (alias) via `ExecutorFactory` / `EXECUTOR_TYPE`
- **Tasks:**
  - [x] TASK-E2B-008.6.1: Orchestration/config/factory integration (`harness/execution/computer_use.py`, `harness/execution/factory.py`, `harness/computer_use/integration.py`)
  - [x] TASK-E2B-008.6.2: Artifact normalization and report format (`normalize_artifacts` → `manifest.json` via `ArtifactManifest`, `run_report.json`, `findings.json`, `checkpoint_log.json`, `plan_checkpoint.json`)
  - [x] TASK-E2B-008.6.3: Checkpoint + bug-filing integration (no approval, no file)
- **Capability:** Orchestration, Human checkpoints, Bug filing
- **Demo:** `PYTHONPATH=. apps/cell/.venv/bin/python scripts/run_computer_use_harness.py` (failing step → finding → bug review; `--approve-bug` → dry-run draft ticket with evidence)
- **Evidence:** `harness/computer_use/integration.py`, `harness/execution/computer_use.py`, `harness/computer_use/tests/test_integration.py` (5 passed; full EPIC-008/checkpoint/bug suite 39 passed), `scripts/run_computer_use_harness.py`

#### STORY-E2B-008.7 — Safety, Observability & Evals
- **Epic:** EPIC-E2B-008 | **Status:** Todo | **Priority:** P1 | **Estimate:** M
- **User story:** As an operator, I need safe, debuggable, measurable computer-use runs.
- **AC:**
  - [ ] Action allowlist/validation; domain restrictions; destructive actions require explicit plan flag + approval
  - [ ] Prompt-injection resistance posture: treat page content as untrusted data, never as instructions overriding the compiled plan; never expose secrets
  - [ ] Full audit log (`action_trace.jsonl`): timestamp, case/step, screenshot ref, proposed action, validation, executed action, observation/result
  - [ ] Metrics: plan validation pass rate, step pass/fail/blocked/infra, agent-vs-product failure rate, retries, runtime, token/cost estimates if available
  - [ ] Evals: golden compiled plans + known flows/seeded bugs; track flake rate
  - [ ] Docs: compiled plan spec, MCP intake, Gemini/E2B setup, troubleshooting
- **Tasks:**
  - [ ] TASK-E2B-008.7.1: Safety policy + audit schema
  - [ ] TASK-E2B-008.7.2: Metrics/reporting
  - [ ] TASK-E2B-008.7.3: Evals + `docs/COMPILED_TEST_PLAN_SPEC.md`, `docs/E2B_GEMINI_COMPUTER_USE.md`
- **Capability:** Safety, Evals, Observability
- **Demo:** Eval report + auditable action trace for a run
- **Evidence:** Audit log, eval report, docs

## 7. Execution Plan (Sprint Order)
1. **Sprint 1 (Week 1):** EPIC-E2B-001 - Infrastructure & Connection *(001.1-001.3 complete; maintain runtime workaround notes)*
2. **Sprint 2 (Week 2):** EPIC-E2B-002 - Provider Integration *(complete; refine for desktop/template/runtime bootstrap as needed)*
3. **Sprint 3 (Week 3, highest leverage):** EPIC-E2B-008.2 + E2B-008.3 - **Compiled Test Plan schema/quality gate + Gemini compiler** (most important). Deliver golden plans and validator before broad execution.
4. **Sprint 4 (Week 4):** EPIC-E2B-008.1 + E2B-008.4 - MCP/manual context intake normalization + Gemini computer-use spike / E2B desktop foundation.
5. **Sprint 5 (Week 5):** EPIC-E2B-008.5 - Computer-use execution runner (compiled plan only; no raw context in sandbox).
6. **Sprint 6 (Week 6):** EPIC-E2B-004 + E2B-008.6 - Evidence/action-trace analysis, checkpoints, bug-filing integration.
7. **Sprint 7 (Week 7):** EPIC-E2B-005 + EPIC-E2B-006 (core) - Checkpoint hardening, orchestration, run lifecycle.
8. **Sprint 8 (Week 8):** EPIC-E2B-006.2–006.3 + E2B-008.7 - Routines, evals, safety/observability, docs.
9. **Sprint 9 (Week 9):** EPIC-E2B-007 - UI integration/polish.
10. **Backlog/optional:** EPIC-E2B-003 - Playwright deterministic adapter generated from compiled plans (regression/evals/fallback), only when justified.

*PM note:* **Do not start broad autonomous execution before 008.2/008.3 quality gates and human plan review exist.** Gemini computer-use quality is bounded by compiled plan quality.

## 8. Success Metrics
| Metric | Target | Measurement |
|---|---|---|
| Compiled plan schema/quality pass rate (post-repair) | > 95% | Validator + lint results on generated plans |
| Compiled plan human-approval rate (reviewed plans) | > 80% initially | Reviewer feedback/edits required |
| Step specificity (no vague assertions/missing fallbacks) | 100% required fields; > 90% reviewer-rated actionable | Lint + human rubric |
| MCP/manual context normalization coverage | Jira/Figma/GitHub/manual supported for pilot | Successful `ContextBundle` creation |
| Gemini computer-use step completion (golden/known-good flows) | >= 70% initial, improving via plan grounding | Evals; classify `pass/fail_product/fail_agent/blocked/infra` |
| Action safety | 100% proposed actions validated/logged; 0 unapproved bug filings | `action_trace.jsonl` + checkpoint audit |
| Artifact capture | 100% | Compiled plan, screenshots, action trace, step results, summary |
| Bug filing with approval | 100% | Checkpoint compliance |
| Seeded-bug/known-flow detection | >= 80% target (mode tracked separately) | Benchmark/eval reports |
| Sandbox bootstrap reliability (desktop, 2CPU/2048MB) | > 95% | Create/connect/ready without manual intervention |
| E2E smoke run time | < 20 min for small compiled plan | Full flow timing |

## 9. Getting Started
```bash
# E2B (self-hosted embed) — do NOT commit keys
export E2B_API_KEY="<set-locally>"
export E2B_API_URL="http://8.231.230.69:3000"
export E2B_DOMAIN="8.231.230.69.nip.io:3002"   # required for sandbox proxy on this embed (HTTP, no wildcard DNS)
export EXECUTOR_TYPE=e2b

# Gemini (planning + computer-use) — verify model IDs/support before implementation
export GEMINI_API_KEY="<set-locally>"           # or GOOGLE_API_KEY, per implementation
# export GEMINI_MODEL_PLANNER="<verified-model-id>"
# export GEMINI_MODEL_COMPUTER_USE="<verified-model-id>"

# Connection / sandbox
python scripts/test_e2b_connection.py
python scripts/test_e2b_hello.py

# Playwright runtime verification (optional adapter path; uses 2CPU/2048MB template)
/Users/skaparwan/github/testradius/apps/cell/.venv/bin/python scripts/e2b_playwright_runtime_verify.py

# Testplan-first flow (target state, as EPIC-E2B-008 lands)
# 1) Intake context (manual or MCP: Jira/Figma/GitHub/docs) -> normalized ContextBundle
# 2) Compile -> artifacts/run-<id>/compiled_test_plan.json (schema + quality gate + human review)
# 3) Execute ONLY the compiled plan in Gemini computer-use desktop sandbox (no raw context upload)
# python scripts/test_gemini_connection.py
# python scripts/compile_test_plan.py --context ... --sut https://testradius.dev
# python scripts/run_compiled_plan_e2b.py --plan artifacts/run-<id>/compiled_test_plan.json
```

## 10. Notes
- **Test plan is the product.** A compiled test plan must be detailed enough for Gemini computer-use to execute every step with no extra human instructions. Raw context is compiled in the control plane; the sandbox receives only the compiled plan + minimal non-secret runtime config.
- **MCP intake (recommended):** use MCP servers/connectors for Jira/Figma/GitHub/docs in Phase 1; normalize to a common `ContextBundle`; keep provenance/source refs; fall back to manual input. Do not leak secrets/tokens into plans, prompts, logs, or artifacts.
- **Self-hosted E2B (proven):** `E2B_DOMAIN=8.231.230.69.nip.io:3002` + HTTP proxy patch; prefer >=2CPU/2048MB for GUI/browser/computer-use. Playwright `install chromium` and baked-browser template finalization have been unreliable on this embed — use runtime bootstrap until fixed.
- **Gemini-first:** use Google Gen AI SDK / verified Gemini vision+action-capable models; `e2b-dev/open-computer-use` is a reference only (TestRadius owns schema, approvals, evidence, safety). Model IDs/capabilities change — verify before implementation.
- **Execution loop:** prefer structured per-step runner (Option B) using step `intent/target/success_criteria/fallback_instructions/evidence`; harness validates all proposed actions. Treat page content and model outputs as untrusted inputs.
- **No mandatory Playwright sandbox:** EPIC-E2B-003 is optional for deterministic regression/evals/fallback from the same compiled plan.
- Always cleanup sandboxes (`try/finally`); human approval before bug filing.

**Total:** 8 Epics, 28 Stories | Focus: testplan-first QA — MCP/manual context compiled into execution-grade plans, executed primarily by Gemini computer-use in E2B desktop sandboxes on GCP (Google credits), with human-approved bug filing.
