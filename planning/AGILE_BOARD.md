# AGILE_BOARD.md — Vertical Manual Software-Testing Agent Harness

## 1. Overview
A vertical agent harness for manual software testing that automates repetitive, observable, evidence-heavy QA while keeping testers in the loop. Harness-first (tools > model), context engineering, human checkpoints, multi-model, eval-backed, and routinized. Initial vertical: **web SaaS regression and visual QA for design-heavy applications**.

## 2. Goals and non-goals
### Goals
- Thin vertical slice: sandbox → context → drive → evidence → report
- Vision QA + self-inspection
- Repro-ready bug filing with dedup + approval
- Risk-based planning + charters
- Scheduled routines as skills
- Evals (seeded bugs, FP, reproducibility, trust)

### Non-goals
- Generic framework day 1, full exploratory replacement, single provider, secrets in board, Helm production claim, mobile/a11y first

## 3. Success metrics
| Metric | Target | Measurement |
|---|---|---|
| Seeded-bug detection | >=80% (50 bugs) | `harness eval seeded-bugs` |
| False positives | <=15% | Human review/10 runs |
| Reproducibility | >=90% | Dual run diff |
| Time-to-first-evidence | <3 min | Trigger→artifact |
| Checkpoint adoption | 100% before filing | Policy gate |
| Routine success | >=95% | Scheduler |
| Trust score | >=4/5 | Survey |

## 4. Risks and mitigations
See full board content.

## 5. Epics
| Epic ID | Name | Outcome | Depends On |
|---|---|---|---|
| EPIC-001 | Foundation and context intake | Scaffold, AGENTS.md, sandbox, context schema | - |
| EPIC-002 | First vertical slice: smoke test + evidence | E2E smoke + evidence | EPIC-001 |
| EPIC-003 | Visual QA and self-inspection | Vision + rounds | EPIC-002 |
| EPIC-004 | Bug filing and human checkpoints | Tickets + approval gates | EPIC-003 |
| EPIC-005 | Test planning and risk-based scope | Plans + charters | EPIC-004 |
| EPIC-006 | Routines and deployment | Scheduled + skills | EPIC-005 |
| EPIC-007 | Evals and continuous improvement | Benchmarks + AB tests | EPIC-006 |
| EPIC-008 | Expansion verticals | Mobile/a11y/exploratory | EPIC-007 |

## 6. Stories
### EPIC-001
#### STORY-001.1 — Bootstrap harness repository and AGENTS.md
- **Epic:** EPIC-001 | **Status:** Done | **Deps:** []
- **User story:** As operator, I want scaffold + rules
- **Vertical slice:** Dirs, AGENTS.md, CLI skeleton
- **AC:** [x] board exists, [x] AGENTS.md, [x] `harness --help` works
- **Tasks:** [x] 1.1.1 scaffold, [x] 1.1.2 AGENTS.md, [x] 1.1.3 CLI, [x] 1.1.4 README
- **Capability:** Context intake (foundation)
- **Demo:** CLI help output - `python -m harness --help`
- **Eval:** Structure check
- **Evidence:** harness/cli.py, AGENTS.md, README_HARNESS.md committed
- **DoD:** Done with evidence

#### STORY-001.2 — Context bundle schema and loader
- **Epic:** EPIC-001 | **Status:** Done | **Deps:** [STORY-001.1]
- **User story:** As a tester, I want ticket/PRD/Figma/ACs/logs bundled so the agent has full context.
- **Vertical slice:** Define `ContextBundle` schema, loader CLI (`harness context validate`), validate inputs.
- **AC:** [x] Schema defined (pydantic), [x] Loader ingests ticket/ACs/links, [x] Executable: `harness context validate sample.json` passes
- **Tasks:** [x] TASK-001.2.1: Schema design, [x] TASK-001.2.2: Loader implementation, [x] TASK-001.2.3: Validation + tests
- **Capability:** Context intake
- **Demo:** `samples/context_sample.json` validates successfully
- **Eval hook:** Context completeness score
- **Evidence:** harness/context/schema.py, harness/context/loader.py, samples/context_sample.json
- **Definition of done:** Validation passes, demo artifact saved

