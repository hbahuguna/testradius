"""Source adapters for normalizing Jira/Figma/GitHub/docs/manual/MCP payloads."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from harness.context.normalization import ContextNormalizer, NormalizationResult
from harness.context.schema import APIConstraint, ContextBundle, SourceRef, UIDesignRef


class AdapterUnavailableError(RuntimeError):
    """Raised when a configured source/MCP server is unavailable; caller may fall back to manual."""


class BaseContextAdapter:
    source_type: str = "unknown"

    def __init__(self, *, normalizer: Optional[ContextNormalizer] = None):
        self.normalizer = normalizer or ContextNormalizer()

    def available(self, config: Optional[Mapping[str, Any]] = None) -> bool:
        return True

    def normalize(self, payload: Any, *, config: Optional[Mapping[str, Any]] = None) -> NormalizationResult:
        raise NotImplementedError


class ManualContextAdapter(BaseContextAdapter):
    source_type = "manual"

    def normalize(self, payload: Any, *, config: Optional[Mapping[str, Any]] = None) -> NormalizationResult:
        cfg = dict(config or {})
        return self.normalizer.from_manual(payload, source_ref=cfg.get("source_ref") or cfg.get("ref"))


class MCPResourceAdapter(BaseContextAdapter):
    source_type = "mcp"

    def available(self, config: Optional[Mapping[str, Any]] = None) -> bool:
        cfg = dict(config or {})
        # Available when caller provides already-fetched content, or an explicit fetcher exists.
        return bool(cfg.get("content") is not None or cfg.get("payload") is not None or cfg.get("resource") is not None or cfg.get("fetcher"))

    def normalize(self, payload: Any, *, config: Optional[Mapping[str, Any]] = None) -> NormalizationResult:
        cfg = dict(config or {})
        content = payload if payload is not None else cfg.get("content", cfg.get("resource"))
        if content is None and cfg.get("fetcher"):
            try:
                content = cfg["fetcher"](cfg)
            except Exception as e:
                raise AdapterUnavailableError(f"MCP fetcher unavailable/failed for {cfg.get('server')}:{cfg.get('uri')}: {e}") from e
        if content is None:
            raise AdapterUnavailableError("MCP resource content not provided and no fetcher configured")
        server = str(cfg.get("server") or cfg.get("mcp_server") or "unknown")
        uri = str(cfg.get("uri") or cfg.get("resource_uri") or cfg.get("ref") or "mcp://unknown")
        return self.normalizer.from_mcp_resource(
            server=server,
            uri=uri,
            content=content,
            mime_type=cfg.get("mime_type") or cfg.get("mimeType"),
            name=cfg.get("name") or cfg.get("title"),
            source_type=str(cfg.get("source_type") or "mcp"),
            fetched_at=cfg.get("fetched_at"),
        )


class JiraContextAdapter(BaseContextAdapter):
    source_type = "jira"

    def normalize(self, payload: Any, *, config: Optional[Mapping[str, Any]] = None) -> NormalizationResult:
        cfg = dict(config or {})
        if payload is None and not cfg.get("allow_empty"):
            raise AdapterUnavailableError("Jira payload unavailable; provide issue JSON/export or use manual fallback")
        data = _as_mapping(payload)
        fields = _as_mapping(data.get("fields")) if isinstance(data.get("fields"), Mapping) else {}
        key = str(data.get("key") or data.get("issue_key") or data.get("id") or cfg.get("ref") or "").strip()
        summary = data.get("summary") or fields.get("summary") or data.get("title")
        description = data.get("description") or fields.get("description")
        description = _adf_or_text(description)
        ac = _extract_acceptance_criteria(description, data, fields)
        labels = _str_list(data.get("labels") or fields.get("labels"))
        components = [c.get("name") if isinstance(c, Mapping) else c for c in (fields.get("components") or [])]
        components = [str(c) for c in components if c]
        links = _extract_urls(description)
        figma = [u for u in links if "figma.com" in u]
        issue_links = []
        for link in (fields.get("issuelinks") or data.get("issuelinks") or []):
            if not isinstance(link, Mapping):
                continue
            for side in ("outwardIssue", "inwardIssue"):
                issue = _as_mapping(link.get(side))
                if issue.get("key"):
                    issue_links.append(str(issue["key"]))
        normalized = {
            "ticket_id": key,
            "title": str(summary or key or "Jira issue").strip(),
            "summary": str(summary).strip() if summary else None,
            "description": description,
            "acceptance_criteria": ac,
            "user_flows": _extract_section_items(description, ["steps to reproduce", "user flow", "flow", "scenario"]),
            "risk_areas": labels + components,
            "prior_bugs": issue_links,
            "figma_links": figma,
            "ui_design_refs": [{"kind": "figma", "ref": u, "source_ref": key, "notes": "Extracted from Jira description"} for u in figma],
            "env_build_info": {k: v for k, v in {
                "project": (_as_mapping(fields.get("project")) or {}).get("key") or data.get("project"),
                "issuetype": (_as_mapping(fields.get("issuetype")) or {}).get("name") or data.get("issuetype"),
                "status": (_as_mapping(fields.get("status")) or {}).get("name") or data.get("status"),
                "priority": (_as_mapping(fields.get("priority")) or {}).get("name") or data.get("priority"),
            }.items() if v},
            "source_refs": [SourceRef(source_type="jira", ref=key or str(cfg.get("ref") or "jira"), title=str(summary or key or "").strip() or None, uri=cfg.get("uri") or data.get("self") or data.get("url"), tool=cfg.get("tool") or "mcp.jira")],
            "_source_type": "jira",
            "_tool": cfg.get("tool") or "mcp.jira",
        }
        return self.normalizer.from_manual(normalized, source_ref=key or cfg.get("ref"), adapter=f"mcp.{cfg.get('server') or 'jira'}" if cfg.get('tool') or cfg.get('server') else 'jira')


class FigmaContextAdapter(BaseContextAdapter):
    source_type = "figma"

    def normalize(self, payload: Any, *, config: Optional[Mapping[str, Any]] = None) -> NormalizationResult:
        cfg = dict(config or {})
        if payload is None:
            raise AdapterUnavailableError("Figma payload unavailable; provide file/node metadata or use manual fallback")
        data = _as_mapping(payload)
        file_key = str(data.get("file_key") or data.get("key") or cfg.get("file_key") or "").strip()
        name = data.get("name") or data.get("title") or cfg.get("title") or "Figma design"
        node_id = data.get("node_id") or cfg.get("node_id")
        url = data.get("url") or cfg.get("uri") or cfg.get("ref")
        if not url and file_key:
            url = f"https://www.figma.com/file/{file_key}" + (f"?node-id={node_id}" if node_id else "")
        description = data.get("description") or data.get("summary") or _figma_summary(data)
        ui_refs = [UIDesignRef(kind="figma", ref=str(url or file_key or name), title=str(name), notes=description[:2000] if isinstance(description, str) else None, source_ref=str(url or file_key or name), metadata={k: v for k, v in {"file_key": file_key, "node_id": node_id, "last_modified": data.get("lastModified") or data.get("last_modified")}.items() if v})]
        # Include child/frame names as flow/design hints
        frames = []
        for node in _iter_figma_nodes(data):
            n = node.get("name")
            t = node.get("type")
            if n and t in {"FRAME", "COMPONENT", "COMPONENT_SET", "SECTION", "PAGE", "SCREEN", None}:
                frames.append(f"{t or 'NODE'}: {n}" if t else str(n))
            if len(frames) >= 50:
                break
        normalized = {
            "title": str(name),
            "summary": str(name),
            "description": description,
            "user_flows": frames[:20],
            "ui_design_refs": [r.model_dump(mode="json") for r in ui_refs],
            "figma_links": [str(url)] if url else [],
            "source_refs": [SourceRef(source_type="figma", ref=str(url or file_key or name), title=str(name), uri=str(url) if url else None, tool=cfg.get("tool") or "mcp.figma", metadata={"file_key": file_key, "node_id": node_id})],
            "_source_type": "figma",
            "_tool": cfg.get("tool") or "mcp.figma",
        }
        return self.normalizer.from_manual(normalized, source_ref=str(url or file_key or name), adapter=f"mcp.{cfg.get('server') or 'figma'}" if cfg.get('tool') or cfg.get('server') else 'figma')


class GitHubContextAdapter(BaseContextAdapter):
    source_type = "github"

    def normalize(self, payload: Any, *, config: Optional[Mapping[str, Any]] = None) -> NormalizationResult:
        cfg = dict(config or {})
        if payload is None:
            raise AdapterUnavailableError("GitHub payload unavailable; provide issue/PR/doc JSON or use manual fallback")
        data = _as_mapping(payload)
        number = data.get("number") or data.get("issue_number") or data.get("pr_number")
        repo = data.get("repository") or cfg.get("repo")
        if isinstance(repo, Mapping):
            repo = repo.get("full_name") or repo.get("name")
        title = data.get("title") or data.get("name") or "GitHub item"
        body = _adf_or_text(data.get("body") or data.get("description") or data.get("content"))
        url = data.get("html_url") or data.get("url") or cfg.get("uri") or cfg.get("ref")
        kind = "pull_request" if ("pull_request" in data or data.get("head") or data.get("base") or cfg.get("kind") == "pr") else "issue"
        ref = f"{repo}#{number}" if repo and number else (str(url) if url else str(title))
        ac = _extract_acceptance_criteria(body, data)
        files = []
        for f in (data.get("files") or data.get("changed_files") or []):
            if isinstance(f, Mapping):
                files.append(str(f.get("filename") or f.get("path") or f.get("name") or "")).strip() if f else None
            elif isinstance(f, str):
                files.append(f)
        files = [f for f in files if f]
        normalized = {
            "ticket_id": ref,
            "title": str(title),
            "summary": str(title),
            "description": body,
            "acceptance_criteria": ac,
            "repo": str(repo) if repo else None,
            "branch": (_as_mapping(data.get("head")) or {}).get("ref") or data.get("branch"),
            "risk_areas": _str_list(data.get("labels"))[:10],
            "api_data_constraints": [{"name": f"changed_file:{p}", "description": f"GitHub {kind} changed file"} for p in files[:20]],
            "figma_links": [u for u in _extract_urls(body) if "figma.com" in u],
            "source_refs": [SourceRef(source_type="github", ref=ref, title=str(title), uri=str(url) if url else None, tool=cfg.get("tool") or "mcp.github", metadata={"kind": kind, "state": data.get("state")})],
            "_source_type": "github",
            "_tool": cfg.get("tool") or "mcp.github",
        }
        return self.normalizer.from_manual(normalized, source_ref=ref, adapter=f"mcp.{cfg.get('server') or 'github'}" if cfg.get('tool') or cfg.get('server') else 'github')


class DocsContextAdapter(BaseContextAdapter):
    source_type = "doc"

    def normalize(self, payload: Any, *, config: Optional[Mapping[str, Any]] = None) -> NormalizationResult:
        cfg = dict(config or {})
        if payload is None:
            raise AdapterUnavailableError("Doc payload unavailable; provide doc content/resource or use manual fallback")
        if isinstance(payload, (str, bytes)) or (isinstance(payload, Mapping) and "text" in payload and not payload.get("title")):
            text = payload.get("text") if isinstance(payload, Mapping) else (payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload))
            adapter_name = f"mcp.{cfg.get('server') or 'docs'}" if (cfg.get('tool') or cfg.get('server')) else 'docs'
            res = self.normalizer.from_manual(text, source_ref=cfg.get("ref") or cfg.get("uri"), adapter=adapter_name)
            if res.bundle.source_refs:
                res.bundle.source_refs[0].source_type = "doc"
                res.bundle.source_refs[0].tool = cfg.get("tool") or adapter_name
                if cfg.get("uri"):
                    res.bundle.source_refs[0].uri = str(cfg["uri"])
            return res
        data = _as_mapping(payload)
        data.setdefault("_source_type", "doc")
        data.setdefault("_tool", cfg.get("tool") or "mcp.docs")
        data.setdefault("_source_ref", cfg.get("ref") or cfg.get("uri") or data.get("uri") or data.get("url"))
        adapter_name = f"mcp.{cfg.get('server') or 'docs'}" if (cfg.get('tool') or cfg.get('server')) else 'docs'
        return self.normalizer.from_manual(data, source_ref=str(data.get("_source_ref") or "doc"), adapter=adapter_name)


ADAPTERS = {
    "manual": ManualContextAdapter,
    "file": ManualContextAdapter,
    "text": ManualContextAdapter,
    "url": ManualContextAdapter,
    "mcp": MCPResourceAdapter,
    "jira": JiraContextAdapter,
    "figma": FigmaContextAdapter,
    "github": GitHubContextAdapter,
    "doc": DocsContextAdapter,
    "docs": DocsContextAdapter,
    "prd": DocsContextAdapter,
}


def get_adapter(source_type: str, *, normalizer: Optional[ContextNormalizer] = None) -> BaseContextAdapter:
    cls = ADAPTERS.get((source_type or "manual").lower(), ManualContextAdapter)
    return cls(normalizer=normalizer)


# helpers

def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _str_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence):
        out = []
        for v in value:
            if isinstance(v, Mapping) and v.get("name"):
                out.append(str(v["name"]))
            elif v is not None and str(v).strip():
                out.append(str(v))
        return out
    return []


def _extract_urls(text: Any) -> List[str]:
    import re
    if not isinstance(text, str):
        return []
    return re.findall(r"https?://[^\s)>\]\"']+", text)


def _adf_or_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        # Atlassian Document Format - emit markdown-ish text so AC extractor works.
        if value.get("type") == "doc" or "content" in value:
            lines: List[str] = []
            buf: List[str] = []

            def _collect_text(node: Any) -> str:
                out: List[str] = []

                def _walk_text(n: Any) -> None:
                    if isinstance(n, Mapping):
                        t = n.get("type")
                        if t == "text" and n.get("text"):
                            out.append(str(n["text"]))
                        elif t == "inlineCard":
                            url = (n.get("attrs") or {}).get("url")
                            if url:
                                out.append(str(url))
                        elif t == "hardBreak":
                            out.append("\n")
                        for c in n.get("content") or []:
                            _walk_text(c)
                    elif isinstance(n, list):
                        for c in n:
                            _walk_text(c)

                _walk_text(node)
                return "".join(out).strip()

            def flush(prefix: str = ""):
                text = "".join(buf).strip()
                if text:
                    lines.append(prefix + text if prefix else text)
                buf.clear()

            def walk(node: Any):
                if isinstance(node, Mapping):
                    t = node.get("type")
                    if t == "heading":
                        level = int((node.get("attrs") or {}).get("level") or 2)
                        lines.append("#" * min(6, level) + " " + _collect_text(node))
                        return
                    if t == "listItem":
                        text = _collect_text(node)
                        if text:
                            lines.append("- " + text)
                        return
                    if t == "text" and node.get("text"):
                        buf.append(str(node["text"]))
                    elif t == "hardBreak":
                        buf.append("\n")
                    elif t == "inlineCard":
                        url = (node.get("attrs") or {}).get("url")
                        if url:
                            buf.append(str(url))
                    elif t in {"paragraph", "bulletList", "orderedList", "doc"}:
                        for c in node.get("content") or []:
                            walk(c)
                        if t == "paragraph":
                            flush()
                    else:
                        for c in node.get("content") or []:
                            walk(c)
                elif isinstance(node, list):
                    for c in node:
                        walk(c)

            walk(value)
            flush()
            return "\n".join(l for l in lines if l.strip()).strip() or None
        return json_dumps_safe(value)
    return str(value)


def _extract_acceptance_criteria(description: Optional[str], *sources: Any) -> List[str]:
    import re
    ac: List[str] = []
    for src in sources:
        if isinstance(src, Mapping):
            for key in ("acceptance_criteria", "ac", "acceptanceCriteria", "customfield_acceptance_criteria"):
                v = src.get(key)
                if isinstance(v, str):
                    ac.extend([s.strip("-* \t") for s in v.splitlines() if s.strip()])
                elif isinstance(v, Sequence) and not isinstance(v, str):
                    ac.extend([str(x).strip() for x in v if str(x).strip()])
    if description:
        # find AC section
        m = re.search(r"(?im)^#+\s*(acceptance criteria|ac)\s*$([\s\S]*?)(^#+\s+|\Z)", description)
        block = m.group(2) if m else description
        for line in block.splitlines():
            s = line.strip()
            if re.match(r"^([-*]|\d+[.)]|\[[ xX]\])\s+", s):
                item = re.sub(r"^([-*]|\d+[.)]|\[[ xX]\])\s+", "", s).strip()
                if item and item not in ac:
                    ac.append(item)
    # de-dupe preserve order
    seen=set(); out=[]
    for x in ac:
        if x not in seen: seen.add(x); out.append(x)
    return out[:50]


def _extract_section_items(text: Optional[str], headings: Sequence[str]) -> List[str]:
    import re
    if not text:
        return []
    for h in headings:
        m = re.search(rf"(?im)^#+\s*{re.escape(h)}\s*$([\s\S]*?)(^#+\s+|\Z)", text)
        if m:
            items = []
            for line in m.group(1).splitlines():
                s = line.strip()
                if re.match(r"^([-*]|\d+[.)])\s+", s):
                    items.append(re.sub(r"^([-*]|\d+[.)])\s+", "", s).strip())
            if items:
                return items
    return []


def _iter_figma_nodes(data: Mapping[str, Any]):
    stack = [data]
    if isinstance(data.get("document"), Mapping):
        stack.append(data["document"])
    if isinstance(data.get("nodes"), Mapping):
        stack.extend(v for v in data["nodes"].values() if isinstance(v, Mapping))
    while stack:
        node = stack.pop()
        yield node
        for c in node.get("children") or []:
            if isinstance(c, Mapping):
                stack.append(c)


def _figma_summary(data: Mapping[str, Any]) -> str:
    parts = []
    for k in ("name", "lastModified", "version", "role", "editorType"):
        if data.get(k): parts.append(f"{k}: {data[k]}")
    doc = _as_mapping(data.get("document"))
    if doc.get("name"): parts.append(f"document: {doc['name']}")
    return "\n".join(parts) if parts else "Figma design metadata"


def json_dumps_safe(value: Any) -> str:
    import json
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value)
