# Story 11.7: Confidence Gradation + Coverage Metadata

**Status**: Done
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

- [x] Each `EVIDENCE` edge stores `covered_line_count` and `coverage_kind` (`line` / `branch` / `inferred`).
- [x] `confidence` is computed from a documented formula (e.g. fraction of the symbol's lines covered, penalized when attribution is `inferred`).
- [x] Re-runs update `confidence` and metadata instead of leaving the first value (fix the `MERGE` to `SET` on match).
- [x] TIA scoring/ranking consumes confidence where it currently assumes `1.0`.
- [x] `get_impacted_tests` (`neo4j_store.py:186`) returns the refined confidence.

## Implementation notes

- Thread covered-line counts from `per_test_analyzer.resolve_to_symbols` (`:584`) and both resolvers into the mapping dicts consumed by `neo4j_store._build_edges` (`:79`).
- Extend the write query (`neo4j_store.py:131`) to store the new props and to `SET` `confidence`/`covered_line_count`/`coverage_kind` on existing edges.
- Document the confidence formula in this story and in the runbook.

## Tests (TDD — write first)

- Extend `services/core/tests/test_neo4j_store.py` — a partially-covered symbol yields confidence < 1.0; a re-run updates confidence.
- Extend `test_persistence_verification.py` — metadata round-trips.

## Verification

```bash
pytest services/core/tests/test_confidence_gradation.py -v
pytest services/core/tests/test_neo4j_store.py services/core/tests/test_persistence_verification.py -v
```

---

## Done — implementation notes

### The formula (one home: `instrumentation/confidence.py`)

```
span       = max(1, end_line - start_line + 1)
ratio      = clamp(covered_line_count / span, 0, 1)
weight     = 0.5 when coverage_kind == "inferred" else 1.0
confidence = round(ratio * weight, 4)
```

`coverage_kind`:

| kind | meaning |
| --- | --- |
| `line` | the symbol's own lines were covered — a function/method attributed directly |
| `branch` | branch/arc coverage established the symbol — **reserved**: the Python extractor emits line coverage only, so nothing produces it yet (noted under Limitations) |
| `inferred` | indirect attribution — today, a **class** credited through a line in its body that sits outside every nested definition |

A class is discounted because such a line is evidence *about the class* (an attribute, a decorator, the class statement) rather than a measured callable entry point. `INFERRED_WEIGHT = 0.5` — one fixed, documented factor, not a guess per call site.

A `None` count means "no coverage metadata was recorded" (a pre-11.7 caller, or a symbol straight out of `get_symbols`): it widens to the whole span, i.e. confidence 1.0, so every legacy caller and every already-written edge keeps its old behaviour.

### Threading the counts

`attribution.attributed_line_counts()` counts covered lines per owned symbol;
`select_innermost_owners()` is now defined **in terms of it**, so the selection
rule and the per-symbol counts can never drift apart. Both resolvers'
`resolve_symbols` return `dataclasses.replace` copies carrying
`covered_line_count` + `coverage_kind` (copies so the per-file parse cache is
never mutated across the many tests that resolve the same file). The mapping
tuples grew from 5 to 7 elements — `(name, type, start, end, file, covered,
kind)` — and `neo4j_store._build_edges` accepts 5- or 7-tuples and `Symbol`
objects, computing `confidence` from whatever metadata it finds.

### The write queries (AC3)

`confidence` was part of the MERGE pattern (`MERGE (t)-[ev:EVIDENCE {source: 'coverage', confidence: 1.0}]->(s)`), so a re-run with a different confidence would have **created a second edge** pinned to the first value rather than updating. All three write queries (`replace_mappings`, `apply_incremental_mappings`, `_bulk_store_edges`) now merge on `source` only and `SET ev.confidence / ev.covered_line_count / ev.coverage_kind` on match.

### AC4 — ranking consumes confidence (two fixes)

1. `analysis/calibrators.py`: `"coverage": lambda x: 0.99` **ignored its input** — every coverage edge fused at a constant 0.99 no matter what the edge said. Now `_coverage_scale(x) = 0.5 + 0.49 * clamp(x, 0, 1)`: a fully-evidenced edge keeps the historical 0.99, a weak one slides to the 0.5 floor (still ≥ 0.5 — the edge *was* executed).
2. **Gate-found defect**: `analysis/diff_parser._query_evidence` and `_query_call_graph_evidence` read `(Symbol)-[:EVIDENCE]->(TestSymbol)` — the **reverse** of what every writer (`neo4j_store`, `graph/client.py:664,715`) writes. The ranking path had therefore never seen a single coverage edge: `/analyze-impact` returned an empty list for real instrumented projects. Both queries now read `(t:TestSymbol)-[e:EVIDENCE]->(s:Symbol)`, scoped to the project, and carry the edge metadata into `Evidence.metadata`.

### AC5 — the impact endpoint

`GET /projects/{id}/instrumentation/impact` used the deprecated
`TestSymbolStore`, whose query reads `[:COVERS]` (written by nothing) and
hardcodes `1.0 as confidence` — it always returned an empty list. It now uses
`Neo4jStore.get_impacted_tests`, which returns the refined `confidence` plus
`covered_line_count`/`coverage_kind`, ordered by confidence DESC. (The
deprecated `TestSymbolStore` itself is Story 11.11's cleanup.)

## Tests

`services/core/tests/test_confidence_gradation.py` (new, 25) — pure logic, no
FastAPI/Neo4j driver needed: the formula (full/partial/inferred/legacy/clamped),
`kind_for_symbol`, per-owner line counts (incl. innermost class/method split),
cache non-mutation, `_build_edges` metadata for 5/7-tuples and objects, metadata
excluded from the edge identity, the three write queries' SET contract, the
re-run-updates parameter flow, `get_impacted_tests` metadata + ordering, and the
calibrator's new scaling (incl. a null-confidence legacy edge).

`test_neo4j_store.py` (+2, 1 updated) and `test_persistence_verification.py`
(+2, 1 updated) — as the story's TDD notes asked: partial coverage < 1.0,
re-run sends fresh confidence, metadata round-trips through the transaction,
and the write-query contract asserts `SET ev.confidence` instead of the pinned
`confidence: 1.0`.

`test_impact_api.py` (+2) — the edge-direction regression tests for the
gate-found defect.

`test_scorer.py` (1 updated) — the coverage calibrator now scales with its
input; also aligned a pre-existing stale test
(`test_unknown_source_returns_prior` expected the prior but the fallback is
`x * 0.5` — it failed on a clean tree before this story).

## Verification — manual gate (live backend, 2026-10-16)

Synthetic testbeds against the running `core-ml` container. Neo4j read directly
via `cypher-shell`.

| Check | Result |
| --- | --- |
| TS edges carry metadata (AC1) | project 8 (`gate-ts`, 72 edges): `48 × line/1.0`, `12 × line/0.25`, `12 × inferred/0.136` — before 11.7 all 72 were `1.0` with no metadata |
| Formula holds on real data (AC2) | `Calc` (class, lines 13–23): span 11, covered 3 → 3/11 × 0.5 = **0.136** ✓; Python `add`: 1/2 → 0.5; `squeeze`: 3/4 → 0.75 |
| Re-run updates confidence (AC3) | corrupted all 10 project-10 edges to `confidence=0.123, covered=99, kind='corrupt'`, re-ran → **0 stale values left**, kinds `["line"]`, distinct confidences `[0.5, 0.75]` |
| Carried-forward evidence keeps metadata | no-change incremental run (`0 of 6 scheduled, 6 carried forward`) → 10 edges, 0 null confidence/kind, confidences `[0.5, 0.75]`, still 1 distinct `built_at_sha` (11.1 invariant intact) |
| Ranking prefers strong evidence (AC4) | `POST /projects/10/analyze-impact` with a diff touching `squeeze` + `kebab` → `test_squeeze` **0.8675** ranks above `test_kebab` **0.7450** — exactly `0.5 + 0.49 × edge_confidence`. Before 11.7 the same request returned **no tests at all** (reversed edge direction) |
| `get_impacted_tests` returns refined confidence (AC5) | `GET /projects/8/instrumentation/impact?symbols=Calc,add` → 24 rows: the 12 `add` edges (1.0, `line`) ordered before the 12 `Calc` edges (0.1364, `inferred`), each row carrying `covered_line_count` + `coverage_kind`. Before: an empty list |
| 11.8 regression | both coverage endpoints still `100.0%, not_reported=false, low_coverage=false` |

## Deviations from the story's implementation notes

1. **`branch` is reserved, not produced.** The Python extractor
   (`extract_per_test_lines`) reads the coverage DB's `line_bits` only; arcs are
   not extracted, so no edge is tagged `branch` yet. The kind exists in the
   schema and the formula so adding arc extraction later is a drop-in.
2. **A second defect was fixed under AC4** (the reversed EVIDENCE direction in
   `analysis/diff_parser`) — without it "ranking consumes confidence" was
   untestable, because ranking saw no evidence at all.
3. **The impact endpoint was rewired** from the deprecated `TestSymbolStore`
   (always-empty `[:COVERS]` read, hardcoded `1.0`) to `Neo4jStore` — AC5's
   consumer.
4. **A pre-existing stale test was repaired**
   (`test_unknown_source_returns_prior`), found failing on a clean tree while
   running this story's regression sweep.

## Limitations / follow-ups

- `branch` coverage kind is not produced yet (see Deviation 1).
- The span denominator counts every line in the symbol's span, including blank
  lines and comments, so a function with interior blank lines rarely reaches
  1.0. That is honest ("we saw 3 of its 11 lines exercised") but a
  non-blank-line denominator would be tighter if it ever matters for ranking.
- `TestSymbolStore` (`coverage_transformer.py`) still pins
  `confidence: 1.0` on its `[:COVERS]` write — deprecated, unread, and slated
  for removal in Story 11.11.
- Full signatures are still computed by the Python resolver and not persisted
  (the story listed them under "not persisted"; persisting them is not required
  by any AC here — left for a future story if a consumer appears).
