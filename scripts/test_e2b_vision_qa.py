#!/usr/bin/env python3
"""Demo for STORY-E2B-004.2: Vision QA Analysis.

Analyzes collected screenshot artifacts (E2B/harness run manifest) with a
configurable vision model and produces structured QA findings for
layout/contrast/clipping/overlap/responsive issues.

Usage:
  # Mock/demo mode (no API key required):
  python scripts/test_e2b_vision_qa.py

  # Live Gemini (requires GEMINI_API_KEY/GOOGLE_API_KEY):
  python scripts/test_e2b_vision_qa.py --model gemini:gemini-2.0-flash --run-dir artifacts/run-<id>

  # Analyze a specific manifest:
  python scripts/test_e2b_vision_qa.py --manifest artifacts/run-<id>/manifest.json --model mock
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.vision import VisionClient
from harness.vision.providers import MockVisionProvider


def _make_demo_run(base: Path) -> Path:
    run_dir = base / "run-vision-demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    # Filenames influence mock provider mode for demo purposes.
    (run_dir / "homepage.png").write_bytes(b"\x89PNG\r\n\x1a\n(demo homepage screenshot)")
    (run_dir / "hero_contrast_issue.png").write_bytes(b"\x89PNG\r\n\x1a\n(demo contrast issue screenshot)")
    manifest = {
        "run_id": "run-vision-demo",
        "source": {"provider": "demo", "sandbox_id": "sbx-demo"},
        "artifacts": [
            {"type": "screenshot", "path": "artifacts/run-vision-demo/homepage.png", "filename": "homepage.png"},
            {"type": "screenshot", "path": "artifacts/run-vision-demo/hero_contrast_issue.png", "filename": "hero_contrast_issue.png"},
            {"type": "trace", "path": "artifacts/run-vision-demo/trace.zip", "filename": "trace.zip"},
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Vision QA analysis demo")
    parser.add_argument("--model", default="mock", help="Model spec: mock, gemini:<id>, openai:<id>, anthropic:<id>")
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help="Write vision_report.json here (or run dir)")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    temp_base = None
    run_dir = args.run_dir
    manifest = args.manifest
    if not run_dir and not manifest:
        temp_base = Path("artifacts/demo_vision_qa_tmp")
        if temp_base.exists():
            shutil.rmtree(temp_base)
        temp_base.mkdir(parents=True)
        run_dir = _make_demo_run(temp_base)
        manifest = run_dir / "manifest.json"

    # Use mock provider with filename-aware behavior for local demo.
    client = VisionClient(model=args.model, provider=MockVisionProvider() if args.model == "mock" else None)
    print("=== STORY-E2B-004.2: Vision QA Analysis Demo ===\n")
    print(f"Model spec: {args.model} (resolved provider: {client.provider_name})")
    if run_dir:
        print(f"Run dir:    {run_dir}")
    if manifest:
        print(f"Manifest:   {manifest}")

    results = client.analyze_artifacts(
        run_dir=run_dir,
        manifest_path=manifest,
        limit=args.limit,
        url="https://testradius.dev",
        viewport="1280x800",
        extra_context="E2B sandbox evidence",
    )

    print(f"\nAnalyzed screenshots: {len(results)}")
    report = {"story": "STORY-E2B-004.2", "model": args.model, "results": [r.to_dict() for r in results]}
    for r in results:
        print(f"\n- {Path(r.screenshot_path).name} [{r.provider}:{r.model}] passed={r.passed}")
        print(f"  summary: {r.summary}")
        if r.error:
            print(f"  error:   {r.error}")
        for f in r.findings:
            issue = getattr(f, "issue", "")
            sev = getattr(f, "severity", "info")
            cat = getattr(f, "category", "")
            conf = getattr(f, "confidence", 0)
            print(f"    • [{cat}] {issue} severity={sev} confidence={conf:.2f}")
            desc = getattr(f, "description", "")
            if desc:
                print(f"      {desc}")

    out_path = args.out or ((Path(run_dir) / "vision_report.json") if run_dir else Path("vision_report.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nStructured report written: {out_path}")

    if temp_base and temp_base.exists():
        shutil.rmtree(temp_base, ignore_errors=True)
        if out_path.exists() and "demo_vision_qa_tmp" in str(out_path):
            pass

    # Demo passes if we produced structured findings for screenshots
    assert results, "No screenshots analyzed"
    assert all(isinstance(r.to_dict().get("findings"), list) for r in results)
    print("\n✓ STORY-E2B-004.2 DEMO PASSED: Vision findings generated.")


if __name__ == "__main__":
    main()
