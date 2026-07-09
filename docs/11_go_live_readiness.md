# 11 — Go-Live Readiness Assessment

> Date: 2026-06-26 (post-market). Author: Claude session.
> Status: **NOT READY for real-money trading on 2026-06-29.**
>
> This document is the formal pre-live audit and the staged gating plan. Real
> orders must not flow until every gate below is green. The numbers in §A are
> based on 210 paper trades across 6 sessions (2026-06-18 → 2026-06-25); §B is
> the bug log; §C is the staged plan. Replace anecdotes with data; trust the
> ledger, not the dashboard.

---

## A. The data, honestly

### A1 — Headline edge: there isn't one yet

| Metric                | Value      | Read                                 |
|-----------------------|-----------:|--------------------------------------|
| Trades                | 210        | Far below any statistical-meaning bar |
| Net P&L               | **−₹1,732**| Negative                             |
| Expectancy per trade  | **−₹8**    | No demonstrated edge                 |
| Hit rate              | 51%        | Indistinguishable from a coin flip   |
| R (avg win / avg loss)| 0.93       | Losers larger than winners           |
| Worst day             | −₹4,859 (06-24) | One bad day ≈ a real account loss |
| Max drawdown          | −₹4,859 (9.7%)  | Brushed the 10% sticky-halt cap   |
| Daily Sharpe (n=6)    | −0.12      | Negative; sample meaningless         |

Six days is not a sample. To estimate variance with any confidence on an
intraday equity system we need 30–60 days minimum, ideally 100+. The two
profitable days (06-22, 06-23) and the one catastrophic day (06-24) together
say nothing about steady-state edge.

### A2 — Where the money goes (per strategy × side)

| Strategy           | Side  | n  | Net P&L     | Win % | Verdict                          |
|--------------------|-------|---:|------------:|------:|----------------------------------|
| orb                | SELL  | 57 | **−₹6,897** | 35%   | Toxic. Drives the system negative.|
| orb                | BUY   | 14 | +₹1,574     | 64%   | OK in isolation; tiny sample.    |
| supertrend_adx     | SELL  | 32 | −₹897       | 38%   | No edge.                         |
| supertrend_adx     | BUY   | 10 | +₹1,514     | 70%   | Looks good — but n=10 is noise.  |
| vwap_revert        | SELL  | 92 | **+₹3,109** | 61%   | The only cell with real edge.    |
| vwap_revert        | BUY   |  5 | −₹134       | 60%   | Too few trades to judge.         |

**One cell is paying for everything: `vwap_revert SELL`.** Strip ORB SELL alone
and the system goes net positive (+₹5,165 across 153 trades). The required
change before live is not subtle: **disable ORB SHORT entirely; gate ORB LONG;
kill `supertrend_adx` until it can be properly walk-forwarded.**

### A3 — Time-of-day pathology

| Hour (IST) | Trades | Net P&L | Win % | Read                              |
|-----------:|-------:|--------:|------:|-----------------------------------|
| 09:xx      | 164    | −₹7,172 | 46%   | **The kill zone.** Most damage here. |
| 10:xx      |  22    | +₹3,726 | 68%   | After the opening drive settles.  |
| 13:xx      |  22    |   +₹548 | 64%   | Mid-session vwap_revert wins.     |
| 15:xx      |   2    | +₹1,166 | 100%  | Just the flatten — not entries.   |

The opening 15–30 min is where the system bleeds. Two compounding causes:

1. **Strategies fire on the first bar** before VWAP / ADX have settled.
   `min_today_bars=6` (added today to `vwap_revert`) addresses this for that
   strategy. ORB and `supertrend_adx` need equivalent guards.
2. **Mass-open clusters** — 06-24 opened 29 positions in a single 5-min bucket
   (09:45 IST). No diversification; that was one bet in 29 wrappers, and one
   bet died. The concurrent-position cap (`TITAN_MAX_CONCURRENT_POSITIONS=50`)
   is essentially unlimited. **Must be tightened to single digits before live.**

### A4 — Regime classifier already disagrees with the trades

| Regime at entry | n   | Net P&L | Win % |
|-----------------|----:|--------:|------:|
| TREND           | 180 | −₹3,112 | 49%   |
| CRISIS          |  25 |   +₹826 | 64%   |
| CLOSED          |   2 | +₹1,166 | 100%  |

180 of 210 trades fired in TREND regime and lost money in aggregate. CRISIS
trades won — even though the selector currently maps `CRISIS → ∅` (no
strategies). The 25 CRISIS trades happened because supervisor's enabled set was
manual at the time, not driven by autopilot. This is interesting (CRISIS days
may favor mean-reversion) but n=25 is not a finding; it's a hypothesis to walk
forward, not a knob to twist now.

