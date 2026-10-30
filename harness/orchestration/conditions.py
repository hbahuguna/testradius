"""Stop condition helpers."""
from .fsm import (
    BudgetCondition,
    DoneCondition,
    ExecutionContext,
    FailureCondition,
    StateMachine,
    TimeoutCondition,
)


def default_conditions(max_seconds: int = 600, max_steps: int = 100, fail_fast: bool = False):
    conditions = [DoneCondition(), BudgetCondition(max_steps)]
    if fail_fast:
        conditions.append(FailureCondition(max_failures=0))
    conditions.append(TimeoutCondition(max_seconds))
    return conditions


__all__ = [
    "BudgetCondition",
    "DoneCondition",
    "ExecutionContext",
    "FailureCondition",
    "StateMachine",
    "TimeoutCondition",
    "default_conditions",
]
