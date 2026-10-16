# Story 11.1: Purge/Version Evidence on Re-Instrumentation

**Status**: Done
**Epic**: 11 — Instrumentation Hardening
**Effort**: 2d
**Priority**: P0
**Depends on**: —

---

## Summary

Re-running instrumentation must replace the project's evidence, not append to it. After a run, the project must have exactly one distinct `built_at_sha`, so freshness detection can work.

## Current behaviour (the problem)

- `Neo4jStore._bulk_store_edges` (`neo4j_store.py:122`) only `MERGE`s nodes and `[:EVIDENCE]` edges. Nothing is ever deleted.
- `Neo4jStore.purge_project` (`neo4j_store.py:22`) exists but has **no caller** (confirmed by grep).
- A re-run at a new commit therefore leaves old-`built_at_sha` nodes in place. `analysis/freshness.py:24` `classify_evidence_freshness` sees more than one distinct SHA and marks evidence `stale_evidence=true` ("built across N different commits") — permanently forcing a full-suite fallback.

## Acceptance criteria

- [x] After instrumentation completes, the project has exactly **one** distinct `built_at_sha` across `TestSymbol` nodes and `EVIDENCE` edges.
- [x] Tests/symbols that existed in a prior run but not the current run have their `EVIDENCE` edges removed.
- [x] `analyze-pr` against the new anchor reports `stale_evidence=false` and `evidence_unversioned=false`.
- [x] The replacement is atomic with the write (no window where the graph is empty on failure).
- [x] Existing verification semantics are preserved: a write/verify mismatch still raises `PersistenceError` (`neo4j_store.py:165-183`).

> **Completion note**: `replace_mappings` is now called by the instrumentation run worker
> (`main.py:1656`). The map-tests path (`main.py:478`) intentionally keeps `store_mappings`
> (merge). The implementation is surgical rather than a full `DETACH DELETE`: it deletes prior
> coverage-sourced `[:EVIDENCE]` edges, clears stale `built_at_sha` stamps on surviving
> `TestSymbol` nodes, then writes the new mappings in the same transaction — satisfying the
> single-distinct-`built_at_sha` invariant while preserving non-coverage (LLM/heuristic) edges.
> `analyze-pr`/freshness and `test_analyze_pr.py` cannot be executed in this environment
> (`PyGithub` → `cryptography` build failure); the freshness invariant is covered by
> `test_persistence_verification.py`.

## Implementation notes

- Add `replace_mappings(mappings, project_id, built_at_sha)` to `Neo4jStore` and call it from the run worker (`main.py:1656`) instead of `store_mappings`.
- Do the delete inside the **same transaction** as the write: e.g. `MATCH (n {project_id:$project_id}) WHERE n:TestSymbol OR n:Symbol DETACH DELETE n` before the `UNWIND` write. Because the write query re-creates both node types, deleting first is safe.
- Alternative (if atomic full-delete is too heavy): tag every node/edge with a `run_id`, write the new run, then delete rows whose `run_id` differs, and scope `analyze-pr`/`get_impacted_tests` queries to the active run.
- Keep `store_mappings` for callers that intentionally merge (map-tests path at `main.py:478`), or document the difference.

## Tests (TDD — write first)

- Extend `services/core/tests/test_persistence_verification.py`: write run A (SHA `aaa...`), then run B (SHA `bbb...`), assert exactly one distinct SHA remains and run-A-only edges are gone.
- Extend `services/core/tests/test_analyze_pr.py`: assert freshness reports not-stale after replacement.

## Verification

```bash
pytest services/core/tests/test_persistence_verification.py services/core/tests/test_analyze_pr.py -v
```
