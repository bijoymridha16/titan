"""Mass walk-forward vetting harness.

Runs every factory variant through the backtester across the universe, applies a
MULTIPLE-TESTING correction, and writes a leaderboard. This is the gate that
turns "59 candidate strategies" into "the 1–3 that might actually work".

Why the correction matters (docs/09 P3): test 59 strategies and the best will
look great on any single dataset purely by luck. We guard against that two ways:
  1. Deflated Sharpe — the OOS Sharpe must exceed the level the BEST of N trials
     would reach by chance alone (≈ σ·√(2·lnN)).
  2. Persistence — the edge must hold on a MAJORITY of universe symbols, not one.
Plus predeclared minimums (trades, profit factor, max drawdown). All predeclared,
no tuning after the fact.

Run:
    python -m titan.backtest.walk_forward            # all symbols, 5m
    python -m titan.backtest.walk_forward --max-symbols 2 --tf 5m
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import text

from titan.backtest.engine import load_bars, run_backtest
from titan.config import settings
from titan.data.store import engine
from titan.strategies.factory import VariantSpec, all_variants

log = logging.getLogger(__name__)

# ── predeclared ship/kill thresholds (DO NOT tune to pass) ──
MIN_TRADES = 30
MIN_PROFIT_FACTOR = 1.10
MAX_DRAWDOWN_PCT = 25.0
MIN_SYMBOLS_PROFITABLE_FRAC = 0.60
ANN = 252


def deflated_sharpe_threshold(n_trials: int, n_obs: int, ann: int = ANN) -> float:
    """The OOS Sharpe a no-skill strategy is expected to reach as the BEST of
    `n_trials` independent trials, given `n_obs` return observations.
    σ_SR ≈ √(ann / n_obs);  E[max of N] ≈ σ_SR · √(2·ln N)."""
    if n_obs < 5:
        return math.inf
    sigma_sr = math.sqrt(ann / n_obs)
    return sigma_sr * math.sqrt(2.0 * math.log(max(n_trials, 2)))


@dataclass
class VariantScore:
    key: str
    family: str
    params: dict
    trades: int = 0
    net_pnl: float = 0.0
    sharpe: float = 0.0
    profit_factor: float = 0.0
    max_dd_pct: float = 0.0
    symbols_tested: int = 0
    symbols_profitable: int = 0
    n_obs: int = 0
    deflated_threshold: float = 0.0
    passed: bool = False
    verdict: str = "KILL"
    reasons: list = field(default_factory=list)


def _score_variant(spec: VariantSpec, symbols: list[str], tf: str,
                   n_trials: int, max_bars: int | None = None) -> VariantScore:
    vs = VariantScore(key=spec.key, family=spec.family, params=dict(spec.params))
    sharpes, pfs, dds, weights = [], [], [], []
    for sym in symbols:
        bars = load_bars(sym, tf)
        if max_bars:
            bars = bars.tail(max_bars)
        if len(bars) < 80:
            continue
        res = run_backtest(spec.cls(sym, dict(spec.params)), bars)
        if res.n_trades == 0:
            vs.symbols_tested += 1
            continue
        vs.symbols_tested += 1
        vs.trades += res.n_trades
        vs.net_pnl += res.total_pnl
        vs.n_obs += len(res.equity)
        if res.total_pnl > 0:
            vs.symbols_profitable += 1
        sharpes.append(res.sharpe); weights.append(res.n_trades)
        pfs.append(min(res.profit_factor, 10.0)); dds.append(res.max_dd_pct)
    if weights:
        w = np.array(weights, dtype=float)
        vs.sharpe = float(np.average(sharpes, weights=w))
        vs.profit_factor = float(np.average(pfs, weights=w))
        vs.max_dd_pct = float(max(dds))
    vs.deflated_threshold = deflated_sharpe_threshold(n_trials, max(vs.n_obs, 1))

    # ── gate (all must pass) ──
    sym_frac = (vs.symbols_profitable / vs.symbols_tested) if vs.symbols_tested else 0.0
    checks = [
        (vs.trades >= MIN_TRADES, f"trades {vs.trades}≥{MIN_TRADES}"),
        (vs.sharpe > vs.deflated_threshold,
         f"sharpe {vs.sharpe:.2f}>deflated {vs.deflated_threshold:.2f}"),
        (vs.profit_factor >= MIN_PROFIT_FACTOR, f"PF {vs.profit_factor:.2f}≥{MIN_PROFIT_FACTOR}"),
        (vs.max_dd_pct <= MAX_DRAWDOWN_PCT, f"DD {vs.max_dd_pct:.1f}≤{MAX_DRAWDOWN_PCT}"),
        (sym_frac >= MIN_SYMBOLS_PROFITABLE_FRAC,
         f"persistence {sym_frac:.0%}≥{MIN_SYMBOLS_PROFITABLE_FRAC:.0%}"),
    ]
    vs.passed = all(ok for ok, _ in checks)
    vs.verdict = "SHIP" if vs.passed else "KILL"
    vs.reasons = [msg for ok, msg in checks if not ok] or ["all gates passed"]
    return vs


def _persist(scores: list[VariantScore]) -> None:
    try:
        with engine().begin() as cx:
            cx.execute(text("DELETE FROM leaderboard"))
            for s in scores:
                cx.execute(text("""
                    INSERT INTO leaderboard
                      (variant_key, family, params, trades, net_pnl, sharpe,
                       deflated_threshold, profit_factor, max_dd_pct,
                       symbols_tested, symbols_profitable, passed, verdict, reasons)
                    VALUES (:k,:f,:p,:t,:np,:sh,:dt,:pf,:dd,:st,:sp,:ps,:v,:rs)
                """), {
                    "k": s.key, "f": s.family, "p": json.dumps(s.params),
                    "t": s.trades, "np": round(s.net_pnl, 2), "sh": round(s.sharpe, 4),
                    "dt": round(s.deflated_threshold, 4), "pf": round(s.profit_factor, 4),
                    "dd": round(s.max_dd_pct, 4), "st": s.symbols_tested,
                    "sp": s.symbols_profitable, "ps": s.passed, "v": s.verdict,
                    "rs": "; ".join(s.reasons),
                })
    except Exception as e:
        log.warning("persist leaderboard failed (run migration 007?): %s", e)


def vet_all(symbols: list[str] | None = None, tf: str = "5m",
            max_bars: int | None = None) -> list[VariantScore]:
    symbols = symbols or settings.symbols
    variants = all_variants()
    n = len(variants)
    log.info("vetting %d variants × %d symbols on %s (max_bars=%s) …",
             n, len(symbols), tf, max_bars)
    scores = [_score_variant(v, symbols, tf, n_trials=n, max_bars=max_bars)
              for v in variants]
    scores.sort(key=lambda s: (s.passed, s.sharpe), reverse=True)
    _persist(scores)
    return scores


def promote(survivors: list[VariantScore]) -> set[str]:
    """Write SHIP survivors to the Redis validated allowlist so the auto-pilot
    can arm them — closing the manual promotion gap. Returns the promoted set."""
    import redis as _redis
    from titan.decision.selector import VALIDATED_KEY
    r = _redis.from_url(settings.redis_url, decode_responses=True)
    keys = {s.key for s in survivors}
    pipe = r.pipeline()
    pipe.delete(VALIDATED_KEY)
    if keys:
        pipe.sadd(VALIDATED_KEY, *keys)
    pipe.execute()
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--max-symbols", type=int, default=None)
    ap.add_argument("--max-bars", type=int, default=None,
                    help="use only the most recent N bars per symbol (speed)")
    ap.add_argument("--promote", action="store_true",
                    help="write SHIP survivors to the Redis validated allowlist")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    syms = settings.symbols[: args.max_symbols] if args.max_symbols else settings.symbols
    scores = vet_all(syms, args.tf, max_bars=args.max_bars)
    survivors = [s for s in scores if s.passed]
    print(f"\n── vetting complete: {len(survivors)}/{len(scores)} SHIP ──")
    print(f"{'variant':32} {'fam':14} {'trades':>6} {'sharpe':>7} "
          f"{'defl':>6} {'PF':>5} {'DD%':>6} {'verdict':>7}")
    for s in scores[:20]:
        print(f"{s.key[:32]:32} {s.family[:14]:14} {s.trades:6d} {s.sharpe:7.2f} "
              f"{s.deflated_threshold:6.2f} {s.profit_factor:5.2f} {s.max_dd_pct:6.1f} "
              f"{s.verdict:>7}")
    if survivors:
        print("\nSurvivors → validated allowlist:")
        print("  " + ",".join(s.key for s in survivors))
        if args.promote:
            promoted = promote(survivors)
            print(f"\n✅ promoted {len(promoted)} strategies to the Redis validated "
                  "allowlist — auto-pilot can now arm them.")
    else:
        print("\nNo survivors — expected when running on synthetic/thin data. "
              "The GATE works; feed it real history to find real edges.")
        if args.promote:
            promote([])  # clears the allowlist — nothing earned a live slot
            print("Cleared the validated allowlist (no survivors).")


if __name__ == "__main__":
    main()
