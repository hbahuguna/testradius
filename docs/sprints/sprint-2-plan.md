# Sprint 2 Plan — Orchestrator + Internal API

**Sprint:** 2 of 6
**Dates:** 2026-11-06 → 2026-11-19 (planned; executed 2026-10-23)
**Capacity:** 34 dev-days committed (4 core engineers × 10 days × 85%)
**Committed:** 32 dev-days
**Status:** Implemented — see `docs/sprints/sprint-2.md`

## Sprint goal
A run can be created, observed over SSE, cancelled, and driven through all seven phases with stubs under a real policy and real secret handling.

## Committed stories

| ID | Story | MoSCoW | Est |
| --- | --- | --- | --- |
| E1-S3 | Internal API + run-scoped tokens | Must | 4 |
| E1-S4 | Orchestrator state machine | Must | 8 |
| E1-S5 | Run lifecycle API | Must | 4 |
| E1-S6 | SSE event stream | Must | 4 |
| E1-S7 | Policy engine | Must | 8 |
| E1-S8 | Secrets broker client | Must | 4 |
| | **Total** | | **32 / 34** |

## Dependencies
- Sprint 1 complete (cell hardened, contracts, arch tests)
- Cell serves on 58000, broker/Vault available in factory stack
- Shared types extended for run events

## Staged verification (agreed deviations)
1. **E1-S5 full dispatch** — Control plane dispatch to cells is Sprint 5 (E5-S5). In Sprint 2, runs are created/driven locally by the cell orchestrator with a stub executor.
2. **E1-S6 replay/resume from disk** — Basic in-memory resume on restart with idempotency; durable event log to disk/object store is Sprint 4+.
3. **E1-S7 full policy language** — Allowlist evaluation only (no general-purpose policy language). RBAC/tenant scoping added in Sprint 5.
4. **E1-S8 broker production backends** — Vault dev broker only; AWS/Azure/GCP backends per ADR-005 land later.

## Acceptance criteria (key)
- POST /v1/runs creates run with run-scoped token (short TTL), returns run_id
- Orchestrator drives all 7 phases (isolate/select/generate/execute/prove/gate/report) with stubs
- GET /v1/runs/{id}, POST /v1/runs/{id}/cancel work
- GET /v1/runs/{id}/events streams SSE with phase/step events and sequence ids
- Policy engine evaluates allowlists; denies logged
- Secrets broker client fetches from Vault with no secrets in logs

## Demoable increment (≤5 commands)
```bash
# start stack if not running
docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory up -d
# create run
RUN_TOKEN=$(curl -s -X POST localhost:58000/v1/runs -H "Content-Type: application/json" -d '{"repo":"fixture","commit":"abc1234","scope":"full","policy":{"allow_network":false}}' | jq -r .run_token)
RUN_ID=$(curl -s -X POST localhost:58000/v1/runs -H "Content-Type: application/json" -d '{"repo":"fixture","commit":"abc1234","scope":"full","policy":{"allow_network":false}}' | jq -r .run_id)
curl -Ns -H "Authorization: Bearer $RUN_TOKEN" localhost:58000/v1/runs/$RUN_ID/events | head -20
curl -s -X POST -H "Authorization: Bearer $RUN_TOKEN" localhost:58000/v1/runs/$RUN_ID/cancel | jq
grep -R "sk-\|Bearer " /workspace /tmp 2>&1 | wc -l  # expect 0
```

## Exit criteria
- [x] All 6 endpoints from contract implemented and audited by arch tests
- [x] Orchestrator drives 7 phases, cancel works, restart resumes idempotently
- [x] SSE streams with seq ids, ordered per run
- [x] Policy allowlists enforced
- [x] Broker client uses Vault, no secret leakage in logs/events
- [x] Tests pass, arch tests green, gitleaks clean

## Risks
| Risk | Mitigation |
| --- | --- |
| SSE backpressure/concurrency | Single writer per run, sequence ids, tests |
| Token leakage | Short TTL, run-scoped, never log tokens |
| State machine complexity | Data-driven transitions, minimal |
| Policy scope creep | Allowlist-only v1 |
