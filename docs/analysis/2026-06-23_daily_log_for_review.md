# TITAN — Daily Operator Log & Data Dump for Analysis · 2026-06-23

> Self-contained snapshot for external analysis (Gemini). All numbers embedded so
> no DB access is needed. Companion to the system spec `docs/11`, strategy guide
> `docs/12`, external-research mapping `docs/14`, and the 2026-06-22 analysis.

---

## 0. Context you need

- **TITAN** = event-driven intraday algo system. Pipeline: tick feed → 5m OHLCV
  bars → strategies emit signals → risk engine gates → paper broker fills →
  Postgres. Decision engine ("auto-pilot") arms strategies by market **regime**
  (TREND / RANGE / TRANSITION / CRISIS).
- **Mode:** paper/sim. **Synthetic random-walk feed** (NOT real market data).
  Capital ₹50,000, 2× MIS leverage, daily-loss/profit/drawdown caps all at 100%
  (deliberately loose for paper), 50-symbol dynamic universe (NSE large-caps),
  **17 strategies**, auto-pilot armed.
- **CRITICAL caveat:** because the feed is a Gaussian random walk with no real
  edge, **absolute P&L is noise** (costs + slippage dominate). Yesterday a lucky
  trending stretch gave +₹38,636; today the same strategies are −₹17k. Read
  **relative** behaviour (strategy × regime, exit mix), NOT absolute alpha. Real
  verdicts require **real backfilled data → walk-forward** (not yet done).
- **Two phases today:** (a) 00:29–04:45 IST = overnight continuation of
  yesterday's run (peaked ~+₹38.6k, then I did a user-requested fresh restart);
  (b) 11:20 IST onward = a clean ₹50k restart for the new day (the "current run"
  analysed in §2). Yesterday's run is preserved in a backup.

---

## 1. Operator decision log — today (12 entries, IST)

The autonomous operator logs every ~30-min review to the `operator_decisions`
table. Today's entries (#39–#50):

| # | Time | Title | Key data | Action |
|---|---|---|---|---|
| 39 | 00:29 | Review #17 — broke out of idle | 1648 trades, realized +38,612, win-rates normalized to 30–50% | held |
| 40 | 01:02 | Review #18 — stable | +38,634, best stoch_adx +28,009, worst supertrend_multi −8,970 | held |
| 41–47 | 01:34–04:45 | Reviews #19–25 — stable/unchanged | hovering ~+38,636, ~1,800–1,816 trades | held |
| 48 | 11:20 | Review #26 — **fresh restart for today** | backed up prior run (+38,636 / 1,816 trades, 129M dump), truncated to clean ₹50k, restarted 6 procs | restart |
| 49 | 11:53 | Review #27 — fresh run bleeding | realized −17,244 / 1,432 trades, worst donchian −12,454, best vwap_revert +4,120 | held |
| 50 | 12:25 | Review #28 — bleeding flat | realized −17,246 / 1,476 trades, not halted | held |

**Recurring operator rationale (every "held"):** *hold params steady — synthetic
P&L is noise; don't optimise to it; keep the dataset comparable. Persistent
laggards across runs = donchian / supertrend_multi / inside_bar (prune
candidates). Real verdicts need a real-data walk-forward.*

---

## 2. Current run data (fresh 2026-06-23 restart) — embedded

Snapshot at review #28+. **1,500 closed trades, realized −₹17,240, win 35%,
equity range ₹30,500–₹52,512.** Paper slippage realized = modeled = 2.0 bps.

### 2a. Per-strategy (closed trades)

| strategy | n | win% | net ₹ | targets | stops |
|---|---|---|---|---|---|
| vwap_revert | 136 | 35 | **+4,126** | 47 | 89 |
| orb | 169 | 49 | +2,280 | 84 | 85 |
| vwap_rsi | 29 | 72 | +2,163 | 21 | 8 |
| bollinger_revert | 26 | 58 | +466 | 15 | 11 |
| bb_squeeze | 2 | 0 | −17 | 0 | 2 |
| rsi_revert | 8 | 0 | −405 | 0 | 8 |
| momentum | 215 | 31 | −450 | 63 | 152 |
| orb_confirmed | 50 | 54 | −525 | 27 | 23 |
| ma_cross | 119 | 34 | −1,296 | 40 | 79 |
| macd_cross | 189 | 34 | −1,345 | 59 | 130 |
| inside_bar | 48 | 29 | −1,450 | 14 | 34 |
| stoch_adx | 209 | 40 | −1,469 | 81 | 128 |
| supertrend_adx | 91 | 31 | −1,517 | 28 | 63 |
| rsi_divergence | 44 | 36 | −2,418 | 16 | 28 |
| supertrend_multi | 63 | 17 | −2,929 | 11 | 52 |
| donchian | 102 | **9** | **−12,454** | 9 | 93 |

### 2b. By regime (the most consistent signal across runs)

| regime | trades | win% | net ₹ |
|---|---|---|---|
| **RANGE** | 210 | **43** | **+6,819** |
| TREND | 1,039 | 33 | −11,991 |
| TRANSITION | 251 | 35 | −12,068 |

### 2c. Signal funnel (why signals don't become trades)

| outcome | count |
|---|---|
| **rejected: sizing → 0 qty** | **23,052** |
| rejected: max concurrent positions | 2,489 |
| **accepted → order** | 1,501 |
| rejected: insufficient funds | 1,179 |
| rejected: position already open | 840 |

---

## 3. Findings & open questions for deeper analysis

**Consistent across both runs (likely structural, not just noise):**
1. **RANGE regime is the only profitable bucket** (mean-reversion: vwap_revert,
   vwap_rsi, bollinger_revert). TREND/TRANSITION bleed even when ADX says "trend"
   — the deterministic ADX gate mislabels random-walk noise as trend. → supports
   moving to **probabilistic regime detection (HMM/GMM)** on real data.
2. **`donchian` is consistently the worst** (9% win, −12.5k) — and
   `supertrend_multi`, `inside_bar` also persistently negative. Prune candidates.
3. **`vwap_rsi` has the best win-rate** (72%, 21 targets / 8 stops) — the RSI
   confirmation gate on VWAP-revert looks like the cleanest behaviour.
4. **Targets fixed the 0%-win problem** (yesterday ma_cross/supertrend_adx/
   momentum were 0% win; now 31–34% with real target hits) — but they're still
   net-negative on this unlucky stretch.

**Two engineering signals worth Gemini's view:**
5. **23,052 "sizing → 0 qty" rejections vs 1,501 fills** — per-trade risk
   (1% equity / per-unit-risk) yields <1 share for many high-priced names, so the
   universe that actually trades is biased toward cheaper symbols / tight stops.
   Question: better sizing (min-1-lot, volatility-scaled, or notional-floor)?
6. **High stop:target ratios** on the trend/momentum strategies (e.g. donchian
   9 targets / 93 stops; momentum 63/152) — entries are low-quality on this feed.

**Questions for Gemini:**
- Given the RANGE-only profitability and ADX mislabeling, what regime-detection
  upgrade would you prioritise, and with what feature set?
- Which of the 16 strategies would you cut vs keep purely on the *relative*
  cross-run evidence (acknowledging synthetic noise)?
- How would you fix the sizing→0 starvation without over-risking the ₹50k account?
- What's the minimum real-data backfill + walk-forward protocol you'd require
  before trusting any of these relative reads?

*Raw CSVs (yesterday's full dump): `~/titan-exports/2026-06-22/`. Per-run DB
backups: `~/titan-backups/`. Full decision history: `operator_decisions` table /
`docs/operator_journal.md`.*
