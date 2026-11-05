#!/usr/bin/env python3
"""Build a Playwright+Chromium template on a self-hosted E2B Embed instance.

Usage:
  export E2B_API_KEY="..."
  export E2B_API_URL="http://8.231.230.69:3000"
  export E2B_PLAYWRIGHT_TEMPLATE="playwright-chromium"
  # Optional: use Microsoft Playwright image as base if VM can pull from mcr.microsoft.com
  # export E2B_PLAYWRIGHT_BASE_IMAGE="mcr.microsoft.com/playwright/python:v1.49.0-noble"

  /path/to/python scripts/build_e2b_playwright_template.py

If a previous build is stuck, delete the template in the dashboard/API and rebuild.
"""
from __future__ import annotations

import os

from e2b import Template


def on_log(e):
    try:
        print(str(e), flush=True)
    except Exception:
        print(e, flush=True)


def main() -> None:
    api_key = os.environ["E2B_API_KEY"]
    api_url = os.environ.get("E2B_API_URL", "http://8.231.230.69:3000")
    alias = os.environ.get("E2B_PLAYWRIGHT_TEMPLATE", "playwright-chromium")
    base_image = os.environ.get("E2B_PLAYWRIGHT_BASE_IMAGE")

    if base_image:
        print(f"Using base image: {base_image}")
        print("NOTE: MCR base images may not preserve Playwright for the sandbox's default python; prefer the lean build if verification fails.")
        tpl = (
            Template()
            .from_image(base_image)
            .set_envs({"DEBIAN_FRONTEND": "noninteractive"})
            .run_cmd("python3 -m pip install --no-cache-dir playwright==1.49.0 && python3 -m playwright install chromium")
            .run_cmd("python3 -c \"import playwright; print('playwright', playwright.__version__)\"")
            .set_workdir("/home/user")
        )
    else:
        # Lean build: avoid `playwright install-deps` (can hang in some envs).
        # Install common Chromium runtime deps via apt, then browser binary only.
        tpl = (
            Template()
            .from_python_image("3.11")
            .set_envs({"DEBIAN_FRONTEND": "noninteractive"})
            .apt_install([
                "ca-certificates", "fonts-liberation", "libasound2", "libatk-bridge2.0-0",
                "libatk1.0-0", "libatspi2.0-0", "libcairo2", "libcups2", "libdbus-1-3",
                "libdrm2", "libgbm1", "libglib2.0-0", "libgtk-3-0", "libnspr4", "libnss3",
                "libpango-1.0-0", "libx11-6", "libxcb1", "libxcomposite1", "libxdamage1",
                "libxext6", "libxfixes3", "libxkbcommon0", "libxrandr2", "libxshmfence1",
                "xdg-utils", "wget",
            ])
            .pip_install(["playwright==1.49.0"])
            .run_cmd("python3 -m playwright install chromium")
            .run_cmd("python3 -c \"import playwright; print('playwright', playwright.__version__)\"")
            .set_workdir("/home/user")
        )

    print(f"Building template alias={alias} via {api_url} (may take several minutes)...")
    info = Template.build(
        tpl,
        alias=alias,
        cpu_count=2,
        memory_mb=2048,
        on_build_logs=on_log,
        api_key=api_key,
        api_url=api_url,
    )
    print(f"\nBuild finished: {info}")


if __name__ == "__main__":
    main()
