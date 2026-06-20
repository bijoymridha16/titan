"""Exchange Strategy-ID resolution + plumbing (manifesto Scenario B)."""
from __future__ import annotations

import asyncio

from titan.brokers.base import OrderStatus
from titan.execution import router as router_mod
from titan.execution.router import ExecutionRouter, resolve_strategy_id
from titan.risk.engine import RiskDecision
from titan.strategies.base import Signal, SignalKind


def test_strategy_id_map_parsing(monkeypatch):
    monkeypatch.setattr(router_mod.settings, "strategy_ids", "orb:NSE123,vwap_revert:NSE456")
    monkeypatch.setattr(router_mod.settings, "strategy_id_default", "")
    monkeypatch.setattr(router_mod.algo_settings, "algo_id", "")
    assert resolve_strategy_id("orb") == "NSE123"
    assert resolve_strategy_id("vwap_revert") == "NSE456"


def test_strategy_id_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(router_mod.settings, "strategy_ids", "")
    monkeypatch.setattr(router_mod.settings, "strategy_id_default", "DEF999")
    assert resolve_strategy_id("unknown") == "DEF999"


def test_strategy_id_falls_back_to_algo_id(monkeypatch):
    monkeypatch.setattr(router_mod.settings, "strategy_ids", "")
    monkeypatch.setattr(router_mod.settings, "strategy_id_default", "")
    monkeypatch.setattr(router_mod.algo_settings, "algo_id", "ALGO1")
    assert resolve_strategy_id("x") == "ALGO1"


def test_strategy_id_none_when_unset(monkeypatch):
    monkeypatch.setattr(router_mod.settings, "strategy_ids", "")
    monkeypatch.setattr(router_mod.settings, "strategy_id_default", "")
    monkeypatch.setattr(router_mod.algo_settings, "algo_id", "")
    assert resolve_strategy_id("x") is None


class _Broker:
    async def get_funds(self): return {"equity": 100_000.0, "cash": 100_000.0}
    async def place_order(self, order):
        order.status = OrderStatus.OPEN
        return order


class _Risk:
    class limits:
        capital = 100_000.0
        max_risk_per_trade_pct = 1.0
    def check(self, order, per_unit_risk, available_cash):
        return RiskDecision(True, None)


def test_router_stamps_strategy_id_on_order(monkeypatch):
    monkeypatch.setattr(router_mod.settings, "strategy_ids", "orb:NSE777")
    monkeypatch.setattr(router_mod.settings, "strategy_id_default", "")
    monkeypatch.setattr(router_mod.algo_settings, "algo_id", "")
    router = ExecutionRouter(_Broker(), _Risk(), lot_size=1)
    sig = Signal(ts=None, symbol="NIFTY", kind=SignalKind.ENTRY_LONG, entry=100.0, stop=99.0)
    res = asyncio.run(router.submit(sig, "orb"))
    assert res.order.strategy_id == "NSE777"
