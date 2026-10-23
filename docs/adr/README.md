# Architecture Decision Records

| ADR | Decision | Status |
| --- | --- | --- |
| [001](001-cell-and-aut-separate-workloads.md) | The cell is a container; the AUT is a separate workload | Accepted (plan approved 2026-10-23) |
| [002](002-no-ui-in-cell.md) | No UI in the cell, enforced by an architecture test | Accepted |
| [003](003-outbound-mtls-control-channel.md) | mTLS + run-scoped tokens, with the cell initiating the connection | Accepted (revisit in S5 load test) |
| [004](004-coverage-stitching.md) | Coverage stitching across the frontend/backend boundary | Accepted |
| [005](005-secrets-broker.md) | Secrets broker: portable interface, Vault default | Accepted |
| [006](006-byoc-licensing.md) | BYOC licensing: per-deployment lease, per-instance metering | Accepted |
| [007](007-reuse-tia-engine.md) | Reuse the existing TIA engine for selection and the graph | Accepted |

## Adding an ADR

1. Copy the structure: Context → Decision → Consequences → Alternatives considered.
2. Number sequentially; never renumber.
3. Record status (`Proposed`, `Accepted`, `Superseded by ADR-NNN`).
4. Link the story that implements it.
5. Security-critical decisions are proposed, not assumed — they need explicit sign-off.
