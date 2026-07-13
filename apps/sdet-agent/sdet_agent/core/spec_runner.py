"""Real Playwright spec runner.

Executes a generated ``.ts`` Playwright spec for real via ``@playwright/test``
(installed in the sibling ``spec_runner/`` Node project). This is what makes the
generated test code actually RUN -- and surface real locator errors -- instead
of being interpreted by the goal-based LLM planner.

The Node project reuses the browser binaries already on disk (shared cache with
the Python Playwright install), so no extra browser download is required.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any, Dict

logger = logging.getLogger("sdet_agent.spec_runner")

# spec_runner/ lives next to the sdet_agent package (apps/sdet-agent/spec_runner).
_SPEC_RUNNER_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "spec_runner")
)
_PLAYWRIGHT_BIN = os.path.join(_SPEC_RUNNER_DIR, "node_modules", ".bin", "playwright")
_CONFIG_PATH = os.path.join(_SPEC_RUNNER_DIR, "playwright.session.config.mjs")
_BROWSERS_PATH = os.path.expanduser("~/Library/Caches/ms-playwright")

_CONFIG_TPL = """import {{ defineConfig, devices }} from "@playwright/test";

export default defineConfig({{
  timeout: 45000,
  expect: {{ timeout: 10000 }},
  reporter: [["list"]],
  use: {{
    headless: {headless},
    trace: "off",
    screenshot: "off",
  }},
  projects: [{{ name: "chromium", use: {{ ...devices["Desktop Chrome"] }} }}],
}});
"""


def _write_config(headless: bool) -> None:
    with open(_CONFIG_PATH, "w") as f:
        f.write(_CONFIG_TPL.format(headless="true" if headless else "false"))


def run_spec(
    test_path: str,
    headless: bool = True,
    timeout: int = 300,
) -> Dict[str, Any]:
    """Run a single Playwright spec file and return success + error output.

    The spec is executed via ``playwright test <file>``; any locator/assertion
    failure is captured verbatim so the self-heal loop can rewrite the spec.
    """
    if not os.path.exists(_PLAYWRIGHT_BIN):
        return {
            "success": False,
            "error_output": (
                "spec runner not installed: run `npm install` in "
                f"{_SPEC_RUNNER_DIR}"
            ),
            "returncode": -1,
        }
    if not os.path.exists(test_path):
        return {
            "success": False,
            "error_output": f"spec file not found: {test_path}",
            "returncode": -1,
        }

    # The spec lives in the user's repo, which has no @playwright/test installed
    # and sits outside Playwright's testDir. Copy it into the runner dir (which
    # already has node_modules + the session config) so it executes for real and
    # is collected normally. The user's repo file stays the source of truth; the
    # heal loop regenerates it from the error output below.
    _write_config(headless)
    run_name = "_session_run_" + os.path.basename(test_path)
    run_path = os.path.join(_SPEC_RUNNER_DIR, run_name)
    shutil.copyfile(test_path, run_path)
    cmd = [
        _PLAYWRIGHT_BIN,
        "test",
        run_name,
        "--config",
        _CONFIG_PATH,
        "--project",
        "chromium",
        "--reporter",
        "list",
    ]
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": _BROWSERS_PATH}
    try:
        proc = subprocess.run(
            cmd,
            cwd=_SPEC_RUNNER_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error_output": f"spec run timed out after {timeout}s",
            "returncode": -1,
        }
    finally:
        try:
            os.remove(run_path)
        except OSError:
            pass
    output = f"--- STDOUT ---\n{proc.stdout or ''}\n--- STDERR ---\n{proc.stderr or ''}"
    if proc.returncode == 0:
        logger.info("spec run OK: %s", os.path.basename(test_path))
    else:
        # Surface the failure verbatim in the server log so operators can see
        # exactly why a test failed (locator not found, assertion, timeout, ...).
        logger.error(
            "spec run FAILED (rc=%s) %s:\n%s",
            proc.returncode,
            os.path.basename(test_path),
            output[-3000:],
        )
    return {
        "success": proc.returncode == 0,
        "error_output": output[-6000:],
        "returncode": proc.returncode,
    }
