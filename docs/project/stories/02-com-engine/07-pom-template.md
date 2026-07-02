# Story 2.7: Jinja2 POM Template

**Status**: Complete
**Epic**: 2 — COM Generation Engine
**Effort**: 2d

---

## Summary

Jinja2 template for Page Object Model (POM) classes that compose multiple Component Object Models (COMs). Each POM class imports COMs, initializes them with scoped locators, and provides `navigate()` and `is_loaded()` methods.

## Files Created

- `services/workbench/testsquad_workbench/generation/templates/pom_template.j2` — POM Jinja2 template
- `services/workbench/tests/testsquad_workbench/generation/test_template_engine_pom.py` — 7 tests
- `docs/project/stories/02-com-engine/07-pom-template.md` — This file

## Generated Code Structure

```python
from playwright.sync_api import Page
from .LoginForm import LoginForm
from .NavBar import NavBar

class LoginPage:
    def __init__(self, page: Page):
        self.page = page
        self.login_form = LoginForm(page, page.locator("[data-testid='login-form']"))
        self.navbar = NavBar(page, page.locator("nav"))

    def navigate(self):
        self.page.goto("https://example.com/login")

    def is_loaded(self):
        return all(comp.is_loaded() for comp in [self.login_form, self.navbar])
```

## Verification

```bash
uv run pytest tests/testsquad_workbench/generation/test_template_engine_pom.py -v
```

Expected: 7 passed
