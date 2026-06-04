# Architecture

TestRadius is a test impact analysis (TIA) platform that determines exactly which tests a code change affects. Instead of running every test on every PR, it maps code symbols to tests in a Neo4j knowledge graph and uses LLM-based scoring to select only the impacted tests.

---

## System Overview

```
┌──────────────────────────────────────────────────────────┐
│                  GitHub App / Webhook                    │
│      (PR opened → analyze → execute → comment)           │
└─────────────────────┬────────────────────────────────────┘
                      │ HTTP
┌─────────────────────▼────────────────────────────────────┐
│    Core Service (FastAPI :8000)                          │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │ Analysis │ │  Graph   │ │  Intel   │ │ Test Runner │  │
│  └──────────┘ └──────────┘ └──────────┘ └─────────────┘  │
└──────┬──────────────────┬────────────────────────────────┘
       │                  │
┌──────▼──────┐   ┌───────▼────────┐
│  PostgreSQL │   │     Neo4j      │
│  runs/users │   │  Symbol→Test   │
│  persistence│   │  Knowledge     │
└─────────────┘   │  Graph         │
                  └────────────────┘
       │
┌──────▼──────────────────────────┐
│  Executor (FastAPI :8001)       │
│  Docker sandboxes for test runs │
└─────────────────────────────────┘
```

---

## Service Boundaries

### Core Service (`services/core`)

The central intelligence engine. Handles all business logic: repository ingestion, symbol extraction, test mapping, impact analysis, and test execution orchestration.

**Module map:**

| Module | Responsibility |
|--------|---------------|
| `analysis/` | Diff parsing, code-to-test surface mapping, scoring pipelines |
| `graph/` | Neo4j ingestion via tree-sitter AST parsing + LSP resolution |
| `instrumentation/` | Per-test coverage collection (Python + TypeScript + Playwright) |
| `intelligence/` | LLM reasoning, Siamese mapping, ensemble fusion |
| `orchestration/` | Test run dispatch, PR automation, GitHub integration |
| `test_runner.py` | Vitest + Playwright execution inside cloned repositories |

### Executor Service (`services/executor`)

Lightweight service that manages isolated Docker sandboxes for executing tests. Receives execution tasks from the Core service and spawns one-shot containers for each test run.

### GitHub App (`services/github-app`)

Express.js server that:
1. Receives GitHub webhooks (`pull_request.opened`, `pull_request.synchronize`)
2. Calls Core service's `analyze-pr` endpoint for test impact analysis
3. Calls Core service's `execute-tests` endpoint to run selected tests
4. Posts results as PR comments and sets commit statuses

### Shared Packages (`packages/`)

| Package | Language | Purpose |
|---------|----------|---------|
| `shared/` | Python | Pydantic/SQLModel contracts consumed by both services |
| `vitest-plugin/` | TypeScript | Vitest plugin that collects per-test V8 coverage |

---

## Data Flow

### 1. Repository Ingestion

```
GitHub repo → Clone → tree-sitter parse → Symbol nodes → Neo4j
                                        → File nodes    →
                                        → LSP resolution →
```

The graph ingester walks the repository, parses every source file (Python/TypeScript/JavaScript) using tree-sitter, extracts code symbols (functions, classes, methods, exports), and stores them as `Symbol` nodes in Neo4j.

### 2. Test Mapping (Evidence Graph)

```
Test execution → Coverage data → Symbol resolution → [:EVIDENCE] edges
```

Two mapping strategies produce `[:EVIDENCE]` edges between `TestSymbol` and `Symbol` nodes:

1. **Instrumentation** — Runs tests with coverage collection, maps covered lines to symbols
2. **LLM Semantic Mapping** — Uses Siamese sentence-transformers and cross-encoders to score test↔symbol relevance

### 3. PR Impact Analysis (TIA)

```
PR diff → DiffParser → Changed symbols → Neo4j query → Impacted tests
                                                  ([:EVIDENCE] traversal)
```

The diff parser extracts changed lines from the PR diff. A dual-query Cypher pattern finds:
- Symbols defined in changed files (ingestor path)
- Symbols stored by the instrumentation pipeline (store_mappings path)

Each symbol's connected tests (via `[:EVIDENCE]` edges) become the impacted test set.

### 4. Test Execution

```
Selected tests → Clone repo → Inject deps → Run tests → Parse results
                                          (pnpm install) → Vitest (unit)
                                                         → Playwright (e2e)
```

The test runner clones the PR's repository at the correct commit SHA, injects required dependencies into `package.json`, installs via `pnpm`, and runs only the selected tests. Results are parsed from JSON reporters and returned to the GitHub App for PR commenting.

---

## Neo4j Schema

```
(Project {sql_id}) -[:CONTAINS]-> (File {path})
(File)-[:DEFINES]-> (Symbol {name, type, start_line, end_line, file_path})
(TestSymbol {name, file_path}) -[:EVIDENCE {confidence, source}]-> (Symbol)
(Symbol)-[:APPROVED_TEST]-> (TestSymbol)
```

- **Symbol**: A code entity (function, class, method, variable, export)
- **TestSymbol**: A test function or spec file
- **[:EVIDENCE]**: Maps a test to the symbol(s) it covers, with confidence score and source label
- **[:APPROVED_TEST]**: Human-verified test-to-symbol mapping

---

## Dual-Query Symbol Selection

The TIA pipeline uses two complementary Cypher queries to find risky symbols:

1. **Ingestor query** — Matches symbols via `(Project)-[:CONTAINS]->(File)-[:DEFINES]->(Symbol)` where the file is in the changed set
2. **Store mappings query** — Matches symbols directly by `file_path` in the changed set (for instrumentation-mapped symbols)

Results are combined, deduplicated, and ranked by priority risk index (base risk + approval bonus).

---

## Playwright + Vitest Execution in Containers

The test runner handles both unit tests (Vitest) and e2e tests (Playwright) within cloned repositories:

1. **Git operations**: Uses `git init` + `fetch` + `checkout` for SHA-based cloning (not branch-based)
2. **Dependency injection**: Patches root `package.json` with required test dependencies (vitest, jsdom, @playwright/test pinned to 1.52.0)
3. **Workspace patching**: Also patches `artifacts/e2e-tests/package.json` to match pinned versions
4. **Installation**: Uses `pnpm install` for workspace-based repos
5. **Execution split**: E2e tests run via Playwright CLI, unit tests run via Vitest binary
6. **Result parsing**: Playwright JSON reporter (nested suite traversal) + Vitest JSON reporter

---

## Key Technical Decisions

1. **Neo4j over relational for test mapping** — Graph traversal of symbol→test edges is sub-millisecond, avoiding expensive JOINs
2. **Pinned Playwright version** — Exact `1.52.0` prevents browser version drift between container and cloned repo
3. **pnpm over npm** — Many repos (like Test-Radius) use pnpm workspaces and block npm via preinstall scripts
4. **Git SHA-based cloning** — `git init + fetch + checkout <sha>` avoids branch-name assumptions
5. **Dual-mode auth** — JWT (Supabase) for production, `DEMO_MODE=true` env var for development/demos
6. **Test file auto-creation** — Missing unit test files are auto-generated with shared-utility imports for repos without committed tests
