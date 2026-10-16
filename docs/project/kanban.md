# Kanban Board

_Last updated: 2026-10-16_

## Legend

| Column | Meaning |
|--------|---------|
| Backlog | Not yet started |
| Ready | Next in priority |
| In Progress | Currently being built |
| Review | Code + tests review |
| Manual Test | You execute test plan |
| Done | Complete |

---

## Currently

| Epic | Status | Task |
|------|--------|------|
| Epic 1: Project Foundation | Done | Verified: 5/5 checks pass |
| Epic 2: COM Generation Engine | Done | 84 tests, 9 stories |
| Epic 3: Page Viewer Shell | Done | 3 stories, 91 tests |
| **Epic 4: Visual Inspector** | **Manual Test** | Frontend rewritten (310 lines). Backend 105 tests pass. Preview wired with SVG/shadow DOM/non-interactive edge cases. E2E flow verified. Test plan: `test-plans/04-visual-inspector.md`. |
| Epic 5: POM Composer + Test Gen | Backlog | — |
| Epic 6: Test Execution | Backlog | — |
| Epic 7: Interaction Recorder | Backlog | — |
| Epic 8: ML Classifier | Backlog | — |
| Epic 9: TIA Integration | Backlog | — |
| Epic 10: Team Features | Backlog | — |
| **Epic 11: Instrumentation Hardening** | **In Progress** | 11 stories. 11.1–11.4, 11.6 and 11.8 done; 11.5 (incremental instrumentation) built and gate-verified but holding on AC6 (Pygments scale measurement). Next: 11.7 (confidence gradation). Epic: `epics/11-instrumentation-hardening.md`. |

## Detailed Queue

### Manual Test
- Epic 4: Run `test-plans/04-visual-inspector.md` sections B-K (browser). Sections A (unit tests) + L (API) auto-verified: 105/105 pass.

### Ready
- Epic 5: POM Composer + Test Gen

### Backlog
- Epic 6: Test Execution + Reports
- Epic 7: Interaction Recorder
- Epic 8: ML Component Classifier
- Epic 9: TestRadius TIA Integration
- Epic 10: Team Features
- Epic 11: Instrumentation Hardening — see story board in `epics/11-instrumentation-hardening.md`

### Epic 11 Story Board

Only one card moves to **In Progress** at a time.

| Backlog | Ready | In Progress | Review | Manual Test | Done |
|---------|-------|-------------|--------|-------------|------|
| 11.7 Confidence gradation | | — | | 11.5 Incremental instrumentation | 11.1 Purge/version evidence |
| 11.9 Failure reasons | | | | | 11.2 Stable symbol identity |
| 11.10 Auto re-instrumentation | | | | | 11.3 Unified attribution |
| 11.11 Dead-code cleanup | | | | | 11.4 Clone/install cache |
| | | | | | 11.6 TS/Playwright parity |
| | | | | | 11.8 TS coverage completeness |

> **2026-10-16 manual gate** — §F (11.5), §G (11.6) and §I (11.8) executed
> against the live `core-ml` backend. 11.6 and 11.8 closed. 11.5's gate found a
> real defect (the changed-file diff counted the run's own artifacts, tripping
> the `large_diff` guard and silently degrading every incremental run to a full
> suite — fixed in `1ceda94`); 11.8's fix closed a false `low_coverage` warning
> on every TS/Playwright project. 11.5 stays in Manual Test pending its AC6
> order-of-magnitude measurement on the Pygments 5k-test suite.

**Recommended order**: 11.1 → 11.2 → 11.3 → 11.4 → 11.5 → 11.6 → 11.8 → 11.7 → 11.9 → 11.10 → 11.11.
**Manual gate**: `test-plans/11-instrumentation-hardening.md`.

> **2026-10-16 manual gate** — §F (11.5) and §G (11.6) executed against the live
> `core-ml` backend. 11.6 closed. 11.5 found and fixed a real defect: the
> changed-file diff counted the run's own artifacts (`.tia-deps-installed`,
> `coverage.json`, `.coverage*`, `.pytest_cache/`, `node_modules/`) as changed
> source files, which tripped the `large_diff` guard and silently degraded every
> incremental run to a full suite. All behavioural ACs of 11.5 now pass; its
> remaining AC6 (order-of-magnitude measurement) still needs the Pygments 5k-test
> suite, so the card stays in Manual Test.
