# Demo Guide — Test-Radius with TestRadius

This guide walks through the complete PR → Test Impact Analysis → Test Execution pipeline using the Test-Radius landing page as the demo target.

**Duration:** ~5 minutes  
**Prerequisites:** Docker, Docker Compose, Node.js 20+

---

## Architecture for the Demo

```
GitHub PR opened on Test-Radius repo
         │
         ▼
┌─────────────────────┐
│   GitHub App (:3000)│  ← receives webhook, orchestrates flow
└────────┬────────────┘
         │ HTTP
┌────────▼────────────────────────────────────┐
│  Core Service (:8000)                       │
│  ┌──────────────┐  ┌──────────────────────┐ │
│  │ analyze-pr   │  │ execute-tests        │ │
│  │ (Neo4j query)│  │ (Vitest + Playwright)│ │
│  └──────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────┘
         │                        │
    ┌────▼─────┐           ┌─────▼──────┐
    │  Neo4j   │           │  Cloned    │
    │  Graph   │           │ Test-Radius│
    └──────────┘           │  repo      │
                           └────────────┘
```

---

## Step 1: Start the Backend Stack

```bash
cd testradius-submission
docker compose --profile ml up -d
```

Wait for all services:
```
✔ Container testradius-db-1        Started
✔ Container testradius-neo4j-1     Started
✔ Container testradius-executor-1  Started
✔ Container testradius-core-ml-1   Started
✔ Container testradius-ui-1        Started
```

Verify:
```bash
curl http://localhost:8000/features
# → {"vector_matching": true, "llm": true}
```

---

## Step 2: Configure the Environment

Create `.env` (not committed to git):

```bash
# testradius-submission/.env
DEMO_MODE=true
GOOGLE_API_KEY=your-gemini-api-key   # optional, for LLM-based scoring
CORS_ORIGINS=http://localhost:5173
```

---

## Step 3: Set Up the GitHub App

### 3.1 Create a GitHub App

1. Go to [GitHub Settings → Developer Settings → GitHub Apps](https://github.com/settings/apps)
2. Click "New GitHub App"
3. Configure:
   - **Name:** TestRadius-Demo (or any name)
   - **Homepage URL:** http://localhost:3000
   - **Webhook URL:** Use smee.io or ngrok to create a public URL → `https://smee.io/your-channel`
   - **Webhook Secret:** Generate a random string
   - **Permissions:**
     - Repository → Pull Requests: Read & Write
     - Repository → Commit Statuses: Read & Write
     - Repository → Contents: Read-only
   - **Subscribe to events:** Pull request
4. Generate and download a **private key** (.pem file)

### 3.2 Configure the GitHub App

```bash
cd services/github-app
cp .env.example .env
```

Edit `services/github-app/.env`:

```env
PORT=3000
GITHUB_APP_ID=your-app-id
GITHUB_APP_NAME=your-app-name
GITHUB_CLIENT_ID=your-client-id
GITHUB_CLIENT_SECRET=your-client-secret
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
GITHUB_WEBHOOK_SECRET=your-webhook-secret
TESTSQUAD_API_URL=http://localhost:8000
TESTSQUAD_AUTH_TOKEN=demo-bypass-token
TESTSQUAD_PROJECT_ID=1211216938
```

### 3.3 Install the GitHub App

1. Go to your GitHub App's "Install App" page
2. Select the `hbahuguna/Test-Radius` repository
3. Click Install

---

## Step 4: Ingest the Test-Radius Repository

First, set up the Neo4j knowledge graph with Test-Radius symbols:

```bash
curl -X POST http://localhost:8000/projects/1211216938/sync \
  -H "Authorization: Bearer demo-bypass-token" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/hbahuguna/Test-Radius.git",
    "project_name": "Test-Radius",
    "source_type": "project"
  }'
```

Then run instrumentation to map tests to symbols:

```bash
curl -X POST http://localhost:8000/projects/1211216938/instrumentation/run \
  -H "Authorization: Bearer demo-bypass-token" \
  -H "Content-Type: application/json" \
  -d '{
    "language": "playwright",
    "testbed_name": "testradius",
    "local_path": "/Users/skaparwan/github/chatgpt/testradius-landing/Test-Radius"
  }'
```

---

## Step 5: Start the GitHub App

```bash
cd services/github-app
npm install
node app.js
# → Server is listening on port 3000
```

The GitHub App is now listening for webhook events.

---

## Step 6: Trigger the Demo

### 6.1 Open a Pull Request

On the `hbahuguna/Test-Radius` repository, make a small change and open a PR. For example, change `Home.tsx`:

```tsx
// Before
<h3 className="text-xl font-bold mb-3">Slow CI Pipelines</h3>

// After
<h3 className="text-xl font-bold mb-3">Slow E2E Pipelines</h3>
```

### 6.2 Watch the Pipeline

1. **Webhook received** — GitHub sends `pull_request.opened` to the app
2. **TIA analysis** — App calls `analyze-pr` → Neo4j finds impacted tests
3. **TIA comment** — App posts a comment on the PR with test impact analysis
4. **Test execution** — App calls `execute-tests` → runs Vitest + Playwright in a cloned repo
5. **Results comment** — App posts test results table
6. **Commit status** — App sets ✅ or ❌ status on the PR head commit

### 6.3 Expected Result

```
TestRadius - Test Impact Analysis
PR: hbahuguna/Test-Radius
Files changed: 1
Symbols analyzed: 1
Tests selected: 2

| Test      | File                                         |
|-----------|----------------------------------------------|
| home.spec | artifacts/e2e-tests/tests/home.spec.ts       |
| Home.test | artifacts/testradius/src/pages/Home.test.tsx |


TestRadius - Test Execution Results
Status: ✅ All tests passed (or ❌ depending on the change)

Result | Test                                          | Status  | Duration
✅     | Home.test.tsx > can use shared utilities      | passed  | 0.5s
✅     | home.spec.ts > hero section renders...        | passed  | 2.1s
...
```

---

## How It Works

1. **TIA finds 2 test files** that map to the changed `Home.tsx` symbol — 1 e2e spec + 1 unit test
2. **Test runner clones** the PR branch, installs dependencies, runs only those 2 files
3. **E2E tests** run in Chromium (Playwright), **unit tests** run in Vitest
4. **Results are parsed** from JSON reporters and formatted into a PR comment
5. **Commit status** reflects the overall pass/fail

If a change breaks an existing assertion (e.g., changing "Slow CI Pipelines" → "Slow E2E Pipelines" when a test expects the old text), the failing test is correctly identified and reported — demonstrating TIA catching real regressions.

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| GitHub App not receiving webhooks | Ensure public URL (smee/ngrok) is configured in GitHub App settings |
| TIA returns empty results | Verify Neo4j has evidence edges: `MATCH ()-[r:EVIDENCE]->() RETURN count(r)` |
| Test execution fails with "pnpm not found" | Rebuild Docker image: `docker compose build core-ml` |
| Playwright tests all fail | Verify Chromium browsers are installed in container: `npx playwright install chromium` |
