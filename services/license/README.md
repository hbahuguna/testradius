# TIA License Server

License activation, subscription validation, and TIA run metering for the commercial TIA agent.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/activations` | Activate a device with `license_key` + `device_fingerprint`. Returns one-time `activation_token`. |
| GET | `/v1/validate` | Daily validation (`Authorization: Bearer <token>`). Returns status, quota, `grace_until`. |
| POST | `/v1/runs` | Meter a **completed** TIA run (idempotent by `run_id`). Only called on successful results. |
| POST | `/v1/webhooks/stripe` | Stripe subscription webhook (signature verified when secret set). |
| POST/GET | `/v1/admin/licenses` | Create/list licenses (`Authorization: Bearer <LICENSE_ADMIN_TOKEN>`). |
| GET | `/health` | Liveness. |

## Behavior

- **Subscription periods**: driven by Stripe `current_period_end`. After period end, a **3-day grace** applies (`LICENSE_GRACE_DAYS`), then runs are blocked with a graceful renewal message.
- **Offline grace**: the client may operate up to 3 days from its last successful validation if the server is unreachable; beyond that it blocks.
- **Quota**: `runs_quota` per subscription period; exhaustion blocks with an upgrade message.
- **Idempotency**: the same `run_id` is never counted twice.
- **Privacy (D12)**: run metadata is allowlisted (`repo_hash`, `file_count`, `test_count`, `language`, `duration_seconds`, `os`, `agent_version`). Repo content is never accepted.

## Configuration (env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `LICENSE_DATABASE_URL` | `sqlite:///./license.db` | SQLAlchemy URL (use `postgresql+psycopg2://...` in prod) |
| `LICENSE_ADMIN_TOKEN` | *(unset = admin disabled)* | Admin API bearer token |
| `LICENSE_STRIPE_WEBHOOK_SECRET` | *(unset = skip verify)* | Stripe webhook signing secret |
| `LICENSE_GRACE_DAYS` | `3` | Grace days after period end |
| `LICENSE_DEVICE_LIMIT` | `3` | Default concurrent devices per license |
| `LICENSE_RUNS_PER_PERIOD` | `500` | Default runs per subscription period |

## Run locally

```bash
cd services/license
uv venv .venv && uv pip install -e . uvicorn
LICENSE_ADMIN_TOKEN=devtoken .venv/bin/uvicorn license_server.app:app --port 8100
```

Seed a license:

```bash
curl -X POST localhost:8100/v1/admin/licenses \
  -H "Authorization: Bearer devtoken" -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "runs_quota": 100}'
```

## Tests

```bash
cd services/license
uv venv .venv && uv pip install -e . pytest
.venv/bin/python -m pytest tests/ -q
```

## Docker

```bash
docker compose --profile license up license
```
