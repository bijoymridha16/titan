"""RiskEngine — synchronous pre-trade gate.

EVERY order placed by EVERY strategy MUST pass through `RiskEngine.check()`.

The engine is intentionally pessimistic:
  - In doubt → reject.
  - Halts are sticky for the day. They do not auto-clear.
  - The kill switch (Redis key `titan:kill`) is checked first.

Counterparty: the strategy passes a proposed Order plus the trade's
per-unit risk (|entry - stop|). The engine validates against:

  1. Kill switch
  2. Square-off cutoff (no new entries after 15:15 IST)
  3. Daily loss cap
  4. Weekly loss cap
  5. Drawdown cap (from session-peak equity)
  6. Consecutive losses
  7. Concurrent positions
  8. Per-trade risk cap
  9. Funds available

All violations are logged to `risk_events` (Postgres) and emit a Telegram alert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from titan.brokers.base import Order, OrderSide
from titan.risk.limits import RiskLimits

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class RiskState:
    """Live mutable state — owned by the engine, updated on every fill."""
    starting_equity: float
    peak_equity: float
    current_equity: float
    realized_pnl_today: float = 0.0
    realized_pnl_week: float = 0.0
    open_positions: int = 0
    consecutive_losses: int = 0
    halted_today: bool = False
    halt_reason: Optional[str] = None
    kill_switch: bool = False

    @property
    def drawdown_inr(self) -> float:
        return max(0.0, self.peak_equity - self.current_equity)

    def on_trade_closed(self, pnl: float) -> None:
        self.realized_pnl_today += pnl
        self.realized_pnl_week += pnl
        self.current_equity += pnl
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        if pnl < 0:
            self.consecutive_losses += 1
        elif pnl > 0:
            self.consecutive_losses = 0


@dataclass
class RiskDecision:
    approved: bool
    reason: Optional[str] = None
    adjusted_qty: Optional[int] = None
    metadata: dict = field(default_factory=dict)


class RiskEngine:
    def __init__(self, limits: RiskLimits, state: RiskState, now_fn=lambda: datetime.now(IST)):
        self.limits = limits
        self.state = state
        self._now = now_fn

    # ---------- public ----------

    def check(self, order: Order, per_unit_risk: float, available_cash: float) -> RiskDecision:
        sticky_checks = (
            self._check_kill,
            self._check_session_halt,
            self._check_cutoff,
            self._check_daily_loss,
            self._check_weekly_loss,
            self._check_drawdown,
            self._check_consecutive_losses,
        )
        transient_checks = (
            self._check_concurrent_positions,
        )
        for check in sticky_checks:
            dec = check(order)
            if not dec.approved:
                if check is not self._check_session_halt:
                    self.state.halted_today = True
                    self.state.halt_reason = dec.reason
                return dec
        for check in transient_checks:
            dec = check(order)
            if not dec.approved:
                return dec

        # per-trade risk
        trade_risk = per_unit_risk * order.qty
        if trade_risk <= 0:
            return RiskDecision(False, "invalid per-unit risk")
        if trade_risk > self.limits.max_risk_per_trade_inr:
            # try to shrink the order to fit
            max_qty = int(self.limits.max_risk_per_trade_inr // per_unit_risk)
            if max_qty < 1:
                return RiskDecision(False, "per-trade risk cap unreachable at any size")
            return RiskDecision(
                True,
                reason="qty reduced to per-trade risk cap",
                adjusted_qty=max_qty,
                metadata={"requested_qty": order.qty, "per_unit_risk": per_unit_risk},
            )

        # funds
        if order.side == OrderSide.BUY and order.price:
            need = order.price * order.qty
            if need > available_cash * 1.0:  # MIS leverage handled elsewhere
                return RiskDecision(False, "insufficient funds")

        return RiskDecision(True)

    def trigger_kill(self, reason: str) -> None:
        self.state.kill_switch = True
        self.state.halted_today = True
        self.state.halt_reason = f"KILL: {reason}"

    # ---------- individual checks ----------

    def _check_kill(self, _: Order) -> RiskDecision:
        return RiskDecision(False, "kill switch active") if self.state.kill_switch else RiskDecision(True)

    def _check_session_halt(self, _: Order) -> RiskDecision:
        if self.state.halted_today:
            return RiskDecision(False, f"session halted: {self.state.halt_reason}")
        return RiskDecision(True)

    def _check_cutoff(self, _: Order) -> RiskDecision:
        now_t = self._now().timetz().replace(tzinfo=None)
        if now_t >= self.limits.intraday_square_off:
            return RiskDecision(False, f"past intraday cutoff {self.limits.intraday_square_off}")
        if now_t < time(9, 15):
            return RiskDecision(False, "pre-market")
        return RiskDecision(True)

    def _check_daily_loss(self, _: Order) -> RiskDecision:
        if -self.state.realized_pnl_today >= self.limits.max_daily_loss_inr:
            return RiskDecision(False, "daily loss cap hit")
        return RiskDecision(True)

    def _check_weekly_loss(self, _: Order) -> RiskDecision:
        if -self.state.realized_pnl_week >= self.limits.max_weekly_loss_inr:
            return RiskDecision(False, "weekly loss cap hit")
        return RiskDecision(True)

    def _check_drawdown(self, _: Order) -> RiskDecision:
        if self.state.drawdown_inr >= self.limits.max_drawdown_inr:
            return RiskDecision(False, "max drawdown breached")
        return RiskDecision(True)

    def _check_consecutive_losses(self, _: Order) -> RiskDecision:
        if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
            return RiskDecision(False, "consecutive loss limit")
        return RiskDecision(True)

    def _check_concurrent_positions(self, _: Order) -> RiskDecision:
        if self.state.open_positions >= self.limits.max_concurrent_positions:
            return RiskDecision(False, "max concurrent positions")
        return RiskDecision(True)
