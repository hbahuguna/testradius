# Sprint 3 demo — cited agent runtime

Commands assume `make up` has run and the cell is healthy on `localhost:58000`.
The fixture is mounted read-only at `/workspace/fixture`; `provider=fake` keeps
the demo deterministic. Set `browser=playwright` to exercise the real browser.

## E2-S2/S3/S11 — cited plan, tools, and metrics

```bash
CREATE=$(curl -sS -X POST localhost:58000/v1/runs -H 'Content-Type: application/json' -d '{
  "repo":"fixture","commit":"abc1234","scope":"full","goal":"verify cart",
  "policy":{
    "runtime":"agent","provider":"fake","browser":"playwright",
    "allow_network":true,"allowed_hosts":["mock-aut"],
    "fake_plan":{"steps":[
      {"step_id":"open","intent":"open cart","tool":"browser.navigate",
       "arguments":{"url":"http://mock-aut:8080/cart"},
       "citations":["file:public/cart.html"]},
      {"step_id":"tree","intent":"read the accessibility tree",
       "tool":"browser.accessibility_tree","arguments":{},
       "citations":["file:public/cart.html"]},
      {"step_id":"assert","intent":"assert summary","tool":"browser.assert_text",
       "arguments":{"text":"Your cart is empty."},
       "citations":["file:public/cart.html"]},
      {"step_id":"shot","intent":"capture evidence","tool":"browser.screenshot",
       "arguments":{"path":"cart.png"},"citations":["file:public/cart.html"]}
    ]}
  }
}')
ID=$(echo "$CREATE" | jq -r .run_id); TOKEN=$(echo "$CREATE" | jq -r .run_token)
for _ in $(seq 1 100); do
  STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID | jq -r .status)
  case "$STATUS" in succeeded|failed|cancelled) break;; esac
  sleep 0.2
done
curl -s -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID | jq '{status,phase}'
curl -sN -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID/events |
  grep -E 'plan.created|tool.completed|run.verdict'
```

`run.verdict.metrics` carries `steps`, `tokens`, `tool_calls`, and `duration_ms`.
The screenshot path is under the run's `/workspace/<run_id>` directory.

## E2-S4/E2-S11 — blocking accessibility defect

The fixture home page intentionally has two unnamed controls. The same plan
against `/` must stop at the accessibility check and never run the later assert.

```bash
CREATE=$(curl -sS -X POST localhost:58000/v1/runs -H 'Content-Type: application/json' -d '{
  "repo":"fixture","commit":"abc1234","scope":"full","goal":"verify home",
  "policy":{
    "runtime":"agent","provider":"fake","browser":"playwright",
    "allow_network":true,"allowed_hosts":["mock-aut"],
    "fake_plan":{"steps":[
      {"step_id":"open","intent":"open home","tool":"browser.navigate",
       "arguments":{"url":"http://mock-aut:8080/"},
       "citations":["file:public/index.html"]},
      {"step_id":"a11y","intent":"check accessible names",
       "tool":"browser.check_a11y","arguments":{},
       "citations":["file:public/index.html"]},
      {"step_id":"assert","intent":"assert menu",
       "tool":"browser.assert_text","arguments":{"text":"Menu"},
       "citations":["file:public/index.html"]}
    ]}
  }
}')
ID=$(echo "$CREATE" | jq -r .run_id); TOKEN=$(echo "$CREATE" | jq -r .run_token)
for _ in $(seq 1 100); do
  STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID | jq -r .status)
  case "$STATUS" in succeeded|failed|cancelled) break;; esac
  sleep 0.2
done
echo "status=$STATUS"   # failed
curl -sN -H "Authorization: Bearer $TOKEN" localhost:58000/v1/runs/$ID/events |
  grep -E 'a11y.blocked|step.failed|run.verdict'
```

Expected verdict: `testability_defect`; the run stops at `execute` and does not
emit `run.completed`.

## E2-S1/S8 — deterministic planner tests

```bash
uv run --project apps/cell pytest -q -c apps/cell/pyproject.toml apps/cell/tests/agent
```

The tests cover provider retry/budget, citation rejection, one planner
re-prompt, cycle detection, tool allowlists, loop detection, cancellation, and
the blocking-a11y terminal path.
