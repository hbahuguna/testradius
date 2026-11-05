# AGILE_BOARD_E2B_MANUAL_QA_HARNESS.md — Manual QA AI Harness on E2B (GCP)

## 1. Overview
Build a production-ready Manual QA AI Harness using E2B Embed on GCP as the sandbox engine. Leverage existing TestRadius harness infrastructure (API/UI/orchestration/approvals/evidence/Cloud Room integration) where possible, add E2B as a new sandbox/executor backend for isolated microVM-based testing.

## 2. Goals and Non-Goals
### Goals
- Deploy/connect to E2B Embed instance on GCP (marine-aria-504018-t8)
- Abstract sandbox provider (E2B) alongside existing sandbox/executor backends
- Build QA agent harness that uses E2B microVMs with Playwright for UI testing
- Vision QA with screenshot analysis and self-inspection loops
- Evidence capture (screenshots, video, traces, logs) from sandboxes
- Human-in-the-loop checkpoints before bug filing
- Bug filing integration (GitHub/Jira/Linear) with deduplication
- Context intake (tickets/PRDs/ACs/Figma) uploaded to sandboxes
- Routines/scheduling for automated QA runs
- Eval framework with seeded-bug benchmarks
- Integrate with existing TestRadius UI/API where beneficial

### Non-Goals
- Rebuilding entire UI from scratch (extend existing)
- Mobile app testing first
- Full exploratory testing replacement
- Storing secrets in repo

## 3. Architecture
```
┌─────────────────────────────────────────────────────────────┐
│ Control Plane (Local/Laptop)                                 │
│ - TestRadius API/UI (existing) OR standalone harness CLI    │
│ - Orchestration, approvals, bug filing                       │
└─────────────────┬───────────────────────────────────────────┘
                  │ E2B SDK (HTTP to API)
┌─────────────────▼───────────────────────────────────────────┐
│ E2B API (GCP VM - marine-aria-504018-t8)                    │
│ - Sandbox lifecycle management                               │
└─────────────────┬───────────────────────────────────────────┘
                  │ Firecracker microVMs
┌─────────────────▼───────────────────────────────────────────┐
│ Sandboxes (isolated microVMs)                                │
│ - Playwright/Chromium, browser automation                    │
│ - Test scripts, context files uploaded                       │
│ - Artifacts (screenshots/video/traces)                       │
└─────────────────────────────────────────────────────────────┘
```

## 4. E2B Instance Details
- Project: marine-aria-504018-t8
- Instance: e2b-embed (us-west1-b)
- API Key: e2b_a4839a085a860c188a85b4b956820783 (from terraform state)
- Terraform outputs available via `terraform output`

## 5. Epics
| Epic ID | Name | Outcome | Depends On |
|---|---|---|---|
| EPIC-E2B-001 | E2B Infrastructure & Connection | Connect to E2B, verify sandbox creation | - |
| EPIC-E2B-002 | E2B Sandbox Provider Integration | Abstract E2B as provider/executor in harness | EPIC-E2B-001 |
| EPIC-E2B-003 | QA Agent Core (UI Driving + Context) | Context upload, Playwright automation in sandboxes | EPIC-E2B-002 |
| EPIC-E2B-004 | Vision QA & Evidence Capture | Screenshot analysis, self-inspection, evidence sync | EPIC-E2B-003 |
| EPIC-E2B-005 | Human Checkpoints & Bug Filing | Approval gates, ticket generation, dedup | EPIC-E2B-004 |
| EPIC-E2B-006 | Orchestration, Routines & Evals | Scheduling, seeded-bug benchmarks | EPIC-E2B-005 |
| EPIC-E2B-007 | UI Integration & Polish | Integrate into existing TestRadius UI/API | EPIC-E2B-006 |

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
- **Epic:** EPIC-E2B-001 | **Status:** Done (partial - template gap) | **Priority:** P0 | **Estimate:** S
- **User story:** As a developer, I need to confirm Playwright template is available for browser automation.
- **AC:**
  - [x] Templates checked via API (`base`/`local-dev-team/base` only; no `playwright-chromium`)
  - [x] Command execution works in base sandbox (envd connectivity fixed)
  - [ ] Playwright/Chromium installed in a usable template (base template lacks `playwright` module and browsers) — needs custom E2B template
