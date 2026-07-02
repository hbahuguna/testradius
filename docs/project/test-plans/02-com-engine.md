# Epic 2: COM Generation Engine — Manual Test Plan

---

## Prerequisites

- [ ] `cd /Users/skaparwan/github/chatgpt/testradius`
- [ ] `uv sync` in `services/workbench/` completed
- [ ] `playwright install chromium` done (for live URL fetching)

---

## 1. Unit Tests

- [ ] `uv run pytest services/workbench/tests/ -v` — all 84 pass (0 failures)

## 2. CLI: `com-gen` with Local HTML

Create a temp test file:
```bash
cat > /tmp/test-page.html << 'EOF'
<!DOCTYPE html>
<html>
<body>
  <form id="login" data-testid="login-form">
    <input type="email" name="email" placeholder="Email" />
    <input type="password" name="password" />
    <button type="submit">Sign In</button>
  </form>
</body>
</html>
EOF
```

- [ ] Run: `uv run python -m testsquad_workbench.generation.cli com-gen file:///tmp/test-page.html "form#login"`
- [ ] Output includes: `class LoginForm:`
- [ ] Output includes: `username_input`, `password_input`, `submit_button` properties
- [ ] Output includes: `is_loaded()` method
- [ ] Output includes: Playwright `Locator` type hints

## 3. CLI: `com-gen` Output File

- [ ] Run: `uv run python -m testsquad_workbench.generation.cli com-gen file:///tmp/test-page.html "form#login" -o /tmp/login_com.py`
- [ ] `/tmp/login_com.py` exists and is valid Python

## 4. CLI: `generate` Full Suite

- [ ] Run: `uv run python -m testsquad_workbench.generation.cli generate file:///tmp/test-page.html -o /tmp/ -n LoginSuite`
- [ ] Output says: `Generated N files in /tmp/LoginSuite/`
- [ ] `/tmp/LoginSuite/LoginSuite.py` exists (POM)
- [ ] `/tmp/LoginSuite/test_LoginSuite.py` exists (tests)
- [ ] `/tmp/LoginSuite/LoginForm.py` exists (COM)

## 5. Generated Code Quality

- [ ] `/tmp/LoginSuite/LoginForm.py` has valid Python syntax: `uv run python -c "import ast; ast.parse(open('/tmp/LoginSuite/LoginForm.py').read()); print('OK')"`
- [ ] `/tmp/LoginSuite/LoginSuite.py` has valid Python syntax: `uv run python -c "import ast; ast.parse(open('/tmp/LoginSuite/LoginSuite.py').read()); print('OK')"`

## 6. Component Classifier Sanity

- [ ] Run: `uv run python -c "from testsquad_workbench.generation.html_parser import parse_html; from testsquad_workbench.generation.classifier import classify; t=parse_html(open('/tmp/test-page.html').read()); e=t.elements_by_selector.get('body > form'); print(classify(e))"`
- [ ] Prints: `ClassificationResult(component_type='LoginForm', ...)`

---

## Result

- [ ] **All pass** — Epic 2 Done, proceed to Epic 3
- [ ] **Some failed** — report issues to fix
