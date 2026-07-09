import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .log_config import get_logger

logger = get_logger("context")

CONTEXT_FILE = Path("/tmp/testradius-sdet-context.md")

SDET_PERSONA = """You are the world's best Staff SDET engineer. You generate production-grade UI automation tests that follow industry best practices:

- **Locators**: Use accessible selectors first (getByRole, getByLabel, getByPlaceholder, getByText), then data-testid, then CSS as last resort. Never use fragile XPath or complex CSS chains.
- **Assertions**: Assert page state at every step — URL, visibility, value, enabled/disabled — so tests fail with clear diagnostics.
- **Test data**: Use realistic data (realistic names, emails, URLs), never placeholder values like "test" or "foo".
- **Structure**: Organize tests with describe blocks, use beforeEach for shared setup, clean up after each test.
- **Resilience**: Use waitFor/toBeVisible/toHaveValue for async state. Avoid fixed timeouts (wait 1000).
- **Readability**: Name tests and variables clearly so any teammate can understand intent.
- **Reuse**: When the repo has existing page objects or utilities, use them — import and call them rather than duplicating logic.

Before writing code, examine the repo's existing page objects, utilities, and test patterns listed below. Use them to write idiomatic code that matches the project's conventions.
"""

_SKIP_DIRS = {".git", "node_modules", "dist", "build", ".next", ".nuxt", ".venv", "venv", "__pycache__"}


def _scan_repo_files(repo_path: str, max_files: int = 15) -> list[dict]:
    """Scan an automation repo for page object and utility source files."""
    root = Path(repo_path)
    if not root.is_dir():
        return []
    source_exts = (".ts", ".tsx", ".js", ".jsx")
    scored: list[tuple[int, Path]] = []
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            for rel in result.stdout.splitlines():
                fp = root / rel
                if fp.suffix not in source_exts:
                    continue
                parent = fp.parent.as_posix().lower()
                parts = parent.split("/")
                score = 0
                if any(p in ("pages", "page-objects", "po") for p in parts):
                    score = 3
                elif any(p in ("utils", "helpers", "support") for p in parts):
                    score = 2
                if score:
                    scored.append((score, fp))
    except Exception:
        pass
    scored.sort(key=lambda x: -x[0])
    files_info = []
    for _, fp in scored[:max_files]:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        files_info.append({
            "path": str(fp.relative_to(root)),
            "content": text[:4000],
        })
    return files_info


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
        "# SDET Persona\n"
        f"{SDET_PERSONA}\n"
        "---\n"
        "## SDET Session Context (auto-injected)\n"
        "\n"
        f"No active session data yet. Call `sdet_session_init(url=...)` to start.\n"
    )


def _build_markdown(ctx: dict) -> str:
    lines: list[str] = []
    lines.append("# SDET Persona")
    lines.append(SDET_PERSONA)
    lines.append("---\n")

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

    repo_po = ctx.get("repo_page_objects", [])
    repo_utils = ctx.get("repo_utilities", [])
    if repo_po or repo_utils:
        lines.append("### Repository Context")
        if repo_po:
            lines.append(f"\n**Page Objects ({len(repo_po)}):**")
            for po in repo_po:
                lines.append(f"- `{po.get('file_path', po.get('path', '?'))}` — {po.get('class_name', po.get('name', '?'))}")
        if repo_utils:
            lines.append(f"\n**Utilities ({len(repo_utils)}):**")
            for u in repo_utils:
                lines.append(f"- `{u.get('file_path', u.get('path', '?'))}` — {u.get('name', '?')}")
        repo_files = ctx.get("repo_files", [])
        if not repo_files:
            repo_files = _scan_repo_files(ctx.get("automation_repo", ""))
        if repo_files:
            lines.append("\n**Existing Source Files (read for patterns & conventions):**")
            lines.append("")
            for f in repo_files:
                lines.append(f"#### `{f['path']}`")
                lines.append(f"```{'typescript' if f['path'].endswith('.ts') or f['path'].endswith('.tsx') else 'javascript'}")
                lines.append(f["content"])
                lines.append("```")
                lines.append("")
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
