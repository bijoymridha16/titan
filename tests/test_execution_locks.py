"""Order-dispatch idempotency lock (manifesto Scenario A)."""
from __future__ import annotations

import asyncio

import pytest

from titan.brokers.base import Order, OrderSide, OrderStatus, OrderType, Product
from titan.execution import locks
from titan.execution.router import ExecutionRouter
from titan.risk.engine import RiskDecision
from titan.strategies.base import Signal, SignalKind


class FakeRedis:
    """Minimal SET NX EX / DELETE semantics."""
    def __init__(self): self.kv = {}
    def set(self, name, value, nx=False, ex=None):
        if nx and name in self.kv:
            return None
        self.kv[name] = value
        return True
    def delete(self, name): self.kv.pop(name, None)


# ── pure helpers ──

def test_lock_key_format():
    assert locks.order_lock_key("orb", "NIFTY") == "titan:lock:order:orb:NIFTY"


def test_acquire_then_blocked_then_released():
    r = FakeRedis()
    k = locks.order_lock_key("orb", "NIFTY")
    assert locks.acquire_order_lock(r, k, 30, "id1") is True
    assert locks.acquire_order_lock(r, k, 30, "id2") is False   # held
    locks.release_order_lock(r, k)
    assert locks.acquire_order_lock(r, k, 30, "id3") is True     # freed


def test_acquire_noop_without_redis():
    assert locks.acquire_order_lock(None, "k", 30, "id") is True


# ── router integration ──

class _Broker:
    def __init__(self, behavior="ok"): self.behavior = behavior; self.calls = 0
    async def get_funds(self): return {"equity": 100_000.0, "cash": 100_000.0}
    async def place_order(self, order):
        self.calls += 1
        if self.behavior == "raise":
            raise TimeoutError("read timeout")
        order.status = OrderStatus.OPEN
        order.broker_order_id = "B123"
        return order


class _Risk:
    class limits:
        capital = 100_000.0
        max_risk_per_trade_pct = 1.0
    def check(self, order, per_unit_risk, available_cash):
        return RiskDecision(True, None)


def _sig():
    return Signal(ts=None, symbol="NIFTY", kind=SignalKind.ENTRY_LONG,
                  entry=100.0, stop=99.0)


def test_router_releases_lock_on_definite_response():
    r = FakeRedis()
    router = ExecutionRouter(_Broker("ok"), _Risk(), lot_size=1, redis_client=r)
    res = asyncio.run(router.submit(_sig(), "orb"))
    assert res.approved is True
    assert r.kv == {}          # lock released


def test_router_holds_lock_on_ambiguous_dispatch():
    r = FakeRedis()
    router = ExecutionRouter(_Broker("raise"), _Risk(), lot_size=1, redis_client=r)
    res = asyncio.run(router.submit(_sig(), "orb"))
    assert res.approved is False
    assert "reconciliation" in res.reason
    assert locks.order_lock_key("orb", "NIFTY") in r.kv   # lock retained


def test_router_refuses_duplicate_while_locked():
    r = FakeRedis()
    r.set(locks.order_lock_key("orb", "NIFTY"), "prev", nx=True, ex=30)  # in flight
    broker = _Broker("ok")
    router = ExecutionRouter(broker, _Risk(), lot_size=1, redis_client=r)
    res = asyncio.run(router.submit(_sig(), "orb"))
    assert res.approved is False
    assert "in flight" in res.reason
    assert broker.calls == 0   # never dispatched
