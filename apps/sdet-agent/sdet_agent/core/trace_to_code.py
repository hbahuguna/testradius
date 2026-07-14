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
    """Convert a target + kind into a Playwright locator expression.
    
    Targets may include context for disambiguation: "role|name|context".
    Context can be a tier name like "tier:growth" or a text snippet like
    "Most Popular". When present, we generate a scoped locator.
    """
    if kind == "role":
        parts = target.split("|")
        role = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ""
        context = parts[2].strip() if len(parts) > 2 else ""
        pw_role = _pw_role(role)
        
        if context:
            # Scope to the context element first
            if "=" in context and context.startswith("data-"):
                # data-* attribute: data-tier=growth → [data-tier="growth"]
                attr_name, attr_val = context.split("=", 1)
                scope = f'{page_ref}.locator(\'[{attr_name}="{attr_val}"]\')'
            else:
                # Text context: find nearest ancestor containing this text
                scope = f'{page_ref}.locator("article").filter({{ hasText: "{_escape(context)}" }})'
            if name:
                return f'{scope}.getByRole("{pw_role}", {{ name: "{_escape(name)}" }})'
            return f'{scope}.getByRole("{pw_role}")'
        
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


_SDET_PERSONA = """You are the world's best Staff SDET engineer. You generate production-grade Playwright tests.

RULES:
- Use accessible locators first: getByRole, getByLabel, getByPlaceholder, getByText. Then data-testid. Never XPath or complex CSS chains.
- Assert page state at EVERY step — URL, visibility, value, enabled/disabled — so tests fail with clear diagnostics.
- Use realistic test data (realistic names, emails, URLs), never "test" or "foo".
- Use describe blocks, beforeEach for shared setup, clean up after each test.
- Use waitFor/toBeVisible/toHaveValue for async state. Avoid fixed timeouts.
- Name tests and variables clearly so any teammate can understand intent.
- Import and use existing page objects when available.
- NEVER add try/catch, console monitoring, or polling fallbacks.
- Generate COMPLETE tests — all steps from navigation to final assertion.
- For <select> elements, use selectOption() not fill().
- Use selectOption with the option LABEL text, not the value attribute.

OUTPUT: Only the TypeScript test code. No explanation, no markdown fences."""


def trace_to_code_refined(
    trace: ExecutionTrace,
    llm_infer_fn,
    page_objects: str = "",
) -> str:
    """Generate a raw trace-based code, then refine it through the LLM with SDET persona.

    Args:
        trace: The execution trace from a successful agentic run.
        llm_infer_fn: Callable(prompt: str, max_tokens: int, temperature: float) -> str
        page_objects: Optional string containing existing page object code for context.
    """
    # Step 1: Generate mechanical code from trace
    raw_code = trace_to_code(trace)

    # Step 2: Build the refinement prompt
    po_section = ""
    if page_objects:
        po_section = f"\nEXISTING PAGE OBJECTS (use these if applicable):\n```\n{page_objects}\n```\n"

    prompt = (
        f"{_SDET_PERSONA}\n\n"
        f"GOAL: {trace.goal}\n"
        f"URL: {trace.url}\n"
        f"{po_section}\n"
        f"RAW TEST CODE (from agentic exploration — correct locators and values):\n"
        f"```\n{raw_code}\n```\n\n"
        f"Rewrite this as a production-grade Playwright test following the rules above. "
        f"Keep the same locators and test data but improve structure, assertions, and readability."
    )

    # Step 3: LLM refinement
    try:
        refined = llm_infer_fn(prompt, max_tokens=4096, temperature=0.0)
        if refined and len(refined) > 100:
            refined = refined.strip()
            if refined.startswith("```"):
                refined = refined.split("\n", 1)[1] if "\n" in refined else refined[3:]
            if refined.endswith("```"):
                refined = refined[:-3]
            return refined.strip()
    except Exception:
        pass

    return raw_code
