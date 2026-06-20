# 08 — Automation & Decision Engine

> How TITAN goes from *human-toggled* to *fully automated and decision-driven* —
> without sacrificing safety or auditability. Companion to `03_architecture.md`
> and the gating logic in `02_strategy_rankings.md §6`.

## The gap this closes

Before this layer, "which algo runs" was a manual decision: a human flipped
`titan:strategies:enabled` via the API or the dashboard. The research
(`02_strategy_rankings.md §6`) specified a regime-gated hybrid — *trend regime →
breakout/trend-follow; range regime → mean-revert; crisis → flat* — but **it was
never built**. The system had strategies and a switch, but no hand on the switch.

The **decision engine** (`titan/decision/`) is that hand. It reads the market,
classifies the regime with deterministic rules, and arms/disarms the validated
strategy set automatically — closing the loop.

```
   5m bars (NIFTY, from TimescaleDB)  ─┐
   IST clock (synth-aware)            ─┼─►  RegimeClassifier  ─►  RegimeReading
   India VIX (optional, if a feed)    ─┘     (pure function)      {regime, features, reason}
                                                                        │
                                                                        ▼
                                                            Selector.decide(apply?)
                                                       target = candidates(regime) ∩ VALIDATED
                                                                        │
                                              ┌─────────────────────────┼──────────────────────┐
                                              ▼                         ▼                       ▼
                                   reconcile Redis            publish titan:regime:*    INSERT regime_decisions
                                   titan:strategies:enabled   (dashboard/observability)  (full audit trail)
                                              │
                                              ▼
                                   Supervisor reads the set on the next bar (UNCHANGED)
```

The key architectural win: the decision engine writes to **the exact same Redis
set the supervisor already reads**. Zero supervisor changes. It's a clean,
additive layer.

## "No hallucination" — what it means here, concretely

Every decision is a **pure function of observable inputs**. There is no ML model,
no opaque score, no fabricated data:

- **Inputs:** OHLCV bars already in our DB + the IST clock + an *optional* India
  VIX value (used only if a real feed sets `titan:vix` — we never invent one).
- **Rules:** ADX bands, realized-vol percentile, session phase — all standard,
  mechanical, reproducible.
- **Output:** a regime label + the exact feature vector that produced it + a
  plain-English reason, persisted to `regime_decisions` on every tick.

Given the same bars and clock, the regime is **always identical**. You can replay
any historical decision and get the same answer. That is the guarantee.

## The regimes (and why, for the Indian market)

| Regime | Trigger | Action | Indian-market rationale |
|---|---|---|---|
| **CLOSED** | Outside 09:15–15:15 IST, or past square-off cutoff | Arm nothing | NSE cash session is 09:15–15:30; MIS auto-square-off ~15:15–15:20. No entries pre-open or into the close rush. |
| **CRISIS** | Realized-vol percentile ≥ 90% (or India VIX ≥ 25) | Arm nothing; let positions exit | SEBI 2024: 93% of F&O traders lose money. Capital preservation dominates at ₹5K. High-vol regimes are where naked directional bets bleed. |
| **TREND** | ADX(14) ≥ 22 on 5m | Arm breakout/trend-follow | Directional NSE days trend cleanly; ADX is the standard separator. ORB's edge (institutional open-flow imbalance) lives here. |
| **RANGE** | ADX(14) < 18, vol not in crisis | Arm mean-revert | Balance days chop around VWAP — where mean-reversion belongs (and trend-follow gets whipsawed). |
| **TRANSITION** | ADX between 18–22 | Arm only ORB | Ambiguous regime → use only the single most-evidenced strategy, never the speculative ones. |

**Session phases** are first-class (not all NSE hours are equal):
`PREOPEN → OPENING_RANGE (09:15–09:30) → MORNING → LUNCH (11:30–13:30, thin) →
AFTERNOON → CUTOFF (≥15:15) → CLOSED`. The opening range is left to ORB itself;
CUTOFF/CLOSED force arm-nothing.

## Two hard safety invariants (enforced in code, not docs)

