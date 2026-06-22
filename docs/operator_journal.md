# TITAN — Autonomous Operator Journal

> Narrative log of decisions made by the autonomous operator (Claude) while
> running TITAN in **paper/sim mode**. Structured, queryable mirror lives in the
> Postgres table `operator_decisions` (migration 009). The system itself
> auto-journals every trade, signal, order attempt, fill, and regime decision —
> this file captures the *operator* layer: what I changed, why, and the thinking.
>
> Mandate (2026-06-22): user handed over full autonomous control of the paper
> platform — pick strategies, manage risk, decide buy/sell, create strategies as
> needed — and asked that **every decision be stored with its reasoning** so the
> run can be analysed and the platform optimised afterwards. No real capital is
> at risk: `live_enabled=0`, `dry_run=1`, sim clock + synthetic feed.

---

## Operating principles I'm holding myself to

1. **Capital preservation first, even on paper** — the point is to learn what a
   disciplined operator would do, not to gamble. I keep hard risk gates on.
2. **Log before/with every change** — no silent tweaks. Each entry: what, why,
   thinking, expected effect (a falsifiable hypothesis to check later).
3. **Prefer reversible, observable changes** — small steps, watch the data.
4. **Don't enable live trading** — that's explicitly out of my remit.
5. **Diversify for signal** — run multiple strategies across regimes so the
   collected data lets us compare, not just confirm one edge.

---

## Decision log (newest first)

### 2026-06-22 — Session 1: take over a halted, index-only paper run

Starting state I inherited: universe = NIFTY+BANKNIFTY, caps at full ₹50k,
max 50 positions, **session HALTED on consecutive-loss limit** (3) after a 7-loss
ORB streak (−₹2,258 realised), 27 signals rejected since. Sim was looping but the
halt had latched across ~13 sim-days, so no data was being generated.

Decisions taken this session are recorded in `operator_decisions` (#1 onward) and
summarised here as I make them:

- **#1 — Initialise the operator journal** (table + helper).
- **#2 — Daily halts self-recover per sim-day** (code: `RiskEngine._maybe_roll`).
  Daily counters/halt reset each new trading date; drawdown/weekly persist.
- **#3 — Funds gate uses 5× MIS leverage** (code). Index longs were being
  funds-rejected on the 50k account, biasing the data to shorts; leverage fixes it.
- **#4 — Consecutive-loss limit 3 → 8** (config). 3 was too tight for noisy
  synthetic data; daily-reset prevents latching.
- **#5 — Diversified to orb + vwap_revert + supertrend_adx.** Comparative data
  across breakout / mean-reversion / trend-follow styles. TSMOM stays killed.
- **#6 — Cleared the inherited latched halt** (supervisor restart).
- **#7 — Holding strategy params fixed despite negative P&L.** On synthetic data
  there's no real edge; costs bleed. The deliverable is clean structured data,
  not synthetic profit — real verdicts need a real-data run.

**State after session 1:** session ACTIVE, 3 strategies live, longs now filling,
trades flowing across regimes. All decisions queryable in `operator_decisions`.

### 2026-06-22 — Review #1 (decision #12): no change

Health 6/6, sim at Jul 26 (~32 sim-days, 81 trades, −10,056 realized), session
ACTIVE, auto-pilot governing correctly. **Held all params steady** (mandate: don't
chase synthetic noise / keep data comparable). Reads: vwap_revert now RANGE-confined
and mildly +ve there (+668); supertrend_adx worst at 0/8 win (too small to act);
orb better in TRANSITION than TREND; the streak-limit raise stopped the daily
halting. Watching supertrend_adx until it has ≥20 trades.

### 2026-06-22 — Review #2 (decision #16): no change

Health 6/6, sim ~Aug 7, session ACTIVE, 12 strategies live (10 have traded).
**Held steady.** Headline: vwap_revert in RANGE now strongly +ve (+5483, 25 trades)
— regime-gating validated. supertrend_adx is 0/20 win (−7143), structurally
expected for trend-following on a random walk — flagged, NOT cut (cutting on
synthetic P&L breaks discipline + comparability). New variants still thin
(orb_confirmed 5, vwap_rsi 2, bb_squeeze 0) — need more trades for an A/B verdict.

### 2026-06-22 — Review #3 (decision #18): no change, 50-symbol universe

Health 6/6, dynamic 50-symbol universe live, 48 equities traded, 572 closed
trades. Account healthy: realized −7,876 (~₹42k equity) — the 423 reading was a
stale sim-ts-ordered equity_curve row, not ruin. **Held params.** Strong read:
trailing-stop trend-following (supertrend_adx +48.6k) catches synthetic shock-legs
while fixed-stop crossovers bleed (momentum 0/74, ma_cross 0/52). orb_confirmed
(58% win) and vwap_rsi (50%, +1.3k) edge their baselines — early but promising.
Follow-up noted: latest_equity() orders by sim-ts and can show a stale row — a
display fix for later (realized total is the source of truth).

### 2026-06-22 — Review #4 (decision #22): run STUCK halted — escalating to user

Health 6/6, but the run is HALTED on max-drawdown: realized −45,906 (~₹4k equity),
0 open, **no trades flowing**. A supervisor restart does NOT clear it (peak_equity
rebuilt from equity_curve → drawdown stays breached → re-halts instantly). The 5×
leverage × 50 symbols × 100% caps drained the account to ruin and the experiment
has stalled. **Did not override** the user's explicit loose-caps/leverage choice —
escalated instead. Pre-stall strategy read: orb +2,200 (58%) only winner;
orb_confirmed 60% win (confirmation edge); donchian/momentum/vwap_revert deep
negative. Fix needs a user decision: cut leverage / reinstate caps / re-fund / prune.

### How to review my decisions later
```sql
SELECT ts, category, title, action, rationale, expected
FROM operator_decisions ORDER BY id;
```
Cross-reference with `trades`, `signals`, `fills`, `regime_decisions` over the
same window to test each `expected` hypothesis.
