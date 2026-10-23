# Sprint 2 Review — Orchestrator + Internal API

**Sprint:** 2 of 6
**Dates:** 2026-11-06 → 2026-11-19 (planned; executed 2026-10-23)
**Branch:** feat/sprint-2-orchestrator
**Status:** Complete

## Goal
A run can be created, observed over SSE, cancelled, and driven through all seven phases with stubs under a real policy and real secret handling.

## Committed vs completed
| Story | Status | Evidence |
| --- | --- | --- |
| E1-S3 Internal API + run-scoped tokens | Done | HS256 JWT (run-scoped, TTL, jti), 401 without token; `POST /v1/runs` issues token |
| E1-S4 Orchestrator state machine | Done | Seven data-driven phases, persisted state, resume skips completed phases |
| E1-S5 Run lifecycle API | Done | create/get/cancel/evidence; cancel is immediate; evidence returns empty list until S4/S5 |
| E1-S6 SSE event stream | Done | Per-run sequence ids, replay from checkpoint, contract-valid events |
| E1-S7 Policy engine | Done | Allowlist-only, deny-by-default network, reload endpoint/version |
| E1-S8 Secrets broker client | Done (Vault dev) | On-demand Vault KV v2 read, env override for tests, values never logged |
| **Total** | | **32 / 34** |

## Verification
| Check | Result |
| --- | --- |
| `uv run ... pytest apps/cell/tests infra/architecture-tests` | 65 passed |
| `make arch-test` | 29 passed |
| `make test` | 65 Python + 6 shared-types + 6 control-plane + fixture-aut |
| `make lint` | Pass |
| `make up && make smoke` | Pass, including run create / get / SSE completion |
| `POST /cancel` on a running run | `cancelled: true`, status `cancelled` |
| `GET /evidence` | `200` with empty list (collector not in S2) |
| `POST /policy/reload` | `200`, version increments |
| Vault broker | 48-char dev secret fetched; no value printed |
| Restart resume | Run continued after `compose restart cell`; seq 1–16, no duplicate phases |

## Staged deviations
- `CP-DISPATCH`: control-plane→cell dispatch remains S5 (E5-S5). Runs are created directly on the cell for local demo.
- `EVIDENCE`: endpoint exists but returns an empty list; collector is E4-S4/S5.
- `DURABLE-EVENTS`: state/events persist on the `/workspace` volume (survives container restart), not object storage; S4 moves evidence to MinIO.
- `POLICY-LANG`: allowlist evaluation only; no general policy language.
- `BROKER-BACKENDS`: Vault dev backend only; cloud backends per ADR-005 later.
- `POLICY-RELOAD-AUTH`: endpoint is internal-only in S2; mTLS/admin auth arrives with CP channel (S5).
- `JTI-REPLAY`: `jti` is present in tokens; the single-use replay cache for mutating calls lands with the CP channel (S5).

## Security notes
- Run tokens are HS256 JWTs with `iss`/`aud`/`sub`/`scope`/`exp`/`jti`, verified locally; they are run-scoped and expire (default 1 h).
- Secret values are never logged; tests assert a sentinel does not appear in logs.
- `/v1/runs` creation is unauthenticated in local dev by design; production is CP-over-mTLS (ADR-003, S5).
- The cell remains UI-free and route-audited; the route allowlist now includes the six Sprint 2 endpoints.

## Next
Sprint 3: agent runtime + MCP (E2-S1, S2, S3, S4, S7, S8, S11), with `FakeProvider` for deterministic CI.
