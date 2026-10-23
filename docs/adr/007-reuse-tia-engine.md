# ADR-007 — Reuse the existing TIA engine for selection and the graph

## Context
This repository already ships the deterministic selection engine: AST parsing, stable symbol identity, innermost-owner attribution, the `EVIDENCE` graph in Neo4j, coverage-confidence gradation (Epic 11), diff→symbol mapping, and ranked impact. The factory needs exactly those capabilities in the `Select` phase and to write coverage edges. Rebuilding them would duplicate a tested system and inevitably diverge.

## Decision
1. The cell depends on `testsquad_core` (or a thin extracted `tia-engine` package) for: symbol resolution, `EVIDENCE` reads/writes, confidence computation, and impacted-test selection.
2. The factory adds only what is new: `granularity`, cross-boundary stitching inputs, mock negative edges, and escalation policy.
3. The CP never queries Neo4j. The graph lives with the cell (customer VPC in BYOC; per-tenant DB in SaaS).
4. If importing `testsquad_core` into the cell is impractical (dependency weight, FastAPI coupling), S2 extracts the needed modules behind a small internal interface — a refactor, not a rewrite. That extraction is an explicit S2 deliverable checkpoint.
5. The physical relationship stays `EVIDENCE`; `COVERS` remains the product-level term. Renaming would break shipped instrumentation and tests for no functional gain.

## Consequences
- (+) Faster delivery and consistent semantics; one confidence formula.
- (+) Existing tests (symbol identity, innermost attribution, persistence contracts) keep guarding behavior.
- (−) Coupling: cell releases and engine changes must be coordinated; schema migrations affect both.
- (−) The engine's multi-tenant assumptions must be audited for cell use (project scoping, read-only graph user).

## Alternatives considered
- Fresh selection engine in the cell — rejected: duplication, drift, and a second set of correctness bugs.
- Call `services/core` over HTTP from the cell — rejected: extra hop, and the core service is shaped as a multi-tenant SaaS API, not a cell-local library.
- Copy the relevant modules — rejected: forks diverge; import or extract instead.

---
