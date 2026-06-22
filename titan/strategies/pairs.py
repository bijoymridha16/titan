"""Pairs / statistical-arbitrage over the traded universe.

Scans recent 5m closes for correlated pairs, fits a hedge ratio (β via OLS on
log prices), and computes the spread z-score. A divergence beyond z_entry is a
mean-reversion signal (short the rich leg, long the cheap leg); it exits as the
spread reverts toward 0.

WHY this is a standalone module (not a Strategy.on_bar): pairs need TWO symbols'
series simultaneously, which the per-symbol on_bar(window) interface can't
provide. So this is a scanner/signal engine — trading it live needs a dedicated
pairs runner (or a supervisor extension that feeds paired windows). The
50-symbol dynamic universe is what makes this viable (it was impossible with the
old 2-index universe).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from titan.config import settings


def load_closes(symbols: list[str] | None = None, n: int = 400, eng=None) -> pd.DataFrame:
    """Wide frame: index=ts, columns=symbols, values=5m close. Aligned/ffilled."""
    eng = eng or create_engine(settings.db_url)
    syms = symbols or settings.symbols
    with eng.connect() as cx:
        df = pd.read_sql(text("""
            SELECT ts, symbol, c FROM ohlcv
            WHERE timeframe='5m' AND symbol = ANY(:syms)
              AND ts > now() - interval '60 days'
        """), cx, params={"syms": list(syms)}, parse_dates=["ts"])
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot_table(index="ts", columns="symbol", values="c").sort_index()
    return wide.tail(n).ffill().dropna(axis=1, how="any")


@dataclass
class PairSignal:
    a: str
    b: str
    beta: float
    corr: float
    z: float
    action: str   # "long_a_short_b" | "short_a_long_b" | "flat"


def _beta(la: pd.Series, lb: pd.Series) -> float:
    # OLS slope of la on lb (log prices), no intercept-adjusted via cov/var
    v = np.var(lb)
    return float(np.cov(la, lb)[0, 1] / v) if v > 0 else 1.0


def scan(symbols: list[str] | None = None, n: int = 400, min_corr: float = 0.8,
         lookback: int = 60, z_entry: float = 2.0, z_exit: float = 0.5,
         top: int = 15, eng=None) -> list[PairSignal]:
    """Return the most-correlated pairs with their current spread z-score + action."""
    wide = load_closes(symbols, n=n, eng=eng)
    if wide.shape[1] < 2:
        return []
    rets = np.log(wide).diff().dropna()
    cols = list(wide.columns)
    cand = []
    for a, b in combinations(cols, 2):
        c = float(rets[a].corr(rets[b]))
        if np.isfinite(c) and abs(c) >= min_corr:
            cand.append((a, b, c))
    cand.sort(key=lambda x: abs(x[2]), reverse=True)

    out: list[PairSignal] = []
    for a, b, corr in cand[:top]:
        la, lb = np.log(wide[a]), np.log(wide[b])
        beta = _beta(la, lb)
        spread = la - beta * lb
        win = spread.tail(lookback)
        mu, sd = win.mean(), win.std()
        if not sd or not np.isfinite(sd):
            continue
        z = float((spread.iloc[-1] - mu) / sd)
        if z >= z_entry:
            action = "short_a_long_b"     # a rich relative to b
        elif z <= -z_entry:
            action = "long_a_short_b"
        elif abs(z) <= z_exit:
            action = "flat"
        else:
            action = "hold"
        out.append(PairSignal(a, b, round(beta, 3), round(corr, 3), round(z, 2), action))
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Scan the universe for stat-arb pairs")
    ap.add_argument("--min-corr", type=float, default=0.8)
    ap.add_argument("--z-entry", type=float, default=2.0)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()
    sigs = scan(min_corr=args.min_corr, z_entry=args.z_entry, top=args.top)
    if not sigs:
        print("no qualifying pairs (need ≥2 symbols with enough aligned history)")
        return
    print(f"{'pair':<26}{'corr':>7}{'beta':>8}{'z':>8}  action")
    for s in sigs:
        print(f"{s.a+'/'+s.b:<26}{s.corr:>7}{s.beta:>8}{s.z:>8}  {s.action}")


if __name__ == "__main__":
    main()
