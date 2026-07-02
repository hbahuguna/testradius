# Story 2.8: Jinja2 Test Template

**Status**: Complete
**Epic**: 2 — COM Generation Engine
**Effort**: 2d

---

## Summary

Jinja2 template for pytest smoke/flow tests that verify POM components. Generates `test_page_loads` and `test_component_visibility` tests for every page, plus optional component interaction tests.

## Files Created

- `services/workbench/testsquad_workbench/generation/templates/test_template.j2` — Test Jinja2 template
- `docs/project/stories/02-com-engine/08-test-template.md` — This file

(Tested together with Story 2.7 — `test_template_engine_pom.py`)

## Generated Code Structure

```python
class TestLoginPage:
    def test_page_loads(self, page):
        pom = LoginPage(page)
        pom.navigate()
        assert pom.is_loaded()

    def test_component_visibility(self, page):
        pom = LoginPage(page)
        pom.navigate()
        assert pom.login_form.is_loaded()
        assert pom.navbar.is_loaded()
```

## Verification

```bash
uv run pytest tests/testsquad_workbench/generation/test_template_engine_pom.py -v
```

Expected: 7 passed
