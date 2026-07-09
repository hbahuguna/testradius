from __future__ import annotations

import httpx
import json
from typing import Optional
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_jira_configs: dict[str, dict] = {}


class JiraClient:
    def __init__(self, instance_url: str, email: str, api_token: str):
        self.base_url = instance_url.rstrip("/")
        self.auth = httpx.BasicAuth(email, api_token)

    async def search(self, jql: str, max_results: int = 10) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as c:
            url = f"{self.base_url}/rest/api/3/search/jql"
            body = {
                "jql": jql,
                "maxResults": max_results,
                "fields": ["key", "summary", "status", "priority", "issuetype"],
            }
            logger.info("Jira POST %s body=%s", url, body)
            resp = await c.post(
                url,
                json=body,
                auth=self.auth,
            )
            try:
                data = resp.json()
            except Exception:
                raise RuntimeError(
                    f"Non-JSON response ({resp.status_code}): {resp.text[:1000]}"
                )
            logger.info("Jira response status=%s keys=%s", resp.status_code, list(data.keys()) if isinstance(data, dict) else type(data))
            if resp.status_code != 200:
                err = data.get("errorMessages") or data.get("errors") or str(data)
                raise RuntimeError(f"Jira API error ({resp.status_code}): {err}")
            issues = data.get("issues", [])
            if issues:
                logger.info("Jira first issue sample: %s", json.dumps(issues[0], indent=2)[:2000])
            result = []
            for i in issues:
                try:
                    result.append({
                        "key": i["key"],
                        "summary": i["fields"]["summary"],
                        "status": i["fields"]["status"]["name"],
                        "priority": i["fields"].get("priority", {}).get("name")
                        if i["fields"].get("priority")
                        else None,
                        "issuetype": i["fields"].get("issuetype", {}).get("name")
                        if i["fields"].get("issuetype")
                        else None,
                    })
                except KeyError as ke:
                    logger.error("Skipping issue missing field %s: %s", ke, json.dumps(i)[:500])
            return result

    async def get_issue(self, issue_key: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as c:
            resp = await c.get(
                f"{self.base_url}/rest/api/3/issue/{issue_key}",
                params={"expand": "renderedFields,comment"},
                auth=self.auth,
            )
            resp.raise_for_status()
            data = resp.json()
            fields = data["fields"]
            rendered = data.get("renderedFields", {}) or {}

        def adf_to_text(doc: object) -> str:
            parts: list[str] = []

            def walk(node: object) -> None:
                if isinstance(node, dict):
                    if node.get("type") == "text":
                        parts.append(str(node.get("text", "")))
                    for child in node.get("content", []) or []:
                        walk(child)
                elif isinstance(node, list):
                    for n in node:
                        walk(n)

            walk(doc)
            return "\n".join(parts)

        def to_text(raw: object, rendered_val: object) -> str:
            if isinstance(raw, str):
                return raw
            if isinstance(raw, dict):
                return adf_to_text(raw)
            if isinstance(rendered_val, str):
                return rendered_val
            return ""

        description = to_text(fields.get("description"), rendered.get("description"))

        rendered_comments = rendered.get("comment", {}) or {}
        rendered_body_by_id = {
            c.get("id"): c.get("body")
            for c in (rendered_comments.get("comments", []) or [])
            if isinstance(c, dict)
        }
        raw_comment_block = fields.get("comment", {}) or {}
        raw_comments = raw_comment_block.get("comments", []) or [] if isinstance(raw_comment_block, dict) else []

        comments = []
        for c in raw_comments:
            if not isinstance(c, dict):
                continue
            body = to_text(c.get("body"), rendered_body_by_id.get(c.get("id")))
            comments.append({
                "author": (c.get("author") or {}).get("displayName", "Unknown"),
                "body": body,
                "created": c.get("created"),
            })

        return {
            "key": data["key"],
            "summary": fields["summary"],
            "description": description,
            "status": fields["status"]["name"],
            "priority": fields["priority"]["name"] if fields.get("priority") else None,
            "issuetype": fields["issuetype"]["name"] if fields.get("issuetype") else None,
            "labels": fields.get("labels", []),
            "assignee": fields["assignee"]["displayName"] if fields.get("assignee") else None,
            "comments": comments,
        }

    async def recent(self, max_results: int = 20) -> list[dict]:
        return await self.search("updated >= -30d ORDER BY updated DESC", max_results)

    async def verify(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                resp = await c.get(f"{self.base_url}/rest/api/3/myself", auth=self.auth)
                return resp.status_code == 200
        except Exception:
            return False


def get_client(session_id: str) -> JiraClient | None:
    config = _jira_configs.get(session_id)
    if not config:
        return None
    return JiraClient(config["instance_url"], config["email"], config["api_token"])


def set_config(session_id: str, instance_url: str, email: str, api_token: str):
    _jira_configs[session_id] = {
        "instance_url": instance_url,
        "email": email,
        "api_token": api_token,
    }


def clear_config(session_id: str):
    _jira_configs.pop(session_id, None)
