# TestSquad Core API Documentation

## Overview

TestSquad Core provides endpoints for code-to-test mapping, impact analysis, and training data export.

## Base URL

```
http://localhost:8000
```

## Authentication

Most endpoints require authentication via `Authorization` header:

```
Authorization: Bearer <github_pat>
```

## Endpoints

### Projects

#### Create Project
```
POST /projects
```

Request:
```json
{
  "name": "my-project",
  "repo_url": "https://github.com/user/repo"
}
```

Response:
```json
{
  "id": 1,
  "name": "my-project",
  "repo_url": "https://github.com/user/repo",
  "created_at": "2026-05-03T12:00:00Z"
}
```

#### Get Project
```
GET /projects/{project_id}
```

Response:
```json
{
  "id": 1,
  "name": "my-project",
  "repo_url": "https://github.com/user/repo"
}
```

### Code-to-Test Mapping

#### Run Mapping
```
POST /projects/{project_id}/map-tests
```

Query Parameters:
- `llm_model` (optional): Model name for LLM enhancement

Response: Server-Sent Events stream
```
event: status
data: {"status": "INDEXING", "message": "Scanning files..."}

event: status
data: {"status": "MATCHING", "message": "Finding test candidates..."}

event: status
data: {"status": "COMPLETED", "message": "Found 42 mappings"}
```

### Test Mapping Matrix

#### Get Mappings
```
GET /projects/{project_id}/test-mapping?limit=50&offset=0
```

Response:
```json
[
  {
    "product_symbol": "add",
    "product_file": "src/math.py",
    "test_symbol": "test_add",
    "test_file": "tests/math.test.ts",
    "confidence": 0.92,
    "reasoning": "Name match + call graph",
    "status": "SUGGESTED_TEST"
  }
]
```

#### Update Mapping Status
```
PUT /projects/{project_id}/test-mapping
```

Request:
```json
{
  "mappings": [
    {
      "product_symbol": "add",
      "test_symbol": "test_add",
      "status": "APPROVED_TEST"
    }
  ]
}
```

Response:
```json
{
  "updated": 1
}
```

### Impact Analysis

#### Analyze Impact
```
POST /projects/{project_id}/analyze-impact
```

Request:
```json
{
  "diff": "diff --git a/src/math.py b/src/math.py\n--- a/src/math.py\n+++ b/src/math.py\n@@ -1,3 +1,4 @@\n+def add(a, b):\n def subtract(a, b):\n"
}
```

Response:
```json
{
  "tests": [
    {
      "name": "test_add",
      "file": "tests/math.test.ts",
      "confidence": 0.85,
      "reason": "call_graph",
      "risk_score": 0.90
    }
  ]
}
```

### Training Data Export

#### Get Training Data
```
GET /projects/{project_id}/training-data?min_confidence=0.6&limit=5000&include_negatives=true
```

Query Parameters:
- `min_confidence` (default: 0.6): Minimum confidence threshold
- `limit` (default: 5000): Maximum pairs
- `include_negatives` (default: true): Include hard negatives

Response: CSV file download

CSV Format:
```csv
sym_id,sym_path,sym_summary,test_id,test_path,test_summary,confidence,source,reasoning,label
add,src/math.py,Adds two numbers,test_add,tests/math.test.ts,Tests add,0.9,vector,Name match,1
```

### Sync

#### Run Sync
```
POST /projects/{project_id}/sync
```

Response: Server-Sent Events stream
```
event: status
data: {"status": "SYNCING", "message": "Syncing repository..."}

event: status
data: {"status": "COMPLETED", "message": "Synced 150 files"}
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|------------|---------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql+asyncpg://testsquad:password@db:5432/testsquad` |
| `NEO4J_URL` | Neo4j connection | `bolt://localhost:7687` |
| `NEO4J_USER` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | `testsquad_password` |
| `EXECUTOR_URL` | Executor service URL | `http://executor:8001` |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `GOOGLE_API_KEY` | Google API key | - |

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Invalid diff format"
}
```

### 401 Unauthorized
```json
{
  "detail": "Not authenticated"
}
```

### 404 Not Found
```json
{
  "detail": "Project not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Analysis failed: Neo4j connection error"
}
```

## Rate Limits

- `/map-tests`: 1 concurrent per project
- `/sync`: 1 concurrent per project
- Training export: 1 per minute

## Health Check

```
GET /health
```

Response:
```json
{
  "status": "healthy",
  "version": "0.1.0"
}
```