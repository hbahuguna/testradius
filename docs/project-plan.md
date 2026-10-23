# TestRadius Testing Factory — Project Plan

**Version:** 1.0 (draft for approval)
**Status:** ⛔ **AWAITING APPROVAL — no production code has been written**
**Date:** 2026-10-23
**Owner:** Engineering Lead
**Scope:** Phase 1 deliverable — epics, user stories, sprint plan, ADRs, risks, DoD

---

## 0. Document control

| Item | Value |
| --- | --- |
| Deliverable | `docs/project-plan.md` (Phase 1, deliverable #1) |
| Approval gate | This document, §14 |
| Next step after approval | Sprint 1 (`docs/sprints/sprint-1-plan.md` → scaffolding, Compose, CI, cell health) |
| Relationship to existing docs | `docs/project/` is the existing TIA workstream (Epic 11). This plan covers the **Testing Factory** (cell + control plane) and reuses that engine. |
| Split-on-approval | The ADRs in §10 move verbatim to `docs/adr/NNN-*.md`; this file keeps links. |

**Conventions used throughout**

- Estimates are **ideal engineer-days**: `S = 2d`, `M = 4d`, `L = 8d`. Anything larger is split.
- Priorities are MoSCoW. Stories committed to S1–S3 are the binding MoSCoW set; later sprints carry the label for planning only.
- Every story's DoD is **§12 (universal DoD)** plus the story's own "DoD+ / verification" line. The universal checklist is not repeated per story.
- `E<n>-S<k>` is a stable story ID; those IDs appear in sprint plans, branches (`feat/e1-s4-orchestrator-state-machine`) and PR titles.
- "COVERS" in the brief is implemented physically as the existing `EVIDENCE` relationship type (see ADR-007) with the mandated `granularity` property. The logical contract is unchanged.

---

## 1. Executive summary

We are building two deployable units:

- **Factory Cell** — an ephemeral, UI-less container that runs one job at a time: it isolates a run, selects tests, runs AI testing agents through MCP tools, deploys the application under test (AUT) as a *separate* workload, stitches frontend + backend coverage across the network boundary, captures evidence to the customer's object store, applies a gate policy, and reports back.
- **Control Plane** — a long-lived, multi-tenant service (Fastify + Postgres + React UI) that authenticates users, dispatches runs to cells over mTLS, stores run metadata/events/evidence *indexes*, manages cell registries, and handles licensing, metering, and signed image distribution. It never holds LLM or repository credentials and never stores client code.

The plan delivers a **thin but complete vertical slice in 6 sprints (12 weeks)**: a UI-initiated run against a sample repo → cell → separately deployed AUT → Playwright-driven e2e with stitched coverage → evidence → gate verdict → run detail in the UI. BYOC provisioning, observability hardening, the remaining four agent roles, and GA documentation follow in S7–S10.

**Three findings that need your decision before we code** (detail in §10 ADRs, §5):

1. **Inbound mTLS to cells is incompatible with BYOC.** The plan recommends an **outbound, cell-initiated control channel** (ADR-003). Without this decision S5 is blocked.
2. **Privileged Docker-in-Docker is incompatible with the cell's security constraints.** The plan recommends a **separate rootless build Job** (ADR-001). Without this decision S4 is blocked.
3. **The CP cannot presign client-owned evidence URLs.** The plan recommends **cell-minted short-TTL URLs + re-mint over the channel** (ADR-004/§5 Q3). Without this S6's evidence viewer is blocked.

Also flagged: the brief's "Test → COVERS → Symbol" is implemented as `EVIDENCE` (existing, tested engine) carrying a new `granularity` property. Renaming the relationship would break the shipped instrumentation work for no functional gain.

---

## 2. Scope

### In scope, S1–S6 (end-to-end demo)

- Monorepo, Compose dev stack, CI with architecture tests, gitleaks, SBOM.
- Cell image: Python 3.12 + Node 20 + Playwright, non-root, read-only rootfs, no UI.
- Orchestrator: `Isolate → Select → Generate → Execute → Prove → Gate → Report`, persisted transitions, SSE.
- Internal API: 6 endpoints, run-scoped JWT, mTLS, no shell/secret routes.
- Policy engine: deny-by-default egress allowlist, action/token/time limits, redaction.
- Secrets broker client: Vault + AWS Secrets Manager adapters, in-memory only.
- Agent runtime: provider abstraction (Anthropic + OpenAI-compatible), MCP layer, Playwright/HTTP/Filesystem tools, citation enforcement, a11y stop rule.
- Agents: **Planner + Executor** working end-to-end (the other four roles are post-S6).
- AUT: instrumented build Job (fixture Dockerfile), adjacent deploy/teardown, readiness.
- Coverage: Playwright V8 + source maps; backend sidecar + `X-Test-Id`; network correlation (path→route→handler→call graph); mock negative edges; `granularity ∈ {line, endpoint, inferred}`; inferred-only escalation.
- Evidence: screenshots, video, trace, network log, console log → client object storage; index in CP.
- Control plane: OIDC + RBAC, runs API, dispatch over the outbound channel, evidence index, audit log.
- Web UI: dashboard, run list, run detail with live SSE, evidence viewer, policy editor.
- Security gate at S6: no-UI-in-cell test, egress + redaction hardening, leak regression suite.

### Explicitly out of scope until S7+ (so nobody assumes otherwise)

- Explorer / Generator / Diagnoser / Healer agents (S7–S8).
- Remote AUT mode, co-located mode as a supported production mode (S8).
- BYOC Terraform, Helm, golden image signing, update distribution (S7–S9).
- Billing provider integration (Stripe etc.), full license UI (S7).
- OTel dashboards/alerts/runbooks, Sentry (S9).
- Java/Go coverage adapters, parallel Playwright sharding (post-GA).
- Multi-region, HA control plane above 3 replicas, SOC2 evidence collection.
- **No UI in the cell, ever. No client code in the CP, ever. No LLM keys in the CP, ever.**

### Assumptions

- GitHub is the only repo host in v1 (GitLab/Bitbucket adapters post-GA). `services/github-app` exists and is reused.
- One cell executes exactly one run then exits; the CP never stores cell-local state.
- Postgres 16 and Neo4j 5.x are the only stateful services; Neo4j lives **in the customer VPC** (BYOC) or as a per-tenant logical DB (SaaS).
- Dev host may run Node 22; images pin Node 20 LTS and Python 3.12. `engines`/`.nvmrc` enforce it.
- The existing `docker-compose.yml` is left untouched; the factory stack is `infra/compose/compose.factory.yaml`.
- Evidence retention defaults: 30 days (configurable per policy); CP stores metadata only.

---

## 3. Team, capacity, estimation

| Role | S1–S4 | S5 | S6 | Focus |
| --- | --- | --- | --- | --- |
| Cell/agents engineer (Python) | 1.0 | 1.0 | 0.5 | Orchestrator, agents, MCP, policy |
| Cell/coverage engineer (Python/Node) | 1.0 | 1.0 | 0.5 | Coverage, source maps, correlation, evidence |
| Control-plane engineer (TS) | 1.0 | 1.0 | 1.0 | Fastify, Prisma, auth, dispatch |
| Full-stack engineer (TS/React) | 1.0 | 1.0 | 1.0 | CP API + UI |
| Frontend engineer (React) | — | 0.5 | 1.0 | `apps/web` |
| SRE/infra (shared) | 0.5 | 0.5 | 0.5 | Compose, CI, mTLS, K8s, Terraform |
| Design/QA (shared) | 0.5 | 0.5 | 0.5 | UX, acceptance, a11y of our own UI |

**Committed capacity:** 34 dev-days/sprint for S1–S5 (4 core engineers × 10 days × 85% focus), **36–40** in S6 with the frontend engineer. 15% is deliberately uncommitted for ceremonies, review, CI flakiness, and DoD work (docs, tests, observability). Every sprint below fits inside that; S6 is the only one that uses the temporary extra capacity.

**Estimation rules**

- An `L` that cannot be demoed inside one sprint is split, not stretched.
- A story that crosses a process boundary is not estimated `S`.
- Estimates include the story's tests and observability, because the DoD requires them.

---

## 4. Architecture at a glance

```
                    ┌──────────────────────────────────────────────┐
   Browser ────────▶│  apps/web (React 18)                         │
                    │  dashboard · run detail · evidence · policy  │
                    └───────────────┬──────────────────────────────┘
                                    │ HTTPS (OIDC session)
                    ┌───────────────▼──────────────────────────────┐
                    │  apps/control-plane (Fastify + Prisma)       │
                    │  auth/RBAC · runs · registry · evidence idx  │
                    │  licensing · metering · audit                │
                    │  Postgres 16      (no client code, no keys)  │
                    └───────────────┬──────────────────────────────┘
                                    │ mTLS + run-scoped JWT
                     ═══════════════▼═══════════════  cell-initiated
                     outbound control channel (ADR-003)
                                    │
        ┌───────────────────────────▼───────────────────────────────┐
        │  apps/cell  (ephemeral, one run, NO UI)                   │
        │  orchestrator · agents · MCP · policy · evidence          │
        │  ┌─────────────────────────────────────────────────────┐  │
        │  │ AUT workload (separate Deployment/Job, same VPC)    │  │
        │  │ instrumented build + coverage sidecar               │  │
        │  └─────────────────────────────────────────────────────┘  │
        │  Neo4j 5.x (customer VPC)   Client S3/MinIO (evidence)    │
        └───────────────────────────────────────────────────────────┘
```

**Trust boundaries**

| Boundary | Control | Story |
| --- | --- | --- |
| CP → user | OIDC + RBAC | E5-S2, E6-S1 |
| CP ↔ cell | mTLS + run-scoped JWT, cell-initiated | E7-S3, E5-S5, E1-S3 |
| cell → internet | deny-by-default egress allowlist | E1-S7, E7-S2 |
| cell → secrets | broker, short-lived, in-memory | E1-S8 |
| cell → AUT | allowlisted private address only | E1-S7, E3-S2 |
| cell → evidence | client-owned bucket, presigned PUT | E4-S4 |
| agent → tools | per-role allowlist + policy check | E2-S3, E1-S7 |
| agent → code | shadow mode, workspace-only writes | §5 Q4, E2-S2 |
| CP → evidence bytes | never; metadata + URLs only | E5-S6 |

**Reuse vs build**

| Asset | Decision |
| --- | --- |
| `services/core` (AST, Neo4j, `EVIDENCE` graph, confidence formula, TIA selection) | **Reuse** as the Select/graph engine (ADR-007). Extract a thin `tia-engine` package during S2 if the cell cannot import it cleanly. |
| `packages/license-client` (Python) | Reuse the lease/fingerprint logic; add a Node verifier for the CP/cell boundary (E5-S9, post-S6). |
| `packages/vitest-plugin` | Reuse for per-test JS coverage experiments; not required by the factory's V8 path. |
| `apps/workbench` (Electron, React 19) | Not reused as a dependency. `apps/web` is new (React 18 per brief); copy individual presentational components only if trivially portable. |
| `services/github-app` | Reuse for repo auth/app installation (E0-S1 integration). |
| `apps/testradius` (Textual TUI) | Unrelated product surface; untouched. |

---

## 5. Clarifying questions and assumed defaults

| # | Question | Impact if wrong | Assumed default (proceed unless you object) | Blocks |
| --- | --- | --- | --- | --- |
| Q1 | BYOC reachability: cell-initiated channel vs CP→cell inbound | **Security / architecture** | Cell dials out over mTLS; CP commands over that channel; direct inbound only for SaaS/peered | S5 |
| Q2 | AUT build: rootless build Job vs prebuilt-only vs privileged DinD | **Security** | Rootless build Job (kaniko/BuildKit) in customer cluster; dev uses host Docker (documented deviation) | S4 |
| Q3 | Evidence URL minting when CP has no client creds | **Security / demo** | Cell mints short-TTL presigned URLs; CP re-mints over the channel; customer evidence broker post-S6 | S6 |
| Q4 | Agent write scope / autonomy | **Security** | Shadow mode; workspace-only artifacts; repo commits only with `allow_test_commits=true`; Healer never auto-merges | S3 |
| Q5 | LLM key custody | **Security** | CP stores secret *references* only; cell fetches values at runtime; prompts stay in-cell | S3 |
| Q6 | Repo strategy (in-place vs new root) | Delivery speed | Restructure in place; add `apps/cell`, `apps/control-plane`, `apps/web`, `packages/*`, `infra/*` | S1 |
| Q7 | Team & capacity | Plan validity | 4 core + FE from S5 + 0.5 SRE + 0.5 design/QA; 34 d/sprint (S6: 40) | S1 |
| Q8 | Backend stacks for v1 coverage | Coverage scope | Node (Express/Fastify/Nest) + Python (FastAPI/Flask/Django) | S4 |
| Q9 | `X-Test-Id` contract | Correlation | Opaque run-scoped id, injected per test by the runner/HTTP MCP | S4 |
| Q10 | Cell registry semantics for ephemeral cells | CP design | Registry = deployments + TTL'd instances; `/v1/health` is run-scoped | S5 |
| Q11 | SSO provider | S5 | OIDC-generic; Keycloak (dev), Auth0 (demo) | S5 |
| Q12 | React version / component reuse | S6 | New app on React 18; workbench untouched | S6 |

**Decisions I will not make unilaterally:** Q1, Q2, Q3, Q4, Q5. If any default is rejected, the affected sprint's scope changes and this plan is re-baselined before that sprint starts.

---

## 6. Epics

Each epic lists: goal, stories (priority · estimate · dependencies · Given/When/Then acceptance criteria), and an epic-level definition of done in addition to §12.

---

### E0. Foundation

**Goal.** One monorepo, one command to bring up a working local stack, one CI pipeline that enforces tests, security, and architecture boundaries. Nothing downstream is credible if this is shaky, so this epic is front-loaded and its exit criteria are hard.

**Stories**

#### E0-S1 — Monorepo scaffolding and workspace tooling
`Must` · `M (4d)` · deps: —
- **AC1** — Given a clean clone, when a developer runs `make bootstrap`, then pnpm + uv workspaces install, git hooks install, and `make doctor` reports Node 20, Python 3.12, Docker, and Compose versions.
- **AC2** — Given the scaffolding, when I inspect the tree, then `apps/{cell,control-plane,web}`, `packages/{shared-types,test-fixtures}`, `infra/{compose,helm,terraform}`, `docs/{adr,runbooks,demos,sprints}` exist and each app builds independently.
- **AC3** — Given the existing product, when the factory is scaffolded, then the root `docker-compose.yml`, `services/`, and `apps/workbench` are untouched and their CI still passes.
- **DoD+** — Architecture decision recorded: in-place restructure (Q6). `make` targets documented in README.

#### E0-S2 — Local development stack (Compose)
`Must` · `M (4d)` · deps: E0-S1
- **AC1** — Given `make up`, when all containers report healthy, then `control-plane`, `web`, `postgres:16`, `neo4j:5`, `minio`, `mock-oidc`, and `mock-aut` are reachable on documented ports within 5 minutes.
- **AC2** — Given the stack is up, when I run `make smoke`, then it creates a run through the CP, observes it reach `Report`, and prints the evidence bucket keys.
- **AC3** — Given `make down -v`, when I bring the stack up again, then it converges from a clean slate with no manual steps and no committed secrets.
- **DoD+** — Compose file lives at `infra/compose/compose.factory.yaml`; root `docker-compose.yml` untouched (Q6).

#### E0-S3 — CI pipeline
`Must` · `M (3d)` · deps: E0-S1
- **AC1** — Given a PR, when CI runs, then lint, typecheck, unit tests (pytest + Vitest), integration tests (Testcontainers), architecture tests, gitleaks, and image build all run, and required checks block merge.
- **AC2** — Given a PR that adds `express.static` to the cell, when CI runs, then the architecture test fails and the job is red.
- **AC3** — Given a merged main build, when it completes, then images are published with a digest and an SBOM artifact is attached.
- **DoD+** — Median PR pipeline < 12 minutes on the fixture repo; cache keys documented.

#### E0-S4 — Engineering standards and ADR workflow
`Should` · `S (2d)` · deps: E0-S1
- **AC1** — Given a new decision, when an engineer adds `docs/adr/NNN-slug.md`, then the template (Context/Decision/Consequences/Alternatives) is enforced by a docs lint check.
- **AC2** — Given a commit, when it is pushed, then commitlint enforces Conventional Commits and pre-commit runs ruff, eslint/prettier, and gitleaks.
- **AC3** — Given `main`, when I read `CONTRIBUTING.md`, then branch naming, PR size guidance, and the "stop and raise" rules are stated.
- **DoD+** — `CODEOWNERS` set; branch protection enabled on `main`.

#### E0-S5 — Shared contracts package
`Should` · `S (3d)` · deps: E0-S1
- **AC1** — Given the cell's OpenAPI document, when `packages/shared-types` is generated, then TypeScript types for the cell API and the CP API exist and are consumed by `apps/web` and `apps/control-plane`.
- **AC2** — Given a contract change, when the generating code changes but the checked-in types do not, then CI fails.
- **AC3** — Given a run event, when it is emitted by the cell, then it validates against the shared JSON schema (versioned) in both Python and TypeScript tests.
- **DoD+** — Schema version bump policy documented (additive = minor, breaking = major).

#### E0-S6 — Test fixtures: sample AUT and sample repo
`Must` · `S (3d)` · deps: E0-S1
- **AC1** — Given `packages/test-fixtures`, when the fixture AUT starts, then it serves a UI with 3 routes and a backend API with 3 endpoints, with seeded deterministic data.
- **AC2** — Given the fixture UI, when a test targets it, then it contains exactly two intentional accessibility defects (unlabeled button, icon-only link) used to exercise the stop-and-report rule.
- **AC3** — Given the fixture repo, when instrumented, then it produces non-empty frontend and backend coverage and at least one mocked network route.
- **DoD+** — Fixtures versioned and pinned; no network egress needed at test time.

#### E0-S7 — Architecture-test harness
`Must` · `S (2d)` · deps: E0-S3
- **AC1** — Given a rule file, when the suite runs, then it can assert dependency allow/deny lists for both `package.json` and `pyproject.toml`/imports, plus filesystem patterns.
- **AC2** — Given a violation, when the test fails, then the message names the offending dependency and the rule that failed.
- **AC3** — Given a new rule, when added to the harness, then it runs in CI without editing workflow YAML.
- **DoD+** — Used by E7-S1; documented in `docs/architecture-tests.md`.

#### E0-S8 — Local secrets and broker
`Must` · `S (2d)` · deps: E0-S2
- **AC1** — Given `make secrets`, when it completes, then dev values for the LLM key, repo token, DB creds, and evidence bucket creds exist in the local broker (Vault dev / MinIO), not in any file.
- **AC2** — Given the repo, when I run `git grep -iE "(sk-|ghp_|AKIA)"`, then no matches exist and gitleaks passes.
- **AC3** — Given a cell starts locally, when it fetches secrets, then values are read once into memory, the fetch is audit-logged, and neither values nor prefixes appear in logs.
- **DoD+** — `.env` files remain git-ignored; rotation steps in `docs/runbooks/local-dev.md`.

**Epic DoD (E0)**

- A new engineer can go from clone to a green `make smoke` in under 30 minutes using only the README.
- CI blocks merge on tests, gitleaks, architecture tests, and image build.
- No secrets in the repo; no UI dependency in the cell skeleton.

---

### E1. Cell — Core Runtime

**Goal.** A hardened, UI-less container that exposes exactly six run-scoped endpoints and drives a persisted, resumable state machine with policy and secret handling in place. After this epic the cell can "run a run" with stubs; after E2 it can think.

**Stories**

#### E1-S1 — Cell container image (multi-stage, hardened)
`Must` · `M (5d)` · deps: E0-S1, E0-S2
- **AC1** — Given the image, when it runs as `uid 10001` with a read-only rootfs and `--cap-drop ALL`, then the cell starts and writes only to the workspace mount and the declared tmpfs paths (`/tmp`, `~/.cache`).
- **AC2** — Given the image, when scanned, then it contains Python 3.12, Node 20, Playwright browsers, and Chromium runtime libs; final size is under 2.5 GB and the SBOM is attached.
- **AC3** — Given the image, when the architecture test inspects its dependency tree, then no UI framework, web server for static assets, template engine, or React/Vue/Angular/Next/Tailwind package is present.
- **AC4** — Given a Compose run, when the container is inspected, then it has no privileged flag, no Docker socket mount, and no `CAP_SYS_ADMIN`.
- **DoD+** — Documented deviation: dev Compose mounts the host Docker socket for the *AUT builder only* (ADR-001), never for the cell itself.

#### E1-S2 — Health and readiness endpoint
`Must` · `S (2d)` · deps: E1-S1
- **AC1** — Given the cell is starting, when `GET /v1/health` is called, then it returns `503` with `{ready:false, aut_status, graph_status}` until dependencies are reachable, then `200` with `{ready:true}`.
- **AC2** — Given a healthy cell, when the endpoint is called, then the response time is `< 50 ms` p95 and contains no secret, path, or version detail beyond the contract.
- **AC3** — Given the graph or AUT is unavailable, when health is called, then `ready` is false, the specific status field explains why, and no exception stack is returned.
- **DoD+** — Contract added to OpenAPI; probe configured in Compose and Helm.

#### E1-S3 — Internal API skeleton and run-scoped token middleware
`Must` · `M (4d)` · deps: E1-S1
- **AC1** — Given a request with a missing, expired, wrong-audience, or wrong-run token, when it hits any `/v1/*` route, then it is rejected `401/403` with a machine-readable reason and the attempt is audited.
- **AC2** — Given a valid run-scoped token, when it calls a route for a different run id, then the request is rejected `403` even if the token is otherwise valid.
- **AC3** — Given the router, when the route-audit test enumerates endpoints, then the only exposed routes are the six in the contract — no shell, exec, file-read, or secret-retrieval route exists.
- **AC4** — Given a mutating request, when it is replayed with the same JWT `jti`, then it is rejected (single-use for mutating routes) and the replay is logged.
- **DoD+** — Token verification is a shared library with a negative-case matrix; mTLS client-cert identity is bound to `aud` (E7-S3).

#### E1-S4 — Orchestrator state machine
`Must` · `L (8d)` · deps: E1-S2, E1-S3
- **AC1** — Given a new run, when it starts, then it transitions `Isolate → Select → Generate → Execute → Prove → Gate → Report` in order, persisting `{phase, entered_at, attempt, actor, reason}` for each transition.
- **AC2** — Given a phase raises, when the orchestrator handles it, then the run enters `Failed` with a phase-attributed error, retries at most the configured count, and never skips a phase.
- **AC3** — Given the cell restarts mid-run, when it resumes, then it continues from the last persisted phase idempotently (no duplicate evidence uploads, no duplicate gate verdicts).
- **AC4** — Given a phase exceeds its timeout, when the deadline passes, then it is cancelled cooperatively, the AUT is torn down, and the run ends `TimedOut` with the phase named.
- **DoD+** — State diagram in `docs/architecture/orchestrator.md`; one OTel span per phase; `Isolate` creates the workspace and takes a policy snapshot; `Gate` consumes policy thresholds (shadow mode never blocks).

#### E1-S5 — Run lifecycle API
`Must` · `M (4d)` · deps: E1-S3, E1-S4
- **AC1** — Given a valid `POST /v1/runs` body, when it is submitted with an idempotency key, then exactly one run is created, the response is `202` with `{id, status, phase}`, and a replay returns the same run.
- **AC2** — Given an invalid body (unknown scope, malformed commit SHA, missing repo, oversized policy), when submitted, then `422` is returned with field-level errors and no run is created.
- **AC3** — Given a running run, when `POST /v1/runs/{id}/cancel` is called, then the run stops within 5 seconds, the AUT is torn down, and the state is `Cancelled`; a second cancel returns `409`.
- **AC4** — Given a terminal run, when `GET /v1/runs/{id}` is called, then it returns status, phase, timings, metrics and no secret or absolute-path detail.
- **DoD+** — `scope: impacted|full` honored; impacted falls back to full when the graph is unavailable and records why.

#### E1-S6 — SSE event stream
`Must` · `M (4d)` · deps: E1-S4
- **AC1** — Given a running run, when a client opens `GET /v1/runs/{id}/events`, then it receives ordered events with monotonically increasing sequence ids, agent steps, tool calls, and verdicts.
- **AC2** — Given a disconnected client, when it reconnects with `Last-Event-ID`, then it receives only the missed events, with no gaps and no duplicates.
- **AC3** — Given a slow consumer, when its buffer exceeds the cap, then the cell drops to heartbeat-only and emits a `stream_lagged` marker instead of growing memory unboundedly.
- **AC4** — Given a subscriber, when events are inspected, then every payload is redacted and schema-validated before write, and the stream carries a heartbeat at least every 15 s.
- **DoD+** — Contract test for schema version; backpressure and reconnect covered by tests.

#### E1-S7 — Policy engine (egress, redaction, action limits)
`Must` · `L (8d)` · deps: E1-S3
- **AC1** — Given a policy, when any tool attempts egress, then only allowlisted destinations (LLM endpoint, package registries, AUT private address) are permitted and every denial is audited with the attempted host.
- **AC2** — Given per-run limits (tool calls, LLM tokens, wall clock, artifact bytes), when a limit is reached, then the run stops at the `Execute`/`Prove` boundary with `BudgetExceeded` and a partial report is still emitted.
- **AC3** — Given a log line, evidence filename, or event containing a JWT, Bearer token, API key, password, or configured PII pattern, when it is written, then it is redacted before the write (verified by a redaction test over logs and artifacts).
- **AC4** — Given `POST /v1/policy/reload` with a valid signed policy, when it applies, then new limits take effect for the next step without restarting the run, and an invalid policy is rejected atomically.
- **DoD+** — Default-deny is the tested default; allowlist entries are documented in the runbook and require an ADR change.

#### E1-S8 — Secrets broker client
`Must` · `M (4d)` · deps: E1-S3, E0-S8
- **AC1** — Given a run starts, when it requests a secret, then the cell authenticates to Vault (K8s auth) or AWS Secrets Manager (IRSA) and receives a value with a TTL no longer than the run's maximum duration.
- **AC2** — Given a secret is fetched, when the run ends or fails, then the reference is cleared from memory, no value was written to the workspace, evidence, or logs, and the fetch appears in the audit trail with a reference id only.
- **AC3** — Given the broker is unavailable, when a secret is required, then the run fails fast with `SecretUnavailable` and does not retry in a tight loop (bounded backoff, then fail).
- **AC4** — Given a leaked-value test, when logs and artifacts are scanned for the seeded sentinel value, then zero matches are found across all sinks.
- **DoD+** — Provider interface (`VaultProvider`, `AwsSecretsManagerProvider`, `FakeProvider` for tests); no secret is ever persisted by the cell.

**Epic DoD (E1)**

- A run can be created, observed over SSE, cancelled, and completes with stubs.
- Kill the cell mid-run; on restart it resumes without duplicating work.
- `grep` for secret-shaped values across logs/evidence returns nothing.
- Route audit shows exactly six endpoints.

---

### E2. Cell — Agent Runtime

**Goal.** A model-agnostic agent runtime with role-scoped tool access, mandatory context citations, and a hard accessibility rule. By the end of the epic, a Planner decomposes a goal and an Executor drives a real browser through Playwright MCP against the sample AUT.

**Stories**

#### E2-S1 — Model provider abstraction
`Must` · `M (4d)` · deps: E0-S5
- **AC1** — Given a provider interface (`complete`, `stream`, `tool_calls`, `token_usage`), when Anthropic and an OpenAI-compatible endpoint are configured, then the same agent loop runs against either without code changes.
- **AC2** — Given a provider error (rate limit, 5xx, timeout), when the agent retries, then it backs off with jitter, respects a per-run budget, and surfaces a typed error after the cap.
- **AC3** — Given a request, when logs are inspected, then the API key is never logged, token counts are recorded per step, and prompt content is excluded from CP-bound events by default.
- **DoD+** — `FakeProvider` used by all agent tests; provider/model selection is policy-configurable per run.

#### E2-S2 — Agent loop, tool protocol, and citation enforcement
`Must` · `L (8d)` · deps: E2-S1, E1-S7
- **AC1** — Given a goal, when the loop runs, then each step is persisted as `{thought, action, args, observation, citations[], usage}` and streamed over SSE.
- **AC2** — Given an action without at least one context citation, when the runtime validates the step, then the action is **blocked**, the model is re-prompted once with the validation error, and a second failure ends the step with `MissingCitation`.
- **AC3** — Given a repeated failing action or identical tool call, when it exceeds the configured repetition threshold, then the loop stops with `LoopDetected` rather than burning the budget.
- **AC4** — Given a step, when the trace is inspected, then it links the cited graph/AST node ids, the tool call, the observation, and the resulting verdict.
- **DoD+** — Citation ids resolve to real nodes (validated, not just formatted); step schema versioned in `shared-types`.

#### E2-S3 — MCP layer and tool registry
`Must` · `M (4d)` · deps: E2-S2
- **AC1** — Given a server definition, when the cell starts a run, then it connects/spawns only the MCP servers allowed for that role, with per-call timeouts and health checks.
- **AC2** — Given a role, when it invokes a tool outside its allowlist, then the call is rejected before execution and audited with `{role, tool, reason}`.
- **AC3** — Given a tool call, when it executes, then a policy check for egress/limits runs first, and the call plus result metadata appear in the event stream.
- **DoD+** — Registry is declarative; adding a tool requires an allowlist entry and a contract test.

#### E2-S4 — Playwright MCP integration
`Must` · `M (5d)` · deps: E2-S3, E0-S2 (Compose mock AUT for S3)
- **AC1** — Given a URL, when the agent navigates, then it can click, type, assert visible text, capture a screenshot, and read the accessibility tree, with each action recorded as an event.
- **AC2** — Given an interactive element with no accessible name/label, when the agent targets it, then the tool **stops**, emits a `testability_defect` verdict with the element snapshot, and does not fall back to a CSS selector.
- **AC3** — Given a successful step, when evidence is captured, then screenshots and a trace are produced and associated with the step id (bytes stored by E4-S4).
- **AC4** — Given a browser crash or navigation timeout, when it occurs, then the step fails with a typed error and the run continues only if policy allows.
- **DoD+** — A11y-first query policy is enforced in the tool, not just the prompt; the negative case is covered by a test against the fixture's intentional defect.

#### E2-S5 — HTTP/API and scoped Filesystem MCP
`Should` · `M (4d)` · deps: E2-S3
- **AC1** — Given an allowed host, when the agent performs an HTTP request, then it injects `X-Test-Id`, validates the response against an optional schema, and records status/latency/headers (redacted) as evidence.
- **AC2** — Given a non-allowlisted host, when requested, then the tool rejects before egress and the denial is audited.
- **AC3** — Given a filesystem tool call, when the path escapes the workspace (including symlinks and `..`), then it is rejected; reads/writes outside the allowed subpaths are impossible.
- **DoD+** — Path-traversal and egress-denial tests; filesystem scope configurable by policy.

#### E2-S6 — Git and Graph (Neo4j) MCP
`Should` · `M (4d)` · deps: E2-S3
- **AC1** — Given the Git tool, when the agent requests history or a diff, then only read operations (`log`, `show`, `diff`, `blame`) are available; any mutating git command is rejected.
- **AC2** — Given the graph tool, when the agent queries, then it connects with a read-only user, parameterized queries only, and row/byte caps are enforced.
- **AC3** — Given a query, when it would exceed the cap, then it returns a truncated result with an explicit `truncated:true` marker rather than failing or flooding context.
- **DoD+** — Query templates for common lookups; no string interpolation of user input into Cypher.

#### E2-S7 — Context retrieval client
`Must` · `M (4d)` · deps: E0-S5
- **AC1** — Given a changed symbol, when the agent asks for context, then it receives the symbol, its file/span, owners, prior evidence, and recent test history, each with a stable node id.
- **AC2** — Given repeated requests in one run, when the cache is warm, then the same node id and a cache hit are returned, and the context payload stays within the configured token budget.
- **AC3** — Given the graph is unavailable, when context is requested, then the client degrades to a documented fallback (filesystem/AST subset) and marks the run's context quality as `degraded`.
- **DoD+** — Cache is per-run, bounded, and cleared at teardown; retrieval latency p95 < 500 ms on the fixture.

#### E2-S8 — Planner agent
`Must` · `S (3d)` · deps: E2-S2, E2-S7
- **AC1** — Given a run goal and selected tests, when the Planner runs, then it emits an ordered plan of steps, each with citations and an expected outcome, before any Execute step.
- **AC2** — Given no usable context, when the Planner runs, then it refuses to invent a plan and returns `InsufficientContext` with the missing inputs named.
- **AC3** — Given a plan, when it is validated, then cycles, duplicate steps, and steps referencing unavailable tools are rejected before execution.
- **DoD+** — Plan artifact stored and surfaced in events; re-planning allowed once on `Diagnoser` input (post-S6).

#### E2-S9 — Explorer agent
`Should` · `M (4d)` · deps: E2-S4
- **AC1** — Given a goal, when the Explorer runs, then it discovers reachable states/routes from the a11y tree and records the exploration path with citations.
- **AC2** — Given a discovered route not covered by existing tests, when it is reported, then it becomes a coverage-gap candidate with evidence, not an automatic test.
- **AC3** — Given the exploration budget, when exhausted, then it stops and reports partial coverage rather than looping.
- **DoD+** — Backlog (S7). No autonomous test authoring in this story.

#### E2-S10 — Generator agent
`Should` · `M (4d)` · deps: E2-S8
- **AC1** — Given a plan and a11y tree, when the Generator runs, then it writes a Playwright test spec into the run workspace only.
- **AC2** — Given `allow_test_commits=false`, when generation completes, then no commit/branch/push occurs and the artifact is attached to the run.
- **AC3** — Given generated code, when it is linted/executed, then failures are reported as generation defects with the failing step, never silently dropped.
- **DoD+** — Backlog (S7). No repo mutation by default (Q4).

#### E2-S11 — Executor agent
`Must` · `M (4d)` · deps: E2-S4, E2-S8
- **AC1** — Given a plan, when the Executor runs, then it performs each step through the allowed tools, records a verdict per step, and stops at the first blocking defect.
- **AC2** — Given a test failure, when the Executor captures it, then evidence (screenshot/video/trace/network/console) is attached and the failure is classified only if a Diagnoser is available; otherwise it stays `unclassified`.
- **AC3** — Given a successful run, when it finishes, then each executed test has a final verdict plus citations, and the run's metrics (steps, tokens, duration) are emitted.
- **DoD+** — The S3 demo path: Planner + Executor + Playwright MCP against the fixture.

#### E2-S12 — Diagnoser agent
`Could` · `M (4d)` · deps: E2-S11
- **AC1** — Given a failure, when the Diagnoser runs, then it classifies it as `product | test | environment | flaky` with cited evidence.
- **AC2** — Given a flaky signal (pass on bounded retry), when classified, then the test is quarantined with evidence rather than reported as a product defect.
- **AC3** — Given insufficient evidence, when it cannot classify, then it returns `inconclusive` rather than guessing.
- **DoD+** — Backlog (S8).

#### E2-S13 — Healer agent
`Could` · `M (5d)` · deps: E2-S12
- **AC1** — Given a `test`-class diagnosis, when the Healer proposes a fix, then the proposal is a workspace patch with rationale and citations.
- **AC2** — Given policy `allow_test_commits=false`, when a fix is proposed, then it is surfaced as a suggestion only and never applied to the repo.
- **AC3** — Given a proposed fix, when it is validated, then the affected tests pass on retry before the suggestion is marked `verified`.
- **DoD+** — Backlog (S8). Never auto-merges, regardless of policy.

**Epic DoD (E2)**

- A planner→executor run against the fixture AUT produces ≥1 verified step per route and a testability-defect report for the two intentional a11y issues.
- Every action in the event log carries ≥1 resolvable citation.
- No UI dependency entered the cell via the agent tooling.

---

### E3. Cell — AUT Deployment Controller

**Goal.** Build and run the client's application as a **separate workload**, never in the cell's namespace, with deterministic readiness, teardown, and orphan protection. This is where the security posture is easiest to accidentally break, so the negative tests matter as much as the happy path.

**Stories**

#### E3-S1 — Instrumented AUT build (fixture Dockerfile, build Job)
`Must` · `S (3d)` · deps: E0-S6, E1-S7
- **AC1** — Given the fixture repo, when the cell prepares the AUT, then it creates a **separate** build Job in the customer cluster using the repo's Dockerfile, rootless (kaniko/BuildKit), with the workspace mounted read-only.
- **AC2** — Given a successful build, when it completes, then the cell records the image **digest** and the source commit SHA, and refuses to proceed if they do not correspond to the requested run inputs.
- **AC3** — Given a failed build, when it occurs, then the run ends `BuildFailed` with the tail of the build log (redacted) and the AUT is never deployed.
- **DoD+** — No `--privileged`, no Docker socket in the cell (ADR-001). Generic repo→image builder is E3-S7.

#### E3-S2 — Adjacent AUT workload deploy and teardown
`Must` · `M (5d)` · deps: E3-S1
- **AC1** — Given a built digest, when the cell deploys, then the AUT runs as a separate Deployment/Job in its own namespace with a network policy permitting only the cell → AUT address and the AUT → its declared dependencies.
- **AC2** — Given the run ends (success, failure, cancel, timeout), when teardown runs, then the workload, its Service, and its config are removed within 60 s and the namespace is verified empty.
- **AC3** — Given the cell dies mid-run, when the orphan reaper runs, then the AUT is removed by label/age and the event is audited (hardening in E3-S4).
- **AC4** — Given the cell's own namespace, when inspected during a run, then no AUT container or client code executes there.
- **DoD+** — Integration test asserts namespace separation and teardown; network-policy denial test for cell→AUT is scoped to the allowlisted address only.

#### E3-S3 — Readiness, migrations, and seed
`Must` · `S (3d)` · deps: E3-S2
- **AC1** — Given a deployed AUT, when it starts, then the cell waits for a readiness probe (HTTP or TCP) with a bounded timeout before any agent or test step.
- **AC2** — Given migrations are declared in policy, when the AUT starts, then migrations run once, their outcome is recorded, and a failure fails the run before tests execute.
- **AC3** — Given seed data is declared, when readiness completes, then seeding is idempotent and the run records the seed version used.
- **DoD+** — Timeout and migration-failure paths tested; no silent "ready" when the app returns 5xx.

#### E3-S4 — Orphan reaper and teardown hardening
`Should` · `M (4d)` · deps: E3-S2
- **AC1** — Given resources labelled with a run id older than the max run duration, when the reaper runs, then it removes them and audits each removal.
- **AC2** — Given a reaper race with an active run, when the run's heartbeat is fresh, then its resources are never removed.
- **AC3** — Given a teardown failure, when retries are exhausted, then the run is marked `TeardownFailed` and an alert-worthy event is emitted.
- **DoD+** — Backlog (S7).

#### E3-S5 — Co-located fallback mode (dev only)
`Could` · `S (3d)` · deps: E3-S2
- **AC1** — Given `mode: co-located`, when the run starts, then the AUT runs as a sibling Compose service and the run is marked `unsupported_production:true` in its metadata.
- **AC2** — Given co-located mode in a non-dev environment, when requested, then the CP rejects the policy.
- **AC3** — Given the mode, when the UI renders the run, then a persistent warning badge is shown.
- **DoD+** — Backlog (S8). Used only for S3's pre-deployment demo path.

#### E3-S6 — Remote AUT mode (SaaS)
`Could` · `L (8d)` · deps: E3-S2, E5-S5
- **AC1** — Given a remote URL and a required commit SHA, when the run starts, then the cell verifies the deployed build's SHA and the environment lock before any action.
- **AC2** — Given a SHA mismatch or unlocked environment, when verification fails, then the run is refused with `EnvironmentMismatch`.
- **AC3** — Given a verified remote AUT, when tests run, then evidence and coverage are still attributed to the verified SHA.
- **DoD+** — Backlog (S8). SaaS only.

#### E3-S7 — Generalized builder (repo → instrumented image)
`Should` · `M (5d)` · deps: E3-S1
- **AC1** — Given a repo with a supported stack, when the builder runs, then it produces an instrumented image without requiring a hand-written Dockerfile.
- **AC2** — Given an unsupported stack, when detected, then it fails early with a capability report rather than a mid-build error.
- **AC3** — Given a build cache, when the commit is unchanged, then the image is reused by digest.
- **DoD+** — Backlog (S7).

**Epic DoD (E3)**

- The fixture AUT is built, deployed, ready, tested, and torn down with zero resources left behind.
- A deliberate kill -9 of the cell leaves no surviving AUT after the reaper window.
- The cell namespace never contains client code (verified by an integration assertion).

---

### E4. Coverage & Evidence

**Goal.** Make "which test touched which symbol" true across the browser→server boundary, with honest granularity and explicit mock boundaries, and capture proof for every verdict. This is the differentiator: without it, the factory is a demo recorder.

**Stories**

#### E4-S1 — Frontend V8 coverage and source-map remapping
`Must` · `L (8d)` · deps: E3-S2, E2-S4
- **AC1** — Given a Playwright test, when it runs, then JS coverage is started/stopped per test and the raw V8 ranges are captured with the test id.
- **AC2** — Given a built bundle with source maps, when coverage is remapped, then covered positions resolve to original TypeScript files and line numbers; files without maps are marked unmapped and excluded from symbol edges.
- **AC3** — Given remapped lines, when they are attributed to symbols, then the existing AST resolver assigns them innermost-owner, and each edge carries `granularity=line`.
- **AC4** — Given two tests covering the same component, when edges are written, then each test gets its own edge set (no cross-test bleed).
- **DoD+** — Source-map correctness spot-checked against the fixture; unmapped bytes are reported as a metric.

#### E4-S2 — Backend coverage sidecar and test-id propagation
`Must` · `L (8d)` · deps: E3-S2
- **AC1** — Given an instrumented AUT, when a test makes a request, then `X-Test-Id` is propagated and the backend agent attributes covered lines to that test id (dynamic contexts for Python; per-request V8/nyc contexts for Node).
- **AC2** — Given a request without `X-Test-Id`, when coverage is collected, then it is attributed to a `no_test_id` bucket and reported, never silently merged into a specific test.
- **AC3** — Given a supported framework, when the sidecar starts, then it exposes a capability probe (`stack`, `version`, `supported:true/false`) and the run refuses coverage claims it cannot make.
- **AC4** — Given a run, when the sidecar is torn down, then its raw data is flushed and no coverage file remains on the AUT's writable layer.
- **DoD+** — Adapters: Node (Express/Fastify/Nest), Python (FastAPI/Flask/Django). Unsupported stack → `coverage_kind=inferred` + escalation, not a false `line` claim.

#### E4-S3 — Coverage stitcher: granularity, mocks, and escalation
`Must` · `M (5d)` · deps: E4-S1, E4-S2
- **AC1** — Given frontend and backend evidence for a test, when the stitcher writes edges, then it dedupes by stable symbol identity and every edge carries `granularity ∈ {line, endpoint, inferred}`.
- **AC2** — Given a network record, when correlation runs, then the request path resolves to a route via the framework route table, the handler is linked as `endpoint`, and the static call graph descendants are linked as `inferred`.
- **AC3** — Given a mocked route, when correlation reaches it, then a negative edge (`MOCKED`) is recorded, traversal **stops**, and no coverage is claimed beyond the mock.
- **AC4** — Given a changed symbol with only `inferred` coverage, when selection runs, then the policy escalates (broaden to endpoint/file, then full suite) and records `escalated_from=inferred` with a reason.
- **AC5** — Given a build whose SHA does not match the requested commit, when stitching runs, then it refuses to write edges (`CoverageShaMismatch`).
- **DoD+** — Confidence uses the existing formula (line ratio × inferred weight); endpoint handler = 1.0, propagated descendants = `inferred` (0.5 weight). No new ad-hoc scores.

#### E4-S4 — Evidence collector to client-owned object storage
`Must` · `M (4d)` · deps: E2-S4, E0-S8
- **AC1** — Given a step, when evidence is captured, then screenshots, video, trace, network log, and console log are written to a run-scoped prefix in the **client's** bucket, with content hashes recorded.
- **AC2** — Given evidence bytes, when scanning runs, then the bucket is the only sink; the CP and the cell's local disk retain no copy after upload.
- **AC3** — Given a non-allowlisted or unavailable bucket, when upload fails, then the step is marked `evidence_missing` (never silently passes) and the run records the failure.
- **AC4** — Given a captured artifact, when it is written, then redaction has already been applied (headers, tokens, PII patterns) and the manifest is signed/checksummed.
- **DoD+** — Presigned PUT with per-run prefix; lifecycle policy documented; retention is policy-driven.

#### E4-S5 — Evidence manifest and chain-of-custody
`Should` · `S (3d)` · deps: E4-S4
- **AC1** — Given a completed run, when the manifest is generated, then it lists every artifact with hash, size, content type, step id, and upload status.
- **AC2** — Given a manifest, when the CP indexes it, then the CP stores metadata only and can verify hashes on request.
- **AC3** — Given a missing artifact referenced by a verdict, when verification runs, then the verdict is downgraded and flagged.
- **DoD+** — Backlog (S7).

#### E4-S6 — Coverage quality report per run
`Could` · `S (3d)` · deps: E4-S3
- **AC1** — Given a run, when it finishes, then it reports coverage completeness (files discovered/scheduled/covered), unmapped bytes, endpoint coverage %, and mock boundaries.
- **AC2** — Given a low-coverage run, when it is reported, then the gate policy can fail or warn based on thresholds.
- **AC3** — Given a comparison, when two runs are viewed, then the delta is shown per route/component.
- **DoD+** — Backlog (S7).

**Epic DoD (E4)**

- The fixture run produces `line` edges for frontend symbols, `endpoint` edges for handlers, `inferred` edges for call-graph descendants, and `MOCKED` negative edges.
- A changed symbol with only inferred coverage demonstrably escalates.
- Evidence for every failed test is retrievable from the client bucket and indexed in the CP.

---

### E5. Control Plane — Backend API

**Goal.** A stateless, auditable API that owns identity, dispatch, history, evidence indexes, and commercial controls — while holding no client code and no LLM keys.

**Stories**

#### E5-S1 — CP scaffold, Prisma schema, migrations
`Must` · `M (4d)` · deps: E0-S1
- **AC1** — Given a fresh Postgres, when `prisma migrate deploy` runs, then the schema for users/orgs, runs, run events (index), cells, evidence, policies, licenses, meters, and audit exists with indexes on tenant + time.
- **AC2** — Given the app, when it starts without a DB, then it fails readiness (not liveness) and does not serve traffic.
- **AC3** — Given a tenant, when any query runs, then row-level scoping is applied by a repository layer and a cross-tenant access test fails closed.
- **DoD+** — `DATABASE_URL` from env/broker; no migrations auto-run in production.

#### E5-S2 — OIDC authentication and RBAC
`Must` · `M (5d)` · deps: E5-S1
- **AC1** — Given an unauthenticated request, when it hits a protected route, then it is redirected/`401` and no run data leaks.
- **AC2** — Given roles `admin | operator | viewer`, when a viewer attempts a mutating action, then it is `403`; an operator can start/cancel runs but not manage billing/licenses; an admin can.
- **AC3** — Given a valid session, when it is idle beyond the policy, then it expires and refresh is re-validated against the IdP.
- **AC4** — Given an SSO login, when the user first appears, then a least-privilege role is assigned by default and the assignment is audited.
- **DoD+** — OIDC discovery + JWKS rotation handled; Keycloak (dev) and Auth0 (demo) both tested.

#### E5-S3 — Runs API and history
`Must` · `M (5d)` · deps: E5-S1, E5-S2
- **AC1** — Given a `POST /v1/runs` from an operator, when accepted, then a run row is created, dispatched to a cell, and the response includes `{id, status, cell_id, created_at}`.
- **AC2** — Given a run, when `GET /v1/runs/{id}` is called, then it returns metadata, phase history, metrics, and verdict; `GET /v1/runs` supports tenant-scoped pagination/filtering.
- **AC3** — Given a run event stream, when stored, then events are appended in order and retrievable after completion (bounded retention) with redaction applied.
- **AC4** — Given a project policy, when `GET/PUT /v1/projects/{id}/policy` is called, then the policy is versioned, validated, and (on PUT) pushed to the running/next cell.
- **DoD+** — Idempotency keys honored; `scope` and `policy` passed through unmodified.

#### E5-S4 — Cell registry and health
`Should` · `M (4d)` · deps: E5-S1
- **AC1** — Given a cell registers, when it heartbeats, then the registry stores deployment id, region, capabilities, image digest, and last-seen; stale instances expire after a TTL.
- **AC2** — Given a cell that misses heartbeats, when the TTL passes, then it is marked `unhealthy` and no new runs are dispatched to it.
- **AC3** — Given the cells view/API, when queried, then it shows only metadata — never cell-local paths, secrets, or client names.
- **DoD+** — Registry distinguishes **deployments** (long-lived) from **instances** (per-run, TTL) per Q10.

#### E5-S5 — Outbound control channel and run dispatch
`Must` · `L (8d)` · deps: E7-S3, E1-S5
- **AC1** — Given a cell in a private VPC, when it starts, then it establishes an mTLS channel to the CP and receives dispatch messages without any inbound firewall rule.
- **AC2** — Given a dispatch, when the CP sends it, then it is authenticated (mTLS identity + run-scoped token), deduplicated by run id, and acknowledged; a lost ack causes a bounded retry, never a duplicate run.
- **AC3** — Given a channel drop, when the cell reconnects, then it resumes heartbeats and receives queued dispatches in order per cell.
- **AC4** — Given the CP is down, when the cell is mid-run, then the run continues locally and buffers events, and reports them on reconnect (bounded buffer with explicit loss markers).
- **DoD+** — ADR-003 signed off before implementation; load test for 50 concurrent channels.

#### E5-S6 — Evidence index and URL broker
`Must` · `M (4d)` · deps: E4-S4
- **AC1** — Given an evidence manifest, when the cell reports it, then the CP stores only metadata (key, bucket, hash, content type, step, run) and never bytes.
- **AC2** — Given an evidence request, when the stored URL has expired, then the CP requests a fresh presigned URL over the control channel and returns it without holding client credentials.
- **AC3** — Given a viewer, when they lack access to the run's tenant, then they receive `403` and the request is audited.
- **DoD+** — URLs are short-TTL and scoped to one object; no bucket-wide credentials ever reach the browser.

#### E5-S7 — Audit log
`Must` · `S (2d)` · deps: E5-S2
- **AC1** — Given an auth event or mutating API call, when it occurs, then an append-only audit record is written with actor, tenant, action, target, result, and request id.
- **AC2** — Given audit records, when tampering is attempted, then the hash chain detects it and an integrity check fails loudly.
- **AC3** — Given an export request, when an admin requests audit data, then it is streamed redacted and the export itself is audited.
- **DoD+** — Retention configurable; no secret values in audit payloads.

#### E5-S8 — Billing and usage metering
`Should` · `M (6d)` · deps: E5-S3
- **AC1** — Given a completed run, when metering runs, then billable units (run minutes, agent tokens, evidence GB) are recorded against the tenant with an idempotency key.
- **AC2** — Given a quota, when it is exhausted, then new runs are refused with `QuotaExceeded` unless an admin overrides.
- **AC3** — Given a period, when usage is requested, then totals reconcile with run records and can be exported.
- **DoD+** — Backlog (S7). Provider integration out of scope.

#### E5-S9 — License management
`Should` · `M (5d)` · deps: E5-S1
- **AC1** — Given a tenant, when a license is issued, then a signed lease is produced with tier, seats/instances, expiry, and a revocation id.
- **AC2** — Given a heartbeat, when a lease is near expiry, then it is renewed; given a revoked lease, then the cell stops accepting new runs within one heartbeat.
- **AC3** — Given an offline cell, when the lease is within grace, then it continues and records `grace_mode`; after grace it blocks new runs.
- **DoD+** — Backlog (S7). Reuses `packages/license-client` semantics; ADR-006.

#### E5-S10 — Signed image catalog and update distribution
`Should` · `M (4d)` · deps: E5-S1
- **AC1** — Given a released cell image, when published, then the CP records digest, SBOM, signature, and channel (stable/canary).
- **AC2** — Given a customer deployment, when it checks for updates, then it receives only signed versions and verifies the signature before pulling.
- **AC3** — Given a rollback, when triggered, then the previous digest is restored and the event audited.
- **DoD+** — Backlog (S8).

**Epic DoD (E5)**

- A user can authenticate, create a run, watch it complete, and retrieve evidence metadata — all tenant-scoped.
- Cross-tenant access tests fail closed.
- The CP's database contains no code, no evidence bytes, and no LLM/repo credentials.

---

### E6. Control Plane — Web UI

**Goal.** A trustworthy operator console. The UI's job is to make a run *explainable* in under a minute: why these tests, what happened, what proves it, and what policy allowed it.

**Stories**

#### E6-S1 — App shell, auth, and data layer
`Must` · `M (4d)` · deps: E5-S2
- **AC1** — Given an unauthenticated visitor, when they open the app, then they are redirected to OIDC and returned to the requested route after login.
- **AC2** — Given a session, when the token nears expiry, then TanStack Query pauses/refreshes without losing the current view; logout clears all cached tenant data.
- **AC3** — Given a role, when the nav renders, then admin-only destinations are hidden and direct navigation is still blocked server-side.
- **DoD+** — Accessible shell (keyboard nav, landmarks, contrast); Storybook or component harness for core primitives.

#### E6-S2 — Dashboard and runs list
`Must` · `M (4d)` · deps: E6-S1, E5-S3
- **AC1** — Given a tenant, when the dashboard loads, then it shows run counts by status, p50/p95 duration, gate pass rate, and coverage completeness for the selected window.
- **AC2** — Given the runs list, when filtered by status/scope/date/PR, then results paginate and deep-link to a shareable URL.
- **AC3** — Given an empty state, when there are no runs, then it explains how to start one rather than showing a blank table.
- **DoD+** — Skeleton/loading and error states; no layout shift on refresh.

#### E6-S3 — Run detail with live SSE
`Must` · `M (5d)` · deps: E6-S2, E5-S5
- **AC1** — Given a running run, when the detail page is open, then phases, agent steps, tool calls, and verdicts append live; reconnect resumes from the last event id.
- **AC2** — Given a step, when expanded, then its citations link to the offending symbol/file and the evidence for that step is one click away.
- **AC3** — Given a completed run, when viewing the summary, then the gate decision, escalation reason, and coverage gaps are visible without reading logs.
- **DoD+** — SSE degradation: polling fallback with a visible staleness indicator.

#### E6-S4 — Evidence viewer
`Must` · `M (5d)` · deps: E5-S6
- **AC1** — Given a failed step, when the evidence viewer opens, then screenshots, video, trace download, network log, and console log are available and labelled by content type.
- **AC2** — Given an expired presigned URL, when the viewer requests it, then the CP re-mints transparently and playback continues.
- **AC3** — Given a large trace/video, when loading, then the UI streams/downloads lazily and never blocks the run detail page.
- **DoD+** — No evidence bytes proxied through the CP; no credentials in the browser beyond the presigned URL.

#### E6-S5 — Policy editor
`Must` · `M (4d)` · deps: E6-S1, E5-S3, E1-S7
- **AC1** — Given a project, when an operator edits policy (egress allowlist, budgets, redaction rules, escalation, `allow_test_commits`), then the change is validated, diffed, and saved as a new version.
- **AC2** — Given an invalid policy (e.g., `0.0.0.0/0` egress, negative budget), when saving, then it is rejected with the specific rule violated.
- **AC3** — Given a running run, when policy is reloaded, then the UI shows which version applies and when it took effect.
- **DoD+** — Dangerous changes require an explicit confirmation; all versions auditable.

#### E6-S6 — Cell registry view
`Could` · `S (3d)` · deps: E5-S4
- **AC1** — Given a tenant, when the cells page loads, then it shows deployment, region, image digest, capability set, and last-seen.
- **AC2** — Given an unhealthy cell, when it is displayed, then stale/failed states are distinguishable and no run can be dispatched to it.
- **AC3** — Given the view, when inspected, then it exposes no secrets or client identifiers.
- **DoD+** — Backlog (S7).

#### E6-S7 — Billing and usage view
`Should` · `M (5d)` · deps: E5-S8
- **AC1** — Given a period, when the usage page loads, then units, quota, and projected overage are shown per project.
- **AC2** — Given an admin, when exporting, then a CSV matching the API totals downloads.
- **AC3** — Given quota exhaustion, when a user tries to start a run, then the UI explains the limit and links to the admin.
- **DoD+** — Backlog (S7).

**Epic DoD (E6)**

- A stakeholder can go from login → dashboard → run detail → evidence → policy change without touching a terminal.
- Every page has loading, empty, and error states.
- Playwright E2E covers the golden path in CI against the Compose stack.

---

### E7. Security & Compliance

**Goal.** Turn the brief's constraints into executable tests, not prose. The gate at S6 is objective: if the architecture tests and leak suites pass, the boundary holds; if they don't, we don't ship the demo.

**Stories**

#### E7-S1 — No-UI-in-cell architecture test and route audit
`Must` · `S (2d)` · deps: E0-S7, E1-S1
- **AC1** — Given the cell's dependency manifests and filesystem, when the test runs, then any of `express`+`static`, `next`, `nuxt`, `vite`, `react`, `vue`, `angular`, `svelte`, `tailwind`, `jinja2`, `django.template`, `public/index.html`, or a session middleware fails the build.
- **AC2** — Given the cell's router, when enumerated, then only the six contract routes exist; any additional route fails unless added to an explicit, reviewed allowlist.
- **AC3** — Given a false positive, when a rule is refined, then the rule change requires an ADR update and a second reviewer.
- **DoD+** — Runs in CI and as a pre-commit hook.

#### E7-S2 — Egress proxy and redaction hardening
`Must` · `M (4d)` · deps: E1-S7
- **AC1** — Given a run, when egress is attempted, then it passes through the proxy which enforces the allowlist at L3/L7 and logs destination + decision (never payloads).
- **AC2** — Given an outbound request, when it contains a credential header, then it is stripped unless the destination rule explicitly permits it.
- **AC3** — Given a denial, when it occurs, then the run receives a typed error and the host is reported without retry storms.
- **DoD+** — Proxy is the only route out (tested by attempting direct egress); allowlist changes require an ADR update.

#### E7-S3 — mTLS CA and rotation
`Must` · `S (3d)` · deps: E0-S8, E5-S1
- **AC1** — Given a cell enrollment, when it is issued a certificate, then the identity binds to the cell deployment id and the cert TTL is ≤ 24 h.
- **AC2** — Given cert rotation, when a new cert is issued, then both CP and cell accept it without downtime and old certs are rejected after a short overlap.
- **AC3** — Given an expired or revoked cert, when the cell connects, then the handshake fails and the event is audited.
- **DoD+** — CA keys never leave the broker/KMS; local dev uses a generated dev CA that is clearly non-production.

#### E7-S4 — Hash-chained audit logging
`Must` · `S (2d)` · deps: E1-S7, E5-S7
- **AC1** — Given any mutating action or secret fetch, when it occurs, then an audit record with actor, action, target, and outcome is appended.
- **AC2** — Given records, when one is modified, then chain verification fails at that point and the failure is surfaced.
- **AC3** — Given redaction, when a payload contains a secret-shaped value, then it is redacted before the audit write.
- **DoD+** — Cell-side and CP-side chains are both verifiable; retention documented.

#### E7-S5 — Threat model and pen-test readiness
`Should` · `M (4d)` · deps: E7-S1..S4
- **AC1** — Given the architecture, when the threat model is written, then STRIDE coverage exists for CP, cell, channel, broker, evidence, and AUT boundaries.
- **AC2** — Given the model, when reviewed, then each high-severity threat maps to a test or a documented accepted risk.
- **AC3** — Given a pen-test scope, when handed over, then it includes network diagrams, roles, and out-of-scope items.
- **DoD+** — Backlog (S7).

#### E7-S6 — Secret-leak regression suite
`Should` · `S (3d)` · deps: E1-S8
- **AC1** — Given seeded sentinel secrets, when a full run executes, then logs, events, evidence, and workspace are scanned and zero matches are found.
- **AC2** — Given a redaction misconfiguration, when the suite runs, then it fails with the sink and pattern that leaked.
- **AC3** — Given new evidence types, when added, then they are automatically included in the scan.
- **DoD+** — Backlog (S7) as a nightly job; the per-run subset ships in S2 via E1-S8.

**Epic DoD (E7)**

- Architecture test blocks a UI import in the cell (demonstrated in a PR).
- Egress deny-by-default proven by a direct-egress attempt.
- Secret sentinel scan is clean across all sinks.
- mTLS handshake rejects expired/revoked certs.

---

### E8. BYOC Provisioning (post-S6)

**Goal.** One `terraform apply` + one Helm install gives a customer a working cell deployment in their VPC, enrolled to the CP, receiving signed updates.

**Stories**

#### E8-S1 — Terraform module (AWS)
`Should` · `L (8d)` · deps: E5-S5
- **AC1** — Given an AWS account, when the module applies, then VPC subnets, IAM roles (IRSA), KMS, S3 (evidence), ECR pull, and an EKS-ready node group are created with least-privilege policies.
- **AC2** — Given the outputs, when consumed by Helm, then no long-lived credentials are required and no secret is written to Terraform state.
- **AC3** — Given `terraform destroy`, when it completes, then no billable resources remain (except retained evidence, per flags).
- **DoD+** — Plan-only CI job with a policy check (no `*` actions/`0.0.0.0/0`).

#### E8-S2 — Golden cell image and signing
`Should` · `M (5d)` · deps: E1-S1
- **AC1** — Given a release, when the image is built, then it is reproducible by digest, signed (cosign/Sigstore), and accompanied by SBOM + provenance.
- **AC2** — Given an unsigned image, when admission control sees it, then it is rejected.
- **AC3** — Given a CVE in the base image, when the rebuild runs, then a patch release is produced and tracked.
- **DoD+** — Backlog (S8).

#### E8-S3 — Cell registry bootstrap and enrollment
`Should` · `S (3d)` · deps: E5-S4, E7-S3
- **AC1** — Given a deployment, when it first starts, then it bootstraps identity via a one-time token and enrolls with the CP.
- **AC2** — Given a re-enrollment, when the token is reused, then it is rejected and the event audited.
- **AC3** — Given a decommission, when a cell is removed, then its cert and registry entry are revoked.
- **DoD+** — Backlog (S8).

#### E8-S4 — Helm charts
`Should` · `M (6d)` · deps: E8-S1
- **AC1** — Given a cluster, when the chart is installed, then the CP (or a cell deployment) comes up with probes, PDBs, resource limits, and network policies.
- **AC2** — Given values overrides, when installed, then images are pinned by digest and secrets come from the broker/CSI driver.
- **AC3** — Given an upgrade, when it rolls, then in-flight runs are drained and no run is orphaned.
- **DoD+** — Backlog (S9).

#### E8-S5 — Signed update distribution and rollback
`Should` · `M (5d)` · deps: E5-S10
- **AC1** — Given a new signed image, when a customer opts into canary, then a bounded percentage of runs use it and metrics are compared.
- **AC2** — Given a regression, when rollback is triggered, then the previous digest is restored within one deployment window.
- **AC3** — Given an update, when the signature is invalid, then the deployment refuses and alerts.
- **DoD+** — Backlog (S9).

---

### E9. Observability & Ops (post-S6)

**Goal.** Every run is explainable after the fact and every failure is actionable before a customer calls.

**Stories**

#### E9-S1 — OTel instrumentation across cell, CP, and web
`Should` · `M (6d)` · deps: E1-S4, E5-S3
- **AC1** — Given a run, when traced, then a single trace id spans dispatch → phases → tool calls → coverage write → report.
- **AC2** — Given a span, when inspected, then it carries run id, tenant, cell id, and phase but no secrets or prompt content.
- **AC3** — Given log correlation, when a log is emitted, then it includes trace/span ids and the tenant/run.
- **DoD+** — Sampling policy documented; overhead < 3%.

#### E9-S2 — Grafana dashboards
`Should` · `M (4d)` · deps: E9-S1
- **AC1** — Given metrics, when the dashboard loads, then run throughput, p50/p95 duration, gate pass rate, agent token spend, and coverage completeness are visible.
- **AC2** — Given a tenant filter, when applied, then all panels scope correctly.
- **AC3** — Given a missing series, when the dashboard loads, then it shows "no data" explicitly rather than a misleading zero.
- **DoD+** — Backlog (S9).

#### E9-S3 — Alerts and SLOs
`Should` · `S (3d)` · deps: E9-S2
- **AC1** — Given SLOs, when error budget burn exceeds the threshold, then an alert fires with a runbook link.
- **AC2** — Given cell channel disconnects, run failures, or stuck runs, when they exceed thresholds, then alerts distinguish them.
- **AC3** — Given an alert, when acknowledged, then it links to the affected runs.
- **DoD+** — Backlog (S9).

#### E9-S4 — Runbooks
`Should` · `M (5d)` · deps: E9-S1
- **AC1** — Given an alert, when followed, then the runbook resolves or escalates with concrete commands.
- **AC2** — Given a new failure mode, when added, then it gets a runbook before release.
- **AC3** — Given a dry run, when executed on staging, then the steps work as written.
- **DoD+** — Backlog (S9).

#### E9-S5 — Sentry integration
`Should` · `S (2d)` · deps: E9-S1
- **AC1** — Given an exception, when captured, then it is grouped with release and run id, and PII is scrubbed.
- **AC2** — Given a frontend error, when it occurs, then the release maps to source maps.
- **AC3** — Given a noisy error class, when it exceeds the budget, then it is sampled/muted with a documented reason.
- **DoD+** — Backlog (S9).

---

### E10. Documentation & Handover (post-S6)

**Goal.** A new engineer or customer SRE can operate the system without a call.

**Stories**

#### E10-S1 — README and architecture docs
`Should` · `S (2d)` · deps: E6-S6
- **AC1** — Given the repo, when reading the README, then setup, run, test, and troubleshooting are covered in under 15 minutes.
- **AC2** — Given the architecture doc, when read, then all trust boundaries and data flows match the ADRs.
- **AC3** — Given a doc change, when merged, then links are checked in CI.
- **DoD+** — Backlog (S10).

#### E10-S2 — API reference
`Should` · `S (3d)` · deps: E5-S6
- **AC1** — Given the CP and cell APIs, when published, then OpenAPI is generated from code and versioned.
- **AC2** — Given an endpoint change, when merged, then the spec changes in the same PR.
- **AC3** — Given a breaking change, when released, then a deprecation notice and migration note exist.
- **DoD+** — Backlog (S10).

#### E10-S3 — Demo scripts
`Should` · `S (2d)` · deps: E6-S4
- **AC1** — Given a demo, when following `docs/demos/*.md`, then it runs in ≤5 commands and produces a run with evidence.
- **AC2** — Given a fresh environment, when the script runs, then it seeds only fixture data.
- **AC3** — Given a failed step, when it occurs, then the script fails loudly with the failing command.
- **DoD+** — Backlog (S10).

#### E10-S4 — BYOC installer guide
`Should` · `S (3d)` · deps: E8-S4
- **AC1** — Given a customer SRE, when following the guide, then they complete Terraform + Helm + enrollment with documented prerequisites.
- **AC2** — Given a failure, when it occurs, then the guide maps error codes to causes.
- **AC3** — Given a successful install, when verified, then a smoke run passes.
- **DoD+** — Backlog (S10).

#### E10-S5 — Handover and final review
`Should` · `S (3d)` · deps: E10-S1..S4
- **AC1** — Given the handover, when complete, then ownership, escalation, and on-call expectations are documented.
- **AC2** — Given the final review, when performed, then all ADRs, runbooks, and demos are current.
- **AC3** — Given open risks, when reviewed, then each has an owner and a next action.
- **DoD+** — Backlog (S10).

---

## 7. Sprint plan

**Cadence:** 2 weeks. Each sprint starts with `docs/sprints/sprint-N-plan.md` (goal, stories, capacity, risks) and ends with `docs/sprints/sprint-N.md` (committed vs delivered, demo, metrics, plan changes, risks hit). No sprint starts without the plan file; no review is accepted without the metrics.

**Capacity:** 34 dev-days committed (S1–S5), 36–40 in S6 (frontend engineer joins). Buffer is not listed as stories; it is reserved for DoD work and CI drift.

### Sprint 1 — Foundation + cell skeleton

**Goal.** One command brings up the local stack; the cell container starts hardened, answers `/v1/health`, and CI rejects any UI dependency.

| Story | Est |
| --- | --- |
| E0-S1 Monorepo scaffolding | 4 |
| E0-S2 Compose stack | 4 |
| E0-S3 CI pipeline | 3 |
| E0-S4 Standards + ADR workflow | 2 |
| E0-S5 Shared contracts | 3 |
| E0-S6 Fixtures (AUT + repo) | 3 |
| E0-S7 Architecture-test harness | 2 |
| E0-S8 Local secrets | 2 |
| E1-S1 Cell image | 5 |
| E1-S2 Health/readiness | 2 |
| E7-S1 No-UI-in-cell test | 2 |
| **Total** | **32 / 34** |

**Demoable increment (5 lines)**
```bash
make bootstrap && make up
make smoke            # creates a stub run, prints phase transitions
curl -s localhost:8000/v1/health | jq '{ready,aut_status,graph_status}'
make arch-test        # green
git commit --allow-empty -m "test: add express.static to cell"  # CI goes red
```
**Risks / mitigations**
- *Dev-environment drift* (Node 22 on host, 20 in image) → pin with `.nvmrc`/`engines`, `make doctor` fails fast.
- *Compose port conflicts with the existing product stack* → factory stack uses a distinct project name and non-overlapping ports.
- *Fixture scope creep* → freeze fixtures at the three-route contract in E0-S6; extensions require a story.

**Exit criteria:** `make up` + `make smoke` green from a clean clone; architecture test demonstrably blocks a UI import; CI runs < 12 min.

---

### Sprint 2 — Orchestrator + internal API

**Goal.** A run can be created, observed over SSE, cancelled, and driven through all seven phases with stubs under a real policy and real secret handling.

| Story | Est |
| --- | --- |
| E1-S3 Internal API + run-scoped tokens | 4 |
| E1-S4 Orchestrator state machine | 8 |
| E1-S5 Run lifecycle API | 4 |
| E1-S6 SSE event stream | 4 |
| E1-S7 Policy engine | 8 |
| E1-S8 Secrets broker client | 4 |
| **Total** | **32 / 34** |

**Demoable increment (5 lines)**
```bash
curl -s -X POST localhost:8000/v1/runs -H "Authorization: Bearer $RUN_TOKEN" \
  -d '{"repo":"fixture","commit":"abc1234","scope":"full","policy":{...}}'
curl -Ns localhost:8000/v1/runs/$ID/events | head -40   # phases + steps
curl -s -X POST localhost:8000/v1/runs/$ID/cancel
docker kill cell && docker start cell                    # resumes, no duplicate work
grep -R "sk-\|Bearer " /workspace /tmp/cell-logs          # no matches
```
**Risks / mitigations**
- *State-machine over-engineering* → keep transitions data-driven; no per-phase subclassing until a phase needs it.
- *SSE ordering under concurrency* → single writer per run, sequence ids, contract tests.
- *Policy engine scope* → allowlist evaluation only; no general-purpose policy language in v1.

**Exit criteria:** kill/restart resumes idempotently; cancel < 5 s; route audit shows six endpoints; secret sentinel scan clean.

---

### Sprint 3 — Agent runtime + MCP

**Goal.** Planner and Executor drive a real browser against the sample AUT through MCP, with citation enforcement and the a11y stop rule proven by a failing fixture element.

| Story | Est |
| --- | --- |
| E2-S1 Provider abstraction | 4 |
| E2-S2 Agent loop + citation enforcement | 8 |
| E2-S3 MCP layer + role allowlists | 4 |
| E2-S4 Playwright MCP | 5 |
| E2-S7 Context retrieval client | 4 |
| E2-S8 Planner | 3 |
| E2-S11 Executor | 4 |
| **Total** | **32 / 34** |

**Demoable increment (5 lines)**
```bash
make up && export ANTHROPIC_API_KEY=$(vault kv get -field=key secret/llm)
curl -s -X POST localhost:8000/v1/runs -d '{"goal":"verify checkout","scope":"impacted",...}'
curl -Ns localhost:8000/v1/runs/$ID/events | jq -r '.step.phase,.step.citations,.step.verdict'
# screenshot of the completed step appears in MinIO under runs/$ID/
# run on the fixture's unlabeled button → verdict=testability_defect, no CSS fallback
```
**Risks / mitigations**
- *Model non-determinism makes demos flaky* → record/replay with `FakeProvider` for CI; live demos use a pinned model + temperature 0.
- *Prompt/tool sprawl* → role allowlist is declarative; adding a tool requires a policy entry and a test.
- *A11y rule blocks legitimate runs* → defect report must include the element snapshot and a suggested human action; the run continues to the next test.
- *Compose-hosted AUT is not the real deployment* → explicitly a dev-only path (E3-S5); S4 replaces it.

**Exit criteria:** two consecutive live runs produce identical verdicts for the fixture; every action has a resolvable citation; the a11y negative test fails the run with a defect, not a selector guess.

---

### Sprint 4 — AUT deployment + coverage

**Goal.** The cell builds the fixture AUT as a separate workload, runs it, and writes stitched FE+BE coverage edges with honest granularity.

| Story | Est |
| --- | --- |
| E3-S1 Instrumented build Job | 3 |
| E3-S2 Adjacent deploy + teardown | 5 |
| E3-S3 Readiness, migrations, seed | 3 |
| E4-S1 FE V8 coverage + source maps | 8 |
| E4-S2 Backend sidecar + `X-Test-Id` | 8 |
| E4-S3 Stitcher: granularity, mocks, escalation | 5 |
| **Total** | **32 / 34** |

**Demoable increment (5 lines)**
```bash
curl -s -X POST localhost:8000/v1/runs -d '{"repo":"fixture","commit":"abc1234","scope":"full"}'
kubectl get pods -n tr-aut-$RUN_ID            # separate workload, ready
docker exec neo4j cypher-shell -c \
  "MATCH (t:TestSymbol)-[e:EVIDENCE]->(s:Symbol) RETURN e.granularity, count(*)"
# expect: line (FE), endpoint (handler), inferred (call graph)
kubectl get all -n tr-aut-$ID                 # empty after teardown
```
**Risks / mitigations**
- **Highest-risk sprint.** Build privilege, cluster permissions, and source-map accuracy all land at once.
- *Build requires privileged mode* → rootless build Job (ADR-001); if the cluster forbids it, fall back to the prebuilt-image mode (E3-S7) and slip the generic builder.
- *Coverage mis-attribution* → SHA guard (E4-S3 AC5), unmapped-byte metric, endpoint coverage % as a gate input.
- *Teardown leaks* → orphan reaper test in CI; a deliberately killed run must leave nothing.
- *Slip candidate:* E3-S3 seed data (the fixture needs none) → move to S5 if the sprint is tight.

**Exit criteria:** a run produces all three granularities + a `MOCKED` edge; inferred-only escalation is demonstrated; no resources remain after teardown.

---

### Sprint 5 — Control plane backend + auth

**Goal.** Users log in, dispatch runs to a cell in a private network, and see history and evidence metadata, all tenant-scoped and audited.

| Story | Est |
| --- | --- |
| E5-S1 CP scaffold + schema | 4 |
| E5-S2 OIDC + RBAC | 5 |
| E5-S3 Runs API + history + policy endpoints | 5 |
| E5-S5 Outbound control channel + dispatch | 8 |
| E4-S4 Evidence collector | 4 |
| E7-S3 mTLS CA + rotation | 3 |
| **Total** | **29 / 34** |

**Demoable increment (5 lines)**
```bash
open http://localhost:3000            # Keycloak login as operator
curl -s localhost:3001/v1/runs | jq '.[] | {id,status,phase}'
curl -s -X POST localhost:3001/v1/runs -d '{"project":1,"commit":"abc1234"}'
curl -Ns localhost:3001/v1/runs/$ID/events | head -20
curl -s localhost:3001/v1/runs/$ID/evidence | jq '.[0] | {key,sha256,url_ttl}'
```
**Risks / mitigations**
- *ADR-003 not approved* → this sprint is blocked; the fallback (queue-only dispatch) costs ~2 extra days and delays live SSE.
- *TS backend pair overload* (22 d across 2 devs) → cell engineers take E4-S4 and E7-S3; the full-stack dev pairs on E5-S5.
- *Cross-tenant leakage* → repository-layer scoping with a failing-closed test on every endpoint.

**Exit criteria:** outbound-only dispatch works with no inbound firewall rule; RBAC matrix passes; evidence URL re-mint works; audit rows verify.

---

### Sprint 6 — Control plane UI + security gate

**Goal.** A stakeholder runs the whole loop from the UI and the security gate passes objectively.

| Story | Est |
| --- | --- |
| E6-S1 App shell + auth | 4 |
| E6-S2 Dashboard + runs list | 4 |
| E6-S3 Run detail + live SSE | 5 |
| E6-S4 Evidence viewer | 5 |
| E6-S5 Policy editor | 4 |
| E5-S4 Cell registry | 4 |
| E5-S6 Evidence index + URL broker | 4 |
| E7-S2 Egress proxy + redaction | 4 |
| E7-S4 Audit logging | 2 |
| **Total** | **36 / 36–40** |

**Demoable increment (5 lines)**
```bash
make up && make seed
open http://localhost:3000                    # login as operator
# dashboard → "Run on PR #42" → watch phases/agents live
# click failed step → screenshot + trace + network log
# edit policy (allow_test_commits=true) → version diff shown → run uses v2
```
**Risks / mitigations**
- *UI scope creep* → five screens only; no settings pages beyond policy; no dark-mode/theme work.
- *Evidence viewer blocked by Q3* → cell-minted 15-min URLs are enough for the demo; re-mint is the Must, customer broker is post-S6.
- *Security gate fails late* → E7-S2/S4 are scheduled, not "if time permits"; if they slip, the demo is declared not-shippable.

**Exit criteria (also the Phase-2 gate):** UI→cell→AUT→evidence loop green; architecture test, egress denial, secret sentinel, and mTLS rejection all pass in CI; no client code or LLM keys in the CP.

---

### Post-S6 roadmap (indicative)

| Sprint | Focus | Stories |
| --- | --- | --- |
| S7 | Remaining agent roles + commercial plumbing | E2-S5, E2-S6, E2-S9, E2-S10, E4-S5, E4-S6, E5-S8, E5-S9, E6-S6, E6-S7, E3-S4, E3-S7 |
| S8 | Diagnostics + BYOC | E2-S12, E2-S13, E3-S5, E3-S6, E5-S10, E8-S1, E8-S2, E8-S3, E7-S5 |
| S9 | Ops + packaging | E8-S4, E8-S5, E9-S1..S5, E7-S6 |
| S10 | Handover + GA | E10-S1..S5, hardening buffer |

**Scope reality check:** 12 weeks delivers the demoable vertical slice, not GA. The remaining ~150 ideal days (S7–S10) cover four agent roles, licensing/billing surfaces, BYOC Terraform/Helm, observability, and handover. Anyone promising GA at S6 is promising the demo, not the product.

---

## 8. Sprint dependency graph (critical path)

```
E0-S1 ─┬─ E0-S2 ─┬─ E0-S8 ──────────────┬─ E1-S8 ─┐
       │         └─ E1-S1 ─ E1-S2 ─ E1-S4 ─ E1-S5 ─┼─ E5-S5 ─ E6-S3
       ├─ E0-S3 ─ E0-S7 ─ E7-S1                   │
       ├─ E0-S5 ─ E2-S1 ─ E2-S2 ─ E2-S3 ─ E2-S4 ──┼─ E2-S11
       └─ E0-S6 ─ E3-S1 ─ E3-S2 ─┬─ E4-S1 ─ E4-S3 │
                                 ├─ E4-S2 ─────────┘
                                 └─ E4-S4 ─ E5-S6 ─ E6-S4
E5-S1 ─ E5-S2 ─ E5-S3 ─ E6-S1 ─ E6-S2 ─ E6-S5
E7-S3 ─ E5-S5
```

**Critical path:** E0 → E1-S1/S2 → E1-S4 → E1-S5/E1-S6 → E3-S2 → E4-S2 → E4-S3 → E5-S5 → E6-S3/S4. Any slip on E1-S4, E3-S2, or E4-S2 moves the S6 demo.

---

## 9. ADRs

> On approval these move to `docs/adr/NNN-*.md` verbatim.

### ADR-001 — The cell is a container; the AUT is a separate workload

**Context**
The cell must run the client's application to exercise it, but it must never run client code in its own namespace, and it must satisfy: read-only root filesystem, non-root user, `CAP_SYS_ADMIN` dropped, no privileged mode. Building an image inside the cell implies Docker-in-Docker or BuildKit, which normally requires privileged mode, a writable rootfs, and mount capabilities. Those requirements directly contradict the cell's hardening constraints. We also need reproducible builds tied to a commit SHA so coverage can be trusted (E4-S3).

**Decision**
1. The cell is an ephemeral container/Job. It never executes client code.
2. The AUT is deployed as a **separate workload** (Deployment/Job + Service) in the same VPC, from a **pinned image digest**.
3. The build is a **separate build Job** (kaniko or rootless BuildKit) created by the cell through a tightly scoped ServiceAccount in the customer cluster. The cell orchestrates; it does not build.
4. Dev-only exception: `infra/compose` uses the host Docker socket for the builder (never for the cell). This is documented as non-production.
5. Optional customer mode: the customer's CI builds the image and passes the digest; the cell only deploys. This is the recommended mode for regulated clients.

**Consequences**
- (+) Isolation is real: a compromised cell has no client code and no build privileges.
- (+) Digests make coverage→commit verification tractable.
- (+) The same model works for SaaS and BYOC.
- (−) More moving parts: build Job, registry auth, scoped RBAC, image pull latency.
- (−) Cold-start time increases (build + pull + readiness).
- (−) The cell needs cluster API permissions; those must be namespaced and audited.

**Alternatives considered**
- **Docker-in-Docker in the cell** — rejected: privileged, `CAP_SYS_ADMIN`, writable rootfs, and it puts client code inside the cell's trust boundary.
- **Build in the control plane** — rejected: violates "no client code in the CP".
- **Prebuilt-only (no builder)** — viable for v1 and kept as a supported mode, but it pushes work onto every customer's CI and makes the demo dependent on external pipelines.

---

### ADR-002 — No UI in the cell, enforced by an architecture test

**Context**
A UI in the cell would add static assets, sessions, cookies, CSRF, XSS, and a browser-facing attack surface to a component that runs with credentials and client code access in some modes. The brief forbids "a user-facing HTTP server, static assets, or session storage". Prose does not prevent regressions; a test does.

**Decision**
- The cell exposes JSON + SSE only, under `/v1/*`, and has no static/template/session middleware.
- `E7-S1` enforces three checks in CI and pre-commit:
  1. **Dependency denylist** for both `pyproject.toml`/imports and `package.json`: `next`, `nuxt`, `vite`, `react`, `react-dom`, `vue`, `@angular/*`, `svelte`, `tailwindcss`, `express` + `static`, `jinja2`, `django.template`, `flask` templates, session middleware.
  2. **Filesystem denylist**: `public/`, `static/`, `templates/`, `*.html` (except test fixtures under `tests/`).
  3. **Route audit**: the router must expose exactly the six contract routes; additions require an explicit allowlist edit reviewed by a second engineer.
- The UI lives only in `apps/web`, which depends on the CP API, never on a cell.

**Consequences**
- (+) A whole vulnerability class is removed by construction.
- (+) The cell image stays small and fast to start.
- (−) Debugging requires curl/SSE tooling; we must ship CLI recipes in runbooks.
- (−) Denylists can produce false positives (e.g., a transitive `tailwind` in a test tool); the allowlist escape hatch is narrow and reviewed.

**Alternatives considered**
- Read-only debug UI behind an internal flag — rejected: still ships static assets and sessions; violates the constraint.
- Separate debug sidecar — rejected: doubles the surface and the image.

---

### ADR-003 — mTLS + run-scoped tokens, with the cell initiating the connection

**Context**
The brief states the CP talks to cells "only via their internal API over mTLS". Read literally, that requires inbound reachability from the CP into the cell. In BYOC the cell runs in the customer's VPC; customers will not expose public ingress or a NAT pinhole to a vendor, and requiring it would fail most security reviews. The CP must also never hold the client's LLM/repo credentials, and every endpoint must be authorized by a short-lived run-scoped token.

**Decision (recommended — needs approval)**
1. **Connectivity:** the cell **initiates** an outbound mTLS connection to the CP and maintains a multiplexed control channel (dispatch, cancellation, evidence URL re-mint, policy reload). The CP never dials into the customer VPC. Direct CP→cell mTLS remains allowed only for SaaS or explicitly peered deployments.
2. **Transport identity:** certificates issued by an internal CA, bound to the cell deployment id, TTL ≤ 24 h, rotated with overlap; revocation checked at handshake.
3. **Authorization:** the CP issues a **run-scoped JWT** (`aud=cell_id`, `sub=run_id`, `scope=run`, `exp` ≤ 2× the run timeout, `jti` single-use for mutating calls). The cell verifies locally — no callback to the CP per request — and binds the token to the mTLS identity.
4. **Resilience:** the cell buffers events during a CP outage (bounded, with explicit loss markers) and flushes on reconnect. Dispatch is idempotent by run id.

**Consequences**
- (+) Works through NAT and corporate firewalls; nothing inbound is exposed.
- (+) Revocation and attribution are per-deployment and per-run.
- (−) The CP must own channel lifecycle: reconnect, backpressure, ordering, at-most-once dispatch.
- (−) "CP talks to the cell API" becomes "CP talks over the channel" — an explicit deviation from the literal brief.
- (−) Live SSE in the UI is relayed through the CP, adding a hop.

**Alternatives considered**
- **Inbound mTLS only** — rejected for BYOC (security review failure); kept for SaaS.
- **WireGuard/Tailscale overlay** — rejected: extra operational burden on customers, conflicts with minimum-footprint BYOC.
- **Queue-only (SQS/NATS) dispatch + polling** — simpler and viable; loses low-latency bidirectional calls (cancel, URL re-mint). Kept as the fallback if Q1 is declined; costs ~2 days in S5 and degrades the live demo.

---

### ADR-004 — Coverage stitching across the frontend/backend boundary

**Context**
An e2e test crosses a browser and a server. Frontend coverage alone misses backend handlers; backend coverage alone cannot tell which test caused a call. The brief requires: V8 + source maps, backend sidecar with `X-Test-Id`, network correlation path → route → handler → static call graph, mock boundaries as negative edges, `granularity ∈ {line, endpoint, inferred}`, and escalation when a changed symbol has only inferred coverage.

**Decision**
1. **Frontend:** Playwright `page.coverage.startJSCoverage/stopJSCoverage` per test → V8 ranges → source maps → original TS positions → AST symbol attribution → `granularity=line`.
2. **Backend:** sidecar in the AUT (Node: V8/nyc contexts; Python: `coverage.py` dynamic contexts) keyed by the `X-Test-Id` header injected by the runner → per-test line sets → AST symbol attribution → `granularity=line`.
3. **Correlation:** Playwright records request/response; the stitcher resolves `method + path` → route using a framework adapter's route table (Express/Fastify/Nest/FastAPI/Flask/Django), links the handler as `granularity=endpoint`, then traverses the static call graph and links descendants as `granularity=inferred`.
4. **Mocks:** every intercepted route produces a negative edge (`MOCKED`) and **stops traversal**; no downstream coverage is claimed.
5. **Confidence:** reuse the shipped formula (line ratio; `inferred` weight 0.5). An endpoint hit is 1.0 for the handler. No new ad-hoc scores per language.
6. **Trust:** edges are written only when the AUT image digest corresponds to the requested commit SHA (`CoverageShaMismatch` otherwise).
7. **Escalation:** if a changed symbol has only `inferred` coverage, selection broadens (endpoint → file → full suite) per policy and records `escalated_from=inferred`.
8. **Physical schema:** the existing `EVIDENCE` relationship carries a new `granularity` property. The brief's "COVERS" is the logical contract; we do not rename the proven edge type (ADR-007).

**Consequences**
- (+) Explainable, cross-boundary evidence with an honest confidence gradient.
- (+) Mock boundaries are explicit rather than silent gaps.
- (−) A route-table adapter per framework; drift breaks attribution (mitigated by conformance tests and SHA-keyed caching).
- (−) Source-map remapping costs time and can be wrong; unmapped bytes are reported, never guessed.
- (−) `X-Test-Id` must be propagated by every runner; non-instrumented calls land in `no_test_id` (visible, not merged).

**Alternatives considered**
- Browser-only coverage — rejected: misses backend impact, the main source of false negatives.
- APM/tracing-based correlation — promising for later, but adds a dependency and does not give per-test line evidence today.
- LLM-inferred mapping — rejected: non-deterministic and unexplainable, contradicting the product promise.

---

### ADR-005 — Secrets broker: portable interface, Vault default, cloud-native supported

**Context**
The cell needs an LLM key, a repo token, DB credentials, and evidence-bucket credentials at runtime. The CP must never hold them. BYOC deployments are in customer clouds with different secret managers; SaaS runs on AWS. Secrets must never be baked into images or written to disk, and every fetch must be auditable.

**Decision**
1. A `SecretProvider` interface in the cell: `get(ref, ttl)`, with `VaultProvider` (KV v2 + K8s auth), `AwsSecretsManagerProvider` (IRSA), and `FakeProvider` for tests.
2. **Vault is the default** and the reference implementation, because it works across clouds and gives dynamic, TTL-bound credentials and audit devices.
3. AWS Secrets Manager is a first-class adapter for customers who mandate cloud-native.
4. The CP stores only **secret references** (Vault path / ARN) in policy; values are fetched by the cell at run time, held in memory, cleared at teardown, and never logged, written to the workspace, or uploaded as evidence.
5. Secret fetches are audit events (`ref`, `ttl`, `outcome`) — never the value.

**Consequences**
- (+) No static secrets in images or config; revocation and TTL are real.
- (+) One interface, two backends; BYOC customers keep their own vault.
- (−) The broker becomes a run dependency; unavailability fails fast (`SecretUnavailable`).
- (−) Vault is operational overhead for small BYOC customers; the AWS adapter mitigates.
- (−) Dynamic DB creds require per-stack provisioning; v1 supports static-with-TTL fallback and documents it.

**Alternatives considered**
- Cloud-native only (Secrets Manager) — simpler on AWS, poor multi-cloud parity, and forces AWS on BYOC.
- Sealed secrets / SOPS in-cluster — rejected: static, weak rotation, no per-run scope.
- CP-held keys — rejected outright by the architecture.

---

### ADR-006 — BYOC licensing: per-deployment lease, per-instance metering

**Context**
BYOC customers want predictable cost and minimal egress; SaaS customers expect elastic, usage-based billing. Licensing must work with partially disconnected VPCs, survive CP outages, and support revocation. The brief allows "per-deployment or per-instance; configurable".

**Decision**
1. **BYOC default: per-deployment license lease.** The CP issues a signed lease (`tier`, `deployments`, `expiry`, `revocation_id`). The cell validates it locally, heartbeats every 24 h, and operates in a 7-day grace window if the CP is unreachable. Revocation takes effect within one heartbeat once connected.
2. **SaaS default: per-instance metering** (concurrent runs / run-minutes / agent tokens).
3. **Metering is always on** for both, as signed, aggregated usage batches (no prompt content, no code); it is used for reporting and quota, not as the sole enforcement for BYOC.
4. Enforcement is local-first: a cell refuses new runs when the lease is expired/revoked outside grace; it never blocks an in-flight run on a licensing check.
5. Reuse the existing `packages/license-client` fingerprint/lease semantics; add a Node verifier for the CP.

**Consequences**
- (+) Predictable BYOC pricing; SaaS remains elastic.
- (+) Works through CP outages and strict egress policies.
- (−) Clock skew and grace-window abuse are possible; mitigated by signed timestamps and anomaly reporting.
- (−) Usage disputes require reconciliation tooling (E5-S8).
- (−) Two commercial models to document and test.

**Alternatives considered**
- Pure per-instance — rejected: BYOC buyers dislike open-ended metering and its egress footprint.
- Pure per-deployment — rejected: no SaaS elasticity, poor fit for small teams.
- Hard online check per run — rejected: breaks air-gapped/regulated deployments and adds a SPOF.

---

### ADR-007 — Reuse the existing TIA engine for selection and the graph

**Context**
This repository already ships the deterministic selection engine: AST parsing, stable symbol identity, innermost-owner attribution, the `EVIDENCE` graph in Neo4j, coverage-confidence gradation (Epic 11), diff→symbol mapping, and ranked impact. The factory needs exactly those capabilities in the `Select` phase and to write coverage edges. Rebuilding them would duplicate a tested system and inevitably diverge.

**Decision**
1. The cell depends on `testsquad_core` (or a thin extracted `tia-engine` package) for: symbol resolution, `EVIDENCE` reads/writes, confidence computation, and impacted-test selection.
2. The factory adds only what is new: `granularity`, cross-boundary stitching inputs, mock negative edges, and escalation policy.
3. The CP never queries Neo4j. The graph lives with the cell (customer VPC in BYOC; per-tenant DB in SaaS).
4. If importing `testsquad_core` into the cell is impractical (dependency weight, FastAPI coupling), S2 extracts the needed modules behind a small internal interface — a refactor, not a rewrite. That extraction is an explicit S2 deliverable checkpoint.
5. The physical relationship stays `EVIDENCE`; `COVERS` remains the product-level term. Renaming would break shipped instrumentation and tests for no functional gain.

**Consequences**
- (+) Faster delivery and consistent semantics; one confidence formula.
- (+) Existing tests (symbol identity, innermost attribution, persistence contracts) keep guarding behavior.
- (−) Coupling: cell releases and engine changes must be coordinated; schema migrations affect both.
- (−) The engine's multi-tenant assumptions must be audited for cell use (project scoping, read-only graph user).

**Alternatives considered**
- Fresh selection engine in the cell — rejected: duplication, drift, and a second set of correctness bugs.
- Call `services/core` over HTTP from the cell — rejected: extra hop, and the core service is shaped as a multi-tenant SaaS API, not a cell-local library.
- Copy the relevant modules — rejected: forks diverge; import or extract instead.

---

## 10. Risks register

| ID | Risk | L | I | Mitigation | Early signal / trigger | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | **Accessibility-tree blind spots** make the agent stop frequently on real apps | H | H | A11y-first tool; stop-and-report with element snapshot; role/name fallbacks; fixture with intentional defects; defect dashboard | >5% of steps blocked on missing labels | Cell/agents |
| R2 | **Context-window exhaustion** in long E2E runs | H | H | Retrieval-ranked context, per-step token budget, plan checkpointing, summarize-and-restart, hard run budget | Runs hitting step/token cap; degraded verdict quality | Cell/agents |
| R3 | **Coverage agent incompatibility** with client stacks | H | H | Capability probe before run; adapter interface; fail to `inferred` + escalation, never false `line` | <80% endpoints mapped; unsupported stack detected | Cell/coverage |
| R4 | **Secrets leakage** via logs, evidence, or artifacts | M | Critical | Write-time redaction, sentinel scans in CI, no-value audit records, presigned URLs, gitleaks | Any sentinel match; any `Bearer` in a log | Security |
| R5 | **Cell image drift** across clients | M | H | One signed digest, SBOM, cosign verification at admission, stable/canary channels, pinned base images | Digest mismatch; admission rejection | SRE |
| R6 | **Control plane becomes a SPOF** | M | H | Stateless replicas, HA Postgres, outbox + retry, cell-side buffering, graceful degradation | CP down >5 min; dispatch backlog | CP |
| R7 | **BYOC connectivity** (NAT/firewall, inbound restrictions) | H | H | Outbound-only channel (ADR-003); reconnect/backoff; queue fallback | Cells fail to heartbeat; channel flaps | CP + SRE |
| R8 | **Build privilege conflict** (DinD vs hardened cell) | H | H | Rootless build Job; prebuilt-image mode; no privileged cell | Build Job requires privileged; policy rejection | SRE |
| R9 | **Evidence URL minting** in BYOC (CP has no client creds) | M | M | Cell-minted short TTL; re-mint over channel; customer broker post-S6 | Expired URLs in UI; re-mint failures | CP |
| R10 | **Route-table drift / mis-attribution** | M | H | Adapter conformance tests; cache keyed by build SHA; cap at `inferred`; escalation | Endpoint coverage <70%; mismatch reports | Cell/coverage |
| R11 | **Agent runaway cost** | M | H | Per-run token/step/time budgets; kill switch; cost meter; model tiering | p95 cost/run above threshold | Product + agents |
| R12 | **Flaky E2E masks real defects** | M | H | Bounded retries; flake classification (Diagnoser); quarantine with evidence; verdict taxonomy | Flake rate >5% | QA + agents |
| R13 | **Source-map inaccuracy** produces wrong symbols | M | M | Verify positions against AST; drop unmapped; report unmapped bytes; never guess | Unmapped >20% of bundle | Cell/coverage |
| R14 | **Scope pressure erodes the S6 security gate** | M | H | Gate stories scheduled, not optional; "not shippable" criterion stated; buffer reserved | E7-S2/S4 trending to slip | Eng lead |

**Assumption watch-list** (revisit each sprint review): team capacity, one repo host (GitHub), Node/Python-only coverage, 30-day evidence retention, Neo4j per tenant.

---

## 11. Definition of Done (applies to every story)

A story is done only when **all** of the following are true:

- [ ] **Code merged to main via PR with at least one self-review pass.**
- [ ] **Unit tests cover the new logic** (target ≥80% line coverage on changed files).
- [ ] **Integration test exists** (Testcontainers or Compose-based) if the story crosses a process boundary.
- [ ] **No secrets, credentials, or PII** in code, logs, or fixtures.
- [ ] **Architecture test passes** (e.g., "no UI framework in cell dependencies").
- [ ] **ADR written or updated** if a decision was made.
- [ ] **README or runbook updated** if the story changes an operational procedure.
- [ ] **Demo script (5 lines max)** shows the story working end-to-end.
- [ ] **Observability:** at least one metric, log line, or trace span added for the new path.

**How each box is enforced**

| Requirement | Mechanism |
| --- | --- |
| Self-review + merge | Branch protection, PR template checklist, no direct pushes |
| Unit coverage ≥80% | CI coverage diff gate on changed files (soft-fail below 70, hard-fail below 60) |
| Integration test | PR label `cross-boundary` requires the integration job to pass |
| No secrets/PII | gitleaks pre-commit + CI, sentinel scan, log-redaction tests |
| Architecture test | E0-S7 harness in CI; E7-S1 denylist + route audit |
| ADR | Docs lint: a decision label in the PR requires an ADR link |
| Docs/runbook | Docs lint for touched operational paths; reviewer checklist |
| Demo script | `docs/demos/<story-id>.md` linted for ≤5 fenced lines |
| Observability | PR checklist; dashboards queried in the sprint demo |

---

## 12. Operating model (Phase 2 working agreement)

**Branching and commits**
- One branch per story: `feat/<epic>-<story-slug>` or `fix/<slug>` (e.g., `feat/e1-s4-orchestrator-state-machine`).
- Conventional Commits (`feat(cell): …`, `fix(cp): …`), small reviewable commits, squash on merge, never commit to `main`.

**Test discipline**
- Test-first or test-in-the-same-commit; a story is not done without a test that would fail on regression.
- Integration tests use Testcontainers/Compose — never a mocked database or a mocked AUT.

**Security discipline**
- gitleaks in pre-commit and CI; structured redaction at the logging layer; no `.env` committed.
- Every new network destination goes on the egress allowlist **and** into the ADR/runbook in the same PR.
- Every new secret goes through the broker; values never appear in code, config, logs, or fixtures.

**Architecture discipline — stop and raise if a change would:**
1. Put UI code in the cell, or LLM/repo keys in the control plane.
2. Let the cell reach the internet beyond the allowlist.
3. Make the cell stateful across runs.

**Documentation discipline**
- OpenAPI entry for every public endpoint; a runbook for every operational procedure; an ADR for every decision; a ≤5-line demo script for every demo.

**Cadence**
- Before a sprint: `docs/sprints/sprint-N-plan.md` confirming the goal and stories.
- After a sprint: `docs/sprints/sprint-N.md` with committed vs delivered, demo links, metrics (coverage, build time, open bugs), plan changes, and risks materialized.
- Any scope change to a running sprint requires updating both files and this plan's changelog.

---

## 13. Traceability — brief constraint → enforcing stories

| Constraint | Enforced by |
| --- | --- |
| Cell is ephemeral, one per run, UI-less | E1-S1, E1-S2, E7-S1, ADR-002 |
| Cell holds secrets only via broker, short-lived | E1-S8, E7-S4, ADR-005 |
| Cell has no user-facing HTTP/static/session storage | E7-S1 (dependency + filesystem + route audit) |
| Internal API limited to six endpoints, run-scoped tokens | E1-S3, E1-S5, E1-S6, ADR-003 |
| Rootless/non-root/read-only rootfs, no `CAP_SYS_ADMIN` | E1-S1 |
| Deny-by-default egress; allowlist LLM/registries/AUT | E1-S7, E7-S2 |
| Redaction before any disk write | E1-S7, E4-S4, E7-S4 |
| Every agent action cites a context node | E2-S2, E2-S7 |
| A11y missing label → stop + testability defect (never guess CSS) | E2-S4 |
| AUT separate workload; cell never runs client code | E3-S1, E3-S2, ADR-001 |
| Build instrumented image (source maps + sidecar) | E3-S1, E4-S1, E4-S2 |
| Frontend V8 + source maps | E4-S1 |
| Backend sidecar + `X-Test-Id` | E4-S2 |
| Network correlation path→route→handler→call graph | E4-S3 |
| Mock targets as negative edges; stop at mocks | E4-S3 |
| `granularity ∈ {line, endpoint, inferred}` on every test→symbol edge | E4-S3, ADR-004, ADR-007 |
| Inferred-only → broaden or full suite | E4-S3 |
| Evidence → client-owned object storage | E4-S4 |
| CP holds no LLM/repo keys, no client code | E5-S1, E5-S6, ADR-005 |
| CP stores evidence metadata only | E5-S6 |
| Auth: SSO + RBAC (admin/operator/viewer) | E5-S2 |
| Cell registry + health | E5-S4, E5-S5 |
| Billing/metering + license management | E5-S8, E5-S9, ADR-006 |
| Signed update distribution | E5-S10, E8-S2, E8-S5 |
| mTLS + rotation | E7-S3 |
| Audit logging | E5-S7, E7-S4 |
| BYOC Terraform (AWS) | E8-S1 |
| OTel/Prometheus/Grafana/Sentry | E9-S1..S5 |
| Docs/runbooks/demos/handover | E10-S1..S5, §12 |

---

## 14. Approval gate

**This is the end of Phase 1. No production code has been written.**

To approve, I need a decision on:

1. **Q1 / ADR-003** — outbound, cell-initiated mTLS control channel (recommended) vs inbound mTLS vs queue-only. *Blocks S5.*
2. **Q2 / ADR-001** — rootless build Job (recommended) vs prebuilt-image-only vs privileged DinD. *Blocks S4.*
3. **Q3** — cell-minted evidence URLs + re-mint over the channel. *Blocks S6.*
4. **Q4, Q5** — shadow mode / workspace-only writes; CP holds secret references only. *Block S3.*
5. **Q7 and Q12** — team capacity and sprint scope (12 weeks = demo, not GA).

**If approved as written:** I start Sprint 1 by creating `docs/sprints/sprint-1-plan.md`, then execute E0-S1 → E0-S8, E1-S1/S2, E7-S1, with the Demo at the end of week 2.

**If any decision changes:** I will re-baseline the affected sprint and update this document's changelog before writing code.

---

### Changelog

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | 2026-10-23 | Initial Phase 1 plan for approval |