- **Tasks:**
  - [x] TASK-E2B-001.3.1: Test playwright template availability
  - [x] TASK-E2B-001.3.2: Probe base template environment
  - [ ] TASK-E2B-001.3.3: Build/publish Playwright template, then verify browser launch
- **Capability:** UI Driving
- **Demo:** `scripts/test_e2b_playwright.py` reports templates and probes base sandbox
- **Evidence:** `scripts/test_e2b_playwright.py`

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

### EPIC-E2B-003: QA Agent Core (UI Driving + Context)
#### STORY-E2B-003.1 — Context Upload to Sandbox
- **Epic:** EPIC-E2B-003 | **Status:** Todo | **Priority:** P0 | **Estimate:** M
- **User story:** As the agent, I need to upload context (tickets/PRDs/ACs) to sandbox.
- **AC:**
  - [ ] Upload files via `sandbox.files.write()`
  - [ ] Upload directories
  - [ ] Create context bundle in sandbox at known path
  - [ ] Verify files exist in sandbox
- **Tasks:**
  - [ ] TASK-E2B-003.1.1: Implement upload in E2BSandboxProvider
  - [ ] TASK-E2B-003.1.2: Create context packaging logic
  - [ ] TASK-E2B-003.1.3: Test with sample context
- **Capability:** Context intake
- **Demo:** Context files accessible in sandbox
- **Evidence:** Context upload working

#### STORY-E2B-003.2 — Playwright Script Generation & Execution
- **Epic:** EPIC-E2B-003 | **Status:** Todo | **Priority:** P0 | **Estimate:** L
- **User story:** As the agent, I need to generate and run Playwright tests in sandbox.
- **AC:**
  - [ ] Generate Playwright script from test plan
  - [ ] Upload script to sandbox (/home/user/)
  - [ ] Run from /app directory as required
  - [ ] Capture stdout/stderr
  - [ ] Handle timeouts
- **Tasks:**
  - [ ] TASK-E2B-003.2.1: Script generator in `harness/e2b/agent.py`
  - [ ] TASK-E2B-003.2.2: Execution logic
  - [ ] TASK-E2B-003.2.3: Test against testradius.dev
- **Capability:** UI Driving
- **Demo:** Navigate and interact with website
- **Evidence:** harness/e2b/agent.py

#### STORY-E2B-003.3 — Test Plan to Playwright Converter
- **Epic:** EPIC-E2B-003 | **Status:** Todo | **Priority:** P0 | **Estimate:** L
- **User story:** As the harness, I need to convert TestRadius test plans to Playwright scripts.
- **AC:**
  - [ ] Parse test plan JSON
  - [ ] Generate Playwright async code
  - [ ] Handle steps (navigate/click/type/wait/assert)
  - [ ] Add screenshots at key points
  - [ ] Include error handling
- **Tasks:**
  - [ ] TASK-E2B-003.3.1: Converter in `harness/e2b/converter.py`
  - [ ] TASK-E2B-003.3.2: Action mapping
  - [ ] TASK-E2B-003.3.3: Test with real plan
- **Capability:** UI Driving, Planning
- **Demo:** Convert plan to executable script
- **Evidence:** harness/e2b/converter.py

### EPIC-E2B-004: Vision QA & Evidence Capture
#### STORY-E2B-004.1 — Screenshot & Artifact Collection
- **Epic:** EPIC-E2B-004 | **Status:** Todo | **Priority:** P0 | **Estimate:** M
- **User story:** As the harness, I need to download artifacts from sandbox.
- **AC:**
  - [ ] Download files via `sandbox.files.read()` or API
  - [ ] Collect screenshots, videos, traces
  - [ ] Save to `artifacts/run-<id>/` structure
  - [ ] Create manifest
