# ADR-002 — No UI in the cell, enforced by an architecture test

## Context
A UI in the cell would add static assets, sessions, cookies, CSRF, XSS, and a browser-facing attack surface to a component that runs with credentials and client code access in some modes. The brief forbids "a user-facing HTTP server, static assets, or session storage". Prose does not prevent regressions; a test does.

## Decision
- The cell exposes JSON + SSE only, under `/v1/*`, and has no static/template/session middleware.
- `E7-S1` enforces three checks in CI and pre-commit:
  1. **Dependency denylist** for both `pyproject.toml`/imports and `package.json`: `next`, `nuxt`, `vite`, `react`, `react-dom`, `vue`, `@angular/*`, `svelte`, `tailwindcss`, `express` + `static`, `jinja2`, `django.template`, `flask` templates, session middleware.
  2. **Filesystem denylist**: `public/`, `static/`, `templates/`, `*.html` (except test fixtures under `tests/`).
  3. **Route audit**: the router must expose exactly the six contract routes; additions require an explicit allowlist edit reviewed by a second engineer.
- The UI lives only in `apps/web`, which depends on the CP API, never on a cell.

## Consequences
- (+) A whole vulnerability class is removed by construction.
- (+) The cell image stays small and fast to start.
- (−) Debugging requires curl/SSE tooling; we must ship CLI recipes in runbooks.
- (−) Denylists can produce false positives (e.g., a transitive `tailwind` in a test tool); the allowlist escape hatch is narrow and reviewed.

## Alternatives considered
- Read-only debug UI behind an internal flag — rejected: still ships static assets and sessions; violates the constraint.
- Separate debug sidecar — rejected: doubles the surface and the image.

---
