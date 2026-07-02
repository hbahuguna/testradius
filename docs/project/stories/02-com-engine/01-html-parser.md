# Story 2.1: HTML Parser

**Status**: Complete
**Epic**: 2 — COM Generation Engine
**Effort**: 2d

---

## Summary

BeautifulSoup wrapper that extracts structured element information from HTML. The parser handles element metadata extraction, CSS path generation, XPath generation, visibility detection, and interactive element identification.

## Files Created

- `services/workbench/testsquad_workbench/generation/__init__.py` — Package init
- `services/workbench/testsquad_workbench/generation/models.py` — `ElementInfo` and `DOMTree` dataclasses
- `services/workbench/testsquad_workbench/generation/html_parser.py` — Parser: `parse_html()`, `get_element_by_css()`, `_compute_css_path()`, `_compute_xpath()`, `_extract_element_info()`
- `services/workbench/tests/testsquad_workbench/generation/__init__.py` — Test package init
- `services/workbench/tests/testsquad_workbench/generation/test_html_parser.py` — 12 tests

## Key Decisions

- **lxml** parser chosen for speed (vs html.parser or html5lib)
- **CSS selector paths** built from parent chain: `body > div.container > form#login`
- **XPath** built from parent chain with sibling indexing for duplicates
- **Visibility**: checks `style="display:none"`, `style="visibility:hidden"`, and `hidden` attribute
- **Interactivity**: detected via tag name (`button`, `a`, `input`, `select`, etc.) or ARIA `role`
- **Element indexing**: by computed CSS path stored in `elements_by_selector` dict

## Verification

```bash
uv run pytest tests/testsquad_workbench/generation/test_html_parser.py -v
```

Expected: 12 passed
