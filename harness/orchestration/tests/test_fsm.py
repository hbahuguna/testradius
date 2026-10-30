import time

from harness.orchestration.fsm import (
    BudgetCondition,
    DoneCondition,
    ExecutionContext,
    FailureCondition,
    RunState,
    StateMachine,
    TimeoutCondition,
    TransitionError,
)


def test_valid_transitions():
    ctx = ExecutionContext(run_id="r1")
    sm = StateMachine(ctx)
    sm.transition(RunState.PLANNING)
    sm.transition(RunState.WAITING_APPROVAL)
    sm.transition(RunState.APPROVED)
    sm.transition(RunState.RUNNING)
    sm.transition(RunState.COMPLETED)
    assert ctx.state == RunState.COMPLETED
    assert ctx.is_terminal()


def test_invalid_transition_raises():
    ctx = ExecutionContext(run_id="r1")
    sm = StateMachine(ctx)
    try:
        sm.transition(RunState.RUNNING)
        assert False, "should have raised"
    except TransitionError:
        pass


def test_done_condition_stops():
    ctx = ExecutionContext(run_id="r1", total=3, completed=3)
    sm = StateMachine(ctx, conditions=[DoneCondition()])
    ctx.state = RunState.RUNNING
    sm.tick()
    assert ctx.state == RunState.COMPLETED


def test_failure_condition_stops():
    ctx = ExecutionContext(run_id="r1", total=5, completed=2, failed=1)
    sm = StateMachine(ctx, conditions=[FailureCondition(max_failures=0)])
    ctx.state = RunState.RUNNING
    sm.tick()
    assert ctx.state == RunState.FAILED


def test_timeout_condition_stops():
    ctx = ExecutionContext(run_id="r1", start_time=time.time() - 10)
    sm = StateMachine(ctx, conditions=[TimeoutCondition(max_seconds=1)])
    ctx.state = RunState.RUNNING
    sm.tick()
    assert ctx.state == RunState.TIMED_OUT


def test_budget_condition_stops():
    ctx = ExecutionContext(run_id="r1", total=100, completed=50, failed=50)
    sm = StateMachine(ctx, conditions=[BudgetCondition(max_steps=100)])
    ctx.state = RunState.RUNNING
    sm.tick()
    assert ctx.state == RunState.FAILED
