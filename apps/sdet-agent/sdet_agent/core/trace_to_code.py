"""Convert a successful agentic ExecutionTrace into a static Playwright test.

Takes the recorded steps (selectors, values, actions) and emits a clean
.spec.ts file that replays the same flow without any LLM calls.
"""

from __future__ import annotations

import re
from typing import Any

from .trace import ActionTrace, AssertionResult, ExecutionTrace


def _escape(s: str) -> str:
    """Escape a string for use inside a TS template literal."""
    return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def _locator_line(target: str, kind: str, page_ref: str = "page") -> str:
    """Convert a target + kind into a Playwright locator expression."""
    if kind == "role":
        # target is "role|name" e.g. "textbox|First Name"
        parts = target.split("|", 1)
        role = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ""
        pw_role = _pw_role(role)
        if name:
            return f'{page_ref}.getByRole("{pw_role}", {{ name: "{_escape(name)}" }})'
        return f'{page_ref}.getByRole("{pw_role}")'
    if kind == "label":
        return f'{page_ref}.getByLabel("{_escape(target)}")'
    if kind == "text":
        return f'{page_ref}.getByText("{_escape(target)}")'
    if kind == "placeholder":
        return f'{page_ref}.getByPlaceholder("{_escape(target)}")'
    if kind == "css":
        return f'{page_ref}.locator("{_escape(target)}")'
    # auto — try role first if target looks like "role|name"
    if "|" in target:
        return _locator_line(target, "role", page_ref)
    return f'{page_ref}.getByText("{_escape(target)}")'


def _pw_role(role: str) -> str:
    """Map ARIA roles to Playwright role names."""
    mapping = {
        "textbox": "textbox",
        "combobox": "combobox",
        "button": "button",
        "link": "link",
        "checkbox": "checkbox",
        "radio": "radio",
        "tab": "tab",
        "menuitem": "menuitem",
        "option": "option",
    }
    return mapping.get(role, role)


def _action_to_code(step: ActionTrace, indent: str = "    ") -> list[str]:
    """Convert a single ActionTrace into lines of Playwright code."""
    loc = _locator_line(step.target, step.kind)
    lines: list[str] = []

    if step.action == "navigate":
        lines.append(f'{indent}await page.goto("{_escape(step.value or step.target)}");')
    elif step.action == "click":
        lines.append(f"{indent}await {loc}.click();")
    elif step.action == "type":
        # browser_type auto-routes <select> to select_option, so mirror that
        if step.detail and "routed" in step.detail:
            lines.append(f'{indent}await {loc}.selectOption("{_escape(step.value)}");')
        else:
            lines.append(f'{indent}await {loc}.fill("{_escape(step.value)}");')
    elif step.action == "select":
        lines.append(f'{indent}await {loc}.selectOption("{_escape(step.value)}");')
    elif step.action == "wait":
        lines.append(f"{indent}await {loc}.waitFor();")
    elif step.action == "assert_visible":
        lines.append(f"{indent}await expect({loc}).toBeVisible();")
    elif step.action == "assert_text":
        lines.append(f'{indent}await expect({loc}).toContainText("{_escape(step.target)}");')
    elif step.action == "assert_url":
        lines.append(f'{indent}await expect(page).toHaveURL(/{_escape(step.value)}/);')
    else:
        # done, fail, or unknown — skip
        pass

    return lines


def _assertion_to_code(a: AssertionResult, indent: str = "    ") -> list[str]:
    """Convert an assertion into Playwright expect() code."""
    lines: list[str] = []
    if a.type == "text":
        # a.detail often has the form "contains: <text>"
        expected = a.description or a.detail.split("contains:")[-1].strip() if "contains:" in a.detail else a.description
        lines.append(f'{indent}await expect(page.getByText("{_escape(expected)}")).toBeVisible();')
    elif a.type == "url":
        lines.append(f'{indent}await expect(page).toHaveURL(/{_escape(a.description)}/);')
    elif a.type == "visibility":
        lines.append(f'{indent}await expect(page.getByText("{_escape(a.description)}")).toBeVisible();')
    return lines


def trace_to_code(trace: ExecutionTrace) -> str:
    """Generate a complete Playwright .spec.ts from a successful execution trace."""
    successful_steps = [s for s in trace.steps if s.ok and s.action not in ("done", "fail")]

    # Derive test name from goal
    test_name = trace.goal
    if len(test_name) > 80:
        test_name = test_name[:80]
    # Sanitize for a valid TS identifier / test title
    test_name = re.sub(r"[^\w\s-]", "", test_name).strip()
    test_name = re.sub(r"\s+", " ", test_name)

    lines: list[str] = [
        'import { test, expect } from "@playwright/test";',
        "",
        "",
        f'test("{_escape(test_name)}", async ({{ page }}) => {{',
    ]

    # Navigate to starting URL
    if trace.url:
        lines.append(f'    await page.goto("{_escape(trace.url)}");')
        lines.append("")

    # Replay successful actions
    for step in successful_steps:
        code_lines = _action_to_code(step)
        if code_lines:
            lines.extend(code_lines)

    # Add assertions from the agentic run
    if trace.assertions:
        lines.append("")
        lines.append("    // Assertions verified during agentic run")
        for a in trace.assertions:
            lines.extend(_assertion_to_code(a))

    lines.append("});")
    lines.append("")

    return "\n".join(lines)


def trace_to_code_with_healing(trace: ExecutionTrace, error_step: ActionTrace | None = None) -> str:
    """Generate code with comments marking the failure point for the healer."""
    code = trace_to_code(trace)
    if error_step:
        marker = f"    // HEAL: step {error_step.step} failed — {error_step.detail}"
        # Insert marker after the failed action's line
        code = code.replace(
            "});",
            f"\n{marker}\n}});",
            1,
        )
    return code
