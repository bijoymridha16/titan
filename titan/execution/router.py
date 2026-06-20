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
from titan.config import algo_settings, settings
from titan.execution.locks import acquire_order_lock, order_lock_key, release_order_lock
from titan.execution.rate_limit import AsyncRateLimiter
from titan.risk.engine import RiskEngine
from titan.risk.sizing import fixed_fractional_qty
from titan.strategies.base import Signal, SignalKind

log = logging.getLogger(__name__)


def resolve_strategy_id(strategy_name: str) -> str | None:
    """Exchange Strategy ID for this strategy (SEBI 2026). Per-strategy mapping
    first, then the configured default, then the ALGO_ID env. None if unset."""
    return (settings.strategy_id_map.get(strategy_name)
            or settings.strategy_id_default
            or algo_settings.algo_id
            or None)


@dataclass
class ExecutionResult:
    signal: Signal
    order: Order | None
    approved: bool
    reason: str | None = None


class ExecutionRouter:
    def __init__(self, broker: BrokerAdapter, risk: RiskEngine, lot_size: int = 1,
                 redis_client=None, rate_limiter: AsyncRateLimiter | None = None):
        self.broker = broker
        self.risk = risk
        self.lot_size = lot_size
        # Optional Redis client for the distributed dispatch lock. None → the
        # idempotency guard is a no-op (single-process/test mode).
        self.r = redis_client
        # Client-side OPS throttle (Scenario B). Defaults to the configured cap.
        self.rate_limiter = rate_limiter or AsyncRateLimiter(
            settings.max_ops, settings.ops_burst)

    async def _to_option_order(self, order: Order, signal: Signal) -> tuple[bool, str | None]:
        """Rewrite a (gated) underlying order into a weekly ATM option order.

        Uses the signal entry as the spot proxy; resolves the contract, sizes in
        whole lots (1 lot for now — margin-aware sizing lands in the margin
        integration), and pegs a midpoint limit when configured. Returns
        (ok, reject_reason)."""
        from datetime import datetime, timezone
        from titan.execution import options as opt

        spot = signal.entry
        inst = opt.resolve_option_contract(signal.symbol, spot, order.side,
                                           datetime.now(timezone.utc).date())
        if not inst:
            return False, f"option contract unresolved for {signal.symbol}"

        lot = int(inst.get("lotsize") or opt.lot_size_for(signal.symbol))
        order.symbol = inst["symbol"]
        order.product = Product.INTRADAY
        order.qty = opt.lots_to_qty(1, lot)   # 1 lot; margin-aware sizing is a follow-up

        # premium for sizing/limit anchor
        try:
            premium = await self.broker.get_ltp(
                inst["symbol"], settings.option_exchange, str(inst["token"]))
        except Exception as e:
            premium = signal.entry
            log.warning("option LTP lookup failed (%s) — using signal price", e)

        if settings.order_exec_mode.upper() == "MIDPOINT_LIMIT":
            # no depth here → anchor the limit at the premium (LTP). cancel-on-no-
            # fill within limit_fill_timeout_s is enforced by the position manager.
            order.order_type = OrderType.LIMIT
            order.price = opt.midpoint(None, None, premium)
        else:
            order.order_type = OrderType.MARKET
            order.price = premium
        log.info("option order: %s %s qty=%d type=%s px=%.2f",
                 order.symbol, order.side.value, order.qty,
                 order.order_type.value, order.price or 0.0)
        return True, None

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
            strategy_id=resolve_strategy_id(strategy_name),
        )

        decision = self.risk.check(order, per_unit_risk=signal.per_unit_risk,
                                   available_cash=float(funds.get("cash", 0.0)))
        if not decision.approved:
            log.warning("risk REJECT: %s", decision.reason)
            return ExecutionResult(signal, order, False, decision.reason)

        if decision.adjusted_qty:
            order.qty = decision.adjusted_qty

        # ── options pivot: risk gates on the underlying signal, but we DISPATCH
        # the concrete weekly ATM option (Multiplier 1). Swap symbol/qty/price
        # after the gate so the index-based risk check still applies. ──
        if settings.instrument_kind.upper() == "OPTION":
            ok, reason = await self._to_option_order(order, signal)
            if not ok:
                return ExecutionResult(signal, order, False, reason)

        # ── idempotency: lock this (strategy, symbol) dispatch ──
        lock_key = order_lock_key(strategy_name, signal.symbol)
        if not acquire_order_lock(self.r, lock_key, settings.order_lock_ttl_s, order.id):
            log.warning("dispatch already in flight for %s/%s — refusing duplicate",
                        strategy_name, signal.symbol)
            return ExecutionResult(signal, order, False, "dispatch in flight (lock held)")

        # OPS throttle: stagger sends to stay under the per-segment cap. Keyed by
        # product (a coarse exchange-segment proxy); waits for a free token.
        await self.rate_limiter.acquire(order.product.value)

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
