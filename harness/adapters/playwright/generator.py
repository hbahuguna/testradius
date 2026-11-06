"""Playwright script generator for compiled test plans."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


SCRIPT_TEMPLATE = r'''#!/usr/bin/env python3
"""Auto-generated Playwright test runner for compiled test plan: __PLAN_ID__"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Ensure standard Playwright browsers path
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")

from playwright.async_api import async_playwright

PLAN_ID = __PLAN_ID__
BASE_URL = __BASE_URL__
VIEWPORT = __VIEWPORT__
ARTIFACTS_DIR = __ARTIFACTS_DIR__
RECORD_TRACE = __RECORD_TRACE__
RECORD_VIDEO = __RECORD_VIDEO__
DEFAULT_TIMEOUT_MS = __DEFAULT_TIMEOUT_MS__

CASES = __CASES_JSON__


async def resolve_locator(page, target):
    """Resolve a Playwright locator from target semantic hints."""
    hints = target.get("hints", {}) if isinstance(target, dict) else {}
    desc = target.get("description", "") if isinstance(target, dict) else str(target)

    # 1. Direct CSS/XPath selector hint
    if hints.get("selector"):
        return page.locator(hints["selector"]).first

    # 2. Text / role combination
    role = hints.get("role")
    texts = hints.get("visible_text") or []
    if isinstance(texts, str):
        texts = [texts]

    if role and texts:
        return page.get_by_role(role, name=texts[0]).first

    # 3. Placeholder
    if hints.get("placeholder"):
        return page.get_by_placeholder(hints["placeholder"]).first

    # 4. Text only
    if texts:
        return page.get_by_text(texts[0]).first

    # 5. Role only
    if role:
        return page.get_by_role(role).first

    # 6. Fallback text from description
    if desc and len(desc.split()) <= 4:
        return page.get_by_text(desc).first

    # Default fallback to body
    return page.locator("body")


async def evaluate_assert_criteria(page, criteria_list):
    """Evaluate textual success criteria against current page state."""
    failures = []
    current_url = page.url
    page_title = await page.title()

    for criterion in criteria_list:
        crit = str(criterion).strip()
        crit_lower = crit.lower()

        # URL check
        if "url contains" in crit_lower or "url matches" in crit_lower:
            parts = crit.split("'", 2)
            if len(parts) >= 2:
                expected_part = parts[1]
                if expected_part not in current_url:
                    failures.append(f"URL '{current_url}' does not contain '{expected_part}'")
            continue

        # Title check
        if "title" in crit_lower:
            parts = crit.split("'", 2)
            if len(parts) >= 2:
                expected_title = parts[1]
                if expected_title.lower() not in page_title.lower():
                    failures.append(f"Page title '{page_title}' does not match '{expected_title}'")
            continue

        # Visibility of text
        if "visible" in crit_lower:
            parts = crit.split("'", 2)
            if len(parts) >= 2:
                expected_text = parts[1]
                count = await page.get_by_text(expected_text).count()
                if count == 0:
                    failures.append(f"Expected visible text '{expected_text}' not found on page")
            continue

    if failures:
        raise AssertionError("; ".join(failures))


