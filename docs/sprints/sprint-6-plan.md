# Sprint 6 Plan — Control Plane UI + Security Gate

**Sprint:** 6 of 6  
**Nominal window:** 2027-01-01 → 2027-01-14 (confirm at kickoff)  
**Capacity:** 36–40 dev-days (frontend engineer joins)  
**Committed:** 36 dev-days  
**Status:** Pre-drafted; not started  
**Baseline:** Sprint 5 accepted

## Goal

Close the vertical slice. An operator signs in, starts a run, watches it live,
opens evidence, reads coverage and risk, and edits policy without touching the
cell directly. The Phase 2 security gate proves deny-by-default egress,
redaction, mTLS rejection, tenant isolation, and the absence of UI/static
serving in the cell.

## Committed stories

| Story | Title | Est | Depends on |
| --- | --- | ---: | --- |
| E6-S1 | App shell, auth, and data layer | 4d | E5-S2 |
| E6-S2 | Dashboard and runs list | 4d | E6-S1, E5-S3 |
| E6-S3 | Run detail with live SSE | 5d | E6-S2, E5-S3 |
| E6-S4 | Evidence viewer | 5d | E6-S3, E4-S4 |
| E6-S5 | Policy editor | 4d | E6-S1, E5-S3 |
| E5-S4 | Cell registry and health | 4d | E5-S5, E7-S3 |
| E5-S6 | Evidence index and URL broker | 4d | E4-S4, E5-S3 |
| E7-S2 | Egress proxy and redaction gate | 4d | E2-S3 |
| E7-S4 | Audit logging for user actions | 2d | E5-S7, E5-S2 |

## Carryover and debt

- **`OPENAPI`** is generated in Sprint 5; Sprint 6 consumes it and must not
  hand-maintain duplicate run/evidence types.
- **`JTI-REPLAY`** is closed in Sprint 5; the UI must not rely on a mutable
  browser cache for dispatch idempotency.
- **`MINIO-IMAGE`** is pinned in Sprint 4; evidence URLs in development point at
  the local client-bucket emulation.
- **Helm remains a sprint-7 artifact.** Do not add a placeholder chart that
  claims production deployability; the Compose dev stack is still the demo path.
- **Pre-existing TIA script secret literal** remains outside factory scope.

## Dependencies and assumptions

- Sprint 5 control plane, auth, dispatch, evidence index, and audit are green.
- The cell is outbound-only and has no UI route or static-serving middleware.
- Evidence bytes are in the configured client bucket; the CP mints short-lived
  URLs and never proxies bytes.
- A frontend engineer is available for the full sprint; the backend pair
  continues part-time for E5-S4/E5-S6 and the security gate.
- E7-S2 is a local enforcement point; production network policy is a later
  deployment concern, but the tests must prove deny-by-default behavior.

## Work breakdown

### E6-S1 — App shell, auth, and data layer

- Build the authenticated shell, OIDC callback/refresh, route guards, tenant
  context, and a typed data client generated from OpenAPI.
- Handle 401/403, expired sessions, and tenant switching without leaking stale
  data.
- Tests: login/logout, expired token, role-gated navigation, tenant switch
  clears cache, unauthenticated deep link redirects.

### E6-S2 — Dashboard and runs list

- Show run status, goal, commit, cell, duration, coverage summary, and risk
  counts. Add filters, pagination, and empty/error states.
- Start a run only through the CP; no cell URL is exposed to the browser.
- Tests: status rendering, filter/pagination, empty state, CP failure, start-run
  authorization.

### E6-S3 — Run detail with live SSE

- Show ordered phases, steps, tool calls, citations, verdicts, and terminal
  reason. Stream via SSE with reconnect/backfill and cancel.
- Never render model prompts or secrets; show redacted tool summaries.
- Tests: ordered replay, reconnect without duplicates, cancel, terminal states,
  citation drill-down, redaction sentinel.

### E6-S4 — Evidence viewer

- List evidence metadata, preview screenshots/traces, show coverage edges, and
  open short-lived bucket URLs. Show hash and expiry.
- Handle expired URL by re-minting; never cache presigned URLs in local storage.
- Tests: metadata-only list, URL re-mint, cross-tenant denial, expired link,
  missing artifact, no bytes through CP.

### E6-S5 — Policy editor

- Edit allowlists, budgets, model/provider selection, and a11y stop policy with
  validation, versioning, and an audit entry.
- Require confirmation for widening egress or disabling a blocking rule; show
  the effective policy for a run.
- Tests: schema validation, version pinning, unauthorized edit, audit entry,
  dangerous-change confirmation.

### E5-S4 — Cell registry and health

