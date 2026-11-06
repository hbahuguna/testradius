"""Bug report generation from vision/E2B findings (STORY-E2B-005.2).

Backward compatible with legacy `BugFiler.generate/findings/file` usage.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
_PRIORITY_BY_SEVERITY = {"critical": "P0", "high": "P1", "medium": "P2", "low": "P3", "info": "P4"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_actionable_finding(f: Dict[str, Any]) -> bool:
    issue = _norm_text(f.get("issue")).lower()
    if issue in {"", "none", "ok", "pass", "no issue", "analysis_error"}:
        return False
    sev = _norm_text(f.get("severity") or "medium").lower()
    return sev in {"low", "medium", "high", "critical", "info"} and issue not in {"none", "ok"}


@dataclass
class BugEvidence:
    run_id: Optional[str] = None
    run_dir: Optional[str] = None
    manifest_path: Optional[str] = None
    screenshots: List[str] = field(default_factory=list)
    videos: List[str] = field(default_factory=list)
    traces: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    console_logs: List[str] = field(default_factory=list)
    network_logs: List[str] = field(default_factory=list)
    step_results_path: Optional[str] = None
    vision_report_path: Optional[str] = None
    inspection_report_path: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BugReport:
    title: str
    summary: str
    severity: str
    priority: str
    steps_to_reproduce: List[str] = field(default_factory=list)
    expected_result: str = ""
    actual_result: str = ""
    suspected_cause: str = ""
    environment: Dict[str, Any] = field(default_factory=dict)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    evidence: BugEvidence = field(default_factory=BugEvidence)
    labels: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=_utc_now)
    fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["evidence"] = self.evidence.to_dict()
        # legacy aliases
        d["steps"] = list(self.steps_to_reproduce)
        d["evidence_path"] = self.evidence.manifest_path or self.evidence.run_dir or ""
        return d

    def render_markdown(self) -> str:
        lines = [f"# {self.title}", "", "## Summary", self.summary or "(none)", "", "## Severity / Priority", f"- Severity: **{self.severity}**", f"- Priority: **{self.priority}**", ""]
        lines += ["## Steps to Reproduce"]
        if self.steps_to_reproduce:
            for i, s in enumerate(self.steps_to_reproduce, 1):
                lines.append(f"{i}. {s}")
        else:
            lines.append("1. (not provided)")
        lines += ["", "## Expected Result", self.expected_result or "(infer from context)", "", "## Actual Result", self.actual_result or "(see findings/evidence)", ""]
        if self.suspected_cause:
            lines += ["## Suspected Cause", self.suspected_cause, ""]
        if self.findings:
            lines += ["## Findings"]
            for f in self.findings:
                cat = f.get("category") or f.get("type") or "unknown"
                issue = f.get("issue") or ""
                sev = f.get("severity") or ""
                conf = f.get("confidence")
                loc = f.get("location") or ""
                desc = f.get("description") or ""
                sug = f.get("suggestion") or ""
                lines.append(f"- **[{cat}] {issue}** (severity={sev}, confidence={conf}, location={loc or 'n/a'})")
                if desc:
                    lines.append(f"  - Description: {desc}")
                if sug:
                    lines.append(f"  - Suggestion: {sug}")
            lines.append("")
        ev = self.evidence
        lines += ["## Evidence"]
        if ev.run_id:
            lines.append(f"- Run ID: `{ev.run_id}`")
        if ev.run_dir:
            lines.append(f"- Run dir: `{ev.run_dir}`")
        if ev.manifest_path:
            lines.append(f"- Manifest: `{ev.manifest_path}`")
        for label, items in [("Screenshots", ev.screenshots), ("Videos", ev.videos), ("Traces", ev.traces), ("Console logs", ev.console_logs or ev.logs), ("Network logs", ev.network_logs), ("Vision report", [ev.vision_report_path] if ev.vision_report_path else []), ("Inspection report", [ev.inspection_report_path] if ev.inspection_report_path else []), ("Step results", [ev.step_results_path] if ev.step_results_path else [])]:
            items = [i for i in items if i]
            if items:
                lines.append(f"- {label}:")
                for it in items:
                    lines.append(f"  - `{it}`")
        if self.environment:
            lines += ["", "## Environment", "```json", json.dumps(self.environment, indent=2), "```"]
        lines += ["", f"_Generated at {self.generated_at}_"]
        return "\n".join(lines)


class BugReportGenerator:
    """Generates repro-ready bug reports from findings + evidence."""

    def generate(
        self,
        findings: Sequence[Dict[str, Any]] | None = None,
        evidence: Union[str, Path, Dict[str, Any], BugEvidence, None] = None,
        *,
        run_id: Optional[str] = None,
        run_dir: Optional[Union[str, Path]] = None,
        manifest_path: Optional[Union[str, Path]] = None,
        vision_report: Optional[Union[str, Path, Dict[str, Any]]] = None,
        inspection_report: Optional[Union[str, Path, Dict[str, Any]]] = None,
        step_results: Optional[Union[str, Path, Dict[str, Any]]] = None,
        environment: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
        url: Optional[str] = None,
    ) -> BugReport:
        findings_list = [dict(f) for f in (findings or [])]
        loaded = self._load_reports(vision_report=vision_report, inspection_report=inspection_report)
        if not findings_list:
            findings_list = loaded.get("findings", [])
        actionable = [f for f in findings_list if _is_actionable_finding(f)]
        primary = self._select_primary(actionable or findings_list)
        severity = self._infer_severity(actionable or findings_list)
        priority = _PRIORITY_BY_SEVERITY.get(severity, "P2")
        ev = self._build_evidence(evidence=evidence, run_id=run_id, run_dir=run_dir, manifest_path=manifest_path,
                                  vision_report=vision_report, inspection_report=inspection_report, step_results=step_results,
                                  findings=findings_list)
        steps = self._build_steps(step_results=loaded.get("step_results") or step_results, primary=primary, url=url)
        expected, actual = self._build_expected_actual(primary)
        bug_title = title or self._build_title(primary, url=url)
        summary = self._build_summary(primary, actionable, url=url)
        suspected = self._infer_suspected_cause(primary)
        labels = self._labels(primary, severity)
        fp = self._fingerprint(bug_title, primary, url=url)
        return BugReport(
            title=bug_title,
            summary=summary,
            severity=severity,
            priority=priority,
            steps_to_reproduce=steps,
            expected_result=expected,
            actual_result=actual,
            suspected_cause=suspected,
            environment=environment or ({"url": url} if url else {}),
            findings=actionable or findings_list,
            evidence=ev,
            labels=labels,
            fingerprint=fp,
        )

    def _load_reports(self, *, vision_report=None, inspection_report=None) -> Dict[str, Any]:
        out: Dict[str, Any] = {"findings": [], "step_results": None}
        for src in [inspection_report, vision_report]:
            data = self._read_jsonish(src)
            if not data:
                continue
            if isinstance(data.get("deduped"), list):
                out["findings"] = data["deduped"]
            elif isinstance(data.get("findings"), list):
                out["findings"] = data["findings"]
            elif isinstance(data.get("results"), list):  # vision report
                fs: List[Dict[str, Any]] = []
                for r in data["results"]:
                    for f in (r.get("findings") or []):
                        ff = dict(f)
                        ff.setdefault("evidence", {}).setdefault("screenshot", r.get("screenshot_path"))
                        fs.append(ff)
                if fs:
                    out["findings"] = fs
        return out

    def _read_jsonish(self, src) -> Optional[Dict[str, Any]]:
        if src is None:
            return None
        if isinstance(src, dict):
            return src
        try:
            p = Path(src)
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        return None

    def _build_evidence(self, **kwargs) -> BugEvidence:
        ev_arg = kwargs.get("evidence")
        ev = BugEvidence()
        if isinstance(ev_arg, BugEvidence):
            ev = ev_arg
        elif isinstance(ev_arg, dict):
            ev = BugEvidence(**{k: v for k, v in ev_arg.items() if k in BugEvidence.__dataclass_fields__})
        elif isinstance(ev_arg, (str, Path)):
            s = str(ev_arg)
            if s.endswith(".json") and "manifest" in Path(s).name:
                ev.manifest_path = s
            elif s:
                ev.run_dir = s

        for key in ["run_id", "manifest_path", "step_results_path", "vision_report_path", "inspection_report_path"]:
            val = kwargs.get(key)
            if val and not getattr(ev, key):
                setattr(ev, key, str(val))
        if kwargs.get("run_dir") and not ev.run_dir:
            ev.run_dir = str(kwargs["run_dir"])

        # Infer from run_dir
        run_dir = Path(ev.run_dir) if ev.run_dir else (Path(ev.manifest_path).parent if ev.manifest_path else None)
        if run_dir and run_dir.exists():
            ev.run_dir = str(run_dir)
            manifest = run_dir / "manifest.json"
            if manifest.exists() and not ev.manifest_path:
                ev.manifest_path = str(manifest)
            if manifest.exists():
                try:
                    m = json.loads(manifest.read_text(encoding="utf-8"))
                    ev.run_id = ev.run_id or m.get("run_id")
                    for a in m.get("artifacts") or []:
                        path = a.get("path") or a.get("filename")
                        if not path:
                            continue
                        p = Path(path)
                        candidate = str(p if p.is_absolute() else (run_dir / p.name))
                        t = (a.get("type") or "").lower()
                        if t == "screenshot" and candidate not in ev.screenshots:
                            ev.screenshots.append(candidate)
                        elif t == "video" and candidate not in ev.videos:
                            ev.videos.append(candidate)
                        elif t == "trace" and candidate not in ev.traces:
                            ev.traces.append(candidate)
                        elif t in {"console", "log"} and candidate not in ev.console_logs:
                            ev.console_logs.append(candidate)
                        elif t == "network" and candidate not in ev.network_logs:
                            ev.network_logs.append(candidate)
                except Exception:
                    pass
            for name, attr in [("step_results.json", "step_results_path"), ("vision_report.json", "vision_report_path"), ("vision_inspection_report.json", "inspection_report_path")]:
                p = run_dir / name
                if p.exists() and not getattr(ev, attr):
                    setattr(ev, attr, str(p))

        # Screenshot hints from findings
        for f in (kwargs.get("findings") or []):
            sp = ((f.get("evidence") or {}).get("screenshot") or f.get("screenshot_path"))
            if sp and str(sp) not in ev.screenshots:
                ev.screenshots.append(str(sp))
        return ev

    def _select_primary(self, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not findings:
            return {"category": "visual", "issue": "Visual issue detected", "severity": "medium"}
        return max(findings, key=lambda f: (_SEVERITY_RANK.get(_norm_text(f.get("severity")).lower(), 0), float(f.get("confidence") or 0)))

    def _infer_severity(self, findings: List[Dict[str, Any]]) -> str:
        if not findings:
            return "medium"
        rank = max(_SEVERITY_RANK.get(_norm_text(f.get("severity")).lower(), 1) for f in findings)
        for name, val in _SEVERITY_RANK.items():
            if val == rank:
                return name
        return "medium"

    def _build_title(self, primary: Dict[str, Any], url: Optional[str] = None) -> str:
        cat = _norm_text(primary.get("category") or primary.get("type") or "Visual").capitalize()
        issue = _norm_text(primary.get("issue") or "issue detected")
        loc = _norm_text(primary.get("location"))
        base = f"[{cat}] {issue}"
        if loc:
            base += f" in {loc}"
        if url:
            try:
                host = re.sub(r"^https?://", "", url).split("/")[0]
                if host:
                    base += f" ({host})"
            except Exception:
                pass
        return base[:140]

    def _build_summary(self, primary: Dict[str, Any], actionable: List[Dict[str, Any]], url: Optional[str] = None) -> str:
        desc = _norm_text(primary.get("description") or primary.get("issue") or "Visual QA finding detected.")
        loc = _norm_text(primary.get("location"))
        where = f" at {loc}" if loc else ""
        target = f" on {url}" if url else ""
        extra = f" ({len(actionable)} actionable findings)" if len(actionable) > 1 else ""
        return f"{desc}{where}{target}.{extra}"

    def _build_steps(self, step_results=None, primary=None, url=None) -> List[str]:
        data = self._read_jsonish(step_results)
        steps: List[str] = []
        if url:
            steps.append(f"Navigate to {url}.")
        # Accept both {"steps": [...]} and bare [...] step_results shapes.
        raw_steps = data.get("steps") if isinstance(data, dict) else (data if isinstance(data, list) else None)
        if isinstance(raw_steps, list):
            for s in raw_steps:
                if not isinstance(s, dict):
                    continue
                intent = _norm_text(s.get("intent") or s.get("title") or s.get("action_type"))
                status = _norm_text(s.get("status"))
                if intent:
                    suffix = f" (observed: {status})" if status else ""
                    steps.append(f"{intent}{suffix}.")
        if not steps:
            steps = [f"Navigate to {url or 'the affected page'}.", "Execute the test flow / reach the affected UI state.", "Observe the reported visual issue."]
        cat = _norm_text((primary or {}).get("category") or "visual")
        steps.append(f"Inspect for {cat} issue: {_norm_text((primary or {}).get('issue') or 'reported issue')}.")
        return steps[:12]

    def _build_expected_actual(self, primary: Dict[str, Any]) -> Tuple[str, str]:
        issue = _norm_text(primary.get("issue") or "visual issue")
        cat = _norm_text(primary.get("category") or primary.get("type") or "visual")
        suggestion = _norm_text(primary.get("suggestion"))
        expected = suggestion or f"UI should render without {cat} issues ({issue})."
        actual = _norm_text(primary.get("description") or issue)
        loc = _norm_text(primary.get("location"))
        if loc:
            actual += f" Location: {loc}."
        return expected, actual

    def _infer_suspected_cause(self, primary: Dict[str, Any]) -> str:
        cat = _norm_text(primary.get("category") or primary.get("type")).lower()
        mapping = {
            "layout": "CSS layout/alignment, spacing, grid/flex rules, or responsive breakpoint handling",
            "contrast": "Color tokens/theme contrast or inaccessible text/background pairing",
            "clipping": "Overflow/height constraints, container clipping, or text wrapping/truncation",
            "overlap": "Positioning/z-index/stacking, negative margins, or responsive wrapping collisions",
            "responsive": "Breakpoint/layout adaptation, fixed widths, or viewport-dependent styling",
        }
        return mapping.get(cat, "UI rendering/CSS or component state")

    def _labels(self, primary: Dict[str, Any], severity: str) -> List[str]:
        cat = _norm_text(primary.get("category") or primary.get("type")).lower() or "visual"
        labels = ["bug", "visual-qa", f"severity:{severity}", f"category:{cat}"]
        return labels

    def _fingerprint(self, title: str, primary: Dict[str, Any], url: Optional[str] = None) -> str:
        raw = "|".join([
            _norm_text(title).lower(),
            _norm_text(primary.get("category") or primary.get("type")).lower(),
            _norm_text(primary.get("issue")).lower(),
            _norm_text(primary.get("location")).lower(),
            _norm_text(url).lower(),
        ])
        return re.sub(r"[^a-z0-9|]+", "-", raw).strip("-")


class BugFiler:
    """Backward-compatible bug filer + richer report/connector-aware filing."""

    def __init__(self, existing: Optional[list] = None, connector: Any = None):
        self.existing = existing or []
        self.connector = connector
        self.generator = BugReportGenerator()

    def dedup(self, title: str) -> bool:
        t = _norm_text(title).lower()
        for b in self.existing:
            bt = _norm_text((b or {}).get("title")).lower()
            if bt == t:
                return True
            # fuzzy fallback: same normalized core
            if bt and t and (bt in t or t in bt):
                return True
        return False

    def dedup_report(self, report: BugReport) -> bool:
        if self.dedup(report.title):
            return True
        for b in self.existing:
            if _norm_text((b or {}).get("fingerprint")).lower() == _norm_text(report.fingerprint).lower() and report.fingerprint:
                return True
        return False

    def generate(self, findings: list, evidence: str):
        """Legacy-compatible: returns a plain dict ticket."""
        report = self.generator.generate(findings=findings or [], evidence=evidence)
        # preserve legacy shape keys used historically
        d = report.to_dict()
        d.setdefault("suspected_cause", report.suspected_cause or "CSS/layout")
        d["evidence"] = evidence  # legacy: raw evidence arg (string/path)
        if not d.get("steps"):
            d["steps"] = ["Navigate to page", "Observe issue"]
        return d

    def generate_report(self, *args, **kwargs) -> BugReport:
        return self.generator.generate(*args, **kwargs)

    def file(self, findings: list, evidence: str, approved: bool = False, **kwargs):
        if not approved:
            raise PermissionError("Approval required before filing")
        report = self.generator.generate(findings=findings or [], evidence=evidence, **kwargs)
        if self.dedup_report(report):
            return {"status": "duplicate", "ticket": report.to_dict(), "report": report.to_dict()}
        if self.connector is not None:
            result = self.connector.file(report)
            status = (result or {}).get("status", "filed")
            return {"status": status, **(result or {}), "ticket": report.to_dict(), "report": report.to_dict()}
        # legacy default behavior
        return {"status": "filed", "ticket": report.to_dict(), "report": report.to_dict(), "url": "https://github.com/org/repo/issues/123"}
