"""Cloud Room API client."""
from __future__ import annotations

import os
import random
import string
import time
from typing import Any, Dict, Optional

try:
    import httpx
except ImportError:
    httpx = None

try:
    import requests
except ImportError:
    requests = None


class CloudRoomError(Exception):
    """Base exception for Cloud Room errors."""

    pass


class CloudRoomClient:
    """HTTP client for Cloud Room API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: int = 60,
    ):
        self.base_url = (base_url or os.environ.get("CLOUDROOM_URL") or "http://127.0.0.1:9840").rstrip("/")
        self.token = token or os.environ.get("CLOUDROOM_TOKEN") or os.environ.get("CLOUDROOM_API_TOKEN")
        self.timeout = timeout
        if not self.token:
            raise CloudRoomError("CLOUDROOM_TOKEN required")

    def _generate_request_id(self) -> str:
        """Generate a request ID (1-64 letters, digits, _, -)."""
        chars = string.ascii_letters + string.digits + "_-"
        return "".join(random.choice(chars) for _ in range(16))

    def _headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if request_id:
            headers["X-Request-ID"] = request_id
        return headers

    def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make HTTP request to Cloud Room API."""
        url = f"{self.base_url}{path}"
        headers = self._headers(request_id)

        if httpx is not None:
            try:
                resp = httpx.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    timeout=self.timeout,
                    **kwargs,
                )
            except Exception as e:
                raise CloudRoomError(f"Request failed: {e}")
        elif requests is not None:
            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    timeout=self.timeout,
                    **kwargs,
                )
            except Exception as e:
                raise CloudRoomError(f"Request failed: {e}")
        else:
            raise CloudRoomError("No HTTP client available (httpx or requests required)")

        if resp.status_code == 401:
            raise CloudRoomError("Unauthorized: check CLOUDROOM_TOKEN")
        elif resp.status_code == 409:
            raise CloudRoomError("Request conflict")
        elif resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise CloudRoomError(f"HTTP {resp.status_code}: {detail}")

        try:
            return resp.json()
        except Exception:
            return {"status": "ok", "raw": resp.text}

    def health(self) -> Dict[str, Any]:
        """Get health status."""
        return self._request("GET", "/health")

    def capabilities(self) -> Dict[str, Any]:
        """Get capabilities."""
        return self._request("GET", "/v1/capabilities")

    def send_command(
        self,
        command: str,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a command (async, returns 202 with receipt)."""
        if request_id is None:
            request_id = self._generate_request_id()
        payload = {
            "request_id": request_id,
            "command": command,
            "params": params or {},
        }
        if session_id:
            payload["session_id"] = session_id
        return self._request("POST", "/v1/commands", json_data=payload, request_id=request_id)

    def get_receipt(self, receipt_id: str) -> Dict[str, Any]:
        """Get receipt status."""
        return self._request("GET", f"/v1/receipts/{receipt_id}")

    def wait_for_receipt(self, receipt_id: str, timeout: int = 300, poll_interval: float = 2.0) -> Dict[str, Any]:
        """Wait for receipt to complete."""
        start = time.time()
        while time.time() - start < timeout:
            receipt = self.get_receipt(receipt_id)
            status = receipt.get("status")
            if status in ("completed", "failed", "interrupted", "unknown", "unknown_after_restart"):
                return receipt
            time.sleep(poll_interval)
        raise CloudRoomError(f"Timeout waiting for receipt {receipt_id}")


    # Sessions API
    def create_session(self, request_id: Optional[str] = None, project: Optional[str] = None) -> Dict[str, Any]:
        """Create a new session."""
        if request_id is None:
            request_id = self._generate_request_id()
        payload = {"request_id": request_id}
        if project:
            payload["project"] = project
        resp = self._request("POST", "/v1/sessions", json_data=payload, request_id=request_id)
        session_id = resp.get("session_id") or f"cr_{request_id}"
        if not session_id.startswith("cr_"):
            session_id = f"cr_{session_id}"
        resp["session_id"] = session_id
        return resp

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session details."""
        return self._request("GET", f"/v1/sessions/{session_id}")

    def list_sessions(self) -> Dict[str, Any]:
        """List sessions."""
        return self._request("GET", "/v1/sessions")

    # Threads API
    def create_thread(
        self,
        session_id: str,
        request_id: Optional[str] = None,
        prompt: Optional[str] = None,
        harness: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a thread in a session."""
        if request_id is None:
            request_id = self._generate_request_id()
        payload = {"request_id": request_id}
        if prompt:
            payload["prompt"] = prompt
        if harness:
            payload["harness"] = harness
        if model:
            payload["model"] = model
        return self._request("POST", f"/v1/sessions/{session_id}/threads", json_data=payload, request_id=request_id)

    def get_thread(self, session_id: str, thread_id: str) -> Dict[str, Any]:
        """Get thread details."""
        return self._request("GET", f"/v1/sessions/{session_id}/threads/{thread_id}")

    def list_threads(self, session_id: str) -> Dict[str, Any]:
        """List threads in a session."""
        return self._request("GET", f"/v1/sessions/{session_id}/threads")

    # Subagents
    def spawn_subagent(
        self,
        session_id: str,
        request_id: Optional[str] = None,
        prompt: Optional[str] = None,
        harness: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Spawn a subagent (creates a thread)."""
        if request_id is None:
            request_id = self._generate_request_id()
        payload = {"request_id": request_id}
        if prompt:
            payload["prompt"] = prompt
        if harness:
            payload["harness"] = harness
        if model:
            payload["model"] = model
        return self._request("POST", f"/v1/sessions/{session_id}/subagents", json_data=payload, request_id=request_id)

    def send_command_and_wait(
        self,
        command: str,
        params: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        timeout: int = 300,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """Send command and wait for completion."""
        resp = self.send_command(command, params=params, request_id=request_id, session_id=session_id)
        receipt_id = resp.get("receipt_id") or resp.get("receipt", {}).get("id")
        if not receipt_id:
            return resp
        return self.wait_for_receipt(receipt_id, timeout=timeout, poll_interval=poll_interval)

    def get_journal(self, session_id: str) -> Dict[str, Any]:
        """Get session journal/events."""
        return self._request("GET", f"/v1/sessions/{session_id}/journal")

    def list_artifacts(self, session_id: str, path: str = "/") -> Dict[str, Any]:
        """List artifacts in workspace."""
        return self._request("GET", f"/v1/sessions/{session_id}/artifacts", params={"path": path})

    def download_artifact(self, session_id: str, artifact_path: str) -> bytes:
        """Download an artifact file."""
        url = f"{self.base_url}/v1/sessions/{session_id}/artifacts/download"
        headers = self._headers()
        if httpx is not None:
            try:
                resp = httpx.get(url, headers=headers, params={"path": artifact_path}, timeout=self.timeout)
            except Exception as e:
                raise CloudRoomError(f"Download failed: {e}")
        elif requests is not None:
            try:
                resp = requests.get(url, headers=headers, params={"path": artifact_path}, timeout=self.timeout)
            except Exception as e:
                raise CloudRoomError(f"Download failed: {e}")
        else:
            raise CloudRoomError("No HTTP client available")
        if resp.status_code >= 400:
            raise CloudRoomError(f"Download failed: HTTP {resp.status_code}")
        return resp.content

    # Automations
    def create_automation(
        self,
        request_id: Optional[str] = None,
        name: Optional[str] = None,
        prompt: Optional[str] = None,
        schedule: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an automation."""
        if request_id is None:
            request_id = self._generate_request_id()
        payload = {"request_id": request_id}
        if name:
            payload["name"] = name
        if prompt:
            payload["prompt"] = prompt
        if schedule:
            payload["schedule"] = schedule
        return self._request("POST", "/v1/automations", json_data=payload, request_id=request_id)

    def list_automations(self) -> Dict[str, Any]:
        """List automations."""
        return self._request("GET", "/v1/automations")

    def trigger_automation(self, automation_id: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        """Trigger an automation."""
        if request_id is None:
            request_id = self._generate_request_id()
        payload = {"request_id": request_id}
        return self._request("POST", f"/v1/automations/{automation_id}/trigger", json_data=payload, request_id=request_id)
