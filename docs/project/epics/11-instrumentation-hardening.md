# Epic 11: Instrumentation Hardening

**Theme**: "Trust the evidence." Make coverage-based instrumentation correct, fast, and honest — so test impact analysis (TIA) never selects a test set from stale, misattributed, or silently-partial evidence.

**Dependencies**: None (touches the existing instrumentation pipeline: `services/core/testsquad_core/instrumentation/`)

**Source**: Improvement review of the instrumentation pipeline (write path `neo4j_store.py`, resolvers `symbol_resolver.py` / `typescript_symbol_resolver.py`, runners `pipeline_worker.py` / `per_test_analyzer.py`, and the Vitest/Playwright pipelines).

---

## Why this epic

The instrumentation pipeline builds the `[:EVIDENCE]` graph that all test selection depends on. Today it has three classes of defect:

1. **Correctness** — re-runs leave stale/mixed-commit evidence; symbols with the same bare name collapse into one node; TypeScript attribution over-credits enclosing classes.
2. **Cost** — every run re-clones, re-installs, and re-runs the entire suite (no caching, no incremental path); TypeScript/Playwright only instrument 10 files, sequentially.
3. **Honesty** — every edge claims `confidence: 1.0`; TypeScript/Playwright report `coverage_pct = 0`; install/collection failures are swallowed; re-instrumentation is never triggered automatically.

---

## Stories

| # | Story | Priority | Effort | Depends on |
|---|-------|----------|--------|------------|
| 11.1 | Purge/version evidence on re-instrumentation | P0 | 2d | — |
| 11.2 | Stable symbol identity (qualify names + line span) | P0 | 2d | — |
| 11.3 | Unified innermost attribution + language-based dispatch | P0 | 2d | 11.2 |
| 11.4 | Clone + dependency-install caching | P1 | 1d | — |
| 11.5 | Incremental instrumentation (only re-run affected tests) | P1 | 3d | 11.1, 11.2 |
| 11.6 | TS/Playwright parity: sharding, lift cap, wire Vitest plugin | P1 | 3d | 11.3 |
| 11.7 | Confidence gradation + coverage metadata | P2 | 2d | 11.2 |
| 11.8 | Coverage completeness for TS/Playwright | P2 | 1d | 11.6 |
| 11.9 | Surface install/collection failures as structured reasons | P2 | 1d | — |
| 11.10 | Automatic re-instrumentation trigger | P2 | 2d | 11.1 |
| 11.11 | Remove dead instrumentation code / wire remaining paths | P3 | 1d | — |

Total: ~20d.

---

## Story Board

Move one card at a time to **In Progress** (Kanban rule: only one task in progress).

| Backlog | Ready | In Progress | Review | Manual Test | Done |
|---------|-------|-------------|--------|-------------|------|
| 11.9, 11.10, 11.11 | — | — | — | 11.5 | 11.1, 11.2, 11.3, 11.4, 11.6, 11.7, 11.8 |

**Recommended order**: 11.1 → 11.2 → 11.3 → 11.4 → 11.5 → 11.6 → 11.8 → 11.7 → 11.9 → 11.10 → 11.11.

> **Manual gate, 2026-10-16** — §F (11.5), §G (11.6), §H (11.7) and §I (11.8)
> run against a live backend. 11.6, 11.7 and 11.8 closed. Three things were
> found by the gates and fixed: (1) 11.5's changed-file diff counted the run's
> own artifacts (`.tia-deps-installed`, `coverage.json`, `.coverage*`,
> `.pytest_cache/`, `node_modules/`) as changed source, tripping the
> `large_diff` guard so incremental silently degraded to full runs (fixed in
> `1ceda94`); (2) 11.8's TS/Playwright pipelines emitted no completeness
> metrics, so the coverage endpoint warned on every one of them; (3) 11.7's
> ranking path read EVIDENCE edges in the **reversed** direction, so
> `/analyze-impact` had never returned a single coverage-evidenced test, and
> the coverage calibrator ignored its input (`lambda x: 0.99`). 11.5 stays in
> Manual Test: all of its behavioural ACs pass, but its AC6
> (order-of-magnitude measurement) still needs the Pygments 5k-test suite.
> Next up: 11.9 (failure reasons).

---

## Dependency graph

```
11.1 purge/version ──┬──▶ 11.5 incremental ──▶ (fast re-runs)
                     └──▶ 11.10 auto-trigger
11.2 symbol identity ─┬──▶ 11.3 unified resolver ──▶ 11.6 TS/Playwright parity ──▶ 11.8 completeness
                      ├──▶ 11.5 incremental
                      └──▶ 11.7 confidence
11.4 clone/install cache (independent)
11.9 failure surfacing (independent)
11.11 dead-code cleanup (independent, any time)
```

---

## Acceptance criteria (epic-level)

- [ ] Re-running instrumentation at a new anchor commit leaves exactly **one** distinct `built_at_sha` for the project; `analyze-pr` reports `stale_evidence=false` against that anchor.
- [ ] Two same-named methods in different classes resolve to **distinct** `Symbol` nodes and select the correct tests.
- [ ] Python and TypeScript produce the **same innermost** attribution for equivalent constructs.
- [ ] A second instrumentation run against an unchanged testbed skips clone and dependency install.
- [ ] A small diff re-instruments by running **only affected tests**; unaffected evidence is carried forward.
- [ ] TypeScript/Playwright instrument the **full** suite (no hardcoded 10-file cap) and report real coverage completeness.
- [ ] Every `[:EVIDENCE]` edge carries a computed confidence and coverage metadata (not a constant `1.0`).
- [ ] Each missing test file reports a **reason** (missing dependency, collection error, skipped, timeout).
- [ ] A default-branch push can trigger re-instrumentation without manual intervention.
- [ ] No dead instrumentation modules remain; `grep` finds no dangling import.

---

## Verification

- Automated: `pytest services/core/tests/`, plus the instrumentation suites
  (`test_per_test_coverage_integration.py`, `test_persistence_verification.py`,
  `test_instrumentation_coverage_api.py`, `test_neo4j_store.py`).
- Manual gate: `docs/project/test-plans/11-instrumentation-hardening.md`.
