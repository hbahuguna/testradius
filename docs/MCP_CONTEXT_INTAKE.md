# MCP Context Intake & Normalization (STORY-E2B-008.1)

This module normalizes requirement context from **MCP/manual sources** into a safe, provenance-rich `ContextBundle` for compiled test-plan generation. It is **control-plane only**: it gathers and normalizes context; it does **not** send raw Jira/Figma/PRD payloads to execution sandboxes.

## Goals

- **Normalized schema**: `harness.context.schema.ContextBundle` captures source refs, title/summary, description, acceptance criteria, user flows, UI/design refs (Figma links + notes), API/data constraints, env/build info, risk areas, and out-of-scope items.
- **MCP-first design with fallback**: configurable source/MCP server mappings for Jira, Figma, GitHub, and docs. If an MCP server or source is unavailable, intake falls back to manual input/explicit fallback payload.
- **No secrets persisted**: tokens/credentials come only from env/config references. Redaction is applied before saving bundles/artifacts. Env var *names* may be referenced; values must never be embedded.
- **Provenance**: every bundle records source refs, adapter/tool used, timestamps, warnings, and redaction status.

## Key modules

- `harness/context/schema.py` — `ContextBundle`, `SourceRef`, `UIDesignRef`, `APIConstraint`, `Provenance`.
- `harness/context/normalization.py` — `ContextNormalizer` (manual/MCP payload normalization, merge, redaction, save).
- `harness/context/loader.py` — `load_context`/`save_context` helpers.
- `harness/integrations/mcp_context/adapters.py` — `ManualContextAdapter`, `MCPResourceAdapter`, `JiraContextAdapter`, `FigmaContextAdapter`, `GitHubContextAdapter`, `DocsContextAdapter`.
- `harness/integrations/mcp_context/intake.py` — `ContextIntake`, `ContextSourceConfig`, `MCPServerConfig`.

## Usage

### Manual / file input

```python
from harness.context import ContextNormalizer

normalizer = ContextNormalizer()
result = normalizer.from_manual("path/to/requirements.md")
normalizer.save_bundle(result.bundle, "artifacts/context_bundle.json")
```

### Mocked MCP/resource payloads (testable)

```python
from harness.integrations.mcp_context import ContextIntake, ContextSourceConfig, MCPServerConfig

intake = ContextIntake(servers=[
    MCPServerConfig(name="jira", kind="jira", auth_env="JIRA_TOKEN"),   # env ref name only
    MCPServerConfig(name="figma", kind="figma", auth_env="FIGMA_TOKEN"),
    MCPServerConfig(name="github", kind="github", auth_env="GITHUB_TOKEN"),
])

bundle = intake.ingest([
    ContextSourceConfig(type="jira", ref="QA-123", server="jira", payload={"key": "QA-123", "fields": {...}}),
    ContextSourceConfig(type="figma", server="figma", payload={"name": "Flow", "file_key": "..."}),
    ContextSourceConfig(type="mcp", server="docs", uri="mcp://docs/prd/checkout", payload={"title": "PRD", ...}),
    ContextSourceConfig(type="manual", payload="# Notes\n## Risk Areas\n- payments"),
])
intake.normalizer.save_bundle(bundle, "artifacts/context_bundle.json")
```

### Fallback behavior

If a source/adapter is unavailable or a configured MCP server is disabled, `ContextIntake` records the reason in provenance and uses `manual_fallback` (or a safe generated fallback) when `fallback_to_manual=True`.

## Demo

```bash
# Uses mocked Jira/Figma/GitHub/manual payloads (no live MCP required)
PYTHONPATH=. apps/cell/.venv/bin/python scripts/normalize_context_bundle.py \
  --out artifacts/examples/008.1/context_bundle.json
```

Committed example: `docs/examples/context_bundle.normalized.008.1.json`.

## Security notes

- Never pass API tokens/secrets in `ContextSourceConfig.payload`, metadata, or saved bundles.
- Use `MCPServerConfig.auth_env` / env var references only.
- `ContextNormalizer.save_bundle` applies recursive redaction and marks `provenance.redacted` when redaction occurs.
- Review `harness/policy/redaction.py` patterns when adding new secret formats.

## Next (EPIC-E2B-008)

- **008.2**: `CompiledExecutionTestPlan` schema + validator/quality gate.
- **008.3**: Gemini compiler consumes normalized `ContextBundle` and produces validated compiled plans.
- **008.5**: Gemini computer-use runner consumes only compiled plan + minimal runtime config; raw MCP payloads remain control-plane only.
