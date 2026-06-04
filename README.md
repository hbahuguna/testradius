# TestRadius

**AI-powered test impact analysis — map, analyze, and execute only the tests that matter.**

Every PR changes code. Most CI pipelines run every test — wasting compute, slowing feedback, and training developers to ignore failures. testradius answers: _which tests does this PR actually affect?_

---

## The Problem

| Without TestRadius | With TestRadius |
|---|---|
| Run 500 tests, 3 matter | Run only the 3 impacted tests |
| PR feedback in 12 minutes | PR feedback in 45 seconds |
| Flaky test? Full suite rerun | Flaky test? Only that test reruns |
| "CI is red again" fatigue | Every failure is actionable |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  GitHub App / Webhook                    │
│      (PR opened → analyze → execute → comment)           │
└─────────────────────┬────────────────────────────────────┘
                      │ HTTP
┌─────────────────────▼────────────────────────────────────┐
│    Core Service (FastAPI :8000)   "The Brain"            │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │ Analysis │ │  Graph   │ │  Intel   │ │ Test Runner │  │
│  │ Diff→Sym │ │AST ingest│ │Code Cvrge│ │ Playwright  │  │
│  │ Scoring  │ │ LSP maps │ │ Ensemble │ │ + Vitest    │  │
│  └──────────┘ └──────────┘ └──────────┘ └─────────────┘  │
└──────┬──────────────────┬────────────────────────────────┘
       │                  │
┌──────▼──────┐   ┌───────▼────────┐
│  PostgreSQL │   │     Neo4j      │
│  runs/users │   │  Symbol→Test   │
│  persistence│   │  Knowledge     │
│             │   │  Graph         │
└─────────────┘   └────────────────┘
       │
┌──────▼──────────────────────────┐
│  Executor (FastAPI :8001)       │
│  Docker sandboxes for test runs │
└─────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend API** | Python 3.12, FastAPI, asyncpg |
| **Code Intelligence** | Neo4j (Cypher), tree-sitter (Python/TS/JS), LSP |
| **ML Scoring** | Siamese sentence-transformers, cross-encoders, LLM (Gemini/Claude) |
| **Test Execution** | Vitest (unit), Playwright + Chromium (e2e), pnpm workspaces |
| **Persistence** | PostgreSQL 16, SQLAlchemy async, SQLModel |
| **Frontend** | React 18, Vite, Supabase Auth |
| **Infra** | Docker, Docker Compose, GitHub Webhooks |

---

## Quick Setup

### Prerequisites

- Docker & Docker Compose
- Python 3.12+, Node.js 20+
- Supabase project (for JWT auth — or use `DEMO_MODE=true`)

### 1. Clone & Configure

```bash
git clone https://github.com/hbahuguna/testradius
cd testradius
cp .env.example .env
# Edit .env: add SUPABASE_JWT_SECRET, GOOGLE_API_KEY, etc.
# For demo without auth: add DEMO_MODE=true
```

### 2. Start the Stack

```bash
docker compose --profile ml up -d
```

This starts: `core-ml` (API + ML), `executor` (sandbox), `ui` (frontend), `db` (Postgres), `neo4j` (graph DB).

### 3. Ingest a Repository

```bash
# Via API
curl -X POST http://localhost:8000/projects/1/sync \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/owner/repo.git"}'
```

### 4. Open the Dashboard

```
http://localhost:5173
```

---

## Demo Flow (HyKr Build Challenge)

The system demonstrates a full PR → Test Impact Analysis → Execution pipeline:

### Automated via GitHub Webhook

1. **PR opened** on a connected repo → webhook fires
2. **TIA analyzes** the diff: identifies changed symbols, queries Neo4j for impacted tests
3. **Test execution**: clones the repo, installs deps (pnpm), runs selected tests (Vitest + Playwright)
4. **Results posted**: automated comment on the PR with test-by-test pass/fail table
5. **Commit status** set: `success` or `failure` based on results

### Example PR Workflow

```
PR #14: Changed Home.tsx <h3> text "Slow CI Pipelines" → "Slow E2E Pipelines"

TIA selected 2 tests:
  ✅ home.spec.ts (e2e) → 10 test cases ran → 1 fails (expected: text mismatch)
  ✅ Home.test.tsx (unit) → 1 test case passes

Result: 10/11 passed, 1 failed (correctly caught the content change)
```

---

## Project Structure

```
testsradius/
├── services/
│   ├── core/              # Main API + intelligence engine (18 modules)
│   │   ├── analysis/      # Diff parsing, risk scoring, community detection
│   │   ├── graph/         # Neo4j ingestion, AST-to-graph pipeline
│   │   ├── instrumentation/  # Per-test coverage (Python + TypeScript + Playwright)
│   │   ├── intelligence/  # LLM reasoning, Siamese mapping, ensemble fusion
│   │   ├── orchestration/ # Test run orchestration + PR automation
│   │   └── test_runner.py # Vitest + Playwright execution in cloned repos
│   ├── executor/          # Docker sandbox for isolated test execution
│   └── worker/            # Sandbox worker image
├── packages/
│   ├── shared/            # Pydantic/SQLModel contracts shared across services
│   └── vitest-plugin/     # npm plugin for per-test V8 coverage collection
├── ui/                    # React dashboard (Vite)
│   ├── src/components/    # 14 components: PR selector, instrumentation, etc.
│   └── src/contexts/      # Auth + GitHub context providers
├── method2test/           # Siamese sentence-transformer model
├── docs/                  # Runbooks, ADRs, migration guides, test plans
├── scripts/               # Training, verification, and utility scripts
└── docker-compose.yml     # Full stack orchestration
```

---

## Key Technical Decisions

1. **Neo4j as knowledge graph** — Code symbols are nodes, `[:EVIDENCE]` edges map tests to symbols. Cypher queries provide sub-millisecond impact analysis without scanning files.

2. **Dual-analysis pipeline** — Combines AST-based symbol extraction (tree-sitter) with LLM semantic scoring. The graph handles structural relationships; LLMs handle ambiguous cases.

3. **Test execution in cloned repos** — Rather than requiring pre-installed test suites, the executor clones the target repo, injects dependencies (vitest, Playwright), and runs only selected tests.

4. **E2E + Unit test support** — Playwright for browser tests, Vitest for unit tests. Both use JSON reporters for machine-parseable results.

5. **GitHub App integration** — Zero-config PR workflow: install the GitHub App, and every PR gets automated TIA comments with test results.

6. **pinned Playwright version** — `1.52.0` exact to prevent browser version mismatch when running e2e tests in containers.

---

## Configuration

See `.env.example` for the full list. Key variables:

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection |
| `NEO4J_URL` | Yes | — | Neo4j bolt connection |
| `DEMO_MODE` | No | false | Skip JWT auth (for demos) |
| `SUPABASE_JWT_SECRET` | If no DEMO_MODE | — | JWT validation secret |
| `GOOGLE_API_KEY` | No | — | Gemini LLM integration |
| `CORS_ORIGINS` | No | `http://localhost:5173` | Allowed origins |

---

## Testing

```bash
# Python tests
pytest services/core/tests/ services/executor/tests/

# Instrumentation tests
python scripts/_root_scripts/test_instrumentation.py

# E2E test selection verification
python scripts/verify_test_selection.py
```

---

## License

MIT
