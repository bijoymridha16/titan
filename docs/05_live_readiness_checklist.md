# 05 — Live trading readiness checklist

## Verdict (as of 2026-06-12)

### 🛑 NOT READY FOR LIVE CAPITAL

This is correct. The system is a scaffold + paper-mode engine with an
honest research survey behind it. Going live requires every box below
checked, in order. There is no shortcut.

---

## Gate A — Code completeness

- [ ] `AngelOneBroker.connect()` implemented + tested in sandbox
- [ ] SmartAPI WS V2 binary parser implemented + unit-tested with recorded frames
- [ ] `place_order` / `cancel_order` / `get_positions` / `get_ltp` / `get_funds` all implemented
- [ ] Daily 05:30 IST JWT refresh cron in place
- [ ] Reconciler verified against broker reality (manually create/cancel an order; confirm reconciler picks it up)
- [ ] Kill switch verified end-to-end (POST /kill → next order is rejected)
- [ ] Telegram alerts firing for: kill, halt, broker disconnect, daily-loss cap, RCA-worthy rejects

## Gate B — Strategy validation (per strategy)

- [ ] Event-driven backtest (`bt_runner`) on ≥ 5 years of 1m/5m data
- [ ] Walk-forward: ≥ 5 non-overlapping OOS windows, all positive expectancy
- [ ] Monte-Carlo trade resampling: 5th-percentile equity curve still positive
- [ ] Costs included: brokerage (`PaperBroker._charges`) + 2 bps slippage minimum
- [ ] Profit factor > 1.5 OOS, net of costs
- [ ] Win rate × R ≥ 0.15 expectancy
- [ ] Max DD ≤ 15% in any 60-day window in the backtest
- [ ] Survives regime changes: COVID Mar 2020, Adani Jan 2023, SEBI Oct 2024 expiry reform

## Gate C — Paper trading

- [ ] ≥ 60 calendar days of paper trading on live market data
- [ ] ≥ 100 trades taken
- [ ] Live paper PF ≥ 1.5 (within 80% of backtest PF — bigger gap means overfit)
- [ ] Live paper DD ≤ backtest DD × 1.3
- [ ] Zero unhandled exceptions in the last 30 days of paper logs
- [ ] All risk halts during the paper period were intentional / correct

## Gate D — Operational

- [ ] Dashboard up and accurate (cross-checked vs broker for ≥ 1 week)
- [ ] Reconciler reports zero drift events for ≥ 5 consecutive trading days
- [ ] Manual fire drill: kill switch, flatten, broker outage, redis outage, postgres outage. Document recovery time for each.
- [ ] On-call rotation defined (even if it's just you with phone alerts)
- [ ] Daily EOD report auto-mailed (trades, P&L, drift count, halt events)

## Gate E — Capital + scaling

- [ ] First live week: max notional ₹50,000 (10% of capital).
- [ ] First live month: max notional ₹2,00,000 (40%).
- [ ] Full capital only after 100 live trades with PF ≥ 1.5 and DD ≤ 8%.
- [ ] Any single-day loss > 1.5% triggers automatic 1-week shutdown for review.
- [ ] Quarterly review: rebaseline parameters; deprecate any strategy that drifts > 30% from its backtested expectancy.

## What "ready" means in one sentence

Every box in Gates A–D is checked, capital starts at 10% per Gate E, and you can answer "what happens if X breaks?" for every X in your dependency tree without looking it up.

## If you skip any of this

The honest base rate: SEBI's own data shows 93% of individual F&O traders
lose money, with aggregate retail losses ₹1.8 lakh crore over FY22–24. The
gates above exist because the default outcome of "build algo, go live" is
losing money. The system is supposed to be the boring path, not the fast
one. Boring is the point.
