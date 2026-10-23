# TestRadius Factory Cell

Ephemeral, UI-less run runtime. One container, one run.

## Contract

The entire external surface is `cell/contracts.py`. Anything not listed there fails the
architecture test. `/docs`, `/redoc` and `/openapi.json` are disabled — they are a UI and the
cell must not ship one (ADR-002).

Sprint 1 implements `GET /v1/health`; the remaining contract routes land in Sprint 2.

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
never mounts the Docker socket.
