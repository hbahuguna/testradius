"""Context retrieval with stable node ids (E2-S7).

The Sprint 3 implementation is deliberately local-first: it indexes the fixture
repository and returns file/symbol nodes with stable ids. A graph-backed client
can replace it without changing the planner or citation resolver.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
_SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".md", ".json", ".yml", ".yaml"}
_SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=", re.MULTILINE),
)


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
    async def retrieve(self, query: str, *, limit: int = 12) -> list[ContextNode]: ...

    async def get(self, node_id: str) -> ContextNode | None: ...


class StaticContextClient:
    """Small deterministic client for tests and for callers that already know nodes."""

    def __init__(self, nodes: list[ContextNode] | None = None):
        self.nodes = list(nodes or [])
        self._by_id = {node.node_id: node for node in self.nodes}

    async def retrieve(self, query: str, *, limit: int = 12) -> list[ContextNode]:
        terms = _terms(query)
        ranked = sorted(
            self.nodes,
            key=lambda node: _score(node, terms),
            reverse=True,
        )
        return ranked[:limit] if terms else ranked[:limit]

    async def get(self, node_id: str) -> ContextNode | None:
        return self._by_id.get(node_id)


class WorkspaceContextClient:
    """Index a local fixture checkout once, then retrieve ranked nodes."""

    def __init__(self, root: str | Path, *, max_file_bytes: int = 120_000):
        self.root = Path(root)
        self.max_file_bytes = max_file_bytes
        self._nodes: list[ContextNode] | None = None
        self._by_id: dict[str, ContextNode] = {}

    async def retrieve(self, query: str, *, limit: int = 12) -> list[ContextNode]:
        if self._nodes is None:
            self._index()
        terms = _terms(query)
        ranked = sorted(self._nodes or [], key=lambda node: _score(node, terms), reverse=True)
        return ranked[:limit]

    async def get(self, node_id: str) -> ContextNode | None:
        if self._nodes is None:
            self._index()
        return self._by_id.get(node_id)

    def _index(self) -> None:
        nodes: list[ContextNode] = []
        self._by_id = {}
        if not self.root.exists():
            self._nodes = []
            return
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or any(part in _IGNORED_PARTS for part in path.parts):
                continue
            if path.suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
                text = path.read_text(errors="replace")
            except OSError:
                continue
            relative = path.relative_to(self.root).as_posix()
            file_node = ContextNode(
                node_id=f"file:{relative}",
                kind="file",
                path=relative,
                label=relative,
                content=text,
                metadata={"suffix": path.suffix},
            )
            nodes.append(file_node)
            self._by_id[file_node.node_id] = file_node
            for name in _symbols(text):
                symbol = ContextNode(
                    node_id=f"symbol:{relative}:{name}",
                    kind="symbol",
                    path=relative,
                    label=name,
                    content=_symbol_excerpt(text, name),
                    metadata={"symbol": name},
                )
                nodes.append(symbol)
                self._by_id[symbol.node_id] = symbol
        self._nodes = nodes


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
