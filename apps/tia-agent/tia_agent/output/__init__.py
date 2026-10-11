"""Structured output (E5/O1): schema, validation, and run-command building."""

from __future__ import annotations

from .commands import build_run_commands
from .schema import OUTPUT_SCHEMA, SCHEMA_VERSION, validate_output

__all__ = [
    "OUTPUT_SCHEMA",
    "SCHEMA_VERSION",
    "validate_output",
    "build_run_commands",
]
