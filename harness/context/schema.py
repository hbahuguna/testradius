from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceRef(BaseModel):
    """Provenance/reference for a context source (no secrets)."""

    source_type: str = Field(..., description="jira|figma|github|doc|manual|mcp|url|file|unknown")
    ref: str = Field(..., description="Human/machine reference: issue key, URL, file path, resource URI")
    title: Optional[str] = None
    uri: Optional[str] = Field(default=None, description="Canonical URI/URL when available")
    tool: Optional[str] = Field(default=None, description="Tool/adapter/MCP server+resource used")
    fetched_at: Optional[str] = Field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Non-secret metadata only")


class UIDesignRef(BaseModel):
    """UI/design reference (e.g. Figma frame/link + notes)."""

    kind: str = Field(default="design", description="figma|screenshot|spec|mockup|component|other")
    ref: str = Field(..., description="URL, frame ID, or reference identifier")
    title: Optional[str] = None
    notes: Optional[str] = None
    source_ref: Optional[str] = None  # points to SourceRef.ref when applicable
    metadata: Dict[str, Any] = Field(default_factory=dict)


class APIConstraint(BaseModel):
    """API/data constraint relevant to test planning (non-secret)."""

    name: str
    description: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    data_shape: Optional[Dict[str, Any]] = None
    constraints: List[str] = Field(default_factory=list)
    source_ref: Optional[str] = None


class Provenance(BaseModel):
    """How normalized context was assembled."""

    normalized_at: str = Field(default_factory=utc_now_iso)
    normalizer: str = Field(default="harness.context.normalize")
    adapters: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    redacted: bool = Field(default=False, description="True if redaction was applied during normalization")


class ContextBundle(BaseModel):
    """Normalized requirement/context bundle for compiled test-plan generation.

    Backward-compatible with the original minimal schema (ticket_id/title/figma_links/etc.).
    New fields support MCP/manual intake, provenance, and richer compiler input.
    """

    # Backward-compatible fields
    ticket_id: str = Field(default="", description="Ticket/issue ID (legacy convenience)")
    title: str = Field(default="")
    summary: Optional[str] = Field(default=None, description="Short summary; falls back to title when absent")
    description: Optional[str] = None
    acceptance_criteria: List[str] = Field(default_factory=list)
    figma_links: List[HttpUrl] = Field(default_factory=list)
    prd_link: Optional[HttpUrl] = None
    prior_bugs: List[str] = Field(default_factory=list)
    env_details: Dict[str, Any] = Field(default_factory=dict)
    repo: Optional[str] = None
    branch: Optional[str] = None

    # Normalized 008.1 fields
    source_refs: List[SourceRef] = Field(default_factory=list)
    user_flows: List[str] = Field(default_factory=list)
    ui_design_refs: List[UIDesignRef] = Field(default_factory=list)
    api_data_constraints: List[APIConstraint] = Field(default_factory=list)
    env_build_info: Dict[str, Any] = Field(default_factory=dict)
    risk_areas: List[str] = Field(default_factory=list)
    out_of_scope: List[str] = Field(default_factory=list)
    provenance: Optional[Provenance] = None

    def effective_summary(self) -> str:
        return (self.summary or self.title or "").strip()

    def to_compiler_input(self) -> Dict[str, Any]:
        """Return a JSON-safe, normalized dict suitable as compiler input."""
        data = self.model_dump(mode="json")
        # Keep env refs/names only; normalization/redaction should already have removed values.
        return data
