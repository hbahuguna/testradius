"""Compiled test plan to Playwright converter (optional adapter).

Converts compiled test plan steps into Playwright-automatable steps where
explicit selectors/hints are present. Steps that cannot be safely automated
are marked as `computer_use_only` with reasons. Produces a conversion report
with coverage metrics and a runnable script for supported steps.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .generator import PlaywrightScriptGenerator, SCRIPT_TEMPLATE


# Actions that can be automated when sufficient target/input info exists.
AUTOMATABLE_ACTIONS = {
    "navigate",
    "click",
    "double_click",
    "type",
    "fill",
    "select",
    "scroll",
    "keypress",
    "wait",
    "assert",
}

# Actions that require an explicit, safe locator hint to automate
# (navigating/waiting/scrolling/keypressing/asserting may not need element targets
# in the same way; click/type/select do).
LOCATOR_REQUIRED_ACTIONS = {"click", "double_click", "type", "fill", "select"}


@dataclass
class StepConversion:
    step_id: str
    case_id: str
    ordinal: Optional[int]
    action_type: str
    intent: str
    classification: str  # "automated" | "computer_use_only"
    reasons: List[str] = field(default_factory=list)
    used_hints: List[str] = field(default_factory=list)


@dataclass
class ConversionReport:
    plan_id: str
    total_steps: int
    automated_steps: int
    computer_use_only_steps: int
    coverage_pct: float
    by_action: Dict[str, Dict[str, int]] = field(default_factory=dict)
    steps: List[StepConversion] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "total_steps": self.total_steps,
            "automated_steps": self.automated_steps,
            "computer_use_only_steps": self.computer_use_only_steps,
            "coverage_pct": self.coverage_pct,
            "by_action": self.by_action,
            "steps": [
                {
                    "step_id": s.step_id,
                    "case_id": s.case_id,
                    "ordinal": s.ordinal,
                    "action_type": s.action_type,
                    "intent": s.intent,
                    "classification": s.classification,
                    "reasons": s.reasons,
                    "used_hints": s.used_hints,
                }
                for s in self.steps
            ],
        }


@dataclass
class ConversionResult:
    report: ConversionReport
    script: str
    converted_plan: Dict[str, Any]

    @property
    def coverage_pct(self) -> float:
        return self.report.coverage_pct


class PlaywrightPlanConverter:
    """Converts compiled test plans to Playwright scripts with coverage reporting.

    Unlike the best-effort generator, this converter is conservative: it marks
    a step as automatable only when explicit selectors/hints (or sufficient
    deterministic inputs like URL for navigate) are present. Otherwise the step
    is marked `computer_use_only`.
    """

    def __init__(self, default_timeout_ms: int = 30000):
        self.default_timeout_ms = default_timeout_ms
        self._generator = PlaywrightScriptGenerator(default_timeout_ms=default_timeout_ms)

    def convert(
        self,
        plan: Union[Dict[str, Any], str, Path],
        target_url: Optional[str] = None,
        artifacts_dir: str = "/home/user/artifacts",
        record_trace: bool = True,
        record_video: bool = False,
    ) -> ConversionResult:
        plan_dict = self._parse_plan(plan)
        plan_id = str(plan_dict.get("plan_id", "compiled_plan"))
        cases = plan_dict.get("cases", []) or []

        step_conversions: List[StepConversion] = []
        converted_cases: List[Dict[str, Any]] = []

        for case in cases:
            case_id = str(case.get("case_id", "TC"))
            converted_steps: List[Dict[str, Any]] = []
            for step in case.get("steps", []) or []:
                conv = self._classify_step(step, case_id)
                step_conversions.append(conv)
                converted_step = dict(step)
                converted_step["automation"] = {
                    "classification": conv.classification,
                    "reasons": conv.reasons,
                    "used_hints": conv.used_hints,
                }
                if conv.classification == "computer_use_only":
                    # Preserve original action for reference; runner script will record skip.
                    converted_step["_original_action_type"] = converted_step.get("action_type")
                    converted_step["action_type"] = "computer_use_only"
                converted_steps.append(converted_step)
            converted_case = dict(case)
            converted_case["steps"] = converted_steps
            converted_cases.append(converted_case)

        converted_plan = dict(plan_dict)
        converted_plan["cases"] = converted_cases

        report = self._build_report(plan_id, step_conversions)
        script = self._generate_script_with_coverage(
            converted_plan=converted_plan,
            report=report,
            target_url=target_url,
            artifacts_dir=artifacts_dir,
            record_trace=record_trace,
            record_video=record_video,
        )
        return ConversionResult(report=report, script=script, converted_plan=converted_plan)

    def _classify_step(self, step: Dict[str, Any], case_id: str) -> StepConversion:
        step_id = str(step.get("step_id", "step"))
        ordinal = step.get("ordinal")
        action_type = str(step.get("action_type", "assert")).lower().strip()
        intent = str(step.get("intent", ""))
        target = step.get("target") or {}
        hints = target.get("hints") if isinstance(target, dict) else {}
        hints = hints if isinstance(hints, dict) else {}
        input_data = step.get("input") or {}
        if not isinstance(input_data, dict):
            input_data = {}

        reasons: List[str] = []
        used_hints: List[str] = []

        if action_type not in AUTOMATABLE_ACTIONS:
            return StepConversion(
                step_id=step_id,
                case_id=case_id,
                ordinal=ordinal,
                action_type=action_type,
                intent=intent,
                classification="computer_use_only",
                reasons=[f"Unsupported action_type '{action_type}' for deterministic Playwright automation"],
            )

        # Check for explicit deterministic hints/inputs
        if hints.get("selector"):
            used_hints.append("selector")
        if hints.get("test_id") or hints.get("testid") or hints.get("data_testid"):
            used_hints.append("test_id")
        if hints.get("role") and (hints.get("visible_text") or hints.get("name")):
            used_hints.append("role+name")
        if hints.get("placeholder"):
            used_hints.append("placeholder")
        if hints.get("label") or hints.get("aria_label"):
            used_hints.append("label")

        if action_type == "navigate":
            url = input_data.get("url") or (hints.get("url") if isinstance(hints, dict) else None)
            if url or True:
                # navigate is automatable even with base_url fallback, but note if explicit
                if url:
                    used_hints.append("input.url")
                else:
                    reasons.append("Using SUT base_url fallback for navigation")
                return StepConversion(
                    step_id=step_id,
                    case_id=case_id,
                    ordinal=ordinal,
                    action_type=action_type,
                    intent=intent,
                    classification="automated",
                    reasons=reasons,
                    used_hints=used_hints or ["base_url_fallback"],
                )

        if action_type in ("wait", "scroll", "keypress"):
            # Automatable from input parameters
            if action_type == "keypress" and not input_data.get("key"):
                reasons.append("keypress missing input.key")
                return self._computer_use_only(step_id, case_id, ordinal, action_type, intent, reasons)
            used_hints.append("input_params")
            return StepConversion(
                step_id=step_id,
                case_id=case_id,
                ordinal=ordinal,
                action_type=action_type,
                intent=intent,
                classification="automated",
                reasons=reasons,
                used_hints=used_hints,
            )

        if action_type == "assert":
            criteria = step.get("success_criteria") or []
            if isinstance(criteria, list) and any(str(c).strip() for c in criteria):
                used_hints.append("success_criteria")
                # Still automatable as a best-effort assertion in generated runner;
                # complex visual assertions may be partial, but criteria are explicit.
                return StepConversion(
                    step_id=step_id,
                    case_id=case_id,
                    ordinal=ordinal,
                    action_type=action_type,
                    intent=intent,
                    classification="automated",
                    reasons=reasons,
                    used_hints=used_hints,
                )
            reasons.append("assert step missing explicit success_criteria")
            return self._computer_use_only(step_id, case_id, ordinal, action_type, intent, reasons)

        # Locator-required actions: need explicit hints
        if action_type in LOCATOR_REQUIRED_ACTIONS:
            if not used_hints:
                reasons.append(
                    f"{action_type} requires explicit selector/hints (selector, test_id, role+name, placeholder, or label) "
                    "for safe deterministic automation"
                )
                return self._computer_use_only(step_id, case_id, ordinal, action_type, intent, reasons)
            if action_type in ("type", "fill") and not (input_data.get("text") or input_data.get("value")):
                reasons.append("type/fill action missing input.text or input.value")
                return self._computer_use_only(step_id, case_id, ordinal, action_type, intent, reasons)
            if action_type == "select" and not (input_data.get("value") or input_data.get("label")):
                reasons.append("select action missing input.value or input.label")
                return self._computer_use_only(step_id, case_id, ordinal, action_type, intent, reasons)
            return StepConversion(
                step_id=step_id,
                case_id=case_id,
                ordinal=ordinal,
                action_type=action_type,
                intent=intent,
                classification="automated",
                reasons=reasons,
                used_hints=used_hints,
            )

        # Default: if we have explicit hints, allow; else computer_use_only
        if used_hints:
            return StepConversion(
                step_id=step_id,
                case_id=case_id,
                ordinal=ordinal,
                action_type=action_type,
                intent=intent,
                classification="automated",
                reasons=reasons,
                used_hints=used_hints,
            )
        reasons.append("No explicit deterministic selectors/hints available")
        return self._computer_use_only(step_id, case_id, ordinal, action_type, intent, reasons)

    def _computer_use_only(
        self, step_id: str, case_id: str, ordinal: Optional[int], action_type: str, intent: str, reasons: List[str]
    ) -> StepConversion:
        return StepConversion(
            step_id=step_id,
            case_id=case_id,
            ordinal=ordinal,
            action_type=action_type,
            intent=intent,
            classification="computer_use_only",
            reasons=reasons or ["Not safely automatable with available hints"],
        )

    def _build_report(self, plan_id: str, steps: List[StepConversion]) -> ConversionReport:
        total = len(steps)
        automated = sum(1 for s in steps if s.classification == "automated")
        computer_use_only = total - automated
        coverage = round((automated / total) * 100.0, 2) if total else 0.0

        by_action: Dict[str, Dict[str, int]] = {}
        for s in steps:
            entry = by_action.setdefault(s.action_type, {"automated": 0, "computer_use_only": 0, "total": 0})
            entry[s.classification] += 1
            entry["total"] += 1

        return ConversionReport(
            plan_id=plan_id,
            total_steps=total,
            automated_steps=automated,
            computer_use_only_steps=computer_use_only,
            coverage_pct=coverage,
            by_action=by_action,
            steps=steps,
        )

    def _generate_script_with_coverage(
        self,
        converted_plan: Dict[str, Any],
        report: ConversionReport,
        target_url: Optional[str],
        artifacts_dir: str,
        record_trace: bool,
        record_video: bool,
    ) -> str:
        # Generate base runnable script using the generator infrastructure.
        # The generator will handle navigate/click/type/etc. For `computer_use_only`
        # action_type we inject handling by temporarily mapping in a wrapper script.
        # Easiest: generate from converted plan and post-process by injecting a handler.
        script = self._generator.generate(
            plan=converted_plan,
            target_url=target_url,
            artifacts_dir=artifacts_dir,
            record_trace=record_trace,
            record_video=record_video,
        )
        report_json = json.dumps(report.to_dict(), indent=2)
        injection = f'''

CONVERSION_REPORT = {report_json}

'''
        # Insert conversion report constant after DEFAULT_TIMEOUT_MS
        marker = "DEFAULT_TIMEOUT_MS = "
        if marker in script:
            line_end = script.index("\n", script.index(marker))
            script = script[: line_end + 1] + injection + script[line_end + 1 :]

        # Inject computer_use_only handling into run_step before evidence capture failure handling
        cuo_handler = r'''
        elif action_type == "computer_use_only":
            status = "COMPUTER_USE_ONLY"
            original = step.get("_original_action_type", "unknown")
            error_msg = f"Step marked computer_use_only (original action: {original}); requires Gemini computer-use runner"
            evidence_cfg = step.get("evidence", {})
            if evidence_cfg.get("screenshot_after", True):
                try:
                    screenshot_file = str(artifacts_path / f"{step_id}_cuo.png")
                    await page.screenshot(path=screenshot_file, full_page=False)
                except Exception:
                    pass
'''
        # Insert before the "# Check success criteria if present on any action" block
        success_check_marker = "        # Check success criteria if present on any action"
        if success_check_marker in script and cuo_handler.strip() not in script:
            script = script.replace(success_check_marker, cuo_handler + "\n" + success_check_marker)

        # Add conversion report to summary and print coverage
        summary_patch_old = '''    summary = {
        "plan_id": PLAN_ID,
        "status": overall_status,
        "total_steps": len(results),
        "passed_steps": sum(1 for s in results if s["status"] == "PASSED"),
        "failed_steps": sum(1 for s in results if s["status"] == "FAILED"),
        "steps": results,
    }'''
        summary_patch_new = '''    cuo_steps = sum(1 for s in results if s["status"] == "COMPUTER_USE_ONLY")
    automated_steps = sum(1 for s in results if s["status"] != "COMPUTER_USE_ONLY")
    coverage_pct = round((automated_steps / len(results)) * 100.0, 2) if results else 0.0
    summary = {
        "plan_id": PLAN_ID,
        "status": overall_status,
        "total_steps": len(results),
        "passed_steps": sum(1 for s in results if s["status"] == "PASSED"),
        "failed_steps": sum(1 for s in results if s["status"] == "FAILED"),
        "computer_use_only_steps": cuo_steps,
        "automated_steps_executed": automated_steps,
        "automation_coverage_pct": coverage_pct,
        "conversion_report": CONVERSION_REPORT,
        "steps": results,
    }'''
        if summary_patch_old in script:
            script = script.replace(summary_patch_old, summary_patch_new)

        print_patch_old = '    print(f"PASSED={summary[\'passed_steps\']}/{summary[\'total_steps\']}")'
        print_patch_new = '''    print(f"PASSED={summary['passed_steps']}/{summary['total_steps']}")
    print(f"AUTOMATION_COVERAGE_PCT={summary['automation_coverage_pct']}")
    print(f"COMPUTER_USE_ONLY={summary['computer_use_only_steps']}")'''
        if print_patch_old in script:
            script = script.replace(print_patch_old, print_patch_new)

        return script

    def _parse_plan(self, plan: Union[Dict[str, Any], str, Path]) -> Dict[str, Any]:
        if isinstance(plan, (str, Path)) and (isinstance(plan, Path) or str(plan).endswith(".json")):
            p = Path(plan)
            if p.exists() and p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
            return json.loads(str(plan))
        if isinstance(plan, str):
            return json.loads(plan)
        if isinstance(plan, dict):
            return plan
        raise TypeError(f"Unsupported plan type: {type(plan).__name__}")
