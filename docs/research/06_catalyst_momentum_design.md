# Catalyst-Momentum (CMOM) — Design

**Status:** Design only. No code, no backtest, no ship/kill decision.
**Last updated:** 2026-06-18
**Predeclaration:** Everything below is fixed BEFORE looking at backtest data. Per README, no tuning to pass.

## 1. Thesis

Stocks with a high-quality positive (or negative) news catalyst tend to drift in the direction of the catalyst over a multi-session window, as the market absorbs the new information unevenly. This is **Post-Event Announcement Drift** — the generalization of PEAD beyond earnings.

Builds on `02_news_driven.md` (PEAD literature, Sehgal-Bijoy 2015 on India). Differences from `02_news_driven`:
- v2 classifier (`titan/news/category.py`) now recognises 11 catalyst types, not 4. Broadens the universe of "events" beyond earnings.
- Trades a **multi-session hold**, not intraday only. Sehgal-Bijoy found India PEAD persists 3–10 trading days.
- Adds a **confirmation gate**: don't enter just because news fired — require price confirmation in the direction of the signal.

## 2. Why a confirmation gate

Catalyst-driven entries without confirmation are the textbook fail mode:
- Sell-the-news on IT contracts where the deal is small relative to revenue.
- "Strategic investment" announcements that are PR with no economics behind them.
- Guidance cuts that get bought immediately by traders front-running the recovery.

The confirmation gate filters these out empirically. If the market doesn't agree with the catalyst's direction in the next session, we don't take the trade.

## 3. Signal definition (predeclared)

A trade fires when **all** of the following hold:

| condition | spec |
|---|---|
| News fire exists | `news_signals.would_fire = TRUE`, published in last 24h, ticker in Nifty 50 |
| Direction | `direction` field set by v2 fire rule (`long` or `short`) |
| Category quality | Category in {`order_win`, `m_and_a`, `partnership`, `guidance_up`, `guidance_down`, `regulatory`} (excludes weaker categories like `dividend` and `debt_*`) |
| Sentiment score | ≥ 0.70 for long, ≤ -0.70 for short (tighter than v2 fire rule's 0.60) |
| Confirmation (long) | Next-session **close > pre-news close × 1.005** (+0.5%) AND volume ≥ 1.5× 20-day avg |
| Confirmation (short) | Next-session **close < pre-news close × 0.995** (-0.5%) AND volume ≥ 1.5× 20-day avg |
| Daily ATR sanity | 14-day ATR > 0.3% of price (avoid dead names) |

## 4. Entry / exit / sizing (predeclared)

- **Entry**: market order at next bar (5m) after confirmation bar's close.
- **Stop**: 1.5 × 14-day daily ATR from entry, in the opposite direction of the trade.
- **Target**: 3.0 × 14-day daily ATR from entry (1:2 R:R).
- **Time exit**: 5 trading sessions from entry. Square off at close of session 5.
- **Sizer**: existing `fixed_fractional_qty` with 1% per-trade risk.
- **Universe**: Nifty 50 only (matches v2 `FIRE_NIFTY50_ONLY=True`).
- **Max concurrent CMOM positions**: 3 (matches existing `RiskLimits.max_concurrent_positions`).
- **No overnight gap risk dressing** — yes, we hold overnight. Stops can gap through. Documented risk.

## 5. Predeclared ship/kill thresholds

Walk-forward: 70% in-sample, 30% out-of-sample.

| metric | bar | rationale |
|---|---|---|
| OOS Sharpe | ≥ 0.7 | Higher than ORB's 0.6 — catalyst-driven trades should be selective and high-quality |
| Max DD | ≤ 12% | Multi-session holds = higher gap risk; we want tighter DD control |
| Hit rate | ≥ 45% | PEAD literature shows 55–65%; we set 45% as a conservative bar |
| Profit factor | ≥ 1.30 | Strict — these aren't supposed to be "noisy edge" trades |
| Min trades in OOS | ≥ 30 | Sample size floor; below this we can't claim significance |
| Avg holding period | ≥ 2 bars | If < 2, time exit isn't binding; thesis is broken |

**SHIP** = all 6 pass. **KILL** = any fail. No tuning, no re-running with different parameters. If it kills, we write up *why* in section 7 of the results file and the strategy enters the killed list.

## 6. Backtest plan

We do NOT have historical `news_signals` rows older than 2026-06-17 (the v2 classifier shipped yesterday). We need to acquire them before backtesting.

**Data acquisition (precondition):**
1. BSE corporate announcements API supports `from_date`/`to_date`. Pull 2025-06-18 → 2026-06-17 (12 months).
2. Run pulled events through current v2 classifier + FinBERT. Insert into `news_signals` with the historical `published_at`.
3. Expected scale: ~250 trading days × 50 names × ~3 announcements per name = ~37k events. Most filter out as `generic_noise` / `other`. Estimate 500–2000 firing signals over 12 months — enough for a real test.

**Backtest mechanics (after data is loaded):**
1. Already have 6 months of daily bars and 6 months of 5m bars for RELIANCE, HDFCBANK, ICICIBANK. Need to extend to all 49 Nifty 50 names.
2. For each fired signal, simulate entry per section 4 specs against 5m bars + daily volume.
3. Use existing `titan/backtest/engine.py` event-loop; extend to handle SHORT entries (currently long-only — known limitation noted in `03_orb_results.md`).
4. Walk-forward split by **calendar date**, not by row count, so seasonality doesn't bleed across IS/OOS.

**Estimated work to first verdict:**
- BSE historical pull + reclassify: 2–3 hours
- Backfill 5m + daily for remaining 46 Nifty 50 names: 1–2 hours (API rate-limited)
- Extend backtest engine for SHORT: 1 hour + tests
- Run backtest + write verdict: 30 min

Total ~5–7 hours before a verdict exists.

## 7. Blockers / risks

1. **Historical news data quality.** BSE filings are official and reliable. ET/MC RSS only goes back ~2 weeks. We will be limited to BSE-sourced catalysts for historical, which means fewer events than today's pipeline produces (today's pipeline includes ET RSS). The backtest universe of events is narrower than the live universe of events. Acknowledged.

