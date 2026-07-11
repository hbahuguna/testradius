# SDET Agent

**Standalone AI Agent for Playwright Test Generation (Sense-Plan-Act-Learn)**

This package implements a full-stack AI agent designed to generate high-quality Playwright UI automation tests from natural language scenarios. It leverages advanced AI agent patterns, including a 16-node reasoning graph, a fine-tuned Qwen SLM, deterministic guardrails, structured tracing, and multi-agent orchestration.

## Architecture & AI Agent Patterns

This agent is built upon the five functional layers and core agent loop described in the AI agent textbook:

1.  **Persona (Layer 1)**: The agent adopts the persona of an "expert Senior SDET" with deep Playwright knowledge. System prompts for each node guide its behavior.
2.  **Tools & Actions (Layer 2)**: A `ToolRegistry` provides access to various functionalities:
    *   **Core Tools (Direct Calls)**: `page_fetch` (for HTML content), `dom_analyze` (for interactive elements), and `session_tools` (for managing the test generation session state). These are called directly by the agent for efficiency.
    *   **External Tools (MCP Exposed)**: `file_read` and `file_save` are exposed via an MCP server. This adheres to the "hybrid" pattern, allowing an external orchestrator to control sensitive file system access.
3.  **Reasoning & Planning (Layer 3)**: The agent navigates a 16-node procedure graph, dynamically deciding its next steps. Generative nodes (N2, N5, N9, N11, N14) utilize a fine-tuned Qwen SLM for sophisticated analysis and code generation. Routing nodes (N3, N6, N8, N15) use deterministic, rule-based logic for reliable decision-making.
4.  **Knowledge & Memory (Layer 4)**:
    *   **Scratchpad (Short-Term Memory)**: A `Scratchpad` records summarized events and decisions, providing continuous context across the multi-step reasoning process.
    *   **Repo Awareness (Long-Term Knowledge)**: `PageObjectStore` discovers existing Playwright Page Objects (classes, locators, methods) in the `artifacts/e2e-tests/pages` directory. `RepoScanner` identifies common test patterns and utility functions, enabling the agent to generate idiomatic and consistent test code.
5.  **Evaluation & Feedback (Layer 5)**: A suite of deterministic `Guardrails` validates the generated test code:
    *   `code_validity`: Checks for syntactic correctness (using tree-sitter or heuristics).
    *   `locator_strategy`: Ensures adherence to accessible locator best practices (e.g., `getByRole` over raw CSS).
    *   `assertion_coverage`: Verifies that actions have corresponding assertions.
    Failed guardrails trigger a `retry_loop`, providing feedback to the Qwen SLM for self-correction, or falling back to rule-based templates after multiple failures.

### Multi-Agent Flow (Ch.4: Handoffs)

The agent employs a sequential multi-agent flow over the 16-node graph. Three specialized `RoleAgent`s (`Planner`, `Builder`, `Validator`) each own a segment of the graph, managing their own scoped memory. Handoffs occur at segment boundaries, passing the `AgentState` (a shared thread of context) downstream.

## Interfaces

The SDET Agent can be interacted with via three distinct interfaces:

1.  **CLI (Command-Line Interface)**: For scriptable, pipeline-friendly test generation.
    ```bash
    python -m sdet_agent generate --url <target_url> \
        --scenario "<natural_language_scenario>" \
        --output <output_file.ts> \
        [--no-qwen] [--multi-agent] [--trace <trace.jsonl>] [--json]
    ```
    *   `mcp-server run-stdio`: Run the MCP server over standard I/O.
    *   `mcp-server run-sse`: Run the MCP server over Server-Sent Events (HTTP).

2.  **HTTP API (FastAPI)**: Exposes agent functionality as a RESTful service.
    ```bash
    uvicorn sdet_agent.interfaces.http_server:app --port 8000
    ```
    Endpoints:
    *   `GET /health`: Liveness probe.
    *   `POST /v1/generate`: Generate test code from URL and scenario.
    *   `WS /v1/stream`: WebSocket for streaming real-time agent progress (spans, outputs).
    *   `GET /v1/tools`: List available tools (MCP-compatible format).

3.  **MCP Server (Model Context Protocol)**: Adheres to the Anthropic JSON-RPC 2.0 standard, allowing any MCP-compatible client (e.g., OpenCode, Claude Code) to seamlessly interact with the agent's tools. Supports both STDIO and SSE transports.

## Quick Start

```bash
# From the testradius-sdet-agent worktree root
cd /path/to/testradius-sdet-agent

# Install the sdet-agent package in editable mode with dev dependencies
# (Ensure your .venv has Python 3.12+ activated)
/path/to/testradius/.venv/bin/pip install -e '.[dev]' --no-deps

# Example: Generate a test via CLI (single agent, rule-based fallback)
python -m sdet_agent generate \
  --url "https://testradius.dev/jobs" \
  --scenario "Submit application form for Freelance Full-Stack Developer with name Himanshu and email jdoe@example.com, click Submit" \
  --output my_test.spec.ts \
  --no-qwen

# Example: Run the MCP server over STDIO (for external clients)
# In one terminal:
python -m sdet_agent mcp-server run-stdio

# In another terminal (send an MCP request):
# echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | nc -q0 localhost 8765 # This is wrong for STDIO, just example
# Correct for STDIO: pipe directly into the process as shown in tests.

# Example: Run the HTTP API server
# uvicorn sdet_agent.interfaces.http_server:app --port 8000 --reload
```

## Development

To manage this package during development, ensure your Python virtual environment is active and use standard development practices.

### Running Tests

```bash
# From apps/sdet-agent directory:
pytest
```
