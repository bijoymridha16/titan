"""Event-driven backtest harness — replays bars through a Strategy + PaperBroker
+ RiskEngine. Same code path as paper trading; the only difference is the bar source.

This is the AUTHORITATIVE backtest. VectorBT (vbt_runner) is for fast sweeps;
its results must always be re-confirmed event-driven before deployment.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import pandas as pd

from titan.brokers.paper import PaperBroker
from titan.execution.router import ExecutionRouter
from titan.risk.engine import RiskEngine, RiskState
from titan.risk.limits import RiskLimits
from titan.strategies.base import Strategy

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    trades: int
    pnl: float
    equity_curve: pd.Series
    rejects: int


async def run_backtest(
    strategy: Strategy,
    bars: pd.DataFrame,
    starting_cash: float = 500_000.0,
    lot_size: int = 1,
    slippage_bps: float = 2.0,
) -> BacktestResult:
    """`bars` indexed by ts ascending, columns o,h,l,c,v."""
    ltp_holder = {"price": float(bars["c"].iloc[0])}
    broker = PaperBroker(cash=starting_cash, ltp_provider=lambda _s: ltp_holder["price"],
                         slippage_bps=slippage_bps)
    limits = RiskLimits.from_settings()
    state = RiskState(starting_equity=starting_cash, peak_equity=starting_cash,
                      current_equity=starting_cash)
    risk = RiskEngine(limits, state, now_fn=lambda: bars.index[-1].to_pydatetime())
    router = ExecutionRouter(broker, risk, lot_size=lot_size)

    rejects = trades = 0
    equity_points: list[tuple[pd.Timestamp, float]] = []

    for i in range(1, len(bars) + 1):
        window = bars.iloc[:i]
        ltp_holder["price"] = float(window["c"].iloc[-1])
        # Patch the risk engine's "now" to the bar time so cutoff checks work.
        risk._now = lambda w=window: w.index[-1].to_pydatetime()

        for sig in strategy.on_bar(window):
            res = await router.submit(sig, strategy.name)
            if res.approved:
                trades += 1
            else:
                rejects += 1

        funds = await broker.get_funds()
        equity_points.append((window.index[-1], funds["equity"]))

    eq = pd.Series({t: v for t, v in equity_points}, name="equity")
    return BacktestResult(trades=trades, pnl=eq.iloc[-1] - starting_cash,
                          equity_curve=eq, rejects=rejects)


def main():
    import argparse
    from titan.data.store import read_bars
    from titan.strategies.orb import OpeningRangeBreakout

    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()

    bars = read_bars(args.symbol, args.tf, args.start, args.end)
    if bars.empty:
        log.error("no bars in window")
        return
    strat = OpeningRangeBreakout(args.symbol)
    res = asyncio.run(run_backtest(strat, bars))
    print(f"trades={res.trades} rejects={res.rejects} pnl={res.pnl:,.2f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
