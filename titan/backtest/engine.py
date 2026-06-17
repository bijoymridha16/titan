"""Event-loop backtester.

Same Strategy.on_bar() interface as paper + live. Replays historical bars from
Postgres one at a time, lets the strategy emit signals, fills them at next-bar
open with realistic costs (brokerage + STT + GST + slippage), tracks an equity
curve, returns a structured result.

Deliberately simple. No look-ahead. No vectorisation magic. The same code path
the live system runs through, just driven by a pandas frame instead of a
Redis pub/sub.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from titan.data.store import engine
from titan.strategies.base import Signal, SignalKind, Strategy

log = logging.getLogger(__name__)


# ──────────────── costs model (matches PaperBroker / Angel One cash MIS) ────────────────
def round_trip_cost(notional: float) -> float:
    """Approximate cost for one MIS round-trip on equity cash on Angel One."""
    brokerage = min(20.0, 0.0003 * notional) * 2          # both legs
    stt       = 0.00025 * notional                         # sell side only
    exch      = 0.0000345 * notional * 2
    gst       = 0.18 * (brokerage + exch)
    sebi      = 0.000001 * notional * 2
    stamp     = 0.00003 * notional                         # buy side only
    return brokerage + stt + exch + gst + sebi + stamp


@dataclass
class BTTrade:
    symbol: str
    entry_ts: pd.Timestamp
    exit_ts: Optional[pd.Timestamp]
    side: str           # LONG / SHORT
    qty: int
    entry_px: float
    exit_px: Optional[float]
    stop: float
    target: Optional[float]
    pnl_gross: float = 0.0
    costs: float = 0.0
    pnl_net: float = 0.0
    exit_reason: str = ""
    bars_held: int = 0


@dataclass
class BTResult:
    trades: list[BTTrade] = field(default_factory=list)
    equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    starting_equity: float = 0.0
    ending_equity: float = 0.0
    symbol: str = ""

    # metrics filled by .summarize()
    n_trades: int = 0
    hit_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    total_costs: float = 0.0
    max_dd_pct: float = 0.0
    sharpe: float = 0.0
    cagr: float = 0.0
    avg_bars_held: float = 0.0
    exposure_pct: float = 0.0   # % of days holding a position

    def summarize(self) -> "BTResult":
        if not self.trades:
            return self
        pnls = np.array([t.pnl_net for t in self.trades])
        self.n_trades = len(pnls)
        self.total_pnl = float(pnls.sum())
        self.total_costs = float(sum(t.costs for t in self.trades))
        wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
        self.hit_rate = float(len(wins) / self.n_trades) if self.n_trades else 0.0
        self.avg_win = float(wins.mean()) if len(wins) else 0.0
        self.avg_loss = float(losses.mean()) if len(losses) else 0.0
        gross_w = float(wins.sum()) if len(wins) else 0.0
        gross_l = -float(losses.sum()) if len(losses) else 1e-9
        self.profit_factor = gross_w / gross_l if gross_l > 0 else math.inf
        self.avg_bars_held = float(np.mean([t.bars_held for t in self.trades]))
        # equity-curve metrics
        if not self.equity.empty:
            eq = self.equity.values
            peak = np.maximum.accumulate(eq)
            dd = (eq - peak) / peak
            self.max_dd_pct = float(-dd.min() * 100)
            rets = pd.Series(eq).pct_change().dropna()
            ann = 252  # daily eq curve
            self.sharpe = float((rets.mean() / (rets.std() + 1e-12)) * math.sqrt(ann)) if len(rets) else 0.0
            days = max(1, len(eq))
            years = days / 252
            self.cagr = (float((eq[-1] / eq[0]) ** (1 / years) - 1)
                         if years > 0 and eq[0] > 0 and eq[-1] > 0 else -1.0)
            # exposure = bars in a trade / total bars (rough proxy)
            held = sum(t.bars_held for t in self.trades)
            self.exposure_pct = float(min(1.0, held / max(1, days)) * 100)
        return self

    def to_markdown(self) -> str:
        rows = [
            ("Symbol",          self.symbol),
            ("Trades",          self.n_trades),
            ("Hit rate",        f"{self.hit_rate*100:.1f}%"),
            ("Avg win",         f"₹{self.avg_win:+.2f}"),
            ("Avg loss",        f"₹{self.avg_loss:+.2f}"),
            ("Profit factor",   f"{self.profit_factor:.2f}"),
            ("Total P&L (net)", f"₹{self.total_pnl:+.2f}"),
            ("Total costs",     f"₹{self.total_costs:.2f}"),
            ("Max drawdown",    f"{self.max_dd_pct:.2f}%"),
            ("Sharpe (daily)",  f"{self.sharpe:.2f}"),
            ("CAGR",            f"{self.cagr*100:+.2f}%"),
            ("Avg bars held",   f"{self.avg_bars_held:.1f}"),
            ("Exposure",        f"{self.exposure_pct:.1f}%"),
            ("Equity",          f"₹{self.starting_equity:.0f} → ₹{self.ending_equity:.2f}"),
        ]
        w = max(len(k) for k, _ in rows)
        lines = [f"  {k.ljust(w)}  {v}" for k, v in rows]
        return "\n".join(lines)


def load_bars(symbol: str, tf: str,
              start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    sql = "SELECT ts,o,h,l,c,v FROM ohlcv WHERE symbol=:s AND timeframe=:tf"
    params: dict = {"s": symbol, "tf": tf}
    if start:
        sql += " AND ts >= :start"; params["start"] = start
    if end:
        sql += " AND ts <= :end";   params["end"] = end
    sql += " ORDER BY ts ASC"
    with engine().connect() as cx:
        df = pd.read_sql(text(sql), cx, params=params,
                         parse_dates=["ts"], index_col="ts")
    for col in ("o", "h", "l", "c"):
        df[col] = df[col].astype(float)
    df["v"] = df["v"].fillna(0).astype(int)
    return df


def run_backtest(strategy: Strategy, bars: pd.DataFrame,
                 starting_equity: float = 5000.0,
                 max_position_pct: float = 1.0,
                 warmup_bars: int = 60,
                 slippage_bps: float = 5.0,
                 window_bars: int = 250,
                 leverage: float = 5.0) -> BTResult:
    """Event-loop backtest. Strategy emits ENTRY_LONG/SHORT → fill at next bar open.
    Exit on signal flip, SL, or TP.

    `window_bars` bounds the trailing history handed to on_bar() each step — this
    matches what the live supervisor does (it passes the last 200 bars) and keeps
    the backtest O(n·window) instead of O(n²) on long series."""
    res = BTResult(symbol=strategy.symbol, starting_equity=starting_equity)
    if len(bars) < warmup_bars + 2:
        log.warning("not enough bars (%d) to backtest %s", len(bars), strategy.symbol)
        return res.summarize()

    equity = starting_equity
    equity_series: list[tuple[pd.Timestamp, float]] = []
    open_trade: Optional[BTTrade] = None

    ruined = False
    for i in range(warmup_bars, len(bars) - 1):
        window = bars.iloc[max(0, i + 1 - window_bars): i + 1]
        bar = bars.iloc[i]
        next_bar = bars.iloc[i + 1]

        # ── 1) exit handling on the just-closed bar (SL / TP intra-bar) ──
        if open_trade is not None:
            open_trade.bars_held += 1
            h, l, c = float(bar["h"]), float(bar["l"]), float(bar["c"])
            ex_px = None; reason = ""
            if open_trade.side == "LONG":
                if l <= open_trade.stop:
                    ex_px, reason = open_trade.stop, "stop"
                elif open_trade.target and h >= open_trade.target:
                    ex_px, reason = open_trade.target, "target"
            else:  # SHORT
                if h >= open_trade.stop:
                    ex_px, reason = open_trade.stop, "stop"
                elif open_trade.target and l <= open_trade.target:
                    ex_px, reason = open_trade.target, "target"
            if ex_px is not None:
                _close_trade(open_trade, bar.name, ex_px, reason, slippage_bps)
                equity += open_trade.pnl_net
                res.trades.append(open_trade)
                open_trade = None
                if equity <= 0:   # ruin: account blown, stop trading
                    equity = 0.0
                    ruined = True

        if ruined:
            equity_series.append((bar.name, 0.0))
            continue

        # ── 2) ask strategy for signals ──
        try:
            signals = strategy.on_bar(window)
        except Exception as e:
            log.warning("on_bar failed at %s: %s", bar.name, e)
            signals = []

        # ── 3) act on first actionable signal ──
        for sig in signals:
            if sig.kind == SignalKind.EXIT and open_trade is not None:
                _close_trade(open_trade, bar.name, float(bar["c"]),
                             "signal_exit", slippage_bps)
                equity += open_trade.pnl_net
                res.trades.append(open_trade)
                open_trade = None
                break
            if sig.kind in (SignalKind.ENTRY_LONG, SignalKind.ENTRY_SHORT) and open_trade is None:
                is_long = sig.kind == SignalKind.ENTRY_LONG
                # size by risk: at most max_position_pct of equity, also bounded
                # by per-trade risk (1% of equity) / per-unit risk
                per_unit = sig.per_unit_risk
                risk_budget = 0.01 * equity
                qty_risk = int(risk_budget / per_unit) if per_unit > 0 else 0
                # margin cap: notional ≤ equity × leverage (MIS-style), so a single
                # position can't be sized beyond what the account could carry.
                qty_pos = int((equity * min(max_position_pct, 1.0) * leverage) / sig.entry)
                qty = max(1, min(qty_risk, qty_pos))
                # fill at NEXT bar open (no look-ahead); slippage against direction
                slip = (1 + slippage_bps / 1e4) if is_long else (1 - slippage_bps / 1e4)
                fill_px = float(next_bar["o"]) * slip
                open_trade = BTTrade(
                    symbol=strategy.symbol,
                    entry_ts=next_bar.name,
                    exit_ts=None,
                    side="LONG" if is_long else "SHORT", qty=qty,
                    entry_px=fill_px, exit_px=None,
                    stop=sig.stop, target=sig.target,
                )
                break

        equity_series.append((bar.name, equity + _unrealized(open_trade, float(bar["c"]))))

    # ── flatten any open trade at the last bar's close ──
    if open_trade is not None:
        last = bars.iloc[-1]
        _close_trade(open_trade, last.name, float(last["c"]),
                     "end_of_data", slippage_bps)
        equity += open_trade.pnl_net
        res.trades.append(open_trade)
        equity_series.append((last.name, equity))

    res.equity = pd.Series(dict(equity_series))
    res.ending_equity = float(equity)
    return res.summarize()


def _unrealized(t: Optional[BTTrade], px: float) -> float:
    if t is None: return 0.0
    sign = 1 if t.side == "LONG" else -1
    return (px - t.entry_px) * t.qty * sign


def _close_trade(t: BTTrade, ts, px: float, reason: str, slip_bps: float) -> None:
    fill = px * (1 - slip_bps / 1e4) if t.side == "LONG" else px * (1 + slip_bps / 1e4)
    sign = 1 if t.side == "LONG" else -1
    t.exit_ts = ts
    t.exit_px = fill
    t.exit_reason = reason
    t.pnl_gross = (fill - t.entry_px) * t.qty * sign
    t.costs = round_trip_cost((t.entry_px + fill) / 2 * t.qty)
    t.pnl_net = t.pnl_gross - t.costs