- List enrolled cells, tenant, certificate expiry, last heartbeat, version, and
  health. Show stale/offline/revoked states.
- No direct browser-to-cell connection; actions go through CP.
- Tests: heartbeat freshness, revoked cert, cross-tenant list, stale cell,
  health transition.

### E5-S6 — Evidence index and URL broker

- Index evidence metadata by tenant/run, enforce retention, and broker URLs with
  a short TTL. Redact object keys/paths from unauthorized roles.
- Tests: tenant isolation, retention expiry, URL TTL, missing object, broker
  failure, audit on mint.

### E7-S2 — Egress proxy and redaction gate

- Add the deny-by-default egress proxy for the cell with an allowlist for the
  model endpoint, fixture AUT, and CP control channel.
- Redact secrets, prompts, and sensitive headers before events/logs leave the
  cell. Block non-allowlisted destinations before connect.
- Tests: denied destination, allowed destination, DNS rebinding/resolved-IP
  denial, secret sentinel, prompt redaction, proxy bypass attempt.

### E7-S4 — Audit logging for user actions

- Emit user/tenant/action/resource audit entries for login, run start/cancel,
  policy change, evidence URL mint, and cell actions.
- Reuse the Sprint 5 hash chain; expose authorized read-only queries.
- Tests: append-only, actor/tenant attribution, chain verification, unauthorized
  read denial.

## Execution order

1. E6-S1 and E5-S4 in parallel.
2. E6-S2, then E6-S3.
3. E5-S6 and E6-S4 after E4-S4; E6-S4 consumes the broker.
4. E6-S5 and E7-S2 in parallel; E7-S4 closes the audit surface.
5. Run the security gate across cell + CP + web, then the end-to-end demo.
6. Freeze the demo and write the sprint review; no new scope in the last 2 days.

## Demo

```bash
make up
open http://localhost:53000

# 1. Sign in as operator.
# 2. Start a run from the fixture repository.
# 3. Watch phases and steps arrive over SSE.
# 4. Open a screenshot/trace and a cited coverage edge.
# 5. Edit the policy; confirm the version and audit entry.
# 6. Cancel a second run and verify the adjacent workload is gone.
```

The demo ends with the security gate output and the audit chain check, not only
with a green UI screen.

## Exit criteria

- [ ] An operator completes the UI → CP → cell → AUT → evidence loop without a
      cell URL or direct API call.
- [ ] SSE reconnect/backfill does not duplicate steps; cancel reaches teardown.
- [ ] Evidence URLs are short-lived, tenant-scoped, and never proxied by CP.
- [ ] Policy edits are validated, versioned, confirmed, and audited.
- [ ] Cell registry shows heartbeat/cert/health states; revoked cells are denied.
- [ ] Egress is deny-by-default; non-allowlisted destinations and resolved-IP
      bypasses fail before connect.
- [ ] Secret/prompt redaction sentinels pass in events and logs.
- [ ] Cross-tenant access fails closed in UI, API, evidence, and audit.
- [ ] Cell route audit still shows no UI/static serving.
- [ ] `make test`, `make lint`, `make arch-test`, `make smoke`, gitleaks, and the
      security-gate suite pass.
- [ ] `docs/sprints/sprint-6.md` records delivered vs planned, demo, metrics,
      and deviations.

## Staged verification

- Local MinIO/client-bucket emulation; customer-owned bucket onboarding is later.
- Local egress proxy; production network policy and BYOC are S7–S9.
- Five UI screens only (shell, dashboard, run detail, evidence, policy); no
  settings/billing/admin console beyond the listed stories.
- Helm/Terraform, signed images, and update distribution are S7–S9; no chart is
  claimed as production-ready in this sprint.
- Auth0 is a manual demo check; Keycloak remains the CI path.
- Global orphan reaper, remaining agent roles, and remote AUT are post-S6.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| UI scope creep | Freeze the five screens; move settings/billing/admin to post-S6. |
| Evidence viewer blocks on bucket behavior | Build against the Sprint 5 index/broker contract; re-mint URLs rather than caching. |
| Security gate is left to the last day | Run E7-S2/E7-S4 in parallel from mid-sprint; gate is a daily check after day 5. |
| Two engineers collide on shared types | Generate from OpenAPI; one owner for the contract and a drift check. |
| Redaction regression | Keep a secret/prompt sentinel in CI and fail the gate on any match. |
| SSE duplicates on reconnect | Use monotonic event IDs and server-side backfill; test reconnect explicitly. |

## Definition of done

The vertical slice is demoable end to end with no direct cell access, and the
security gate is green. The review records delivered vs planned, the demo, the
gate output, metrics, and every staged deviation. Sprint 7 planning starts only
after this review is accepted.
