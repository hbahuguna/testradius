import json
from pathlib import Path

import pytest

from harness.context import ContextBundle, ContextNormalizer, load_context
from harness.integrations.mcp_context import (
    ContextIntake,
    ContextSourceConfig,
    DocsContextAdapter,
    FigmaContextAdapter,
    GitHubContextAdapter,
    JiraContextAdapter,
    ManualContextAdapter,
    MCPServerConfig,
)


def test_manual_text_normalization_extracts_sections_and_figma_links():
    res = ManualContextAdapter().normalize(
        "# Checkout bug\n\nFix checkout CTA.\n\n## Acceptance Criteria\n- [ ] User can click Place Order\n- Given cart has items\n\nSee https://www.figma.com/file/abc123/Checkout?node-id=1-2\n\n## Risk Areas\n- payment\n"
    )
    b = res.bundle
    assert b.title == "Checkout bug"
    assert any("Place Order" in a for a in b.acceptance_criteria)
    assert any("figma.com/file/abc123" in str(u) for u in b.figma_links)
    assert any(r.source_type == "manual" for r in b.source_refs)
    assert b.provenance and b.provenance.adapters


def test_jira_payload_normalization_maps_fields_and_provenance():
    payload = {
        "key": "QA-123",
        "fields": {
            "summary": "Login form validation",
            "description": "As a user...\n\n## Acceptance Criteria\n- Invalid email shows error\n- Password required\n\nFigma: https://www.figma.com/design/xyz/Login",
            "labels": ["auth", "p1"],
            "components": [{"name": "web"}],
            "project": {"key": "QA"},
            "issuetype": {"name": "Bug"},
            "status": {"name": "To Do"},
            "priority": {"name": "High"},
        },
    }
    res = JiraContextAdapter().normalize(payload, config={"tool": "mcp:jira", "uri": "jira://QA-123"})
    b = res.bundle
    assert b.ticket_id == "QA-123"
    assert b.title == "Login form validation"
    assert "Invalid email shows error" in b.acceptance_criteria
    assert b.env_build_info.get("project") == "QA"
    assert any(r.source_type == "jira" and r.tool == "mcp:jira" for r in b.source_refs)
    assert any("figma.com/design/xyz" in str(u) for u in b.figma_links)


def test_figma_payload_normalization_captures_design_refs_and_frames():
    payload = {
        "name": "Checkout Flow",
        "file_key": "abc123",
        "lastModified": "2026-01-01T00:00:00Z",
        "document": {"name": "Doc", "children": [{"type": "FRAME", "name": "Cart"}, {"type": "FRAME", "name": "Payment"}]},
    }
    res = FigmaContextAdapter().normalize(payload, config={"tool": "mcp:figma"})
    b = res.bundle
    assert "Checkout Flow" in b.title
    assert any(r.kind == "figma" for r in b.ui_design_refs)
    assert any("FRAME: Cart" in f or "Cart" in f for f in b.user_flows)
    assert any("figma.com/file/abc123" in str(u) for u in b.figma_links)
    assert any(r.source_type == "figma" for r in b.source_refs)


def test_github_issue_normalization_maps_repo_and_ac():
    payload = {
        "number": 42,
        "title": "Fix CTA alignment",
        "body": "## Acceptance Criteria\n- CTA aligns on mobile\n- No horizontal scroll",
        "html_url": "https://github.com/acme/web/issues/42",
        "repository": {"full_name": "acme/web"},
        "labels": [{"name": "ui"}],
    }
    res = GitHubContextAdapter().normalize(payload, config={"tool": "mcp:github"})
    b = res.bundle
    assert b.ticket_id == "acme/web#42"
    assert b.repo == "acme/web"
    assert "CTA aligns on mobile" in b.acceptance_criteria
    assert any(r.source_type == "github" for r in b.source_refs)


def test_docs_adapter_normalizes_markdown_resource():
    res = DocsContextAdapter().normalize(
        "# PRD: Search\n\nUsers can search products.\n\n## Acceptance Criteria\n- Results show within 2s",
        config={"uri": "docs://prd/search", "tool": "mcp:docs", "ref": "prd/search"},
    )
    b = res.bundle
    assert "Search" in b.title
    assert b.acceptance_criteria
    assert any(r.source_type == "doc" and r.tool == "mcp:docs" for r in b.source_refs)


