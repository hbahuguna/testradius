# Contributing to the TestRadius Factory

This repository contains two product surfaces:

- `services/`, `apps/workbench/`, `apps/testradius/` — the existing TIA product (see `docs/project/`).
- `apps/cell/`, `apps/control-plane/`, `apps/web/`, `packages/`, `infra/` — the Testing Factory
  (see `docs/project-plan.md` and `docs/sprints/`).

Keep changes scoped to one surface per PR wherever possible.

## Branching

- One branch per story: `feat/<epic>-<story>-<slug>` (e.g. `feat/e1-s4-orchestrator-state-machine`)
  or `fix/<slug>`.
- Never commit directly to `main`. Open a PR, get a self-review pass recorded in the PR checklist,
  and squash-merge.
- Keep PRs under ~400 changed lines where practical. Split schema/refactor churn from behavior.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `feat(cell): add health endpoint`,
`fix(cp): scope run lookup by tenant`, `docs(adr): record outbound control channel`.
`commitlint` enforces the header in CI.

## Tests

- Test-first or test-in-the-same-commit. A change is not done without a test that fails on
  regression.
- Integration tests use Compose or Testcontainers — never a mocked database or a mocked AUT.
- Commands:
  - `make test` — Python cell + architecture tests, then JS workspace tests.
  - `make arch-test` — the boundary checks only (fast; run before every push).
  - `make ci` — what CI enforces locally.

## Security

- `gitleaks` runs in pre-commit and CI. Never commit `.env`, keys, tokens, or fixtures containing
  secret-shaped values.
- Every new secret goes through the secrets broker (Vault or AWS Secrets Manager). Secret values
  are never logged, written to a workspace, or uploaded as evidence.
- Every new outbound destination must be added to the egress allowlist **and** documented in the
  ADR/runbook in the same PR.

## Architecture — stop and raise

Open an issue/thread before writing code if a change would:

1. Put UI code, static assets, or session storage in the cell.
2. Put LLM, repository, or database credentials in the control plane.
3. Let the cell reach the internet beyond the allowlist.
4. Make the cell stateful across runs.
5. Run client code inside the cell's namespace.

The architecture tests (`infra/architecture-tests`) will fail the build for (1) and (3); the rest
are review gates.

## Documentation

- ADR for every decision → `docs/adr/NNN-slug.md`.
- Runbook for every operational procedure → `docs/runbooks/`.
- OpenAPI entry for every endpoint.
- Demo script (≤5 commands) → `docs/demos/`.

## Local setup

```bash
make doctor
make bootstrap
make up
make smoke
```

See `docs/runbooks/local-dev.md` for ports, troubleshooting, and teardown.
