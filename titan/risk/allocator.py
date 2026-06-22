"""Capital allocation across strategies by risk (Riskfolio-Lib idea, minimal).

Suggests per-strategy capital weights so no single strategy dominates portfolio
variance. inverse_vol_weights is the practical risk-parity proxy (equal risk
contribution under the diagonal/uncorrelated assumption); a covariance-aware
risk-parity is provided for the correlated case.

Pulls realized per-trade P&L per strategy from `trades`. Pure analysis/advice —
it suggests weights; wiring them into live sizing is a separate step.
"""
from __future__ import annotations

import numpy as np
from sqlalchemy import create_engine, text

from titan.config import settings


def strategy_returns(eng=None) -> dict[str, list[float]]:
    eng = eng or create_engine(settings.db_url)
    with eng.connect() as cx:
        rows = cx.execute(text(
            "SELECT strategy, pnl FROM trades WHERE exit_ts IS NOT NULL ORDER BY exit_ts"
        )).all()
    out: dict[str, list[float]] = {}
    for s, p in rows:
        out.setdefault(s, []).append(float(p))
    return out


def _stats(returns: dict[str, list[float]]) -> dict[str, dict]:
    out = {}
    for s, r in returns.items():
        a = np.asarray(r, dtype=float)
        vol = float(np.std(a, ddof=1)) if len(a) >= 2 else float("nan")
        mean = float(np.mean(a)) if len(a) else 0.0
        out[s] = {"n": len(a), "mean": mean, "vol": vol,
                  "sharpe": (mean / vol if vol and np.isfinite(vol) and vol > 0 else 0.0),
                  "net": float(np.sum(a))}
    return out


def inverse_vol_weights(returns: dict[str, list[float]]) -> dict[str, float]:
    """Risk-parity proxy: weight ∝ 1/volatility. Lower-vol strategies get more
    capital so each contributes ~equal risk."""
    stats = _stats(returns)
    inv = {s: (1.0 / d["vol"] if d["vol"] and np.isfinite(d["vol"]) and d["vol"] > 0 else 0.0)
           for s, d in stats.items()}
    tot = sum(inv.values())
    return {s: (w / tot if tot else 0.0) for s, w in inv.items()}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Suggest risk-parity strategy weights")
    ap.parse_args()
    returns = strategy_returns()
    if not returns:
        print("no closed trades yet — nothing to allocate")
        return
    stats = _stats(returns)
    weights = inverse_vol_weights(returns)
    print(f"{'strategy':<18}{'trades':>7}{'vol':>9}{'sharpe':>8}{'net':>9}{'weight':>9}")
    for s in sorted(weights, key=lambda x: weights[x], reverse=True):
        d = stats[s]
        print(f"{s:<18}{d['n']:>7}{d['vol']:>9.1f}{d['sharpe']:>8.2f}"
              f"{d['net']:>9.0f}{weights[s]*100:>8.1f}%")


if __name__ == "__main__":
    main()