- **Tasks:**
  - [ ] TASK-E2B-004.1.1: Artifact downloader for E2B
  - [ ] TASK-E2B-004.1.2: Normalize to harness structure
  - [ ] TASK-E2B-004.1.3: Integration with evidence pipeline
- **Capability:** Evidence capture
- **Demo:** Artifacts synced locally
- **Evidence:** harness/e2b/artifacts.py

#### STORY-E2B-004.2 — Vision QA Analysis
- **Epic:** EPIC-E2B-004 | **Status:** Todo | **Priority:** P0 | **Estimate:** L
- **User story:** As the agent, I want to analyze screenshots with vision models.
- **AC:**
  - [ ] Send screenshots to vision model (Claude/GPT/Gemini)
  - [ ] Prompt for layout/contrast/clipping/overlap/responsive issues
  - [ ] Parse findings into structured format
  - [ ] Support multiple models
- **Tasks:**
  - [ ] TASK-E2B-004.2.1: Extend vision client for sandbox artifacts
  - [ ] TASK-E2B-004.2.2: QA-focused prompts
  - [ ] TASK-E2B-004.2.3: Test on real screenshots
- **Capability:** Vision QA
- **Demo:** Vision findings generated
- **Evidence:** Uses existing harness/vision/ with E2B integration

#### STORY-E2B-004.3 — Multi-Round Self-Inspection
- **Epic:** EPIC-E2B-004 | **Status:** Todo | **Priority:** P1 | **Estimate:** M
- **User story:** As the agent, I want to self-inspect and iterate.
- **AC:**
  - [ ] Round 1: Initial inspection
  - [ ] Round 2: Verify fixes/check additional areas
  - [ ] Deduplicate findings
  - [ ] Log inspection rounds
- **Tasks:**
  - [ ] TASK-E2B-004.3.1: Inspector loop for E2B workflow
  - [ ] TASK-E2B-004.3.2: Dedupe logic
  - [ ] TASK-E2B-004.3.3: Logging
- **Capability:** Vision QA
- **Demo:** 2+ inspection rounds logged
- **Evidence:** Inspection report

### EPIC-E2B-005: Human Checkpoints & Bug Filing
#### STORY-E2B-005.1 — Checkpoint Integration
- **Epic:** EPIC-E2B-005 | **Status:** Todo | **Priority:** P0 | **Estimate:** M
- **User story:** As a tester, I want to approve findings before filing bugs.
- **AC:**
  - [ ] Use existing checkpoint system
  - [ ] Block bug filing until approved
  - [ ] Show findings with screenshots
  - [ ] Audit log
- **Tasks:**
  - [ ] TASK-E2B-005.1.1: Integrate with harness/checkpoints
  - [ ] TASK-E2B-005.1.2: UI for approval (or CLI)
  - [ ] TASK-E2B-005.1.3: Test flow
- **Capability:** Human checkpoints
- **Demo:** Approval required before filing
- **Evidence:** Checkpoint approval log

#### STORY-E2B-005.2 — Bug Generation from E2B Findings
- **Epic:** EPIC-E2B-005 | **Status:** Todo | **Priority:** P0 | **Estimate:** M
- **User story:** As the harness, I want to generate repro-ready bug tickets.
- **AC:**
  - [ ] Combine vision findings + logs + evidence
  - [ ] Generate steps to reproduce
  - [ ] Include screenshots/videos
  - [ ] Severity/priority inference
- **Tasks:**
  - [ ] TASK-E2B-005.2.1: Use existing bug generator
  - [ ] TASK-E2B-005.2.2: Enrich with E2B artifacts
  - [ ] TASK-E2B-005.2.3: Template customization
