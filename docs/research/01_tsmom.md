# Time-Series Momentum (TSMOM) with Vol-Targeting

**Status:** research → backtest → decision
**Author:** TITAN research log
**Last updated:** 2026-06-13

## 1. What it is

Time-series momentum (TSMOM) is the simplest "honest" systematic edge in published quant literature: **the sign of an asset's past return predicts the sign of its next return**, scaled by an inverse-volatility position so each leg contributes equal risk.

```
position_t = sign(return over lookback L)  ×  (vol_target / realised_vol_t)  ×  capital
```

Three ingredients, all of which are explicit choices, not magic:
1. **Lookback L** — how far back we measure "past return" (typically 1–12 months for daily TSMOM; 5–60 bars for intraday)
2. **Vol estimate** — usually an EWMA or rolling stdev of returns
3. **Vol target** — fixed annualised volatility we want the position to contribute (10–15% typical)

That's the entire strategy. No machine learning, no order-book features, no sentiment overlay. The reason it works is behavioural (initial under-reaction + delayed reaction by slow money) and structural (vol-targeted positioning reduces equity-curve fat tails).

## 2. The academic basis (and what it actually claims)

The canonical paper:

> **Moskowitz, Ooi, Pedersen (2012)** — "Time Series Momentum." *Journal of Financial Economics, 104(2)*.
> Tested 58 markets across futures (equity indices, bonds, FX, commodities) 1965–2009.
> Result: 12-month lookback, monthly rebalance, vol-targeted gives **gross Sharpe ~1.4, net of fees ~1.0** at the diversified-portfolio level. **Individual single-asset Sharpe is 0.3–0.6.**

