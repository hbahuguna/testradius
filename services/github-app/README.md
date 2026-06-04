# TestRadius GitHub App

Node.js Express server that powers the PR → TIA → Test Execution automation.

## How It Works

1. Receives GitHub webhooks (`pull_request.opened`, `pull_request.synchronize`)
2. Authenticates as a GitHub App installation using `@octokit/auth-app`
3. Calls TestSquad v2 Core Service:
   - `POST /projects/{id}/analyze-pr` — Test Impact Analysis
   - `POST /projects/{id}/execute-tests` — Run selected tests
4. Posts results as PR comments and sets commit statuses

## Setup

### 1. Create a GitHub App

1. Go to GitHub Settings → Developer Settings → GitHub Apps → New GitHub App
2. Set **Webhook URL** to a public URL (use [smee.io](https://smee.io) or ngrok)
3. Set **Webhook Secret** to a random string
4. Permissions needed:
   - Pull Requests: Read & Write
   - Commit Statuses: Read & Write
   - Contents: Read-only
5. Subscribe to: **Pull request** events
6. Generate and download a private key

### 2. Configure

```bash
cp .env.example .env
```

Fill in the values from your GitHub App settings page.

### 3. Install

```bash
npm install
```

### 4. Run

```bash
node app.js
# → Server is listening on port 3000
```

### 5. Install the App on a Repository

Go to your GitHub App's "Install App" page and select the repositories you want to enable TIA on.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | No | Server port (default: 3000) |
| `GITHUB_APP_ID` | Yes | GitHub App ID |
| `GITHUB_CLIENT_ID` | Yes | GitHub App client ID |
| `GITHUB_CLIENT_SECRET` | Yes | GitHub App client secret |
| `GITHUB_PRIVATE_KEY` | Yes | RSA private key (newline-escaped) |
| `GITHUB_WEBHOOK_SECRET` | Yes | Webhook HMAC secret |
| `TESTSQUAD_API_URL` | Yes | Core service URL (default: http://localhost:8000) |
| `TESTSQUAD_AUTH_TOKEN` | Yes | Bearer token for Core service |
| `TESTSQUAD_PROJECT_ID` | Yes | Neo4j project ID for TIA queries |