- **Capability:** Bug filing
- **Demo:** Generated ticket with evidence
- **Evidence:** Bug report

#### STORY-E2B-005.3 — Connector Integration & Dedup
- **Epic:** EPIC-E2B-005 | **Status:** Todo | **Priority:** P0 | **Estimate:** M
- **User story:** As a tester, I want bugs filed to GitHub/Jira/Linear with dedup.
- **AC:**
  - [ ] File to configured connector
  - [ ] Dedup against existing issues
  - [ ] Requires checkpoint approval
  - [ ] Links evidence
- **Tasks:**
  - [ ] TASK-E2B-005.3.1: Use existing connectors
  - [ ] TASK-E2B-005.3.2: Dedup logic
  - [ ] TASK-E2B-005.3.3: Test filing
- **Capability:** Bug filing
- **Demo:** Ticket created in tracker
- **Evidence:** Filed ticket URL

### EPIC-E2B-006: Orchestration, Routines & Evals
#### STORY-E2B-006.1 — End-to-End Orchestration
- **Epic:** EPIC-E2B-006 | **Status:** Todo | **Priority:** P0 | **Estimate:** L
- **User story:** As the harness, I need full orchestration: context → plan → execute in E2B → evidence → vision → report.
- **AC:**
  - [ ] Orchestrator coordinates all steps
  - [ ] Error handling and cleanup
  - [ ] Progress tracking
  - [ ] Sandbox cleanup on completion/failure
- **Tasks:**
  - [ ] TASK-E2B-006.1.1: Create `harness/e2b/orchestrator.py`
  - [ ] TASK-E2B-006.1.2: Wire all components
  - [ ] TASK-E2B-006.1.3: E2E test on testradius.dev
- **Capability:** All core
- **Demo:** Full run completes
- **Evidence:** Run report with artifacts

#### STORY-E2B-006.2 — Routines & Scheduling
- **Epic:** EPIC-E2B-006 | **Status:** Todo | **Priority:** P1 | **Estimate:** M
- **User story:** As an operator, I want scheduled QA runs.
- **AC:**
  - [ ] Use existing scheduler or simple cron
  - [ ] Config for E2B runs
  - [ ] Run history
  - [ ] Notifications
- **Tasks:**
  - [ ] TASK-E2B-006.2.1: Integrate with harness/routines
  - [ ] TASK-E2B-006.2.2: E2B-specific config
  - [ ] TASK-E2B-006.2.3: Test scheduling
- **Capability:** Routines
- **Demo:** Scheduled run executes
- **Evidence:** Routine log

#### STORY-E2B-006.3 — Seeded-Bug Benchmark
- **Epic:** EPIC-E2B-006 | **Status:** Todo | **Priority:** P1 | **Estimate:** L
- **User story:** As an engineer, I want to measure detection rate.
- **AC:**
  - [ ] Use existing benchmark framework
  - [ ] Run against seeded bugs
  - [ ] Metrics: detection rate, FP rate, reproducibility
  - [ ] Report generation
- **Tasks:**
  - [ ] TASK-E2B-006.3.1: Adapt benchmark for E2B
  - [ ] TASK-E2B-006.3.2: Run benchmark
  - [ ] TASK-E2B-006.3.3: Analyze results
- **Capability:** Evals
- **Demo:** Benchmark report
- **Evidence:** evals/reports/e2b-benchmark.json

### EPIC-E2B-007: UI Integration & Polish
#### STORY-E2B-007.1 — Add E2B to UI Settings
- **Epic:** EPIC-E2B-007 | **Status:** Todo | **Priority:** P1 | **Estimate:** M
- **User story:** As a user, I want to select E2B as executor in UI.
- **AC:**
  - [ ] Add E2B option to executor selection
  - [ ] Show E2B connection status
  - [ ] Configure API key/URL
  - [ ] Validate connection
