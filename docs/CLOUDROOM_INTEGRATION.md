# Cloud Room Integration Guide

## Overview
TestRadius integrates with Cloud Room to run tests in isolated cloud VMs instead of local Docker containers.

## Setup
1. Install Cloud Room: `curl -fsSL https://cloudroom.dev/install.sh | sudo bash`
2. Get token from `/etc/cloudroom/core.env`
3. Configure TestRadius with `CLOUDROOM_URL` and `CLOUDROOM_TOKEN`
4. Set `EXECUTOR_TYPE=cloudroom`

## Architecture
- **Executor Abstraction**: `BaseExecutor` interface allows swapping backends
- **CloudRoomExecutor**: Orchestrates threads/subagents via Cloud Room API
- **Plan Injection**: Test plans converted to prompts with browser-harness instructions
- **Artifact Sync**: Auto-downloads and normalizes artifacts to `artifacts/run-<id>/`

## API Endpoints
- `GET /api/system/executor` - Current executor status
- `GET /api/executor/config` - Executor configuration
- `POST /api/runs/{id}/start-executor` - Start with selected executor

## Testing
```bash
python scripts/test_cloudroom_e2e.py
```
