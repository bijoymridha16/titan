# 12 — New Strategy Candidates

> Date: 2026-06-26. Inputs: the data findings in `docs/11_go_live_readiness.md` §A.
> Each candidate below has an explicit *data hook* (which finding it exploits)
> and a falsifiable *kill criterion*. No candidate ships until it clears the
> walk-forward bar in `walk_forward.py`: ≥30 OOS trades, PF ≥ 1.10, max DD ≤
> 25%, profitable on ≥ 60% of symbols, OOS Sharpe above the deflated bar
> `σ·√(2·lnN)`.

## Status

These are **research candidates**, not production code. None should be added to
`titan/strategies/registry.py` or `TITAN_AUTOPILOT_VALIDATED` until walk-forward
results exist on backfilled real data.

---

## A. Candidates derived directly from the audit

### A1 — `pmr` (Post-Open VWAP Mean-Revert)

**Data hook.** 09:xx lost ₹7,172 over 164 trades (46% win). 10:xx made
₹3,726 over 22 trades (68% win). The opening drive eats mean-reversion logic;
VWAP and σ are noisy in the first ~15 min.

**Logic.**
- Identical to `vwap_revert` SELL leg, but the entry gate requires
  `now ≥ 09:30 IST` AND `len(today_bars) ≥ 6`.
- Target: `vwap - 0.5σ` (already in `vwap_revert` after the 06-26 fix).
- Stop: `entry + 0.8 * atr_14` (tighter than current 1.0 to claw the R ratio
  back above 1).
- SHORT-only (`vwap_revert BUY` has n=5 and no demonstrated edge).

**Why it might work.** The current `vwap_revert` already wins 61% of SELLs;
removing the noisy first 15 min should preserve hit rate while shedding the
worst losers (the cluster-stops at 09:15–09:30).

**Kill criterion.** If walk-forward shows <55% hit rate OR PF <1.20 on a 90-day
replay, abandon. Don't keep tweaking parameters — that's overfitting.

---

### A2 — `orf` (Opening-Range Fade)

**Data hook.** `orb SELL` lost −₹6,897 across 57 trades. The setup (breakout
on the first 15-min range, SHORT on a downside break) is structurally
mis-firing on trend-up days. The *inverse* — fade a breakout that lacks
follow-through — may be the actual edge.

**Logic.**
- Build OR from 09:15–09:30 IST (first 3 × 5m bars).
- Wait for a breakout (close > OR high OR close < OR low) on a 5m bar.
- If breakout has *low volume* (`vol < median(vol_first_3) × 0.8`) OR the next
  bar fails to follow through (`close_{n+1}` returns inside the OR), enter the
  *opposite* side.
- Stop = OR midpoint. Target = far OR edge ± 0.25 × OR width.
- Only fires once per symbol per day.

**Why it might work.** False breakouts are well-documented in NSE-large-cap
literature: open-drive bursts that fizzle by 10:00 IST. The data shows our
ORB-SELL was eating false-breakout-the-wrong-way; ORF would harvest the
correction.

**Kill criterion.** Walk-forward must show PF ≥ 1.30 (higher bar than A1 — this
is a more speculative thesis). If <30 trades fire in a 90-day window, the gate
is too tight; widen the volume filter rather than abandoning.

---

### A3 — `crm` (Crisis Mean-Revert) — *speculative, n=25*

**Data hook.** 25 trades fired with `regime=CRISIS` in our ledger and won 64%
(net +₹826). The selector currently maps `CRISIS → ∅` per `decision/selector.py`,
so CRISIS trades only happen when humans manually enable strategies. The
hypothesis: a high-IV / wide-range regime is *good* for short-term
mean-reversion, contrary to the textbook "stand down in crisis" framing.

**Logic.**
- Same as `pmr` (A1), but only enabled when `regime == CRISIS`.
- Tighter sizing: 0.3% per trade vs the 0.5% baseline (we don't trust the
  signal yet; size for survival, not edge).
- Add a regime-flip guard: if regime exits CRISIS while a position is open,
  flatten immediately rather than waiting for SL/TP.

**Why it might work.** India VIX spikes correlate with widened intraday ranges,
which mechanically increase the distance from VWAP and improve target-hit
probability for mean-revert strategies.

**Kill criterion.** This needs the most validation. **No live deployment until
≥100 walk-forward CRISIS trades exist.** Until then it's a research-only
strategy that runs alongside paper to gather more samples.

---

## B. Literature scan — patterns we haven't tried

These are documented intraday-Indian-equity approaches that fit our pipeline
(5m bars, single-symbol, intraday-flat) and are not yet in the registry. Each
needs a `walk_forward.py` validation before adoption.

