# Story 11.11: Remove Dead Instrumentation Code / Wire Remaining Paths

**Status**: Backlog
**Epic**: 11 — Instrumentation Hardening
**Effort**: 1d
**Priority**: P3
**Depends on**: —

---

## Summary

Remove or intentionally wire up the unused instrumentation modules so there is one implementation, not several drifting copies.

## Current behaviour (the problem)

Dead or unused code in the instrumentation area:

- `instrumentation/service.py` (`InstrumentationService`) — imported by `instrumentation/__init__.py`, not referenced by any route.
- `instrumentation/coverage_transformer.py` (`CoverageTransformer`, `TestSymbolStore`) — imported by `service.py`; `TestSymbolStore` uses the deprecated `[:COVERS]` relationship (`:336-348`).
- `instrumentation/transformer.py` (`InstrumentationTransformer`) — only used in tests.
- `instrumentation/plugin.py` (`PerTestCoveragePlugin`) — unused; has a duplicated `pytest_configure` (module-level `:87` and method `:21`) and a self-referential `pytest_plugins` (`:93`).
- `per_test_analyzer._find_coverage_db` (`:420`) — never called.
- The Vitest plugin (`packages/vitest-plugin`) is declared in config but unused (handled by 11.6).

## Acceptance criteria

- [ ] Unused modules/functions are deleted, or explicitly wired and covered by tests.
- [ ] `instrumentation/__init__.py` exports only what is used.
- [ ] `grep` finds no dangling imports of removed symbols; the test suite is green.
- [ ] `plugin.py`, if kept, no longer has the duplicate `pytest_configure` / self-referential `pytest_plugins`.
- [ ] Decide and document the fate of the Vitest plugin (wire in via 11.6, or delete).

## Implementation notes

- Confirm usage with `grep` before deleting each symbol; delete the module, its tests, and its exports together.
- Prefer deletion over keeping "legacy" code that duplicates the live `per_test_analyzer` + `Neo4jStore` path.

## Tests

- Remove tests that only exercise deleted code; do not weaken assertions on live paths.
- Full suite must stay green (see Verification).

## Verification

```bash
pytest services/core/tests/ -q
grep -rn "InstrumentationService\|CoverageTransformer\|InstrumentationTransformer\|_find_coverage_db" services/core --include=*.py
```
