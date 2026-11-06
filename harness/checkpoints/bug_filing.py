"""Checkpoint-gated bug filing workflow (STORY-E2B-005.1/005.3).

Uses existing approval state/audit primitives, blocks filing until approved,
presents findings with screenshots, and supports connector-based filing with dedup.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .approval import ApprovalRegistry, ApprovalState, AuditEntry
from ..bugs.generator import BugFiler, BugReport, BugReportGenerator
from ..connectors.base import BaseIssueConnector


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def render_review_package(report: BugReport) -> str:
    lines = [
        "=" * 72,
        "BUG FILING REVIEW (human approval required)",
        "=" * 72,
        f"Title:    {report.title}",
        f"Severity: {report.severity} | Priority: {report.priority}",
        f"Summary:  {report.summary}",
        "",
        "Findings:",
    ]
    for f in report.findings or []:
        cat = f.get("category") or f.get("type")
        issue = f.get("issue")
        sev = f.get("severity")
        conf = f.get("confidence")
        loc = f.get("location") or "n/a"
        lines.append(f"  - [{cat}] {issue} (severity={sev}, confidence={conf}, location={loc})")
        desc = f.get("description")
        if desc:
            lines.append(f"    {desc}")
    ev = report.evidence
    lines += ["", "Screenshots / Evidence:"]
    for s in ev.screenshots:
        exists = Path(s).exists()
        lines.append(f"  - screenshot: {s} {'[exists]' if exists else '[missing locally]'}")
    for v in ev.videos:
        lines.append(f"  - video:      {v}")
    for t in ev.traces:
        lines.append(f"  - trace:      {t}")
    for c in (ev.console_logs or ev.logs):
        lines.append(f"  - console:    {c}")
    for n in ev.network_logs:
        lines.append(f"  - network:    {n}")
    if ev.manifest_path:
        lines.append(f"  - manifest:   {ev.manifest_path}")
    if ev.inspection_report_path:
        lines.append(f"  - inspection: {ev.inspection_report_path}")
    lines += ["", "Steps to Reproduce:"]
    for i, s in enumerate(report.steps_to_reproduce, 1):
        lines.append(f"  {i}. {s}")
    lines += ["", "Filing is BLOCKED until an authorized reviewer approves this report.", "=" * 72]
    return "\n".join(lines)


class BugFilingWorkflow:
    """Prepare bug review, require approval, then file/dedup via connector."""

    def __init__(
        self,
        registry: Optional[ApprovalRegistry] = None,
        generator: Optional[BugReportGenerator] = None,
        connector: Optional[BaseIssueConnector] = None,
    ):
        self.registry = registry or ApprovalRegistry()
        self.generator = generator or BugReportGenerator()
        self.connector = connector

    def prepare_review(
        self,
        *,
        approval_id: str,
        findings: Optional[Sequence[Dict[str, Any]]] = None,
        run_dir: Optional[Union[str, Path]] = None,
        manifest_path: Optional[Union[str, Path]] = None,
        vision_report: Optional[Union[str, Path, Dict[str, Any]]] = None,
        inspection_report: Optional[Union[str, Path, Dict[str, Any]]] = None,
        step_results: Optional[Union[str, Path, Dict[str, Any]]] = None,
        environment: Optional[Dict[str, Any]] = None,
        url: Optional[str] = None,
        title: Optional[str] = None,
        save: bool = True,
    ) -> Dict[str, Any]:
        report = self.generator.generate(
            findings=findings,
            run_dir=run_dir,
            manifest_path=manifest_path,
            vision_report=vision_report,
            inspection_report=inspection_report,
            step_results=step_results,
            environment=environment,
            url=url,
            title=title,
        )
        state = self.registry.get(approval_id)
        state.audit_log.append(
            AuditEntry(ts=_utc_now(), action="REVIEW_PREPARED", actor="system", run_id=approval_id, detail=report.title)
        )
        review_text = render_review_package(report)
        package: Dict[str, Any] = {
            "approval_id": approval_id,
            "approved": state.approved,
            "report": report.to_dict(),
            "markdown": report.render_markdown(),
            "review_text": review_text,
        }

        target_dir = Path(run_dir) if run_dir else (Path(manifest_path).parent if manifest_path else None)
        if save and target_dir:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "bug_review_package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
            (target_dir / "bug_report.md").write_text(report.render_markdown(), encoding="utf-8")
            state.export_audit(target_dir / "bug_filing_audit.json")
            package["saved"] = {
                "review_package": str(target_dir / "bug_review_package.json"),
                "bug_report": str(target_dir / "bug_report.md"),
                "audit_log": str(target_dir / "bug_filing_audit.json"),
            }
        return package

    def approve(self, approval_id: str, actor: str, detail: str = "") -> ApprovalState:
        state = self.registry.get(approval_id)
        state.approve(actor=actor, detail=detail)
        return state

    def file_after_approval(
        self,
        *,
        approval_id: str,
        review_package: Optional[Dict[str, Any]] = None,
        connector: Optional[BaseIssueConnector] = None,
        existing_issues: Optional[List[Dict[str, Any]]] = None,
        actor: str = "system",
        **prepare_kwargs: Any,
    ) -> Dict[str, Any]:
        state = self.registry.get(approval_id)
        try:
            state.require_approval()
        except PermissionError:
            state.audit_log.append(AuditEntry(ts=_utc_now(), action="FILE_BLOCKED", actor=actor, run_id=approval_id, detail="approval required"))
            raise

        if review_package is None:
            review_package = self.prepare_review(approval_id=approval_id, save=False, **prepare_kwargs)
        report = BugReportGenerator().generate(**{k: v for k, v in prepare_kwargs.items() if k in {"findings", "run_dir", "manifest_path", "vision_report", "inspection_report", "step_results", "environment", "url", "title"}}) if not review_package.get("report") else None
        if report is None:
            # reconstruct minimal report from saved dict through generator inputs where possible
            report = self.generator.generate(
                findings=(review_package.get("report") or {}).get("findings"),
                run_dir=prepare_kwargs.get("run_dir"),
                manifest_path=prepare_kwargs.get("manifest_path"),
                vision_report=prepare_kwargs.get("vision_report"),
                inspection_report=prepare_kwargs.get("inspection_report"),
                step_results=prepare_kwargs.get("step_results"),
                environment=(review_package.get("report") or {}).get("environment"),
                url=prepare_kwargs.get("url"),
                title=(review_package.get("report") or {}).get("title"),
            )

        conn = connector or self.connector
        if conn is None:
            raise ValueError("No connector configured for filing")

        if conn.is_duplicate(report, existing=existing_issues):
            state.audit_log.append(AuditEntry(ts=_utc_now(), action="FILE_DUPLICATE", actor=actor, run_id=approval_id, detail=report.title))
            return {"status": "duplicate", "approval_id": approval_id, "approved": True, "title": report.title, "report": report.to_dict()}

        result = conn.file(report, existing_issues=existing_issues)
        state.audit_log.append(AuditEntry(ts=_utc_now(), action=f"FILE_{str(result.get('status','unknown')).upper()}", actor=actor, run_id=approval_id, detail=str(result.get("url") or result.get("error") or report.title)))
        result.update({"approval_id": approval_id, "approved": True, "report": report.to_dict()})
        return result