### A5 — Exit-reason × strategy

| Strategy          | Reason          |  n | Net P&L      | Avg     |
|-------------------|-----------------|---:|-------------:|--------:|
| orb               | stop            | 30 | **−₹14,727** | −₹491   |
| orb               | target          | 17 | +₹9,572      | +₹563   |
| orb               | manual_flatten  | 24 | −₹168        | −₹7     |
| supertrend_adx    | stop            | 19 | −₹9,351      | −₹492   |
| supertrend_adx    | target          | —  | (none — supertrend's wins come from 15:15 flatten only) | |
| supertrend_adx    | manual_flatten  | 23 | +₹9,967      | +₹433   |
| vwap_revert       | stop            | 38 | −₹19,269     | −₹507   |
| vwap_revert       | target          | 59 | +₹22,244     | +₹377   |

**The R ratio is broken across every strategy.** Avg stop loss is ~₹500
everywhere; avg target win is ₹377–₹563. The system is paying more on losers
than collecting on winners. This is the R<1 problem the vwap_revert fix
addresses for one strategy; ORB and `supertrend_adx` still have it.

Note also: `supertrend_adx` has **zero target hits in the entire ledger** —
every winner is a 15:15 manual-flatten. That's not a strategy; that's a
position-holding hack.

### A6 — Hold-time distribution

| Hold      |  n | Net P&L | Win % |
|-----------|---:|--------:|------:|
| <5 min    | 42 | −₹1,927 | 60%   |
| 5–15 min  | 32 |   −₹533 | 53%   |
| 15–60 min | 40 |   +₹458 | 50%   |
| >60 min   | 96 |   +₹271 | 47%   |

High win-rate on the <5m bucket but the worst PnL — these are the cluster-stops
where a quick win-then-lose pair leaves you negative. Longer holds give
positive expectancy but only marginally. This is consistent with the system
being over-traded.

### A7 — Symbol concentration

The worst 10 symbols cost the system **−₹12,024**; the best 10 paid
**+₹13,000**. Net is roughly a wash; risk per symbol is roughly uniform.
That means **no single symbol is broken** — the strategy×side cell is the
unit of edge, not the ticker. Don't blacklist tickers; fix the strategies.

---

## B. Open bugs & operational risks (as of 2026-06-26 close)

### B1 — Fixed today but **unvalidated against live data**

| # | File                                | Change                              |
|---|-------------------------------------|-------------------------------------|
| 1 | `titan/risk/engine.py:144` + `config.py` | Funds gate now `equity * settings.mis_leverage` (5×) instead of `* 1.0`. Sizing was 3.4× wrong on live trades. |
| 2 | `titan/strategies/vwap_revert.py`   | Target = `vwap ± 0.5σ` (not exactly vwap). Added `min_today_bars=6` guard. |
| 3 | `titan/strategies/supervisor.py:_on_bar_event` | Drop bars older than 5 min — stops stale-bar replay after restarts. |
| 4 | `titan/data/market_probe.py` + `feed_supervisor.py` + `dashboard/app.py` | Runtime REST probe detects holidays; sets `titan:market:traded:YYYY-MM-DD` and stops the feed. |

**None of these have been exercised on a real session.** Today the market was
closed; first live test is Monday's open. They are reasonable changes; they
are not validated changes.

### B2 — Known but unfixed

| Severity | Issue | Fix needed before live |
|----------|-------|------------------------|
| Critical | `orb` short side is structurally broken (−₹6,897 in 57 trades). Has no direction veto on TREND-up days. | Disable ORB SELL outright OR gate by reference symbol direction. |
| Critical | `TITAN_MAX_CONCURRENT_POSITIONS=50` is unbounded in practice. 29 trades in one bar happened. | Reduce to **3** for live; add per-strategy cap. |
| Critical | No "one-shot per symbol per day" guard. Today's ITC was traded 3× (−₹917). | Add `seen_today` set in supervisor; refuse re-entry on same symbol same side. |
| High     | `supertrend_adx` has zero target hits across the whole ledger. Edge is only via 15:15 flatten — that is not an edge. | Disable. Re-introduce only after walk-forward shows ≥1.10 PF. |
| High     | `TITAN_MAX_DAILY_LOSS_PCT=10.0` was bumped from 2% on 06-23 for demo, and again to 20% drawdown on 06-25. | **Restore to 2% daily loss / 5% drawdown before live.** |
| High     | Live execution path (`live_enabled=1`, `live_dry_run=0`) has never been exercised. Order rejection, partial fills, latency all unknown. | Shadow-live first (live submit, dry-run gate). |
| Medium   | Feed died for 4 days (06-22 → 06-26) without anyone noticing. Dashboard's `feed` dot was the only indicator. | Add a heartbeat-age alarm: if `titan:feed:age_s > 60` during NSE hours, sound something (Telegram is wired but `TELEGRAM_BOT_TOKEN` is empty). |
| Medium   | Position sizing uses `confidence` from signals, but no strategy has been validated at the right size. | Cap `confidence ≤ 1.0` (already done); verify per-trade ₹risk caps at 0.5% (₹250 on ₹50K) for first week live. |
| Medium   | Dashboard's "NSE OPEN" pill is purely time-of-day driven. Holiday detection added today but **only the feed_supervisor populates the Redis key**; weekend / pre-09:25 has no override yet. | Pre-load weekend / yaml-holiday into the same key on dashboard load. |
| Low      | `titan:risk:date` Redis snapshot stays stale (lagged a day). Cosmetic; in-memory state is authoritative. | Persist on every risk-state mutation, not just on EOD. |
| Low      | `entry_ts` on instant-fill trades after restart was a previous day's bar timestamp. Stale-bar guard above fixes the cause. | Validate Monday — query `select count(*) from trades where entry_ts::date < current_date and exit_ts::date = current_date`. Must be 0. |

### B3 — Statistical / capital-sizing risks for live

- **`TITAN_CAPITAL=50000` is the paper number.** What's the real live capital?
  At ₹5K (the original live-week-1 profile), the per-trade risk cap is ₹50 — so
  with current ~₹500 stop distances, qty rounds to zero on most symbols. **The
  live universe needs to be re-scoped to symbols where ₹50 risk gives qty ≥ 1
  share** (basically low-priced names like UPL, BPCL, NTPC), OR capital needs
  to be ₹25K+ to use the existing universe.
- **Slippage is modeled at 2 bps; reality unknown.** On a ₹400 stock that's
  ₹0.08 — almost certainly understated for MIS market orders.
- **One-share NIFTYBEES live smoke test** has never been done. Until one real
  order goes through end-to-end and reconciles, the live path is unproven.

---

## C. Staged go-live plan

Each gate must be GREEN for the stated duration before proceeding. Define
"green" precisely; otherwise the gates are theatre.

### Gate 1 — Paper validation of the post-fix code (4 weeks ≈ 20 trading days)

**Config to set on Monday 06-29:**

```bash
# .env
TITAN_AUTOPILOT_ENABLED=false                  # Don't let autopilot toggle anything during validation
TITAN_AUTOPILOT_VALIDATED=vwap_revert          # ORB and supertrend_adx out
TITAN_MAX_CONCURRENT_POSITIONS=3               # was 50
TITAN_MAX_RISK_PER_TRADE_PCT=0.5               # was 1.0
TITAN_MAX_DAILY_LOSS_PCT=2.0                   # restore from 10.0
TITAN_MAX_DRAWDOWN_PCT=5.0                     # restore from 20.0
TITAN_MAX_CONSECUTIVE_LOSSES=3                 # unchanged
TITAN_LIVE_ENABLED=0                           # paper
TITAN_LIVE_DRY_RUN=1                           # paper
```

```bash
# Redis (pre-open every day)
SET titan:autopilot:enabled 0
DEL titan:strategies:enabled
SADD titan:strategies:enabled vwap_revert
SET titan:risk:date "$(date -u +%F)"
SET titan:risk:halted_today 0
DEL titan:risk:halt_reason
SET titan:risk:consecutive_losses 0
```

**Code change before Gate 1 (do these first, commit, then run):**
1. Add one-shot-per-symbol guard in `supervisor.py:_open_position` — reject if
   `(strategy, symbol, side)` already traded today.
2. Add per-side concurrent cap (`MAX_CONCURRENT_PER_SIDE = 3`) in risk engine.
3. Confirm vwap_revert SHORT cluster-stop is mitigated by the per-side cap.

**Pass criteria:**
- ≥ 20 trading days completed.
- Net P&L > 0.
- Daily Sharpe (in-sample, n=20+) > 0.3.
- No day worse than −2% of capital.
- Max consecutive losses ≤ 5.
- Zero days with the `entry_ts < current_date` bug recurring.

**Fail criteria → DO NOT proceed:**
- Any single day exceeding the daily-loss cap.
- Stale-bar replay row appears in DB.
- Sizing produces qty that exceeds `equity × leverage / price`.

### Gate 2 — Shadow-live (1 week, 5 sessions)

Verifies the order-submission path against Angel without spending money.

**Config:**

```bash
TITAN_LIVE_ENABLED=1
TITAN_LIVE_DRY_RUN=1          # critical: dry-run keeps Angel from filling
TITAN_LIVE_MAX_ORDER_VALUE=2500
```

The supervisor already has a `shadow_broker` path that submits orders to
Angel with `dry_run` semantics. Verify in `supervisor.py:380–395`.

**Pass criteria:**
- ≥ 5 sessions with shadow submissions logged.
- 100% of paper fills correspond to a shadow-submitted order.
- Zero shadow-submit exceptions.
- Latency from signal → shadow submit < 500 ms p95.

### Gate 3 — Tiny live (1 week, 5 sessions)

One share of NIFTYBEES (~₹250) per signal, single position only. Total capital
at risk ≤ ₹2,000 — even total loss is recoverable.

**Config:**

```bash
TITAN_LIVE_ENABLED=1
TITAN_LIVE_DRY_RUN=0          # now real
TITAN_LIVE_MAX_ORDER_VALUE=500
TITAN_MAX_CONCURRENT_POSITIONS=1
TITAN_CAPITAL=2000
```

**Universe override:** `TITAN_UNIVERSE=NIFTYBEES` only.

**Pass criteria:**
- ≥ 5 sessions, ≥ 10 fills.
- Realized slippage vs modeled within 2× (i.e., if modeled 2bps then ≤ 4bps).
- Zero broker rejections (or each one understood and the cause logged).
- Intraday flatten at 15:15 actually closes the position (verify on Angel
  positions page).
- Reconciliation: supervisor's trade ledger matches Angel's trade book exactly.

### Gate 4 — Real capital, scaled

Only after Gates 1–3 are green for full duration.

**Phase 4a:** ₹5,000 capital, 1 concurrent position, full universe (re-scoped
for the price floor). Run 2 weeks. Daily loss cap 2%.

**Phase 4b:** ₹25,000 capital, 3 concurrent, 4 weeks. Daily loss cap 2%.

**Phase 4c:** Full intended capital. Daily loss cap 1.5%. Concurrent ≤ 5.

At every phase: if drawdown hits 50% of the cap intra-day, the system
must halt for the day (already the behaviour; verify it actually fires).

---

## D. What not to do

1. **Do not move to live before Gate 1.** The current code has unproven fixes
   and one paying strategy across 92 trades; that's not edge, that's a
   coincidence-sized win.
2. **Do not re-enable `orb` or `supertrend_adx`** without each strategy
   producing ≥ 30 OOS trades with PF ≥ 1.10 on a walk-forward replay.
3. **Do not loosen safety caps to "let it trade."** That happened twice this
   week — daily-loss to 10%, drawdown to 20%. Loosening caps to make trades
   happen is exactly how live accounts blow up.
4. **Do not run multiple Angel SmartAPI sessions concurrently.** Angel
   downgrades the second session to snapshot-only silently. The pre-market
   checklist (§E) covers this.
5. **Do not interpret the +₹3,109 vwap_revert SELL number as edge.** It's 3
   trading days. The 06-23 entry in the same cell was −₹2,027. The variance is
   bigger than the mean.

---

## E. Pre-market routine (every trading day)

1. **08:50 IST** — Read `out/feed.log` last 50 lines; confirm yesterday's close
   was clean (no `STALE` / max-retry errors).
2. **08:55 IST** — Verify only one `titan.data.feed*` process exists:
   `ps aux | grep titan.data.feed | grep -v grep | wc -l` must be `2`
   (feed_supervisor + feed child). More = stale; kill them.
3. **09:00 IST** — Restart `titan.strategies.supervisor` to clear in-memory
   risk state (the stale-overnight gotcha). Confirm boot log shows
   `next flatten at 15:15`.
4. **09:05 IST** — Roll Redis keys per Gate 1 § Redis block above.
5. **09:25 IST** — Verify `titan:market:traded:$(date +%F)` is `"1"`. If `"0"`,
   the runtime probe says it's a holiday; halt for the day.
6. **09:30 IST** — Verify first bars are coming through:
   `XLEN bars:1m:RELIANCE` should be > 0; supervisor log should have at least
   one `_on_bar_event` activity line.
7. **At market close** — Pull the day's trade ledger, append a one-line entry
   to `docs/10_changes_and_decisions.md` §F.

---

## F. Bottom line

The system is **not ready for real money on Monday**. With 4 weeks of clean
paper validation on the post-fix code, plus shadow-live and tiny-live phases,
real capital can responsibly flow from **2026-08-10** at the earliest. Any
faster is a gamble dressed up as a plan.

The path forward is clear; the discipline to walk it is the only question.
