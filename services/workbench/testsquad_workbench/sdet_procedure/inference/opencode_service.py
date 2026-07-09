from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from testsquad_workbench.sdet_procedure.inference.conversation_state import (
    ConversationState,
)


@dataclass
class OpenCodeConfig:
    # `opencode run` is OpenCode's official headless/non-interactive mode
    # (built for CI/automation). It streams NDJSON events to stdout.
    binary: str = os.environ.get("OPENCODE_BIN", "opencode")
    model: Optional[str] = os.environ.get("OPENCODE_MODEL")  # e.g. "anthropic/claude-..."
    agent: str = os.environ.get("OPENCODE_AGENT", "build")
    timeout: float = float(os.environ.get("OPENCODE_TIMEOUT", "300.0"))
    # Auto-approve permission prompts so generation needs no manual step.
    auto_approve: bool = os.environ.get("OPENCODE_AUTO_APPROVE", "1") != "0"
    # Run in an isolated temp dir so stray writes never touch the repo.
    workdir: Optional[str] = os.environ.get("OPENCODE_WORKDIR")


_SYSTEM_PROMPT = (
    "You are OpenCode, an expert SDET specializing in Playwright UI automation. "
    "Given the SDET session context (nodes N0-N14) and a test scenario, produce a "
    "complete, production-ready Playwright test in TypeScript. Output ONLY valid "
    "TypeScript code inside a single code block. Do NOT modify any files - return the "
    "code in your response only. Be concise. No reasoning, no explanation."
)


def format_opencode_prompt(state: ConversationState) -> str:
    """Format the full SDET session context (N0-N14) as an OpenCode prompt."""
    lines: List[str] = []
    lines.append(
        "Generate a complete, production-ready Playwright test (TypeScript) for the "
        "following SDET session context."
    )
    lines.append("")
    lines.append(f"URL: {state.url}")
    lines.append(f"Feature: {state.feature_type or 'unspecified'}")
    lines.append(f"Test Type: {state.test_type or 'positive'}")
    lines.append(f"Scenario: {state.scenario_description or 'User flow test'}")
    lines.append("")

    if state.selected_elements:
        lines.append("=== Target Elements (N9-N10) ===")
        for i, el in enumerate(state.selected_elements, 1):
            tag = el.get("tag", "?")
            text = (el.get("text", "") or el.get("label", "") or "")[:40]
            css = el.get("css_path", el.get("cssPath", ""))
            role = el.get("role", "")
            aria = el.get("aria_label", "")
            lines.append(
                f'{i}. <{tag}> text="{text}" css="{css}" role="{role}" aria="{aria}"'
            )
        lines.append("")

    if state.recorded_actions:
        lines.append("=== Recorded User Actions (N11) ===")
        for a in state.recorded_actions:
            target = a.label or a.text[:40] or a.tag
            loc = a.locator or ""
            val = a.value or ""
            lines.append(
                f'{a.step_order}. {a.action_type} on "{target}" -> {loc} value="{val}"'
            )
        lines.append("")

    lines.append("=== Requirements ===")
    lines.append("- Use accessible locators (getByRole, getByLabel, getByPlaceholder, getByText)")
    lines.append("- Include proper assertions at each step (URL, visibility, value checks)")
    lines.append("- Use realistic test data (not 'test-value')")
    lines.append("- Use page.goto() for navigation and await for async")
    lines.append("- Import test and expect from '@playwright/test'")
    lines.append("- Consider the full SDET workflow context above")
    lines.append("- Output ONLY valid TypeScript code inside a single code block. No explanation.")

    return "\n".join(lines)


def build_opencode_context(state: ConversationState) -> Dict[str, Any]:
    """Structured context (mirrors what the SDET console already tracks)."""
    return {
        "url": state.url,
        "current_node": state.current_node_id,
        "feature_type": state.feature_type,
        "test_type": state.test_type,
        "scenario_description": state.scenario_description,
        "selected_elements": state.selected_elements,
        "recorded_actions": [
            {
                "step_order": a.step_order,
                "action_type": a.action_type,
                "tag": a.tag,
                "label": a.label,
                "text": a.text,
                "locator": a.locator,
                "value": a.value,
            }
            for a in state.recorded_actions
        ],
        "node_ids": [t.node_id for t in state.history],
        "hub_decisions": state.hub_decisions,
    }


def _build_command(config: OpenCodeConfig, prompt: str) -> List[str]:
    cmd = [config.binary, "run", "--format", "json"]
    if config.model:
        cmd += ["--model", config.model]
    if config.agent:
        cmd += ["--agent", config.agent]
    if config.auto_approve:
        cmd.append("--auto")
    cmd.append(prompt)
    return cmd


def _extract_text(line: str) -> Optional[str]:
    """Pull streamed text out of one NDJSON event line from `opencode run`."""
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if event.get("type") != "text":
        return None
    part = event.get("part") or {}
    text = part.get("text")
    return text if isinstance(text, str) else None


async def _stream_via_cli(config: OpenCodeConfig, prompt: str) -> AsyncIterator[str]:
    """Run `opencode run --format json` headlessly and yield streamed text chunks."""
    cmd = _build_command(config, prompt)
    env = {k: v for k, v in os.environ.items() if k != "OPENCODE_SESSION_ID"}
    workdir = config.workdir or tempfile.mkdtemp(prefix="opencode-")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=workdir,
        env=env,
    )
    assert proc.stdout is not None
    try:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            chunk = _extract_text(raw.decode("utf-8", errors="replace"))
            if chunk:
                yield chunk
        await asyncio.wait_for(proc.wait(), timeout=config.timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise


async def stream_opencode_completion(
    state: ConversationState, model: Optional[str] = None
) -> AsyncIterator[str]:
    """Build the N0-N14 prompt and stream OpenCode's generated test code.

    `model` (provider/model) overrides the OPENCODE_MODEL env default for this call.
    """
    config = OpenCodeConfig()
    if model:
        config.model = model
    prompt = format_opencode_prompt(state)
    async for chunk in _stream_via_cli(config, prompt):
        yield chunk
