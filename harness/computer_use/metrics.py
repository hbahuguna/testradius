"""Run metrics + reporting for computer-use runs (008.7.2)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _parse_ts(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def compute_run_metrics(summary: Any) -> Dict[str, Any]:
    """Derive metrics from a runner RunSummary (or its dict form)."""
    if isinstance(summary, dict):
        steps = summary.get("steps") or []
        total = summary.get("total_steps") or len(steps)
        passed = summary.get("passed", sum(1 for s in steps if s.get("status") == "pass"))
        blocked = summary.get("blocked", sum(1 for s in steps if s.get("status") == "blocked"))
        infra = summary.get("infra_errors", sum(1 for s in steps if s.get("status") == "infra_error"))
        failed = summary.get("failed", sum(1 for s in steps if s.get("status") in {"fail_product", "fail_agent"}))
        fail_product = sum(1 for s in steps if (s.get("status") == "fail_product" if isinstance(s, dict) else getattr(s, "status", "") == "fail_product"))
        fail_agent = sum(1 for s in steps if (s.get("status") == "fail_agent" if isinstance(s, dict) else getattr(s, "status", "") == "fail_agent"))
        retries = sum(max(0, int((s.get("attempts", 1) if isinstance(s, dict) else getattr(s, "attempts", 1)) or 1) - 1) for s in steps)
        started = summary.get("started_at")
        ended = summary.get("ended_at")
        token_cost = summary.get("token_cost_estimate")
        artifacts = summary.get("artifacts") or []
    else:
        steps = getattr(summary, "steps", []) or []
        total = getattr(summary, "total_steps", len(steps))
        passed = getattr(summary, "passed", sum(1 for s in steps if s.status == "pass"))
        blocked = getattr(summary, "blocked", sum(1 for s in steps if s.status == "blocked"))
        infra = getattr(summary, "infra_errors", sum(1 for s in steps if s.status == "infra_error"))
        failed = getattr(summary, "failed", sum(1 for s in steps if s.status in {"fail_product", "fail_agent"}))
        fail_product = sum(1 for s in steps if s.status == "fail_product")
        fail_agent = sum(1 for s in steps if s.status == "fail_agent")
        retries = sum(max(0, int(getattr(s, "attempts", 1) or 1) - 1) for s in steps)
        started = getattr(summary, "started_at", None)
        ended = getattr(summary, "ended_at", None)
        token_cost = getattr(summary, "metadata", {}).get("token_cost_estimate") if hasattr(summary, "metadata") else None
        artifacts = getattr(summary, "artifacts", []) or []
    s_ts, e_ts = _parse_ts(started), _parse_ts(ended)
    runtime_s = round((e_ts - s_ts).total_seconds(), 2) if s_ts and e_ts else None
    denom = max(1, total)
    return {
        "total_steps": total,
        "pass": passed,
        "fail_product": fail_product,
        "fail_agent": fail_agent,
        "blocked": blocked,
        "infra_error": infra,
        "step_pass_rate": round(passed / denom, 4),
        "agent_vs_product_failure_rate": round(fail_agent / max(1, fail_agent + fail_product), 4),
        "retries": retries,
        "runtime_s": runtime_s,
        "token_cost_estimate": token_cost,
        "artifact_count": len(artifacts),
    }


def aggregate_metrics(run_summaries: Iterable[Any]) -> Dict[str, Any]:
    """Aggregate multiple run metrics (for evals/reports)."""
    metrics = [compute_run_metrics(s) for s in run_summaries]
    if not metrics:
        return {"runs": 0}
    total_steps = sum(m["total_steps"] for m in metrics)
    total_pass = sum(m["pass"] for m in metrics)
    validation_pass = sum(1 for s in run_summaries if (s.get("validation", {}).get("ok", True) if isinstance(s, dict) else True))
    return {
        "runs": len(metrics),
        "total_steps": total_steps,
        "overall_pass_rate": round(total_pass / max(1, total_steps), 4),
        "plan_validation_pass_rate": round(validation_pass / len(metrics), 4),
        "agent_vs_product_failure_rate": round(sum(m["fail_agent"] for m in metrics) / max(1, sum(m["fail_agent"] + m["fail_product"] for m in metrics)), 4),
        "total_retries": sum(m["retries"] for m in metrics),
        "avg_runtime_s": round(sum(m["runtime_s"] or 0 for m in metrics) / len(metrics), 2),
        "runs_detail": metrics,
    }
