"""Run ORB, VWAPRevert, SupertrendADX on the same real 5m data and compare
against the same predeclared ship/kill thresholds. Honest head-to-head.

PREREQUISITE: real 5m bars backfilled for RELIANCE, HDFCBANK, ICICIBANK.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from titan.backtest.engine import load_bars, run_backtest
from titan.strategies.orb import OpeningRangeBreakout
from titan.strategies.vwap_revert import VWAPRevert
from titan.strategies.supertrend_adx import SupertrendADX


SYMBOLS = ["RELIANCE", "HDFCBANK", "ICICIBANK"]
STRATEGIES = {
    "orb":            OpeningRangeBreakout,
    "vwap_revert":    VWAPRevert,
    "supertrend_adx": SupertrendADX,
}
CAPITAL = 50_000.0

THRESHOLDS = [
    ("OOS Sharpe ≥ 0.6",     lambda m: m["sharpe"] >= 0.6,     "{sharpe:.2f}"),
    ("Max DD ≤ 15%",         lambda m: m["max_dd"] <= 15,      "{max_dd:.1f}%"),
    ("Hit rate ≥ 35%",       lambda m: m["hit_rate"] >= 0.35,  "{hit_pct:.1f}%"),
    ("Profit factor ≥ 1.10", lambda m: m["pf"] >= 1.10,        "{pf:.2f}"),
    ("Avg bars held ≥ 1",    lambda m: m["bars_held"] >= 1,    "{bars_held:.1f}"),
]


def split70(bars):
    cut = int(len(bars) * 0.70)
    return bars.iloc[:cut], bars.iloc[cut:]


def evaluate(strategy_cls):
    oos_runs = []
    is_runs = []
    for sym in SYMBOLS:
        full = load_bars(sym, "5m")
        if full.empty:
            continue
        is_b, oos_b = split70(full)
        is_runs.append(run_backtest(strategy_cls(sym), is_b, starting_equity=CAPITAL))
        oos_runs.append(run_backtest(strategy_cls(sym), oos_b, starting_equity=CAPITAL))
    return is_runs, oos_runs


def summarize(runs):
    runs = [r for r in runs if r.n_trades > 0]
    if not runs:
        return None
    sharpes = [r.sharpe for r in runs]
    return {
        "trades":     sum(r.n_trades for r in runs),
        "pnl":        sum(r.total_pnl for r in runs),
        "costs":      sum(r.total_costs for r in runs),
        "sharpe":     sum(sharpes) / len(sharpes),
        "max_dd":     sum(r.max_dd_pct for r in runs) / len(runs),
        "hit_rate":   sum(r.hit_rate for r in runs) / len(runs),
        "hit_pct":    sum(r.hit_rate for r in runs) / len(runs) * 100,
        "pf":         sum(min(r.profit_factor, 10) for r in runs) / len(runs),
        "bars_held":  sum(r.avg_bars_held for r in runs) / len(runs),
    }


def main():
    print(f"\n{'='*80}\n"
          f"Strategy comparison @ ₹{CAPITAL:,.0f} capital · real 5m NSE data · 3 symbols\n"
          f"{'='*80}\n")
    header = ("strategy", "trades", "PnL", "costs", "Sharpe", "max DD", "hit", "PF", "verdict")
    print(f"{header[0]:<16} {header[1]:>7} {header[2]:>10} {header[3]:>9} "
          f"{header[4]:>7} {header[5]:>7} {header[6]:>6} {header[7]:>6} {header[8]:>8}")
    print("-" * 80)
    rows = []
    for name, cls in STRATEGIES.items():
        _is, oos = evaluate(cls)
        m = summarize(oos)
        if m is None:
            print(f"{name:<16} (no OOS trades)")
            continue
        passes = [check(m) for _, check, _ in THRESHOLDS]
        verdict = "SHIP" if all(passes) else "KILL"
        print(f"{name:<16} {m['trades']:>7} ₹{m['pnl']:>+9.0f} ₹{m['costs']:>+8.0f} "
              f"{m['sharpe']:>7.2f} {m['max_dd']:>6.1f}% {m['hit_pct']:>5.1f}% "
              f"{m['pf']:>6.2f} {verdict:>8}")
        rows.append((name, m, passes, verdict))

    print()
    for name, m, passes, verdict in rows:
        print(f"\n{name} — {verdict}")
        for (label, _, fmt), ok in zip(THRESHOLDS, passes):
            print(f"  {'✅' if ok else '❌'} {label} — actual " + fmt.format(**m))


if __name__ == "__main__":
    main()
