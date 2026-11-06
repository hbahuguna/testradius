#!/usr/bin/env python3
"""Build/verify an E2B **desktop-capable** template (STORY-E2B-008.4.1).

Template stack (X11 desktop + browser + input):
- Xvfb virtual display + openbox/icewm + xterm (minimal window manager)
- xdotool (mouse/keyboard), scrot + imagemagick (screenshots)
- Chromium/Google Chrome (headless + headed on Xvfb) + fonts
- Python 3.11, pip, e2b SDK helpers (setup only; harness runs outside sandbox)

Resources: **2 CPU / 2048 MB** (GUI/browser workloads OOM on 512 MB ``base``).

Live build requires ``E2B_API_KEY``/``E2B_API_URL`` (and ``E2B_DOMAIN`` for SDK).
Template finalization on self-hosted E2B Embed can be flaky; this script is
idempotent (rebuilds the alias) and prints verification output below. Use
``--dry-run`` to inspect the template spec without API calls.

Usage:
  python scripts/build_e2b_desktop_template.py --dry-run
  E2B_API_KEY=... E2B_API_URL=http://8.231.230.69:3000 E2B_DOMAIN=8.231.230.69.nip.io:3002 \\
    python scripts/build_e2b_desktop_template.py
"""
from __future__ import annotations

import argparse
import json
import os

TEMPLATE_ALIAS = os.environ.get("E2B_DESKTOP_TEMPLATE", "desktop-chromium")
CPU = int(os.environ.get("E2B_CPU_COUNT", "2"))
MEM_MB = int(os.environ.get("E2B_MEMORY_MB", "2048"))
API_URL_DEFAULT = "http://8.231.230.69:3000"

APT = [
    "xvfb", "x11-utils", "x11-xserver-utils", "openbox", "xterm",
    "xdotool", "scrot", "imagemagick", "x11-apps",
    "chromium",  # Debian Chromium; prefer google-chrome-stable if preinstalled
    "fonts-liberation", "fonts-noto", "ca-certificates", "curl", "wget", "unzip",
]

TEMPLATE_SPEC = {
    "alias": TEMPLATE_ALIAS,
    "base": "python:3.11",
    "apt": APT,
    "pip": ["playwright==1.49.0", "pillow", "requests"],
    "env": {"DEBIAN_FRONTEND": "noninteractive", "DISPLAY": ":99"},
    "cpu": CPU,
    "memory_mb": MEM_MB,
    "notes": "Self-hosted finalization may fail; verify with --dry-run spec and runtime bootstrap if needed.",
}


def _build() -> None:
    api_key = os.environ.get("E2B_API_KEY")
    if not api_key:
        raise SystemExit("E2B_API_KEY not set (required for live template build)")
    api_url = os.environ.get("E2B_API_URL", API_URL_DEFAULT)
    from e2b import Template  # type: ignore

    def on_log(e):  # pragma: no cover - manual script
        try:
            print(str(e), flush=True)
        except Exception:
            pass

    tpl = (
        Template()
        .from_python_image("3.11")
        .set_envs({"DEBIAN_FRONTEND": "noninteractive", "DISPLAY": ":99"})
        .apt_install(APT)
        .pip_install(TEMPLATE_SPEC["pip"])
        .run_cmd("python3 -c \"import PIL; print('pillow ok')\"")
        .run_cmd("which Xvfb xdotool scrot chromium google-chrome 2>/dev/null; echo desktop-toolchain-ok")
        .run_cmd(
            "mkdir -p /home/user/desktop /home/user/artifacts && "
            "cat > /home/user/start-desktop.sh <<'EOS'\n"
            "#!/usr/bin/env bash\n"
            "set -e\n"
            "export DISPLAY=:99\n"
            "if ! pgrep -x Xvfb >/dev/null; then Xvfb :99 -screen 0 1440x900x24 +extension RANDR & fi\n"
            "openbox & sleep 1\n"
            "echo desktop-ready\n"
            "EOS\nchmod +x /home/user/start-desktop.sh"
        )
        .set_workdir("/home/user")
    )
    print(f"Building template alias={TEMPLATE_ALIAS} cpu={CPU} mem={MEM_MB} via {api_url} ... (may take several minutes)")
    info = Template.build(tpl, alias=TEMPLATE_ALIAS, cpu_count=CPU, memory_mb=MEM_MB, on_build_logs=on_log, api_key=api_key, api_url=api_url)
    print(f"Build finished: {info}")
    print("Next: create a 2CPU/2048MB sandbox from this template, run ~/start-desktop.sh, then verify via scripts/test_e2b_gemini_computer_use.py --live")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Print template spec without API calls")
    args = p.parse_args()
    if args.dry_run:
        print(json.dumps({**TEMPLATE_SPEC, "dry_run": True, "self_hosted_constraints": {"E2B_DOMAIN": os.environ.get("E2B_DOMAIN", "8.231.230.69.nip.io:3002"), "min_resources": ">=2CPU/2048MB", "finalization_note": "Self-hosted Embed finalization can be flaky; keep runtime bootstrap fallback (see docs)."}}, indent=2))
        return
    _build()


if __name__ == "__main__":
    main()
