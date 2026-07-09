# 13 — Full Ledger Audit (14 sessions)

> Date: 2026-07-06 (post-market). Author: Claude session.
> Ledger: 399 trades across 14 trading sessions, 2026-06-15 → 2026-07-06.
> Sources: Postgres `trades` (375) + `out/2026-06-17/trades.csv` snapshot (24 pre-DB-reset).
> Status: **NOT READY for live. Zero of the five Gate 1 pass criteria met.**

---

## A. Headline

| Metric | Value | Read |
|---|---:|---|
| Net PnL | **−₹5,896** | −11.79% on ₹50k capital |
| Expectancy / trade | **−₹14.78** | negative edge |
| Hit rate | 47.1% | worse than coin flip |
| R (avg win / avg loss) | 1.05 | flat; losers slightly bigger |
| Daily Sharpe (n=14) | **−0.19** | Gate 1 needs > +0.30 |
| Green sessions | 6 / 14 | 43% |
| Best / worst day | +₹3,813 / **−₹4,859** | worst day > weekly loss cap |
| Max cum drawdown | **−₹6,905** | 13.8% of capital; Gate 1 limit = 5% |

## B. Gate 1 pass criteria vs reality

| Criterion | Target | Actual | Result |
|---|---|---|---|
| Sessions completed | ≥ 20 | 14 | **FAIL** (6 short) |
| Net P&L | > 0 | −₹5,896 | **FAIL** |
| Daily Sharpe | > +0.30 | −0.19 | **FAIL** |
| No day worse than −2% | −₹1,000 | 06-24 = −₹4,859 (−9.7%) | **FAIL** |
| Max consecutive losses | ≤ 5 | tripped today | **FAIL** |

## C. Per-session ledger

| Date | n | W/L | PnL | Cum |
|---|---:|---:|---:|---:|
| 2026-06-15 | 4 | 1/3 | −422.46 | −422.46 |
| 2026-06-16 | 4 | 1/3 | −1,091.32 | −1,513.78 |
| 2026-06-17 | 16 | 5/11 | −1,945.52 | −3,459.30 |
| 2026-06-18 | 3 | 1/2 | −611.10 | −4,070.40 |
| 2026-06-19 | 3 | 2/1 | +277.76 | −3,792.64 |
| 2026-06-22 | 88 | 43/45 | +1,228.14 | −2,564.50 |
| 2026-06-23 | 44 | 25/19 | +518.40 | −2,046.10 |
| 2026-06-24 | 48 | 20/28 | **−4,858.70** | −6,904.80 |
| 2026-06-25 | 24 | 16/8 | +1,713.87 | −5,190.93 |
| 2026-06-29 | 49 | 22/27 | +2,364.40 | −2,826.53 |
| 2026-06-30 | 31 | 19/12 | **+3,812.88** | +986.35 |
| 2026-07-01 | 24 | 9/15 | −2,733.97 | −1,747.62 |
| 2026-07-02 | 16 | 5/11 | −962.47 | −2,710.09 |
| 2026-07-06 | 45 | 19/26 | −3,186.11 | **−5,896.20** |

## D. Strategy verdict (changed with the fuller ledger)

Doc-11 (n=210): *"vwap_revert SELL is the only paying cell."*
n=399 (this audit): **supertrend_adx is now the only positive strategy; vwap_revert has gone net negative.**

### Strategy × side

| Strategy | Side | n | Win % | PnL |
|---|---|---:|---:|---:|
| supertrend_adx | SELL | 82 | 45.1% | **+₹4,834** |
| supertrend_adx | BUY | 61 | 49.2% | +₹1,861 |
| orb | BUY | 18 | 50.0% | +₹202 |
| vwap_revert | BUY | 41 | 43.9% | −₹1,543 |
| vwap_revert | SELL | 138 | 53.6% | **−₹3,465** ← was doc-11's "paying cell" |
| orb | SELL | 59 | 33.9% | **−₹7,786** ← toxic across every audit |

### Strategy totals

| Strategy | n | Win % | PnL |
|---|---:|---:|---:|
| supertrend_adx | 143 | 46.9% | **+₹6,695** |
| vwap_revert | 179 | 51.4% | −₹5,008 |
| orb | 77 | 37.7% | −₹7,584 |

## E. Exit-reason asymmetry (R < 1)

| Reason | n | PnL | Avg |
|---|---:|---:|---:|
| target | 104 | +₹41,726 | +₹401 |
| manual_flatten | 133 | +₹32,552 | +₹245 |
| stop | 158 | **−₹79,988** | **−₹506** |
| eod_flatten | 2 | −₹180 | — |
| eod_outage_close | 2 | −₹7 | — |

