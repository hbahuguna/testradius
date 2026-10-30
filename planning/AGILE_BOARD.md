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
- **Epic:** EPIC-001 | **Status:** Backlog | **Deps:** [STORY-001.1]
- **AC:** Schema + loader + `harness context validate` passes
- **Capability:** Context intake

#### STORY-001.3 — Sandbox skeleton (Docker Compose)
- **Epic:** EPIC-001 | **Status:** Backlog | **Deps:** [STORY-001.1]
- **AC:** Compose up, health OK, Playwright reachable
- **Capability:** Sandboxing

### EPIC-002
#### STORY-002.1 — UI driver (Playwright)
- **Epic:** EPIC-002 | **Status:** Backlog | **Deps:** [STORY-001.3]
- **AC:** Navigate/click/type/assert + screenshot
- **Capability:** UI driving

#### STORY-002.2 — Evidence capture pipeline
- **Epic:** EPIC-002 | **Status:** Backlog | **Deps:** [STORY-002.1]
- **AC:** video/screenshots/logs/traces + manifest
- **Capability:** Evidence capture

#### STORY-002.3 — First vertical slice: smoke test end-to-end
- **Epic:** EPIC-002 | **Status:** Backlog | **Deps:** [STORY-001.2, STORY-002.2]
- **AC:** `harness run smoke` produces report + evidence
- **Capability:** Full smoke slice

### EPIC-003
#### STORY-003.1 — Vision model integration
- **Epic:** EPIC-003 | **Status:** Backlog | **Deps:** [STORY-002.3]
- **Capability:** Vision QA

#### STORY-003.2 — Multi-round self-inspection
- **Epic:** EPIC-003 | **Status:** Backlog | **Deps:** [STORY-003.1]
- **Capability:** Vision QA

### EPIC-004
#### STORY-004.1 — Human checkpoint system
- **Epic:** EPIC-004 | **Status:** Backlog | **Deps:** [STORY-003.2]
- **Capability:** Human checkpoints

#### STORY-004.2 — Bug ticket generator + dedup + filing
- **Epic:** EPIC-004 | **Status:** Backlog | **Deps:** [STORY-004.1]
- **Capability:** Bug filing, Human checkpoints

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
