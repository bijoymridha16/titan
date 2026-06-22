# 12 — Strategy Guide & Analysis Reference

> What each TITAN strategy does, the regime it's built for, how the auto-pilot
> assigns them, what the collected paper data shows so far, and how to design new
> strategies. Written 2026-06-22 during the autonomous paper run. Data snapshots
> here are point-in-time — re-run the queries at the bottom for current numbers.
>
> **Read alongside:** `docs/11` (system spec §5.5 strategies, §5.6 decision
> engine), `docs/operator_journal.md` (operator decisions), and the live
> `operator_decisions` / `trades` / `signals` tables.

---

## 1. Active strategies — what they're for

| Strategy | Style | Designed for | Entry logic | Stop / Target | Timeframe |
|---|---|---|---|---|---|
| **ORB** (Opening Range Breakout) | Breakout / momentum | Directional days that break out of the morning range | First 5m close **beyond** the 09:15–09:30 range. LONG if close > range-high, SHORT if close < range-low. One long + one short per day; no entries after 14:30 IST | Stop = opposite side of the range; Target = 1.5× range width | 5m |
| **VWAP Mean Reversion** (`vwap_revert`) | Mean-reversion | Range-bound / choppy days where price oscillates around fair value | Price deviates **> 2σ** from the session VWAP → fade it. SHORT if z > +2, LONG if z < −2 | Stop = 1× ATR; **Target = back to VWAP** | 5m |
| **Supertrend + ADX** (`supertrend_adx`) | Trend-following | Strong, sustained trends | Supertrend line **flips** direction **and** ADX > 20 (trend-strength filter) → ride the new direction | Stop = the Supertrend line; no fixed target (rides the trend) | 5m |

**Killed:** **TSMOM** (daily time-series momentum, long-only, vol-targeted) —
failed the walk-forward ship/kill thresholds, so the engine blocks it (API
returns 409, hidden in the UI).

### Exact default parameters
- **ORB:** `or_minutes=15`, `target_r=1.5`, `cutoff="14:30"`, `session_open="09:15"` (IST)
- **VWAP-revert:** `k_sigma=2.0`, `atr_period=14`, `atr_mult=1.0`, `lookback=20`
- **Supertrend-ADX:** `st_period=10`, `st_mult=3.0`, `adx_period=14`, `adx_min=20.0`
- **TSMOM (killed):** `lookback=20`, `vol_window=60`, `vol_target=0.10`, `stop_sigma=2.0`

---

## 2. How the auto-pilot maps regimes → strategies

The decision engine classifies the market regime from NIFTY 5m bars and arms only
the strategies that suit it (`decision/selector.py → REGIME_CANDIDATES`):

```
TREND        → ORB + Supertrend-ADX     (ride directional moves)
RANGE        → VWAP-revert              (fade extremes back to mean)
TRANSITION   → ORB                      (only the most-evidenced strategy)
CRISIS/CLOSED → nothing                 (capital preservation)
```

Regime thresholds: TREND `ADX ≥ 22`, RANGE `ADX < 18`, CRISIS `India-VIX ≥ 25 OR
realized-vol percentile ≥ 0.90`, TRANSITION otherwise. **The whole point: each
strategy runs only in the regime that fits its style.**

---

## 3. What the collected data shows so far

Point-in-time snapshot (2026-06-22, synthetic feed, small samples, and much of it
predates full auto-pilot governance — strategies ran in wrong regimes early):

| strategy | regime | trades | win% | net P&L | avg P&L |
|---|---|---|---|---|---|
| orb | TREND | 15 | 40% | −1,122 | −74.8 |
| orb | TRANSITION | 3 | 67% | **+496** | +165.4 |
| orb | CRISIS | 1 | 100% | +418 | +418 |
| orb | RANGE | 1 | 0% | −351 | −351 |
| supertrend_adx | TREND | 3 | 0% | −976 | −325 |
| supertrend_adx | TRANSITION | 2 | 0% | −748 | −374 |
| vwap_revert | RANGE | 2 | 50% | **+1,217** | +608 |
| vwap_revert | TREND | 25 | 24% | −2,844 | −114 |
| vwap_revert | TRANSITION | 8 | 13% | −3,359 | −420 |
| vwap_revert | CRISIS | 2 | 0% | −736 | −368 |

**Exit mix:** orb 11 stop / 9 target · supertrend 5 stop / 0 target ·
vwap_revert 30 stop / 7 target.

### Early read (hypotheses to test on more / real data)
1. **VWAP-revert is profitable only in RANGE** (+1,217) and bleeds badly in
   TREND/TRANSITION (−6,200). Strong support for strict regime-gating — it should
   *never* run outside RANGE.
