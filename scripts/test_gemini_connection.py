#!/usr/bin/env python3
"""Verify Gemini configuration/SDK availability (STORY-E2B-008.4.2).

Checks:
- GEMINI_API_KEY or GOOGLE_API_KEY is present (value never printed).
- google-genai SDK is importable (if not, prints install guidance).
- If both are present, runs a tiny text generation and prints model latency.

Safe to run without keys: reports SKIP/ guidance and exits 0.
"""
from __future__ import annotations

import os
import sys
import time

MODEL = os.environ.get("GEMINI_COMPUTER_USE_MODEL") or os.environ.get("GEMINI_TESTPLAN_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
VERIFICATION_DATE_PLACEHOLDER = "TODO-record-on-live-verification"


def has_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def sdk_available() -> tuple[bool, str]:
    try:
        import google.genai  # noqa: F401
        return True, "google-genai import OK"
    except Exception as e:
        return False, f"google-genai not importable: {e}"


def live_probe() -> tuple[bool, str]:
    if not has_key():
        return False, "SKIP: no GEMINI_API_KEY/GOOGLE_API_KEY (live model verification requires keys)"
    ok, msg = sdk_available()
    if not ok:
        return False, f"SKIP-live: {msg}. Install google-genai in the active venv (e.g. apps/cell/.venv) to verify models."
    try:
        from google import genai  # type: ignore

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        client = genai.Client(api_key=api_key)
        t0 = time.time()
        resp = client.models.generate_content(model=MODEL, contents="Reply with exactly: COMPUSE_OK")
        dt = int((time.time() - t0) * 1000)
        text = (getattr(resp, "text", None) or str(resp)).strip()
        ok_resp = "COMPUSE_OK" in text.upper()
        return ok_resp, f"Live probe responded in {dt}ms (model={MODEL}): {text[:120]!r}"
    except Exception as e:
        return False, f"Live probe failed: {type(e).__name__}: {e}"


def main() -> None:
    print("Gemini computer-use connection check")
    print(f"model (configured): {MODEL}")
    print(f"key present: {has_key()}")
    print(f"verification date placeholder: {VERIFICATION_DATE_PLACEHOLDER}")
    ok, msg = sdk_available()
    print(f"sdk: {msg}")
    if not has_key() or not ok:
        print(f"result: SKIP-live ({msg if not ok else 'no key'}; model/tool support must be verified with keys/network)")
        return
    success, detail = live_probe()
    print(f"live probe: {'OK' if success else 'FAILED'} — {detail}")
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
