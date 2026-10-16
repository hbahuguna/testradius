"""E7 / E2 metering edge-case matrix.

Drives the *real* agent path (``AnalyzeRunner`` + ``LicenseGuard`` +
``license_client``) against a *real* license server (spawned as a subprocess
with the license-service venv) for the four metering edge cases:

  1. expiry mid-session  -> a completed analysis is kept, just not counted
  2. expiry mid-session  -> the next run is blocked at the gate
  3. grace expiry        -> offline beyond the 3-day grace blocks the gate
  4. quota hit           -> exhausted quota blocks before any analysis
  5. failed run          -> a backend error is never metered

Only the TestRadius backend is faked; the license server, the client's local
state store and the D1 "meter only on success" path are all real.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.e2e_three_repos import DEFAULT_LICENSE_PYTHON, LicenseServer
from tia_agent.analyze import AnalyzeRunner
from tia_agent.config import TiaConfig
from tia_agent.errors import BackendError, LicenseError
from tia_agent.license_guard import LicenseGuard
from tia_agent.radius_client import ProjectInfo
from license_client.store import LicenseStore

pytestmark = pytest.mark.skipif(
    not Path(DEFAULT_LICENSE_PYTHON).exists(),
    reason="license-service venv not available (needed to run the real server)",
)

_ENV_KEYS = (
    "TIA_LICENSE_URL",
    "TIA_RADIUS_URL",
    "TIA_CONFIG_HOME",
    "TIA_LICENSE_STATE_PATH",
    "TIA_GITHUB_TOKEN",
)


# ---------------------------------------------------------------------------
# fakes + helpers
# ---------------------------------------------------------------------------
class _FakeRadius:
    def __init__(self, raw=None, error=None):
        self.raw = raw if raw is not None else _sample_raw()
        self.error = error
        self.base_url = "http://radius.test:8000"
        self.analyzed = []

    def list_projects(self):
        return [ProjectInfo(id=7, name="acme/shop")]

    def analyze_pr(self, **kwargs):
        self.analyzed.append(kwargs)
        if self.error:
            raise self.error
        return self.raw

    def run_instrumentation(self, payload):
        return {"status": "COMPLETED"}


def _sample_raw():
    """One PR file -> one impacted symbol -> one reused test (real evidence shape)."""
    return {
        "project_id": 7,
        "full_name": "acme/shop",
        "pr_number": 42,
        "commit_sha": "abc123",
        "pr_files_analyzed": 1,
        "symbols_selected": 1,
        "tests_selected": 1,
        "total_tests_reused": 1,
        "results": [
            {
                "symbol_name": "apply_discount",
                "symbol_file": "src/shop.py",
                "symbol_summary": "",
                "symbol_type": "function",
                "priority_risk_index": 4200.0,
                "existing_tests": [
                    {"test_name": "test_apply_discount", "test_file": "tests/test_shop.py"}
                ],
            }
        ],
    }


@contextmanager
def _live_license(quota: int = 5):
    """Start a real license server + an activated agent guard against it."""
    server = LicenseServer(Path(DEFAULT_LICENSE_PYTHON), quota=quota)
    server.start()
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    tmp = tempfile.mkdtemp(prefix="tia-meter-")
    os.environ.update(
        TIA_LICENSE_URL=server.url,
        TIA_RADIUS_URL="http://radius.test:8000",
        TIA_CONFIG_HOME=tmp,
        TIA_LICENSE_STATE_PATH=os.path.join(tmp, "license.json"),
        TIA_GITHUB_TOKEN="",
    )
    try:
        key = server.create_license()
        config = TiaConfig.load()
        guard = LicenseGuard(config)
        yield server, config, guard, key
    finally:
        server.stop()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _connect(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path, timeout=10)


def _count_runs(db_path: str) -> int:
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def _set_period_end(db_path: str, license_key: str, when: datetime) -> None:
    """Expire a subscription mid-session, straight in the server's SQLite DB.

    SQLAlchemy's SQLite DateTime stores ``YYYY-MM-DD HH:MM:SS.ffffff`` (naive
    UTC); the server re-attaches UTC on read.
    """
    value = when.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE licenses SET current_period_end = ? WHERE license_key = ?",
            (value, license_key),
        )
        conn.commit()


def _age_last_validation(days: int) -> None:
    """Pretend the client's daily validation is stale so the next call refreshes."""
    path = Path(os.environ["TIA_LICENSE_STATE_PATH"])
    store = LicenseStore(path=path)
    state = store.load()
    state.last_validated_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    store.save(state)


