# Sprint 4 Plan — AUT Deployment + Coverage

**Sprint:** 4 of 6  
**Nominal window:** 2026-12-04 → 2026-12-17 (confirm at kickoff)  
**Capacity:** 34 dev-days  
**Committed:** 32 dev-days  
**Status:** Pre-drafted; not started  
**Baseline:** Sprint 3 accepted

## Goal

Turn the cell from a browser driver into an isolated test runner. The cell builds
the instrumented fixture AUT, deploys it as an adjacent workload, waits for
readiness, runs the scenario, and attributes browser and backend coverage back to
test IDs. Every temporary namespace is torn down. This is the highest-risk sprint
in Phase 1; the build/cluster path is proven before coverage work expands.

## Committed stories

| Story | Title | Est | Depends on |
| --- | --- | ---: | --- |
| E3-S1 | Instrumented AUT build (fixture Dockerfile, build Job) | 3d | E2-S4 |
| E3-S2 | Adjacent AUT workload deploy and teardown | 5d | E3-S1 |
| E3-S3 | Readiness, migrations, and seed | 3d | E3-S2 |
| E4-S1 | Frontend V8 coverage and source-map remapping | 8d | E3-S2, E2-S4 |
| E4-S2 | Backend coverage sidecar and test-id propagation | 8d | E3-S3 |
| E4-S3 | Coverage stitcher: granularity, mocks, escalation | 5d | E4-S1, E4-S2 |

## Carryover and debt

- **`MINIO-IMAGE`** — replace `elestio/minio:latest` with a trusted, pinned
  image before evidence work depends on it. Budget 0.5 day inside the 2-day
  buffer.
- **Evidence remains an in-run artifact.** E4-S4 is Sprint 5; Sprint 4 proves
  coverage attribution and local artifact capture, not the evidence API.
- **`IMAGE-SIZE`** should be closed in Sprint 3. If still open, take one day from
  this sprint's buffer and record the carryover rather than hiding it.
- **Full orphan reaper is E3-S4 (post-S6).** Sprint 4 implements label/age
  cleanup and teardown for the active run; the global sweeper remains future work.
- **Pre-existing TIA script secret literal** remains outside factory scope.

## Dependencies and assumptions

- Sprint 3 agent loop, MCP Playwright tools, and citation enforcement are green.
- A local Kubernetes cluster is available for integration tests. Use `kind` or
  `k3d`; a Compose sibling is **not** accepted as evidence for E3-S2.
- A rootless image builder is available in-cluster. Prefer rootless BuildKit;
  prove it in the first two days. Do not give the cell a Docker socket.
- The fixture AUT has a deterministic build, a health endpoint, and no external
  services beyond its own process.
- The fixture graph or a read-only graph adapter is available for E4-S3. Verify
  this on day one; if the graph is empty, seed fixture symbols from the AST.

## Environment decision required at kickoff

Sprint 4 adds a second execution substrate (Kubernetes) alongside the local
Compose stack. Decide and document one of:

1. **Recommended:** `kind` for local/CI integration, with raw manifests under
   `infra/k8s/`; Helm and customer clusters arrive in S7–S9.
2. A managed development cluster with the same namespace and network-policy
   tests.

The sprint does not exit on a Compose-only emulation. If the cluster path is
blocked, the sprint is blocked, not silently redefined.

## Work breakdown

### E3-S1 — Instrumented AUT build

- Add the fixture Dockerfile/build job. Build from the workspace read-only,
  emit an image digest, and record the source commit.
- Use a rootless builder; the cell never receives a Docker socket or host build
  credentials.
- Fail closed on build errors; redact logs before they enter run events.
- Tests: build produces a digest; source mutation is impossible; failure is
  typed and redacted; no host socket is mounted.

### E3-S2 — Adjacent AUT workload deploy and teardown

- Create a per-run namespace/name derived from the run ID; apply labels,
  resource limits, and a default-deny network policy plus the minimum ingress.
- Deploy the built image as a separate workload. The cell reaches it only over
  the documented service endpoint.
- Tear down the namespace on success, failure, timeout, and cancel. Add a
  label/age cleanup path for leaked resources.
- Tests: cell and AUT are in different workloads; network policy blocks
  unexpected paths; teardown leaves no namespace; cancel during deploy cleans up.

### E3-S3 — Readiness, migrations, and seed

- Wait for readiness with a bounded timeout; distinguish crash loop, migration
  failure, and not-ready-yet.
- Run fixture migrations/seed only when required. Do not run production
  migrations from the cell in later environments.
- Tests: readiness timeout; migration failure; seed is idempotent; `5xx` is not
  treated as ready.

### E4-S1 — Frontend V8 coverage and source-map remapping

