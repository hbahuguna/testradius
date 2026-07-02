# Epic 5: POM Composer + Test Generation — Manual Test Plan

---

## Prerequisites

- [ ] `cd /Users/skaparwan/github/chatgpt/testradius`
- [ ] Ensure test fixture exists:
```bash
cat > /tmp/test-page.html << 'EOF'
<!DOCTYPE html>
<html>
<head><title>Login Page</title></head>
<body>
  <nav><a href="/">Home</a><a href="/about">About</a></nav>
  <form id="login" data-testid="login-form">
    <input type="email" name="email" placeholder="Email" />
    <input type="password" name="password" />
    <button type="submit">Sign In</button>
  </form>
  <aside class="sidebar">
    <ul><li>Dashboard</li><li>Settings</li></ul>
  </aside>
</body>
</html>
EOF
```
- [ ] Terminal 1 — backend: `cd services/workbench && uv run uvicorn testsquad_workbench.main:app --port 8000 --reload`
- [ ] Terminal 2 — frontend: `cd apps/workbench && npm run dev`

---

## A. Regression: Unit Tests

- [ ] `cd services/workbench && uv run pytest -v` — **all 101 pass**

---

## B. Regression: Existing API Endpoints (Epics 2-4)

- [ ] `curl http://localhost:8000/health` → `{"status":"ok"}`
- [ ] `curl -X POST http://localhost:8000/analyze -H "Content-Type: application/json" -d '{"url":"file:///tmp/test-page.html"}'` → JSON with `title: "Login Page"`
- [ ] `curl -X POST http://localhost:8000/com-gen -H "Content-Type: application/json" -d '{"url":"file:///tmp/test-page.html","selector":"form#login"}'` → `LoginForm` with valid Python code
- [ ] `curl -X POST http://localhost:8000/components -H "Content-Type: application/json" -d '{"url":"file:///tmp/test-page.html"}'` → includes `NavBar`, `LoginForm`, `Sidebar`

---

## C. Story 5.1 — Multi-Component Selection

- [ ] Open `http://localhost:5173`
- [ ] Enter `file:///tmp/test-page.html`, click **Go**
- [ ] Component sidebar (middle column, below DOM tree) shows checkboxes next to each component
- [ ] **Check** the box next to `NavBar`
- [ ] **Check** the box next to `LoginForm`
- [ ] "Generate POM (2)" button is enabled
- [ ] **Uncheck** `NavBar` → button shows "Generate POM (1)"
- [ ] **Re-check** `NavBar`

---

## D. Story 5.2 — POM Code Preview

- [ ] Enter suite name `MySuite` in the input field (or leave default)
- [ ] Click **"Generate POM (2)"**
- [ ] Code panel shows **file tabs** across the top: `MySuite.py` (POM), `test_MySuite.py` (tests), `LoginForm.py` (COM), `NavBar.py` (COM)
- [ ] Click `MySuite.py` tab → shows Page Object Model class with:
  - `navigate()` method
  - `is_loaded()` that checks all components
  - `login_form` and `navbar` properties for each COM
- [ ] Click `test_MySuite.py` tab → shows pytest test file with:
  - `test_page_loads`
  - `test_component_visibility`
  - Interaction tests for components with fields
- [ ] Click `LoginForm.py` tab → shows LoginForm COM class with `email_input`, `password_input`, `submit_button`
- [ ] Click `NavBar.py` tab → shows NavBar COM class

---

## E. Story 5.3 — Smoke Test Generation

- [ ] Click the `test_MySuite.py` tab
- [ ] Verify it contains:
  - `import pytest` and Playwright imports
  - `test_page_loads` function that navigates to the page
  - `test_component_visibility` function checking each component's `is_loaded()`
  - Valid Python: copy the content and run `uv run python -c "import ast; ast.parse(r'''<content>'''); print('OK')"` → prints `OK`

---

## F. Story 5.4 — Flow Test Generation

- [ ] The generated test file includes interaction tests for components that have fields/inputs (e.g. `test_login_form_interaction` or similar for `LoginForm`)
- [ ] Interaction tests use the COM locator methods (`.email_input`, `.password_input`, `.submit_button`)

---

## G. Story 5.5 — Export Suite to .py Files

- [ ] With POM results visible, click **"Download Suite"** button in the code panel header
- [ ] A file downloads to your computer (named after the suite)
- [ ] Open the downloaded file — it contains all generated code files concatenated with `# === filename.py ===` headers
- [ ] Each section is valid Python: extract any file and run `uv run python -c "import ast; ast.parse(open('/path/to/extracted.py').read()); print('OK')"` → prints `OK`

---

## H. Edge Cases

- [ ] **No components selected**: "Generate POM (0)" is disabled
- [ ] **Single component**: Check only `NavBar`, generate POM → suite has 3 files (POM + test + 1 COM)
- [ ] **Custom suite name**: Enter `MyCustomName`, generate → tabs show `MyCustomName.py`, `test_MyCustomName.py`
- [ ] **API direct**:
```bash
curl -X POST http://localhost:8000/pom-gen \
  -H "Content-Type: application/json" \
  -d '{"url":"file:///tmp/test-page.html","selectors":["nav","form#login","aside.sidebar"],"suite_name":"FullSuite"}'
```
  - Returns JSON with 5 files (`FullSuite.py`, `test_FullSuite.py`, + 3 COMs), all with non-empty content

---

## Result

- [ ] **All pass** — Epic 5 Done
- [ ] **Some failed** — note which steps for fixing
