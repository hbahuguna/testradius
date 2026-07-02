# Epic 4: Visual Inspector + Single-Click Test Builder — Manual Test Plan

---

## Prerequisites

- [ ] `cd /Users/skaparwan/github/chatgpt/testradius`
- [ ] `uv sync` in `services/workbench/` completed
- [ ] `npm install` in `apps/workbench/` completed
- [ ] Test fixture exists:
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
- [ ] Open `http://localhost:5173`

---

## A. Regression: Unit Tests

- [ ] `cd services/workbench && uv run pytest -v` — **all 105 pass**

---

## B. Story 4.1 + 4.3: Hover + Click-to-Select

- [ ] Enter `file:///tmp/test-page.html` in URL bar, click **Go**
- [ ] Preview panel loads the page with login form visible
- [ ] Hover over **Sign In** button → blue outline appears around button
- [ ] Hover over email input → blue outline appears
- [ ] Hover over password input → blue outline appears
- [ ] Click **Sign In** button → step card appears in right panel named "sign_in" with action "Click"
- [ ] Click email input → step card appears named "email" with action "Type Text"
- [ ] Click password input → step card appears named "password" with action "Type Text"
- [ ] Right panel shows "3 steps" count

---

## C. Story 4.3: Duplicate Click (Flash)

- [ ] Click **Sign In** button again → no new step card; existing "sign_in" card flashes with orange border animation
- [ ] Same for email input → flashes existing card

---

## D. Inline Step Editing

- [ ] Click step name input → edit "sign_in" to "login_button" — name updates in card
- [ ] Change action dropdown from "Click" to "Assert Visible" → action updates
- [ ] Change action to "Type Text" → value input appears with placeholder "text to type"
- [ ] Type "hello@test.com" in the value field
- [ ] Change action to "Select Option" → value placeholder changes to "option value"
- [ ] Change action to "Wait" → value placeholder changes to "ms or selector"
- [ ] Change action back to "Click" → value input disappears

---

## E. Story 4.4: Generate Test Code

- [ ] Remove password step (click **x**), keep "email" and "login_button" steps
- [ ] Click **Generate Test**
- [ ] Modal overlay appears with generated code
- [ ] Shows file tabs across the top: `LoginPageTest.py` (test), `LoginPage.py` (POM)
- [ ] Click `LoginPage.py` tab → shows POM class with `email` and `login_button` locators
- [ ] Click `LoginPageTest.py` tab → shows test file with navigation + step flow

---

## F. Story 4.6: Copy Generated Code

- [ ] With `LoginPageTest.py` tab active in modal, click **Copy Code**
- [ ] Button text changes to "Copied!" for 2 seconds
- [ ] Paste clipboard content → matches the displayed test file content
- [ ] Switch to POM tab, click **Copy Code** again → copies POM content
- [ ] Close modal (click **x** or overlay backdrop) → modal dismisses

---

## G: Edge Cases: Non-Interactive Elements

- [ ] Enter `file:///private/tmp/test-page-edge-cases.html`, click **Go**
- [ ] Hover over `<script>` or `<style>` → blue outline may appear (expected: script/style tags are live elements)
- [ ] Click on script/style region → no step added (should be rejected by inspector)
- [ ] Click **Plain Div Content** → step card added with action "Click" (divs are clickable by intent)
- [ ] Click **Span Content** → step card added
- [ ] Click **Paragraph text here** → step card added

---

## H: Edge Cases: SVG Elements

- [ ] Click the blue rectangle (SVG `<rect>`) in the preview → step card added with tag "rect"
- [ ] Click the red circle (SVG `<circle>`) → step card added
- [ ] Click the green triangle (SVG `<path>`) → step card added
- [ ] Click **SVG Text** → step card added with tag "text"
- [ ] Verify all SVG selectors are valid (e.g. `rect#svg-rect`, `circle#svg-circle`)

---

## I: Edge Cases: Shadow DOM

- [ ] Click **Shadow Button** or **Shadow text** → step card added
- [ ] Step card shows `inShadowDOM: true` (visible in the step card or selector area)
- [ ] Verify generated test includes the shadow host selector for the step

---

## J: Edge Cases: Duplicate / Invalid Inputs

- [ ] Click **Clear** → all steps removed, generate button hidden, "Click any element in the preview to add a test step" shown
- [ ] Clear URL bar, press Enter → nothing happens (empty URL guard)
- [ ] Enter invalid URL (e.g. `not-a-url`), click Go → error bar appears
- [ ] Enter valid URL again → error clears, page loads

---

## K: Layout Toggle

- [ ] Default layout: side-by-side (horizontal)
- [ ] Click vertical layout button (up/down arrow) → layout switches to stacked
- [ ] Click horizontal layout button (left/right arrow) → layout switches back
- [ ] Verify both panels are still functional after toggle

---

## L: API Direct (Backend)

- [ ] **Preview**:
```bash
curl -s "http://localhost:8000/preview?url=file:///tmp/test-page.html" | head -1
```
  → Returns HTML with injected inspector script

- [ ] **Generate test**:
```bash
curl -X POST http://localhost:8000/generate-test \
  -H "Content-Type: application/json" \
  -d '{"url":"file:///tmp/test-page.html","components":[{"name":"email","selector":"input[type=email]","tag":"input","text":"","actions":[{"type":"type","value":"test@example.com"}]},{"name":"submit","selector":"button[type=submit]","tag":"button","text":"Sign In","actions":[{"type":"click","value":""}]}]}'
```
  → Returns JSON with test file + POM file, both with non-empty content

---

## Result

- [ ] **All pass** — Epic 4 Done, proceed to Epic 5
- [ ] **Some failed** — note which steps for fixing