#### STORY-001.3 — Sandbox skeleton (Docker Compose)
- **Epic:** EPIC-001 | **Status:** Done | **Deps:** [STORY-001.1]
- **User story:** As a harness operator, I want an isolated sandbox so tests run reproducibly.
- **Vertical slice:** `docker-compose.sandbox.yml` with browser (playwright), seeded app stub, test users.
- **AC:** [x] Compose starts/stops cleanly, [x] Playwright can reach stub app, [x] Executable: `docker compose -f docker-compose.sandbox.yml up -d && curl http://localhost:8080/health`
- **Tasks:** [x] TASK-001.3.1: Compose file, [x] TASK-001.3.2: Seed data, [x] TASK-001.3.3: Health check
- **Capability:** Sandboxing
- **Demo:** Sandbox compose + stub app
- **Eval hook:** Sandbox reset time
- **Evidence:** docker-compose.sandbox.yml, sandbox/stub/
- **Definition of done:** Sandbox boots, verified

### EPIC-002
#### STORY-002.1 — UI driver (Playwright)
- **Epic:** EPIC-002 | **Status:** Done | **Deps:** [STORY-001.3]
- **User story:** As the agent, I want to navigate/click/type/assert so I can drive UI.
- **Vertical slice:** `harness/driver` with navigate/click/type/assert + screenshots.
- **AC:** [x] Login flow driven against sandbox, [x] Screenshot captured, [x] Executable test passes
- **Tasks:** [x] TASK-002.1.1: Driver wrapper, [x] TASK-002.1.2: Basic actions, [x] TASK-002.1.3: Tests
- **Capability:** UI driving
- **Demo:** Screenshot of login (artifacts/login.png)
- **Eval hook:** Action success rate
- **Evidence:** harness/driver/playwright_driver.py
- **Definition of done:** Demoable

#### STORY-002.2 — Evidence capture pipeline
- **Epic:** EPIC-002 | **Status:** Done | **Deps:** [STORY-002.1]
- **User story:** As a tester, I want video/screenshots/logs/traces so failures are provable.
- **Vertical slice:** Capture on run, save to `artifacts/run-<id>/`
- **AC:** [x] Screenshot, console, network, trace saved, [x] Artifacts indexed in run manifest, [x] Executable: check files exist
- **Tasks:** [x] TASK-002.2.1: Capture hooks, [x] TASK-002.2.2: Manifest, [x] TASK-002.2.3: Verify
- **Capability:** Evidence capture
- **Demo:** Artifact bundle with manifest
- **Eval hook:** Evidence completeness
- **Evidence:** harness/evidence/capture.py
- **Definition of done:** Bundle present

#### STORY-002.3 — First vertical slice: smoke test end-to-end
- **Epic:** EPIC-002 | **Status:** Done | **Deps:** [STORY-001.2, STORY-002.2]
- **User story:** As a QA lead, I want one smoke test run end-to-end with report.
- **Vertical slice:** Context → plan → drive → evidence → pass/fail report
- **AC:** [x] `harness run smoke` completes, [x] Report with evidence links generated, [x] Executable: report exists
- **Tasks:** [x] TASK-002.3.1: Orchestrator, [x] TASK-002.3.2: Report generator, [x] TASK-002.3.3: E2E test
- **Capability:** All core (smoke slice)
- **Demo:** Smoke report + artifacts
- **Eval hook:** Slice success rate
- **Evidence:** harness/run/smoke.py, reports/smoke-*.json
- **Definition of done:** Demoed

### EPIC-003
#### STORY-003.1 — Vision model integration
- **Epic:** EPIC-003 | **Status:** Done | **Deps:** [STORY-002.3]
- **User story:** As the agent, I want vision inspection of screenshots.
- **Vertical slice:** Vision client with pluggable models, prompt for layout/contrast/clipping/overlap/responsive.
- **AC:** [x] Inspects screenshot, returns findings, [x] Model selectable via config
- **Tasks:** [x] TASK-003.1.1: Vision client, [x] TASK-003.1.2: Prompt, [x] TASK-003.1.3: Config
- **Capability:** Vision QA
- **Demo:** Vision findings JSON
- **Eval hook:** Vision precision/recall
- **Evidence:** harness/vision/client.py
- **Definition of done:** Working

