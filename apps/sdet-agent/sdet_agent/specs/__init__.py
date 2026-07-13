"""Agentic test specifications: goal-driven test definitions."""

from __future__ import annotations

from .goal_spec import (
    AssertionSpec,
    GoalSpec,
    load_goal_spec,
    load_goal_spec_file,
    parse_assertion,
)

__all__ = [
    "AssertionSpec",
    "GoalSpec",
    "load_goal_spec",
    "load_goal_spec_file",
    "parse_assertion",
]
