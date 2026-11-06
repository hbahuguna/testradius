"""Config-driven context intake with MCP/manual fallback and provenance (008.1)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from harness.context.normalization import ContextNormalizer
from harness.context.schema import ContextBundle, Provenance, SourceRef

from .adapters import AdapterUnavailableError, get_adapter


Fetcher = Callable[[Mapping[str, Any]], Any]


@dataclass
class MCPServerConfig:
    """Configured MCP server/tool mapping (control plane). No secrets stored."""

    name: str
    kind: str = "generic"  # jira|figma|github|docs|generic
    enabled: bool = True
    # References to env/config only - never token values.
    auth_env: Optional[str] = None
    url_env: Optional[str] = None
    tool_prefix: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_safe_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "enabled": self.enabled,
            "auth_env": self.auth_env,
            "url_env": self.url_env,
            "tool_prefix": self.tool_prefix,
            "metadata": self.metadata,
        }


@dataclass
class ContextSourceConfig:
    """One context source to intake."""

    type: str  # jira|figma|github|doc|manual|mcp|file|url
    ref: Optional[str] = None
    payload: Any = None  # pre-fetched payload/content (preferred for tests/manual/MCP resource reads)
    uri: Optional[str] = None
    server: Optional[str] = None  # MCP server name
    tool: Optional[str] = None
    title: Optional[str] = None
    mime_type: Optional[str] = None
    fallback_to_manual: bool = True
    manual_fallback: Any = None  # explicit manual payload to use if primary unavailable
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContextIntake:
    """Normalize configured sources into a merged ContextBundle with provenance/fallback."""

    def __init__(
        self,
        *,
        servers: Optional[Sequence[MCPServerConfig]] = None,
        normalizer: Optional[ContextNormalizer] = None,
        mcp_fetcher: Optional[Fetcher] = None,
    ):
        self.servers = {s.name: s for s in (servers or [])}
        self.normalizer = normalizer or ContextNormalizer()
        self.mcp_fetcher = mcp_fetcher

    def ingest(self, sources: Sequence[Union[ContextSourceConfig, Mapping[str, Any]]]) -> ContextBundle:
        merged = ContextBundle(provenance=Provenance(normalizer="harness.integrations.mcp_context.intake", adapters=[]))
        for raw in sources:
            src = raw if isinstance(raw, ContextSourceConfig) else ContextSourceConfig(**dict(raw))
            bundle = self._ingest_one(src)
            merged = self.normalizer.merge(bundle, base=merged)
        # final safety pass
        safe, redacted = self.normalizer.redact_data(merged.to_compiler_input(), path="context_bundle")
        if redacted:
            merged = ContextBundle.model_validate(safe)
            merged.provenance = merged.provenance or Provenance()
            merged.provenance.redacted = True
        if merged.provenance and not merged.provenance.adapters:
            merged.provenance.adapters.append("manual")
        return merged

    def ingest_and_save(self, sources: Sequence[Union[ContextSourceConfig, Mapping[str, Any]]], path: Union[str, Path]) -> Path:
        bundle = self.ingest(sources)
        return self.normalizer.save_bundle(bundle, path)

    def _ingest_one(self, src: ContextSourceConfig) -> ContextBundle:
        source_type = (src.type or "manual").lower()
        cfg = {
            "ref": src.ref,
            "uri": src.uri,
            "server": src.server,
            "tool": src.tool or self._tool_for(src),
            "title": src.title,
            "mime_type": src.mime_type,
            "fetched_at": None,
            **(src.metadata or {}),
        }
        server_cfg = self.servers.get(src.server) if src.server else None
        if server_cfg and not server_cfg.enabled:
            return self._fallback(src, reason=f"MCP server '{src.server}' disabled")
        if server_cfg and server_cfg.auth_env:
            cfg.setdefault("auth_env_ref", server_cfg.auth_env)  # ref name only, never value
        if source_type == "mcp" and self.mcp_fetcher and src.payload is None:
            cfg["fetcher"] = self.mcp_fetcher
        try:
            adapter = get_adapter(source_type, normalizer=self.normalizer)
            if not adapter.available(cfg):
                raise AdapterUnavailableError(f"Adapter '{source_type}' unavailable")
            result = adapter.normalize(src.payload, config=cfg)
            return result.bundle
        except AdapterUnavailableError as e:
            return self._fallback(src, reason=str(e))
        except Exception as e:
            if src.fallback_to_manual:
                return self._fallback(src, reason=f"{type(e).__name__}: {e}")
            raise

    def _tool_for(self, src: ContextSourceConfig) -> Optional[str]:
        if src.tool:
            return src.tool
        if src.server:
            return f"mcp:{src.server}"
        return None

    def _fallback(self, src: ContextSourceConfig, *, reason: str) -> ContextBundle:
        payload = src.manual_fallback if src.manual_fallback is not None else (src.payload if src.payload is not None else {
            "title": src.title or src.ref or f"{src.type} context",
            "description": f"Primary {src.type} source unavailable; using manual fallback. Reason: {reason}",
            "ticket_id": src.ref or "",
        })
        res = self.normalizer.from_manual(payload, source_ref=src.ref or src.uri)
        bundle = res.bundle
        bundle.provenance = bundle.provenance or Provenance()
        bundle.provenance.adapters = [f"fallback.manual({src.type})"]
        bundle.provenance.warnings.append(reason)
        bundle.provenance.redacted = bundle.provenance.redacted or res.redacted
        # Preserve intended source ref provenance
        bundle.source_refs.insert(0, SourceRef(source_type=src.type, ref=src.ref or src.uri or "unavailable", title=src.title, uri=src.uri, tool=self._tool_for(src), metadata={"fallback": True, "reason": reason}))
        return bundle