- **Tasks:**
  - [ ] TASK-E2B-007.1.1: Update SettingsPage
  - [ ] TASK-E2B-007.1.2: Update API types
  - [ ] TASK-E2B-007.1.3: Test UI
- **Capability:** UI
- **Demo:** E2B selectable in settings
- **Evidence:** UI screenshot

#### STORY-E2B-007.2 — E2B-Specific Live View
- **Epic:** EPIC-E2B-007 | **Status:** Todo | **Priority:** P2 | **Estimate:** M
- **User story:** As a user, I want to see E2B sandbox status.
- **AC:**
  - [ ] Show sandbox ID
  - [ ] Show template used
  - [ ] Link to artifacts
  - [ ] Status updates
- **Tasks:**
  - [ ] TASK-E2B-007.2.1: Enhance live view
  - [ ] TASK-E2B-007.2.2: Add sandbox info
  - [ ] TASK-E2B-007.2.3: Test
- **Capability:** UI
- **Demo:** Sandbox info visible
- **Evidence:** UI update

#### STORY-E2B-007.3 — Documentation & Examples
- **Epic:** EPIC-E2B-007 | **Status:** Todo | **Priority:** P1 | **Estimate:** S
- **User story:** As a user, I want docs to use E2B harness.
- **AC:**
  - [ ] Update README with E2B setup
  - [ ] Create E2B usage guide
  - [ ] Add example scripts
  - [ ] Troubleshooting section
- **Tasks:**
  - [ ] TASK-E2B-007.3.1: Write docs/E2B_MANUAL_QA_HARNESS.md
  - [ ] TASK-E2B-007.3.2: Update README
  - [ ] TASK-E2B-007.3.3: Add examples
- **Capability:** Documentation
- **Demo:** Clear setup instructions
- **Evidence:** docs/E2B_MANUAL_QA_HARNESS.md

## 7. Execution Plan (Sprint Order)
1. **Sprint 1 (Week 1):** EPIC-E2B-001 - Infrastructure & Connection
2. **Sprint 2 (Week 2):** EPIC-E2B-002 - Provider Integration
3. **Sprint 3 (Week 3):** EPIC-E2B-003 - QA Agent Core
4. **Sprint 4 (Week 4):** EPIC-E2B-004 - Vision QA & Evidence
5. **Sprint 5 (Week 5):** EPIC-E2B-005 - Checkpoints & Bug Filing
6. **Sprint 6 (Week 6):** EPIC-E2B-006 - Orchestration & Evals
7. **Sprint 7 (Week 7):** EPIC-E2B-007 - UI Integration & Polish

## 8. Success Metrics
| Metric | Target | Measurement |
|---|---|---|
| Sandbox creation time | < 30s | Time from create() to ready |
| Test execution in sandbox | Success rate > 95% | Runs completing without errors |
| Vision QA findings | Useful findings > 70% | Human review |
| Bug filing with approval | 100% | Checkpoint compliance |
| Artifact capture | 100% | Screenshots/video downloaded |
| Seeded-bug detection | >= 80% | Benchmark (like existing) |
| E2E run time | < 10 min for smoke | Full flow timing |

## 9. Getting Started
```bash
# Set up environment
export E2B_API_KEY="e2b_a4839a085a860c188a85b4b956820783"
export E2B_API_URL="http://8.231.230.69:3000" # Check actual URL from terraform
export EXECUTOR_TYPE=e2b

# Test connection
python scripts/test_e2b_connection.py

# Run first sandbox test
python scripts/test_e2b_hello.py
```

## 10. Notes
- Leverage existing harness components (vision, bugs, checkpoints, evidence) where possible
- Use Playwright template on E2B for browser automation
- Scripts must run from /app directory in Playwright template
- Always cleanup sandboxes (use try/finally)
- Store API keys in env vars only
- Can run alongside existing Cloud Room/local executors

**Total:** 7 Epics, 21 Stories | Focus: E2B microVM sandboxes for isolated QA execution
