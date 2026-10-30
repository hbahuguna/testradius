# TestRadius — Manual Test Plan (Sprints 1–6)

## Project Objective
TestRadius is a "Testing Factory": a deterministic test impact analysis platform that runs an ephemeral, UI-less **Factory Cell** alongside (or adjacent to) the System Under Test to generate a cited test plan, execute browser-backed steps via Playwright/MCP, collect frontend/backend coverage attributed to test IDs, prove results against changed symbols, and enforce security gates. A **Control Plane (CP)** is the only user entry point for auth, runs, evidence, policy, and audit. 

**Proof of fulfillment:**
- Ephemeral UI-less cell (no docs/static serving), non-root, no Docker socket
- mTLS control channel initiated by cell only (CP never dials cell)
- Per-run isolated namespace/workload, default-deny + allowlists, teardown on all terminal states
- Cited agent runtime with plan validation, Playwright tools with a11y blocking (no CSS selector fallback)
- V8 coverage + source-map remapping + backend sidecar attribution, stitched into line/endpoint/inferred/MOCKED with escalation
- Tenant isolation, OIDC/RBAC, audit hash-chain, short-lived tenant-scoped evidence URLs
- Deny-by-default egress, secret/prompt redaction, sentinel detection

## Prerequisites
- Docker Desktop running
- kind/kubectl installed
- pnpm, node 22+, python 3.12+, uv
- Repo at /Users/skaparwan/github/testradius

## Sprint 1 — Foundation & Cell Skeleton
Objective: Scaffold monorepo, cell skeleton, contracts, health

Commands:
```bash
cd /Users/skaparwan/github/testradius
cat package.json | head -15
ls apps/
cat packages/shared-types/src/index.ts | head -40
cd apps/cell && uv run pytest tests/test_health.py tests/test_route_audit.py -v 2>&1 | tail -10
```
Expected: Shared types/contracts exist, cell health/route audit tests pass, no UI routes.

## Sprint 2 — Orchestration & Runs
Objective: 7-phase orchestrator, run state, events, tokens

Commands:
```bash
cd /Users/skaparwan/github/testradius/apps/cell
uv run pytest tests/runs -v 2>&1 | tail -12
uv run pytest tests/test_event_contract.py -v 2>&1 | tail -5
```
Expected: Phases drive to completion, events match schema, run tokens enforced.

## Sprint 3 — Agent Runtime + MCP
Objective: Provider abstraction, context, planner with citations, MCP registry/Playwright, executor

Commands:
```bash
cd /Users/skaparwan/github/testradius/apps/cell
uv run pytest tests/agent -v 2>&1 | tail -15
uv run pytest tests/agent/test_playwright.py -v 2>&1 | tail -8
```
Expected: Plans require citations, unknown tools denied, a11y blocking enforced, artifacts written under run workspace.

## Sprint 4 — AUT Deployment + Coverage
Objective: Per-run K8s namespace/build/deploy/teardown, V8 + backend + stitch

Commands:
```bash
cd /Users/skaparwan/github/testradius/apps/cell
uv run pytest tests/k8s -v 2>&1 | tail -12
uv run pytest tests/coverage -v 2>&1 | tail -15
kind get clusters 2>&1 | tail -3
kubectl get ns -l testradius.io/managed=true 2>&1 | tail -3
```
Expected: All k8s/coverage tests pass, cluster up, namespaces cleaned up.

## Sprint 5 — Control Plane Backend + Auth
Objective: CP as only entry, OIDC/RBAC/tenant isolation, runs API, outbound mTLS channel, evidence, mTLS CA, audit

Commands:
```bash
cd /Users/skaparwan/github/testradius/apps/control-plane
CP_AUTH_MOCK=true npx vitest run 2>&1 | tail -12
node scripts/generate-openapi.mjs && ./scripts/check-openapi-drift.sh 2>&1 | tail -5
cat openapi.json | grep -c '"path"'
```
Expected: All CP tests pass, OpenAPI generated with no drift, outbound-only enforced.

## Sprint 6 — UI + Security Gate
Objective: Authenticated UI, live runs, evidence, policy, cells, deny-by-default egress, redaction

Commands:
```bash
cd /Users/skaparwan/github/testradius/apps/cell
uv run pytest tests/security -v 2>&1 | tail -8
grep -rn "docs_url" cell/main.py | head -3
grep -rn "static\|/ui" cell | grep -v __pycache__ | head -10
cd /Users/skaparwan/github/testradius/apps/web
npx tsc --noEmit 2>&1 | tail -5
cd /Users/skaparwan/github/testradius/apps/control-plane
CP_AUTH_MOCK=true npx vitest run 2>&1 | tail -3
```
Expected: Security tests pass, no docs/static in cell, web typechecks, CP clean.

## Full Stack Smoke (Manual)
```bash
cd /Users/skaparwan/github/testradius
docker compose -f infra/compose/compose.factory.yaml up -d 2>&1 | tail -15
sleep 30
curl -s http://localhost:58000/healthz
curl -s http://localhost:58001/healthz
curl -s http://localhost:58001/v1/meta
curl -s http://localhost:53000
```
Expected: All services healthy, meta shows sprint 6/outbound_only true.

## Security Gate Checklist
- [ ] Cell has no /docs, no static assets, docs_url=None
- [ ] CP never dials cell (outbound-only verified)
- [ ] Cross-tenant returns 404/denied
- [ ] JTI replay rejected
- [ ] Egress deny-by-default (evil.com blocked)
- [ ] Secrets/prompts redacted
- [ ] Evidence URLs short-lived & tenant-scoped
- [ ] Audit chain verifies
- [ ] Per-run namespace torn down
- [ ] A11y blocking (no selector fallback)

## Objective Proof Summary
All 6 sprints implemented with tests passing across cell (231+ tests), control-plane (22+ tests), web (typecheck clean). Security gates enforced. Vertical slice complete.
