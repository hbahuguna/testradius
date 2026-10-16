"""HTTP client for the TestRadius backend API.

Covers the endpoints the agent needs: project resolution/registration, the
analyze-pr pipeline, evidence (derived from test-mapping), and instrumentation
(SSE). Parsed results are returned as the dataclasses in ``tools.models``.

A ``transport`` can be injected for tests (httpx MockTransport), and the base
URL/token/timeout are the only connection knobs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

import httpx

from .errors import BackendError


@dataclass
class ProjectInfo:
    id: int
    name: str
    description: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "ProjectInfo":
        return cls(id=int(raw["id"]), name=raw.get("name", ""), description=raw.get("description"))


class RadiusClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: float = 120.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        headers = {"Authorization": f"Bearer {self.token}"} if token else {}
        self._client = httpx.Client(
            base_url=self.base_url, headers=headers, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RadiusClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- /health ------------------------------------------------------------
    def health(self) -> bool:
        try:
            r = self._client.get("/health")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    # -- /projects ----------------------------------------------------------
    def list_projects(self) -> List[ProjectInfo]:
        data = self._get_json("/projects")
        return [ProjectInfo.from_raw(p) for p in data]

    def create_project(self, name: str, description: Optional[str] = None) -> ProjectInfo:
        body: Dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        data = self._request_json("POST", "/projects", json=body)
        return ProjectInfo.from_raw(data)

    def get_project_features(self, project_id: int) -> Dict[str, bool]:
        return self._get_json(f"/projects/{project_id}/features")

    def set_project_features(self, project_id: int, features: Dict[str, bool]) -> None:
        self._request_json(
            "PUT", f"/projects/{project_id}/features", json={"features": features}
        )

    def ensure_feature(self, project_id: int, name: str) -> None:
        """Enable a feature flag if it is not already on (idempotent)."""
        try:
            if self.get_project_features(project_id).get(name):
                return
        except BackendError:
            pass
        # set_project_features is additive server-side, so this keeps other flags.
        self.set_project_features(project_id, {name: True})

    # -- /projects/{project_id}/analyze-pr ----------------------------------
    def analyze_pr(
        self,
        project_id: int,
        full_name: str,
        pr_number: int,
        commit_sha: str = "main",
        file_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "full_name": full_name,
            "pr_number": pr_number,
            "commit_sha": commit_sha,
        }
        if file_paths:
            body["file_paths"] = file_paths
        return self._request_json("POST", f"/projects/{project_id}/analyze-pr", json=body)

    def analyze(self, project_id: int, full_name: str, pr_number: int, **kwargs: Any) -> AnalyzeResult:
        from .tools.models import AnalyzeResult

        return AnalyzeResult.from_raw(
            self.analyze_pr(project_id, full_name, pr_number, **kwargs)
        )

    # -- evidence (derived from /test-mapping) ------------------------------
    def list_test_mappings(self, project_id: int, limit: int = 1000) -> List[MappingEntry]:
        from .tools.models import MappingEntry

        data = self._get_json(f"/projects/{project_id}/test-mapping", params={"limit": limit})
        return [MappingEntry.from_raw(m) for m in data]

    def check_evidence(
        self,
        project_id: int,
        file_paths: Optional[List[str]] = None,
    ) -> EvidenceStatus:
        """Derive evidence freshness from existing test mappings.

        Fresh when at least one mapping exists — and, when changed paths are
        supplied, when at least one mapping targets one of those paths.
        """
        from .tools.models import EvidenceStatus

        mappings = self.list_test_mappings(project_id)
        count = len(mappings)
        if file_paths:
            wanted = {p.strip().lstrip("/") for p in file_paths if p and p.strip()}
            covered = sorted(
                {
                    m.product_file
                    for m in mappings
                    if m.product_file.lstrip("/") in wanted
                    or any(m.product_file.endswith("/" + w) or m.product_file == w for w in wanted)
                }
            )
        else:
            covered = []
        fresh = count > 0 and (not file_paths or bool(covered))
        if count == 0:
            reason = "no test mappings recorded for this project"
        elif fresh:
            reason = f"{count} existing mapping(s)"
        else:
            reason = "no mappings cover the changed files"
        return EvidenceStatus(
            known=True,
            fresh=fresh,
            mapping_count=count,
            covered_files=covered,
            reason=reason,
        )

    # -- /projects/{project_id}/instrumentation/run (SSE) -------------------
    def run_instrumentation(
        self,
        project_id: int,
        repo_url: Optional[str] = None,
        run_fresh: bool = False,
        language: Optional[str] = None,
        testbed_name: Optional[str] = None,
        local_path: Optional[str] = None,
    ) -> InstrumentationResult:
        from .tools.models import InstrumentationResult

        body: Dict[str, Any] = {"run_fresh": run_fresh}
        if repo_url:
            body["repo_url"] = repo_url
        if language:
            body["language"] = language
        if testbed_name:
            body["testbed_name"] = testbed_name
        if local_path:
            body["local_path"] = local_path

        result = InstrumentationResult()
        try:
            with self._client.stream(
                "POST", f"/projects/{project_id}/instrumentation/run", json=body
            ) as response:
                response.raise_for_status()
                for event in _iter_sse(response):
                    result.events.append(event)
                    _apply_instrumentation_event(result, event)
        except httpx.HTTPStatusError as e:
            raise BackendError(
                f"instrumentation/run failed: HTTP {e.response.status_code} {e.response.text[:300]}"
            ) from e
        except httpx.HTTPError as e:
            raise BackendError(f"Cannot reach TestRadius at {self.base_url}: {e}") from e
        return result

    # -- low-level helpers --------------------------------------------------
    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request_json("GET", url, params=params)

    def _request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            r = self._client.request(method, url, **kwargs)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise BackendError(
                f"{method} {url} failed: HTTP {e.response.status_code} {e.response.text[:300]}"
            ) from e
        except httpx.HTTPError as e:
            raise BackendError(f"Cannot reach TestRadius at {self.base_url}: {e}") from e


def _iter_sse(response: httpx.Response) -> Iterator[Dict[str, Any]]:
    """Yield the JSON payload of each ``data:`` line in an SSE response."""
    for line in response.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload:
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def _apply_instrumentation_event(result: InstrumentationResult, event: Dict[str, Any]) -> None:
    kind = event.get("event")
    data = event.get("data")
    if kind == "error":
        result.status = "ERROR"
        result.error = str(data)
        return
    if kind == "status" and isinstance(data, dict):
        if result.status == "ERROR":
            return  # an error is terminal; ignore any trailing status
        status = str(data.get("status", "")).upper()
        if status:
            result.status = status
        if "edges" in data:
            try:
                result.edges = int(data["edges"])
            except (TypeError, ValueError):
                pass
        if isinstance(data.get("coverage"), dict):
            result.coverage = data["coverage"]
    elif kind == "coverage_completeness" and isinstance(data, dict):
        result.coverage = data
