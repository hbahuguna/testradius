# Sprint 2 demo — Orchestrator + internal API

Commands assume `make up && make secrets` has run. The cell is on `localhost:58000`.

## E1-S3 — Internal API + run-scoped tokens

```bash
CREATE=$(curl -sS -X POST localhost:58000/v1/runs -H 'Content-Type: application/json' \
  -d '{"repo":"fixture","commit":"abc1234","scope":"full","policy":{"allow_network":false}}')
ID=$(echo "$CREATE" | jq -r .run_id); TOKEN=$(echo "$CREATE" | jq -r .run_token)
curl -s -o /dev/null -w '%{http_code}\n' localhost:58000/v1/runs/$ID          # 401
curl -s -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID | jq   # 200
```

## E1-S4 — Orchestrator state machine

```bash
curl -Ns -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID/events |
  grep -o '"phase": "[a-z]*"' | uniq
# isolate → select → generate → execute → prove → gate → report
```

## E1-S5 — Run lifecycle API

```bash
curl -s -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID/evidence | jq
curl -s -X POST -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID/cancel | jq
```

## E1-S6 — SSE event stream

```bash
curl -Ns -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID/events | head -6
# id: 1 / data: {"schema_version":"1",...,"payload":{"event":"run.started"}}
```

## E1-S7 — Policy engine

```bash
docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory \
  exec -T cell python -c "from cell.policy.engine import PolicyEngine; p=PolicyEngine(); \
  p.load({'allow_network': False}); print(p.check_network('example.com'))"
# PolicyDecision(allowed=False, reason='network_egress_denied')
```

## E1-S8 — Secrets broker

```bash
make secrets
docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory \
  exec -T cell python -c "from cell.config import get_settings; from cell.secrets.broker import VaultBroker; \
  s=get_settings(); print('length', len(VaultBroker(s.vault_addr, s.vault_token).get_secret('factory/llm')))"
```

## Restart / resume (exit criterion)

```bash
CREATE=$(curl -sS -X POST localhost:58000/v1/runs -H 'Content-Type: application/json' \
  -d '{"repo":"fixture","commit":"resume","scope":"full","policy":{"stub_delay_ms":1000}}')
ID=$(echo "$CREATE" | jq -r .run_id); TOKEN=$(echo "$CREATE" | jq -r .run_token)
docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory restart cell
sleep 3; curl -s -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID | jq '{status,phase}'
# succeeded / report, with event seq continuing (no duplicate phase work)
```
