# Story 2.2: Selector Strategy Engine

**Status**: Complete
**Epic**: 2 — COM Generation Engine
**Effort**: 2d

---

## Summary

Multi-strategy selector generator for Playwright locators. Given an `ElementInfo`, produces prioritized selector candidates: `data-testid` > `aria-label` > `role+text` > `id` > CSS path > XPath. The `pick_best_selector()` function returns the highest priority unique selector.

## Files Created

- `services/workbench/testsquad_workbench/generation/selector_strategy.py` — `generate_selectors()`, `pick_best_selector()`
- `services/workbench/tests/testsquad_workbench/generation/test_selector_strategy.py` — 9 tests

## Selector Priority

1. `data-testid` / `data-test-id` / `data-test` / `data-cy` attribute
2. `aria-label` attribute
3. ARIA `role` + visible text name
4. Plain text match (`text=...`)
5. CSS `#id` selector
6. Full CSS path
7. XPath expression

## Key Decisions

- **Best selector = highest priority that is unique** (if `all_elements` provided)
- **Sanitized text values**: non-alphanumeric characters stripped for safe selectors
- **Multiple test-id attrs handled**: `data-testid`, `data-test-id`, `data-test`, `data-cy` checked in order

## Verification

```bash
uv run pytest tests/testsquad_workbench/generation/test_selector_strategy.py -v
```

Expected: 9 passed