def test_intake_merges_sources_and_records_provenance(tmp_path: Path):
    intake = ContextIntake(servers=[MCPServerConfig(name="jira", kind="jira", auth_env="JIRA_TOKEN_ENV_REF")])
    bundle = intake.ingest([
        ContextSourceConfig(type="jira", ref="QA-123", payload={"key": "QA-123", "fields": {"summary": "A", "description": "AC:\n- ok"}}),
        ContextSourceConfig(type="figma", payload={"name": "Flow", "url": "https://www.figma.com/file/f1/x"}),
        ContextSourceConfig(type="manual", payload={"title": "Manual note", "risk_areas": ["payments"], "acceptance_criteria": ["no regression"]}),
    ])
    assert bundle.ticket_id == "QA-123"
    assert any("payments" in r for r in bundle.risk_areas)
    assert any(r.source_type == "jira" for r in bundle.source_refs)
    assert any(r.source_type == "figma" for r in bundle.source_refs)
    assert bundle.provenance and bundle.provenance.adapters
    out = tmp_path / "context_bundle.json"
    intake.ingest_and_save([{"type": "manual", "payload": {"title": "X", "description": "hello"}}], out)
    loaded = load_context(out)
    assert loaded.title == "X"
    raw = json.loads(out.read_text())
    assert raw["provenance"]["normalizer"]


def test_mcp_unavailable_falls_back_to_manual_with_provenance():
    intake = ContextIntake(servers=[MCPServerConfig(name="jira", kind="jira", enabled=False)])
    bundle = intake.ingest([
        ContextSourceConfig(
            type="jira",
            server="jira",
            ref="QA-999",
            manual_fallback={"ticket_id": "QA-999", "title": "Manual fallback", "acceptance_criteria": ["works"]},
        )
    ])
    assert bundle.title == "Manual fallback"
    assert any(r.metadata.get("fallback") for r in bundle.source_refs)
    assert bundle.provenance and any("disabled" in w.lower() or "unavailable" in w.lower() or "fallback" in a.lower() for w in bundle.provenance.warnings for a in bundle.provenance.adapters)


def test_mocked_mcp_resource_payload_normalizes():
    intake = ContextIntake()
    bundle = intake.ingest([
        ContextSourceConfig(
            type="mcp",
            server="docs-server",
            uri="mcp://docs-server/prd/checkout",
            payload={"title": "Checkout PRD", "acceptance_criteria": ["User can pay"], "description": "Checkout flow"},
            tool="mcp:docs-server/read_resource",
            mime_type="application/json",
        )
    ])
    assert bundle.title == "Checkout PRD"
    assert "User can pay" in bundle.acceptance_criteria
    assert any(r.tool == "mcp:docs-server/read_resource" for r in bundle.source_refs)


def test_secrets_are_redacted_not_persisted(tmp_path: Path):
    n = ContextNormalizer()
    res = n.from_manual({
        "title": "Secret case",
        "description": "Use api_key=supersecretvalue123456 and token abcdefghijklmnop",
        "env_details": {"API_KEY": "sk-live-VERYSECRET123456", "SAFE_ENV": "${E2B_API_KEY}", "region": "us-west1"},
        "acceptance_criteria": ["login"],
    })
    out = tmp_path / "bundle.json"
    n.save_bundle(res.bundle, out)
    text = out.read_text()
    assert "supersecretvalue123456" not in text
    assert "VERYSECRET123456" not in text
    assert "abcdefghijklmnop" not in text
    assert "[REDACTED]" in text
    assert "${E2B_API_KEY}" in text or "E2B_API_KEY" in text  # env ref name/value placeholder may remain as ref
    assert "us-west1" in text
    loaded = json.loads(text)
    assert loaded["provenance"]["redacted"] is True


def test_compiler_input_is_json_safe():
    b = ContextBundle(ticket_id="X", title="T", acceptance_criteria=["a"], source_refs=[])
    d = b.to_compiler_input()
    json.dumps(d)  # must not raise
    assert d["ticket_id"] == "X"
