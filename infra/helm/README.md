# Helm charts

Sprint 1 placeholder. The cell/control-plane charts land in E9-S1 (S6) per
`docs/project-plan.md`. Compose is the only supported local deployment in Sprint 1.

The cell chart must set: `readOnlyRootFilesystem: true`, `runAsUser: 10001`,
`runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, and mount
`/workspace` plus `emptyDir` for `/tmp` and `~/.cache` (ADR-001/ADR-002).
