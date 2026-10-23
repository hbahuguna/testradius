# Sprint 5 Plan — Control Plane Backend + Auth

**Sprint:** 5 of 6  
**Nominal window:** 2026-12-18 → 2026-12-31 (confirm at kickoff)  
**Capacity:** 34 dev-days  
**Committed:** 31 dev-days  
**Status:** Pre-drafted; not started  
**Baseline:** Sprint 4 accepted

## Goal

Make the control plane the only entry point. It owns identity, tenancy, dispatch,
run history, evidence indexes, and audit, while holding no client code, no LLM
keys, and no evidence bytes. The cell initiates an mTLS control channel; the CP
never reaches inbound into the cell. A tenant cannot see another tenant's run,
token, evidence URL, or audit record.

## Committed stories

| Story | Title | Est | Depends on |
| --- | --- | ---: | --- |
| E5-S1 | CP scaffold, Prisma schema, migrations | 4d | E0-S1 |
| E5-S2 | OIDC authentication and RBAC | 5d | E5-S1 |
| E5-S3 | Runs API and history | 5d | E5-S1, E5-S2 |
| E5-S5 | Outbound control channel and run dispatch | 8d | E5-S3, E7-S3, E1-S5 |
| E4-S4 | Evidence collector to client-owned object storage | 4d | E3-S2, E4-S3 |
| E7-S3 | mTLS CA, certificate issuance, and rotation | 3d | E5-S1 |
| E5-S7 | Audit log (plan-gap close) | 2d | E5-S2 |

**Total:** 31 dev-days, leaving 3 days for the OpenAPI/contract debt and buffer.

## Carryover and debt

- **`OPENAPI` (Sprint 1 AC1).** Generate OpenAPI from the cell and CP, regenerate
  `packages/shared-types`, and add a drift check. Budget 1 day from the reserve.
- **`JTI-REPLAY` (Sprint 2 AC4).** Add a single-use `jti` cache for mutating
  control-channel calls inside E5-S5. Do not call the channel replay-safe without
  it.
- **`E5-S7` plan gap.** The original S5 table omitted the Must audit story even
  though E7-S4 depends on it. Commit it here so Sprint 6 is not blocked.
- **`EVIDENCE` stub.** E4-S4 replaces the empty evidence endpoint with indexed
  object references; the cell still owns artifact bytes.
- **`MINIO-IMAGE`** must be pinned from Sprint 4; do not reintroduce `latest`.
- **Pre-existing TIA script secret literal** remains outside factory scope.

## Dependencies and assumptions

- ADR-003 (outbound mTLS control channel) is accepted and unchanged.
- Sprint 4's adjacent AUT workload and coverage edges are green.
- The cell has a stable control-channel client surface from E1-S5.
- A development OIDC provider is available. Use Keycloak in Compose by default;
  keep the mock OIDC provider for fixture/unit tests. Auth0 is a manual demo
  check, not the CI dependency.
- Object storage in development is MinIO; production uses the client-owned
  bucket. No long-lived bucket credentials are stored in CP.
- Postgres is the CP system of record; no cross-tenant repository path is
  permitted.

## Work breakdown

### E5-S1 — CP scaffold, Prisma schema, migrations

- Add Prisma with migrations for users/orgs, runs, run-event indexes, cells,
  evidence, policies, licenses, meters, and audit. Index tenant + time.
- Make readiness fail when the DB is unavailable; liveness stays independent.
- Enforce tenant scoping in a repository layer and add a cross-tenant test that
  fails closed.
- Tests: fresh `migrate deploy`; readiness without DB; tenant scoping; no
  auto-migrate in production mode.

### E5-S2 — OIDC authentication and RBAC

- Implement discovery, JWKS caching/rotation, token validation, and role checks
  for admin, operator, and viewer.
- Add a dev Keycloak service/profile; keep mock OIDC for deterministic tests.
- Tests: expired token, wrong issuer/audience, rotated key, revoked user, role
  denial, no token, and tenant claim mismatch.

### E5-S3 — Runs API and history

- Add authenticated create/list/get/cancel/history endpoints, policy versioning,
  pagination, and idempotency keys.
- Expose run events as an index; do not proxy raw cell streams through the CP by
  default.
- Return evidence metadata only; bytes stay in the client bucket.
- Tests: tenant-scoped list/get; idempotent create; pagination; cancel
  authorization; policy version pinned to the run.

### E5-S5 — Outbound control channel and run dispatch

- Implement the cell-initiated mTLS channel: enrollment, heartbeat, dispatch,
  ack, retry, backoff, and buffering when a cell is offline.
- The CP must not dial the cell. A dispatch must be idempotent and reject a
  replayed `jti`.
- Keep LLM keys and repo credentials out of the CP; dispatch carries only a
  run-scoped capability.
- Tests: mTLS handshake; no inbound listener; duplicate dispatch; replay
  rejection; offline cell buffers; retry cap; cancel propagation.

