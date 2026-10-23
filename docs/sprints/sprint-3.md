# Sprint 3 Review — Agent Runtime + MCP

**Sprint:** 3 of 6  
**Dates:** 2026-11-20 → 2026-12-03 (planned)  
**Branch:** feat/sprint-3-agent-runtime  
**Status:** Complete

## Goal
Make the cell reason and act. A Planner decomposes a goal into cited steps, an Executor drives the Compose-hosted fixture AUT through Playwright tools, every action is attributable to a resolved context node, and a blocking accessibility defect is reported as `testability_defect` with no brittle selector workaround.

## Committed vs completed
| Story | Status | Evidence |
| --- | --- | --- |
| E2-S1 Model provider abstraction | Done | `apps/cell/cell/agent/provider.py` — protocol (`complete`/`stream`), `FakeProvider`, Anthropic and OpenAI-compatible adapters, `RetryingProvider`, `ProviderBudget`, typed `ProviderError`, redaction. Transport injection for tests. |
| E2-S2 Agent loop, tool protocol, citation enforcement | Done | `agent/types.py`, `agent/citations.py`, `agent/planner.py`, `agent/executor.py` — step contract, citation resolution, one re-prompt, cycles/duplicates/steps capped, ordered events, uncited actions blocked. Per-step durations. |
| E2-S3 MCP layer and tool registry | Done | `agent/mcp.py` — declarative registry, role allowlists, timeouts, health checks with TTL/cache, structured denials, `tool_not_registered` rejection, unknown tools rejected before invocation. |
| E2-S4 Playwright MCP integration | Done | `agent/playwright.py` — navigate/click/type/assert/check_a11y/accessibility_tree/screenshot/console/network/trace; blocking a11y stops with `testability_defect`; no CSS selector fallback; run-scoped artifact paths with traversal protection; network allowlist/egress guard. |
| E2-S7 Context retrieval client | Done | `agent/context.py` — stable file/symbol/route/test node IDs, workspace indexing, cache stats, token budget, graph-down `FallbackContextClient` marking source/fallback reason, `context.retrieved` events. |
| E2-S8 Planner agent | Done | `agent/planner.py` — JSON plan, validation, `insufficient_context`/`uncited_action`/`unavailable_tool`/`plan_cycle`, replayable from events. |
| E2-S11 Executor agent | Done | `agent/executor.py` — stepwise execution, loop detection, cancellation, evidence, metrics, terminal reasons. Two consecutive FakeProvider runs produce identical verdicts. |

## Demo
Verified via `docs/demos/sprint-3.md`:
- Cited FakeProvider plan against Playwright + mock AUT; artifacts under `/workspace/<run_id>` (`cart.png`, `console.json`, `network.json`, `trace.zip`).
- Blocking a11y defect on `/` yields `testability_defect`, stops at execute, no `run.completed`.

## Verification
| Check | Result |
| --- | --- |
| `make test` | Python cell tests (including 29 arch) + shared-types + control-plane + fixture-aut all passed (96 Python tests + workspace suites). |
| `make lint` | Passed (ruff check/format, prettier, typecheck). |
| `make arch-test` | 29 passed. |
| `make smoke` | Passed against running factory stack. |
| Agent tests | All `apps/cell/tests/agent/*` passed, including provider adapter contracts (Anthropic/OpenAI with fake transports), MCP health/allowlists/denials, context fallback/budget, Playwright path traversal and selector fallback blocking, executor durations and denial events, planner replay. |
| Image size | `tesseradius-cell:dev` **1.62 GB** (down from 2.81 GB) — below 2.5 GB. |
| Gitleaks | Scanned factory paths with `gitleaks:v8.18.4` (docker) — no leaks found. |
| Real browser | Golden path and a11y-negative verified with `browser=playwright` against the fixture AUT. |

## Staged deviations
- **MCP transport:** In-process typed tool registry only; external stdio/HTTP MCP transport not implemented (protocol-level surface is present).
- **Graph adapter:** Neo4j graph client not wired; filesystem/AST is configured source with a tested `FallbackContextClient` and `context.retrieved` source marking.
- **Egress:** Network policy is enforced in the Playwright client allowlist only; hard egress proxy remains Sprint 6 (`E7-S2`).
- **Evidence storage:** Local run workspace artifacts only; object storage and the evidence endpoint collector remain Sprint 5.
- **Streaming:** `Provider.stream` and adapter streaming are implemented (compatibility + real text SSE chunks) but the planner uses `complete` for JSON plans.
- **Live provider:** Deterministic gates use `FakeProvider`; live Anthropic/OpenAI calls are supported via the broker and verified with fake transports.

## Security notes
- API keys never logged or emitted in events; adapters accept credentials via constructor/secret path only; tests assert sentinel absence.
- Artifact paths sanitized to the run workspace (absolute and `..` escapes rejected).
- Tool calls require citations and role allowlists; unknown tools and unhealthy servers denied before invocation.
- A11y blocking defect is terminal (`testability_defect`) with no selector/synthetic fallback.
- `no UI assets` route audit remains enforced.

## Next
Merge `feat/sprint-3-agent-runtime` to `main`. Start Sprint 4 (AUT deployment + coverage) after provisioning `kind`/`k3d` or a managed dev cluster.
