# Sprint 1 Plan — Foundation + Cell Skeleton

**Sprint:** 1 of 6
**Dates:** 2026-10-23 → 2026-11-05 (2 weeks)
**Capacity:** 34 dev-days committed (4 core engineers × 10 days × 85%)
**Committed:** 32 dev-days
**Status:** In Progress

---

## Sprint goal

> One command brings up the local factory stack; the cell container starts hardened, answers
> `/v1/health`, and CI objectively rejects any UI dependency or non-contract route in the cell.

---

## Committed stories

| ID | Story | MoSCoW | Est |
| --- | --- | --- | --- |
| E0-S1 | Monorepo scaffolding and workspace tooling | Must | 4 |
| E0-S2 | Local development stack (Compose) | Must | 4 |
| E0-S3 | CI pipeline | Must | 3 |
| E0-S4 | Engineering standards and ADR workflow | Should | 2 |
| E0-S5 | Shared contracts package | Should | 3 |
| E0-S6 | Test fixtures: sample AUT and sample repo | Must | 3 |
| E0-S7 | Architecture-test harness | Must | 2 |
| E0-S8 | Local secrets and broker | Must | 2 |
| E1-S1 | Cell container image (multi-stage, hardened) | Must | 5 |
| E1-S2 | Health and readiness endpoint | Must | 2 |
| E7-S1 | No-UI-in-cell architecture test and route audit | Must | 2 |
| | **Total** | | **32 / 34** |

### Explicitly not in this sprint

- Run creation, SSE, cancel, policy reload auth (E1-S3 → E1-S8, Sprint 2).
- Orchestrator state machine (E1-S4, Sprint 2).
- Agent runtime and any LLM call (E2, Sprint 3).
- Real control-plane auth/runs API (E5, Sprint 5).

---

## Staged verification (agreed deviations)

These are called out up front so the sprint review can measure them, not discover them.

1. **E0-S2 AC2 — `make smoke` run-through-CP.**
   Creating a run through the control plane requires the cell orchestrator (S2) and CP dispatch
   (S5). In Sprint 1, `make smoke` asserts every service's health/readiness plus MinIO, Neo4j,
   Postgres and the mock IdP. The run-through-CP assertion is re-enabled in Sprint 5 and tracked
   here as `SMOKE-RUN` (open).
2. **E0-S6 AC3 — fixture instrumentation coverage.**
   The fixture exists and is deterministic in S1; non-empty FE+BE coverage and a mocked route are
   proven in Sprint 4 when the coverage pipeline lands. Tracked as `FIXTURE-INSTR` (open, S4).
3. **E7-S1 route audit scope.**
   The allowlist contains all seven contract routes from the brief. Only `GET /v1/health` is
   registered in S1; the audit fails if any route outside the allowlist appears, and the remaining
   six routes are added story-by-story. FastAPI's `/docs`, `/redoc` and `/openapi.json` are
   disabled because they ship a UI.
4. **E1-S1 image size.**
   Python 3.12 + Node 20 + Chromium (downloaded by Playwright). Measured: ~2.81 GB (> 2.5 GB).
   Firefox/WebKit were never installed. Optimized in follow-up (system browser or compressed cache)
   tracked as `IMAGE-SIZE` (open, S2).
5. **E0-S5 generation boundary.**
   The cell's OpenAPI document is intentionally disabled (ADR-002: it ships a UI). The contract
   source of truth is `packages/shared-types/contracts/run-event.v1.json` plus typed models; drift
   tests run in both Python and TypeScript. Generated CP/cell client types land when the run API
   exists (S5), not in S1.
6. **E0-S8 AC3 secret fetch.**
   `make secrets` seeds Vault in S1, but the cell has no broker client yet. Fetching at start and
   audit-logging the access is E1-S8 (S2). The Sprint 1 review reports `SECRET-FETCH` open.