#### STORY-003.2 — Multi-round self-inspection
- **Epic:** EPIC-003 | **Status:** Done | **Deps:** [STORY-003.1]
- **User story:** As the agent, I want to self-inspect and fix/flag issues.
- **Vertical slice:** Round 1 inspect → propose checks → round 2 verify
- **AC:** [x] >=2 rounds logged, [x] Findings deduplicated
- **Tasks:** [x] TASK-003.2.1: Inspector loop, [x] TASK-003.2.2: Dedupe, [x] TASK-003.2.3: Logging
- **Capability:** Vision QA
- **Demo:** Inspection rounds log
- **Eval hook:** Issue catch rate
- **Evidence:** harness/vision/inspector.py
- **Definition of done:** Demoed

### EPIC-004
#### STORY-004.1 — Human checkpoint system
- **Epic:** EPIC-004 | **Status:** Done | **Deps:** [STORY-003.2]
- **User story:** As a tester, I want to approve plan/findings before filing bugs.
- **Vertical slice:** Checkpoint prompts, CLI/UI, approvals logged
- **AC:** [x] Blocks filing until approved, [x] Approvals persisted
- **Tasks:** [x] TASK-004.1.1: Checkpoint engine, [x] TASK-004.1.2: Prompts, [x] TASK-004.1.3: Audit log
- **Capability:** Human checkpoints
- **Demo:** Approval log
- **Eval hook:** Gate compliance
- **Evidence:** harness/checkpoints/engine.py, artifacts/checkpoints.jsonl
- **Definition of done:** Enforced

#### STORY-004.2 — Bug ticket generator + dedup + filing
- **Epic:** EPIC-004 | **Status:** Done | **Deps:** [STORY-004.1]
- **User story:** As a tester, I want repro-ready tickets filed after approval.
- **Vertical slice:** Generate ticket with steps/evidence/severity/causes, dedup against existing, file to connector
- **AC:** [x] Ticket includes evidence links, [x] Dedup prevents duplicates, [x] Requires checkpoint approval
- **Tasks:** [x] TASK-004.2.1: Generator, [x] TASK-004.2.2: Dedup, [x] TASK-004.2.3: Connectors (GitHub/Jira/Linear)
- **Capability:** Bug filing, Human checkpoints
- **Demo:** Filed ticket + evidence
- **Eval hook:** Ticket quality score
- **Evidence:** harness/bugs/generator.py
- **Definition of done:** Demoed

### EPIC-005
#### STORY-005.1 — Risk-based test plan generator
- **Epic:** EPIC-005 | **Status:** Backlog | **Deps:** [STORY-004.2]
- **Capability:** Planning

#### STORY-005.2 — Exploratory charters
- **Epic:** EPIC-005 | **Status:** Backlog | **Deps:** [STORY-005.1]
- **Capability:** Planning

### EPIC-006
#### STORY-006.1 — Routine scheduler
- **Epic:** EPIC-006 | **Status:** Backlog | **Deps:** [STORY-005.2]
- **Capability:** Routines

#### STORY-006.2 — Client-operable skills
- **Epic:** EPIC-006 | **Status:** Backlog | **Deps:** [STORY-006.1]
- **Capability:** Routines

### EPIC-007
#### STORY-007.1 — Seeded-bug benchmark
- **Epic:** EPIC-007 | **Status:** Backlog | **Deps:** [STORY-006.2]
- **Capability:** Evals

#### STORY-007.2 — FP tracking & AB tests
- **Epic:** EPIC-007 | **Status:** Backlog | **Deps:** [STORY-007.1]
- **Capability:** Evals

### EPIC-008
#### STORY-008.1 — Accessibility checks (post-MVP)
- **Epic:** EPIC-008 | **Status:** Icebox | **Deps:** [STORY-007.2]
- **Capability:** Expansion

## 7. Execution protocol for OpenCode
1. Pick highest-priority unblocked story
2. Read AC/tasks, check AGENTS.md, ask if unclear
3. Task order, verify each
4. DoD: AC pass, executable green, demo exists, board updated
5. Status transitions with notes/evidence
6. Block if deps missing
7. Evals required
8. Commits start with story ID

## 8. Open questions / assumptions
- Stack: Python/TS + Playwright + Docker + pluggable providers
- Vertical: web SaaS regression + visual QA
- Connectors: GitHub/Jira/Linear configurable
- MVP: EPIC-001–007
- First 3: STORY-001.1, STORY-001.2, STORY-001.3

**Summary:** 8 epics, 18 stories | First 3: STORY-001.1, STORY-001.2, STORY-001.3 | Assumptions: stack/providers/connectors above
