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

import pandas as pd
import redis as _redis_sync
import redis.asyncio as aioredis
from sqlalchemy import text

from titan.brokers.angelone import AngelOneBroker
from titan.brokers.base import Order, OrderSide, OrderStatus, OrderType, Product
from titan.brokers.paper import PaperBroker
from titan.config import settings
from titan.data.store import engine
from titan.execution.router import ExecutionRouter
from titan.risk.engine import RiskEngine, RiskState
from titan.risk.limits import RiskLimits
from titan.strategies.base import Signal, SignalKind, Strategy
from titan.strategies.orb import OpeningRangeBreakout
from titan.strategies.supertrend_adx import SupertrendADX
from titan.strategies.tsmom import TSMOM
from titan.strategies.vwap_revert import VWAPRevert

log = logging.getLogger(__name__)

STRATEGIES: dict[str, type[Strategy]] = {
    "orb": OpeningRangeBreakout,
    "vwap_revert": VWAPRevert,
    "supertrend_adx": SupertrendADX,
    "tsmom": TSMOM,
}

NON_TRADABLE_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY"}

# subscribe to (universe × timeframe used by strategies). 5m for intraday;
# 1d for TSMOM. Bar writer needs to publish bars:<symbol>:1d on daily close.
TIMEFRAMES = {"5m", "1d"}
WINDOW_BARS = 200


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
        # In synth mode the wall-clock is past the 15:15 cutoff, which would
        # block every order. Override the engine's clock to a mid-session IST
        # time so the rest of the risk checks still apply normally.
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")
        def synth_or_real_now():
            try:
                if self.r_sync.get("titan:mode:synthetic") == "1":
                    return datetime.now(IST).replace(hour=11, minute=0,
                                                     second=0, microsecond=0)
            except Exception: pass
            return datetime.now(IST)
        # sync redis client for synchronous risk-engine clock check
        import redis as _redis_sync
        self.r_sync = _redis_sync.from_url(settings.redis_url, decode_responses=True)
        self.risk = RiskEngine(self.limits, self.state, now_fn=synth_or_real_now)
        self.router = ExecutionRouter(self.broker, self.risk, lot_size=1)

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
                                    entry_price, stop_loss, target, is_paper)
                VALUES (:id, :strat, :sym, :qty, :side, :ets, :ep, :sl, :tg, true)
            """), {"id": t.id, "strat": t.strategy, "sym": t.symbol,
                   "qty": t.qty, "side": t.side.value, "ets": t.entry_ts,
                   "ep": t.entry_price, "sl": t.stop, "tg": t.target})

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

        # 2) run each enabled strategy that matches this tf
        for name in enabled:
            cls = STRATEGIES.get(name)
            if not cls or cls.timeframe != tf:
                continue
            key = (name, symbol)
            inst = self.strategies.get(key) or cls(symbol)
            self.strategies[key] = inst

            window = self._load_window(symbol, tf)
            if window.empty:
                continue
            try:
                sigs = inst.on_bar(window)
            except Exception as e:
                log.exception("%s.on_bar(%s) failed: %s", name, symbol, e)
                continue
            for sig in sigs:
                if sig.kind == SignalKind.EXIT:
                    continue  # exits handled by SL/TP block above
                if sig.symbol in NON_TRADABLE_INDICES:
                    continue  # indices used as regime input only; trade ETFs at this capital
                if (name, symbol) in self.open_trades:
                    continue  # one position per (strategy, symbol)
                await self._open_position(name, sig)

            await self.r.set(f"titan:heartbeat:{name}",
                             datetime.now(timezone.utc).isoformat())

    async def _open_position(self, strategy_name: str, sig: Signal) -> None:
        res = await self.router.submit(sig, strategy_name)
        if not res.approved or not res.order or res.order.status != OrderStatus.FILLED:
            log.info("REJECT %s %s: %s", strategy_name, sig.symbol, res.reason)
            return
        side = OrderSide.BUY if sig.kind == SignalKind.ENTRY_LONG else OrderSide.SELL
        t = OpenTrade(
            id=str(uuid.uuid4()), strategy=strategy_name, symbol=sig.symbol,
            side=side, qty=res.order.qty,
            entry_price=res.order.avg_fill_price, stop=sig.stop, target=sig.target,
            entry_ts=datetime.now(timezone.utc),
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
        ts = datetime.now(timezone.utc)
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
            # paper-execute the exit (opposite side, market)
            close_side = OrderSide.SELL if t.side == OrderSide.BUY else OrderSide.BUY
            o = await self.broker.place_order(Order(
                symbol=t.symbol, side=close_side, qty=t.qty,
                order_type=OrderType.MARKET, product=Product.INTRADAY,
                price=exit_price, strategy=t.strategy,
            ))
            sign = 1 if t.side == OrderSide.BUY else -1
            pnl = (exit_price - t.entry_price) * t.qty * sign
            self.state.on_trade_closed(pnl)
            await self.r.set("titan:consec_losses",
                             str(self.state.consecutive_losses))
            self._persist_close(t, ts, exit_price, reason, pnl)
            del self.open_trades[key]
            self.state.open_positions = len(self.open_trades)
            log.info("CLOSE %s %s @ %.2f  %s  pnl=%+.2f  eq=%.2f",
                     t.strategy, t.symbol, exit_price, reason, pnl,
                     self.state.current_equity)

            # shadow live exit
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
                             tag, t.symbol, close_side.value, t.qty,
                             res.status.value,
                             res.reject_reason or res.broker_order_id or "ok")
                except Exception as e:
                    log.warning("shadow exit failed: %s", e)

    # ─────────────── entrypoint ───────────────
    async def run(self):
        pubsub = self.r.pubsub()
        channels = [f"bars:{s}:{tf}" for s in settings.symbols for tf in TIMEFRAMES]
        await pubsub.subscribe(*channels)
        log.info("supervisor subscribed to %d channels", len(channels))
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


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(Supervisor().run())


if __name__ == "__main__":
    main()
