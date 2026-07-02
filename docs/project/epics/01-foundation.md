# Epic 1: Project Foundation

**Theme**: "Build the workbench." Establish project structure, tooling, CI, and conventions.

**Dependencies**: None

---

## Stories

| # | Story | Status |
|---|-------|--------|
| 1.1 | Project scaffolding — directories, pyproject.toml, package.json | Done |
| 1.2 | Python backend skeleton — FastAPI app with health endpoint | Done |
| 1.3 | Electron + React skeleton — Electron shell with React UI | Done |
| 1.4 | Testing infrastructure — pytest config, conftest, first tests | Done |
| 1.5 | CI pipeline — GitHub Actions workflow | Done |
| 1.6 | Conventions — CLAUDE.md, project docs | Done |

---

## Acceptance Criteria

- [ ] `apps/workbench/` exists with runnable Electron + React app
- [ ] `services/workbench/` exists with runnable FastAPI backend
- [ ] `pytest services/workbench/tests/` — all green
- [ ] `npm run build` in apps/workbench — succeeds
- [ ] CI pipeline runs on push/PR
- [ ] Project docs in `docs/project/`

---

## Manual Test Plan

See `docs/project/test-plans/01-foundation.md`
