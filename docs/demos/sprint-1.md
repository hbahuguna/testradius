# Sprint 1 demo

Every command runs from the repository root. Five lines max per story.

## E0-S1 — Monorepo scaffolding

```bash
make doctor
pnpm -r --if-present typecheck
ls apps/cell apps/control-plane apps/web packages/shared-types packages/test-fixtures
```

## E0-S2 — Local stack

```bash
make up
make smoke
open http://localhost:53000
```

## E0-S3 — CI

```bash
make ci
gh run list --workflow factory-ci.yml --limit 3
```

## E0-S4 — Standards + ADR workflow

```bash
ls docs/adr
pre-commit run --all-files   # after `pre-commit install`
```

## E0-S5 — Shared contracts

```bash
pnpm --filter @testradius/shared-types test
uv run --project apps/cell pytest -c apps/cell/pyproject.toml apps/cell/tests/test_event_contract.py
```

## E0-S6 — Fixtures

```bash
pnpm --filter @testradius/fixture-aut test
curl -fsS localhost:58080/api/products | jq '.products | length'
```

## E0-S7 / E7-S1 — Architecture tests

```bash
make arch-test
# negative demo: add `@router.get("/debug")` to apps/cell/cell/routes.py
make arch-test   # fails: routes outside the cell contract
git checkout apps/cell/cell/routes.py
```

## E0-S8 — Local secrets

```bash
make secrets
curl -fsS -H "X-Vault-Token: dev-root-token" \
  http://localhost:58200/v1/secret/metadata/factory | jq '.data.keys'
```

## E1-S1 — Hardened cell image

```bash
docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory build cell
docker image inspect testradius-cell:dev --format '{{.Size}} bytes'
docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory exec cell id -u
```

## E1-S2 — Health and readiness

```bash
curl -fsS localhost:58000/v1/health | jq
docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory stop mock-aut
curl -s -o /dev/null -w '%{http_code}\n' localhost:58000/v1/health   # 503
docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory start mock-aut
```
