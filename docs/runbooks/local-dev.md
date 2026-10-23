# Local development runbook

The factory stack is **separate** from the existing TIA product stack. It uses its own Compose
project (`testradius-factory`), its own file (`infra/compose/compose.factory.yaml`), and
non-overlapping ports. `docker-compose.yml` at the repo root is untouched.

## Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| Node | 22 (`.nvmrc`) | pnpm 11 requires Node >= 22.13; the cell image still pins Node 20 for Playwright |
| pnpm | 11.x | `packageManager` in `package.json` |
| uv | 0.5+ | `uv python install 3.12` |
| Docker | 27+ with Compose v2 | Docker Desktop or colima |
| curl, openssl | any | smoke + dev secret generation |

```bash
make doctor   # fails fast with the exact missing item
```

## Ports

| Service | URL |
| --- | --- |
| cell | http://localhost:58000 |
| control plane | http://localhost:58001 |
| web | http://localhost:53000 |
| fixture AUT | http://localhost:58080 |
| mock OIDC | http://localhost:58090 |
| Postgres | `localhost:55432` (`testsquad` / `testsquad_password` / db `factory`) |
| Neo4j | http://localhost:57474, bolt `localhost:57687` |
| MinIO | http://localhost:59000, console http://localhost:59001 |
| Vault (dev) | http://localhost:58200, token `dev-root-token` |

## First run

```bash
make doctor
make bootstrap     # pnpm install + uv sync for apps/cell
make up            # builds images and waits for health
make secrets       # generates dev secrets into Vault (values never touch disk)
make smoke
```

`make up` waits up to 5 minutes. The cell will not report ready until the fixture AUT and Neo4j
answer their probes; that is intentional (E1-S2).

## Day-to-day

```bash
make logs                  # tail every service
make test                  # Python cell + architecture + JS workspaces
make arch-test             # fast boundary check before pushing
make ci                    # lint + test + arch-test
```

The cell and control plane rebuild on `make up`; for tight loops run them locally instead:

```bash
uv run --project apps/cell uvicorn cell.main:app --reload --port 58000
pnpm --filter @testradius/control-plane dev
pnpm --filter @testradius/web dev
```

## Dev secrets

`make secrets` writes four values to the local Vault under `secret/factory/{llm,github,db,evidence}`.
The values are generated at run time with `openssl rand` and are never printed or written to a file.
Read a value explicitly when you need it:

```bash
curl -s -H "X-Vault-Token: dev-root-token" \
  http://localhost:58200/v1/secret/data/factory/llm | jq -r .data.data.value
```

This is a dev-only Vault (in-memory, no persistence). Production uses the providers in ADR-005.

### Rotate a dev secret

Generate the replacement and write it directly to Vault; do not put it in a shell history file:

```bash
NEW="$(openssl rand -hex 24)"
curl -fsS -X POST -H "X-Vault-Token: dev-root-token" \
  -H "Content-Type: application/json" \
  -d "{\"data\":{\"value\":\"$NEW\"}}" \
  http://localhost:58200/v1/secret/data/factory/llm >/dev/null
unset NEW
```

Restart the consumer (`docker compose ... restart cell` or the local process). In S1 no service
fetches broker values yet (`SECRET-FETCH` is open until E1-S8), so rotation currently verifies the
broker path only.

## Troubleshooting

**Port already in use.** Check the existing product stack first: `docker ps --format '{{.Names}}\t{{.Ports}}'`.
The factory deliberately avoids 3000/5432/7474/7687/8000.

**`uv sync` fails building `cryptography`.** Sprint 1 does not depend on it; PyJWT is added in
S2 with a pinned wheel. If you see this, you are on a stale `uv.lock`.

**`pnpm` exits with `ERR_PNPM_IGNORED_BUILDS`.** pnpm 11 requires an explicit build allowlist.
`pnpm-workspace.yaml` allows `esbuild`; add a package there only with a review note.

**Cell is unhealthy with `aut_status: unreachable`.** The fixture AUT container is not ready. Check
`docker compose -f infra/compose/compose.factory.yaml logs mock-aut`. The cell returns `503` by
design until its configured dependencies answer (E1-S2 AC3).

**`make smoke` says the cell rootfs is writable.** You are running an old image. Rebuild with
`make up`; the Compose service sets `read_only: true`.

**Docker socket.** The cell never mounts it. If a build story needs Docker, that is a separate
build job (ADR-001), never a cell volume.

## Teardown

```bash
make down     # stop, keep volumes (Neo4j/Postgres/MinIO data)
make clean    # stop and delete volumes
```
