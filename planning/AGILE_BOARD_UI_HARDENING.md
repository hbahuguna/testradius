# AGILE_BOARD_UI_HARDENING.md — TestRadius Agentic Testing Harness UI + Hardening

## 1. Overview

This board focuses on building a task-centric UI for the TestRadius agentic testing harness (not a pure chat UI) and hardening the core harness for reliability, safety, and operability. The UI should expose plan review, live execution, evidence gallery (screenshots/video/traces), assertions, and human checkpoints. Hardening covers orchestration, real browser execution, sandboxing, policy/guards, evals, and observability.

## 2. Goals and Non-Goals

### Goals
- Task-centric UI: New Run form, Plan Review, Live Run, Evidence Center, Results/Report
- Real execution visibility: live logs, current step, screenshots, video preview
- Plan as first-class: review/edit Gemini plan, checkpoint before execution
- Evidence-first: gallery, video player for .webm, traces, console/network
- Hardening: robust orchestrator, retries/timeouts, stop conditions, error handling
- Sandboxing: run Playwright in isolated env (Docker), artifacts isolation
- Policy/guards: checkpoints, redaction, egress allowlists
- Observability: run manifest, structured logs, eval hooks

### Non-Goals
- Full chat-first clone of OpenCode
- Multi-tenant SaaS UI polish on day 1
- Mobile app
- Replacing CLI (keep CLI-first)

## 3. Epics

| Epic ID | Name | Outcome | Depends On |
| --- | --- | --- | --- |
| EPIC-H001 | UI Foundation (Task-Centric Shell) | App shell, routing, layout, API client, auth stub | - |
| EPIC-H002 | New Run & Plan Review | Form + Gemini plan generation + checkpoint | EPIC-H001 |
| EPIC-H003 | Live Execution & Orchestration | Real-time run state, step progress, logs, stop/resume | EPIC-H002 |
| EPIC-H004 | Evidence Center | Gallery, video player, traces, console/network, downloads | EPIC-H003 |
| EPIC-H005 | Results, Assertions & Reporting | Per-test results, assertions, export, share | EPIC-H004 |
| EPIC-H006 | Harness Orchestration Hardening | State machine, timeouts, retries, stop conditions, recovery | - |
| EPIC-H007 | Browser/Sandbox Hardening | Real Playwright stability, video/traces, Docker sandbox, isolation | EPIC-H006 |
| EPIC-H008 | Policy, Security & Guards | Checkpoints, redaction, egress, rate limits, secrets | EPIC-H006 |
| EPIC-H009 | Evals, Observability & Resilience | Benchmarks, logs/metrics, tracing, failure analysis | EPIC-H007, EPIC-H008 |

## 4. Stories

### EPIC-H001 UI Foundation
#### STORY-H001.1 — UI Scaffolding (Vite + React + TS)
- Status: Done | Deps: []
- Goal: apps/harness-ui scaffold, routing, layout
- AC: [x] `pnpm dev` works on :53100 (HTTP 200), [x] shell renders with sidebar/topbar/5 routes, [x] `pnpm typecheck` + `pnpm build` green
- Tasks: [x] scaffold (apps/harness-ui), [x] hash router (runs/new-run/evidence/results/settings), [x] layout (Sidebar + TopBar + responsive), [x] styles
- Evidence: apps/harness-ui/ (src/App.tsx, components/, pages/, styles.css), wired into pnpm-workspace.yaml

#### STORY-H001.2 — API Client & Types
- Status: Backlog | Deps: [STORY-H001.1]
- Goal: Typed API client for harness endpoints (plans/runs/evidence)
- AC: types match reports/artifacts
- Tasks: client, types, mocks

### EPIC-H002 New Run & Plan Review
#### STORY-H002.1 — New Run Form
- Status: Backlog | Deps: [STORY-H001.2]
- Goal: Target URL, goal/context, model selection (Gemini)
- AC: form validates, creates run

#### STORY-H002.2 — Plan Review & Checkpoint
- Status: Backlog | Deps: [STORY-H002.1]
- Goal: Review/edit test plan, require approval before execute
- AC: checkpoint blocks execute until approved

### EPIC-H003 Live Execution
#### STORY-H003.1 — Live Run View
- Status: Backlog | Deps: [STORY-H002.2]
- Goal: Step list, current step, status, logs
- AC: real-time updates

#### STORY-H003.2 — Orchestrator API
- Status: Backlog | Deps: [STORY-H003.1]
- Goal: API to start/stop/run real browser execution
- AC: endpoints work with harness runners

### EPIC-H004 Evidence Center
#### STORY-H004.1 — Evidence Gallery & Video
- Status: Backlog | Deps: [STORY-H003.2]
- Goal: Screenshots grid, video player for .webm, lightbox
- AC: view evidence per test case

#### STORY-H004.2 — Traces & Console/Network
- Status: Backlog | Deps: [STORY-H004.1]
- Goal: Trace viewer, console/network logs
- AC: inspect traces

### EPIC-H005 Results & Reporting
#### STORY-H005.1 — Assertions & Results
- Status: Backlog | Deps: [STORY-H004.2]
- Goal: Per-test pass/fail, assertions list
- AC: results view

#### STORY-H005.2 — Export Report
- Status: Backlog | Deps: [STORY-H005.1]
- Goal: Export JSON/HTML report
- AC: downloadable report

### EPIC-H006 Orchestration Hardening
#### STORY-H006.1 — State Machine & Stop Conditions
- Status: Backlog | Deps: []
- Goal: Explicit states, terminal conditions, budgets
- AC: stops on done/failed/timeout/budget
- Tasks: FSM, conditions, tests

#### STORY-H006.2 — Retries, Timeouts, Backoff
- Status: Backlog | Deps: [STORY-H006.1]
- Goal: Retry policy, step/tool timeouts
- AC: retries with backoff

### EPIC-H007 Browser/Sandbox Hardening
#### STORY-H007.1 — Playwright Stability
- Status: Backlog | Deps: [STORY-H006.2]
- Goal: Stealth/waits, navigation safety, error handling
- AC: stable runs

#### STORY-H007.2 — Docker Sandbox Execution
- Status: Backlog | Deps: [STORY-H007.1]
- Goal: Run in Playwright container, artifact volume mounts
- AC: isolated execution

### EPIC-H008 Policy & Guards
#### STORY-H008.1 — Checkpoints & Approval Flow
- Status: Backlog | Deps: [STORY-H006.1]
- Goal: Enforce approvals, audit log
- AC: blocks without approval

#### STORY-H008.2 — Redaction & Egress
- Status: Backlog | Deps: [STORY-H008.1]
- Goal: Redact secrets, egress allowlists
- AC: leaks blocked

### EPIC-H009 Evals & Observability
#### STORY-H009.1 — Run Manifest & Logging
- Status: Backlog | Deps: [STORY-H007.2]
- Goal: Structured logs, run manifest schema
- AC: traceable runs

#### STORY-H009.2 — Evals & Failure Analysis
- Status: Backlog | Deps: [STORY-H009.1]
- Goal: Benchmark runs, failure categorization
- AC: eval reports

## 5. Execution Protocol
1. Pick highest priority unblocked story
2. Read AC, verify locally
3. Implement in task order
4. DoD: AC pass, executable check, demo, board updated
5. Commit with story ID

## 6. First 3 Stories
STORY-H001.1, STORY-H001.2, STORY-H002.1