### B1 — Gap-fade
- **Setup:** stocks gapping >1% from previous close at the open.
- **Trade:** fade the gap on the first 5m bar (enter against the gap
  direction); target = previous close; stop = 0.5 × gap distance from entry.
- **Evidence basis:** classic equity intraday pattern; documented win rates of
  55–60% on liquid NSE names per multiple back-tested studies.
- **Pipeline fit:** trivial — needs `yesterday_close` from `bars:1d:<sym>` and
  a single gap-trigger check at the first bar.

### B2 — RSI-2 mean-reversion
- **Setup:** 2-period RSI on 5m bars; entry when RSI < 10 (LONG) or > 90 (SHORT).
- **Trade:** exit when RSI returns to 50, or 30-min time-stop, or 1× ATR stop.
- **Evidence basis:** Larry Connors' RSI-2 has been backtested across markets;
  works on liquid intraday because RSI-2 captures genuine short-term overextension.
- **Pipeline fit:** add to `indicators.py` (RSI is trivial), one-file strategy
  identical in shape to `supertrend_adx`.

### B3 — Volume-weighted breakout (VWB)
- **Setup:** breakout above N-bar high *only if* `current_bar_vol > 1.5 ×
  rolling_mean_vol_20`.
- **Trade:** LONG on confirmed breakout; stop = breakout level − 1 × ATR;
  target = entry + 2 × ATR (R:R fixed at 2:1).
- **Why we should try this:** our entire ledger has R<1 because every strategy
  computes target and stop independently. A strategy that *enforces* R≥2 by
  construction is the simplest way to claw expectancy positive.
- **Pipeline fit:** straightforward; uses fields already on every bar dict.

### B4 — Time-decay scratch (TDS) — overlay, not standalone
- **Logic:** any open position that has not moved ±0.5 × ATR within 20 minutes
  is closed at break-even (no SL/TP wait).
- **Why it might pay:** our >60m holds returned +₹271 across 96 trades —
  marginal. The thesis being slow to play out is the same as it being wrong.
  Closing flat instead of waiting for the SL frees capital and avoids the
  slow-bleed scenarios.
- **Pipeline fit:** add to `supervisor._check_exits` as a third branch
  (`stop` / `target` / `scratch`). Affects every strategy uniformly.

---

## C. Cross-cutting framework changes (apply to ALL strategies)

These aren't new algorithms; they're risk/sizing/exit changes that the audit
revealed apply to every strategy in the registry.

1. **R≥1.5 by construction.** In `base.Signal`, validate that
   `|target − entry| ≥ 1.5 × |stop − entry|` at signal-emit time; reject the
   signal otherwise. Stops the current "R=0.93" bug at the source.
2. **Per-symbol-per-side cap.** No re-entry on the same `(symbol, side)`
   within the same trading day. The current ledger shows ITC traded 3× on
   06-25 (net −₹917 from re-entries).
3. **Per-side concurrent cap.** `MAX_CONCURRENT_PER_SIDE = 3`. 06-24's cluster
   of 29 simultaneous opens is the kind of correlated bet that wipes accounts.
4. **No first-bar entries.** Universal `min_today_bars ≥ 6` guard in
   `base.Strategy.on_bar` (today only `vwap_revert` has it after the 06-26
   fix).

---

## D. Recommended next steps

1. Implement the cross-cutting changes in §C — they're framework, not
   strategy, and they help every existing strategy immediately.
2. Code A1 (`pmr`) — it's the smallest delta from existing `vwap_revert`. Run
   walk-forward against the backfilled history (RELIANCE + 10 others) for
   2026-Q1 and 2026-Q2.
3. If A1 ships, then A2 (`orf`) — same vetting bar.
4. A3 (`crm`) and the literature-scan candidates (B1–B4) are research-mode
   only until the cross-cutting fixes are deployed and walk-forward pipeline
   on real data is producing trustworthy verdicts.

---

## E. What we explicitly are NOT building

- **ML-based strategies** (LSTM, transformer, RL). We don't have remotely
  enough data. Premature ML would just overfit the 6 days of paper we have.
- **Options strategies** (straddle, iron condor, etc.). The execution router
  for options isn't built (`docs/10` D1); without it, options are paper-only.
- **Pairs trading / cross-asset.** Out of scope for a single-symbol intraday
  pipeline.
- **News-driven event trading.** The pipeline exists (`titan/news/`) but it's
  read-only today (`would_fire` signals not wired to orders). Adding a NDET
  strategy needs the execution path first, which is its own project.
