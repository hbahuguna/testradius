# Story 2.4: Element Descriptor Mapping

**Status**: Complete
**Epic**: 2 — COM Generation Engine
**Effort**: 1d

---

## Summary

Maps classified elements to typed Python descriptor objects. Each component type produces a `ComponentDescriptor` with named fields corresponding to its child elements (e.g., LoginForm → username_input, password_input, submit_button).

## Files Created

- `services/workbench/testsquad_workbench/generation/descriptors.py` — `build_descriptor()`, `ComponentDescriptor`, `DescriptorField`
- `services/workbench/tests/testsquad_workbench/generation/test_descriptors.py` — 10 tests
- `docs/project/stories/02-com-engine/04-descriptors.md` — This file

## Field Naming

| Component Type | Field Names |
|---------------|-------------|
| LoginForm | username_input, password_input, submit_button, remember_me_checkbox |
| DataTable | header_cell[], row[] |
| NavBar | brand_link, nav_link[] |
| SearchBox | search_input, search_button |
| Modal | close_button, title |
| Card | image, title, body_text, action_button[] |
| Tabs | tab[], tab_panel[] |
| Alert | message, dismiss_button |
| Breadcrumb | breadcrumb_item[] |
| Pagination | next_button, prev_button, page_button[] |
| Sidebar | menu_item[] |
| FormGroup | label, <field_name>, submit_button |
| Dropdown | option[] |
| Accordion | accordion_header[], accordion_panel[] |
| Chart | (none - raw canvas/svg) |
| GenericComponent | (auto-named from child elements) |

## Key Decisions

- **`[]` suffix** on field names denotes `is_multiple=True` (renders as list locators)
- **Descriptors are data, not code** — they feed Jinja2 templates for actual code generation
- **Child element matching** uses tag name filtering per component type
- **Custom classification** can be injected via `build_descriptor(element, ClassificationResult(...))`

## Verification

```bash
uv run pytest tests/testsquad_workbench/generation/test_descriptors.py -v
```

Expected: 10 passed
