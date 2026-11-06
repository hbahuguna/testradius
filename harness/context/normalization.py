"""Normalize manual/MCP/resource inputs into a ContextBundle (STORY-E2B-008.1).

Design goals:
- Control-plane intake only: adapters map source payloads to normalized context.
- No secrets/tokens persisted in bundles/artifacts; env/config refs only.
- Provenance recorded (source refs, timestamps, adapter/tool).
- Manual fallback when MCP/server/source unavailable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from harness.policy.redaction import Redactor

from .schema import APIConstraint, ContextBundle, Provenance, SourceRef, UIDesignRef, utc_now_iso

_SECRET_KEY_RE = re.compile(r"(?i)(^|[_\-])(api[_\-]?key|token|secret|password|passwd|authorization|cookie|session|credential|private[_\-]?key)($|[_\-])")
_ENV_REF_RE = re.compile(r"\$\{?([A-Z][A-Z0-9_]{1,})\}?")


@dataclass
class NormalizationResult:
    bundle: ContextBundle
    warnings: List[str]
    redacted: bool


class ContextNormalizer:
    """Normalize heterogeneous inputs into a safe, provenance-rich ContextBundle."""

    def __init__(self, *, redactor: Optional[Redactor] = None):
        self.redactor = redactor or Redactor()

    def redact_data(self, value: Any, *, path: str = "") -> tuple[Any, bool]:
        """Redact secrets recursively. Returns (value, redacted?)."""
        redacted = False
        if isinstance(value, str):
            out = self.redactor.redact(value)
            # Also replace obvious env-assignment-looking secrets only when key/path hints secret.
            if _SECRET_KEY_RE.search(path) and out == value and not _ENV_REF_RE.fullmatch(value.strip()):
                return "[REDACTED]", True
            return out, out != value
        if isinstance(value, Mapping):
            out: Dict[str, Any] = {}
            for k, v in value.items():
                key = str(k)
                child_path = f"{path}.{key}" if path else key
                if _SECRET_KEY_RE.search(key):
                    if isinstance(v, str) and _ENV_REF_RE.fullmatch(v.strip()):
                        out[key], r = self.redact_data(v, path=child_path)
                    elif v in (None, ""):
                        out[key], r = v, False
                    else:
                        out[key], r = "[REDACTED]", True
                else:
                    out[key], r = self.redact_data(v, path=child_path)
                redacted = redacted or r
            return out, redacted
        if isinstance(value, (list, tuple)):
            items = []
            for i, v in enumerate(value):
                nv, r = self.redact_data(v, path=f"{path}[{i}]")
                items.append(nv)
                redacted = redacted or r
            return items, redacted
        return value, False

    def merge(self, *bundles: Optional[ContextBundle], base: Optional[ContextBundle] = None) -> ContextBundle:
        merged = base.model_copy(deep=True) if base else ContextBundle()
        for b in bundles:
            if b is None:
                continue
            if not merged.ticket_id and b.ticket_id:
                merged.ticket_id = b.ticket_id
            if not merged.title and b.title:
                merged.title = b.title
            if not merged.summary and b.summary:
                merged.summary = b.summary
            if not merged.description and b.description:
                merged.description = b.description
            elif b.description and merged.description and b.description not in merged.description:
                merged.description = merged.description.rstrip() + "\n\n" + b.description
            for lst_name in ("acceptance_criteria", "user_flows", "prior_bugs", "risk_areas", "out_of_scope"):
                dst = getattr(merged, lst_name)
                for item in getattr(b, lst_name, []) or []:
                    if item and item not in dst:
                        dst.append(item)
            for lst_name in ("figma_links", "source_refs", "ui_design_refs", "api_data_constraints"):
                dst = getattr(merged, lst_name)
                for item in getattr(b, lst_name, []) or []:
                    if item not in dst:
                        dst.append(item)
            if b.prd_link and not merged.prd_link:
                merged.prd_link = b.prd_link
            for k, v in (b.env_details or {}).items():
                merged.env_details.setdefault(k, v)
            for k, v in (b.env_build_info or {}).items():
                merged.env_build_info.setdefault(k, v)
            for k, v in ({"repo": b.repo, "branch": b.branch}).items():
                if v and not getattr(merged, k):
                    setattr(merged, k, v)
            if b.provenance:
                if not merged.provenance:
                    merged.provenance = b.provenance
                else:
                    for a in b.provenance.adapters:
                        if a not in merged.provenance.adapters:
                            merged.provenance.adapters.append(a)
                    for w in b.provenance.warnings:
                        if w not in merged.provenance.warnings:
                            merged.provenance.warnings.append(w)
                    merged.provenance.redacted = merged.provenance.redacted or b.provenance.redacted
        if not merged.provenance:
            merged.provenance = Provenance()
        return merged

    def from_manual(self, payload: Union[str, Mapping[str, Any], Path], *, source_ref: Optional[str] = None, adapter: str = "manual") -> NormalizationResult:
        """Normalize manual input (text/markdown, JSON, dict, or file path)."""
        warnings: List[str] = []
        if isinstance(payload, Path) or (isinstance(payload, str) and Path(payload).exists() and len(payload) < 4096):
            p = Path(payload)
            text = p.read_text(encoding="utf-8")
            ref = source_ref or str(p)
            if p.suffix.lower() == ".json":
                try:
                    data = json.loads(text)
                except Exception as e:
                    warnings.append(f"Manual JSON parse failed, using raw text: {e}")
                    data = {"title": p.stem, "description": text}
            else:
                data = _parse_manual_text(text, title=p.stem)
            data.setdefault("_source_ref", ref)
            data.setdefault("_source_type", "file")
            data.setdefault("_tool", "manual.file")
        elif isinstance(payload, Mapping):
            data = dict(payload)
            data.setdefault("_source_type", "manual")
            data.setdefault("_tool", "manual.input")
        elif isinstance(payload, str):
            s = payload.strip()
            if s.startswith("{") or s.startswith("["):
                try:
                    data = json.loads(s)
                    if not isinstance(data, Mapping):
                        data = {"description": s}
                    data.setdefault("_source_type", "manual")
                    data.setdefault("_tool", "manual.json")
                except Exception:
                    data = _parse_manual_text(s)
                    data["_source_type"] = "manual"
                    data["_tool"] = "manual.text"
            else:
                data = _parse_manual_text(s)
                data["_source_type"] = "manual"
                data["_tool"] = "manual.text"
        else:
            raise TypeError(f"Unsupported manual payload type: {type(payload)}")
        if source_ref:
            data.setdefault("_source_ref", source_ref)
        bundle, redacted = self._bundle_from_mapping(data, adapter=adapter)
        warnings.extend(bundle.provenance.warnings if bundle.provenance else [])
        return NormalizationResult(bundle=bundle, warnings=warnings, redacted=redacted)

    def from_mcp_resource(
        self,
        *,
        server: str,
        uri: str,
        content: Union[str, Mapping[str, Any], Sequence[Any]],
        mime_type: Optional[str] = None,
        name: Optional[str] = None,
        source_type: str = "mcp",
        fetched_at: Optional[str] = None,
    ) -> NormalizationResult:
        """Normalize an MCP resource payload/content already fetched by a caller/tool."""
        data: Dict[str, Any]
        if isinstance(content, Mapping):
            data = dict(content)
        elif isinstance(content, (list, tuple)):
            data = {"items": list(content), "description": json.dumps(content, ensure_ascii=False)[:4000]}
        else:
            text = str(content)
            if mime_type and "json" in mime_type or text.lstrip().startswith(("{", "[")):
                try:
                    parsed = json.loads(text)
                    data = dict(parsed) if isinstance(parsed, Mapping) else {"items": parsed, "description": text[:4000]}
                except Exception:
                    data = {"title": name or uri, "description": text}
            else:
                data = _parse_manual_text(text, title=name or uri)
        data.setdefault("title", name or uri)
        data.setdefault("_source_type", source_type)
        data.setdefault("_source_ref", uri)
        data.setdefault("_tool", f"mcp:{server}")
        data.setdefault("_mcp_server", server)
        data.setdefault("_mcp_uri", uri)
        data.setdefault("_fetched_at", fetched_at or utc_now_iso())
        bundle, redacted = self._bundle_from_mapping(data, adapter=f"mcp.{server}")
        return NormalizationResult(bundle=bundle, warnings=bundle.provenance.warnings if bundle.provenance else [], redacted=redacted)

    def save_bundle(self, bundle: ContextBundle, path: Union[str, Path]) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        safe, redacted = self.redact_data(bundle.to_compiler_input(), path="context_bundle")
        if redacted and bundle.provenance:
            bundle.provenance.redacted = True
            safe["provenance"] = bundle.provenance.model_dump(mode="json")
            safe["provenance"]["redacted"] = True
        p.write_text(json.dumps(safe, indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    def _bundle_from_mapping(self, data: Mapping[str, Any], *, adapter: str) -> tuple[ContextBundle, bool]:
        raw = dict(data)
        safe_raw, redacted = self.redact_data(raw, path="context")
        d: Dict[str, Any] = safe_raw if isinstance(safe_raw, dict) else {"description": str(safe_raw)}

        source_ref = d.pop("_source_ref", None) or d.get("url") or d.get("uri") or d.get("id")
        source_type = str(d.pop("_source_type", d.get("source_type") or "manual"))
        tool = d.pop("_tool", adapter)
        fetched_at = d.pop("_fetched_at", None)
        mcp_server = d.pop("_mcp_server", None)
        mcp_uri = d.pop("_mcp_uri", None)

        title = str(d.get("title") or d.get("name") or d.get("summary") or "").strip()
        ticket_id = str(d.get("ticket_id") or d.get("issue_key") or d.get("key") or d.get("id") or source_ref or "").strip()
        summary = d.get("summary") or title
        description = d.get("description") or d.get("body") or d.get("content")
        if isinstance(description, (dict, list)):
            description = json.dumps(description, ensure_ascii=False, indent=2)
        ac = _coerce_str_list(d.get("acceptance_criteria") or d.get("ac") or d.get("acceptanceCriteria") or [])
        flows = _coerce_str_list(d.get("user_flows") or d.get("flows") or [])
        risks = _coerce_str_list(d.get("risk_areas") or d.get("risks") or [])
        out_of_scope = _coerce_str_list(d.get("out_of_scope") or d.get("outOfScope") or [])
        prior_bugs = _coerce_str_list(d.get("prior_bugs") or d.get("bugs") or [])

        figma_links = _coerce_url_list(d.get("figma_links") or d.get("figmaLinks") or [])
        prd_link = _coerce_optional_url(d.get("prd_link") or d.get("prdLink") or d.get("prd"))
        ui_refs = _coerce_ui_refs(d.get("ui_design_refs") or d.get("design_refs") or d.get("ui_refs") or [], figma_links)
        api_constraints = _coerce_api_constraints(d.get("api_data_constraints") or d.get("api_constraints") or [])
        source_refs = _coerce_source_refs(d.get("source_refs") or [], fallback=SourceRef(
            source_type=source_type, ref=str(source_ref or ticket_id or title or "manual"),
            title=title or None, uri=mcp_uri or (str(source_ref) if source_ref and str(source_ref).startswith(("http", "mcp://", "file:")) else None),
            tool=tool, fetched_at=fetched_at, metadata={k: v for k, v in {"mcp_server": mcp_server}.items() if v}
        ) if (source_ref or ticket_id or title) else None)

        bundle = ContextBundle(
            ticket_id=ticket_id,
            title=title,
            summary=str(summary).strip() if summary else (title or None),
            description=str(description).strip() if description else None,
            acceptance_criteria=ac,
            figma_links=figma_links,
            prd_link=prd_link,
            prior_bugs=prior_bugs,
            env_details=d.get("env_details") if isinstance(d.get("env_details"), dict) else {},
            repo=d.get("repo"),
            branch=d.get("branch"),
            source_refs=source_refs,
            user_flows=flows,
            ui_design_refs=ui_refs,
            api_data_constraints=api_constraints,
            env_build_info=d.get("env_build_info") if isinstance(d.get("env_build_info"), dict) else {},
            risk_areas=risks,
            out_of_scope=out_of_scope,
            provenance=Provenance(adapters=[adapter], warnings=[], redacted=redacted),
        )
        return bundle, redacted


def _parse_manual_text(text: str, *, title: Optional[str] = None) -> Dict[str, Any]:
    lines = [l.rstrip() for l in text.splitlines()]
    data: Dict[str, Any] = {"title": title or "", "description": text.strip(), "acceptance_criteria": [], "user_flows": [], "risk_areas": [], "out_of_scope": []}
    section = None
    for line in lines:
        s = line.strip()
        if not s:
            continue
        low = s.lower().strip("#: ")
        if low in {"acceptance criteria", "ac", "acceptance"}:
            section = "acceptance_criteria"; continue
        if low in {"user flows", "flows", "steps", "user journey"}:
            section = "user_flows"; continue
        if low in {"risks", "risk areas", "risk"}:
            section = "risk_areas"; continue
        if low in {"out of scope", "out-of-scope", "non goals", "non-goals"}:
            section = "out_of_scope"; continue
        if s.startswith("#") and not data["title"]:
            data["title"] = s.lstrip("# ").strip(); continue
        if section and re.match(r"^([-*]|\d+[.)])\s+", s):
            item = re.sub(r"^([-*]|\d+[.)])\s+", "", s).strip()
            if item:
                data[section].append(item)
            continue
        if not data["title"] and len(s) < 140 and not s.startswith("http"):
            data["title"] = s
    # Extract URLs as figma/design refs opportunistically
    urls = re.findall(r"https?://[^\s)>\]]+", text)
    data["figma_links"] = [u.rstrip(".,") for u in urls if "figma.com" in u]
    data["source_refs"] = [{"source_type": "manual", "ref": title or "manual-input", "title": data["title"] or None, "tool": "manual.text"}]
    return data


def _coerce_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip("-* \t") for p in re.split(r"\n+", value) if p.strip()]
        return parts if parts else ([value.strip()] if value.strip() else [])
    if isinstance(value, Sequence):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def _coerce_url_list(value: Any) -> List[str]:
    out: List[str] = []
    for item in _coerce_str_list(value) if not isinstance(value, str) else ([value] if value else []):
        s = str(item).strip()
        if s.startswith("http://") or s.startswith("https://"):
            out.append(s)
    if isinstance(value, Sequence) and not isinstance(value, str):
        for item in value:
            if isinstance(item, str) and item.startswith(("http://", "https://")) and item not in out:
                out.append(item)
    return out


def _coerce_optional_url(value: Any) -> Optional[str]:
    urls = _coerce_url_list([value] if value is not None else [])
    return urls[0] if urls else None


def _coerce_ui_refs(value: Any, figma_links: Sequence[str]) -> List[UIDesignRef]:
    refs: List[UIDesignRef] = []
    seen = set()
    if isinstance(value, Sequence) and not isinstance(value, str):
        for item in value:
            if isinstance(item, UIDesignRef):
                refs.append(item); seen.add(item.ref); continue
            if isinstance(item, Mapping):
                ref = str(item.get("ref") or item.get("url") or item.get("uri") or "").strip()
                if not ref or ref in seen:
                    continue
                refs.append(UIDesignRef(kind=str(item.get("kind") or "design"), ref=ref, title=item.get("title"), notes=item.get("notes"), source_ref=item.get("source_ref"), metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {}))
                seen.add(ref)
            elif isinstance(item, str) and item.strip() and item.strip() not in seen:
                refs.append(UIDesignRef(ref=item.strip())); seen.add(item.strip())
    for url in figma_links:
        if url not in seen:
            refs.append(UIDesignRef(kind="figma", ref=url, title="Figma design"))
            seen.add(url)
    return refs


def _coerce_api_constraints(value: Any) -> List[APIConstraint]:
    out: List[APIConstraint] = []
    if isinstance(value, Sequence) and not isinstance(value, str):
        for item in value:
            if isinstance(item, APIConstraint):
                out.append(item)
            elif isinstance(item, Mapping):
                name = str(item.get("name") or item.get("endpoint") or item.get("title") or "constraint")
                out.append(APIConstraint(name=name, description=item.get("description"), endpoint=item.get("endpoint"), method=item.get("method"), data_shape=item.get("data_shape") if isinstance(item.get("data_shape"), dict) else None, constraints=_coerce_str_list(item.get("constraints")), source_ref=item.get("source_ref")))
            elif isinstance(item, str) and item.strip():
                out.append(APIConstraint(name=item.strip()[:80], description=item.strip()))
    elif isinstance(value, str) and value.strip():
        out.append(APIConstraint(name="api_constraint", description=value.strip()))
    return out


def _coerce_source_refs(value: Any, fallback: Optional[SourceRef]) -> List[SourceRef]:
    refs: List[SourceRef] = []
    if isinstance(value, Sequence) and not isinstance(value, str):
        for item in value:
            if isinstance(item, SourceRef):
                refs.append(item)
            elif isinstance(item, Mapping):
                ref = str(item.get("ref") or item.get("uri") or item.get("id") or "").strip()
                if not ref:
                    continue
                refs.append(SourceRef(source_type=str(item.get("source_type") or "unknown"), ref=ref, title=item.get("title"), uri=item.get("uri"), tool=item.get("tool"), fetched_at=item.get("fetched_at"), metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {}))
    if not refs and fallback:
        refs.append(fallback)
    return refs