2. **ORB does best in TRANSITION/CRISIS, worst in TREND** here — counter to the
   intuition that ORB is a TREND play. Worth investigating (could be sample
   noise, or the synthetic feed's breakout behaviour).
3. **VWAP-revert gets stopped out 30 vs 7 targets** — its 1× ATR stop may be too
   tight, or the 2σ trigger fires too early. A parameter sweep candidate.
4. **Supertrend-ADX has too few trades (5) to judge** — needs more data.

### ⚠️ Critical caveat
This is a **synthetic random walk with no real edge**; transaction costs +
slippage dominate, so absolute P&L is negative by construction. **Use the data
for *relative* comparison** (strategy × regime, exit reasons, slippage realism) —
**not** to declare winners. Real ship/kill verdicts require backfilled **real**
market history (walk-forward harness).

---

## 4. Dormant strategy library (ready to activate / vet)

`titan/strategies/library.py` already holds **5 parametrized families = 59
variants**, vetted via walk-forward but not in the live rotation:

| Family (`name`) | Style | Param grid → variants |
|---|---|---|
| MACrossover (`ma_cross`) | trend | fast[5,9,12,20] × slow[21,50,100] × atr_mult[2,3] → 24 |
| DonchianBreakout (`donchian`) | breakout | period[10,20,55] × target_r[1.5,2,3] → 9 |
| RSIReversion (`rsi_revert`) | mean-rev | period[2,7,14] × lo[20,30] × hi[70,80] → 12 |
| BollingerReversion (`bollinger_revert`) | mean-rev | period[20,50] × k[2,2.5,3] → 6 |
| MomentumROC (`momentum`) | momentum | lookback[10,20,40,60] × atr_mult[2,3] → 8 |

---

## 5. How to design / add a new strategy

1. **Code it:** subclass `Strategy` in `titan/strategies/` — implement
   `on_bar(bars: pd.DataFrame) -> list[Signal]` (bars = history up to the closed
   bar, columns `o,h,l,c,v`). Return `Signal(kind, entry, stop, target?,
   confidence)`; `SignalKind ∈ {ENTRY_LONG, ENTRY_SHORT, EXIT}`.
2. **Register it:** add `name → class` to `BASE_STRATEGIES` in
   `titan/strategies/registry.py` (live rotation), **or** add a param family to
   `PARAM_GRID` in `titan/strategies/factory.py` (mass variant vetting).
3. **Map it to a regime:** add it to the right bucket in `decision/selector.py →
   REGIME_CANDIDATES` so the auto-pilot arms it in the right conditions.
4. **Allow it:** add to the validated allowlist (`titan:autopilot:validated`) so
   the armed auto-pilot can use it.
5. **Vet it:** run the walk-forward backtest (`titan/backtest/walk_forward.py`)
   with predeclared thresholds before trusting it — ideally on **real** backfilled
   data, not synthetic.
6. **Available indicators** (`titan/strategies/indicators.py`, all leak-free):
   `ema, sma, roc, true_range, atr, rsi, bollinger, donchian`.

---

## 6. Queries for your analysis (run anytime)

```sql
-- per-strategy × regime performance (current)
SELECT strategy, COALESCE(regime,'—') regime, count(*) trades,
       round(100.0*count(*) FILTER (WHERE pnl>0)/NULLIF(count(*),0),0) win_pct,
       round(sum(pnl)::numeric,0) net_pnl, round(avg(pnl)::numeric,1) avg_pnl
FROM trades WHERE exit_ts IS NOT NULL
GROUP BY strategy, regime ORDER BY strategy, trades DESC;

-- exit reasons (stop vs target) by strategy
SELECT strategy, exit_reason, count(*) FROM trades WHERE exit_ts IS NOT NULL
GROUP BY strategy, exit_reason ORDER BY strategy, count(*) DESC;

-- signal funnel: what was generated vs why rejected
SELECT accepted, COALESCE(reject_reason,'(accepted)') reason, count(*)
FROM signals GROUP BY accepted, reject_reason ORDER BY count(*) DESC;

-- slippage realism (paper fills vs modeled)
SELECT strategy, round(avg(realized_slippage_bps)::numeric,2) realized_bps,
       round(avg(modeled_slippage_bps)::numeric,2) modeled_bps, count(*)
FROM fills GROUP BY strategy;

-- my operator decisions + reasoning
SELECT ts, category, title, action, rationale, expected
FROM operator_decisions ORDER BY id;
```

---

*Living document — update §3 as more (and eventually real) data accrues, and §1/§4
as strategies are added or promoted.*
