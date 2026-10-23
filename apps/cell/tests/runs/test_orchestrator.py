import asyncio

from cell.models import RunStatus
from cell.policy.engine import PolicyEngine
from cell.runs.orchestrator import Orchestrator
from cell.runs.state import Run, RunStore


def test_orchestrator_drives_seven_phases():
    async def scenario():
        store = RunStore()
        run = Run(run_id="r1", repo="x", commit="y", scope="full", policy={})
        store.create(run)
        orchestrator = Orchestrator(store)
        orchestrator.start(run)
        for _ in range(200):
            await asyncio.sleep(0.01)
            if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
                break
        assert run.status == RunStatus.SUCCEEDED
        assert run.phase is not None and run.phase.value == "report"

    asyncio.run(scenario())


def test_policy_engine_allowlist():
    policy = PolicyEngine()
    policy.load({"allow_network": False})
    assert not policy.check_network("example.com").allowed
    policy.load({"allow_network": True, "allowed_hosts": ["example.com"]})
    assert policy.check_network("example.com").allowed
    assert not policy.check_network("bad.com").allowed


def test_secrets_do_not_log_values(monkeypatch, caplog):
    from cell.secrets.broker import VaultBroker

    monkeypatch.setenv("CELL_SECRET_FACTORY_LLM", "sentinel-secret-value")
    broker = VaultBroker()
    assert broker.get_secret("factory/llm") == "sentinel-secret-value"
    assert "sentinel-secret-value" not in caplog.text


def test_resume_skips_already_completed_phases(tmp_path):
    from cell.models import Phase

    async def scenario():
        store = RunStore(str(tmp_path))
        run = Run(
            run_id="run_resume",
            repo="x",
            commit="y",
            scope="full",
            policy={"stub_delay_ms": 1},
            status=RunStatus.RUNNING,
            phase=Phase.EXECUTE,
        )
        store.create(run)
        orchestrator = Orchestrator(store, str(tmp_path))
        orchestrator.resume_incomplete()

        for _ in range(300):
            await asyncio.sleep(0.01)
            if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
                break

        assert run.status == RunStatus.SUCCEEDED
        started = [
            event["phase"]
            for event in orchestrator.get_events(run.run_id)
            if event["payload"].get("event") == "phase.started"
        ]
        assert started[0] == "prove"
        assert "execute" not in started

    asyncio.run(scenario())


def test_cancel_running_run_is_immediate():
    async def scenario():
        store = RunStore()
        run = Run(
            run_id="run_cancel",
            repo="x",
            commit="y",
            scope="full",
            policy={"stub_delay_ms": 200},
        )
        store.create(run)
        orchestrator = Orchestrator(store)
        orchestrator.start(run)
        await asyncio.sleep(0.05)
        assert await orchestrator.cancel(run.run_id) is True
        await asyncio.sleep(0.05)
        assert run.status == RunStatus.CANCELLED
        assert await orchestrator.cancel(run.run_id) is False

    asyncio.run(scenario())
