"""Subagent orchestration for parallel execution."""
from __future__ import annotations

from typing import Any, Dict, List

from .client import CloudRoomClient


class SubagentOrchestrator:
    """Orchestrate parallel subagent runs."""

    def __init__(self, client: CloudRoomClient):
        self.client = client
        self.runs: Dict[str, Dict[str, Any]] = {}

    def spawn_parallel(
        self,
        session_id: str,
        prompts: List[str],
        models: List[str] | None = None,
        harness: str = "opencode",
    ) -> List[Dict[str, Any]]:
        """Spawn multiple subagents in parallel."""
        results = []
        for i, prompt in enumerate(prompts):
            model = models[i] if models and i < len(models) else None
            try:
                resp = self.client.spawn_subagent(session_id, prompt=prompt, harness=harness, model=model)
                thread_id = resp.get("thread_id") or resp.get("id")
                run_id = f"subagent-{i}-{thread_id}"
                self.runs[run_id] = {
                    "thread_id": thread_id,
                    "model": model,
                    "status": "RUNNING",
                    "prompt": prompt[:100],
                }
                results.append({"run_id": run_id, "thread_id": thread_id, "status": "RUNNING"})
            except Exception as e:
                results.append({"index": i, "status": "FAILED", "error": str(e)})
        return results

    def get_status(self, run_id: str) -> Dict[str, Any]:
        return self.runs.get(run_id, {"status": "UNKNOWN"})
