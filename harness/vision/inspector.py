"""Multi-round vision self-inspection (STORY-E2B-004.2/004.3)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .client import VisionClient

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
_ROUND_PURPOSES = {
    1: "initial_inspection",
    2: "verify_fixes_and_check_additional_areas",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(finding: Dict[str, Any]) -> str:
    category = str(finding.get("category") or finding.get("type") or "").lower().strip()
    issue = str(finding.get("issue") or "").lower().strip()
    location = str(finding.get("location") or "").lower().strip()
    return f"{category}|{issue}|{location}"


def _is_actionable(finding: Dict[str, Any]) -> bool:
    issue = str(finding.get("issue") or "").lower().strip()
    if issue in {"none", "ok", "pass", "no issue", ""}:
        return False
    sev = str(finding.get("severity") or "info").lower()
    return sev in {"low", "medium", "high", "critical"}


class SelfInspector:
    def __init__(self, rounds: int = 2, *, client: Optional[VisionClient] = None, model: str = "mock"):
        self.rounds = max(1, int(rounds))
        self.client = client or VisionClient(model=model)

    def _round_purpose(self, round_num: int) -> str:
        return _ROUND_PURPOSES.get(round_num, f"additional_inspection_round_{round_num}")

    def inspect(self, screenshot: str, **context: Any) -> Dict[str, Any]:
        log: List[Dict[str, Any]] = []
        analyses: List[Dict[str, Any]] = []
        findings: List[Dict[str, Any]] = []
        prior_actionable: List[str] = []

        for r in range(1, self.rounds + 1):
            started_at = _utc_now()
            purpose = self._round_purpose(r)
            round_context = dict(context)
            extra = str(round_context.get("extra_context") or "")
            round_note = f"Inspection round {r}/{self.rounds}: {purpose}."
            if r > 1 and prior_actionable:
                round_note += " Verify previously noted issues and check additional areas: " + "; ".join(prior_actionable[:5])
            round_context["extra_context"] = (extra + "\n" + round_note).strip()

            result = self.client.analyze(screenshot, **round_context)
            fdicts = [f.to_dict() for f in result.findings]
            analyses.append(result.to_dict())
            actionable = [f"{f.get('category') or f.get('type')}: {f.get('issue')}" for f in fdicts if _is_actionable(f)]
            prior_actionable = actionable or prior_actionable
            log.append(
                {
                    "round": r,
                    "purpose": purpose,
                    "started_at": started_at,
                    "completed_at": _utc_now(),
                    "screenshot": screenshot,
                    "findings": fdicts,
                    "actionable_findings": actionable,
                    "summary": result.summary,
                    "model": result.model,
                    "provider": result.provider,
                    "error": result.error,
                }
            )
            findings.extend(fdicts)

        deduped = self._dedupe(findings)
        report = {
            "schema_version": "1.0",
            "generated_at": _utc_now(),
            "screenshot": screenshot,
            "rounds": log,
            "deduped": deduped,
            "analyses": analyses,
            "summary": {
                "round_count": self.rounds,
                "total_findings": len(findings),
                "deduped_findings": len(deduped),
                "actionable_deduped_findings": sum(1 for f in deduped if _is_actionable(f)),
                "models": sorted({a.get("model", "") for a in analyses if a.get("model")}),
                "purposes": [self._round_purpose(r) for r in range(1, self.rounds + 1)],
            },
        }
        return report

    def inspect_and_save(self, screenshot: str, report_path: Union[str, Path], **context: Any) -> Dict[str, Any]:
        report = self.inspect(screenshot, **context)
        self.save_report(report, report_path)
        return report

    @staticmethod
    def save_report(report: Dict[str, Any], path: Union[str, Path]) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return p

    def _dedupe(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best: Dict[str, Dict[str, Any]] = {}
        for f in findings:
            fp = _fingerprint(f)
            prev = best.get(fp)
            if prev is None:
                best[fp] = f
                continue
            prev_score = (_SEVERITY_RANK.get(str(prev.get("severity", "info")).lower(), 0), float(prev.get("confidence") or 0))
            cur_score = (_SEVERITY_RANK.get(str(f.get("severity", "info")).lower(), 0), float(f.get("confidence") or 0))
            if cur_score > prev_score:
                best[fp] = f
        return list(best.values())

