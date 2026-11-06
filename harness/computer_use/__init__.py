"""Gemini computer-use spike & execution runner (EPIC-E2B-008.4/008.5)."""

from .action_schema import SUPPORTED_ACTIONS, ProposedAction, execute_action
from .config import ComputerUseConfig
from .gemini_client import GeminiComputerUseClient, MockGeminiComputerUseClient
from .primitives import (
    ComputerUsePrimitives,
    E2BDesktopPrimitives,
    MockComputerUsePrimitives,
)
from .ref_resolver import resolve_value
from .runner import ComputerUseRunner, RunSummary, RunnerStepResult, StepActionValidator
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
]
