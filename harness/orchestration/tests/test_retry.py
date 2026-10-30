from harness.orchestration.retry import RetryPolicy, retry_call


class FlakyError(Exception):
    pass


def test_retry_succeeds_after_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FlakyError("boom")
        return "ok"

    policy = RetryPolicy(max_attempts=5, base_delay=0.001, jitter=0)
    result = retry_call(flaky, policy)
    assert result == "ok"
    assert calls["n"] == 3


def test_retry_exhausted():
    def always_fail():
        raise FlakyError("boom")

    policy = RetryPolicy(max_attempts=2, base_delay=0.001, jitter=0)
    try:
        retry_call(always_fail, policy)
        assert False
    except FlakyError:
        pass


def test_delay_increases():
    p = RetryPolicy(base_delay=1.0, multiplier=2.0, jitter=0)
    assert p.delay_for(1) == 1.0
    assert p.delay_for(2) == 2.0
    assert p.delay_for(3) == 4.0


def test_delay_capped():
    p = RetryPolicy(base_delay=5.0, max_delay=10.0, multiplier=2.0, jitter=0)
    assert p.delay_for(3) == 10.0
