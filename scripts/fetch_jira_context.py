#!/usr/bin/env python3
"""Fetch a real Jira issue (REST) and normalize it into a ContextBundle (008.1 live).

Auth via env only (never persisted): JIRA_API_TOKEN (Cloud Basic $JIRA_EMAIL:$TOKEN)
or JIRA_PAT (Server/DC Bearer). Normalization reuses JiraContextAdapter.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fetch_issue(jira_url: str, issue_key: str) -> dict:
    import httpx  # type: ignore

    jira_url = jira_url.rstrip("/")
    api = "3" if "atlassian.net" in jira_url else "2"
    url = f"{jira_url}/rest/api/{api}/issue/{issue_key}?fields=*all"
    headers = {"Accept": "application/json"}
    if os.environ.get("JIRA_API_TOKEN"):
        email = os.environ.get("JIRA_EMAIL", "")
        r = httpx.get(url, headers=headers, auth=httpx.BasicAuth(email, os.environ["JIRA_API_TOKEN"]))
    elif os.environ.get("JIRA_PAT"):
        headers["Authorization"] = f"Bearer {os.environ['JIRA_PAT']}"
        r = httpx.get(url, headers=headers)
    else:
        raise SystemExit("JIRA_API_TOKEN (Cloud) or JIRA_PAT (Server/DC) not set in env")
    r.raise_for_status()
    return r.json()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--jira-url", default=os.environ.get("JIRA_SITE", ""))
    p.add_argument("--issue-key", required=True)
    p.add_argument("--out", default="artifacts/manual-e2e-01/context_bundle.json")
    args = p.parse_args()
    if not args.jira_url:
        raise SystemExit("JIRA_SITE / --jira-url required")

    from harness.integrations.mcp_context import ContextIntake, ContextSourceConfig

    payload = _fetch_issue(args.jira_url, args.issue_key)
    intake = ContextIntake()
    bundle = intake.ingest([
        ContextSourceConfig(type="jira", ref=args.issue_key, payload=payload, tool="mcp.jira/get_issue", uri=payload.get("self")),
    ])
    out = Path(args.out)
    intake.normalizer.save_bundle(bundle, out)
    print(json.dumps({
        "saved": str(out),
        "ticket_id": bundle.ticket_id,
        "title": bundle.title,
        "source_types": [r.source_type for r in bundle.source_refs],
        "acceptance_criteria_count": len(bundle.acceptance_criteria),
        "figma_links": [str(u) for u in bundle.figma_links],
        "provenance": bundle.provenance.model_dump() if bundle.provenance else None,
    }, indent=2))


if __name__ == "__main__":
    main()
