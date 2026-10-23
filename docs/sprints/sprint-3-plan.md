# Sprint 3 Plan — Agent Runtime + MCP

**Sprint:** 3 of 6  
**Nominal window:** 2026-11-20 → 2026-12-03 (confirm at kickoff; can start earlier)  
**Capacity:** 34 dev-days  
**Committed:** 32 dev-days  
**Status:** In progress (branch `feat/sprint-3-agent-runtime`)  
**Baseline:** `main` after the sprint-plan merge (`e1686c8`)

## Goal

Make the cell reason and act. A Planner decomposes a goal into cited steps, an
Executor drives the Compose-hosted fixture AUT through Playwright MCP, and every
action is attributable to a resolved context node. The accessibility stop rule
is enforced: a blocking defect is reported as `testability_defect`, never worked
around with brittle CSS or a synthetic selector.

## Committed stories

| Story | Title | Est | Depends on |
| --- | --- | ---: | --- |
| E2-S1 | Model provider abstraction | 4d | E0-S5 |
| E2-S2 | Agent loop, tool protocol, citation enforcement | 8d | E2-S1, E1-S7 |
| E2-S3 | MCP layer and tool registry | 4d | E2-S2 |
| E2-S4 | Playwright MCP integration | 5d | E2-S3, E0-S2 |
| E2-S7 | Context retrieval client | 4d | E0-S5 |
| E2-S8 | Planner agent | 3d | E2-S2, E2-S7 |
| E2-S11 | Executor agent | 4d | E2-S4, E2-S8 |

## Carryover and debt

- **`IMAGE-SIZE` (Sprint 1 AC2) — closed.** The recursive `chown` of `/app` and
  `/ms-playwright` was copying the Chromium tree into a new layer. Removing it
  (only `/workspace` and `/home/cell` need cell ownership) reduced the measured
  image from 2.81 GB to **1.62 GB**, below the 2.5 GB target.
- **Evidence is local for now.** E4-S4 object storage is Sprint 5. Sprint 3
  writes screenshots, traces, and console/network logs under the run workspace
  and references them from events; the evidence API remains a stub.
- **Compose AUT is the S3 execution path.** The adjacent AUT workload is E3-S2
  in Sprint 4. Do not present the Compose sibling as the production isolation
  model.
- **`OPENAPI` and `JTI-REPLAY`** remain Sprint 5 debt; they are not Sprint 3
  exit criteria.
- **Pre-existing TIA script secret literal** remains with TIA owners; factory
  gitleaks stays scoped to factory paths.

## Dependencies and assumptions

- S1/S2 are merged and green: run lifecycle, SSE, policy engine, token issuance,
  Vault broker, and the seven-phase orchestrator exist.
- The fixture AUT exposes the golden path and the two intentional a11y defects.
- CI uses `FakeProvider`; no live model call is required to pass tests.
- The cell may reach the configured model endpoint and the Compose mock AUT only;
  hard egress enforcement is E7-S2 in Sprint 6.
- Node 20 remains in the cell image for Playwright; MCP packages are pinned.
- No UI dependency is added to the cell.

## Work breakdown

### E2-S1 — Model provider abstraction

- Define `complete`, `stream`, `tool_calls`, and `token_usage` in a provider
  interface. Implement Anthropic and OpenAI-compatible adapters plus
  `FakeProvider`.
- Add retry with exponential backoff and jitter for 429/5xx/timeout, a per-run
  token/tool budget, typed terminal errors, and per-step usage accounting.
- Never log API keys or prompt bodies in CP-bound events. Redact provider errors
  before they reach events.
- Tests: same agent-loop contract against both adapters with fake transports;
  retry cap; budget exhaustion; key sentinel absent from logs and events;
  provider selection is policy-configurable.

### E2-S2 — Agent loop, tool protocol, citation enforcement

- Add a versioned step/tool contract to `packages/shared-types` and the cell.
- Resolve citations against context node IDs. A step with a missing or
  unresolved citation is rejected; one re-prompt is allowed, then the run fails
  with a typed `uncited_action` error.
- Add duplicate-tool/step loop detection and a hard step cap.
- Emit `step.started`, `tool.called`, `step.completed`, and citation failures as
  ordered SSE events.
- Tests: uncited tool call blocked before execution; second failure terminal;
  repeated action stops; citations resolve; event ordering and schema.

### E2-S3 — MCP layer and tool registry

- Implement a declarative registry with per-role allowlists, per-call timeouts,
  health checks, and structured denial events.
- Only allow spawning/connecting to registered MCP servers. Unknown tools are
  rejected before invocation.
