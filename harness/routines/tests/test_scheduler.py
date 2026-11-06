"""Tests for STORY-E2B-006.2 — Routines & Scheduling."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness.routines import RoutineConfig, RoutineHistory, Scheduler


def test_legacy_schedule_and_run_now(tmp_path):
    s = Scheduler(history=tmp_path / "history.jsonl")
    rec = s.schedule("nightly", cron="0 2 * * *")
    assert rec["name"] == "nightly" and rec["cron"] == "0 2 * * *"
    run = s.run_now("nightly")  # legacy: no runner, no registered config
    assert run["name"] == "nightly"
    assert run["status"] == "ok"
    assert "run_at" in run
    rows = [json.loads(l) for l in (tmp_path / "history.jsonl").read_text().splitlines() if l.strip()]
    assert any(r.get("event") == "scheduled" for r in rows)
    assert any(r.get("event") == "run_completed" for r in rows)


def test_register_e2b_routine_and_run_with_injected_runner(tmp_path):
    notifications = []
    calls = []

    def runner(cfg: RoutineConfig):
        calls.append(cfg.name)
        return {"status": "COMPLETED", "run_id": f"{cfg.name}-run", "executor_type": cfg.executor_type}

    s = Scheduler(history=tmp_path / "history.jsonl", runner=runner, notifiers=[notifications.append])
    cfg = RoutineConfig(
        name="e2b-nightly", cadence="@daily", executor_type="e2b", target_url="https://testradius.dev",
        plan={"plan_id": "P1", "steps": [{"step_id": "S1"}]}, metadata={"env": "staging"},
    )
    s.register(cfg)
    result = s.run_now("e2b-nightly")

    assert calls == ["e2b-nightly"]
    assert result["status"].lower() in {"completed", "ok"}
    assert result["result"]["status"] == "COMPLETED"
    assert any(n["event"] == "run_started" for n in notifications)
    assert any(n["event"] == "run_completed" and n["status"] == "COMPLETED" for n in notifications)
    history = RoutineHistory(tmp_path / "history.jsonl").records()
    assert any(r.get("event") == "registered" and r.get("name") == "e2b-nightly" for r in history)
    assert any(r.get("event") == "run_completed" and r.get("executor_type") == "e2b" for r in history)


def test_cadence_due_checks(tmp_path):
    s = Scheduler(history=tmp_path / "history.jsonl")
    daily = RoutineConfig(name="daily", cadence="@daily")
    interval = RoutineConfig(name="int", cadence="interval:60")
    manual = RoutineConfig(name="manual", cadence="manual")
    cron = RoutineConfig(name="cron", cadence="0 2 * * *")  # external cron string
    now = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)

    assert s.is_due(daily, now=now) is True  # never run
    assert s.is_due(interval, now=now) is True
    assert s.is_due(manual, now=now) is False
    assert s.is_due(cron, now=now) is False  # raw cron not evaluated in-process

    s.history.append({"event": "run_completed", "name": "daily", "ts": (now - timedelta(hours=1)).isoformat()})
    s.history.append({"event": "run_completed", "name": "int", "ts": (now - timedelta(seconds=30)).isoformat()})
    assert s.is_due(daily, now=now) is False
    assert s.is_due(interval, now=now) is False
    s.history.append({"event": "run_completed", "name": "int", "ts": (now - timedelta(seconds=120)).isoformat()})
    assert s.is_due(interval, now=now) is True


def test_run_due_executes_only_due_routines(tmp_path):
    ran = []

    def runner(cfg):
        ran.append(cfg.name)
        return {"status": "COMPLETED"}

    now = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    s = Scheduler(history=tmp_path / "history.jsonl", runner=runner)
    s.register(RoutineConfig(name="due", cadence="@daily"))
    s.register(RoutineConfig(name="manual", cadence="manual"))
    s.register(RoutineConfig(name="notdue", cadence="@daily"))
    s.history.append({"event": "run_completed", "name": "notdue", "ts": (now - timedelta(hours=1)).isoformat()})

    results = s.run_due(now=now)
    assert [r["name"] for r in results] == ["due"]
    assert ran == ["due"]


def test_failed_run_records_history_and_notifies(tmp_path):
    notifications = []

    def runner(cfg):
        raise RuntimeError("E2B unavailable")

    s = Scheduler(history=tmp_path / "history.jsonl", runner=runner, notifiers=[notifications.append])
    s.register(RoutineConfig(name="broken", cadence="@daily", notify_on=["failed"]))
    rec = s.run_now("broken")
    assert rec["status"] == "failed"
    assert "E2B unavailable" in rec["error"]
    assert any(n["event"] == "run_failed" for n in notifications)
    rows = RoutineHistory(tmp_path / "history.jsonl").records()
    assert any(r.get("event") == "run_failed" and r.get("name") == "broken" for r in rows)
