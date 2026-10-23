# ADR-006 — BYOC licensing: per-deployment lease, per-instance metering

## Context
BYOC customers want predictable cost and minimal egress; SaaS customers expect elastic, usage-based billing. Licensing must work with partially disconnected VPCs, survive CP outages, and support revocation. The brief allows "per-deployment or per-instance; configurable".

## Decision
1. **BYOC default: per-deployment license lease.** The CP issues a signed lease (`tier`, `deployments`, `expiry`, `revocation_id`). The cell validates it locally, heartbeats every 24 h, and operates in a 7-day grace window if the CP is unreachable. Revocation takes effect within one heartbeat once connected.
2. **SaaS default: per-instance metering** (concurrent runs / run-minutes / agent tokens).
3. **Metering is always on** for both, as signed, aggregated usage batches (no prompt content, no code); it is used for reporting and quota, not as the sole enforcement for BYOC.
4. Enforcement is local-first: a cell refuses new runs when the lease is expired/revoked outside grace; it never blocks an in-flight run on a licensing check.
5. Reuse the existing `packages/license-client` fingerprint/lease semantics; add a Node verifier for the CP.

## Consequences
- (+) Predictable BYOC pricing; SaaS remains elastic.
- (+) Works through CP outages and strict egress policies.
- (−) Clock skew and grace-window abuse are possible; mitigated by signed timestamps and anomaly reporting.
- (−) Usage disputes require reconciliation tooling (E5-S8).
- (−) Two commercial models to document and test.

## Alternatives considered
- Pure per-instance — rejected: BYOC buyers dislike open-ended metering and its egress footprint.
- Pure per-deployment — rejected: no SaaS elasticity, poor fit for small teams.
- Hard online check per run — rejected: breaks air-gapped/regulated deployments and adds a SPOF.

---