7. **E0-S3 Testcontainers.**
   The integration job uses the Compose stack (process boundary, real dependencies) rather than a
   Java/Testcontainers runtime. The assertion set is the same: health, hardening, smoke, route
   audit.
8. **E0-S8 AC2 `git grep` pattern.**
   The literal pattern `sk-` matches pre-existing CSS (`mask-image`) and TIA test fixtures, so the
   executable gate is gitleaks scoped to the factory tree. The pre-existing
   `sk-...` literal in `scripts/run-workbench-all-local.sh` is reported to the TIA owners; it is
   not silently allowlisted.
9. **E1-S2 OpenAPI + Helm probe.**
   The health contract is documented in `cell/contracts.py` and shared types because OpenAPI is
   disabled. The Compose healthcheck is live; the Helm probe lands with the chart in E9-S1 (S6).
10. **E0-S1 Node version.**
    Tooling runs on Node 22 because pnpm 11.15.1 declares `node >= 22.13`. The cell image still
    pins Node 20 for Playwright browser compatibility (E1-S1). `make doctor`, CI, and the CP/web
    build stages use Node 22; the cell runtime uses Node 20.

---

## Demoable increment (≤5 commands)

```bash
make bootstrap && make up          # stack healthy; cell is non-root / read-only / cap-drop ALL
make smoke                         # health of cell, CP, web, postgres, neo4j, minio, oidc
make arch-test                     # green
curl -fsS localhost:58000/v1/health | jq '{ready,aut_status,graph_status}'
# add `express.static` or `/docs` to the cell -> `make arch-test` fails (demonstrated in review)
```

---

## Risks and mitigations

| Risk | Mitigation | Trigger |
| --- | --- | --- |
| Host has Node 22 / Python 3.10 only | Pin Node 20 + Python 3.12 in images and `.nvmrc`/`uv`; `make doctor` fails fast | `make doctor` red |
| Compose port clash with the existing product stack | Dedicated project name + non-overlapping 5xxxx ports; root `docker-compose.yml` untouched | bind error on `make up` |
| Cell image build is heavy/slow | Single base `python:3.12-slim` + Node tarball + Chromium only; no Firefox/WebKit | build > 8 min |
| Fixture scope creep | Freeze at 3 UI routes / 3 API endpoints / 2 a11y defects | new route in a PR |
| Architecture test false positives | Rule file is reviewable; allowlist requires a second reviewer | rule change PR |
| "Smoke" over-promises run creation | Staged verification above; review reports `SMOKE-RUN` open | review |
| Pre-existing TIA tree contains secret-shaped literals | Gitleaks is scoped to factory paths; the workbench literal is escalated to TIA owners, not allowlisted | gitleaks / security review |

---

## Exit criteria

- [ ] Clean clone → `make bootstrap && make up && make smoke` green in ≤ 30 minutes.
- [ ] Cell runs as uid 10001, `read_only: true`, `cap_drop: ALL`, no Docker socket.
- [ ] `GET /v1/health` returns `503` while a configured dependency is unreachable and `200` when ready.
- [ ] `/docs`, `/redoc`, `/openapi.json` return 404 on the cell.
- [ ] `make arch-test` fails when `express.static`/`react`/`next`/`jinja2` or an out-of-contract route is added.
- [ ] `gitleaks` clean; no secret-shaped values in the tree; dev secrets live in Vault.
- [ ] CI runs lint, typecheck, unit, architecture, gitleaks, compose smoke, image builds, SBOM.
- [ ] ADRs 001–007 exist under `docs/adr/`; `CONTRIBUTING.md`, `CODEOWNERS`, PR template in place.
- [ ] Demo script in `docs/demos/sprint-1.md`; review in `docs/sprints/sprint-1.md`.

---

## Definition of Ready (checked before each story starts)

- Acceptance criteria understood and testable.
- Cross-boundary stories have an integration-test approach (Compose/Testcontainers).
- No security-critical decision is open for the story (Q1–Q5 resolved in the approved plan).
- Demo command identified.
