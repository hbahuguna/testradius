"""Tests for live state translation."""
from harness.integrations.cloudroom import LiveStateTranslator


def test_translate():
    t = LiveStateTranslator()
    journal = {"events": [{"message": "Starting test TC01"}, {"message": "TC01 completed"}, {"message": "Running TC02"}]}
    state = t.translate(journal, "r1", "https://example.com")
    assert state["runId"] == "r1"
    assert len(state["steps"]) > 0
    assert "progress" in state
    assert len(state["logs"]) == 3
