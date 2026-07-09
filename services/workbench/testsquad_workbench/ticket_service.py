from __future__ import annotations

import httpx
from typing import Optional
import logging

logger = logging.getLogger(__name__)

_jira_configs: dict[str, dict] = {}


class JiraClient:
    def __init__(self, instance_url: str, email: str, api_token: str):
        self.base_url = instance_url.rstrip("/")
        self.auth = httpx.BasicAuth(email, api_token)

    async def search(self, jql: str, max_results: int = 10) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as c:
            resp = await c.post(
                f"{self.base_url}/rest/api/3/search/jql",
                json={"jql": jql, "maxResults": max_results},
                auth=self.auth,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "key": issue["key"],
                    "summary": issue["fields"]["summary"],
                    "status": issue["fields"]["status"]["name"],
                    "priority": issue["fields"]["priority"]["name"]
                    if issue["fields"].get("priority")
                    else None,
                    "issuetype": issue["fields"]["issuetype"]["name"]
                    if issue["fields"].get("issuetype")
                    else None,
                }
                for issue in data.get("issues", [])
            ]

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

            comments = []
            if fields.get("comment", {}).get("comments"):
                for c in fields["comment"]["comments"]:
                    comments.append({
                        "author": c["author"]["displayName"],
                        "body": c.get("renderedBody", c.get("body", "")),
                        "created": c.get("created"),
                    })

            return {
                "key": data["key"],
                "summary": fields["summary"],
                "description": fields.get("description")
                or fields.get("renderedFields", {}).get("description", ""),
                "status": fields["status"]["name"],
                "priority": fields["priority"]["name"] if fields.get("priority") else None,
                "issuetype": fields["issuetype"]["name"] if fields.get("issuetype") else None,
                "labels": fields.get("labels", []),
                "assignee": fields["assignee"]["displayName"] if fields.get("assignee") else None,
                "comments": comments,
            }

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
