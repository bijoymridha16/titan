# 13 — Triage of the External (Gemini) Strategy Analysis

> Operator assessment of `docs/Project Insights Analysis and Strategy
> Development.md` (Gemini, 2026-06-22). What to adopt, what to defer, what's
> out-of-scope — and the one trap to avoid. Companion to `docs/12` (strategy
> guide) and `docs/operator_journal.md`.

---

## What the report gets right (adopt the *insight*)

- **Regime-gating is validated.** Its read matches ours: VWAP-revert only works in
  RANGE; strategies bleed when run in the wrong regime. Keep the auto-pilot lane.
- **VWAP stop is too tight** (30 stops vs 7 targets) — a *structural* observation
  (a 1×ATR stop fights the micro-volatility that precedes reversion), not just a
  synthetic artifact. Worth testing a wider stop + entry confirmation.
- **ORB triggers naively** on the first close beyond the range → false-breakout
  prone. A confirmation filter (volume / EMA-slope / VWAP side) is sound.
- **Static ADX thresholds are brittle.** True. Probabilistic regime detection
  (HMM/GMM) is a real upgrade over a hard `ADX≥22` line.
- **Costs/slippage discipline & WFA-before-promotion.** Already our doctrine.

## ⚠️ The trap (why I will NOT just apply its parameter prescriptions)

The report derives specific numbers — "widen VWAP stop to 2.5×ATR", "tighten ADX
to 25", "ORB best in TRANSITION" — **from behaviour on a synthetic random walk
with no real edge.** Tuning live params to fit synthetic artifacts is exactly the
noise-chasing I committed to avoid (operator decisions #7, #12). **Structural**
ideas (add a confirmation filter; use probabilistic regimes) are data-independent
and safe to build; **specific parameter values** must be earned on backfilled
**real** data via walk-forward — not adopted from this report.

Also several recommendations quietly assume infrastructure we don't have, or
conflict with the current config — flagged per item below.

---

## The 10 proposed strategies — triaged

| # | Proposal | Verdict | Why |
|---|---|---|---|
| 1 | Multi-timeframe ORB + confirmation (vol/EMA/VWAP/Fib) | **Build (new variant)** | Confirmation filter is structurally sound; add as a *new* ORB variant, don't mutate live ORB (keeps data comparable). Skip the Fib/SMC discretion. |
| 2 | ATR-optimized VWAP-revert + RSI-divergence | **Build (new variant)** | Wider stop + entry confirmation is sound; add as a variant, validate stop width on real data. |
| 3 | Supertrend+ADX, tighten ADX→25 | **Defer-tune** | The idea (stronger trend filter) is fine; the value 25 is synthetic-derived. Sweep on real data. |
| 4 | Donchian breakout + GARCH vol-sizing | **Activate base / defer GARCH** | Donchian family already in the library — activate for comparative data. GARCH sizing = separate, later. |
| 5 | RSI-divergence reversion | **Activate base** | RSI family in library; divergence logic is a worthwhile new variant. |
| 6 | Bollinger squeeze (BBW expansion) | **Build (new variant)** | Genuinely new (squeeze ≠ the current Bollinger-revert); good RANGE→TREND transition play. |
| 7 | Cross-sectional momentum (rank a universe) | **Out-of-scope now** | Needs a broad equity universe; we deliberately restricted to NIFTY+BANKNIFTY. Revisit if universe widens. |
| 8 | Regime-adaptive MA matrix (Heikin-Ashi) | **Activate base** | MA-crossover family in library; HA smoothing is a nice variant. |
| 9 | High-IV option writing / Iron Condors | **Blocked** | Requires the options-routing layer (not built) + real options/IV data. This is the Track-B / G1 dependency. Real money risk shape — do not attempt on this plumbing. |
| 10 | Multi-strategy convexity / correlation allocator | **Defer (good, bigger)** | Real value once we have several working strategies + real returns to correlate. Build after a real-data run. |

## Regime engine: HMM / GMM

A legitimate upgrade over static thresholds. But: it adds `hmmlearn`/`scikit-learn`
deps, a training pipeline, and only pays off on **real, non-stationary** data —
on a Gaussian random walk an HMM learns nothing useful. **Recommendation:** keep
the deterministic regime engine for the synthetic run; build HMM/GMM as a
*pluggable* classifier to switch on once we have backfilled real history.

---

## Recommended sequence (operator view)

1. **Now (safe, paper, comparable):** activate the dormant library families
   (Donchian, RSI, Bollinger, MA, Momentum) into the rotation so we collect
   8-style comparative data — *without* tuning anything to synthetic noise.
   *(Requires registering library variants in the supervisor/registry — small
   code change.)*
2. **New structural variants** (paper): confirmation-filtered ORB (#1),
   confirmation+wider-stop VWAP (#2), Bollinger squeeze (#6) — added as **new**
   strategies so the originals stay as a stable baseline.
3. **Real-data phase (the real unlock):** backfill real NIFTY/BANKNIFTY history →
   walk-forward the whole set → *then* tune params (ADX, ATR-stop) and promote
   survivors. This is where #3 and the parameter prescriptions get earned.
4. **Bigger builds, later:** HMM/GMM regime engine; GARCH sizing; correlation
   allocator (#10).
5. **Gated on Track B:** options strategies (#9) — needs the options-routing layer.

**Bottom line:** adopt the report's *architecture* (confirmation filters,
probabilistic regimes, portfolio thinking, WFA discipline); **reject its
synthetic-derived parameter values** until real data earns them.
