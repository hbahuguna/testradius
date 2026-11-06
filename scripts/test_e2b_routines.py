#!/usr/bin/env python3
"""Demo for STORY-E2B-006.2: Routines & Scheduling.

Shows E2B routine config, configurable cadence, run history, and notifications.
Uses injected runner (no live E2B required).
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.routines import RoutineConfig, RoutineHistory, Scheduler


def main() -> None:
    base = Path("artifacts/demo_e2b_routines")
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    notifications = []

    def mock_e2b_runner(cfg: RoutineConfig):
        return {
            "status": "COMPLETED",
            "run_id": f"{cfg.name}-20260102",
            "executor_type": cfg.executor_type,
            "target_url": cfg.target_url,
            "plan_id": (cfg.plan or {}).get("plan_id") if isinstance(cfg.plan, dict) else None,
            "summary": {"total_steps": 3, "passed_steps": 3},
        }

    scheduler = Scheduler(history=base / "routine_history.jsonl", runner=mock_e2b_runner, notifiers=[notifications.append])
    scheduler.register(RoutineConfig(
        name="testradius-nightly-smoke",
        cadence="@daily",  # configurable cadence; raw cron like "0 2 * * *" also supported/stored
        executor_type="e2b",
        target_url="https://testradius.dev",
        plan={"plan_id": "PLAN-NIGHTLY", "steps": [{"step_id": "S1"}, {"step_id": "S2"}, {"step_id": "S3"}]},
        metadata={"env": "staging", "template": "playwright-chromium"},
        notify_on=["completed", "failed"],
    ))

    print("=" * 72)
    print("STORY-E2B-006.2: Routines & Scheduling")
    print("=" * 72)
    now = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    due = scheduler.is_due(scheduler.routines["testradius-nightly-smoke"], now=now)
    print(f"Cadence=@daily, due now={due}")
    assert due is True

    result = scheduler.run_now("testradius-nightly-smoke")
    print(json.dumps({"routine": result["name"], "status": result["result"]["status"], "executor_type": result["executor_type"], "run_id": result["result"]["run_id"]}, indent=2))
    assert result["result"]["status"] == "COMPLETED"

    # not due immediately after run
    assert scheduler.is_due(scheduler.routines["testradius-nightly-smoke"], now=now + timedelta(hours=1)) is False
    print("After run, due in +1h:", scheduler.is_due(scheduler.routines["testradius-nightly-smoke"], now=now + timedelta(hours=1)))

    history = RoutineHistory(base / "routine_history.jsonl").records()
    print(f"\nRun history records: {len(history)}")
    for r in history:
        print(f"  - {r.get('event')} name={r.get('name')} status={r.get('status','')}")
    print(f"Notifications: {[n['event'] for n in notifications]}")
    assert any(r.get("event") == "run_completed" and r.get("executor_type") == "e2b" for r in history)
    assert "run_started" in [n["event"] for n in notifications] and "run_completed" in [n["event"] for n in notifications]

    print("\n✓ 006.2 demo passed: E2B routine registered, cadence evaluated, run executed, history+notifications recorded.")
    print("=" * 72)
    shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
