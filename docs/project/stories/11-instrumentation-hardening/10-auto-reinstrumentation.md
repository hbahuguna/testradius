# Story 11.10: Automatic Re-Instrumentation Trigger

**Status**: Backlog
**Epic**: 11 — Instrumentation Hardening
**Effort**: 2d
**Priority**: P2
**Depends on**: 11.1

---

## Summary

Evidence must refresh without manual intervention. A default-branch push (or a schedule) should trigger re-instrumentation, and stale evidence should be refreshable on demand.

## Current behaviour (the problem)

- There is no automatic trigger. Re-instrumentation is user/agent-driven only.
- The agent's `EvidenceStatus.needs_instrumentation` (`apps/tia-agent/.../tools/models.py:216-218`) is derived from `/test-mapping` freshness, not from `built_at_sha`; `flow._instrumentation_gate` explains and asks for confirmation but never auto-runs.
- When evidence is stale, `analyze-pr` forces a full-suite fallback (`apps/tia-agent/.../analyze.py`) instead of refreshing the graph.

## Acceptance criteria

- [ ] A push to the project's default branch triggers an instrumentation run (via the GitHub App webhook → core service).
- [ ] The trigger is idempotent and coalesces rapid pushes (e.g. skip if a run is in progress; debounce).
- [ ] A project can opt in/out via its feature flags (consistent with `PUT /projects/{id}/features`).
- [ ] An on-demand refresh endpoint lets the agent request re-instrumentation when evidence is stale.
- [ ] Documented in the runbooks; no run is triggered for archived/disabled projects.

## Implementation notes

- GitHub App (`services/github-app`) already handles `pull_request.opened` / `synchronize`; add a `push` handler for the default branch that calls the instrumentation endpoint.
- Reuse the cancel flag mechanism (`main.py:1676`) to avoid duplicate concurrent runs per project.
- Gate on the `instrumentation` feature flag (`PUT /projects/{id}/features`).

## Tests (TDD — write first)

- New: `services/github-app` test — a default-branch push schedules one run; a second rapid push is coalesced.
- Core test — an in-progress run blocks a second run for the same project.

## Verification

```bash
# github-app tests + a manual push to a fork's default branch, then:
curl -s "$RADIUS/projects/$PROJECT_ID/instrumentation/coverage" | jq '.created_at'
```
