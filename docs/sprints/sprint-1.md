# Sprint 1 Review — Foundation + Cell Skeleton

**Sprint:** 1 of 6  
**Dates:** 2026-10-23 → 2026-11-05  
**Branch:** feat/sprint-1-foundation (proposed)  
**Status:** Ready for review

## Goal
One command brings up the local factory stack; the cell container starts hardened, answers `/v1/health`, and CI objectively rejects any UI dependency or non-contract route in the cell.

## Committed vs completed
| Story | Status | Notes |
| --- | --- | --- |
| E0-S1 Monorepo scaffolding and workspace tooling | Done | pnpm 11 / Node 22 tooling, `make bootstrap/doctor`, workspace for apps/packages/infra/docs |
| E0-S2 Local development stack (Compose) | Done (staged smoke) | Distinct project/ports, `make up`, all services healthy; run-through-CP tracked as `SMOKE-RUN` (S5) |
| E0-S3 CI pipeline | Done (deviated) | `factory-ci.yml`: python/node/arch/gitleaks/factory paths/compose/image; uses Compose, not Testcontainers |
| E0-S4 Engineering standards and ADR workflow | Done | ADRs 001–007, template lint, CODEOWNERS, PR template, commitlint, pre-commit (ruff + prettier + gitleaks) |
| E0-S5 Shared contracts package | Done (staged generation) | JSON Schema + TS types + drift tests in both languages; cell OpenAPI disabled (ADR-002), generation deferred to S5 |
| E0-S6 Test fixtures: sample AUT and mock OIDC | Done (staged instrumentation) | 3 routes/3 APIs, 2 a11y defects enforced; coverage instrumentation tracked as `FIXTURE-INSTR` (S4) |
| E0-S7 Architecture-test harness | Done | `make arch-test`, rule file reviewable, synthetic violation tests, CI + pre-commit |
| E0-S8 Local secrets and broker | Done (staged fetch) | `make secrets` seeds Vault (values never to disk); cell broker fetch tracked as `SECRET-FETCH` (S2) |
| E1-S1 Cell container image (multi-stage, hardened) | Done (sized over) | uid 10001, read-only root, `cap_drop: ALL`, no Docker socket; 2.81 GB (`IMAGE-SIZE` open, S2) |
| E1-S2 Health and readiness endpoint | Done (staged OpenAPI/Helm probe) | `/v1/health` 503 until deps ready / 200 ready; p95 test; contract in models + shared types |
| E7-S1 No-UI-in-cell architecture test and route audit | Done | Closed allowlist (7 routes, only `/v1/health` registered in S1), docs disabled |

**Committed:** 32 / 34 dev-days.

## Verification
| Check | Result |
| --- | --- |
| `make bootstrap` / `make doctor` | OK (Node 22, pnpm 11, uv, Docker v2) |
| `pnpm -r typecheck` / `pnpm -r test` | 5/5 workspaces OK; shared-types 6/6, control-plane 6/6, fixture-aut OK |
| `uv run ... pytest apps/cell/tests infra/architecture-tests` | 47 passed |
| `make arch-test` | 29 passed |
| `make up` + `make smoke` | All services healthy; cell uid 10001, rootfs read-only |
| `make secrets` | Seeds 4 secrets to Vault (not printed) |
| `docker image inspect testradius-cell:dev` | uid 10001, read-only, size 2.81 GB |
| gitleaks (factory paths) | No leaks found |
| Prettier check / lint | Pass |

## Staged deviations
- `SMOKE-RUN`: run-through-CP deferred to S5.
- `FIXTURE-INSTR`: fixture coverage instrumentation deferred to S4.
- `SECRET-FETCH`: cell broker fetch + audit deferred to S2 (E1-S8).
- `IMAGE-SIZE`: cell 2.81 GB > 2.5 GB, optimization tracked S2.
- OpenAPI generation for cell/CP disabled (ADR-002); contract is schema + drift tests (S5).
- Helm probes/charts placeholder (E9-S1).
- Integration via Compose, not Testcontainers (equivalent boundary coverage).
- Toolchain: Node 22 for pnpm 11; cell runtime Node 20 for Playwright.

## Security findings
- **Pre-existing (out of scope):** `scripts/run-workbench-sdet-local.sh` contains a secret-shaped literal. Factory paths scanned clean. Escalated to TIA owners; do not allowlist.

## Artifacts
- ADRs: `docs/adr/001-007` + template + README
- Docs: `docs/architecture-tests.md`, `docs/runbooks/local-dev.md`, `docs/demos/sprint-1.md`, `docs/sprints/sprint-1-plan.md`
- CI: `.github/workflows/factory-ci.yml`
- Stack: `infra/compose/compose.factory.yaml`, `Makefile`, `scripts/*`
- Cell: `apps/cell/` (hardened, no UI, contract routes only)
- Contracts: `packages/shared-types/`, fixtures: `packages/test-fixtures/`

## Next
Sprint 2: cell orchestrator/auth/channel (E1-S3–S8), harden CP auth, extend tests.
