"""Gemini computer-use spike, runner, integration, safety & observability (EPIC-E2B-008)."""

from .action_schema import SUPPORTED_ACTIONS, ProposedAction, execute_action
from .audit import AUDIT_SCHEMA, AuditEntry, AuditWriter, validate_trace_file
from .config import ComputerUseConfig
from .gemini_client import GeminiComputerUseClient, MockGeminiComputerUseClient
from .integration import ComputerUseHarnessRunner, PlanCheckpoint, build_findings_from_run, normalize_artifacts
from .metrics import aggregate_metrics, compute_run_metrics
from .primitives import (
    ComputerUsePrimitives,
    E2BDesktopPrimitives,
    MockComputerUsePrimitives,
)
from .ref_resolver import resolve_value
from .runner import ComputerUseRunner, RunSummary, RunnerStepResult, StepActionValidator
from .safety import SafetyPolicy, detect_prompt_injection, sanitize_untrusted_text
from .spike import ActionValidator, ComputerUseSpikeRunner, SpikeReport

__all__ = [
    "ComputerUseConfig",
    "ComputerUsePrimitives",
    "ComputerUseRunner",
    "ComputerUseSpikeRunner",
    "E2BDesktopPrimitives",
    "GeminiComputerUseClient",
    "MockComputerUsePrimitives",
    "MockGeminiComputerUseClient",
    "ProposedAction",
    "RunSummary",
    "RunnerStepResult",
    "SpikeReport",
    "StepActionValidator",
    "SUPPORTED_ACTIONS",
    "ActionValidator",
    "execute_action",
    "resolve_value",
    "ComputerUseHarnessRunner",
    "PlanCheckpoint",
    "build_findings_from_run",
    "normalize_artifacts",
    "SafetyPolicy",
    "detect_prompt_injection",
    "sanitize_untrusted_text",
    "AUDIT_SCHEMA",
    "AuditEntry",
    "AuditWriter",
    "validate_trace_file",
    "aggregate_metrics",
    "compute_run_metrics",
]
