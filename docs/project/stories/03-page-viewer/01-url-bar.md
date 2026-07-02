# Story 3.1: URL Bar + Navigation Controls

**Status**: Complete
**Epic**: 3 — Page Viewer Shell
**Effort**: 1d

---

## Summary

URL input bar with navigation controls (back, forward, refresh) in the Electron app toolbar. Users enter a URL and press Go or Enter to analyze a page via the Python backend.

## Implementation

- **URL bar**: Text input with placeholder showing example formats (`https://`, `file://`)
- **Go button**: Sends `POST /analyze` to the backend; shows `...` while loading
- **Nav buttons**: Back (◀) and Forward (▶) navigate through page history; Refresh (⟳) re-fetches current URL
- **Error bar**: Inline error display for failed fetches or parse errors

## Files

- `apps/workbench/src/App.tsx` — toolbar section with URL bar, nav buttons, Go button
- `apps/workbench/src/App.css` — `.url-bar`, `.nav-btn`, `.go-btn`, `.toolbar`, `.error-bar`

## Verification

1. Start backend: `uv run uvicorn testsquad_workbench.main:app --port 8080`
2. Open the Electron app (or built frontend)
3. Enter `file:///tmp/test-page.html`, press Go
4. Verify the DOM tree appears in the left panel
5. Verify back/forward/refresh buttons work
6. Verify error message appears for invalid URLs