**Losers are 25% bigger than winners.** Same R<1 problem doc-11 flagged; still unfixed.

## F. Time-of-day pathology (IST)

| Hour | n | Win % | PnL |
|---|---:|---:|---:|
| 09:xx | 223 | 47.5% | **−₹4,757** ← opening kill zone |
| 10:xx | 56 | 55.4% | +₹1,342 |
| 11:xx | 25 | 48.0% | +₹1,594 |
| 12:xx | 15 | 40.0% | +₹2,047 |
| 13:xx | 32 | 50.0% | −₹480 |
| 14:xx | 45 | 33.3% | **−₹6,705** ← new bleed (today's damage) |
| 15:xx | 3 | 66.7% | +₹1,062 |

- 09:xx: same opening bleed doc-11 flagged. `min_today_bars=6` guard on vwap_revert only; ORB and supertrend_adx still fire on first bar.
- 14:xx: new failure mode. Today's consecutive-loss halt tripped at 14:20 — after the damage was already done.

## G. Cluster opens (still unbounded)

Top same-5m-bar entry counts (UTC):

| Bar | Concurrent opens |
|---|---:|
| 2026-06-24 04:15 | **29** |
| 2026-06-23 04:05 | 17 |
| 2026-06-22 03:45 | 17 |
| 2026-06-22 03:50 | 16 |
| 2026-06-23 04:15 | 15 |
| 2026-06-30 03:50 | 14 |
| 2026-07-01 05:00 | 13 |
| 2026-07-06 04:10 | 11 |

`TITAN_MAX_CONCURRENT_POSITIONS=50` in current `.env`. 29 concurrent opens on 06-24 = one bet in 29 wrappers = that day's entire −₹4,859 loss.

## H. Duplicate re-entries (still unguarded)

**63 duplicate (strategy, symbol, side, day) entries across the ledger.** Doc-11's one-shot-per-symbol guard was never merged.

---

## I. Required changes before Gate 1 can be re-attempted

### Code (must merge before restarting the 20-session clock)

1. **Kill `orb SELL` outright.** 3 audits, 59 trades, −₹7,786, 33.9% win rate. Structurally broken.
2. **Reconsider `vwap_revert`.** The edge that motivated the Gate 1 single-strategy allowlist has evaporated (+₹3,109 → −₹5,008 net over 3 audits).
3. **One-shot-per-symbol-per-day guard** in `supervisor._open_position` (63 dupes).
4. **Per-side + global concurrent cap = 3** in `titan/risk/engine.py`.
5. **`min_today_bars=6` on all strategies** (fixes 09:xx bleed).
6. **Peak-PnL trailing profit-lock.** Today's ₹2,242 peak → −₹3,186 giveback = ₹5,428 round-trip.
7. **Consecutive-loss halt must be reversible from Redis** without a supervisor restart. Today's halt stuck in-memory after Redis was primed.

### Config (`.env` still at paper-relaxed values)

| Key | Current | Target |
|---|---:|---:|
| `TITAN_MAX_CONCURRENT_POSITIONS` | 50 | **3** |
| `TITAN_MAX_DAILY_LOSS_PCT` | 10.0 | **2.0** |
| `TITAN_MAX_DRAWDOWN_PCT` | 20.0 | **5.0** |
| `TITAN_MAX_RISK_PER_TRADE_PCT` | 1.0 | **0.5** |
| `TITAN_MAX_DAILY_PROFIT_PCT` | 10.0 | **5.0** |
| `TITAN_AUTOPILOT_ENABLED` | true | **false** |
| `TITAN_AUTOPILOT_VALIDATED` | orb,vwap_revert,supertrend_adx | **supertrend_adx** (data-driven) |

### Ops (before Gate 2 shadow-live)

- Feed heartbeat alarm — `TELEGRAM_BOT_TOKEN` still empty; 06-22→06-26 silent-outage repeats otherwise.
- Automated pre-market supervisor restart cron — today proved a stale supervisor holds risk state Redis prime can't clear.
- Angel `shadow_broker` path never exercised end-to-end; verify latency + rejection paths per doc-11 § Gate 2.

---

## J. Bottom line

- **14 sessions run, −11.79% of capital lost, −13.8% peak drawdown.**
- The "paying cell" identity has flipped between every audit (n=210 → n=375 → n=399). That instability *is* the finding: no single cell has proved edge; each has taken a turn carrying the P&L before decaying.
- Zero Gate 1 criteria met. Six code changes and seven config changes required before restarting the 20-session validation clock.
- Real money must not flow until Gate 1 is green for the full 20 sessions.