1. **Validated-only.** Auto-pilot can enable a strategy *only* if it's in
   `settings.autopilot_validated_set`. That set contains only strategies that
   passed their walk-forward ship/kill gate. Default = `{orb}`. This is the
   code-level fix for **AUTOPSY_FINDINGS H1** — `vwap_revert`, `supertrend_adx`
   (unvalidated) and `tsmom` (killed) **cannot** be auto-armed in any regime,
   by construction. Tested in `tests/test_decision/test_selector.py`.
2. **Stays in its lane.** Auto-pilot only adds/removes strategies within its
   controlled (validated) universe. A human who manually enables an experiment
   outside that set is never stomped.

Plus: the **kill switch dominates** — when `titan:kill=1`, auto-pilot disarms its
whole lane and refuses to arm anything.

## Arm / disarm — the dry-run philosophy, applied to automation

Mirroring the broker's `dry_run`, auto-pilot has two modes:

- **Disarmed (observe-only, default):** classifies the regime and logs the full
  decision *it would have made*, every tick — but does **not** touch the enabled
  set. This is the dress rehearsal: watch it for a week, confirm its regime calls
  match reality, then hand it the keys.
- **Armed:** actually reconciles the enabled set.

```bash
curl -X POST :8000/autopilot/arm      # hand over control
curl -X POST :8000/autopilot/disarm   # back to observe-only
curl       :8000/autopilot            # current regime + arm state + reason
```

Resolution order: Redis `titan:autopilot:enabled` (live) overrides the
`.env` default `TITAN_AUTOPILOT_ENABLED`.

## Running it

```bash
# 6th process, alongside feed / bar_writer / supervisor / api / dashboard
python -m titan.decision.auto_pilot
```

It loops every `TITAN_AUTOPILOT_INTERVAL_S` (default 30s): load NIFTY 5m bars →
classify → decide → reconcile. Errors are logged and the tick is skipped — it
never crashes the loop and never leaves a half-applied change.

## Configuration (all in `.env`)

| Var | Default | Purpose |
|---|---|---|
| `TITAN_AUTOPILOT_ENABLED` | `0` | Default arm state (observe-only when 0) |
| `TITAN_AUTOPILOT_VALIDATED` | `orb` | Comma-list of auto-armable (validated) strategies |
| `TITAN_AUTOPILOT_INTERVAL_S` | `30` | Decision cadence |
| `TITAN_AUTOPILOT_REF_SYMBOL` | `NIFTY` | Symbol whose bars define the regime |
| `TITAN_REGIME_ADX_TREND` | `22` | ADX ≥ → TREND |
| `TITAN_REGIME_ADX_RANGE` | `18` | ADX < → RANGE |
| `TITAN_REGIME_VOL_CRISIS_PCTILE` | `0.90` | Realized-vol percentile → CRISIS |
| `TITAN_REGIME_VIX_CRISIS` | `25` | India VIX → CRISIS (only if `titan:vix` set) |

## What this does NOT do (honest scope)

- It does **not** size positions or place orders — that stays in the router /
  risk engine / broker. It only decides *which strategies are eligible to fire*.
- It does **not** invent an India-VIX feed. VIX sharpens CRISIS detection only if
  a real value is published to `titan:vix`; otherwise realized-vol carries it.
- It does **not** auto-validate strategies. Promoting `vwap_revert` /
  `supertrend_adx` into `TITAN_AUTOPILOT_VALIDATED` still requires a walk-forward
  results doc first — automation enforces the process, it doesn't bypass it.

## Roadmap to "more automated" (next, not in this change)

1. Publish daily `1d` bars (fixes M1) so daily-timeframe regime inputs exist.
2. A real India-VIX poller writing `titan:vix` → genuine volatility regime.
3. Validate `vwap_revert` / `supertrend_adx` → add to the allowlist → range/trend
   regimes gain real strategy coverage.
4. Auto-flatten on CRISIS entry (currently arms-nothing; positions still rely on
   SL/TP or manual `/flatten`).
