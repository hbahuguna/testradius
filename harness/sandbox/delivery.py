"""Compiled plan and minimal runtime configuration delivery for sandboxes.

Ensures sandboxes (E2B desktop/computer-use or Playwright) receive only what they need:
- compiled_test_plan.json
- runtime_config.json
No raw context (PRDs, Figma dumps, ticket dumps) is uploaded.
Enforces secret redaction on all payloads, log outputs, and summaries.
Verifies file delivery inside the sandbox.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..policy.redaction import Redactor
from .base import BaseSandboxProvider


class SecretExposureError(ValueError):
    """Raised when unredacted raw credentials/secrets are detected in delivery payloads."""


@dataclass
class RuntimeConfig:
    """Minimal, non-secret runtime configuration passed to a sandbox."""

    run_id: str
    target_url: str
    env: str = "staging"
    allowed_domains: List[str] = field(default_factory=list)
    env_vars: Dict[str, str] = field(default_factory=dict)
    timeout_s: int = 600
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SandboxDeliveryResult:
    """Outcome of delivering a compiled plan and runtime config to a sandbox."""

    sandbox_id: str
    plan_path: str
    config_path: str
    plan_bytes: int
    config_bytes: int
    verified: bool
    plan_id: str
    redacted_summary: Dict[str, Any] = field(default_factory=dict)


def _normalize_plan(plan: Union[Dict[str, Any], str, Path]) -> tuple[Dict[str, Any], str]:
    """Parse and return (plan_dict, plan_id)."""
    if isinstance(plan, (str, Path)) and (isinstance(plan, Path) or plan.endswith(".json")):
        p = Path(plan)
        if p.exists() and p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
        else:
            data = json.loads(str(plan))
    elif isinstance(plan, str):
        data = json.loads(plan)
    elif isinstance(plan, dict):
        data = json.loads(json.dumps(plan))  # deep copy
    else:
        raise TypeError(f"Unsupported plan type: {type(plan).__name__}")

    plan_id = str(data.get("plan_id") or data.get("id") or "compiled_plan")
    return data, plan_id


def _normalize_runtime_config(config: Union[RuntimeConfig, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(config, RuntimeConfig):
        return config.to_dict()
    if isinstance(config, dict):
        return json.loads(json.dumps(config))
    raise TypeError(f"Unsupported runtime config type: {type(config).__name__}")


def _scan_for_raw_secrets(payload_text: str, redactor: Redactor) -> List[str]:
    """Return names of secret patterns that matched unredacted content."""
    matches = []
    for name, pat in redactor.patterns.items():
        if pat.search(payload_text):
            matches.append(name)
    return matches


def deliver_plan_and_config(
    provider: BaseSandboxProvider,
    sandbox_id: str,
    plan: Union[Dict[str, Any], str, Path],
    runtime_config: Union[RuntimeConfig, Dict[str, Any]],
    destination_dir: str = "/home/user",
    verify: bool = True,
    strict_secrets: bool = True,
    alias_legacy_plan: bool = True,
) -> SandboxDeliveryResult:
    """Safely deliver compiled test plan and runtime config to an E2B sandbox.

    Args:
        provider: Sandbox provider instance (e.g. E2BSandboxProvider).
        sandbox_id: ID of the running sandbox.
        plan: Compiled test plan dict, JSON string, or Path to JSON.
        runtime_config: RuntimeConfig instance or dict.
        destination_dir: Target directory inside the sandbox (default /home/user).
        verify: Verify uploaded files exist in sandbox and are non-empty.
        strict_secrets: If True, raise SecretExposureError on unredacted secret patterns.
                        If False, automatically redact before uploading.
        alias_legacy_plan: Also write `/home/user/plan.json` for legacy executors.

    Returns:
        SandboxDeliveryResult describing delivered files and verification status.
    """
    redactor = Redactor()
    plan_dict, plan_id = _normalize_plan(plan)
    cfg_dict = _normalize_runtime_config(runtime_config)

    # Convert to JSON strings
    raw_plan_json = json.dumps(plan_dict, indent=2)
    raw_cfg_json = json.dumps(cfg_dict, indent=2)

    # Secret scanning
    leaks = _scan_for_raw_secrets(raw_plan_json, redactor) + _scan_for_raw_secrets(raw_cfg_json, redactor)
    if leaks:
        if strict_secrets:
            raise SecretExposureError(
                f"Potential raw secrets detected in delivery payload: {sorted(set(leaks))}. "
                "Use non-secret environment references (e.g. {{env.TOKEN_VAR}}) instead of inline values."
            )
        # Auto-redact
        raw_plan_json = redactor.redact(raw_plan_json)
        raw_cfg_json = redactor.redact(raw_cfg_json)

    dest = destination_dir.rstrip("/")
    plan_path = f"{dest}/compiled_test_plan.json"
    cfg_path = f"{dest}/runtime_config.json"

    plan_bytes = raw_plan_json.encode("utf-8")
    cfg_bytes = raw_cfg_json.encode("utf-8")

    # Upload files
    ok_plan = provider.upload_file(sandbox_id, plan_path, plan_bytes)
    if not ok_plan:
        raise RuntimeError(f"Failed to upload compiled test plan to {plan_path} in sandbox {sandbox_id}")

    ok_cfg = provider.upload_file(sandbox_id, cfg_path, cfg_bytes)
    if not ok_cfg:
        raise RuntimeError(f"Failed to upload runtime config to {cfg_path} in sandbox {sandbox_id}")

    if alias_legacy_plan:
        legacy_path = f"{dest}/plan.json"
        provider.upload_file(sandbox_id, legacy_path, plan_bytes)

    verified = True
    if verify:
        verified = verify_delivered_files(provider, sandbox_id, [plan_path, cfg_path])
        if not verified:
            raise RuntimeError(
                f"Verification failed: delivered files ({plan_path}, {cfg_path}) were not verified in sandbox {sandbox_id}"
            )

    redacted_summary = {
        "plan_id": plan_id,
        "title": redactor.redact(str(plan_dict.get("title", ""))),
        "sut": redactor.redact_dict(plan_dict.get("sut", {})) if isinstance(plan_dict.get("sut"), dict) else {},
        "target_url": cfg_dict.get("target_url"),
        "env": cfg_dict.get("env"),
        "allowed_domains": cfg_dict.get("allowed_domains", []),
        "cases_count": len(plan_dict.get("cases", [])) if isinstance(plan_dict.get("cases"), list) else 0,
    }

    return SandboxDeliveryResult(
        sandbox_id=sandbox_id,
        plan_path=plan_path,
        config_path=cfg_path,
        plan_bytes=len(plan_bytes),
        config_bytes=len(cfg_bytes),
        verified=verified,
        plan_id=plan_id,
        redacted_summary=redacted_summary,
    )


def verify_delivered_files(provider: BaseSandboxProvider, sandbox_id: str, paths: List[str]) -> bool:
    """Verify that the specified paths exist inside the sandbox and are non-empty."""
    for p in paths:
        # Check via run_command first if supported, fallback to download_file
        check = provider.run_command(sandbox_id, f"test -s '{p}' && echo OK", timeout=15)
        out = (check.get("stdout") or "").strip()
        if out == "OK" and check.get("exit_code") == 0:
            continue

        # Fallback to download_file
        try:
            content = provider.download_file(sandbox_id, p)
            if content and len(content) > 0:
                continue
        except Exception:
            pass
        return False
    return True
