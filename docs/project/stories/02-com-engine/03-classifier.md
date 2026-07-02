# Story 2.3: Heuristic Component Classifier

**Status**: Complete
**Epic**: 2 — COM Generation Engine
**Effort**: 3d

---

## Summary

Rule-based component classifier that identifies 16 component types from DOM element structure. Each rule checks tag name, attributes, ARIA roles, CSS classes, and child element patterns. Returns the highest-confidence match or `GenericComponent` as fallback.

## Files Created

- `services/workbench/testsquad_workbench/generation/classifier.py` — 16 classification rules + `classify()` function
- `services/workbench/tests/testsquad_workbench/generation/test_classifier.py` — 26 tests

## Component Types

| Type | Trigger | Confidence |
|------|---------|-----------|
| LoginForm | `<form>` with password input | 0.9 |
| DataTable | `<table>` / `role=grid` / class | 0.7-0.9 |
| NavBar | `<nav>` / class="nav*" | 0.7-0.9 |
| SearchBox | `input[type=search]` / aria-label | 0.7-0.9 |
| Modal | `role=dialog` / class="modal" | 0.7-0.9 |
| Card | `<article>` / class="card" | 0.6-0.8 |
| Tabs | `role=tablist` / class="tab" | 0.7-0.9 |
| Alert | `role=alert` / class="alert" | 0.7-0.9 |
| Breadcrumb | `nav[aria-label=breadcrumb]` / class | 0.8-0.95 |
| Pagination | `nav[aria-label=pagination]` / class | 0.8-0.95 |
| Sidebar | `<aside>` / class="sidebar" | 0.8-0.9 |
| FormGroup | `<fieldset>` / div with label+input | 0.7-0.8 |
| Dropdown | `<select>` / class="dropdown" | 0.7-0.9 |
| Accordion | `<details>` / class="accordion" | 0.8-0.9 |
| Chart | `<canvas>` / `<svg>` | 0.5-0.8 |
| GenericComponent | Fallback | 0.0 |

## Key Decisions

- **Rule order doesn't matter** — all rules run, highest confidence wins (priority via confidence, not ordering)
- **Pure heuristics** — no ML dependency; fast, deterministic, predictable
- **Class-based detection** uses substring match (e.g., `"nav" in classes`) for framework-agnostic coverage
- **GenericComponent** always returned as fallback when no rules match

## Verification

```bash
uv run pytest tests/testsquad_workbench/generation/test_classifier.py -v
```

Expected: 26 passed
