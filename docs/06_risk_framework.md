# 06 — Risk framework

Implementation: `titan/risk/` (engine.py, sizing.py, limits.py).
Tests: `tests/test_risk_engine.py`, `tests/test_sizing.py`.

> **Principle.** Risk management is more important than entry signals.
> A great strategy with bad risk loses money; a mediocre strategy with
> tight risk survives. Surviving long enough is the actual job.

## Capital + caps (₹5L baseline)

| Cap | Default | Why |
|---|---|---|
| Per-trade risk | 1.0% = ₹5,000 | Tradeable expectancy at ~20–40 trades/month without single-trade ruin. |
| Daily loss | 2.0% = ₹10,000 | One bad day ≠ recoverable in one good day; halts force a reset. |
| Weekly loss | 5.0% = ₹25,000 | Catches regime shifts strategy by strategy is too slow to notice. |
| Max drawdown | 10.0% = ₹50,000 | Kill switch trips here. Below 10% the system is "having a rough week"; at 10% something is structurally wrong. |
| Consecutive losses | 5 | Halves size at 3 (manual override only), halts at 5. |
| Concurrent positions | 3 | Correlation-budget heuristic; not a substitute for real correlation gating, which is a TODO. |
| Intraday square-off | 15:15 IST | 15 minutes before NSE close to avoid auction & freeze qty issues. |

All caps live in `.env` / `RiskLimits.from_settings()`. Changing them requires
an explicit deploy — there is no UI knob, by design.

## Per-trade sizing

Two modes, both implemented:

- **Fixed fractional** (`sizing.fixed_fractional_qty`):
  `qty = floor( equity * risk% / |entry - stop| )` floored to `lot_size`.
- **ATR** (`sizing.atr_position_size`):
  `qty = floor( equity * risk% / (atr * atr_mult) )`.

Choose ATR when stops are derived from a volatility model (Supertrend);
choose fixed-fractional when stops are structural (OR levels, prior swing).

`fixed_fractional_qty(500_000, 1.0, entry=100, stop=90) == 500` ← verified
in `test_fixed_fractional_basic`.

## Halt taxonomy

When the engine returns `RiskDecision.approved=False`, it records the
reason and sets `state.halted_today=True`. The halt is **sticky for the
calendar day** (process restart doesn't clear it — Redis flag persists).

| Reason | Recovery |
|---|---|
| `daily loss cap hit` | next trading day, automatic |
| `weekly loss cap hit` | next Monday |
| `max drawdown breached` | manual review, restart, smaller size |
| `consecutive loss limit` | next trading day; review trades first |
| `kill switch active` | manual `redis-cli DEL titan:kill` after RCA |

## System risk (not P&L risk)

These exist as code paths even if no trade is in flight:

- **Broker disconnect.** Reconciler emits `risk:broker_drift` event; strategy
  supervisor flattens or halts based on policy.
- **Feed gap.** If no tick for `symbol` > 5s during market hours, mark stale;
  signals on stale data are ignored.
- **Order ack timeout.** If broker doesn't ack within 3s, cancel locally,
  emit `order:ack_timeout`, halt strategy.
- **Kill switch.** Single key (`titan:kill`). FastAPI `/kill` flips it.
  Every order checks it.

## What this does NOT cover

- **Correlation budget.** Three correlated longs ≠ three positions worth of
  risk — they're approximately one. TODO before scaling: compute rolling
  intraday correlation across the active universe and reject opens that
  push correlated-net-exposure past `2 × max_concurrent_positions × R`.
- **Vega/Gamma caps** for option positions. Only delta-equivalent qty is
  capped today. Required before any option-selling strategy goes live.
- **Tail / black-swan.** SL only fires if the market reaches the level.
  Gap-down through a stop is unhedged. Mitigation: caps on overnight
  exposure (TODO when extending past intraday).

## Validation

`pytest tests/test_risk_engine.py tests/test_sizing.py` — 21 tests covering
every reject path, the shrink-to-cap logic, sticky halt, drawdown tracking,
consecutive-loss counter, and pre-market / post-cutoff windows. All pass.
