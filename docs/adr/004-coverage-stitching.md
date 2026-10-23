# ADR-004 — Coverage stitching across the frontend/backend boundary

## Context
An e2e test crosses a browser and a server. Frontend coverage alone misses backend handlers; backend coverage alone cannot tell which test caused a call. The brief requires: V8 + source maps, backend sidecar with `X-Test-Id`, network correlation path → route → handler → static call graph, mock boundaries as negative edges, `granularity ∈ {line, endpoint, inferred}`, and escalation when a changed symbol has only inferred coverage.

## Decision
1. **Frontend:** Playwright `page.coverage.startJSCoverage/stopJSCoverage` per test → V8 ranges → source maps → original TS positions → AST symbol attribution → `granularity=line`.
2. **Backend:** sidecar in the AUT (Node: V8/nyc contexts; Python: `coverage.py` dynamic contexts) keyed by the `X-Test-Id` header injected by the runner → per-test line sets → AST symbol attribution → `granularity=line`.
3. **Correlation:** Playwright records request/response; the stitcher resolves `method + path` → route using a framework adapter's route table (Express/Fastify/Nest/FastAPI/Flask/Django), links the handler as `granularity=endpoint`, then traverses the static call graph and links descendants as `granularity=inferred`.
4. **Mocks:** every intercepted route produces a negative edge (`MOCKED`) and **stops traversal**; no downstream coverage is claimed.
5. **Confidence:** reuse the shipped formula (line ratio; `inferred` weight 0.5). An endpoint hit is 1.0 for the handler. No new ad-hoc scores per language.
6. **Trust:** edges are written only when the AUT image digest corresponds to the requested commit SHA (`CoverageShaMismatch` otherwise).
7. **Escalation:** if a changed symbol has only `inferred` coverage, selection broadens (endpoint → file → full suite) per policy and records `escalated_from=inferred`.
8. **Physical schema:** the existing `EVIDENCE` relationship carries a new `granularity` property. The brief's "COVERS" is the logical contract; we do not rename the proven edge type (ADR-007).

## Consequences
- (+) Explainable, cross-boundary evidence with an honest confidence gradient.
- (+) Mock boundaries are explicit rather than silent gaps.
- (−) A route-table adapter per framework; drift breaks attribution (mitigated by conformance tests and SHA-keyed caching).
- (−) Source-map remapping costs time and can be wrong; unmapped bytes are reported, never guessed.
- (−) `X-Test-Id` must be propagated by every runner; non-instrumented calls land in `no_test_id` (visible, not merged).

## Alternatives considered
- Browser-only coverage — rejected: misses backend impact, the main source of false negatives.
- APM/tracing-based correlation — promising for later, but adds a dependency and does not give per-test line evidence today.
- LLM-inferred mapping — rejected: non-deterministic and unexplainable, contradicting the product promise.

---
