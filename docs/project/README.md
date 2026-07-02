# TestRadius Workbench — Project Management Framework

**Methodology**: Kanban + TDD + Manual Gate

## Workflow

```
Backlog → Ready → In Progress → Review → [GATE: Manual Test] → Done
                                            ↑
                                     You execute test plan
                                     before epic is Done
```

### Rules
1. **One task at a time** — only one task in `In Progress`
2. **TDD** — write test first (fails), then code (passes), then refactor
3. **Manual gate** — you execute the epic's test plan before it's marked Done
4. **Each task = one commit** — no partial or WIP commits
5. **All code has automated tests** — pytest for backend, Playwright for frontend

## Document Structure

```
docs/project/
├── README.md          ← This file
├── kanban.md          ← Current kanban state
├── epics/             ← One file per epic
├── stories/           ← Stories grouped by epic-#
├── tasks/             ← Individual tasks
└── test-plans/        ← Manual test plans, one per epic
```

## Epic Structure

Each epic file contains:
- **Theme** — what this epic delivers
- **Stories** — numbered user-valuable features
- **Acceptance criteria** — what must be true for Done
- **Dependencies** — what this depends on

## TDD Workflow Per Task

```
1. Write automated test(s)          → Test FAILS (red)
2. Write production code            → Test PASSES (green)
3. Refactor if needed               → Tests still PASS
4. Commit
```

## Testing Layers

| Layer | Tool | Owner |
|-------|------|-------|
| Backend unit tests | pytest | Automated (CI) |
| Backend integration | pytest + httpx | Automated (CI) |
| Frontend component | Playwright CT | Automated (CI) |
| Frontend E2E | Playwright | Automated (CI) |
| Manual acceptance | Epic test plan | **You** (gate) |