### E4-S4 — Evidence collector

- Collect cell-produced evidence metadata, hash artifacts, and write an index to
  CP; store bytes in the configured client-owned bucket.
- Replace the empty evidence endpoint with metadata + re-minted presigned URLs.
  URLs must be short-lived and tenant-scoped.
- Tests: hash mismatch; missing artifact; cross-tenant URL denial; expiry;
  upload failure is retryable; no bytes in CP logs.

### E7-S3 — mTLS CA and rotation

- Stand up a development CA, issue short-lived cell certificates, and implement
  rotation/revocation. Certificates are scoped to a cell/tenant.
- Pin the CP trust bundle and reject expired or wrong-SAN certificates.
- Tests: expired cert, wrong SAN, revoked cert, rotation overlap, trust-bundle
  reload.

### E5-S7 — Audit log

- Append tenant-scoped audit entries for login, run create/cancel, policy change,
  evidence URL minting, cell enrollment, and admin actions.
- Hash-chain entries and expose a read-only query for authorized roles.
- Tests: append-only; tenant isolation; chain verification; tamper detection.

### Contract debt — generated OpenAPI

- Generate the CP and cell OpenAPI documents from code, publish them, regenerate
  shared types, and add a CI drift check.
- Keep the runtime image independent of workspace packages.

## Execution order

1. E5-S1, then E7-S3 (certificate path needed by dispatch).
2. E5-S2, then E5-S3.
3. E5-S5 after E5-S3 and E7-S3; add JTI replay in the same story.
4. E4-S4 in parallel with E5-S5 once Sprint 4 coverage is stable.
5. E5-S7 after E5-S2; OpenAPI/contract debt last.
6. Re-run the full stack smoke with auth enabled and the mock providers.

## Demo

```bash
# Obtain a dev Keycloak token (or use the documented Auth0 manual profile).
TOKEN=$(curl -fsS -X POST localhost:58080/realms/testradius/protocol/openid-connect/token \
  -d grant_type=password -d client_id=factory -d username=operator -d password=operator \
  | jq -r .access_token)

# Dispatch through the CP; the cell connects outbound over mTLS.
RUN_ID=$(curl -fsS localhost:58001/v1/runs \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"goal":"verify checkout","repo":"fixture","commit":"abc1234","scope":"full"}' \
  | jq -r .id)
curl -fsS localhost:58001/v1/runs/$RUN_ID -H "authorization: Bearer $TOKEN" | jq
curl -fsS localhost:58001/v1/runs/$RUN_ID/evidence -H "authorization: Bearer $TOKEN" | jq

# Prove tenant isolation and replay rejection.
```

## Exit criteria

- [ ] Fresh Postgres migrates; readiness fails without DB; no production
      auto-migrate.
- [ ] OIDC login, JWKS rotation, and RBAC are tested; Auth0 demo is documented.
- [ ] Cross-tenant access fails closed for runs, evidence, policies, and audit.
- [ ] The CP never dials the cell; dispatch is mTLS, idempotent, and replay-safe.
- [ ] Evidence metadata is indexed and URLs are short-lived and tenant-scoped.
- [ ] Certificates rotate/revoke and expired/wrong-SAN certs are rejected.
- [ ] Audit entries are append-only and tamper-evident.
- [ ] OpenAPI is generated and shared types are drift-checked.
- [ ] `make test`, `make lint`, `make arch-test`, `make smoke`, gitleaks, and the
      control-channel integration suite pass.
- [ ] `docs/sprints/sprint-5.md` records delivered vs planned, demo, metrics,
      and deviations.

## Staged verification

- Dev Keycloak profile; Auth0 is a documented manual check, not a CI dependency.
- Local MinIO/client-bucket emulation; production bucket onboarding is later.
- Local CA and TLS; customer PKI/BYOC is S7–S9.
- Cell registry (E5-S4) and evidence index UI (E5-S6) are Sprint 6.
- Helm/Terraform and signed image distribution are post-S6.
- `E5-S7` is committed here to close the plan gap; if it slips, E7-S4 in Sprint 6
  must be descoped rather than silently shipped without audit.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| TypeScript pair overload | Pair CP stories with a second engineer in the first half; keep the cell contract frozen. |
| Tenant leak in a repository | Centralize scoping and require a cross-tenant negative test for every new query. |
| Control channel becomes bidirectional | Enforce cell-initiated only; add an architecture test that CP has no cell dialer. |
| Evidence URL leaks | Short TTL, tenant claim check, no permanent public bucket. |
| Audit scope creep | Limit to the six required event families; chain verification is the gate. |
| Auth provider drift | Test discovery/JWKS rotation against Keycloak and a cached mock. |

## Definition of done

The CP is the only user entry point, the cell remains outbound-only, and tenant
isolation is proven by failing tests. No LLM key, repository credential, or
evidence byte is stored in the CP. Sprint 6 starts only after this review.
