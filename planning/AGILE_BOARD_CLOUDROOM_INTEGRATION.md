# AGILE_BOARD_CLOUDROOM_INTEGRATION.md — Cloud Room Integration (Cloud VM Backend)

## 1. Overview

This board tracks the integration of Cloud Room (https://github.com/davidondrej/cloudroom) as a cloud VM backend for the TestRadius agentic testing harness. The goal is to **abstract the executor interface** and support Cloud Room as an alternative to local Playwright/Docker execution, while keeping the entire testing product (UI, orchestration, approvals, evidence, results, evals) intact.

**Strategy:** Option A from the analysis - Control-plane orchestration. Keep `harness/api/` + `apps/harness-ui/` as-is. Add executor abstraction with `LocalPlaywrightExecutor` and `CloudRoomExecutor`. Use Cloud Room's HTTP API + `room-cli` patterns to spawn threads/subagents that use `browser-harness` skill.

## 2. Goals and Non-Goals

### Goals
- **Executor abstraction**: Define `BaseExecutor` interface with consistent API for all executors
- **Cloud Room client**: Python client for Cloud Room HTTP API (auth, sessions, threads, receipts, artifacts)
- **Cloud Room executor**: Implement `CloudRoomExecutor` that spawns threads, injects test plans, collects artifacts
- **Feature flag**: Toggle between `local` and `cloudroom` executors via env/config
- **Artifact sync**: Download screenshots/video/traces from Cloud Room sandbox to local `artifacts/run-<id>/`
- **API integration**: Wire executor into orchestrator API (`harness/api/app.py`) 
- **UI compatibility**: No UI changes required - evidence/live/results flow unchanged
- **Evals support**: Enable parallel runs via subagents for seeded-bug benchmarks
- **Security**: Enforce egress allowlists/redaction in prompts, respect approvals

### Non-Goals
- Forking Cloud Room
- Replacing UI or orchestration logic
- Full migration of all execution to Cloud Room on day 1
- Building Cloud Room from scratch
- Changing the test plan schema

## 3. Epics

| Epic ID | Name | Outcome | Depends On |
| --- | --- | --- | --- |
| EPIC-CR001 | Executor Abstraction | Define BaseExecutor interface, refactor existing code to use it | - |
| EPIC-CR002 | Cloud Room Client | HTTP client for Cloud Room API with auth, sessions, threads, receipts | EPIC-CR001 |
| EPIC-CR003 | Cloud Room Executor | Implement executor that spawns threads and orchestrates via browser-harness | EPIC-CR002 |
| EPIC-CR004 | Orchestrator Integration | Wire CloudRoomExecutor into API/orchestrator with feature flags | EPIC-CR003 |
| EPIC-CR005 | Artifact Sync & Evidence | Download artifacts from sandbox, normalize to existing structure | EPIC-CR004 |
| EPIC-CR006 | Evals & Parallelism | Support subagent spawning for parallel eval runs | EPIC-CR005 |
| EPIC-CR007 | Testing, Docs & Hardening | E2E tests, docs, error handling, monitoring | EPIC-CR006 |

## 4. Stories

### EPIC-CR001 Executor Abstraction
#### STORY-CR001.1 — Define BaseExecutor Interface
- Status: Done | Deps: []
- Goal: Create abstract base class for executors with consistent API
- AC:
  - [x] `harness/execution/base.py` defines `BaseExecutor` ABC
  - [x] Methods: `prepare()`, `execute_plan()`, `get_status()`, `stop()`, `cleanup()`
  - [x] Return types match existing flow (evidence paths, logs, status)
  - [x] Type hints and docstrings
- Tasks:
  - [x] Create `harness/execution/__init__.py`
  - [x] Define `ExecutionResult`, `StepResult`, `ExecutionStatus` dataclasses
  - [x] Define `BaseExecutor` with abstract methods
  - [x] Add tests for interface
- Evidence: harness/execution/base.py, harness/execution/__init__.py, harness/execution/tests/test_base_executor.py

#### STORY-CR001.2 — Refactor Local Executor
- Status: Done | Deps: [STORY-CR001.1]
- Goal: Wrap existing Playwright execution in `LocalPlaywrightExecutor`
- AC:
  - [x] `harness/execution/local.py` implements `BaseExecutor`
  - [x] Uses `PlaywrightRealDriver` and existing logic
  - [x] Produces same artifacts structure as before
  - [x] All existing tests still pass
- Tasks:
  - [x] Extract execution logic from `runner/execute_testradius_real.py` or similar
  - [x] Implement LocalPlaywrightExecutor
  - [x] Update imports to use new interface
  - [x] Regression test
- Evidence: harness/execution/local.py, harness/execution/tests/test_local_executor.py

#### STORY-CR001.3 — Executor Factory & Config
- Status: Done | Deps: [STORY-CR001.2]
- Goal: Factory to instantiate executor based on config/feature flag
- AC:
  - [x] `harness/execution/factory.py` with `create_executor()`
  - [x] Config in `harness/config.py` for `EXECUTOR_TYPE`, `CLOUDROOM_URL`, etc.
  - [x] Environment variable support (`EXECUTOR=local|cloudroom`)
  - [x] Default to `local` for backward compat
- Tasks:
  - [x] Update `HarnessConfig`
  - [x] Create factory
  - [x] Add validation
  - [x] Tests
- Evidence: harness/execution/factory.py, harness/config.py, harness/execution/tests/test_factory.py

### EPIC-CR002 Cloud Room Client
#### STORY-CR002.1 — Cloud Room API Client Core
- Status: Done | Deps: [STORY-CR001.1]
- Goal: HTTP client for Cloud Room API with auth and error handling
- AC:
  - [x] `harness/integrations/cloudroom/client.py` with `CloudRoomClient`
  - [x] Auth via `Authorization: Bearer CLOUDROOM_TOKEN`
  - [x] Request ID generation and idempotency
  - [x] Handles 202 async responses and receipts
  - [x] Error handling for 401, 409, etc.
- Tasks:
  - [x] Read Cloud Room API docs patterns
  - [x] Implement HTTP client (httpx/requests)
  - [x] Add request/response models
  - [x] Tests with mocked responses
- Evidence: harness/integrations/cloudroom/client.py, harness/integrations/cloudroom/__init__.py, harness/integrations/cloudroom/tests/test_client_core.py

#### STORY-CR002.2 — Sessions & Threads API
- Status: Done | Deps: [STORY-CR002.1]
- Goal: Create/manage sessions and threads
- AC:
  - [x] `create_session()`, `get_session()`, `list_sessions()`
  - [x] `create_thread()`, `get_thread()`, `list_threads()`
  - [x] `spawn_subagent()` support
  - [x] Proper session ID format (`cr_*`)
- Tasks:
  - [x] Implement session methods
  - [x] Implement thread methods
  - [x] Add models
  - [x] Tests
- Evidence: harness/integrations/cloudroom/client.py, harness/integrations/cloudroom/tests/test_sessions_threads.py

#### STORY-CR002.3 — Commands, Receipts & Status Polling
- Status: Done | Deps: [STORY-CR002.2]
- Goal: Send commands, poll receipts until completion
- AC:
  - [x] Send commands with request_id
  - [x] Poll receipts with backoff
  - [x] Handle receipt states (accepted/delivered/completed/failed)
  - [x] Timeout handling
- Tasks:
  - [x] Command sending
  - [x] Receipt polling with retry
  - [x] Status helpers
  - [x] Tests
- Evidence: harness/integrations/cloudroom/client.py, harness/integrations/cloudroom/tests/test_commands_receipts.py

#### STORY-CR002.4 — Artifacts & Journal Access
- Status: Done | Deps: [STORY-CR002.3]
- Goal: Access session journal and download artifacts
- AC:
  - [x] Get session journal/events
  - [x] Download files from workspace
  - [x] List artifacts in sandbox
  - [x] Handle paths correctly
- Tasks:
  - [x] Journal API
  - [x] File download/listing
  - [x] Tests
- Evidence: harness/integrations/cloudroom/client.py, harness/integrations/cloudroom/tests/test_artifacts_journal.py

### EPIC-CR003 Cloud Room Executor
#### STORY-CR003.1 — Executor Scaffolding
- Status: Done | Deps: [STORY-CR001.1, STORY-CR002.4]
- Goal: Create CloudRoomExecutor skeleton implementing BaseExecutor
- AC:
  - [x] `harness/execution/cloudroom.py` implements BaseExecutor
  - [x] Constructor takes client/config
  - [x] Basic structure with TODOs for implementation
  - [x] Can be instantiated via factory
- Tasks:
  - [x] Create class structure
  - [x] Add config
  - [x] Wire to factory
  - [x] Basic tests
- Evidence: harness/execution/cloudroom.py, harness/execution/tests/test_cloudroom_executor.py

#### STORY-CR003.2 — Thread Creation & Plan Injection
- Status: Done | Deps: [STORY-CR003.1]
- Goal: Create thread with test plan injected as prompt/context
- AC:
  - [x] Convert harness test plan to prompt for agent
  - [x] Include target URL, constraints, egress rules
  - [x] Include instructions to use `browser-harness` skill
  - [x] Create thread with proper setup
- Tasks:
  - [x] Plan-to-prompt converter
  - [x] Prompt template with browser-harness instructions
  - [x] Thread creation flow
  - [x] Tests
- Evidence: harness/execution/cloudroom.py, harness/execution/tests/test_cloudroom_executor.py

#### STORY-CR003.3 — Browser-Harness Orchestration
- Status: Done | Deps: [STORY-CR003.2]
- Goal: Orchestrate agent to execute test steps using browser-harness
- AC:
  - [x] Send commands to execute test plan step by step
  - [x] Monitor progress via journal
  - [x] Handle agent actions
  - [x] Capture when execution completes
- Tasks:
  - [x] Command orchestration
  - [x] Progress tracking
  - [x] Completion detection
  - [x] Error handling
- Evidence: harness/execution/cloudroom.py, harness/execution/tests/test_cloudroom_executor.py

#### STORY-CR003.4 — Evidence Collection
- Status: Done | Deps: [STORY-CR003.3]
- Goal: Collect screenshots, video, traces from sandbox
- AC:
  - [x] List artifacts in workspace
  - [x] Download to local `artifacts/run-<id>/`
  - [x] Match expected structure (screenshots/, video, traces)
  - [x] Handle missing artifacts gracefully
- Tasks:
  - [x] Artifact discovery
  - [x] Download logic
  - [x] Normalization
  - [x] Tests
- Evidence: harness/execution/cloudroom.py, harness/execution/tests/test_cloudroom_executor.py

### EPIC-CR004 Orchestrator Integration
#### STORY-CR004.1 — API Integration
- Status: Done | Deps: [STORY-CR001.3, STORY-CR003.4]
- Goal: Wire executor into `harness/api/app.py`
- AC:
  - [x] API uses executor factory based on config
  - [x] `start_run` uses selected executor
  - [x] Status/progress updates flow through executor
  - [x] Backward compatible with existing behavior
- Tasks:
  - [x] Modify API to use executor
  - [x] Update run state management
  - [x] Add executor lifecycle
  - [x] Tests
- Evidence: harness/api/app.py

#### STORY-CR004.2 — Config & Environment
- Status: Done | Deps: [STORY-CR004.1]
- Goal: Add Cloud Room config to env/config system
- AC:
  - [x] `CLOUDROOM_URL`, `CLOUDROOM_TOKEN`, `CLOUDROOM_PROJECT` in config
  - [x] `.env.example` updated
  - [x] Validation for required vars when using cloudroom
  - [x] Documentation
- Tasks:
  - [x] Update config
  - [x] Update .env.example
  - [x] Add validation
  - [x] Docs
- Evidence: harness/config.py, .env.example

#### STORY-CR004.3 — Feature Flag & Mode Switching
- Status: Done | Deps: [STORY-CR004.2]
- Goal: Allow switching executors via env/UI indicator
- AC:
  - [x] `EXECUTOR_TYPE=local|cloudroom` env var
  - [x] API returns executor info in health/config
  - [x] UI can show executor mode (optional)
  - [x] Graceful fallback
- Tasks:
  - [x] Feature flag logic
  - [x] API exposure
  - [x] Tests
  - [x] Docs
- Evidence: harness/api/app.py, harness/execution/factory.py

### EPIC-CR005 Artifact Sync & Evidence
#### STORY-CR005.1 — Artifact Downloader
- Status: Done | Deps: [STORY-CR003.4]
- Goal: Robust artifact download from Cloud Room
- AC:
  - [x] Download all files from workspace artifacts dir
  - [x] Preserve structure
  - [x] Handle large files
  - [x] Resume on failure
- Tasks:
  - [x] Download implementation
  - [x] Progress tracking
  - [x] Error handling
  - [x] Tests
- Evidence: harness/integrations/cloudroom/artifacts.py, harness/integrations/cloudroom/tests/test_artifacts_download.py

#### STORY-CR005.2 — Evidence Normalization
- Status: Done | Deps: [STORY-CR005.1]
- Goal: Normalize artifacts to match existing evidence structure
- AC:
  - [x] Screenshots in `artifacts/run-<id>/screenshots/` or as expected
  - [x] Video as `.webm` in expected location
  - [x] Traces/logs in expected format
  - [x] Compatible with Evidence Gallery UI
- Tasks:
  - [x] Normalization logic
  - [x] Manifest generation/update
  - [x] Compatibility check
  - [x] Tests
- Evidence: harness/integrations/cloudroom/normalize.py, harness/integrations/cloudroom/tests/test_normalize.py

#### STORY-CR005.3 — Live State Translation
- Status: Done | Deps: [STORY-CR005.2]
- Goal: Translate Cloud Room journal/events to harness live state
- AC:
  - [x] Map journal events to steps
  - [x] Update progress
  - [x] Stream logs
  - [x] Show current step
- Tasks:
  - [x] Event mapping
  - [x] State translation
  - [x] API integration
  - [x] Tests
- Evidence: harness/integrations/cloudroom/live.py, harness/integrations/cloudroom/tests/test_live_translate.py

### EPIC-CR006 Evals & Parallelism
#### STORY-CR006.1 — Subagent Spawning
- Status: Done | Deps: [STORY-CR004.3]
- Goal: Spawn multiple subagents for parallel execution
- AC:
  - [x] API to spawn subagents
  - [x] Each runs in isolated thread/sandbox
  - [x] Can run same plan with different models
  - [x] Track all subagent runs
- Tasks:
  - [x] Subagent API integration
  - [x] Orchestration logic
  - [x] Tracking
  - [x] Tests
- Evidence: harness/integrations/cloudroom/subagents.py, harness/integrations/cloudroom/tests/test_subagents.py

#### STORY-CR006.2 — Parallel Eval Runs
- Status: Done | Deps: [STORY-CR006.1]
- Goal: Run evals across multiple models in parallel
- AC:
  - [x] Matrix execution (models x plans)
  - [x] Collect results from all
  - [x] Aggregate for comparison
  - [x] Works with existing evals framework
- Tasks:
  - [x] Matrix logic
  - [x] Result aggregation
  - [x] Integration with `harness/evals/`
  - [x] Tests
- Evidence: harness/integrations/cloudroom/subagents.py, harness/integrations/cloudroom/tests/test_subagents.py

#### STORY-CR006.3 — Automations Support
- Status: Done | Deps: [STORY-CR006.2]
- Goal: Trigger runs via Cloud Room automations
- AC:
  - [x] Can create automation via API
  - [x] Webhook/trigger support
  - [x] For scheduled regression/evals
  - [x] Documentation
- Tasks:
  - [x] Automation API
  - [x] Trigger handling
  - [x] Examples
  - [x] Docs
- Evidence: harness/integrations/cloudroom/client.py, harness/integrations/cloudroom/tests/test_automations.py

### EPIC-CR007 Testing, Docs & Hardening
#### STORY-CR007.1 — E2E Spike Test
- Status: Backlog | Deps: [STORY-CR005.3]
- Goal: End-to-end test against real Cloud Room instance
- AC:
  - [ ] Self-host Cloud Room locally or have instance
  - [ ] Run full flow: create run → approve → start with cloudroom executor
  - [ ] Execute against testradius.dev
  - [ ] Artifacts appear in Evidence Gallery
  - [ ] Results show correctly
- Tasks:
  - [ ] Setup Cloud Room instance
  - [ ] Create test script
  - [ ] Run E2E
  - [ ] Document findings

#### STORY-CR007.2 — Error Handling & Resilience
- Status: Backlog | Deps: [STORY-CR007.1]
- Goal: Robust error handling for Cloud Room failures
- AC:
  - [ ] Handle network failures
  - [ ] Handle timeout/receipt failures
  - [ ] Graceful cleanup on failure
  - [ ] Clear error messages
- Tasks:
  - [ ] Error cases
  - [ ] Retry logic
  - [ ] Cleanup
  - [ ] Tests

#### STORY-CR007.3 — Documentation
- Status: Backlog | Deps: [STORY-CR007.2]
- Goal: Complete documentation for Cloud Room integration
- AC:
  - [ ] README section on Cloud Room
  - [ ] Setup guide
  - [ ] Configuration docs
  - [ ] Troubleshooting
  - [ ] Architecture diagram
- Tasks:
  - [ ] Write docs
  - [ ] Update README
  - [ ] Add examples
  - [ ] Review

#### STORY-CR007.4 — Security Review
- Status: Backlog | Deps: [STORY-CR007.3]
- Goal: Security review of integration
- AC:
  - [ ] Egress enforcement in prompts
  - [ ] Secret redaction
  - [ ] Token handling secure
  - [ ] No secrets in logs
- Tasks:
  - [ ] Review against policy
  - [ ] Test redaction
  - [ ] Audit
  - [ ] Document

## 5. Execution Plan

### Phase 0: Prep & Spike (Week 1)
- **Goal:** Understand Cloud Room, set up instance
- **Stories:** STORY-CR007.1 (partial - setup)
- **Tasks:**
  1. Read Cloud Room docs thoroughly
  2. Self-host Cloud Room on local VM/ machine
  3. Get room-cli working
  4. Test browser-harness against testradius.dev manually
  5. Understand API auth and flows

### Phase 1: Abstraction (Week 1-2)
- **Goal:** Create executor interface without breaking existing code
- **Stories:** STORY-CR001.1, CR001.2, CR001.3
- **Tasks:**
  1. Define BaseExecutor
  2. Refactor local execution
  3. Add factory and config
  4. Ensure all tests pass

### Phase 2: Cloud Room Client (Week 2)
- **Goal:** Build client library
- **Stories:** STORY-CR002.1 through CR002.4
- **Tasks:**
  1. HTTP client with auth
  2. Sessions/threads
  3. Receipts/polling
  4. Artifacts/journal

### Phase 3: Executor Implementation (Week 2-3)
- **Goal:** Implement CloudRoomExecutor
- **Stories:** STORY-CR003.1 through CR003.4
- **Tasks:**
  1. Scaffolding
  2. Plan injection
  3. Orchestration
  4. Evidence collection

### Phase 4: Integration (Week 3)
- **Goal:** Wire into API and make it usable
- **Stories:** STORY-CR004.1-CR004.3, CR005.1-CR005.3
- **Tasks:**
  1. API integration
  2. Config
  3. Artifact sync
  4. Live state translation

### Phase 5: Evals & Polish (Week 4)
- **Goal:** Add eval support and harden
- **Stories:** STORY-CR006.1-CR006.3, CR007.1-CR007.4
- **Tasks:**
  1. Subagent spawning
  2. E2E testing
  3. Docs
  4. Security review

## 6. Definition of Done

For each story:
- [ ] All acceptance criteria met
- [ ] Code follows existing patterns and style
- [ ] Tests written and passing
- [ ] No regression in existing functionality
- [ ] Documentation updated if needed
- [ ] Committed with story ID (e.g., `STORY-CR001.1: ...`)
- [ ] PR reviewed and merged

For epic completion:
- [ ] All stories done
- [ ] Integration tested end-to-end
- [ ] Works with both local and cloudroom executors
- [ ] UI unchanged and functional
- [ ] Evidence flows correctly
- [ ] Docs updated

## 7. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Cloud Room API changes/alpha instability | High | Med | Pin to specific commit, add version checks, have local fallback |
| Artifact download issues | High | Med | Robust retry, multiple download methods, verify checksums |
| Browser-harness skill not available/configured | High | Med | Check capabilities API, graceful error, clear setup docs |
| Prompt engineering for reliable execution | High | High | Iterative testing, structured prompts, validation of agent output |
| Network/firewall issues with self-hosted Cloud Room | Med | Med | Clear networking docs, health checks |
| Token/security exposure | High | Low | Use env vars, never log tokens, follow redaction |
| Breaking existing UI/API | High | Low | Feature flag defaults to local, extensive regression testing |

## 8. Success Metrics

- [ ] Can switch executor via `EXECUTOR_TYPE=cloudroom` env var
- [ ] End-to-end run against testradius.dev works with Cloud Room
- [ ] Artifacts (screenshots/video/traces) appear in Evidence Gallery
- [ ] Live execution shows progress correctly
- [ ] Results/Reports render identically
- [ ] Can spawn 3 parallel subagent runs for evals
- [ ] No changes to UI code required
- [ ] All existing tests still pass
- [ ] Documentation complete

## 9. Quick Start Commands

```bash
# Phase 0: Setup Cloud Room
curl -fsSL https://cloudroom.dev/install.sh -o install.sh
sudo bash install.sh

# Get token from /etc/cloudroom/core.env or as instructed
export CLOUDROOM_URL=http://127.0.0.1:9840
export CLOUDROOM_TOKEN=...

# Test client
cd /Users/skaparwan/github/testradius
python -c "from harness.integrations.cloudroom import CloudRoomClient; print('ok')"

# Run with cloudroom executor
EXECUTOR_TYPE=cloudroom python -m harness testradius --target https://testradius.dev
```

## 10. References

- [Cloud Room GitHub](https://github.com/davidondrej/cloudroom)
- [Cloud Room Docs](https://github.com/davidondrej/cloudroom/tree/main/core/docs)
- [Browser Harness Skill](https://github.com/davidondrej/cloudroom/tree/main/skills/browser-harness)
- [API Reference](https://raw.githubusercontent.com/davidondrej/cloudroom/main/core/docs/api.md)
- [Setup Guide](https://raw.githubusercontent.com/davidondrej/cloudroom/main/core/docs/setup.md)
- [TestRadius AGILE_BOARD_UI_HARDENING.md](./AGILE_BOARD_UI_HARDENING.md)
- [TestRadius README](../README.md)
