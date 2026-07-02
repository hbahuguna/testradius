# Story 2.6: CLI — `testradius com-gen`

**Status**: Complete
**Epic**: 2 — COM Generation Engine
**Effort**: 1d

---

## Summary

Command-line interface for the COM generation pipeline. `testradius com-gen <url> <selector>` fetches a page, parses it, classifies the target element, and renders a Python COM class.

## Files Created

- `services/workbench/testsquad_workbench/generation/cli.py` — `main()`, `com_gen()`, `build_parser()`
- `services/workbench/testsquad_workbench/generation/page_fetcher.py` — `fetch_page_html()` (Playwright or file://)
- `services/workbench/tests/testsquad_workbench/generation/test_cli.py` — 8 tests
- `docs/project/stories/02-com-engine/06-cli-com-gen.md` — This file

## Usage

```bash
# From a local HTML file
python -m testsquad_workbench.generation.cli com-gen file:///path/to/page.html "form#login"

# With Playwright (fetches live page)
testradius com-gen https://example.com "form[data-testid='login']" -o login_com.py
```

## Key Decisions

- **`file://` prefix** for local HTML files (no Playwright needed)
- **argparse** (stdlib) instead of Click for zero-dependency CLI
- **Playwright lazy-loaded** — import error raised only when actually fetching from HTTP(S)

## Verification

```bash
uv run pytest tests/testsquad_workbench/generation/test_cli.py -v
```

Expected: 8 passed