2. **Look-ahead bias from FinBERT.** FinBERT was trained on financial news through 2019. Applying it retroactively to 2025–2026 headlines is fine in principle (no future leakage on the model side) but the *category classifier* (rules) was tuned on yesterday's headlines. There is a real risk that the rules overfit yesterday's specific wording. Mitigation: hold out 30% of historical headlines from any rule tuning. We only saw a handful yesterday so this is already approximately true.

3. **Survivorship bias on Nifty 50.** Today's Nifty 50 ≠ 2025-06's Nifty 50. Need point-in-time index membership or accept the bias and document it.

4. **Volume confirmation requires intraday data we don't have historically.** Daily volume can substitute for 1.5× rule (use 5-day vs 20-day daily volume). Cleaner but slightly weaker filter.

5. **Costs assumption.** Catalyst trades are larger position sizes (multi-session holds = wider stops = smaller qty per ₹500 budget). Brokerage % is lower than intraday MIS but STT on delivery is higher. Need to verify the cost model in `titan/backtest/engine.py` handles non-MIS correctly.

## 8. Out of scope for this design

- Sector strength layer (Step 3 of the user's rubric). Add as a separate filter once base CMOM is shown to work.
- FII/DII institutional flow gating (Step 4). Same — add after base.
- X / Reddit / social sentiment (Step 6 of rubric). Same — add after base.
- The 30/20/15/20/15 weighted score (Step 7). The current design uses categorical filters, not a weighted score. Once we have a working base, weight-based ranking is a refinement.

## 9. Discipline contract

Per README invariant: **this strategy does not ship until the verdict file `docs/research/07_cmom_results.md` shows SHIP** against the section 5 thresholds, on out-of-sample data we have not previously inspected. If KILL — the strategy stays dormant and the writeup explains what we learned, same way `01_tsmom_results.md` and `05_strategy_comparison_2026-06-18.md` did.

No exceptions. No "let me just try enabling it for a session to see".
