"""Agent session wiring: provider + context + MCP registry + planner/executor."""

from __future__ import annotations

import json
from typing import Any, Protocol

from cell.config import Settings

from .citations import CitationResolver
from .context import ContextClient, StaticContextClient, WorkspaceContextClient
from .executor import Emit, Executor
from .mcp import FakeMCPClient, MCPClient, ToolRegistry
from .planner import Planner
from .playwright import PlaywrightMCPClient
from .provider import FakeProvider, Provider, ProviderBudget, build_provider
from .types import AgentResult, Completion, Plan


class SecretBroker(Protocol):
    def get_secret(self, path: str) -> str: ...


class AgentSession:
    def __init__(
        self,
        *,
        provider: Provider,
        context: ContextClient,
        registry: ToolRegistry,
        max_steps: int = 12,
        block_on_a11y: bool = True,
        max_repetitions: int = 2,
        close: Any = None,
    ):
        self.provider = provider
        self.context = context
        self.registry = registry
        self._close = close
        resolver = CitationResolver(context)
        self.planner = Planner(provider, context, resolver, max_steps=max_steps)
        self.executor = Executor(
            resolver,
            registry,
            block_on_a11y_violation=block_on_a11y,
            max_repetitions=max_repetitions,
        )

    async def plan(self, goal: str) -> Plan:
        tools = await self.registry.list_tools("executor")
        return await self.planner.plan(goal, tools=tools)

    async def execute(
        self,
        plan: Plan,
        *,
        is_cancelled: Any = lambda: False,
        emit: Emit | None = None,
    ) -> AgentResult:
        return await self.executor.execute(plan, is_cancelled=is_cancelled, emit=emit)

    async def close(self) -> None:
        if self._close is not None:
            await self._close()


def build_agent_session(
    settings: Settings,
    secrets: SecretBroker,
    run: Any,
    *,
    provider: Provider | None = None,
    mcp: MCPClient | None = None,
    context: ContextClient | None = None,
) -> AgentSession:
    policy = run.policy or {}
    provider_name = str(policy.get("provider", "fake"))
    provider = provider or _provider_from_policy(settings, secrets, policy, provider_name)
    context = context or _context_from_policy(settings, policy)
    tools = policy.get("tools")
    allowed_by_role = tools if isinstance(tools, dict) else None
    if mcp is None:
        if str(policy.get("browser", "")).lower() == "playwright":
            mcp = PlaywrightMCPClient(
                workspace_dir=f"{settings.workspace_dir}/{run.run_id}",
                allow_network=bool(policy.get("allow_network", False)),
                allowed_hosts=[str(host) for host in policy.get("allowed_hosts") or []],
            )
        else:
            mcp = FakeMCPClient()
    registry = ToolRegistry(mcp, allowed_by_role=allowed_by_role)
    return AgentSession(
        provider=provider,
        context=context,
        registry=registry,
        max_steps=int(policy.get("max_steps", 12)),
        block_on_a11y=bool((policy.get("a11y") or {}).get("block_on_violation", True)),
        max_repetitions=int(policy.get("max_repetitions", 2)),
        close=getattr(mcp, "close", None),
    )


def _provider_from_policy(
    settings: Settings,
    secrets: SecretBroker,
    policy: dict[str, Any],
    provider_name: str,
) -> Provider:
    if provider_name.lower() == "fake":
        raw_plan = policy.get("fake_plan")
        if raw_plan:
            return FakeProvider([Completion(text=json.dumps(raw_plan))])
        return FakeProvider()
    secret_path = str(policy.get("secret_path", "factory/llm"))
    api_key = secrets.get_secret(secret_path)
    max_tokens = int(policy.get("max_tokens", settings.max_agent_tokens))
    return build_provider(
        provider_name,
        api_key=api_key,
        model=policy.get("model"),
        base_url=policy.get("base_url"),
        max_retries=int(policy.get("max_retries", 3)),
        budget=ProviderBudget(max_tokens=max_tokens),
    )


def _context_from_policy(settings: Settings, policy: dict[str, Any]) -> ContextClient:
    root = policy.get("fixture_path") or settings.fixture_repo_path
    if root:
        return WorkspaceContextClient(str(root))
    return StaticContextClient([])
