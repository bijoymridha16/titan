"""RiskEngine — synchronous pre-trade gate.

EVERY order placed by EVERY strategy MUST pass through `RiskEngine.check()`.

The engine is intentionally pessimistic:
  - In doubt → reject.
  - Halts are sticky for the day. They do not auto-clear.
  - The kill switch (Redis key `titan:kill`) is checked first.

Counterparty: the strategy passes a proposed Order plus the trade's
per-unit risk (|entry - stop|). The engine validates against:

  1. Kill switch
  2. Market hours (NSE open: 09:15–15:30 IST, Mon–Fri) — bypassed only in sim mode
  3. Square-off cutoff (no new entries after 15:15 IST)
  4. Daily loss cap
  5. Daily profit target (profit-lock — stop trading once gains are booked)
  6. Weekly loss cap
  7. Drawdown cap (from session-peak equity)
  8. Consecutive losses
  9. Concurrent positions
 10. Per-trade risk cap
 11. Funds available

The market-hours gate is what makes the system honest: in real mode it will not
open a position when the exchange is closed. Simulation must be opted into
explicitly (sim_mode), and only then are the time gates relaxed.

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
    def __init__(self, limits: RiskLimits, state: RiskState,
                 now_fn=lambda: datetime.now(IST), sim_mode_fn=lambda: False):
        self.limits = limits
        self.state = state
        self._now = now_fn
        # callable so a live toggle (Redis/API) is reflected without rebuilding
        # the engine. Accepts a bool too, for convenience in tests.
        self._sim_mode_fn = sim_mode_fn if callable(sim_mode_fn) else (lambda: bool(sim_mode_fn))
        self._day = None    # trading date currently in effect
        self._week = None   # (iso-year, iso-week) currently in effect

    @property
    def sim_mode(self) -> bool:
        return bool(self._sim_mode_fn())

    # ---------- public ----------

    def _maybe_roll(self, now) -> None:
        """Reset DAILY state at the start of each new trading day so a daily halt
        (loss cap, profit lock, consecutive-loss streak) self-recovers next
        session instead of latching forever. Multi-day risk (drawdown, weekly
        loss) persists; weekly resets on an iso-week change."""
        d = now.date()
        wk = now.isocalendar()[:2]
        if self._day is None:
            self._day, self._week = d, wk
            return
        if d != self._day:
            self._day = d
            self.state.realized_pnl_today = 0.0
            self.state.consecutive_losses = 0
            self.state.halted_today = False
            self.state.halt_reason = None
        if wk != self._week:
            self._week = wk
            self.state.realized_pnl_week = 0.0

    def check(self, order: Order, per_unit_risk: float, available_cash: float) -> RiskDecision:
        self._maybe_roll(self._now())
        # (gate, sticky): sticky gates halt the rest of the trading day on a breach.
        # Transient gates (market-hours, concurrent-positions) must NOT permanently
        # halt the day — the market reopens / sim can be toggled, and a concurrent
        # cap clears as positions close — so they do not set halted_today.
        for check, sticky in (
            (self._check_kill, True),
            (self._check_session_halt, True),
            (self._check_market_hours, False),
            (self._check_cutoff, True),
            (self._check_daily_loss, True),
            (self._check_daily_profit_lock, True),
            (self._check_weekly_loss, True),
            (self._check_drawdown, True),
            (self._check_consecutive_losses, True),
            (self._check_concurrent_positions, False),
        ):
            dec = check(order)
            if not dec.approved:
                # Only record the halt cause on the FIRST breach. Otherwise the
                # session-halt check re-wraps its own message every bar
                # ("session halted: session halted: …") and the reason balloons.
                if sticky and not self.state.halted_today:
                    self.state.halted_today = True
                    self.state.halt_reason = dec.reason
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

        # funds — intraday MIS lets notional exceed cash up to the leverage cap,
        # so index longs aren't systematically funds-rejected on a small account.
        if order.side == OrderSide.BUY and order.price:
            need = order.price * order.qty
            if need > available_cash * self.limits.leverage:
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

    def _check_market_hours(self, _: Order) -> RiskDecision:
        """The honesty gate. In real mode, refuse to open a position when the NSE
        cash market is closed (weekend, or outside 09:15–15:30 IST). Bypassed only
        when simulation is explicitly enabled."""
        if self.sim_mode:
            return RiskDecision(True)
        now = self._now()
        if now.weekday() >= 5:
            return RiskDecision(False, "market closed (weekend)")
        now_t = now.timetz().replace(tzinfo=None)
        if now_t < time(9, 15):
            return RiskDecision(False, "market closed (pre-open)")
        if now_t >= time(15, 30):
            return RiskDecision(False, "market closed (after hours)")
        return RiskDecision(True)

    def _check_cutoff(self, _: Order) -> RiskDecision:
        if self.sim_mode:
            return RiskDecision(True)
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

    def _check_daily_profit_lock(self, _: Order) -> RiskDecision:
        """Profit-lock: once today's realized PnL reaches the target, stop opening
        new positions to protect the gains. The positive mirror of the loss cap.
        A pct of 0 disables the lock. Open positions still exit normally via SL/TP."""
        if self.limits.max_daily_profit_pct <= 0:
            return RiskDecision(True)
        if self.state.realized_pnl_today >= self.limits.max_daily_profit_inr:
            return RiskDecision(False, "daily profit target reached — gains locked")
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
