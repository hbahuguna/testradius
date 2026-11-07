"""Gemini compiler: normalized context -> validated CompiledExecutionTestPlan (008.3).

Uses a pluggable text-generation client for testability. Real Gemini calls require
`google-genai` and `GEMINI_API_KEY`/`GOOGLE_API_KEY` in the environment.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Union

from harness.context.schema import ContextBundle
from harness.policy.redaction import Redactor

from .prompts.v1 import PROMPT_VERSION, build_compile_messages, build_repair_messages
from .schema import CompiledExecutionTestPlan
from .validator import CompiledPlanValidator, ValidationResult


class TextGenerator(Protocol):
    model: str

    def generate(self, *, system: str, user: str) -> str: ...


@dataclass
class CompileResult:
    ok: bool
    plan: Optional[CompiledExecutionTestPlan]
    validation: Optional[ValidationResult]
    raw_text: Optional[str] = None
    repaired: bool = False
    attempts: int = 0
    artifact_path: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "attempts": self.attempts,
            "repaired": self.repaired,
            "artifact_path": self.artifact_path,
            "error": self.error,
            "validation": self.validation.to_dict() if self.validation else None,
            "metadata": self.metadata,
        }


class GeminiTestPlanCompiler:
    """Compile normalized context into a validated execution test plan."""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        generator: Optional[TextGenerator] = None,
        validator: Optional[CompiledPlanValidator] = None,
        redactor: Optional[Redactor] = None,
        max_repair_attempts: int = 2,
    ):
        self.model = model or os.environ.get("GEMINI_TESTPLAN_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.generator = generator or GoogleGenAITextGenerator(model=self.model, api_key=self.api_key)
        self.validator = validator or CompiledPlanValidator()
        self.redactor = redactor or Redactor()
        self.max_repair_attempts = max(0, int(max_repair_attempts))

    def compile(
        self,
        *,
        context_bundle: Union[ContextBundle, Mapping[str, Any]],
        sut_config: Mapping[str, Any],
        run_id: Optional[str] = None,
        run_config: Optional[Mapping[str, Any]] = None,
        provided_acs: Optional[Sequence[str]] = None,
        artifacts_dir: Union[str, Path] = "artifacts",
        mode: str = "local_spike",
        save: bool = True,
    ) -> CompileResult:
        ctx = context_bundle.to_compiler_input() if isinstance(context_bundle, ContextBundle) else dict(context_bundle)
        sut = dict(sut_config or {})
        acs = list(provided_acs or ctx.get("acceptance_criteria") or [])
        messages = build_compile_messages(context_bundle=ctx, sut_config=sut, run_config=run_config, provided_acs=acs)
        system = messages[0]["content"]
        user = messages[1]["content"]

        last_raw = None
        last_validation: Optional[ValidationResult] = None
        repaired = False
        try:
            raw = self.generator.generate(system=system, user=user)
            last_raw = raw
            for attempt in range(1, self.max_repair_attempts + 2):
                plan_dict = self._extract_json(raw)
                plan_dict = self._apply_defaults(plan_dict, ctx=ctx, sut=sut)
                validation = self.validator.validate(plan_dict, mode=mode, provided_acs=acs, require_human_review_for_production=(mode == "production"))
                last_validation = validation
                if validation.ok:
                    plan = CompiledExecutionTestPlan.model_validate(plan_dict)
                    plan.generator = plan.generator if not isinstance(plan.generator, dict) else plan.generator
                    gen = plan.generator.model_dump() if hasattr(plan.generator, "model_dump") else dict(plan.generator)
                    gen.update({"model": getattr(self.generator, "model", self.model), "prompt_version": PROMPT_VERSION, "compiler": "harness.testplan.compiler.GeminiTestPlanCompiler"})
                    gen["model_verification"] = {
                        "verified_live": False,
                        "note": "Live model/tool verification requires GEMINI_API_KEY/GOOGLE_API_KEY and network access; record verified model IDs/date during 008.4 spike or production setup.",
                    }
                    plan.generator = gen  # type: ignore[assignment]
                    artifact = self._save(plan, ctx=ctx, sut=sut, run_id=run_id, artifacts_dir=artifacts_dir, validation=validation, attempts=attempt, repaired=repaired) if save else None
                    return CompileResult(ok=True, plan=plan, validation=validation, raw_text=raw, repaired=repaired, attempts=attempt, artifact_path=str(artifact) if artifact else None, metadata={"prompt_version": PROMPT_VERSION, "model": getattr(self.generator, "model", self.model)})
                if attempt > self.max_repair_attempts:
                    break
                repaired = True
                repair_messages = build_repair_messages(previous_json=self._safe_json(plan_dict), validation_errors=[i.model_dump() for i in validation.issues + validation.warnings], context_bundle=ctx, sut_config=sut)
                raw = self.generator.generate(system=repair_messages[0]["content"], user=repair_messages[1]["content"])
                last_raw = raw
            return CompileResult(ok=False, plan=None, validation=last_validation, raw_text=last_raw, repaired=repaired, attempts=self.max_repair_attempts + 1, error="Validation failed after bounded repair attempts", metadata={"prompt_version": PROMPT_VERSION, "model": getattr(self.generator, "model", self.model)})
        except Exception as e:
            return CompileResult(ok=False, plan=None, validation=last_validation, raw_text=last_raw, repaired=repaired, attempts=0, error=str(e), metadata={"prompt_version": PROMPT_VERSION, "model": getattr(self.generator, "model", self.model)})

    def _extract_json(self, text: str) -> Dict[str, Any]:
        s = (text or "").strip()
        if s.startswith("```"):
            lines = s.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            obj = json.loads(s[start:end + 1])
            if isinstance(obj, dict):
                return obj
        raise ValueError("Model output did not contain a JSON object")

    def _apply_defaults(self, plan: Dict[str, Any], *, ctx: Mapping[str, Any], sut: Mapping[str, Any]) -> Dict[str, Any]:
        out = dict(plan)
        out.setdefault("schema_version", "1.0.0")
        out.setdefault("plan_id", f"ctp-{(ctx.get('ticket_id') or 'manual').lower().replace(' ', '-')}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        out.setdefault("title", ctx.get("title") or "Compiled test plan")
        out.setdefault("objective", ctx.get("summary") or ctx.get("description") or out["title"])
        out.setdefault("source_refs", ctx.get("source_refs") or ([{"kind": "ticket", "ref": ctx.get("ticket_id"), "title": ctx.get("title")} ] if ctx.get("ticket_id") else []))
        out.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
        out.setdefault("sut", {})
        if isinstance(out["sut"], dict):
            out["sut"].setdefault("base_url", sut.get("base_url") or sut.get("url") or "")
            out["sut"].setdefault("environment", sut.get("environment") or "test")
            for k in ("browser", "device_profile", "locale", "timezone", "viewport", "auth_mode"):
                if sut.get(k) is not None and k not in out["sut"]:
                    out["sut"][k] = sut[k]
        out.setdefault("constraints", {})
        if isinstance(out["constraints"], dict):
            domains = out["constraints"].get("allowed_domains") or []
            if not domains and out["sut"].get("base_url"):
                from urllib.parse import urlparse
                host = urlparse(out["sut"]["base_url"]).netloc.split(":")[0]
                if host:
                    domains = [host]
            out["constraints"]["allowed_domains"] = domains
            out["constraints"].setdefault("destructive_action_policy", "require_human_approval")
            out["constraints"].setdefault("max_runtime_s", sut.get("max_runtime_s") or 900)
            out["constraints"].setdefault("max_steps", sut.get("max_steps") or 200)
        out.setdefault("quality_gate", {"review_status": "draft", "compiled_by": "gemini", "validation_errors": [], "coverage_notes": []})
        if isinstance(out["quality_gate"], dict):
            out["quality_gate"].setdefault("review_status", "draft")
        return out

    def _save(self, plan: CompiledExecutionTestPlan, *, ctx: Mapping[str, Any], sut: Mapping[str, Any], run_id: Optional[str], artifacts_dir: Union[str, Path], validation: ValidationResult, attempts: int, repaired: bool) -> Path:
        rid = run_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        path = Path(artifacts_dir) / rid / "compiled_test_plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = plan.to_json()
        gen = payload.get("generator") if isinstance(payload.get("generator"), dict) else {}
        gen = dict(gen)
        gen["prompt_version"] = PROMPT_VERSION
        gen["attempts"] = attempts
        gen["repaired"] = repaired
        gen["validation_ok"] = validation.ok
        payload["generator"] = self.redactor.redact_dict(gen)
        payload["quality_gate"] = dict(payload.get("quality_gate") or {})
        payload["quality_gate"]["validation_errors"] = [i.model_dump() for i in validation.issues]
        payload["quality_gate"]["validated_at"] = datetime.now(timezone.utc).isoformat()
        safe_payload, redacted = _redact_any(payload, self.redactor)
        if isinstance(safe_payload, dict):
            safe_payload.setdefault("compiler_metadata", {})
            if isinstance(safe_payload["compiler_metadata"], dict):
                safe_payload["compiler_metadata"]["redacted"] = redacted
        path.write_text(json.dumps(safe_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def _safe_json(self, obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return json.dumps({"unserializable": str(obj)})


class GoogleGenAITextGenerator:
    """Thin adapter over google-genai (new SDK), lazily imported."""

    def __init__(self, *, model: str, api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key

    def generate(self, *, system: str, user: str) -> str:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY/GOOGLE_API_KEY not set; cannot compile test plan with Gemini")
        try:
            from google import genai  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "google-genai is required for live Gemini compilation. Install in the active environment (e.g. apps/cell/.venv) or pass a mocked generator for tests."
            ) from e
        client = genai.Client(api_key=self.api_key)
        prompt = f"SYSTEM:\n{system}\n\nUSER:\n{user}"
        resp = client.models.generate_content(model=self.model, contents=prompt)
        return getattr(resp, "text", None) or str(resp)


def _redact_any(value: Any, redactor: Redactor) -> tuple[Any, bool]:
    # Similar to ContextNormalizer.redact_data; keeps env-ref *names*/placeholders safe.
    import re
    secret_key = re.compile(r"(?i)(^|[_\-])(api[_\-]?key|token|secret|password|passwd|authorization|cookie|session|credential|private[_\-]?key)($|[_\-])")
    ref_container = re.compile(r"(?i)(^|[_\-])(refs?|names?|env|var|vars)($|[_\-])")
    env_ref = re.compile(r"\$\{?([A-Z][A-Z0-9_]{1,})\}?$|^\{\{\s*(env\.[A-Z][A-Z0-9_]*|test_data\.[A-Za-z0-9_.-]+)\s*\}\}$")
    env_name_ref = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")  # secret *name* ref, not a value
    redacted = False
    if isinstance(value, str):
        out = redactor.redact(value)
        return out, out != value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k)
            if secret_key.search(key) and not ref_container.search(key):
                if isinstance(v, dict):
                    nv, r = _redact_any(v, redactor)
                elif isinstance(v, str) and (env_ref.fullmatch(v.strip()) or env_name_ref.fullmatch(v.strip())):
                    nv, r = _redact_any(v, redactor)
                elif v in (None, ""):
                    nv, r = v, False
                else:
                    nv, r = "[REDACTED]", True
            else:
                nv, r = _redact_any(v, redactor)
            out[k] = nv
            redacted = redacted or r
        return out, redacted
    if isinstance(value, list):
        items = []
        for v in value:
            nv, r = _redact_any(v, redactor)
            items.append(nv)
            redacted = redacted or r
        return items, redacted
    return value, redacted
