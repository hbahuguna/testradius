"""CLI interface (textbook Ch.3/Ch.4: a scriptable entry point).

  sdet-agent generate --url https://testradius.dev/jobs \
      --scenario "Submit application form..." \
      --output test.spec.ts [--no-qwen] [--multi-agent]

Uses argparse (stdlib) so it runs without extra installs; swap to Click if
desired. Exits non-zero on failure so it composes in pipelines.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core.agent import Agent
from ..core.multiagent import MultiAgentOrchestrator
from ..core.tracer import Tracer


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sdet-agent",
        description="Generate Playwright tests via an AI-agent (Sense-Plan-Act-Learn).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Generate a Playwright test from a scenario")
    g.add_argument("--url", required=True, help="URL under test")
    g.add_argument("--scenario", required=True, help="Natural-language test scenario")
    g.add_argument("--session-id", default="", help="Optional session id")
    g.add_argument("--output", "-o", default="", help="Write generated code to this file")
    g.add_argument("--no-qwen", action="store_true", help="Disable Qwen SLM (rules only)")
    g.add_argument("--multi-agent", action="store_true", help="Use the multi-agent flow")
    g.add_argument("--trace", default="", help="Write a JSONL trace to this path")
    g.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    g.add_argument("--stream", action="store_true", help="Stream live think/content/tool events (OpenCode-style)")

    # Agentic test execution (Slack-style goal-driven browser runs)
    ax = sub.add_parser("execute", help="Run a goal-driven agentic test in a live browser")
    ax.add_argument("--url", required=True, help="URL under test")
    ax.add_argument("--goal", required=True, help="Natural-language goal for the agent")
    ax.add_argument("--assert", action="append", default=[], metavar="TYPE:EXPECTED", dest="assert_",
                    help="Assertion TYPE:EXPECTED (type=visibility|text|url). Repeatable.")
    ax.add_argument("--assert-url", default="", help="Regex the final URL must match")
    ax.add_argument("--spec", default="", help="Path to a YAML/JSON goal spec (overrides --url/--goal/--assert)")
    ax.add_argument("--backend", default="mcp", choices=["mcp", "cli"], help="Browser backend")
    ax.add_argument("--no-headless", action="store_true", help="Show the browser window")
    ax.add_argument("--max-turns", type=int, default=30, help="Max agent turns before stopping")
    ax.add_argument("--output", "-o", default="", help="Write the JSON execution trace to this file")
    ax.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    ax.add_argument("--stream", action="store_true", help="Stream live think/content/tool events (OpenCode-style)")

    # Self-healing for failing deterministic tests
    hx = sub.add_parser("heal", help="Self-heal a failing Playwright test via live re-exploration")
    hx.add_argument("--test", required=True, help="Path to the failing Playwright test file")
    hx.add_argument("--error", default="", help="Error output from the failing run")
    hx.add_argument("--url", default="", help="URL under test (where the failure occurs)")
    hx.add_argument("--line", type=int, default=0, help="Approximate failing line number")
    hx.add_argument("--backend", default="mcp", choices=["mcp", "cli"], help="Browser backend")
    hx.add_argument("--no-headless", action="store_true", help="Show the browser window")
    hx.add_argument("--output", "-o", default="", help="Write the healed test code to this file")
    hx.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    hx.add_argument("--stream", action="store_true", help="Stream live think/content/tool events (OpenCode-style)")

    # MCP server subcommands
    mcp_parser = sub.add_parser("mcp-server", help="Run the MCP server (STDIO or SSE)")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    stdio_cmd = mcp_sub.add_parser("run-stdio", help="Run MCP server over STDIO")

    sse_cmd = mcp_sub.add_parser("run-sse", help="Run MCP server over SSE (HTTP)")
    sse_cmd.add_argument("--host", default="127.0.0.1", help="SSE host")
    sse_cmd.add_argument("--port", type=int, default=8765, help="SSE port")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "generate":
        tracer = Tracer(enabled=bool(args.trace))
        if args.multi_agent:
            orchestrator = MultiAgentOrchestrator(tracer=tracer)
            result = orchestrator.run(args.url, args.scenario, args.session_id)
            success = result["success"]
            code = result["generated_code"]
            meta = {
                "success": success,
                "final_node": result["final_node"],
                "handoffs": result["handoffs"],
                "trace_summary": result["trace_summary"],
                "error": result["error"],
            }
        else:
            agent = Agent(tracer=tracer, use_qwen=not args.no_qwen)
            if args.stream:
                from ..core.events import LoggingEmitter

                emitter = LoggingEmitter()
                res = agent.run_stream(emitter, args.url, args.scenario, args.session_id)
            else:
                res = agent.run(args.url, args.scenario, args.session_id)
            success = res.success
            code = res.generated_code
            meta = {
                "success": res.success,
                "final_node": res.final_node,
                "trace_summary": res.trace_summary,
                "guardrail_used_fallback": res.to_dict().get("journal") and True,
                "error": res.error,
            }

        if args.trace:
            tracer.to_jsonl(args.trace)

        if args.json:
            import json

            print(json.dumps({"code": code, **meta}, indent=2))
        else:
            print(code)
            if not success:
                print(f"\n[agent] generation did not fully succeed: {meta.get('error')}", file=sys.stderr)

        if args.output and code:
            Path(args.output).write_text(code, encoding="utf-8")
            if not args.json:
                print(f"\n[saved] {args.output}")

        return 0 if success else 1

    elif args.command == "execute":
        from ..core.agentic_executor import AgenticExecutor
        from ..specs.goal_spec import load_goal_spec_file

        headless = not args.no_headless
        assertions: list[dict] = []
        for a in args.assert_:
            if ":" in a:
                atype, _, expected = a.partition(":")
                if atype == "url":
                    assertions.append({"type": "url", "pattern": expected, "description": expected})
                elif atype == "text":
                    assertions.append({"type": "text", "expected": expected, "description": expected})
                else:
                    # visibility (default): the `expected` string is the locator
                    # target the executor checks for visibility.
                    assertions.append(
                        {"type": "visibility", "target": expected, "expected": expected, "description": expected}
                    )

        if args.assert_url:
            assertions.append({"type": "url", "pattern": args.assert_url, "description": args.assert_url})

        goal, url = args.goal, args.url
        if args.spec:
            spec = load_goal_spec_file(args.spec)
            goal, url = spec.goal, spec.url
            assertions = spec.assertion_dicts()

        emitter = None
        if args.stream:
            from ..core.events import LoggingEmitter

            emitter = LoggingEmitter()

        ex = AgenticExecutor(emitter=emitter, max_turns=args.max_turns, backend=args.backend, headless=headless)
        res = ex.run(goal=goal, url=url, assertions=assertions)
        out = res.to_dict()
        if args.output:
            import json as _json

            Path(args.output).write_text(_json.dumps(out, indent=2, default=str), encoding="utf-8")
            if not args.json:
                print(f"\n[saved trace] {args.output}")
        if args.json:
            import json as _json

            print(_json.dumps(out, indent=2, default=str))
        else:
            print(f"\nsuccess={res.success} goal_reached={res.goal_reached} steps={len(res.trace.steps)}")
            if res.error:
                print(f"error: {res.error}", file=sys.stderr)
        return 0 if res.success else 1

    elif args.command == "heal":
        from ..core.self_healer import SelfHealer

        headless = not args.no_headless
        emitter = None
        if args.stream:
            from ..core.events import LoggingEmitter

            emitter = LoggingEmitter()

        healer = SelfHealer(emitter=emitter, backend=args.backend, headless=headless)
        res = healer.heal(test_path=args.test, error_output=args.error, url=args.url, failing_line=args.line)
        out = res.to_dict()
        if args.output and res.healed_code:
            Path(args.output).write_text(res.healed_code, encoding="utf-8")
            if not args.json:
                print(f"\n[saved healed] {args.output}")
        if args.json:
            import json as _json

            print(_json.dumps(out, indent=2, default=str))
        else:
            print(f"\nsuccess={res.success} changed={res.changed_locators}")
            if res.error:
                print(f"error: {res.error}", file=sys.stderr)
            if res.healed_code:
                print("\n----- healed test -----")
                print(res.healed_code)
        return 0 if res.success else 1

    elif args.command == "mcp-server":
        from .mcp_server import MCPServer, build_registry

        registry = build_registry()
        server = MCPServer(registry)
        if args.mcp_command == "run-stdio":
            server.run_stdio()
        elif args.mcp_command == "run-sse":
            server.run_sse(host=args.host, port=args.port)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
