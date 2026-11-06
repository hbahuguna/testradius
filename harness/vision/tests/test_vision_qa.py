"""Tests for STORY-E2B-004.2 — Vision QA Analysis."""
import json
from pathlib import Path

from harness.vision import (
    QA_CATEGORIES,
    SelfInspector,
    VisionAnalysisResult,
    VisionClient,
    VisionFinding,
    build_qa_vision_prompt,
    parse_model_spec,
)
from harness.vision.providers import MockVisionProvider


def test_parse_model_spec():
    assert parse_model_spec("mock") == ("mock", None)
    assert parse_model_spec("gemini:gemini-2.0-flash") == ("gemini", "gemini-2.0-flash")
    assert parse_model_spec("gpt-4o-mini") == ("openai", "gpt-4o-mini")
    assert parse_model_spec("claude-sonnet-4-5") == ("anthropic", "claude-sonnet-4-5")
    assert parse_model_spec("gpt-vision-default") == ("mock", None)  # legacy compat


def test_qa_prompt_includes_categories_and_context():
    prompt = build_qa_vision_prompt(url="https://example.com", step_intent="Check hero", expected="No overlap", viewport="1280x800")
    for c in QA_CATEGORIES:
        assert c in prompt
    assert "https://example.com" in prompt
    assert "Check hero" in prompt
    assert "JSON" in prompt


def test_mock_provider_clean_and_issue_modes(tmp_path):
    img = tmp_path / "clean.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    provider = MockVisionProvider(mode="clean")
    payload, raw, err = provider.analyze_image(str(img), "prompt")
    assert err is None
    assert payload["summary"]
    cats = {f["category"] for f in payload["findings"]}
    assert set(QA_CATEGORIES).issubset(cats)

    issue_img = tmp_path / "hero_contrast_issue.png"
    issue_img.write_bytes(b"\x89PNG\r\n\x1a\n")
    payload2, _, err2 = provider.analyze_image(str(issue_img), "prompt")
    assert err2 is None
    contrast = [f for f in payload2["findings"] if f["category"] == "contrast"][0]
    assert contrast["severity"] in {"medium", "high", "low", "critical", "info"}


def test_vision_client_backward_compatible_inspect(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    client = VisionClient(model="gpt-vision-default")  # legacy
    findings = client.inspect(str(img))
    assert isinstance(findings, list)
    assert findings
    assert all("type" in f or "category" in f for f in findings)
    assert all("issue" in f for f in findings)
    assert all("confidence" in f for f in findings)


def test_vision_client_structured_analysis(tmp_path):
    img = tmp_path / "broken_layout.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    client = VisionClient(model="mock", provider=MockVisionProvider(mode="issues"))
    result = client.analyze(str(img), url="https://testradius.dev", step_intent="Verify hero")
    assert isinstance(result, VisionAnalysisResult)
    assert result.provider == "mock"
    assert result.error is None
    assert result.findings
    assert not result.passed  # has medium/high issues
    d = result.to_dict()
    assert d["screenshot_path"].endswith("broken_layout.png")
    assert "passed" in d and "findings" in d


def test_vision_client_parses_provider_json_response():
    class FakeProvider:
        name = "fake"

        def analyze_image(self, image_path, prompt, *, model=None, **kwargs):
            return {
                "summary": "Found clipping.",
                "findings": [
                    {"category": "clipping", "issue": "Button clipped", "severity": "high", "confidence": 93, "description": "CTA cut off", "location": "footer", "suggestion": "Fix overflow"},
                    {"category": "layout", "issue": "none", "severity": "info", "confidence": 0.8, "description": "ok", "suggestion": ""},
                ],
            }, "{\"summary\": \"Found clipping.\"}", None

    client = VisionClient(model="fake:model", provider=FakeProvider())
    result = client.analyze("/tmp/nonexistent.png")
    assert result.summary == "Found clipping."
    assert len(result.findings) == 2
    assert result.findings[0].category == "clipping"
    assert result.findings[0].confidence == 0.93  # normalized from 93
    assert result.passed is False


def test_analyze_artifacts_from_manifest(tmp_path):
    run_dir = tmp_path / "artifacts" / "run-v1"
    run_dir.mkdir(parents=True)
    (run_dir / "A.png").write_bytes(b"\x89PNG\r\n\x1a\nA")
    (run_dir / "B.png").write_bytes(b"\x89PNG\r\n\x1a\nB")
    (run_dir / "console.log").write_text("log")
    manifest = {
        "run_id": "run-v1",
        "artifacts": [
            {"type": "screenshot", "path": f"artifacts/run-v1/A.png", "filename": "A.png"},
            {"type": "screenshot", "path": f"artifacts/run-v1/B.png", "filename": "B.png"},
            {"type": "trace", "path": f"artifacts/run-v1/trace.zip", "filename": "trace.zip"},
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))

    client = VisionClient(model="mock")
    results = client.analyze_artifacts(run_dir=run_dir)
    assert len(results) == 2
    assert all(isinstance(r, VisionAnalysisResult) for r in results)
    assert {Path(r.screenshot_path).name for r in results} == {"A.png", "B.png"}


def test_self_inspector_dedupes_and_keeps_rounds(tmp_path):
    img = tmp_path / "page.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    inspector = SelfInspector(rounds=2, client=VisionClient(model="mock"))
    report = inspector.inspect(str(img))
    assert report["summary"]["round_count"] == 2
    assert len(report["rounds"]) == 2
    assert "deduped" in report
    assert report["summary"]["deduped_findings"] <= report["summary"]["total_findings"]
    # each round has findings
    assert all(isinstance(r.get("findings"), list) for r in report["rounds"])


def test_finding_from_dict_accepts_type_alias():
    f = VisionFinding.from_dict({"type": "overlap", "issue": "Overlap detected", "confidence": 0.7})
    assert f.category == "overlap"
    assert f.to_dict()["type"] == "overlap"
