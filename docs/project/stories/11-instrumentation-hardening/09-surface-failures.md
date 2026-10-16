# Story 11.9: Surface Install/Collection Failures as Structured Reasons

**Status**: Backlog
**Epic**: 11 — Instrumentation Hardening
**Effort**: 1d
**Priority**: P2
**Depends on**: —

---

## Summary

When a test file yields no evidence, the run must say **why** (missing dependency, collection error, skipped, timeout) instead of only listing the filename.

## Current behaviour (the problem)

- `_install_test_deps` (`per_test_analyzer.py:153`) swallows `pip` failures with a warning (`:170-209`).
- `_collect_one` returns `None` on any exception (`:222`).
- `_coverage_completeness` (`:637`) reports `missing_test_files` as paths only — no reason. A run can look "complete" while silently missing evidence.

## Acceptance criteria

- [ ] Each entry in `missing_test_files` includes a `reason` (`dependency_missing` / `collection_error` / `skipped` / `timeout` / `no_context`).
- [ ] Install failures are either fatal or recorded as a structured run error — never silently ignored.
- [ ] Skipped tests are labelled `skipped` (documented as expected, not a gap) rather than appearing as ordinary misses.
- [ ] The coverage API payload exposes reasons without breaking existing consumers.
- [ ] The zero-edge guard (`main.py:1657-1661`) still fails runs that persist no evidence.

## Implementation notes

- Capture stderr from `pip install` and from the pytest shard runs (`_run_coverage_shard`, `:279`) and classify it.
- Change `missing_test_files` from `List[str]` to a list of objects `{file, reason}` (keep a flat list of names for backward compatibility, e.g. add `missing_test_files_detailed`).
- Note: `store_mappings` returns `0` for an empty mapping set (`neo4j_store.py:73`), which the route currently turns into an ERROR — decide and document the intended behaviour for a legitimately empty suite.

## Tests (TDD — write first)

- Extend `services/core/tests/test_instrumentation_coverage_api.py` — a missing-dependency file reports `reason=dependency_missing`.
- Add a classification unit test for install/collection error strings.

## Verification

```bash
pytest services/core/tests/test_instrumentation_coverage_api.py -v
```
