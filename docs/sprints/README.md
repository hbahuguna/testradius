# Sprint index

## How many sprints

The approved Phase 1 plan has **six committed sprints** (S1–S6), followed by an
**indicative post-S6 roadmap** of four more (S7–S10). The six committed sprints
deliver the demoable vertical slice; S7–S10 cover the remaining agent roles,
BYOC/Helm/Terraform, licensing, observability, and handover.

| Sprint | Title | Committed | Status | Plan |
| --- | --- | ---: | --- | --- |
| S1 | Foundation + cell skeleton | 32 | Complete, merged | [`sprint-1-plan.md`](sprint-1-plan.md) |
| S2 | Orchestrator + internal API | 32 | Complete, merged | [`sprint-2-plan.md`](sprint-2-plan.md) |
| S3 | Agent runtime + MCP | 32 | **Complete, merged (pending)** | [`sprint-3-plan.md`](sprint-3-plan.md), [`sprint-3.md`](sprint-3.md) |
| S4 | AUT deployment + coverage | 32 | Planned | [`sprint-4-plan.md`](sprint-4-plan.md) |
| S5 | Control plane backend + auth | 31 | Planned | [`sprint-5-plan.md`](sprint-5-plan.md) |
| S6 | Control plane UI + security gate | 36 | Planned | [`sprint-6-plan.md`](sprint-6-plan.md) |

Capacity is 34 dev-days for S3–S5 and 36–40 for S6. The committed totals leave
buffer for debt and discovery; no sprint is considered started until its plan
is reconfirmed at kickoff.

## Recommended order

**Sprint 3 is in progress.** Sprints 1 and 2 are merged into `main`; Sprint 3 is
the first sprint that makes the cell reason and act, and S4–S6 depend on its
agent loop, MCP layer, citations, and Playwright executor.

The critical path is:

```text
S1 → S2 → S3 → S4 → S5 → S6
              ↘ image-size debt (S3 buffer)
```

Sprint 4 is the highest-risk sprint because it introduces a separate AUT
workload and browser/server coverage attribution. Sprint 5 must not start until
S4's teardown and coverage tests are green; Sprint 6 must not start until S5's
tenant scoping and control channel are green.

## Post-S6 roadmap (indicative)

| Sprint | Focus |
| --- | --- |
| S7 | Remaining agent roles, generator, orphan reaper, billing/licensing |
| S8 | Diagnoser/healer, remote AUT, BYOC foundations |
| S9 | Operations, observability, packaging, Terraform/Helm |
| S10 | Handover and GA |

These are not scheduled in detail yet. They depend on S6 outcomes, frontend
capacity, and BYOC decisions; each will get a just-in-time plan before it starts.

## Known carryovers into S3–S6

| Item | Origin | Target |
| --- | --- | --- |
| `IMAGE-SIZE` — cell image 2.81 GB > 2.5 GB AC | S1 | Closed in S3: 1.62 GB |
| `OPENAPI` — generated contracts/shared types from APIs | S1 | S5 |
| `JTI-REPLAY` — single-use `jti` cache for mutating calls | S2 | S5 |
| `MINIO-IMAGE` — pin a trusted MinIO image | S1/S2 | S4 |
| `EVIDENCE` — evidence endpoint returns empty list | S2 | S5 |
| `E5-S7` — CP audit log omitted from the original S5 table | Plan gap | S5 |
| `FIXTURE-INSTR` — fixture coverage instrumentation | S1 | S4 |
| Pre-existing TIA script secret literal | TIA workstream | Not factory scope |
