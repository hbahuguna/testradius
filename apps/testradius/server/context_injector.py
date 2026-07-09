from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .log_config import get_logger

logger = get_logger("context")

CONTEXT_FILE = Path("/tmp/testradius-sdet-context.md")


def _fmt(val: Any) -> str:
    if val is None or val == "" or val == [] or val == {}:
        return "_empty_"
    return str(val)


def write_context_file(session_id: str, context: Optional[dict[str, Any]]) -> None:
    if context is None:
        content = _empty_context(session_id)
    else:
        content = _build_markdown(context)
    CONTEXT_FILE.write_text(content)
    logger.info("Context file written (%d bytes, session=%s)", len(content), session_id)


def _empty_context(session_id: str) -> str:
    return (
        "## SDET Session Context (auto-injected)\n"
        "\n"
        f"No active session data yet. Call `sdet_session_init(url=...)` to start.\n"
    )


def _build_markdown(ctx: dict) -> str:
    lines: list[str] = []
    lines.append("## SDET Session Context (auto-injected)\n")
    lines.append(f"- **Session**: `{ctx['session_id']}`")
    lines.append(f"- **URL**: {_fmt(ctx.get('url'))}")

    updated = ctx.get("updated_at", "")
    if updated:
        try:
            dt = datetime.fromisoformat(updated)
            updated = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except ValueError:
            pass
    lines.append(f"- **Updated**: {updated}")
    lines.append("")

    actions = ctx.get("recorded_actions", [])
    lines.append(f"### Recorded Actions ({len(actions)})")
    if actions:
        lines.append("| # | Action | Selector | Value | URL |")
        lines.append("|---|--------|----------|-------|-----|")
        for i, a in enumerate(actions, 1):
            lines.append(
                f"| {i} | {_fmt(a.get('action_type'))} "
                f"| `{_fmt(a.get('selector'))}` "
                f"| {_fmt(a.get('value'))} "
                f"| {_fmt(a.get('url'))} |"
            )
    else:
        lines.append("*No actions recorded yet.*")
    lines.append("")

    elements = ctx.get("selected_elements", [])
    lines.append(f"### Selected Elements ({len(elements)})")
    if elements:
        lines.append("| # | Tag | Text | Selector | Attributes |")
        lines.append("|---|-----|------|----------|------------|")
        for i, e in enumerate(elements, 1):
            attrs = ",".join(
                f"{k}={v}" for k, v in e.get("attributes", {}).items()
            )
            lines.append(
                f"| {i} | `{_fmt(e.get('tag'))}` "
                f"| {_fmt(e.get('text'))} "
                f"| `{_fmt(e.get('selector'))}` "
                f"| {_fmt(attrs)} |"
            )
    else:
        lines.append("*No elements selected yet.*")
    lines.append("")

    tc = ctx.get("test_code")
    lines.append("### Generated Test Code")
    if tc and tc.get("code"):
        lang = tc.get("language", "") or ""
        desc = tc.get("description", "")
        lines.append(f"- **Language**: {_fmt(lang)}")
        lines.append(f"- **Description**: {_fmt(desc)}")
        lines.append(f"- **Size**: {len(tc['code'])} bytes")
        lines.append("")
        lines.append(f"```{lang}")
        lines.append(tc["code"].rstrip())
        lines.append("```")
    else:
        lines.append("*No test code generated yet.*")
    lines.append("")

    conv = ctx.get("conversation_history", [])
    lines.append(f"### Conversation Turns ({len(conv)})")
    if conv:
        for i, m in enumerate(conv, 1):
            role = m.get("role", "?")
            content = m.get("content", "")
            preview = content.replace("\n", " ")
            lines.append(f"{i}. **{role}**: {preview}")
    else:
        lines.append("*No conversation history yet.*")
    lines.append("")

    lines.append("---")
    lines.append(
        f"*To refresh this context during the session, "
        f"call `sdet_session_context(session_id=\"{ctx['session_id']}\")`.*"
    )
    lines.append("")

    return "\n".join(lines)
