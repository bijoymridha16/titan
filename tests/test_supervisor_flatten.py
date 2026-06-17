"""EOD flatten tests for the supervisor.

Covers the bug found 2026-06-17 where:
  - no wall-clock task closed open positions at session end
  - POST /flatten published FLATTEN to titan:control but supervisor never
    subscribed, so the endpoint silently no-op'd
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from titan.brokers.base import OrderSide
from titan.strategies.supervisor import Supervisor, OpenTrade


def _make_supervisor(open_trade: OpenTrade, ltp: float) -> Supervisor:
    """Build a Supervisor with only the attributes _flatten_all touches."""
    s = Supervisor.__new__(Supervisor)
    s.open_trades = {(open_trade.strategy, open_trade.symbol): open_trade}
    s._ltp_cache = {open_trade.symbol: ltp}
    s._ltp_sync = lambda sym: float(s._ltp_cache.get(sym, 0.0))

    async def _no_refresh():
        return None
    s._refresh_ltps = _no_refresh

    s.broker = SimpleNamespace(place_order=AsyncMock(return_value=None))
    s.r = SimpleNamespace(set=AsyncMock(return_value=None))
    s.state = SimpleNamespace(
        current_equity=500_000.0,
        consecutive_losses=0,
        open_positions=1,
        on_trade_closed=MagicMock(),
    )
    s._persist_close = MagicMock()
    return s


@pytest.mark.asyncio
async def test_flatten_closes_long_at_ltp_with_eod_reason():
    t = OpenTrade(
        id="t1", strategy="orb", symbol="ICICIBANK",
        side=OrderSide.BUY, qty=10, entry_price=1300.0,
        stop=1280.0, target=1340.0,
        entry_ts=datetime(2026, 6, 17, 9, 30, tzinfo=timezone.utc),
    )
    sup = _make_supervisor(t, ltp=1325.0)

    n = await sup._flatten_all("eod_flatten")

    assert n == 1
    assert sup.open_trades == {}
    sup._persist_close.assert_called_once()
    args = sup._persist_close.call_args.args
    assert args[0] is t
    assert args[2] == 1325.0           # exit_price = LTP
    assert args[3] == "eod_flatten"    # reason
    assert args[4] == (1325.0 - 1300.0) * 10  # pnl long
    sup.broker.place_order.assert_awaited_once()
    sent = sup.broker.place_order.await_args.args[0]
    assert sent.side == OrderSide.SELL  # close side opposite of long
    assert sent.qty == 10
    sup.state.on_trade_closed.assert_called_once_with(250.0)


@pytest.mark.asyncio
async def test_flatten_closes_short_at_ltp_with_manual_reason():
    t = OpenTrade(
        id="t2", strategy="vwap_revert", symbol="ICICIBANK",
        side=OrderSide.SELL, qty=8, entry_price=1300.0,
        stop=1320.0, target=1280.0,
        entry_ts=datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc),
    )
    sup = _make_supervisor(t, ltp=1290.0)

    n = await sup._flatten_all("manual_flatten")

    assert n == 1
    assert sup.open_trades == {}
    args = sup._persist_close.call_args.args
    assert args[3] == "manual_flatten"
    assert args[4] == (1290.0 - 1300.0) * 8 * -1  # short pnl = (entry-exit)*qty
    sent = sup.broker.place_order.await_args.args[0]
    assert sent.side == OrderSide.BUY


@pytest.mark.asyncio
async def test_flatten_empty_open_trades_returns_zero():
    sup = Supervisor.__new__(Supervisor)
    sup.open_trades = {}
    n = await sup._flatten_all("eod_flatten")
    assert n == 0


@pytest.mark.asyncio
async def test_flatten_skips_position_with_no_ltp():
    t = OpenTrade(
        id="t3", strategy="orb", symbol="UNKNOWN",
        side=OrderSide.BUY, qty=5, entry_price=100.0,
        stop=95.0, target=110.0,
        entry_ts=datetime(2026, 6, 17, 9, 30, tzinfo=timezone.utc),
    )
    sup = _make_supervisor(t, ltp=0.0)
    n = await sup._flatten_all("eod_flatten")
    assert n == 0
    assert (t.strategy, t.symbol) in sup.open_trades  # not closed
    sup._persist_close.assert_not_called()
