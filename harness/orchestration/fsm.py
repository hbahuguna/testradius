"""Explicit FSM with terminal conditions and budgets."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RunState(str, Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    TIMED_OUT = "TIMED_OUT"


TERMINAL = {RunState.COMPLETED, RunState.FAILED, RunState.ABORTED, RunState.TIMED_OUT}
TRANSITIONS = {
    RunState.IDLE: {RunState.PLANNING},
    RunState.PLANNING: {RunState.WAITING_APPROVAL, RunState.FAILED},
    RunState.WAITING_APPROVAL: {RunState.APPROVED, RunState.ABORTED},
    RunState.APPROVED: {RunState.RUNNING, RunState.ABORTED},
    RunState.RUNNING: {RunState.PAUSED, RunState.COMPLETED, RunState.FAILED, RunState.ABORTED, RunState.TIMED_OUT},
    RunState.PAUSED: {RunState.RUNNING, RunState.ABORTED},
    RunState.COMPLETED: set(),
    RunState.FAILED: set(),
    RunState.ABORTED: set(),
    RunState.TIMED_OUT: set(),
}


class TransitionError(Exception):
    pass


class StopCondition:
    def __init__(self, reason: str):
        self.reason = reason

    def should_stop(self, ctx: "ExecutionContext") -> bool:
        raise NotImplementedError


class DoneCondition(StopCondition):
    def __init__(self):
        super().__init__("done")

    def should_stop(self, ctx: "ExecutionContext") -> bool:
        return ctx.completed >= ctx.total and ctx.total > 0


class FailureCondition(StopCondition):
    def __init__(self, max_failures: int = 0):
        super().__init__("failed")
        self.max_failures = max_failures

    def should_stop(self, ctx: "ExecutionContext") -> bool:
        if self.max_failures < 0:
            return ctx.failed > 0
        return ctx.failed > self.max_failures


class TimeoutCondition(StopCondition):
    def __init__(self, max_seconds: int = 600):
        super().__init__("timeout")
        self.max_seconds = max_seconds

    def should_stop(self, ctx: "ExecutionContext") -> bool:
        if ctx.start_time is None:
            return False
        import time

        return (time.time() - ctx.start_time) >= self.max_seconds


class BudgetCondition(StopCondition):
    def __init__(self, max_steps: int = 100):
        super().__init__("budget")
        self.max_steps = max_steps

    def should_stop(self, ctx: "ExecutionContext") -> bool:
        return ctx.completed + ctx.failed >= self.max_steps


@dataclass
class ExecutionContext:
    run_id: str
    total: int = 0
    completed: int = 0
    failed: int = 0
    start_time: Optional[float] = None
    state: RunState = RunState.IDLE
    history: list = field(default_factory=list)

    def is_terminal(self) -> bool:
        return self.state in TERMINAL


class StateMachine:
    def __init__(self, ctx: ExecutionContext, conditions: Optional[list] = None):
        self.ctx = ctx
        self.conditions = conditions or [DoneCondition()]

    def can_transition(self, to: RunState) -> bool:
        return to in TRANSITIONS.get(self.ctx.state, set())

    def transition(self, to: RunState) -> RunState:
        if not self.can_transition(to):
            raise TransitionError(f"Invalid transition {self.ctx.state} -> {to}")
        self.ctx.state = to
        import time
        self.ctx.history.append((to, time.time()))
        return self.ctx.state

    def evaluate_stop(self) -> Optional[StopCondition]:
        if self.ctx.is_terminal():
            return None
        for cond in self.conditions:
            if cond.should_stop(self.ctx):
                return cond
        return None

    def tick(self) -> RunState:
        stop = self.evaluate_stop()
        if stop:
            if stop.reason == "timeout":
                self.transition(RunState.TIMED_OUT)
            elif stop.reason in ("failed", "budget"):
                self.transition(RunState.FAILED)
            else:
                self.transition(RunState.COMPLETED)
            return self.ctx.state
        return self.ctx.state
