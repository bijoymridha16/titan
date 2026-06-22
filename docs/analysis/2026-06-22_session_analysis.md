# TITAN — Session Data Analysis · 2026-06-22

> Analysis of the day's captured paper/sim data (the current "2× leverage" run,
> post the 3+1 re-fund). Earlier runs of the day are preserved in
> `~/titan-backups/`. Full raw exports of every table: `~/titan-exports/2026-06-22/`
> (ohlcv, trades, signals, order_attempts, fills, feature_snapshots, equity_curve,
> regime_decisions, risk_events, operator_decisions, universe_selection).
>
> **Frame of reference:** synthetic random-walk feed, 50-symbol dynamic universe,
> 12 strategies under armed auto-pilot, 2× MIS leverage, caps at 100%. Absolute
> P&L is negative by construction (no real edge in a random walk; costs + slippage
> dominate). Read RELATIVE behaviour, not absolute alpha.

---

## 1. Scope captured

| Table | Rows | Notes |
|---|---|---|
| ohlcv | ~261k | 8 sim-days × 50 symbols × {5m,1d} |
| signals | ~8.3k | every signal incl. rejected |
| order_attempts | ~8.0k | every risk decision |
| feature_snapshots | ~8.3k | indicator vectors at decision time |
| trades | 363 | 355 closed / 8 open |
| fills | 363 | with slippage |
| equity_curve | 127 | |
| regime_decisions | ~52 | auto-pilot audit |
| operator_decisions | 24 | my decision journal |
| universe_selection | 61 | the top-50 analysis |
| risk_events | 2 | halt episodes |

Sim span: **2026-06-22 → 06-29 (8 sim-days).**

---

## 2. Headline P&L (355 closed trades)

- **Realized total: −₹51,590** · **win rate 24%** (85 W / 270 L) · avg −₹145/trade
- Best trade +₹773 · worst −₹587 · **equity peaked ₹49,433, ended ≈ −₹1,381** (account drawn to ruin)
- The account hit **both** the daily-loss cap and the max-drawdown halt (it re-ruined even at 2×).

## 3. By strategy (the most useful cut)

| strategy | trades | win% | net ₹ | profit factor |
|---|---|---|---|---|
| **orb_confirmed** | 46 | **61%** | −893 | **0.81** |
| orb | 107 | 39% | −8,150 | 0.62 |
| ma_cross | 25 | 0% | −6,557 | — |
| supertrend_adx | 36 | 0% | −7,821 | — |
| donchian | 85 | 18% | −13,357 | 0.36 |
| momentum | 56 | 0% | −14,812 | — |

**Findings:**
1. **`orb_confirmed` is clearly the best** — 61% win vs raw `orb` 39%, profit factor 0.81 vs 0.62. **The confirmation filter (volume + EMA-slope) materially improves breakout quality** — the strongest signal of the day, and it holds across two runs now.
2. **`ma_cross`, `supertrend_adx`, `momentum` = 0% win.** These ride-until-reverse strategies have **no profit target**, so on a random walk they only ever exit at a stop (or worse). They are pure cost on this feed — prime candidates to **cut or give a target/trailing exit**.
3. **`donchian` worst net (−13,357)** — high trade count × low (18%) win.
4. **The mean-reversion family (vwap_revert, vwap_rsi, rsi_revert, bollinger_revert) made 0 trades** this run — the regime stayed TREND/TRANSITION and, when it briefly hit RANGE, the account was halted. So no RANGE evidence this session (last session showed vwap_revert strong in RANGE).

## 4. By regime & exit reason

| regime | trades | win% | net ₹ |
|---|---|---|---|
| TRANSITION | 117 | 36% | −15,882 |
| TREND | 238 | 18% | −35,708 |

- **Trend-followers lost *in the TREND regime*** — because ADX≥22 tagged random-walk noise as "trend" with no persistent follow-through. Confirms the deterministic ADX gate is fooled by synthetic data (and argues for the HMM/GMM upgrade on real data).
- **Exit reasons: 269 stops (−₹76,063) vs 86 targets (+₹24,473)** — a ~3:1 stop:target count. Strategies get stopped out far more than they reach targets. The wins are too small/rare to cover the stops.

## 5. Execution & funnel

- **Slippage: realized 2.0 bps = modeled 2.0 bps** (paper broker applies the model exactly — clean fills; nothing to flag until real fills).
- **Signal funnel:** 363 accepted vs huge rejections — **3,817 "max drawdown breached" + 2,596 "daily loss cap hit"** (the account spent most of the run halted), plus 586 max-concurrent, 257 position-already-open, 188 insufficient-funds, 75 sizing→0. The halts dominate: once ruined, the vast majority of signals were rejected.
- **Regime decisions:** TREND 28 · RANGE 9 · TRANSITION 6 · CRISIS 6 — the run was trend-dominated; RANGE windows existed but coincided with halts, so the mean-reversion strategies never got to act.

---

## 6. Conclusions

1. **Confirmation filtering works** — `orb_confirmed` > `orb` is the clearest, most repeatable edge in the data. Worth applying the same "confirm the breakout" idea to donchian / bb_squeeze.
2. **No-target trend/momentum strategies are dead weight on this feed** (0% win): `ma_cross`, `supertrend_adx`, `momentum`. Either add a profit target / trailing take-profit, or drop them.
3. **The deterministic ADX regime gate mislabels random-walk noise as TREND** → trend-followers bleed in "TREND". This is the case for probabilistic regime detection (HMM/GMM) — but only meaningful on **real** data.
4. **Risk posture is the binding constraint:** with caps at 100% and no per-trade-quality filter, the losing strategies drained the account even at 2×. To keep a run alive you need **pruning + a real daily-loss cap**, not just lower leverage.
5. **This is all synthetic.** The single most valuable next step remains **real backfilled NIFTY/BANKNIFTY (or NSE-50) history → walk-forward** — only then do these relative signals become tradeable verdicts.

## 7. Recommended next actions (for the optimize phase)

- **Prune** `ma_cross`, `supertrend_adx`, `momentum` (0% win, no target) from the live rotation.
- **Promote the confirmation pattern**: keep `orb_confirmed`; add volume/trend confirmation to `donchian`.
- **Reinstate a real daily-loss cap** (e.g. 2–3%) so a bad day can't wipe the account.
- **Backfill real data** and re-run the whole set through walk-forward before trusting any of this.
- Optional: build the **HMM/GMM regime classifier** (docs/13) for the real-data phase.

*Raw data for independent analysis: `~/titan-exports/2026-06-22/*.csv`. Operator
reasoning trail: `operator_decisions` table / `docs/operator_journal.md`.*