async def run_step(page, step, artifacts_path):
    step_id = step.get("step_id", "step")
    action_type = str(step.get("action_type", "assert")).lower()
    target = step.get("target", {})
    input_data = step.get("input", {})
    timeout_s = step.get("timeout_s", DEFAULT_TIMEOUT_MS // 1000)
    timeout_ms = int(timeout_s * 1000)

    t0 = time.time()
    error_msg = None
    status = "PASSED"
    screenshot_file = None

    try:
        if action_type == "navigate":
            url = input_data.get("url") or (target.get("hints", {}).get("url") if isinstance(target, dict) else None)
            if not url:
                url = BASE_URL
            elif not url.startswith("http://") and not url.startswith("https://"):
                url = BASE_URL.rstrip("/") + "/" + url.lstrip("/")
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        elif action_type in ("click", "double_click"):
            loc = await resolve_locator(page, target)
            if action_type == "double_click":
                await loc.dblclick(timeout=timeout_ms)
            else:
                await loc.click(timeout=timeout_ms)

        elif action_type in ("type", "fill"):
            loc = await resolve_locator(page, target)
            text = str(input_data.get("text") or input_data.get("value") or "")
            await loc.fill(text, timeout=timeout_ms)

        elif action_type == "select":
            loc = await resolve_locator(page, target)
            val = str(input_data.get("value") or "")
            await loc.select_option(val, timeout=timeout_ms)

        elif action_type == "scroll":
            delta_y = int(input_data.get("delta_y", 400))
            await page.mouse.wheel(0, delta_y)
            await asyncio.sleep(0.5)

        elif action_type == "keypress":
            key = str(input_data.get("key", "Enter"))
            await page.keyboard.press(key)

        elif action_type == "wait":
            sec = float(input_data.get("seconds", 2))
            await asyncio.sleep(sec)

        elif action_type == "assert":
            criteria = step.get("success_criteria", [])
            if criteria:
                await evaluate_assert_criteria(page, criteria)

        # Check success criteria if present on any action
        if action_type != "assert" and step.get("success_criteria"):
            try:
                await evaluate_assert_criteria(page, step.get("success_criteria"))
            except Exception:
                pass

        # Capture screenshot if requested
        evidence_cfg = step.get("evidence", {})
        if evidence_cfg.get("screenshot_after", True):
            screenshot_file = str(artifacts_path / f"{step_id}.png")
            await page.screenshot(path=screenshot_file, full_page=False)

    except Exception as e:
        status = "FAILED"
        error_msg = str(e)
        # Always screenshot on failure
        try:
            screenshot_file = str(artifacts_path / f"{step_id}_failure.png")
            await page.screenshot(path=screenshot_file, full_page=False)
        except Exception:
            pass

    duration_ms = int((time.time() - t0) * 1000)
    return {
        "step_id": step_id,
        "ordinal": step.get("ordinal"),
        "intent": step.get("intent", ""),
        "action_type": action_type,
        "status": status,
        "duration_ms": duration_ms,
        "error": error_msg,
        "screenshot": screenshot_file,
    }


async def main():
    artifacts_path = Path(ARTIFACTS_DIR)
    artifacts_path.mkdir(parents=True, exist_ok=True)

    results = []
    overall_status = "PASSED"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context_kwargs = {"viewport": VIEWPORT}
        if RECORD_VIDEO:
            context_kwargs["record_video_dir"] = str(artifacts_path)

        context = await browser.new_context(**context_kwargs)

        if RECORD_TRACE:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)

        page = await context.new_page()

        for case in CASES:
            case_id = case.get("case_id", "TC")
            steps = case.get("steps", [])
            for step in steps:
                step_res = await run_step(page, step, artifacts_path)
                step_res["case_id"] = case_id
                results.append(step_res)
                if step_res["status"] == "FAILED":
                    overall_status = "FAILED"
                    if step.get("on_fail") == "stop_case":
                        break

        if RECORD_TRACE:
            trace_file = str(artifacts_path / "trace.zip")
            try:
                await context.tracing.stop(path=trace_file)
            except Exception:
                pass

        await context.close()
        await browser.close()

    summary = {
        "plan_id": PLAN_ID,
        "status": overall_status,
        "total_steps": len(results),
        "passed_steps": sum(1 for s in results if s["status"] == "PASSED"),
        "failed_steps": sum(1 for s in results if s["status"] == "FAILED"),
        "steps": results,
    }

    summary_file = artifacts_path / "step_results.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"RESULTS_FILE={summary_file}")
    print(f"OVERALL_STATUS={overall_status}")
    print(f"PASSED={summary['passed_steps']}/{summary['total_steps']}")
    return summary


if __name__ == "__main__":
    asyncio.run(main())
'''


class PlaywrightScriptGenerator:
    """Generates executable async Python Playwright scripts from compiled test plans."""

    def __init__(self, default_timeout_ms: int = 30000):
        self.default_timeout_ms = default_timeout_ms

    def generate(
        self,
        plan: Union[Dict[str, Any], str, Path],
        target_url: Optional[str] = None,
        artifacts_dir: str = "/home/user/artifacts",
        record_trace: bool = True,
        record_video: bool = False,
    ) -> str:
        """Generate Python async Playwright script from compiled plan."""
        plan_dict = self._parse_plan(plan)
        sut = plan_dict.get("sut", {})
        base_url = target_url or sut.get("base_url") or "https://testradius.dev"
        viewport = self._parse_viewport(sut.get("viewport", "1280x800"))

        cases = plan_dict.get("cases", [])
        plan_id = plan_dict.get("plan_id", "compiled_plan")

        cases_json = json.dumps(cases, indent=2)

        script = (
            SCRIPT_TEMPLATE
            .replace("__PLAN_ID__", repr(plan_id))
            .replace("__BASE_URL__", repr(base_url))
            .replace("__VIEWPORT__", repr(viewport))
            .replace("__ARTIFACTS_DIR__", repr(artifacts_dir))
            .replace("__RECORD_TRACE__", repr(record_trace))
            .replace("__RECORD_VIDEO__", repr(record_video))
            .replace("__DEFAULT_TIMEOUT_MS__", str(self.default_timeout_ms))
            .replace("__CASES_JSON__", cases_json)
        )
        return script

    def _parse_plan(self, plan: Union[Dict[str, Any], str, Path]) -> Dict[str, Any]:
        if isinstance(plan, (str, Path)) and (isinstance(plan, Path) or str(plan).endswith(".json")):
            p = Path(plan)
            if p.exists() and p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
            return json.loads(str(plan))
        if isinstance(plan, str):
            return json.loads(plan)
        if isinstance(plan, dict):
            return plan
        raise TypeError(f"Unsupported plan type: {type(plan).__name__}")

    def _parse_viewport(self, viewport_str: str) -> Dict[str, int]:
        try:
            if "x" in str(viewport_str):
                w, h = str(viewport_str).split("x")
                return {"width": int(w), "height": int(h)}
        except Exception:
            pass
        return {"width": 1280, "height": 800}
