"""Gemini computer-use spike & E2B desktop foundation (EPIC-E2B-008.4)."""

from .config import ComputerUseConfig
from .gemini_client import GeminiComputerUseClient, MockGeminiComputerUseClient, ProposedAction
from .primitives import (
    ComputerUsePrimitives,
    E2BDesktopPrimitives,
    MockComputerUsePrimitives,
)
from .spike import ComputerUseSpikeRunner, SpikeReport

__all__ = [
    "ComputerUseConfig",
    "ComputerUsePrimitives",
    "ComputerUseSpikeRunner",
    "E2BDesktopPrimitives",
    "GeminiComputerUseClient",
    "MockComputerUsePrimitives",
    "MockGeminiComputerUseClient",
    "ProposedAction",
    "SpikeReport",
]