- Pass the run-scoped secret only through the broker; never expose it in tool
  arguments, events, or logs.
- Tests: disallowed tool denied before call; timeout is typed; unhealthy server
  is not selected; registry change is policy-configurable.

### E2-S4 — Playwright MCP integration

- Expose `navigate`, `click`, `type`, `assert`, `screenshot`, and
  accessibility-tree reads through MCP.
- Drive the golden path and assert the two intentional a11y defects. A blocking
  defect produces `testability_defect` and stops the scenario; no CSS-selector
  fallback.
- Capture screenshot/trace/console/network artifacts into the run workspace and
  link them to the step event.
- Tests: golden path; a11y negative; blocked selector fallback; artifact paths
  are run-scoped; no UI asset served by the cell.

### E2-S7 — Context retrieval client

- Retrieve fixture symbols, routes, and prior test context with stable node IDs;
  cache per run and respect a token budget.
- Degrade to a filesystem/AST view if the graph is unavailable; mark the source
  in the event rather than fabricating a citation.
- Tests: stable IDs; cache hit/miss; budget truncation; graph-down fallback;
  no citation to a missing node.

### E2-S8 — Planner agent

- Produce a plan artifact with ordered steps, tool intent, and citations.
- Validate cycles, duplicate steps, unavailable tools, and missing context.
  Return `insufficient_context` instead of guessing.
- Tests: valid plan; cycle rejected; unknown tool rejected; missing citation
  rejected; plan is replayable from the event stream.

### E2-S11 — Executor agent

- Execute the plan one step at a time, record verdicts, stop on blocking a11y
  defects, and attach local evidence.
- Record step duration, token usage, tool calls, and terminal reason.
- Tests: two consecutive FakeProvider runs produce the same verdicts; blocking
  defect stops the scenario; cancel is honored between steps; evidence links
  resolve.

## Execution order

1. E2-S1 and E2-S7 in parallel.
2. E2-S2 on top of E2-S1.
3. E2-S3, then E2-S4.
4. E2-S8 after E2-S2 and E2-S7.
5. E2-S11 after E2-S4 and E2-S8.
6. Image-size reduction in the final buffer; re-run the image check last.

## Demo

```bash
make up
make smoke
```

Run the cited FakeProvider scenario, the Playwright artifact capture, and the
blocking-a11y negative in [`docs/demos/sprint-3.md`](../demos/sprint-3.md).

Optional live demo: select the pinned Anthropic or OpenAI-compatible model via
policy, with the key supplied by the cell secret broker.

## Exit criteria

- [ ] Two consecutive FakeProvider runs produce the same scenario verdicts.
- [ ] Every executed action resolves to a citation; uncited actions are blocked.
- [ ] The fixture's blocking a11y defect yields `testability_defect` with no
      selector fallback.
- [ ] Tool allowlists and denial events are tested.
- [ ] The cell serves no UI assets and route-audit tests still pass.
- [ ] No model key or prompt body appears in CP-bound events or logs.
- [ ] Cell image is ≤2.5 GB, or `IMAGE-SIZE` is explicitly carried forward.
- [ ] `make test`, `make lint`, `make arch-test`, `make smoke`, and gitleaks pass.
- [ ] `docs/sprints/sprint-3.md` records delivered vs planned, demo, metrics,
      and deviations.

## Staged verification

- Local evidence workspace, not object storage; E4-S4 is Sprint 5.
- Compose-hosted fixture AUT, not an adjacent workload; E3-S2 is Sprint 4.
- Policy allowlist in the tool layer, not a network-enforced egress proxy; E7-S2
  is Sprint 6.
- `FakeProvider` is the CI path; live provider output is demo evidence, not a
  deterministic gate.
- No Kubernetes, Helm, or Terraform work in this sprint.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Agent loop becomes a monolith | Keep provider, planner, executor, and MCP registry behind typed interfaces; test each in isolation. |
| Citation enforcement is bypassed by tool calls | Resolve citations before tool invocation; make the tool gateway the only path. |
| MCP package churn breaks the image | Pin versions and add a contract smoke test against the mock AUT. |
| Live model variability | CI uses FakeProvider; live demo uses a pinned model and records the transcript. |
| Image-size work expands | Timebox to 2 days; carry the measured debt rather than silently failing the AC. |
| A11y rule is treated as advisory | Make `testability_defect` terminal and cover it with a negative test. |

## Definition of done

Code, tests, docs, and demo are merged on a feature branch. No secrets are
committed, architecture tests pass, and the sprint review records both delivered
and staged behavior. The next sprint does not start until Sprint 3 is accepted.
