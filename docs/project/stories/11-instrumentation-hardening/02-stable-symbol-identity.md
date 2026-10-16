# Story 11.2: Stable Symbol Identity (Qualify Names + Line Span)

**Status**: Done
**Epic**: 11 — Instrumentation Hardening
**Effort**: 2d
**Priority**: P0
**Depends on**: —

---

## Summary

A code symbol must map to exactly one `Symbol` node. Today, symbols with the same bare name in the same file collapse into one node, mixing the evidence of unrelated code.

## Current behaviour (the problem)

- Methods are collected with a bare name and no class qualifier: `symbol_resolver.py:129` (`FunctionDef`, `name=child.name`) and `:139` (`AsyncFunctionDef`). `AsyncFunctionDef` is also typed `"function"`, so `async` is not distinguished.
- `Symbol` nodes are keyed `(name, file_path, project_id)` and the dedup key (`neo4j_store.py:115`) is `(test_name, test_file, symbol_name, symbol_file)` — the line span is **not** part of either key.
- Result: `ClassA.get` and `ClassB.get` in one file become one `Symbol`. `get_impacted_tests` matches `s.name IN $changed_symbols` (`neo4j_store.py:198`), so the collision propagates into test selection — one class's coverage over-selects for the other.

## Acceptance criteria

- [x] Symbols carry a qualified identity. **Design decision (see below):** the resolver
  (`symbol_resolver.py`) deliberately keeps the **bare** name; the module-qualified identity
  (`src.c.get`) is composed by `instrumentation/diff_parser._qualified_name(file, name)` and
  same-name methods are told apart by **line span**. This is required by the existing, seeded
  `test_innermost_symbols.py` (asserts bare names) and `test_diff_parser_qualified.py`
  (asserts `qualified_name == "src.c.get"` from a bare-name resolver). Qualifying inside the
  resolver would double-qualify (`src.c.src.c.get`) and regress G1 attribution.
- [x] `Symbol` node identity and the `EVIDENCE` dedup key both include the line span (`start_line`, `end_line`).
- [x] `ClassA.get` and `ClassB.get` resolve to distinct nodes with distinct evidence.
- [x] `analyze-pr` selects the correct tests when only one of the two same-named methods changes
  (span-aware matching in `instrumentation/diff_parser`, G2).
- [x] A graph reset/migration step is documented (see "Graph reset" below).
- [x] Optional: distinguish `async` functions (`symbol_type="async_function"`).

## Implementation notes

- `symbol_resolver.py:_collect_symbols`: collects bare names (no class prefix) and keeps the
  innermost-symbol attribution (smallest enclosing span wins) that G1 relies on.
  `AsyncFunctionDef` is typed `async_function`.
- `neo4j_store.py`: `start_line`/`end_line` added to the `Symbol` `MERGE` keys, to
  `_distinct_edges`, and to both the write and verify queries in `_bulk_store_edges` **and**
  `replace_mappings`.
- `get_impacted_tests` still matches by name (its endpoint takes a comma-separated name list);
  span-accurate selection is provided by the analyze-pr path through `diff_parser`.
- `diff_parser.py` symbol matching already matches on `(file, name, start_line, end_line)` with
  a `(file, name)` fallback, so no change was required beyond confirming the identity scheme.

## Graph reset

Existing `Symbol` nodes created before this change were keyed without a line span, so collapsed
nodes (e.g. one `get` for two classes) must be rebuilt. No offline migration is required:
`Neo4jStore.replace_mappings()` (Story 11.1) deletes prior coverage `[:EVIDENCE]` edges and the
next instrumentation run re-`MERGE`s `Symbol` nodes with the new span-bearing key. Operational
step: after deploying, trigger a fresh instrumentation run for each project (or invoke the
instrumentation endpoint with `x-run-fresh: true`). Non-coverage edges are preserved.

## Tests (TDD — write first)

- `services/core/tests/test_symbol_identity.py` — same-named methods in different classes resolve
  to two distinct `Symbol` objects (distinct spans) and two store edges; the `Symbol` `MERGE`
  query carries the span in both write paths.
- `services/core/tests/test_neo4j_store.py` — `test_same_named_methods_in_one_file_yield_two_edges`,
  `test_symbol_node_identity_includes_line_span`.
- `test_analyze_pr.py` (changed `ClassB.get` does not select `ClassA.get` tests) — **not runnable in
  this environment** (`PyGithub` → `cryptography` cannot build); covered indirectly by
  `test_diff_parser_qualified.py`.

## Verification

```bash
# Runnable in this environment (path-loaded; no native deps):
PYTHONPATH="services/core:packages/shared" python3.10 -m pytest \
  services/core/tests/test_symbol_identity.py \
  services/core/tests/test_neo4j_store.py \
  services/core/tests/test_innermost_symbols.py \
  services/core/tests/test_diff_parser_qualified.py \
  services/core/tests/test_symbol_resolver.py \
  --override-ini='addopts=' --noconftest -v
```
