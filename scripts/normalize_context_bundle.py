#!/usr/bin/env python3
"""Demo: Jira/Figma/GitHub/manual input → normalized context_bundle.json (STORY-E2B-008.1).

Uses mocked payloads by default (no live MCP required). Pass --jira-file /tmp/jira-KAN-1.json
(or any REST-exported issue JSON) to normalize a REAL Jira issue instead of the mock.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.integrations.mcp_context import ContextIntake, ContextSourceConfig, MCPServerConfig


MOCK_JIRA = {
    "key": "QA-812",
    "fields": {
        "summary": "Homepage hero CTA routes to contact form",
        "description": "## Acceptance Criteria\n- Clicking primary CTA navigates to /contact\n- Form renders with name/email/message\n- Mobile viewport preserves CTA visibility\n\nDesign: https://www.figma.com/file/demo123/Homepage?node-id=10-20",
        "labels": ["smoke", "homepage"],
        "project": {"key": "QA"},
        "issuetype": {"name": "Story"},
        "status": {"name": "Ready"},
        "priority": {"name": "High"},
    },
}

MOCK_FIGMA = {
    "name": "Homepage redesign",
    "file_key": "demo123",
    "lastModified": "2026-01-10T00:00:00Z",
    "document": {
        "children": [
            {"type": "FRAME", "name": "Desktop hero"},
            {"type": "FRAME", "name": "Mobile hero"},
            {"type": "FRAME", "name": "Contact form"},
        ]
    },
}

MOCK_GITHUB = {
    "number": 128,
    "title": "Add homepage CTA analytics attribute",
    "body": "## Acceptance Criteria\n- CTA includes data-testid='hero-cta'\n- Existing navigation behavior unchanged",
    "html_url": "https://github.com/testradius/web/issues/128",
    "repository": {"full_name": "testradius/web"},
    "labels": [{"name": "frontend"}],
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="artifacts/examples/008.1/context_bundle.json")
    p.add_argument("--manual", help="Optional manual text/JSON file to include")
    p.add_argument("--jira-file", help="Real Jira REST issue JSON (e.g. /tmp/jira-KAN-1.json) — replaces mocked QA-812")
    p.add_argument("--jira-only", action="store_true", help="Use ONLY the Jira source (no demo Figma/GitHub/manual merge)")
    args = p.parse_args()

    if args.jira_file:
        jira_payload = json.loads(Path(args.jira_file).read_text(encoding="utf-8"))
        jira_ref = str(jira_payload.get("key") or "jira")
        jira_source = ContextSourceConfig(type="jira", ref=jira_ref, server="jira", payload=jira_payload, tool="mcp.jira/get_issue")
    else:
        jira_payload = MOCK_JIRA
        jira_ref = "QA-812"
        jira_source = ContextSourceConfig(type="jira", ref=jira_ref, server="jira", payload=jira_payload, tool="mcp:jira/get_issue")

    sources = [jira_source]
    if not args.jira_only:
        sources += [
            ContextSourceConfig(type="figma", server="figma", payload=MOCK_FIGMA, uri="https://www.figma.com/file/demo123/Homepage?node-id=10-20", tool="mcp:figma/get_file"),
            ContextSourceConfig(type="github", server="github", payload=MOCK_GITHUB, tool="mcp:github/get_issue"),
        ]
    if args.jira_only:
        if args.manual:
            sources.append(ContextSourceConfig(type="manual", ref=args.manual, payload=Path(args.manual).read_text(encoding="utf-8")))
    elif args.manual:
        sources.append(ContextSourceConfig(type="manual", ref=args.manual, payload=Path(args.manual).read_text(encoding="utf-8")))
    else:
        sources.append(ContextSourceConfig(type="manual", ref="qa-notes", payload="# QA notes\n\n## Risk Areas\n- mobile viewport\n- flaky network\n\n## Out of Scope\n- billing flows"))

    intake = ContextIntake(servers=[
        MCPServerConfig(name="jira", kind="jira", auth_env="JIRA_TOKEN"),      # env ref names only
        MCPServerConfig(name="figma", kind="figma", auth_env="FIGMA_TOKEN"),
        MCPServerConfig(name="github", kind="github", auth_env="GITHUB_TOKEN"),
    ])
    bundle = intake.ingest(sources)
    out = Path(args.out)
    intake.normalizer.save_bundle(bundle, out)
    print(json.dumps({
        "saved": str(out),
        "ticket_id": bundle.ticket_id,
        "title": bundle.title,
        "source_types": [r.source_type for r in bundle.source_refs],
        "acceptance_criteria_count": len(bundle.acceptance_criteria),
        "provenance_adapters": (bundle.provenance.adapters if bundle.provenance else []),
        "redacted": (bundle.provenance.redacted if bundle.provenance else False),
    }, indent=2))


if __name__ == "__main__":
    main()
