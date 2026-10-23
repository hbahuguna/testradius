## What changed

<!-- One paragraph. Link the story id (e.g. E1-S4). -->

Story:
Surface: <!-- cell | control-plane | web | shared-types | fixtures | infra | existing-TIA -->

## Definition of Done

- [ ] Tests would fail if this regressed (unit, and integration if a process boundary is crossed)
- [ ] No secrets, credentials, or PII in code, logs, or fixtures
- [ ] Architecture test passes (no UI in cell; route allowlist)
- [ ] ADR added/updated if a decision was made
- [ ] Runbook/README updated if an operational procedure changed
- [ ] Demo script (≤5 commands) in `docs/demos/`
- [ ] Observability: a metric, log line, or span added for the new path

## Security review

- [ ] New outbound destination added to the egress allowlist and documented
- [ ] New secret goes through the broker (reference only, never a value)
- [ ] No UI/static/session code added to `apps/cell`

## How to verify

```bash
# exact commands the reviewer should run
```
