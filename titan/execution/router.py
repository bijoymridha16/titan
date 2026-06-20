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
from titan.config import settings
from titan.execution.locks import acquire_order_lock, order_lock_key, release_order_lock
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
    def __init__(self, broker: BrokerAdapter, risk: RiskEngine, lot_size: int = 1,
                 redis_client=None):
        self.broker = broker
        self.risk = risk
        self.lot_size = lot_size
        # Optional Redis client for the distributed dispatch lock. None → the
        # idempotency guard is a no-op (single-process/test mode).
        self.r = redis_client

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

        # ── idempotency: lock this (strategy, symbol) dispatch ──
        lock_key = order_lock_key(strategy_name, signal.symbol)
        if not acquire_order_lock(self.r, lock_key, settings.order_lock_ttl_s, order.id):
            log.warning("dispatch already in flight for %s/%s — refusing duplicate",
                        strategy_name, signal.symbol)
            return ExecutionResult(signal, order, False, "dispatch in flight (lock held)")

        try:
            placed = await self.broker.place_order(order)
        except Exception as e:
            # AMBIGUOUS: we don't know if the order reached the exchange. Keep the
            # lock for its full TTL so a retry can't double-fire; the order must be
            # reconciled via broker order details before the symbol is freed.
            log.exception("place_order ambiguous for %s — lock held for reconciliation",
                          order.id)
            return ExecutionResult(signal, order, False,
                                   f"dispatch ambiguous, lock held for reconciliation: {e}")

        # definite response → release the lock
        release_order_lock(self.r, lock_key)
        if placed.status == OrderStatus.REJECTED:
            return ExecutionResult(signal, placed, False, placed.reject_reason)
        return ExecutionResult(signal, placed, True)
