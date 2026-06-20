"""ExecutionRouter — turns Signals into Orders, gates them through RiskEngine,
sends them to the BrokerAdapter, and tracks the resulting state machine.

Order lifecycle:
    NEW → (broker.place_order) → OPEN | FILLED | REJECTED
    OPEN → (reconciler) → FILLED | CANCELLED
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from titan.brokers.base import BrokerAdapter, Order, OrderSide, OrderStatus, OrderType, Product
from titan.risk.engine import RiskEngine
from titan.risk.sizing import fixed_fractional_qty
from titan.strategies.base import Signal, SignalKind

log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    signal: Signal
    order: Order | None
    approved: bool
    reason: str | None = None


class ExecutionRouter:
    def __init__(self, broker: BrokerAdapter, risk: RiskEngine, lot_size: int = 1):
        self.broker = broker
        self.risk = risk
        self.lot_size = lot_size

    async def submit(self, signal: Signal, strategy_name: str) -> ExecutionResult:
        if signal.kind == SignalKind.EXIT:
            log.info("EXIT signals handled by position manager, not router")
            return ExecutionResult(signal, None, approved=False, reason="exit handled elsewhere")

        funds = await self.broker.get_funds()
        equity = float(funds.get("equity", self.risk.limits.capital))

        qty = fixed_fractional_qty(
            equity=equity,
            risk_pct=self.risk.limits.max_risk_per_trade_pct,
            entry=signal.entry,
            stop=signal.stop,
            lot_size=self.lot_size,
            confidence=signal.confidence,   # M3: conviction now affects size
        )
        if qty < 1:
            return ExecutionResult(signal, None, False, "sizing → 0 qty")

        side = OrderSide.BUY if signal.kind == SignalKind.ENTRY_LONG else OrderSide.SELL
        order = Order(
            symbol=signal.symbol, side=side, qty=qty,
            order_type=OrderType.MARKET, product=Product.INTRADAY,
            price=signal.entry, strategy=strategy_name,
        )

        decision = self.risk.check(order, per_unit_risk=signal.per_unit_risk,
                                   available_cash=float(funds.get("cash", 0.0)))
        if not decision.approved:
            log.warning("risk REJECT: %s", decision.reason)
            return ExecutionResult(signal, order, False, decision.reason)

        if decision.adjusted_qty:
            order.qty = decision.adjusted_qty

        placed = await self.broker.place_order(order)
        if placed.status == OrderStatus.REJECTED:
            return ExecutionResult(signal, placed, False, placed.reject_reason)
        return ExecutionResult(signal, placed, True)
