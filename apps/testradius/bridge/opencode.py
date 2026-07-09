import asyncio
import json
import subprocess
from pathlib import Path
from typing import AsyncIterator


class OpenCodeBridge:
    """Spawns `opencode run --format json` and streams NDJSON events."""

    def __init__(self, repo_path: str | Path | None = None, model: str | None = None):
        self._process: asyncio.subprocess.Process | None = None
        self._repo_path = str(repo_path or Path.cwd())
        self._model = model

    async def run(self, message: str, model: str | None = None) -> AsyncIterator[dict]:
        """Send a message to opencode and yield parsed NDJSON events.

        `model` (provider/model) overrides the bridge's default for this run.
        """
        effective_model = model or self._model
        cmd = ["opencode", "run", "--format", "json"]
        if effective_model:
            cmd += ["--model", effective_model]
        cmd.append(message)
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._repo_path,
        )

        async for parsed in self._read_stdout():
            yield parsed

        stderr = (await self._process.stderr.read()).decode().strip()
        if stderr:
            yield {"type": "error", "content": stderr[-500:]}

        self._process = None

    async def _read_stdout(self) -> AsyncIterator[dict]:
        assert self._process is not None
        assert self._process.stdout is not None

        while True:
            line = await self._process.stdout.readline()
            if not line:
                break
            line = line.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            yield self._normalize(obj)

    def _normalize(self, obj: dict) -> dict:
        evt_type = obj.get("type", "")
        part = obj.get("part", {})

        if evt_type == "text":
            text = part.get("text", "")
            return {"type": "text", "content": text}

        if evt_type == "tool_use":
            tool = part.get("tool", "")
            state = part.get("state", {})
            status = state.get("status", "")
            output = state.get("output", "")
            input_data = state.get("input", {})
            return {
                "type": "tool_use",
                "tool": tool,
                "status": status,
                "output": output,
                "input": input_data,
            }

        if evt_type == "step_start":
            return {"type": "step_start"}

        if evt_type == "step_finish":
            reason = part.get("reason", "")
            tokens = part.get("tokens", {})
            return {"type": "step_finish", "reason": reason, "tokens": tokens}

        if evt_type == "error":
            return {"type": "error", "content": part.get("error", str(obj))}

        return {"type": "unknown", "raw": obj}

    async def stop(self):
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
