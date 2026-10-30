from harness.checkpoints.approval import ApprovalRegistry, ApprovalState


def test_blocks_without_approval():
    state = ApprovalState(run_id="r1")
    try:
        state.require_approval()
        assert False
    except PermissionError:
        pass


def test_approve_allows_execution():
    registry = ApprovalRegistry()
    state = registry.get("r1")
    state.approve(actor="tester", detail="plan reviewed")
    assert registry.enforce("r1") is True
    assert state.approved is True
    assert len(state.audit_log) == 1


def test_revoke_blocks_again():
    state = ApprovalState(run_id="r2")
    state.approve("tester")
    state.revoke("lead")
    try:
        state.require_approval()
        assert False
    except PermissionError:
        pass
    assert len(state.audit_log) == 2
