"""Client-side OPS throttle — keeps order dispatch under the SEBI/broker cap.

Manifesto Scenario B: the 2026 framework caps automated submissions at ~10
orders/sec per exchange-segment; breaching it risks an API ban. Because TITAN
re-evaluates the whole universe every cycle, simultaneous signals can burst well
past that. This token bucket staggers sends so the rate is never exceeded.

`TokenBucket` is pure and clock-injected (unit-testable). `AsyncRateLimiter`
wraps per-segment buckets and awaits a free token before returning.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable


class TokenBucket:
    def __init__(self, rate: float, capacity: float,
                 monotonic: Callable[[], float] = time.monotonic):
        self.rate = float(rate)            # tokens refilled per second
        self.capacity = float(capacity)    # max burst
        self._mono = monotonic
        self._tokens = float(capacity)
        self._last = monotonic()

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._last)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last = now

    def try_acquire(self, n: float = 1.0) -> bool:
        """Consume n tokens if available; return success."""
        now = self._mono()
        self._refill(now)
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    def time_until(self, n: float = 1.0) -> float:
        """Seconds until n tokens would be available (0 if already)."""
        now = self._mono()
        self._refill(now)
        if self._tokens >= n:
            return 0.0
        return (n - self._tokens) / self.rate if self.rate > 0 else float("inf")


class AsyncRateLimiter:
    def __init__(self, rate: float, capacity: float | None = None, sleep=None):
        self.rate = rate
        self.capacity = capacity if capacity is not None else max(1.0, rate)
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()
        self._sleep = sleep or asyncio.sleep   # injectable for tests

    def _bucket(self, key: str) -> TokenBucket:
        b = self._buckets.get(key)
        if b is None:
            b = self._buckets[key] = TokenBucket(self.rate, self.capacity)
        return b

    async def acquire(self, key: str = "default") -> None:
        """Block (via the sleep fn) until a token is free for this segment."""
        async with self._lock:
            b = self._bucket(key)
            while not b.try_acquire():
                await self._sleep(min(b.time_until(), 0.25))
