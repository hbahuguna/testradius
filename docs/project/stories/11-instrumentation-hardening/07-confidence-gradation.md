# Story 11.7: Confidence Gradation + Coverage Metadata

**Status**: Backlog
**Epic**: 11 — Instrumentation Hardening
**Effort**: 2d
**Priority**: P2
**Depends on**: 11.2

---

## Summary

`[:EVIDENCE]` edges must carry a real confidence score and coverage metadata, so ranking can prefer strong evidence over weak evidence.

## Current behaviour (the problem)

- Every edge is written with `confidence: 1.0` and `source: 'coverage'` (`neo4j_store.py:147`) — a constant. `confidence` is also not part of the `MERGE` key and is never updated on re-merge.
- No coverage metadata is stored (covered-line count, line vs branch, whether attribution came from a class span). Full signatures are computed (`symbol_resolver._get_function_signature`, `:161`) but not persisted.

## Acceptance criteria

- [ ] Each `EVIDENCE` edge stores `covered_line_count` and `coverage_kind` (`line` / `branch` / `inferred`).
- [ ] `confidence` is computed from a documented formula (e.g. fraction of the symbol's lines covered, penalized when attribution is `inferred`).
- [ ] Re-runs update `confidence` and metadata instead of leaving the first value (fix the `MERGE` to `SET` on match).
- [ ] TIA scoring/ranking consumes confidence where it currently assumes `1.0`.
- [ ] `get_impacted_tests` (`neo4j_store.py:186`) returns the refined confidence.

## Implementation notes

- Thread covered-line counts from `per_test_analyzer.resolve_to_symbols` (`:584`) and both resolvers into the mapping dicts consumed by `neo4j_store._build_edges` (`:79`).
- Extend the write query (`neo4j_store.py:131`) to store the new props and to `SET` `confidence`/`covered_line_count`/`coverage_kind` on existing edges.
- Document the confidence formula in this story and in the runbook.

## Tests (TDD — write first)

- Extend `services/core/tests/test_neo4j_store.py` — a partially-covered symbol yields confidence < 1.0; a re-run updates confidence.
- Extend `test_persistence_verification.py` — metadata round-trips.

## Verification

```bash
pytest services/core/tests/test_neo4j_store.py services/core/tests/test_persistence_verification.py -v
```
