# TestRadius Factory Cell

Ephemeral, UI-less run runtime. One container, one run.

## Contract

The entire external surface is `cell/contracts.py`. Anything not listed there fails the
architecture test. `/docs`, `/redoc` and `/openapi.json` are disabled — they are a UI and the
cell must not ship one (ADR-002).

Sprint 2 provides the run lifecycle. Sprint 3 adds an optional agent runtime behind
the run policy: `runtime=agent` uses a provider, a local context index, a cited
planner, and an MCP-compatible tool registry. The default remains the deterministic
stub runtime so existing smoke tests do not need a model or browser.

## Agent runtime

Set `runtime` to `agent` on a run. The fixture repository is indexed from
`CELL_FIXTURE_REPO_PATH` (Compose mounts it read-only at `/workspace/fixture`).
`provider=fake` uses the deterministic provider; `provider=anthropic` or
`provider=openai` reads the key from the cell secret broker. `browser=playwright`
enables the real browser tool client; without it the in-memory client is used for
tests and offline demos. Every tool call must cite a resolved context node.
The browser surface also exposes accessibility-tree reads, screenshots, traces,
and console/network artifacts under `/workspace/<run_id>`. Artifact paths are
sanitized to the run workspace and cannot escape it. A blocking accessibility
defect produces `testability_defect` and stops execution with no selector fallback.

```json
{
  "runtime": "agent",
  "provider": "fake",
  "browser": "playwright",
  "allow_network": true,
  "allowed_hosts": ["mock-aut"],
  "fake_plan": {
    "steps": [
      {
        "intent": "open the fixture",
        "tool": "browser.navigate",
        "arguments": {"url": "http://mock-aut:8080/cart"},
        "citations": ["file:public/cart.html"]
      }
    ]
  }
}
```

## Local

```bash
uv sync --all-groups
uv run pytest
uv run uvicorn cell.main:app --port 58000
curl -s localhost:58000/v1/health | jq
```

## Hardening

The image is built from `python:3.12-slim` with Node 20 and Chromium only. It runs as uid
`10001`; Compose enforces `read_only: true`, `cap_drop: ALL`, and `no-new-privileges`. The cell
never mounts the Docker socket. Tool allowlists, MCP health checks, and citation
enforcement are applied before every invocation. Context retrieval marks its source
and falls back to the filesystem/AST view if the graph is unavailable. The image is
1.62 GB (Chromium preserved; only `/workspace` and `/home/cell` chowned).
