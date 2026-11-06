"""Vision QA client with multi-model support (STORY-E2B-004.2).

Backward compatible: `VisionClient().inspect(screenshot_path)` returns
`List[Dict[str, Any]]` with `type/category`, `issue`, `confidence` keys.

Extended: `analyze()` returns structured `VisionAnalysisResult`; `analyze_artifacts()`
inspects screenshots collected by E2B/harness artifact manifests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .models import QA_CATEGORIES, VisionAnalysisResult, VisionFinding
from .prompts import build_qa_vision_prompt
from .providers import (
    AnthropicVisionProvider,
    BaseVisionProvider,
    GeminiVisionProvider,
    MockVisionProvider,
    OpenAIVisionProvider,
)

SCREENSHOT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _default_findings() -> List[VisionFinding]:
    # Preserve legacy clean behavior.
    return [
        VisionFinding(category="layout", issue="none", confidence=0.9, description="No issue detected.", severity="info"),
        VisionFinding(category="contrast", issue="ok", confidence=0.9, description="No issue detected.", severity="info"),
        VisionFinding(category="clipping", issue="none", confidence=0.9, description="No issue detected.", severity="info"),
        VisionFinding(category="overlap", issue="none", confidence=0.9, description="No issue detected.", severity="info"),
        VisionFinding(category="responsive", issue="ok", confidence=0.9, description="No issue detected.", severity="info"),
    ]


def parse_model_spec(model: Optional[str]) -> Tuple[str, Optional[str]]:
    """Parse 'provider:model' or aliases. Returns (provider, model_name)."""
    raw = (model or "").strip()
    if not raw:
        return "mock", None
    lowered = raw.lower()
    if lowered in {"mock", "fake", "test", "gpt-vision-default", "default-vision"}:
        return "mock", None
    if ":" in raw:
        provider, model_name = raw.split(":", 1)
        provider = provider.strip().lower()
        model_name = model_name.strip() or None
        aliases = {"gpt": "openai", "claude": "anthropic", "google": "gemini"}
        return aliases.get(provider, provider), model_name
    # Aliases / legacy names
    if lowered.startswith(("claude", "anthropic")):
        return "anthropic", raw
    if lowered.startswith(("gemini", "google")):
        return "gemini", raw
    if lowered.startswith(("gpt", "openai", "o1", "o3", "o4")):
        return "openai", raw
    # Unknown legacy model string: preserve old non-calling behavior
    return "mock", None


class VisionClient:
    """Facade for screenshot vision QA across providers."""

    def __init__(
        self,
        model: str = "mock",
        *,
        provider: Optional[BaseVisionProvider] = None,
        api_key: Optional[str] = None,
        use_live: bool = False,
    ):
        self.model = model
        self._explicit_provider = provider
        self._api_key = api_key
        self._use_live = use_live
        self._provider_name, self._model_name = parse_model_spec(model)
        self._provider = provider or self._build_provider(self._provider_name, api_key=api_key)

    def _build_provider(self, name: str, api_key: Optional[str] = None) -> BaseVisionProvider:
        if name == "gemini":
            return GeminiVisionProvider(api_key=api_key)
        if name == "openai":
            return OpenAIVisionProvider(api_key=api_key)
        if name in {"anthropic", "claude"}:
            return AnthropicVisionProvider(api_key=api_key)
        return MockVisionProvider()

    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "name", self._provider_name)

    def analyze(
        self,
        screenshot_path: Union[str, Path],
        *,
        url: Optional[str] = None,
        step_intent: Optional[str] = None,
        expected: Optional[str] = None,
        viewport: Optional[str] = None,
        extra_context: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> VisionAnalysisResult:
        screenshot = str(screenshot_path)
        prompt_text = prompt or build_qa_vision_prompt(
            url=url, step_intent=step_intent, expected=expected, viewport=viewport, extra_context=extra_context
        )
        model_name = self._model_name

        # Backward-compat: only the implicit default mock path avoids provider calls.
        # Explicit providers (including injected/configured MockVisionProvider) are executed.
        if self._explicit_provider is None and self.provider_name == "mock" and self.model in {"mock", "fake", "test", "gpt-vision-default", "default-vision", ""}:
            findings = _default_findings()
            return VisionAnalysisResult(
                screenshot_path=screenshot,
                model=model_name or self.model or "mock",
                provider="mock",
                findings=findings,
                summary="Mock vision analysis (no live model call).",
            )

        # If configured for a live provider but missing credentials/SDK, fall back to mock
        # only when not explicitly forced live? Prefer explicit error for explicit provider specs.
        payload, raw_text, error = self._provider.analyze_image(screenshot, prompt_text, model=model_name)
        if error and self._provider_name == "mock":
            findings = _default_findings()
            return VisionAnalysisResult(
                screenshot_path=screenshot,
                model=model_name or self.model,
                provider=self.provider_name,
                findings=findings,
                summary="Mock vision analysis.",
                raw_response=raw_text,
                error=None,
            )
        if error:
            # Explicit provider error: return structured error result (tests/demos can inspect).
            return VisionAnalysisResult(
                screenshot_path=screenshot,
                model=model_name or self.model,
                provider=self.provider_name,
                findings=[],
                summary="",
                raw_response=raw_text,
                error=error,
            )

        findings = self._parse_findings(payload)
        summary = str((payload or {}).get("summary") or "")
        return VisionAnalysisResult(
            screenshot_path=screenshot,
            model=model_name or self.model,
            provider=self.provider_name,
            findings=findings,
            summary=summary,
            raw_response=raw_text,
            error=None,
            metadata={"payload_keys": sorted((payload or {}).keys())},
        )

    def inspect(self, screenshot_path: str) -> List[Dict[str, Any]]:
        """Backward-compatible API: returns list of finding dicts."""
        result = self.analyze(screenshot_path)
        if result.findings:
            return [f.to_dict() for f in result.findings]
        if result.error:
            # Keep shape stable for legacy callers
            return [{"type": c, "issue": "analysis_error", "confidence": 0.0, "error": result.error} for c in QA_CATEGORIES]
        return [f.to_dict() for f in _default_findings()]

    def analyze_artifacts(
        self,
        run_dir: Optional[Union[str, Path]] = None,
        *,
        manifest_path: Optional[Union[str, Path]] = None,
        screenshots: Optional[Sequence[Union[str, Path]]] = None,
        limit: int = 20,
        **context: Any,
    ) -> List[VisionAnalysisResult]:
        """Analyze screenshot artifacts from an E2B/harness run directory or manifest."""
        paths = list(screenshots or [])
        if manifest_path:
            paths.extend(self._screenshots_from_manifest(Path(manifest_path)))
        if run_dir:
            run_path = Path(run_dir)
            manifest = run_path / "manifest.json"
            if manifest.exists() and not manifest_path:
                paths.extend(self._screenshots_from_manifest(manifest))
            if not paths:
                paths.extend(sorted(p for p in run_path.iterdir() if p.suffix.lower() in SCREENSHOT_EXTS))

        # Dedupe preserving order
        seen = set()
        unique: List[Path] = []
        for p in paths:
            pp = Path(p)
            key = str(pp.resolve()) if pp.exists() else str(pp)
            if key not in seen and pp.suffix.lower() in SCREENSHOT_EXTS:
                seen.add(key)
                unique.append(pp)
        return [self.analyze(p, **context) for p in unique[: max(0, int(limit))]]

    def _screenshots_from_manifest(self, manifest_path: Path) -> List[Path]:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        run_dir = manifest_path.parent
        results: List[Path] = []
        for item in data.get("artifacts") or []:
            if (item.get("type") or "").lower() != "screenshot":
                continue
            raw = item.get("path") or item.get("filename")
            if not raw:
                continue
            p = Path(raw)
            candidates = [p, run_dir / p.name, run_dir / raw, Path.cwd() / raw]
            for c in candidates:
                if c.exists():
                    results.append(c)
                    break
            else:
                # Keep manifest-relative filename fallback
                results.append(run_dir / Path(raw).name)
        return results

    def _parse_findings(self, payload: Any) -> List[VisionFinding]:
        if not isinstance(payload, dict):
            return _default_findings()
        raw_findings = payload.get("findings")
        if not isinstance(raw_findings, list) or not raw_findings:
            return _default_findings()
        findings: List[VisionFinding] = []
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            f = VisionFinding.from_dict(item)
            # Normalize common model outputs
            if not f.category:
                f.category = "unknown"
            if f.confidence > 1.0:
                f.confidence = min(1.0, f.confidence / 100.0)
            findings.append(f)
        return findings or _default_findings()
