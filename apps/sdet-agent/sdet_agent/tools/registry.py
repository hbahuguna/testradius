"""Tool registry: the agent's hands (textbook Ch.2).

A central registry maps tool names to functions and their JSON-schema
definitions. The agent calls tools by name through `call()`. The same
registry is surfaced to MCP clients, so internal direct calls and external
MCP calls share one source of truth (the "USB-C" idea from Ch.3).
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core.events import EV_TOOL_CALL, EV_TOOL_RESULT, get_emitter


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict  # JSON Schema object
    func: Callable[..., Any]
    external: bool = False  # True => expose only via MCP (hybrid pattern)

    def to_mcp(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        func: Callable[..., Any],
        description: str,
        input_schema: Optional[dict] = None,
        external: bool = False,
    ) -> None:
        if input_schema is None:
            input_schema = self._infer_schema(func)
        self._tools[name] = ToolSpec(
            name=name, description=description, input_schema=input_schema, func=func, external=external
        )

    @staticmethod
    def _infer_schema(func: Callable[..., Any]) -> dict:
        sig = inspect.signature(func)
        props: dict[str, Any] = {}
        required: list[str] = []
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            props[pname] = {"type": "string"}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        return {"type": "object", "properties": props, "required": required}

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_specs(self, external_only: bool = False) -> list[ToolSpec]:
        return [t for t in self._tools.values() if (t.external or not external_only)]

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"Unknown tool: {name}")
        emitter = get_emitter()
        args = arguments or {}
        if emitter is not None:
            emitter.emit(EV_TOOL_CALL, name=name, arguments=args)
        try:
            result = spec.func(**args)
        except Exception as exc:  # noqa: BLE001
            if emitter is not None:
                emitter.emit(EV_TOOL_RESULT, name=name, ok=False, error=str(exc))
            raise
        if emitter is not None:
            try:
                rendered = result if isinstance(result, str) else json.dumps(result, default=str)
            except (TypeError, ValueError):
                rendered = str(result)
            emitter.emit(EV_TOOL_RESULT, name=name, ok=True, result=rendered[:2000])
        return result

    def names(self) -> list[str]:
        return list(self._tools.keys())
