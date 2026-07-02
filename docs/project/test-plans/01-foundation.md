# Epic 1: Project Foundation — Manual Test Plan

---

## Prerequisites

- [ ] `cd /Users/skaparwan/github/chatgpt/testradius`
- [ ] `uv sync` in `services/workbench/` completed
- [ ] `npm install` in `apps/workbench/` completed

---

## 1. Directory Structure

- [ ] `apps/workbench/` exists with: `package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`, `electron/`, `src/`
- [ ] `services/workbench/` exists with: `pyproject.toml`, `tests/`, `testsquad_workbench/`

## 2. Python Backend

- [ ] `uv run pytest services/workbench/tests/ -v` — all pass (0 failures)
- [ ] `uvicorn services.workbench.main:app --port 8000` starts without error
- [ ] `curl http://localhost:8000/health` returns `{"status":"ok"}`

## 3. Electron App

- [ ] `npm run build` in `apps/workbench/` succeeds
- [ ] Build output contains: `dist/index.html`, `dist/assets/*.js`, `dist/assets/*.css`

## 4. Project Docs

- [ ] `docs/project/README.md` exists
- [ ] `docs/project/kanban.md` shows current state
- [ ] All 10 epic files exist in `docs/project/epics/`

---

## Result

- [ ] **All pass** — Epic 1 Done, proceed to Epic 2
- [ ] **Some failed** — report issues to fix
