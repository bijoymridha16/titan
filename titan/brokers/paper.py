"""PaperBroker — simulates fills against the next available tick / bar close.

Cost model:
  - Angel One MIS brokerage: flat ₹20 or 0.03% (whichever lower) per executed order.
  - STT, exchange txn, GST, SEBI, stamp duty roughly modeled as `_charges()`.
  - Slippage: configurable bps applied against the trade direction.

This is intentionally pessimistic — better to be surprised upward in live.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Callable, Optional

from titan.brokers.base import (
    BrokerAdapter,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)


class PaperBroker(BrokerAdapter):
    name = "paper"

    def __init__(
        self,
        cash: float,
        ltp_provider: Callable[[str], float],
        slippage_bps: float = 2.0,
    ):
        self._cash_start = cash
        self.cash = cash
        self._ltp = ltp_provider
        self.slippage_bps = slippage_bps
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._realized_pnl_by_symbol: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def place_order(self, order: Order) -> Order:
        async with self._lock:
            order.is_paper = True
            ltp = self._ltp(order.symbol)
            if ltp is None or ltp <= 0:
                order.status = OrderStatus.REJECTED
                order.reject_reason = "no LTP available"
                self._orders[order.id] = order
                return order

            fill = self._apply_slippage(ltp, order.side)
            if order.order_type == OrderType.LIMIT and order.price is not None:
                # only fill if marketable
                if order.side == OrderSide.BUY and fill > order.price:
                    order.status = OrderStatus.OPEN
                    self._orders[order.id] = order
                    return order
                if order.side == OrderSide.SELL and fill < order.price:
                    order.status = OrderStatus.OPEN
                    self._orders[order.id] = order
                    return order
                fill = order.price  # pessimistic: limit fills at limit

            order.broker_order_id = f"PAPER-{order.id[:8]}"
            order.status = OrderStatus.FILLED
            order.avg_fill_price = round(fill, 4)
            order.filled_at = datetime.utcnow()
            self._orders[order.id] = order
            self._apply_fill(order)
            return order

    async def cancel_order(self, order_id: str) -> bool:
        async with self._lock:
            o = self._orders.get(order_id)
            if o and o.status == OrderStatus.OPEN:
                o.status = OrderStatus.CANCELLED
                return True
            return False

    async def get_positions(self) -> list[Position]:
        out: list[Position] = []
        for sym, pos in self._positions.items():
            if pos.qty == 0:
                continue
            ltp = self._ltp(sym) or pos.avg_price
            pos.unrealized_pnl = (ltp - pos.avg_price) * pos.qty
            out.append(pos)
        return out

    async def get_ltp(self, symbol: str) -> float:
        return self._ltp(symbol)

    async def get_funds(self) -> dict:
        realized = sum(self._realized_pnl_by_symbol.values())
        unrealized = sum((self._ltp(s) - p.avg_price) * p.qty for s, p in self._positions.items() if p.qty)
        return {
            "cash": round(self.cash, 2),
            "starting_cash": self._cash_start,
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "equity": round(self.cash + unrealized, 2),
        }

    # ---------- internals ----------

    def _apply_slippage(self, ltp: float, side: OrderSide) -> float:
        s = ltp * (self.slippage_bps / 10_000.0)
        return ltp + s if side == OrderSide.BUY else ltp - s

    def _charges(self, notional: float) -> float:
        # Rough Angel One MIS equity charges. F&O differs — refine per segment later.
        brokerage = min(20.0, notional * 0.0003)
        stt = notional * 0.00025  # sell side; over-applied here as worst-case
        exch = notional * 0.0000345
        gst = (brokerage + exch) * 0.18
        sebi = notional * 0.000001
        stamp = notional * 0.00003
        return round(brokerage + stt + exch + gst + sebi + stamp, 2)

    def _apply_fill(self, order: Order) -> None:
        signed_qty = order.qty if order.side == OrderSide.BUY else -order.qty
        notional = order.avg_fill_price * order.qty
        charges = self._charges(notional)

        pos = self._positions.get(order.symbol) or Position(order.symbol, 0, 0.0)

        if pos.qty == 0 or (pos.qty > 0) == (signed_qty > 0):
            # opening or adding
            new_qty = pos.qty + signed_qty
            pos.avg_price = (
                (pos.avg_price * pos.qty + order.avg_fill_price * signed_qty) / new_qty
                if new_qty != 0
                else 0.0
            )
            pos.qty = new_qty
        else:
            # reducing/closing/reversing
            closed = min(abs(signed_qty), abs(pos.qty))
            pnl = (order.avg_fill_price - pos.avg_price) * (closed if pos.qty > 0 else -closed)
            self._realized_pnl_by_symbol[order.symbol] += pnl
            self.cash += pnl
            remaining = signed_qty + (closed if pos.qty > 0 else -closed)  # signed
            pos.qty = pos.qty + signed_qty
            if pos.qty == 0:
                pos.avg_price = 0.0
            elif remaining != 0 and (pos.qty > 0) == (remaining > 0):
                # reversal leg
                pos.avg_price = order.avg_fill_price

        self.cash -= charges
        self._realized_pnl_by_symbol[order.symbol] -= charges
        self._positions[order.symbol] = pos
