from pathlib import Path

from cell.models import RunStatus
from cell.runs.state import Run, RunStore


def test_run_store_persists_across_instances(tmp_path: Path) -> None:
    store = RunStore(str(tmp_path))
    run = Run(run_id="run_persist", repo="fixture", commit="abc", scope="full", policy={})
    store.create(run)
    run.status = RunStatus.RUNNING
    store.save()

    reloaded = RunStore(str(tmp_path))

    loaded = reloaded.get("run_persist")
    assert loaded is not None
    assert loaded.status == RunStatus.RUNNING
    assert loaded.repo == "fixture"


def test_run_store_ignores_a_corrupt_state_file(tmp_path: Path) -> None:
    (tmp_path / "runs.json").write_text("{not json")

    store = RunStore(str(tmp_path))

    assert store.list() == []


def test_run_store_skips_invalid_records(tmp_path: Path) -> None:
    (tmp_path / "runs.json").write_text('{"runs":[{"run_id":"broken"}]}')

    store = RunStore(str(tmp_path))

    assert store.list() == []
