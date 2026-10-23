"""Context retrieval with stable node ids (E2-S7).

The Sprint 3 implementation is deliberately local-first: it indexes the fixture
repository and returns file, symbol, route, and prior-test nodes with stable ids.
A graph-backed client can replace it without changing the planner or citation
resolver. ``FallbackContextClient`` records when the graph is unavailable so the
run event can show that the filesystem/AST view was used instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

_IGNORED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
}
_SOURCE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".html",
    ".md",
    ".json",
    ".yml",
    ".yaml",
}
_SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=", re.MULTILINE),
)
_TOKEN_CHARS = 4


class ContextUnavailable(Exception):
    """A primary context source (typically the graph) cannot be reached."""


@dataclass(frozen=True)
class ContextNode:
    node_id: str
    kind: str
    path: str
    label: str
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "path": self.path,
            "label": self.label,
            "metadata": self.metadata,
        }


class ContextClient(Protocol):
    source: str

    async def retrieve(self, query: str, *, limit: int = 12) -> list[ContextNode]: ...

    async def get(self, node_id: str) -> ContextNode | None: ...


class StaticContextClient:
    """Small deterministic client for tests and callers that know the nodes."""

    source = "static"

    def __init__(self, nodes: list[ContextNode] | None = None, *, token_budget: int = 0):
        self.nodes = list(nodes or [])
        self._by_id = {node.node_id: node for node in self.nodes}
        self.token_budget = token_budget
        self.cache_hits = 0
        self.cache_misses = 0
        self.truncated_nodes = 0
        self.last_budget_used = 0
        self._retrieved = False

    async def retrieve(self, query: str, *, limit: int = 12) -> list[ContextNode]:
        self._mark_cache(self._retrieved)
        self._retrieved = True
        terms = _terms(query)
        ranked = sorted(
            self.nodes,
            key=lambda node: _score(node, terms),
            reverse=True,
        )
        return _budget(self, ranked[:limit])

    async def get(self, node_id: str) -> ContextNode | None:
        node = self._by_id.get(node_id)
        self._mark_cache(node is not None)
        return node

    def _mark_cache(self, hit: bool) -> None:
        if hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1


class WorkspaceContextClient:
    """Index a local fixture checkout once, then retrieve ranked nodes."""

    source = "filesystem"

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = 120_000,
        token_budget: int = 6000,
        prior_tests: list[ContextNode] | None = None,
    ):
        self.root = Path(root)
        self.max_file_bytes = max_file_bytes
        self.token_budget = token_budget
        self.prior_tests = list(prior_tests or [])
        self._nodes: list[ContextNode] | None = None
        self._by_id: dict[str, ContextNode] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self.truncated_nodes = 0
        self.last_budget_used = 0

    async def retrieve(self, query: str, *, limit: int = 12) -> list[ContextNode]:
        self._ensure_index()
        terms = _terms(query)
        ranked = sorted(self._nodes or [], key=lambda node: _score(node, terms), reverse=True)
        return _budget(self, ranked[:limit])

    async def get(self, node_id: str) -> ContextNode | None:
        self._ensure_index()
        node = self._by_id.get(node_id)
        if node is None:
            self.cache_misses += 1
        else:
            self.cache_hits += 1
        return node

    def _ensure_index(self) -> None:
        if self._nodes is not None:
            self.cache_hits += 1
            return
        self.cache_misses += 1
        self._index()

    def _index(self) -> None:
        nodes: list[ContextNode] = []
        self._by_id = {}
        if not self.root.exists():
            self._nodes = []
            return

        for prior in self.prior_tests:
            _add_node(nodes, self._by_id, prior)

        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            try:
                relative_path = path.relative_to(self.root)
            except ValueError:
                continue
            if any(part in _IGNORED_PARTS for part in relative_path.parts):
                continue
            if path.suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
                text = path.read_text(errors="replace")
            except OSError:
                continue

            relative = relative_path.as_posix()
            file_node = ContextNode(
                node_id=f"file:{relative}",
                kind="file",
                path=relative,
                label=relative,
                content=text,
                metadata={"suffix": path.suffix},
            )
            _add_node(nodes, self._by_id, file_node)

            for name in _symbols(text):
                _add_node(
                    nodes,
                    self._by_id,
                    ContextNode(
                        node_id=f"symbol:{relative}:{name}",
                        kind="symbol",
                        path=relative,
                        label=name,
                        content=_symbol_excerpt(text, name),
                        metadata={"symbol": name},
                    ),
                )

            route = _route_for(relative_path)
            if route:
                _add_node(
                    nodes,
                    self._by_id,
                    ContextNode(
                        node_id=f"route:{route}",
                        kind="route",
                        path=relative,
                        label=route,
                        content=text,
                        metadata={"route": route, "source_file": relative},
                    ),
                )

            if _is_test_path(relative_path):
                _add_node(
                    nodes,
                    self._by_id,
                    ContextNode(
                        node_id=f"test:{relative}",
                        kind="test",
                        path=relative,
                        label=relative,
                        content=text,
                        metadata={"prior_test": True},
                    ),
                )

        self._nodes = nodes


class FallbackContextClient:
    """Use a primary context source and degrade to a local view when it is down.

    Retrieval ids always come from one source within a run. If the primary is
    unavailable, the fallback view is used for both retrieval and citation
    resolution; the run event records ``source`` and ``fallback_used``.
    """

    def __init__(
        self,
        primary: ContextClient,
        fallback: ContextClient,
        *,
        primary_name: str = "graph",
    ):
        self.primary = primary
        self.fallback = fallback
        self.primary_name = primary_name
        self.source = primary_name
        self.fallback_used = False
        self.fallback_reason: str | None = None

    async def retrieve(self, query: str, *, limit: int = 12) -> list[ContextNode]:
        try:
            nodes = await self.primary.retrieve(query, limit=limit)
        except ContextUnavailable as exc:
            self.fallback_used = True
            self.fallback_reason = str(exc) or type(exc).__name__
            self.source = self.fallback.source
            return await self.fallback.retrieve(query, limit=limit)
        self.fallback_used = False
        self.fallback_reason = None
        self.source = self.primary_name
        return nodes

    async def get(self, node_id: str) -> ContextNode | None:
        if self.fallback_used:
            return await self.fallback.get(node_id)
        return await self.primary.get(node_id)

    @property
    def cache_hits(self) -> int:
        active = self.fallback if self.fallback_used else self.primary
        return int(getattr(active, "cache_hits", 0))

    @property
    def cache_misses(self) -> int:
        active = self.fallback if self.fallback_used else self.primary
        return int(getattr(active, "cache_misses", 0))

    @property
    def truncated_nodes(self) -> int:
        active = self.fallback if self.fallback_used else self.primary
        return int(getattr(active, "truncated_nodes", 0))


def context_metadata(client: ContextClient) -> dict[str, Any]:
    return {
        "source": getattr(client, "source", "unknown"),
        "fallback_used": bool(getattr(client, "fallback_used", False)),
        "fallback_reason": getattr(client, "fallback_reason", None),
        "cache_hits": int(getattr(client, "cache_hits", 0)),
        "cache_misses": int(getattr(client, "cache_misses", 0)),
        "truncated_nodes": int(getattr(client, "truncated_nodes", 0)),
    }


def estimate_tokens(text: str) -> int:
    """Cheap deterministic estimate suitable for budgeting, not billing."""

    return max(1, (len(text) + _TOKEN_CHARS - 1) // _TOKEN_CHARS)


def _budget(client: Any, nodes: list[ContextNode]) -> list[ContextNode]:
    budget = int(getattr(client, "token_budget", 0) or 0)
    client.last_budget_used = 0
    client.truncated_nodes = 0
    if not budget:
        return nodes

    kept: list[ContextNode] = []
    used = 0
    for node in nodes:
        cost = estimate_tokens(node.label) + estimate_tokens(node.content)
        if used + cost <= budget:
            kept.append(node)
            used += cost
            continue
        remaining = budget - used
        if remaining >= 8:
            kept.append(
                replace(
                    node,
                    content=node.content[: remaining * _TOKEN_CHARS],
                    metadata={**node.metadata, "truncated": True},
                )
            )
            used = budget
            client.truncated_nodes = 1
        break
    client.last_budget_used = used
    return kept


def _add_node(
    nodes: list[ContextNode],
    by_id: dict[str, ContextNode],
    node: ContextNode,
) -> None:
    if node.node_id in by_id:
        return
    nodes.append(node)
    by_id[node.node_id] = node


def _terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[A-Za-z0-9_.:/-]{2,}", query.lower()) if term]


def _score(node: ContextNode, terms: list[str]) -> int:
    haystack = f"{node.path} {node.label} {node.content[:4000]}".lower()
    return sum(haystack.count(term) for term in terms)


def _symbols(text: str) -> list[str]:
    names: set[str] = set()
    for pattern in _SYMBOL_PATTERNS:
        names.update(pattern.findall(text))
    return sorted(names)


def _symbol_excerpt(text: str, name: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if name in line:
            return "\n".join(lines[index : index + 8])
    return ""


def _route_for(path: Path) -> str | None:
    if path.suffix.lower() != ".html":
        return None
    parts = {part.lower() for part in path.parts}
    if "public" not in parts and "static" not in parts:
        return None
    if path.stem.lower() == "index":
        return "/"
    return f"/{path.stem}"


def _is_test_path(path: Path) -> bool:
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    return (
        "test" in parts
        or "tests" in parts
        or "__tests__" in parts
        or ".test." in name
        or ".spec." in name
        or name.startswith("test_")
        or name.startswith("verify.")
    )