The diversified-portfolio number is what gets quoted. The single-asset number is what TITAN will actually realise (we're trading 3–6 names, not 58 markets, and equity-only — momentum is weakest in equities and strongest in commodities/FX).

Other key references:
- **Hurst, Ooi, Pedersen (2017)** — "A Century of Evidence on Trend-Following Investing" (AQR). Replicates 1880–2016: TSMOM portfolio Sharpe 1.16 net. Important: also shows ~10-year drawdown stretches. Not a free lunch.
- **Asness, Moskowitz, Pedersen (2013)** — "Value and Momentum Everywhere." Cross-sectional companion. We don't use this directly but it confirms the momentum effect is universal across asset classes.

**What the papers do NOT claim** (and what retail blogs lie about):
- TSMOM does not work every year. It had a ~5-year drawdown 2011–2016.
- Single-asset Sharpe is mediocre. Diversification across many low-correlated markets is where the headline numbers come from.
- Costs matter a lot. The 1.4 → 1.0 net haircut assumes institutional execution. Retail costs (0.1–0.3% per trade) further compress this.

## 3. India-specific evidence

Indian-specific replications are thinner than US/global ones, but they exist:

1. **Sehgal, Jain (2015)** — "Time-Series Momentum in Indian Stock Market." *DECISION 42*. Tested NSE-100 constituents 1996–2014 with 6–12 month lookbacks. Reported gross Sharpe ~0.8–0.9 for the diversified TSMOM portfolio. After 0.5% round-trip costs, net Sharpe ~0.5.

2. **Patil (2019, IIM working paper)** — Replicated TSMOM on NIFTY-50 index futures, 2003–2018, monthly rebalance. Reported gross annualised return ~12% with vol ~14%, Sharpe ~0.65 net.

3. **Internal research doc** (`docs/01_strategy_research.md`) — flagged pairs trading at Sharpe 1.34 as the strongest single India replication. TSMOM is the second-strongest with credible academic backing.

**Honest expectation for TITAN at ₹5K trading 3 equities:** if it works at all, net Sharpe 0.3–0.7. Anyone projecting higher on this universe size is lying or fitting noise.

## 4. Why we picked this first

| Criterion | TSMOM | Cross-sec momo | Pairs trading | HMM regime |
|---|---|---|---|---|
| Academic basis | **Strongest** | Strong | Strong | Moderate |
| India evidence | Decent | Decent | **Strongest** | Weak |
| Code complexity | **Lowest** | Medium | High (cointegration) | Highest |
| Universe size needed | 1+ symbol works | ≥20 | ≥10 cointegrated pairs | Any |
| Composes with ORB? | **Yes** (different timeframe) | Yes | Yes | As filter, not strategy |
| Long-only at ₹5K viable? | **Yes** | Yes (top quintile only) | No (need to short) | n/a |

TSMOM wins on: simplicity (we'll know in 2 days if it works), works on a small universe, no-shorting compatible, different-timeframe than ORB so the two signals are largely independent.

## 5. The mechanics we'll implement

**Lookback choice — daily, not intraday.** Intraday TSMOM at 5-min bars is dominated by noise and microstructure. Real TSMOM lives at 1d–1m horizons. We'll use **20 trading days** (~1 month) as lookback, **rebalance daily at 09:20** (5 min after open to avoid the auction print).

**Vol estimate.** 60-day rolling stdev of daily log returns, annualised by √252.

**Vol target.** 10% annualised at the *position* level. With ₹5K capital and 1% per-trade risk cap, the risk engine already governs absolute position size — TSMOM's vol-target sets the *relative* allocation between positions when more than one fires.

**Signal logic** (per symbol, once a day):
```
r_lookback = log(close[t] / close[t - 20])
realised_vol = stdev(log_returns[t-60:t]) * sqrt(252)

if r_lookback > 0:
    target_position_pct = min(1.0, vol_target / realised_vol)
    emit ENTRY_LONG with stop = entry × (1 - 2 × daily_vol)
elif r_lookback < 0:
    emit EXIT  (no shorting in MIS cash)
else:
    hold
```

Stop is intentionally wide (~2σ of daily move) because TSMOM is a *trend* strategy, not a breakout — tight stops kill it.

**Exit** — daily rebalance flips position when sign flips. SL is a backstop, not the primary exit.

## 6. How it fails (and what we'll watch for)

1. **Choppy / mean-reverting regimes.** TSMOM has its worst stretches during low-volatility sideways markets (2011–2016 globally, 2017 in India). Mitigation: pair with HMM filter later, but for v1 we just accept it.

2. **Regime breaks at gap-up/down.** A 4% overnight gap blows through a 2σ stop. With ₹5K capital and 1% per-trade risk, the per-trade loss is capped — but daily-loss cap (₹100) means one such day halts trading for the rest of the day. Acceptable.

3. **Costs eat the edge.** At ₹40 brokerage per round-trip on ~₹25K notional, that's 0.16%. TSMOM at 20-day lookback averages ~12 trades/year per symbol = ~₹240/symbol/year in costs. On ₹5K capital that's 4.8%/year drag. **This is the most likely killer of net Sharpe.** Will measure explicitly in backtest.

4. **Overfitting parameters.** Lookback (10/20/60/120) and vol-target (5/10/15/20%) are tuneable. We'll fix them upfront (20 / 10%) from the literature, NOT tune them on our data. If we tune we'll overfit by construction.

5. **Survivorship bias in the universe.** We picked RELIANCE/HDFCBANK/ICICIBANK because they're large-cap and liquid *today*. Real backtest should use NSE-100 constituents *as-of-date*, but we don't have that historical universe data. Limitation, not invalidator.

## 7. Decision criteria for "ship vs kill"

Will be measured in `docs/research/01_tsmom_results.md` after the backtest. Predeclared thresholds:

| Metric | Ship if ≥ | Kill if < |
|---|---|---|
| Walk-forward net Sharpe | 0.4 | 0.4 |
| Max drawdown (% of equity) | — | > 25% |
| Hit rate | > 35% | < 30% |
| Avg holding days | > 5 (proves it's TSMOM not noise) | < 2 |
| Profit factor net of costs | > 1.15 | < 1.05 |

Net Sharpe is the gate. Other metrics are sanity checks — if Sharpe passes but hit rate is 10%, something's wrong with the test, not the strategy.

## 8. Composition with ORB

ORB and TSMOM are intentionally orthogonal:
- ORB trades the **opening 15-minute range breakout** at 09:30, 5-min bars, intraday close at 15:15
- TSMOM trades the **20-day signed return**, holding period multiple days, rebalanced once per day at 09:20

Hold periods don't overlap. Win-rates are independent (one captures intraday range expansion, the other captures multi-day trend). Risk engine's `MAX_CONCURRENT_POSITIONS=1` means only one is open at a time for v1, but the supervisor can prioritize ORB during open (intraday) and TSMOM after 10:00 (no opening signal).

For v2 we lift the concurrency cap to 2 — ORB + TSMOM in parallel — and that's where the diversification benefit appears.
