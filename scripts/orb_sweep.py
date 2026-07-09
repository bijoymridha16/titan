"""ORB ADX-threshold sweep on real 5m data.

Runs ORB across {symbol × adx_min} and prints a matrix of OOS metrics. Use to
locate the regime gate that actually pays for itself.

Limitation: symbol universe is restricted to names with >=4000 bars; expand
via `python -m titan.data.backfill --symbols X,Y --timeframe 5m --days 180`
and re-run.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from titan.backtest.engine import load_bars, run_backtest
from titan.strategies.orb import OpeningRangeBreakout


SYMBOLS = ["RELIANCE", "HDFCBANK", "ICICIBANK"]
ADX_GRID = [0.0, 20.0, 25.0]
TARGET_R_GRID = [1.5, 2.0]
DIRECTION_GRID = [("both", False, False), ("longs_only", True, False), ("shorts_only", False, True)]
TIMEFRAME = "5m"


def split(bars, frac=0.7):
    n = len(bars); cut = int(n * frac)
    return bars.iloc[:cut], bars.iloc[cut:]


def main() -> None:
    rows = []
    for sym in SYMBOLS:
        bars = load_bars(sym, TIMEFRAME)
        if bars.empty or len(bars) < 500:
            print(f"# skip {sym}: insufficient bars ({len(bars)})")
            continue
        _, oos = split(bars)
        for adx_min in ADX_GRID:
            for tgt in TARGET_R_GRID:
                for dir_label, longs_only, shorts_only in DIRECTION_GRID:
                    strat = OpeningRangeBreakout(sym, params={
                        "adx_min": adx_min, "target_r": tgt,
                        "longs_only": longs_only, "shorts_only": shorts_only,
                    })
                    res = run_backtest(strat, oos)
                    rows.append({
                        "sym": sym, "adx": adx_min, "tgt": tgt, "dir": dir_label,
                        "n": res.n_trades, "hit": res.hit_rate * 100,
                        "pf": res.profit_factor, "pnl": res.total_pnl,
                        "sharpe": res.sharpe,
                    })

    # Aggregate per (adx, tgt) across symbols
    print(f"\n## OOS per-symbol matrix ({TIMEFRAME})\n")
    print(f"{'sym':<11}{'adx':>5}{'tgt':>5}{'dir':>12}{'n':>5}{'hit%':>7}{'PF':>7}{'PnL':>10}{'Sharpe':>9}")
    for r in rows:
        print(f"{r['sym']:<11}{r['adx']:>5.0f}{r['tgt']:>5.1f}{r['dir']:>12}"
              f"{r['n']:>5}{r['hit']:>7.1f}{r['pf']:>7.2f}"
              f"{r['pnl']:>10.0f}{r['sharpe']:>9.2f}")

    # Aggregate
    print(f"\n## Aggregated across {len(SYMBOLS)} symbols\n")
    print(f"{'adx':>5}{'tgt':>5}{'dir':>12}{'n':>6}{'hit%':>7}{'PF':>7}{'pnl_sum':>10}{'sharpe_avg':>12}")
    from collections import defaultdict
    by_key = defaultdict(list)
    for r in rows:
        by_key[(r["adx"], r["tgt"], r["dir"])].append(r)
    for (adx, tgt, dir_label), lst in sorted(by_key.items()):
        n = sum(r["n"] for r in lst)
        # weighted hit by trade count
        hit_num = sum(r["hit"] * r["n"] for r in lst)
        hit = hit_num / n if n else 0.0
        # PF as weighted avg by trades
        pf_num = sum(r["pf"] * r["n"] for r in lst if r["n"] > 0)
        pf = pf_num / n if n else 0.0
        pnl = sum(r["pnl"] for r in lst)
        sharpe = sum(r["sharpe"] for r in lst) / len(lst)
        print(f"{adx:>5.0f}{tgt:>5.1f}{dir_label:>12}{n:>6}{hit:>7.1f}{pf:>7.2f}"
              f"{pnl:>10.0f}{sharpe:>12.2f}")


if __name__ == "__main__":
    main()