def _runner(config: TiaConfig, guard: LicenseGuard, radius: _FakeRadius) -> AnalyzeRunner:
    return AnalyzeRunner(config, guard, radius)


# ---------------------------------------------------------------------------
# 1 + 2: expiry mid-session
# ---------------------------------------------------------------------------
def test_expiry_mid_session_keeps_result_but_does_not_count():
    """Gate caches a valid state; the subscription lapses before the run ends.

    The analysis must still be returned (metering is soft) but the server
    rejects the record, so nothing is counted.
    """
    with _live_license(quota=5) as (server, config, guard, key):
        guard.activate(key)
        radius = _FakeRadius()
        runner = _runner(config, guard, radius)

        # Lapse the subscription after the gate already cached a valid state.
        _set_period_end(server.db_path, key, datetime.now(timezone.utc) - timedelta(days=4))

        result = runner.run("acme/shop", 42, file_paths=["src/shop.py"])

        assert result.total_affected_tests == 1  # analysis preserved
        assert any("not counted" in n.lower() for n in result.notes)
        assert _count_runs(server.db_path) == 0


def test_expiry_mid_session_blocks_next_run_at_gate():
    """Once the daily refresh sees the lapse, the next run never analyzes."""
    with _live_license(quota=5) as (server, config, guard, key):
        guard.activate(key)
        radius = _FakeRadius()
        runner = _runner(config, guard, radius)

        _set_period_end(server.db_path, key, datetime.now(timezone.utc) - timedelta(days=4))
        _age_last_validation(days=2)  # forces the next ensure_valid to hit the server

        with pytest.raises(LicenseError) as exc:
            runner.run("acme/shop", 42, file_paths=["src/shop.py"])

        assert "expired" in str(exc.value).lower()
        assert radius.analyzed == []  # blocked before analysis
        assert _count_runs(server.db_path) == 0


# ---------------------------------------------------------------------------
# 3: grace expiry (offline beyond 3 days)
# ---------------------------------------------------------------------------
def test_offline_grace_expiry_blocks_at_gate():
    with _live_license(quota=5) as (server, config, guard, key):
        guard.activate(key)
        radius = _FakeRadius()
        runner = _runner(config, guard, radius)

        _age_last_validation(days=4)  # beyond the 3-day offline grace
        server.stop()  # server unreachable

        with pytest.raises(LicenseError) as exc:
            runner.run("acme/shop", 42, file_paths=["src/shop.py"])

        assert "grace" in str(exc.value).lower()
        assert radius.analyzed == []
        assert _count_runs(server.db_path) == 0


# ---------------------------------------------------------------------------
# 4: quota hit
# ---------------------------------------------------------------------------
def test_quota_hit_blocks_before_analysis():
    with _live_license(quota=1) as (server, config, guard, key):
        guard.activate(key)
        radius = _FakeRadius()
        runner = _runner(config, guard, radius)

        first = runner.run("acme/shop", 42, file_paths=["src/shop.py"])
        assert first.total_affected_tests == 1
        assert _count_runs(server.db_path) == 1

        with pytest.raises(LicenseError) as exc:
            runner.run("acme/shop", 43, file_paths=["src/shop.py"])

        assert "quota" in str(exc.value).lower()
        assert len(radius.analyzed) == 1  # 2nd run blocked before analysis
        assert _count_runs(server.db_path) == 1


# ---------------------------------------------------------------------------
# 5: failed runs are not counted
# ---------------------------------------------------------------------------
def test_failed_run_is_not_counted_then_success_counts_once():
    with _live_license(quota=5) as (server, config, guard, key):
        guard.activate(key)
        radius = _FakeRadius(error=BackendError("analyze-pr failed: HTTP 500"))
        runner = _runner(config, guard, radius)

        with pytest.raises(BackendError):
            runner.run("acme/shop", 42, file_paths=["src/shop.py"])
        assert _count_runs(server.db_path) == 0  # failure never meters

        radius.error = None
        runner.run("acme/shop", 42, file_paths=["src/shop.py"])
        assert _count_runs(server.db_path) == 1  # the successful retry counts once
