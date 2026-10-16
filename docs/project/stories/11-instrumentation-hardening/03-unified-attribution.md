# Story 11.3: Unified Innermost Attribution + Language-Based Dispatch

**Status**: Done
**Epic**: 11 — Instrumentation Hardening
**Effort**: 2d
**Priority**: P0
**Depends on**: 11.2

---

## Summary

Python and TypeScript must credit a covered line to the **same** symbol: the innermost enclosing definition. The diff analyzer must also use the resolver that matches the file's language.

## Current behaviour (the problem)

- Python uses *innermost* attribution (`symbol_resolver.py:67-79`: smallest enclosing span wins), so a line in a method credits the method only.
- TypeScript uses *overlap* (`typescript_symbol_resolver.py:60-66`): any symbol whose `[start, end]` intersects the covered lines is returned, so a line inside a method credits **both the method and its enclosing class**. Evidence is inflated.
- `DiffParser.resolve_impacted_tests` (`diff_parser.py:187`) defaults to a **TypeScriptSymbolResolver** (`diff_parser.py:193-195`) even for Python analyses — a Python diff is parsed as TS/JS.

## Acceptance criteria

- [x] TypeScript attribution is innermost (a method hit does not also credit its class).
- [x] Equivalent constructs in Python and TypeScript produce equivalent attribution in a shared fixture test.
- [x] `DiffParser` selects the resolver by file extension (`.py` → Python AST; `.ts/.tsx/.js/.jsx` → tree-sitter), and accepts an injected resolver for tests.
- [x] No regression in existing `test_instrumentation.py` / coverage integration tests.

## Implementation notes

- **Shared helper.** New `instrumentation/attribution.py` exports
  `select_innermost_owners(symbols, covered_lines)` — the innermost-owner selection
  (smallest enclosing span wins, each symbol emitted once, original order kept).
  Both `SymbolResolver.resolve_symbols` (Python) and
  `TypeScriptSymbolResolver.resolve_symbols` (TypeScript) now delegate to it, so the
  two languages cannot drift.
  - `symbol_resolver.py` also carries a defensive import: it is loaded by path as a
    standalone module by `test_innermost_symbols.py`, where a relative import has no
    parent package. The `except ImportError` branch loads the sibling `attribution.py`
    by file path.
- **TypeScript parser construction fixed.** `TypeScriptSymbolResolver._get_parser`
  used the pre-0.22 API (`Language(ptr, name)` + `parser.set_language(...)`), which
  raises `TypeError`/`AttributeError` on modern tree-sitter (`uv.lock` resolves 0.25.2,
  this environment has 0.26) — the TS resolver parsed nothing and logged a warning.
  It now tries the old form and falls back to `Language(ptr)` / `Parser(lang)`, matching
  `graph/resolvers/python.py`. Attribution could not be exercised until this was fixed.
- **`SymbolResolver.get_symbols`.** The diff analyzer needs *every* symbol in a file
  (it decides which changed from the hunk), not a coverage-filtered subset — so the
  Python resolver gained the public `get_symbols` the TS resolver already had.
- **Language dispatch.** `diff_parser.select_resolver(file_path)` is the per-path
  factory (`.py`/`.pyi` → `SymbolResolver`, everything else → `TypeScriptSymbolResolver`),
  and `_LanguageDispatchResolver` caches one instance per language and proxies
  `get_symbols`. `resolve_impacted_tests` uses it as the default, so the two existing
  callers in `main.py` (`:1215`, `:1808`) — which pass no resolver — now parse Python
  with Python. An injected `resolver=` still takes precedence (all `test_diff_parser_qualified`
  tests inject a fake).
- **Not in scope.** `per_test_analyzer.resolve_to_symbols` still constructs a Python
  `SymbolResolver()` for every covered file; it is the Python-only pipeline
  (`typescript_pipeline.py` / `playwright_pipeline.py` handle TS separately).
  Flag as a candidate follow-up if a combined analyzer is ever needed.

## Tests (TDD — write first)

- New `services/core/tests/test_resolver_parity.py` (5 tests):
  - `test_typescript_method_hit_does_not_credit_class` — TS line in `add` → `["add"]`.
  - `test_typescript_class_body_hit_credits_class` — TS class-body-only line → `["Calculator"]`.
  - `test_python_and_typescript_attribution_match` — same expectations for Python
    (lines 4/3) and TypeScript (lines 5/3) on equivalent `Calculator` sources.
  - `test_select_resolver_by_extension` — factory returns the right class per extension.
  - `test_python_diff_uses_python_resolver_end_to_end` — `resolve_impacted_tests` with
    **no** injected resolver on a `.py` diff resolves `add` (fails under the old
    hardcoded TS default).
- No regression: `test_innermost_symbols.py` (G1), `test_diff_parser_qualified.py` (G2),
  `test_symbol_resolver.py`, `test_per_test_coverage_integration.py`,
  `test_coverage_sharding.py`, `test_test_discovery.py` all still pass — no existing
  test asserts the old TypeScript overlap behaviour.

## Verification

```bash
# Runnable in this environment (tree-sitter + tree_sitter_{python,javascript,typescript}):
PYTHONPATH="services/core:packages/shared" python3.10 -m pytest \
  services/core/tests/test_resolver_parity.py \
  services/core/tests/test_innermost_symbols.py \
  services/core/tests/test_diff_parser_qualified.py \
  services/core/tests/test_symbol_resolver.py \
  services/core/tests/test_per_test_coverage_integration.py \
  --override-ini='addopts=' --noconftest -v
```

`python scripts/_root_scripts/test_instrumentation.py` could not be run here: it needs
`PyGithub`, whose `cryptography` dependency does not build in this environment.
