"""Retry policy with exponential backoff and jitter."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Type


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 10.0
    multiplier: float = 2.0
    jitter: float = 0.1
    retry_on: Tuple[Type[Exception], ...] = (Exception,)

    def delay_for(self, attempt: int) -> float:
        # attempt is 1-based for the retry
        delay = min(self.max_delay, self.base_delay * (self.multiplier ** (attempt - 1)))
        if self.jitter:
            delta = delay * self.jitter
            delay = delay + random.uniform(-delta, delta)
        return max(0.0, delay)

    def should_retry(self, exc: Exception, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        return isinstance(exc, self.retry_on)


class TimeoutError(Exception):
    pass


def with_timeout(fn: Callable, timeout_seconds: float, *args, **kwargs):
    import signal

    def handler(signum, frame):
        raise TimeoutError(f"Timed out after {timeout_seconds}s")

    old = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return fn(*args, **kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def retry_call(fn: Callable, policy: Optional[RetryPolicy] = None, *args, **kwargs):
    policy = policy or RetryPolicy()
    last_exc = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not policy.should_retry(exc, attempt):
                raise
            time.sleep(policy.delay_for(attempt))
    if last_exc:
        raise last_exc
    raise RuntimeError("retry_call failed without exception")
