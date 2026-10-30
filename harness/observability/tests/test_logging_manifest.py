from harness.observability.logging import StructuredLogger
from harness.observability.manifest import RunManifest


def test_structured_logger_creates_event():
    logger = StructuredLogger(run_id="r1", component="executor")
    event = logger.info("started", step="navigate")
    assert event.run_id == "r1"
    assert event.level == "info"
    assert event.context["step"] == "navigate"
    assert "ts" in event.to_json()


def test_run_manifest_lifecycle(tmp_path):
    m = RunManifest(run_id="r1", target="https://testradius.dev", model="gemini-2.5-flash")
    m.mark_started()
    m.add_step("s1", "Navigate", "COMPLETED")
    m.add_artifact("screenshot", "artifacts/run-r1/01.png")
    m.mark_finished("COMPLETED")
    assert m.status == "COMPLETED"
    assert m.ended_at is not None
    assert len(m.steps) == 1
    assert len(m.artifacts) == 1
    path = tmp_path / "manifest.json"
    m.save(path)
    loaded = RunManifest.load(path)
    assert loaded.run_id == "r1"
    assert loaded.steps[0]["id"] == "s1"
