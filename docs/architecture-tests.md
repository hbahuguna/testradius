# Architecture tests

The factory has two executable boundaries that prose cannot enforce:

1. **The cell is UI-less.** No UI framework, template engine, static asset, or session middleware
   may enter `apps/cell`. (ADR-002)
2. **The cell has a closed route surface.** Only the routes listed in `cell/contracts.py` may be
   registered; `/docs`, `/redoc` and `/openapi.json` are disabled because they ship a UI.

Both are checked by `infra/architecture-tests/` on every test run, in CI, and in pre-commit.

## Run

```bash
make arch-test
# or, directly:
uv run --project apps/cell pytest -c apps/cell/pyproject.toml infra/architecture-tests
```

The suite runs inside the cell's Python environment because the route audit imports the real
FastAPI app — it does not grep source files and cannot be fooled by a dynamic route.

## Rules

`infra/architecture-tests/rules.toml` is the reviewable rule file.

| Rule | Enforced by | What fails |
| --- | --- | --- |
| `deny_python_imports` | `test_no_ui_in_cell.py` | Direct imports of `flask`, `jinja2`, `django`, `fastapi.staticfiles`, `starlette.templating`, … |
| `deny_python_dependencies` | `test_no_ui_in_cell.py` | UI/template packages declared in `apps/cell/pyproject.toml` |
| `deny_node_dependencies` | `test_no_ui_in_cell.py` | A future `apps/cell/package.json` adding `react`, `next`, `vite`, `express`, … |
| `deny_directory_names` / `deny_file_extensions` | `test_no_ui_in_cell.py` | `public/`, `static/`, `templates/`, `*.html`, `*.css` outside `apps/cell/tests` |
| `CONTRACT_ROUTES` | `test_route_contract.py` | Any registered route outside the seven contract routes |
| `EXPECTED_REGISTERED_ROUTES` | `test_route_contract.py` | Implementing a route without an explicit allowlist update (forces review) |
| Dockerfile + Compose assertions | `test_cell_hardening.py` | Running as root, writable rootfs, added capabilities, Docker socket, Firefox/WebKit |

## Adding a contract route

Route additions are a two-line change in `apps/cell/cell/contracts.py` plus the handler and its
tests:

1. The route must already exist in `CONTRACT_ROUTES` (from the product brief). If it is a new
   product surface, that is an ADR, not a story.
2. Add the `(method, path)` pair to `EXPECTED_REGISTERED_ROUTES` in the same PR.
3. The PR needs a second reviewer (CODEOWNERS: `@testradius/cell`).

The architecture test intentionally fails when a route appears without the allowlist edit, so an
accidental `@router.get("/debug")` cannot merge silently.

## Escape hatch

There is none for UI code. The only permissible exception is a **test fixture** under
`apps/cell/tests/`, which is excluded by `allow_path_parts` and cannot be imported by production
code.