- Collect V8 coverage from the fixture browser session and remap through source
  maps to source files.
- Attribute coverage per test ID; prevent coverage bleed between tests.
- Record unmapped coverage as `inferred`/unmapped, never as a false `line` claim.
- Tests: two tests produce distinct coverage; source-map remap; unmapped metric;
  coverage survives navigation/reload.

### E4-S2 — Backend coverage sidecar and test-id propagation

- Add the Node fixture coverage sidecar and propagate `X-Test-Id` from the
  browser/MCP layer.
- Record `no_test_id` when propagation is absent; do not guess.
- Add a capability probe so unsupported stacks degrade to `inferred` plus
  escalation.
- Tests: endpoint edge attributed to the test; missing ID yields `no_test_id`;
  sidecar flush; capability probe for an unsupported stack.

### E4-S3 — Coverage stitcher

- Join test → symbol evidence with granularity `line`, `endpoint`, `inferred`,
  and `MOCKED`.
- A changed symbol with only inferred coverage must escalate. Mocked paths stop
  traversal instead of creating false reachability.
- Guard against stale SHAs and missing test IDs.
- Tests: fixture yields all four edge kinds; inferred-only change escalates;
  mock stops traversal; SHA mismatch fails closed.

## Execution order

1. **Day 1–2:** cluster proof, rootless build, fixture graph check. If any fails,
   escalate before writing coverage code.
2. E3-S1, then E3-S2.
3. E3-S3 and E4-S1/E4-S2 in parallel after E3-S2.
4. E4-S3 after both coverage paths.
5. Teardown/cancel/leak tests and the MinIO image pin.
6. Re-run the full Compose smoke to prove the factory path did not regress.

## Demo

```bash
# Provision the local cluster once.
kind create cluster --name testradius-s4

# Run through the cell; the run creates and tears down its own namespace.
RUN_ID=$(curl -fsS localhost:58000/v1/runs \
  -H 'content-type: application/json' \
  -d '{"goal":"verify checkout","repo":"fixture","commit":"abc1234","scope":"full","policy":{"coverage":true}}' \
  | jq -r .id)
curl -fsSN localhost:58000/v1/runs/$RUN_ID/events

kubectl get ns -l testradius.io/run=$RUN_ID   # expect none after completion
curl -fsS localhost:58000/v1/runs/$RUN_ID | jq '.coverage'
```

Show Neo4j edges for `line`, `endpoint`, `inferred`, and `MOCKED`, then show
that a changed symbol with only inferred coverage escalates.

## Exit criteria

- [ ] The fixture AUT builds in a separate build job with a recorded digest.
- [ ] The AUT runs in an adjacent workload; the cell has no Docker socket.
- [ ] Readiness, migration, and seed failures are typed and tested.
- [ ] Teardown removes the namespace after success, failure, timeout, and cancel.
- [ ] Frontend coverage remaps to source; backend coverage carries test IDs.
- [ ] All four edge kinds are produced; inferred-only changes escalate.
- [ ] `MINIO-IMAGE` is pinned to a trusted image and the stack still passes smoke.
- [ ] `make test`, `make lint`, `make arch-test`, `make smoke`, gitleaks, and the
      cluster integration suite pass.
- [ ] `docs/sprints/sprint-4.md` records delivered vs planned, demo, metrics,
      and deviations.

## Staged verification

- Local `kind`/managed dev cluster, not customer BYOC or Helm; S7–S9.
- Fixture Dockerfile, not a generic builder; E3-S7 is post-S6.
- Adjacent workload, not remote customer AUT; E3-S6 is post-S6.
- Evidence is local; E4-S4 object storage and the evidence API are Sprint 5.
- Global orphan reaper is E3-S4 post-S6; Sprint 4 provides run-scoped teardown
  and label/age cleanup.
- Coverage adapters cover the fixture's Node/browser stack first; other stacks
  degrade to `inferred` with escalation.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Cluster/build path fails | Prove it in the first two days; stop and escalate rather than fake isolation. |
| Build requires privileges | Use rootless BuildKit; never mount the Docker socket into the cell. |
| Coverage remapping is wrong | Treat unmapped as unmapped; require a real source-map test and a false-`line` guard. |
| Teardown leaks on cancel | Test cancel at each deployment stage; add label/age cleanup now. |
| Graph data is missing | Seed fixture symbols from AST on day one; do not fabricate inferred edges. |
| Sprint is too large | Protect E3-S2 and E4-S1; descope fixture seed only with a documented deviation. |

## Definition of done

The cluster integration suite is part of the sprint gate, not a manual demo.
Namespaces are gone after every terminal state, coverage claims are honest, and
the next sprint starts only after the Sprint 4 review accepts the cluster path.
