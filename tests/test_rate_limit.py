"""OPS token-bucket throttle (manifesto Scenario B)."""
from __future__ import annotations

import asyncio

from titan.execution.rate_limit import AsyncRateLimiter, TokenBucket


class _Clock:
    def __init__(self, t=0.0): self.t = t
    def __call__(self): return self.t


def test_burst_then_empty():
    clk = _Clock()
    b = TokenBucket(rate=10, capacity=10, monotonic=clk)
    # 10 tokens available → 10 immediate acquires, 11th fails
    assert all(b.try_acquire() for _ in range(10))
    assert b.try_acquire() is False


def test_refill_over_time():
    clk = _Clock()
    b = TokenBucket(rate=10, capacity=10, monotonic=clk)
    for _ in range(10):
        b.try_acquire()
    assert b.try_acquire() is False
    clk.t += 0.5                      # 0.5s → +5 tokens at 10/s
    assert sum(b.try_acquire() for _ in range(10)) == 5


def test_capacity_caps_refill():
    clk = _Clock()
    b = TokenBucket(rate=10, capacity=10, monotonic=clk)
    clk.t += 100                      # huge gap, but capacity caps at 10
    assert sum(b.try_acquire() for _ in range(20)) == 10


def test_time_until_estimate():
    clk = _Clock()
    b = TokenBucket(rate=10, capacity=1, monotonic=clk)
    assert b.try_acquire() is True
    assert b.time_until() > 0.0       # must wait for refill
    assert abs(b.time_until() - 0.1) < 1e-6   # 1 token / 10 per s = 0.1s


def test_async_limiter_serializes_burst(monkeypatch):
    # with rate=high we shouldn't actually sleep; verify acquire returns
    rl = AsyncRateLimiter(rate=1000, capacity=1000)

    async def go():
        for _ in range(50):
            await rl.acquire("INTRADAY")
        return True

    assert asyncio.run(go()) is True


def test_async_limiter_blocks_when_empty():
    slept = []

    async def fake_sleep(s):
        slept.append(s)
        # simulate time passing so a token refills on the next check
        rl._bucket("default")._last -= 1.0

    rl = AsyncRateLimiter(rate=10, capacity=1, sleep=fake_sleep)

    async def go():
        await rl.acquire()            # consumes the only token
        await rl.acquire()            # must wait (sleep) then succeed

    asyncio.run(go())
    assert slept                       # it had to wait at least once
