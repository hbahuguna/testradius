# AGENTS.md — Vertical Manual Testing Harness

## Purpose
Agent harness for web SaaS regression and visual QA with human-in-the-loop checkpoints, evidence capture, and evals.

## Stack
- Harness: Python (primary) or TypeScript
- Driver: Playwright
- Sandbox: Docker Compose
- Models: Pluggable (config)
- Connectors: GitHub/Jira/Linear

## Commands
- `python -m harness --help`
- `make harness-test` (if present)
- `docker compose -f docker-compose.sandbox.yml up -d`

## Conventions
- Stories tracked in `planning/AGILE_BOARD.md`
- Commits start with story ID: `STORY-001.1: ...`
- Human approval required before filing bugs
- Evidence in `artifacts/run-<id>/`
- No secrets in repo

## Definition of Done
All AC pass, executable check green, demo artifact exists, board updated.
