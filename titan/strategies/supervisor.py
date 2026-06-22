"""Strategy supervisor.

Drives the on_bar() loop end-to-end:
    Redis pub/sub bars:<sym>:<tf>  →  load history from Postgres  →
    strategy.on_bar(window)  →  Signal  →  ExecutionRouter.submit()  →
    PaperBroker fill  →  write `trades` row in Postgres  →
    on subsequent bars, check SL / TP / EOD square-off → close & write exit.

Also maintains:
    titan:heartbeat:<strategy>        ISO timestamp per bar processed
    titan:consec_losses               int for dashboard
    equity_curve                      one row per closed trade
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

import pandas as pd
import redis as _redis_sync
import redis.asyncio as aioredis
from sqlalchemy import text

from titan.analytics import recorder as rec
from titan.brokers.angelone import AngelOneBroker
from titan.brokers.base import Order, OrderSide, OrderStatus, OrderType, Product
from titan.brokers.paper import PaperBroker
from titan.config import settings
from titan.data.store import engine
from titan.execution.router import ExecutionRouter
from titan.risk.engine import RiskEngine, RiskState
from titan.risk.limits import RiskLimits
from titan.strategies.base import Signal, SignalKind, Strategy
from titan.strategies.registry import BASE_STRATEGIES as STRATEGIES

log = logging.getLogger(__name__)

NON_TRADABLE_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY"}

# subscribe to (universe × timeframe used by strategies). 5m for intraday;
# 1d for TSMOM. Bar writer needs to publish bars:<symbol>:1d on daily close.
TIMEFRAMES = {"5m", "1d"}
WINDOW_BARS = 200


def _to_utc(ts) -> datetime:
    """Coerce a signal/bar timestamp (naive, IST-aware, or UTC) to tz-aware UTC,
    so trade times share the same clock as the OHLCV candles they render on."""
    try:
        p = pd.Timestamp(ts)
        p = p.tz_localize("UTC") if p.tzinfo is None else p.tz_convert("UTC")
        return p.to_pydatetime()
    except Exception:
        return datetime.now(timezone.utc)


@dataclass
class OpenTrade:
    id: str
    strategy: str
    symbol: str
    side: OrderSide
    qty: int
    entry_price: float
    stop: float
    target: Optional[float]
    entry_ts: datetime
    regime: Optional[str] = None


class Supervisor:
    def __init__(self):
        self.r = aioredis.from_url(settings.redis_url, decode_responses=True)
        self.limits = RiskLimits.from_settings()
        # Reconstruct equity from realized PnL so restarts don't reset to capital.
        realized = self._realized_pnl_total()
        current = settings.capital + realized
        peak = self._peak_equity_seen(default=current)
        self.state = RiskState(
            starting_equity=settings.capital,
            peak_equity=peak,
            current_equity=current,
        )
        # one PaperBroker shared (per-symbol LTP from Redis)
        self.broker = PaperBroker(
            cash=settings.capital,
            ltp_provider=self._ltp_sync,
            slippage_bps=2.0,
        )
        # Honest clock: the risk engine always sees the truth (real IST in real
        # mode, an explicit labeled simulation clock only when sim_mode is on).
        # No silent "pretend it's 11am" override — the market-hours gate decides
        # whether trading is allowed, and simulation must be opted into.
        import redis as _redis_sync
        from titan import clock
        self.r_sync = _redis_sync.from_url(settings.redis_url, decode_responses=True)
        self.risk = RiskEngine(
            self.limits, self.state,
            now_fn=lambda: clock.trading_now(self.r_sync),
            sim_mode_fn=lambda: clock.sim_mode(self.r_sync),
        )
        self.router = ExecutionRouter(self.broker, self.risk, lot_size=1,
                                      redis_client=self.r_sync)

        # ─── shadow live broker (paper+dry-run parallel rehearsal) ───
        # When TITAN_LIVE_ENABLED=1 + TITAN_LIVE_DRY_RUN=1, every paper fill
        # ALSO fires through AngelOneBroker.place_order(), which goes through
        # all 5 gates and logs the exact payload that *would* have been sent
        # to Angel's REST API. Failures are isolated — they never affect the
        # paper trade. This is the dress rehearsal for going live.
        self.shadow_broker: AngelOneBroker | None = None
        if settings.live_enabled:
            try:
                self.shadow_broker = AngelOneBroker()
                log.info("shadow live broker armed (dry_run=%s)", settings.live_dry_run)
            except Exception as e:
                log.warning("shadow broker init failed: %s — continuing paper-only", e)

        # active strategy instances keyed by (name, symbol)
        self.strategies: dict[tuple[str, str], Strategy] = {}
        # open trades by (strategy, symbol) — reload from DB so restarts
        # don't lose track of in-flight positions
        self.open_trades: dict[tuple[str, str], OpenTrade] = self._load_open_trades()
        self.state.open_positions = len(self.open_trades)
        self._ltp_cache: dict[str, float] = {}

    # ─────────────── helpers ───────────────
    def _ltp_sync(self, symbol: str) -> float:
        return float(self._ltp_cache.get(symbol, 0.0))

    async def _refresh_ltps(self):
        for s in settings.symbols:
            v = await self.r.get(f"titan:ltp:{s}")
            if v:
                try: self._ltp_cache[s] = float(v)
                except Exception: pass

    def _load_window(self, symbol: str, tf: str, n: int = WINDOW_BARS) -> pd.DataFrame:
        with engine().connect() as cx:
            df = pd.read_sql(text("""
                SELECT ts, o, h, l, c, v FROM ohlcv
                WHERE symbol=:s AND timeframe=:tf
                ORDER BY ts DESC LIMIT :n
            """), cx, params={"s": symbol, "tf": tf, "n": n},
            parse_dates=["ts"], index_col="ts")
        return df.sort_index()

    def _persist_open_trade(self, t: OpenTrade) -> None:
        with engine().begin() as cx:
            cx.execute(text("""
                INSERT INTO trades (id, strategy, symbol, qty, side, entry_ts,
                                    entry_price, stop_loss, target, regime, is_paper)
                VALUES (:id, :strat, :sym, :qty, :side, :ets, :ep, :sl, :tg, :rg, true)
            """), {"id": t.id, "strat": t.strategy, "sym": t.symbol,
                   "qty": t.qty, "side": t.side.value, "ets": t.entry_ts,
                   "ep": t.entry_price, "sl": t.stop, "tg": t.target,
                   "rg": t.regime})

    def _load_open_trades(self) -> dict[tuple[str, str], OpenTrade]:
        out: dict[tuple[str, str], OpenTrade] = {}
        try:
            with engine().begin() as cx:
                rows = cx.execute(text("""
                    SELECT id, strategy, symbol, side, qty, entry_price,
                           stop_loss, target, entry_ts
                    FROM trades WHERE exit_ts IS NULL
                """)).all()
            for r in rows:
                side = OrderSide(r.side) if r.side in ("BUY", "SELL") else (
                    OrderSide.BUY if r.side == "LONG" else OrderSide.SELL
                )
                out[(r.strategy, r.symbol)] = OpenTrade(
                    id=str(r.id), strategy=r.strategy, symbol=r.symbol,
                    side=side, qty=int(r.qty),
                    entry_price=float(r.entry_price),
                    stop=float(r.stop_loss) if r.stop_loss is not None else 0.0,
                    target=float(r.target) if r.target is not None else None,
                    entry_ts=r.entry_ts,
                )
        except Exception as e:
            log.warning("could not reload open trades: %s", e)
        return out

    def _realized_pnl_total(self) -> float:
        try:
            with engine().begin() as cx:
                row = cx.execute(text(
                    "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE pnl IS NOT NULL"
                )).scalar()
            return float(row or 0.0)
        except Exception:
            return 0.0

    def _peak_equity_seen(self, default: float) -> float:
        try:
            with engine().begin() as cx:
                row = cx.execute(text("SELECT MAX(equity) FROM equity_curve")).scalar()
            return float(row) if row is not None else default
        except Exception:
            return default

    def _persist_close(self, t: OpenTrade, exit_ts: datetime,
                       exit_price: float, exit_reason: str, pnl: float) -> None:
        with engine().begin() as cx:
            cx.execute(text("""
                UPDATE trades SET exit_ts=:ets, exit_price=:xp,
                                  pnl=:pnl, exit_reason=:rs
                WHERE id=:id
            """), {"ets": exit_ts, "xp": exit_price, "pnl": pnl,
                   "rs": exit_reason, "id": t.id})
            cx.execute(text("""
                INSERT INTO equity_curve (ts, equity)
                VALUES (:ts, :eq) ON CONFLICT (ts) DO NOTHING
            """), {"ts": exit_ts, "eq": round(self.state.current_equity, 2)})

    # ─────────────── core loop ───────────────
    async def _on_bar_event(self, symbol: str, tf: str, bar: dict) -> None:
        await self._refresh_ltps()
        enabled = await self.r.smembers("titan:strategies:enabled") or set()
        if not enabled:
            return

        # 1) check SL/TP exits on any open trade for this symbol
        await self._check_exits(symbol, bar)

        # 2) load the bar window ONCE for this (symbol, tf) — it's identical for
        #    every strategy on this timeframe, so loading per-strategy would mean
        #    N redundant DB reads per event (crippling with a 50-symbol universe).
        window = self._load_window(symbol, tf)
        if window.empty:
            return
        regime = await self.r.get("titan:regime:current")
        last = window.iloc[-1]
        features = {"o": float(last["o"]), "h": float(last["h"]),
                    "l": float(last["l"]), "c": float(last["c"]),
                    "v": float(last["v"]), "window_bars": int(len(window))}

        # 3) run each enabled strategy that matches this tf on the shared window
        for name in enabled:
            cls = STRATEGIES.get(name)
            if not cls or cls.timeframe != tf:
                continue
            key = (name, symbol)
            inst = self.strategies.get(key) or cls(symbol)
            self.strategies[key] = inst

            try:
                sigs = inst.on_bar(window)
            except Exception as e:
                log.exception("%s.on_bar(%s) failed: %s", name, symbol, e)
                continue
            for sig in sigs:
                # capture EVERY signal — including the ones we don't act on
                if sig.kind == SignalKind.EXIT:
                    # M2: honour strategy-driven exits (e.g. TSMOM trend flip,
                    # Supertrend flip). Close the open position at the bar close.
                    ot = self.open_trades.get((name, symbol))
                    if ot is not None:
                        self._record_signal(name, sig, regime, accepted=True,
                                            reject_reason=None, features=features)
                        await self._close_trade(ot, float(last["c"]), "signal_exit",
                                                _to_utc(sig.ts))
                    else:
                        self._record_signal(name, sig, regime, accepted=False,
                                            reject_reason="exit but no open position",
                                            features=features)
                    continue
                if sig.symbol in NON_TRADABLE_INDICES and settings.live_enabled:
                    # Indices aren't directly tradable on the live cash path at this
                    # capital — block real orders and route via ETF/option instead.
                    # In paper/sim we trade the index NOTIONALLY (PaperBroker fills
                    # at index LTP) so strategies can be rehearsed on the index itself.
                    self._record_signal(name, sig, regime, accepted=False,
                                        reject_reason="non-tradable index (live) — route via ETF/option",
                                        features=features)
                    continue
                if (name, symbol) in self.open_trades:
                    self._record_signal(name, sig, regime, accepted=False,
                                        reject_reason="position already open", features=features)
                    continue
                await self._open_position(name, sig, regime, features)

            await self.r.set(f"titan:heartbeat:{name}",
                             datetime.now(timezone.utc).isoformat())

        await self._publish_session_state()

    def _record_risk_event(self, kind: str, detail: dict) -> None:
        """Persist a risk event (halt / kill / profit-lock) to risk_events so the
        dashboard's 'Recent risk events' panel is populated. Best-effort."""
        try:
            with engine().begin() as cx:
                cx.execute(text(
                    "INSERT INTO risk_events (ts, kind, detail) "
                    "VALUES (now(), :k, CAST(:d AS JSONB))"),
                    {"k": kind, "d": json.dumps(detail)})
        except Exception as e:
            log.warning("risk_event persist failed: %s", e)

    async def _publish_session_state(self) -> None:
        """Surface risk-engine session state to Redis so the dashboard can show
        the true halt status (loss-halt vs profit-lock vs active), and record the
        START of each halt episode to risk_events."""
        try:
            await self.r.set("titan:session:realized_pnl",
                             f"{self.state.realized_pnl_today:.2f}")
            if self.state.halted_today:
                reason = self.state.halt_reason or "halted"
                await self.r.set("titan:session:status", "HALTED")
                await self.r.set("titan:session:reason", reason)
                # record once per halt episode (reason changes on a new halt)
                if getattr(self, "_last_halt_recorded", None) != reason:
                    self._last_halt_recorded = reason
                    kind = "PROFIT_LOCK" if "profit" in reason.lower() else "SESSION_HALT"
                    self._record_risk_event(kind, {
                        "reason": reason,
                        "realized_pnl_today": round(self.state.realized_pnl_today, 2),
                        "consecutive_losses": self.state.consecutive_losses,
                        "equity": round(self.state.current_equity, 2),
                    })
            else:
                await self.r.set("titan:session:status", "ACTIVE")
                await self.r.set("titan:session:reason", "")
                self._last_halt_recorded = None   # reset so the next halt records
        except Exception:
            pass

    def _record_signal(self, strategy_name: str, sig: Signal, regime,
                       accepted: bool, reject_reason, features: dict,
                       order_id=None) -> str:
        """Persist a signal (accepted or not) + its feature snapshot. Best-effort."""
        sid = rec.new_id()
        rec.record_signal(
            signal_id=sid, strategy=strategy_name, symbol=sig.symbol,
            kind=sig.kind.value, entry=sig.entry, stop=sig.stop, target=sig.target,
            per_unit_risk=sig.per_unit_risk, confidence=sig.confidence,
            regime=regime, accepted=accepted, reject_reason=reject_reason,
            order_id=order_id, reason=sig.reason,
        )
        rec.record_feature_snapshot(strategy=strategy_name, symbol=sig.symbol,
                                    signal_id=sid, features=features)
        return sid

    async def _open_position(self, strategy_name: str, sig: Signal,
                             regime=None, features: dict | None = None) -> None:
        features = features or {}
        res = await self.router.submit(sig, strategy_name)
        order = res.order
        side = OrderSide.BUY if sig.kind == SignalKind.ENTRY_LONG else OrderSide.SELL
        filled = bool(res.approved and order and order.status == OrderStatus.FILLED)

        # record the signal (accepted = it reached a fill) + the order attempt
        oid = rec.new_id()
        sid = self._record_signal(strategy_name, sig, regime, accepted=filled,
                                  reject_reason=None if filled else res.reason,
                                  features=features, order_id=oid if filled else None)
        rec.record_order_attempt(
            order_id=oid, signal_id=sid, strategy=strategy_name, symbol=sig.symbol,
            side=side.value, qty_requested=(order.qty if order else None),
            qty_final=(order.qty if order else None),
            order_type="MARKET", product="INTRADAY",
            price=sig.entry, risk_approved=bool(res.approved),
            risk_reason=res.reason, broker="paper",
            status=(order.status.value if order else "REJECTED"),
            broker_order_id=(order.broker_order_id if order else None),
            avg_fill_price=(order.avg_fill_price if order else None),
            reject_reason=None if res.approved else res.reason,
        )
        if not filled:
            log.info("REJECT %s %s: %s", strategy_name, sig.symbol, res.reason)
            return
        # realized-vs-modeled slippage on the entry fill
        rec.record_fill(
            order_id=oid, strategy=strategy_name, symbol=sig.symbol, side=side.value,
            qty=order.qty, fill_price=order.avg_fill_price,
            ltp_at_decision=self._ltp_cache.get(sig.symbol), modeled_slippage_bps=2.0,
            is_paper=True,
        )
        t = OpenTrade(
            id=str(uuid.uuid4()), strategy=strategy_name, symbol=sig.symbol,
            side=side, qty=res.order.qty,
            entry_price=res.order.avg_fill_price, stop=sig.stop, target=sig.target,
            entry_ts=_to_utc(sig.ts),  # market/bar time, so it aligns with candles
            regime=regime,
        )
        self.open_trades[(strategy_name, sig.symbol)] = t
        self._persist_open_trade(t)
        self.state.open_positions = len(self.open_trades)
        log.info("OPEN  %s %s %s qty=%d @ %.2f sl=%.2f tg=%s",
                 strategy_name, sig.symbol, side.value, t.qty,
                 t.entry_price, t.stop, f"{t.target:.2f}" if t.target else "—")

        # ─── shadow live submit (dry-run by default) ───
        if self.shadow_broker is not None:
            try:
                shadow_order = Order(
                    symbol=sig.symbol, side=side, qty=t.qty,
                    order_type=OrderType.MARKET, product=Product.INTRADAY,
                    price=t.entry_price, strategy=strategy_name,
                    is_paper=False,
                )
                if self.shadow_broker._jwt is None:
                    await self.shadow_broker.connect()
                shadow_res = await self.shadow_broker.place_order(shadow_order)
                tag = "SHADOW-DRY" if settings.live_dry_run else "SHADOW-LIVE"
                log.info("%s entry %s %s qty=%d → %s (%s)",
                         tag, sig.symbol, side.value, t.qty,
                         shadow_res.status.value,
                         shadow_res.reject_reason or shadow_res.broker_order_id or "ok")
            except Exception as e:
                log.warning("shadow submit failed (paper trade unaffected): %s", e)

    async def _check_exits(self, symbol: str, bar: dict) -> None:
        h = float(bar["h"]); l = float(bar["l"]); c = float(bar["c"])
        ts = _to_utc(bar["ts"]) if bar.get("ts") else datetime.now(timezone.utc)
        # iterate over a copy because we may mutate
        for key, t in list(self.open_trades.items()):
            if t.symbol != symbol:
                continue
            exit_price = None; reason = None
            if t.side == OrderSide.BUY:
                if l <= t.stop: exit_price, reason = t.stop, "stop"
                elif t.target and h >= t.target: exit_price, reason = t.target, "target"
            else:
                if h >= t.stop: exit_price, reason = t.stop, "stop"
                elif t.target and l <= t.target: exit_price, reason = t.target, "target"
            if exit_price is None:
                continue
            await self._close_trade(t, exit_price, reason, ts)

    async def _close_trade(self, t: "OpenTrade", exit_price: float,
                           reason: str, ts: datetime) -> None:
        """Single exit path — used by SL/TP checks AND strategy EXIT signals (M2)."""
        key = (t.strategy, t.symbol)
        if key not in self.open_trades:
            return
        close_side = OrderSide.SELL if t.side == OrderSide.BUY else OrderSide.BUY
        await self.broker.place_order(Order(
            symbol=t.symbol, side=close_side, qty=t.qty,
            order_type=OrderType.MARKET, product=Product.INTRADAY,
            price=exit_price, strategy=t.strategy,
        ))
        sign = 1 if t.side == OrderSide.BUY else -1
        pnl = (exit_price - t.entry_price) * t.qty * sign
        self.state.on_trade_closed(pnl)
        await self.r.set("titan:consec_losses", str(self.state.consecutive_losses))
        self._persist_close(t, ts, exit_price, reason, pnl)
        del self.open_trades[key]
        self.state.open_positions = len(self.open_trades)
        log.info("CLOSE %s %s @ %.2f  %s  pnl=%+.2f  eq=%.2f",
                 t.strategy, t.symbol, exit_price, reason, pnl, self.state.current_equity)

        if self.shadow_broker is not None:
            try:
                shadow_exit = Order(
                    symbol=t.symbol, side=close_side, qty=t.qty,
                    order_type=OrderType.MARKET, product=Product.INTRADAY,
                    price=exit_price, strategy=t.strategy, is_paper=False,
                )
                if self.shadow_broker._jwt is None:
                    await self.shadow_broker.connect()
                res = await self.shadow_broker.place_order(shadow_exit)
                tag = "SHADOW-DRY" if settings.live_dry_run else "SHADOW-LIVE"
                log.info("%s exit  %s %s qty=%d → %s (%s)",
                         tag, t.symbol, close_side.value, t.qty, res.status.value,
                         res.reject_reason or res.broker_order_id or "ok")
            except Exception as e:
                log.warning("shadow exit failed: %s", e)

    async def _flatten_all(self, reason: str) -> int:
        """Close every open position at current LTP. Returns count closed.

        Reason is persisted as exit_reason. Used by:
          - _eod_scheduler  → reason="eod_flatten"
          - _control_loop FLATTEN message → reason="manual_flatten"
        """
        if not self.open_trades:
            return 0
        await self._refresh_ltps()
        ts = datetime.now(timezone.utc)
        closed = 0
        for key, t in list(self.open_trades.items()):
            ltp = self._ltp_sync(t.symbol)
            if ltp <= 0:
                log.warning("flatten: no LTP for %s, skipping", t.symbol)
                continue
            close_side = OrderSide.SELL if t.side == OrderSide.BUY else OrderSide.BUY
            try:
                await self.broker.place_order(Order(
                    symbol=t.symbol, side=close_side, qty=t.qty,
                    order_type=OrderType.MARKET, product=Product.INTRADAY,
                    price=ltp, strategy=t.strategy,
                ))
            except Exception as e:
                log.exception("flatten: broker exit failed for %s: %s", t.symbol, e)
                continue
            sign = 1 if t.side == OrderSide.BUY else -1
            pnl = (ltp - t.entry_price) * t.qty * sign
            self.state.on_trade_closed(pnl)
            try:
                await self.r.set("titan:consec_losses",
                                 str(self.state.consecutive_losses))
            except Exception:
                pass
            self._persist_close(t, ts, ltp, reason, pnl)
            del self.open_trades[key]
            self.state.open_positions = len(self.open_trades)
            closed += 1
            log.info("FLATTEN %s %s @ %.2f  %s  pnl=%+.2f  eq=%.2f",
                     t.strategy, t.symbol, ltp, reason, pnl,
                     self.state.current_equity)
        return closed

    # ─────────────── background loops ───────────────
    async def _control_loop(self):
        """Consume titan:control channel (FLATTEN published by API /flatten)."""
        pubsub = self.r.pubsub()
        await pubsub.subscribe("titan:control")
        log.info("supervisor subscribed to titan:control")
        while True:
            try:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=5.0)
            except (asyncio.TimeoutError, _redis_sync.exceptions.TimeoutError):
                continue
            if not msg:
                continue
            data = msg.get("data")
            if data == "FLATTEN":
                log.info("control: FLATTEN received")
                try:
                    n = await self._flatten_all("manual_flatten")
                    log.info("control: flattened %d positions", n)
                except Exception as e:
                    log.exception("control: flatten failed: %s", e)

    async def _eod_scheduler(self):
        """Sleep until intraday_square_off IST, then publish FLATTEN.

        Going through the control channel (not calling _flatten_all directly)
        means scheduled and manual flatten share one code path.
        """
        cutoff = settings.intraday_square_off  # time(15, 15) by default
        while True:
            now = datetime.now(IST)
            target = now.replace(hour=cutoff.hour, minute=cutoff.minute,
                                 second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            wait_s = (target - now).total_seconds()
            log.info("eod scheduler: next flatten at %s IST (in %.0fs)",
                     target.strftime("%Y-%m-%d %H:%M"), wait_s)
            try:
                await asyncio.sleep(wait_s)
            except asyncio.CancelledError:
                raise
            try:
                await self.r.publish("titan:control", "FLATTEN")
                log.info("eod scheduler: published FLATTEN at %s IST",
                         datetime.now(IST).strftime("%H:%M:%S"))
            except Exception as e:
                log.exception("eod scheduler: publish failed: %s", e)
            # avoid double-fire within same minute
            await asyncio.sleep(60)

    # ─────────────── entrypoint ───────────────
    async def _bar_loop(self):
        pubsub = self.r.pubsub()
        channels = [f"bars:{s}:{tf}" for s in settings.symbols for tf in TIMEFRAMES]
        await pubsub.subscribe(*channels)
        log.info("supervisor subscribed to %d bar channels", len(channels))
        while True:
            try:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=5.0)
            except (asyncio.TimeoutError, _redis_sync.exceptions.TimeoutError):
                continue
            if not msg:
                continue
            ch = msg["channel"]
            try:
                _, symbol, tf = ch.split(":")
                bar = json.loads(msg["data"])
            except Exception:
                continue
            try:
                await self._on_bar_event(symbol, tf, bar)
            except Exception as e:
                log.exception("on_bar_event failed: %s", e)

    async def run(self):
        await asyncio.gather(
            self._bar_loop(),
            self._control_loop(),
            self._eod_scheduler(),
        )


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(Supervisor().run())


if __name__ == "__main__":
    main()
