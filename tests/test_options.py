"""Options routing helpers (manifesto Multiplier 1 / Scenario C)."""
from __future__ import annotations

from datetime import date

from titan.brokers.base import OrderSide
from titan.execution import options as opt


def test_nearest_strike_rounds_to_step():
    assert opt.nearest_strike(24_537, 50) == 24_550
    assert opt.nearest_strike(24_524, 50) == 24_500
    assert opt.nearest_strike(52_080, 100) == 52_100


def test_nearest_strike_zero_step():
    assert opt.nearest_strike(123.4, 0) == 123


def test_atm_strike_with_offset(monkeypatch):
    monkeypatch.setattr(opt.settings, "option_strike_steps", "NIFTY:50")
    assert opt.atm_strike("NIFTY", 24_537, offset_steps=0) == 24_550
    assert opt.atm_strike("NIFTY", 24_537, offset_steps=2) == 24_650   # +2 strikes


def test_option_type_for_side():
    assert opt.option_type_for(OrderSide.BUY) == "CE"
    assert opt.option_type_for(OrderSide.SELL) == "PE"


def test_weekly_expiry_same_weekday_is_today():
    # 2026-06-11 is a Thursday (weekday 3)
    d = date(2026, 6, 11)
    assert d.weekday() == 3
    assert opt.weekly_expiry(d, weekday=3) == d


def test_weekly_expiry_next_occurrence():
    # Monday 2026-06-08 → next Thursday 2026-06-11
    d = date(2026, 6, 8)
    assert opt.weekly_expiry(d, weekday=3) == date(2026, 6, 11)
    # Friday 2026-06-12 → next Thursday is 2026-06-18
    assert opt.weekly_expiry(date(2026, 6, 12), weekday=3) == date(2026, 6, 18)


def test_midpoint_and_fallback():
    assert opt.midpoint(100.0, 102.0, fallback=999) == 101.0
    assert opt.midpoint(None, None, fallback=50.0) == 50.0
    assert opt.midpoint(0, 0, fallback=7.5) == 7.5


def test_lot_size_for(monkeypatch):
    monkeypatch.setattr(opt.settings, "lot_sizes", "NIFTY:65,BANKNIFTY:30")
    assert opt.lot_size_for("NIFTY") == 65
    assert opt.lot_size_for("BANKNIFTY") == 30
    assert opt.lot_size_for("UNKNOWN", default=1) == 1


def test_lots_to_qty():
    assert opt.lots_to_qty(1, 65) == 65
    assert opt.lots_to_qty(3, 30) == 90
    assert opt.lots_to_qty(0, 65) == 65    # floors at 1 lot


# ── router integration: OPTION mode swaps the dispatched contract ──

import asyncio  # noqa: E402

from titan.brokers.base import OrderStatus, OrderType  # noqa: E402
from titan.execution import router as router_mod  # noqa: E402
from titan.execution.router import ExecutionRouter  # noqa: E402
from titan.risk.engine import RiskDecision  # noqa: E402
from titan.strategies.base import Signal, SignalKind  # noqa: E402


class _Broker:
    def __init__(self): self.placed = None
    async def get_funds(self): return {"equity": 100_000.0, "cash": 100_000.0}
    async def get_ltp(self, symbol, exchange="NSE", symboltoken=None): return 120.0
    async def place_order(self, order):
        order.status = OrderStatus.OPEN
        self.placed = order
        return order


class _Risk:
    class limits:
        capital = 100_000.0
        max_risk_per_trade_pct = 1.0
    def check(self, order, per_unit_risk, available_cash):
        return RiskDecision(True, None)


def test_router_swaps_to_option_contract(monkeypatch):
    monkeypatch.setattr(router_mod.settings, "instrument_kind", "OPTION")
    monkeypatch.setattr(router_mod.settings, "order_exec_mode", "MIDPOINT_LIMIT")
    monkeypatch.setattr(opt, "resolve_option_contract",
                        lambda u, s, side, today: {
                            "symbol": "NIFTY26JUN24550CE", "token": "111", "lotsize": 65})
    broker = _Broker()
    router = ExecutionRouter(broker, _Risk(), lot_size=1)
    sig = Signal(ts=None, symbol="NIFTY", kind=SignalKind.ENTRY_LONG, entry=24_537.0, stop=24_500.0)
    res = asyncio.run(router.submit(sig, "orb"))
    assert res.approved is True
    assert broker.placed.symbol == "NIFTY26JUN24550CE"
    assert broker.placed.qty == 65                       # 1 lot
    assert broker.placed.order_type == OrderType.LIMIT   # midpoint-limit mode
    assert broker.placed.price == 120.0                  # premium anchor


def test_router_rejects_when_option_unresolved(monkeypatch):
    monkeypatch.setattr(router_mod.settings, "instrument_kind", "OPTION")
    monkeypatch.setattr(opt, "resolve_option_contract", lambda u, s, side, today: None)
    router = ExecutionRouter(_Broker(), _Risk(), lot_size=1)
    sig = Signal(ts=None, symbol="NIFTY", kind=SignalKind.ENTRY_LONG, entry=24_537.0, stop=24_500.0)
    res = asyncio.run(router.submit(sig, "orb"))
    assert res.approved is False
    assert "unresolved" in res.reason
