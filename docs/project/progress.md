# Project Progress — TestRadius Workbench

_Last updated: 2026-06-14_

---

## Overview

| Epics Total | Completed | In Progress | Backlog |
|-------------|-----------|-------------|---------|
| 10          | 4         | 1           | 5       |

**Current phase**: Epic 4 — Visual Inspector Rewrite (Single-Click Test Builder)

---

## Epic Status

| # | Epic | Status | Complete | Notes |
|---|------|--------|----------|-------|
| 1 | Project Foundation | **Done** | 100% | 5/5 manual checks pass |
| 2 | COM Generation Engine | **Done** | 100% | 84 tests, 9 stories |
| 3 | Page Viewer Shell | **Done** | 100% | API endpoints + React tree view |
| 4 | Visual Inspector + COM Gen | **In Progress** | ~60% | Rewrote frontend to Single-Click Test Builder (310 lines), removed 1493-line old UI. All 101 backend tests pass. |
| 5 | POM Composer + Test Gen | Backlog | 0% | Depends on Epic 4 |
| 6 | Test Execution + Reports | Backlog | 0% | Depends on Epic 5 |
| 7 | Interaction Recorder | Backlog | 0% | Depends on Epic 3 |
| 8 | ML Component Classifier | Backlog | 0% | Depends on Epic 2 |
| 9 | TestRadius TIA Integration | Backlog | 0% | Depends on Epic 6 |
| 10 | Team Features | Backlog | 0% | Depends on Epics 6 + 9 |

---

## What's Been Completed

### Epic 4: Visual Inspector — Single-Click Test Builder (Session: 2026-06-14)

**Goal**: Replace the complex drag-select + dialog-heavy UI with an always-on click-to-add-test-step workbench.

**Backend**: Copied from `testsquad-testing/testsquad-v2` — all 11 API endpoints (schemas.py, main.py, generation module). **101 tests passing.**

**Frontend rewrite** (`apps/workbench/src/`):

| Before (removed) | After (new) |
|---|---|
| ~1493 lines App.tsx — drag overlay, naming dialog with 7 sections, COM code editor, POM flow, element stack picker, selector chips, DOM tree viewer, field mini-dialog, ~30 state variables | ~310 lines App.tsx — simplified state (url, testSteps, genOutput, genLoading, highlightedStep, activeFile, copied) |
| Toggle-based selection mode (Select / Cancel Select) | **Always-on click** — every click in preview instantly adds a step, no toggle |
| Naming dialog with validation, selector alternates, DOM tree, child fields | **No dialog** — step added instantly, name/action inferred from element |
| Separate Components and Generated Code panels | **Right panel: test steps** — step cards with inline edit, Generate button |
| Generated code in a side panel | **Modal overlay** with file tabs (POM + test) + Copy button |
| ~1350 lines App.css with complex dialog/field/selection/tree styles | ~285 lines clean CSS with step card + output modal styles |

**Key UX decisions implemented**:
- `handleElementClick` with functional updater for duplicate detection (same cssPath → flash existing step)
- `inferName`: `elementId → text content (first 3 words) → tag`
- `inferAction`: `button/a → click`, `input/textarea → type`, `select → select`, default `click`
- Inspector script uses both `window.parent.postMessage` (iframe) and `console.log` (Electron webview)
- Preview loads via `/preview?url=` proxy (strips CSP, injects inspector server-side)
- Electron webview injects inspector via `executeJavaScript`

### Files Modified

| File | What |
|------|------|
| `apps/workbench/src/App.tsx` | Complete rewrite: 1493 → 310 lines |
| `apps/workbench/src/App.css` | Complete rewrite: 1350 → 285 lines |
| `apps/workbench/tsconfig.json` | Added `"types": ["vite/client"]` |

---

## What's Next

### Epic 4 remaining work (Visual Inspector):
1. Wire up the preview iframe correctly — make sure URL loads via `/preview?url=` proxy in browser mode
2. Test the full flow end-to-end: enter URL → click elements → generate test → copy code
3. Handle edge cases: non-interactive elements, SVG clicks, shadow DOM
4. Add "Clear" button behavior to also clear the iframe preview
5. Manual test gate for Epic 4

### Next epics in order
Epic 5 (POM Composer) → Epic 6 (Test Execution) → Epic 7 (Recorder) → Epic 8 (ML) → Epic 9 (TIA) → Epic 10 (Team)

---

## Key Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-14 | Always-on click over toggleable selection | One less mode = one less thing to understand. Every click either adds a step or flashes existing. |
| 2026-06-14 | No dialog for element addition | Click adds step instantly to right panel. No "Name Your Component" dialog, no COM code editor shown. |
| 2026-06-14 | Auto-inference over user specification | Names/actions inferred from element attributes/tag. Users can override inline. |
| 2026-06-14 | Generate modal over code panel | Generated code in dismissible overlay instead of permanent third panel — cleaner layout. |
| 2026-06-14 | Workbench lives in `testradius` dir | User prefers codebase at `~/github/chatgpt/testradius`; avoid confusion with `testsquad-testing/testsquad-v2`. |
| 2026-06-13 | Epic 2 shipped with 84 tests in a single session | Core engine proven: CLI works without UI, generates real Playwright COM/POM/test code |
| 2026-06-13 | Dockerize workbench deferred to after Epic 4 | Backend API still in flux; Electron frontend not containerizable; no benefit to containerizing yet |
| 2026-06-12 | Backend-first (Epic 2 before Epics 3-7) | Core engine is testable via CLI without UI; proves concept before building visual tools |
| 2026-06-12 | Separate `apps/workbench` dir from existing `ui/` | Clean separation: `ui/` is web dashboard, `apps/workbench/` is Electron IDE |
| 2026-06-12 | FastAPI backend + Electron/React frontend | Matches existing TestRadius architecture; Electron gives native browser control |
| 2026-06-12 | No LLM dependency | Deterministic templates + optional XGBoost; zero per-call API costs |
| 2026-06-12 | Manual test gate between epics | User verifies each epic before next one starts |

---

## Verification Commands

```bash
# Run backend tests
cd /Users/skaparwan/github/chatgpt/testradius/services/workbench
uv run pytest tests/ -v

# TypeScript check (no build needed)
cd /Users/skaparwan/github/chatgpt/testradius/apps/workbench
npx tsc --noEmit

# Build frontend
npm run build

# Start backend
uvicorn services.workbench.main:app --port 8000

# Check health
curl http://localhost:8000/health
```
