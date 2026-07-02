# Story 3.3: Backend API Endpoints

**Status**: Complete
**Epic**: 3 — Page Viewer Shell
**Effort**: 1d

---

## Summary

FastAPI endpoints for page analysis and COM generation, enabling the frontend to fetch and analyze pages through the Python backend.

## Endpoints

### `POST /analyze`

**Request**: `{"url": "https://..."}` or `{"url": "file:///path/to/page.html"}`  
**Response**: `{"url": "...", "title": "...", "root": ElementNode, "element_count": N}`

Fetches the URL, parses the DOM, returns the element tree as structured JSON.

### `POST /com-gen`

**Request**: `{"url": "https://...", "selector": "form#login"}`  
**Response**: `{"component_type": "LoginForm", "confidence": 0.9, "python_code": "..."}`

Generates a Playwright COM Python class for the element matching the CSS selector.

## Files

- `services/workbench/testsquad_workbench/main.py` — FastAPI app with `/health`, `/analyze`, `/com-gen`
- `services/workbench/testsquad_workbench/schemas.py` — Pydantic request/response models
- `services/workbench/tests/testsquad_workbench/test_analyze.py` — 7 API tests

## Verification

```bash
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{"url":"file:///tmp/test-page.html"}'

curl -X POST http://localhost:8080/com-gen \
  -H "Content-Type: application/json" \
  -d '{"url":"file:///tmp/test-page.html","selector":"form#login"}'
```
