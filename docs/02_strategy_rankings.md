# Strategy Rankings & Final Picks — NSE Intraday (₹5L capital)

**Companion to:** `01_strategy_research.md`.
**Ranking principle:** qualitative `automation × evidence × Indian-market fit`. No fabricated composite scores. Sub-variants used to reach 20 rows.
**Capital-preservation mandate is binding:** the ₹5L account size + SEBI 2024 evidence that 93% of F&O traders lose money tilts the recommendation away from undefined-risk short-premium strategies.

---

## 1. Top-20 ranked table

| # | Strategy | Category | Automation | Evidence | India Fit | Recommend | Rationale |
|---|---|---|---|---|---|---|---|
| 1 | Pairs / stat-arb on NIFTY constituents (intraday-to-overnight z-score) | stat-arb | 9/10 | M (peer-reviewed) | H | Y | Only strategy with peer-reviewed Sharpe (~1.34) on NSE data; market-neutral fits capital-preservation. |
| 2 | ORB 15-min on NIFTY index futures | breakout | 9/10 | M | H | Y | Best evidence base (US SSRN Sharpe 2.81 mechanism-portable + multi-year NIFTY vendor backtest). |
| 3 | ORB 5-min on liquid large-caps (RELIANCE/HDFCBANK/ICICIBANK) on "stocks in play" (gap/volume) | breakout | 9/10 | M | H | Y | Directly mirrors Zarattini/Aziz SSRN setup, just on NSE names. |
| 4 | ORB 30-min on BANKNIFTY futures | breakout | 9/10 | L–M | M | Y | Wider OR damps whipsaw on BANKNIFTY's high intraday range. |
| 5 | Pairs — HDFCBANK/ICICIBANK, RELIANCE/ONGC sector pairs | stat-arb | 9/10 | M | H | Y | Concrete cointegrated pairs cited in QuantInsti EPAT 2015–2025 study. |
| 6 | VWAP-anchored trend (long above VWAP / short below, on large-caps) | trend | 9/10 | L | H | Y | Self-reinforcing institutional benchmark; lower discretion than MR variant. |
| 7 | HMM / VIX regime overlay (gate other strategies) | overlay | 8/10 | M concept / L India | H | Y | As an overlay, raises evidence of underlying base strategies. |
| 8 | BANKNIFTY weekly expiry-day short straddle (defined-risk SL on each leg) | options short premium | 10/10 | M (vendor) | M | Conditional | Tail risk + SEBI 2024 regime change argue against as core; acceptable as small-allocation satellite. |
| 9 | NIFTY weekly expiry short strangle (further OTM, defined SL) | options short premium | 10/10 | L | M | Conditional | Lower premium but lower gamma than straddle. |
| 10 | Bollinger Band mean reversion on large-caps with ADX<20 gate | mean-rev | 10/10 | L India | M | Y (small) | Combine with #7 regime overlay to manage failure mode. |
| 11 | RSI(2) Connors on daily large-caps (positional, not intraday) | mean-rev | 10/10 | M (US daily) | M | Y (small) | Use as swing complement; intraday version loses the trend filter. |
| 12 | Supertrend + ADX on BANKNIFTY futures 15m | trend | 10/10 | L | M | Y (small) | Construction is sound; deploy only with walk-forward parameter validation. |
| 13 | NR7 breakout on NIFTY/BANKNIFTY | volatility breakout | 10/10 | L | M | Conditional | Rare signals; combine with ATR-expansion filter. |
| 14 | ATR breakout on large-caps (open + k·ATR trigger) | volatility breakout | 10/10 | L | M | Conditional | Generalization of #13 with more trades. |
| 15 | Donchian 20-bar intraday breakout on BANKNIFTY 15m | breakout | 10/10 | L | M | N | Lower-evidence variant of #4 ORB; not additive. |
| 16 | Multi-EMA 8/21/55 crossover on NIFTY 5m | trend | 10/10 | L (Sharpe ~0.43) | L | N | Vendor backtest Sharpe is too low for the noise. |
| 17 | Long straddle around scheduled events (RBI, Budget, earnings) | options long premium | 8/10 | L | M | Y (event-driven only) | Defined risk; selective use only. |
| 18 | VWAP mean-reversion (fade 2σ bands) on single stocks | mean-rev | 9/10 | L | M | N as standalone | Counter-trend without regime gate is unsafe; use only inside #7. |
| 19 | XGBoost direction classifier on 5m bars as filter | ML | 9/10 | L | L | N | No credible OOS evidence; high overfitting risk. |
| 20 | XGBoost spread-prediction overlay on pairs (#1) | ML | 8/10 | L | L | N | Same overfitting concern; not justified at ₹5L size. |

---

## 2. Top 5 NSE intraday strategies

1. **Pairs / stat-arb on cointegrated NSE large-cap pairs** — only strategy in the survey with peer-reviewed Indian Sharpe (1.34, [arxiv 2211.07080](https://arxiv.org/abs/2211.07080)). Market-neutral. Best alignment with capital-preservation mandate.
2. **15-min ORB on NIFTY futures** — most rigorous published mechanism (SSRN 4729284, Sharpe 2.81 on adjacent US market) plus a multi-year NIFTY-specific vendor backtest (win rate 48.7%, PF 1.23). Fully automatable.
3. **5-min ORB on "stocks in play" (RELIANCE/HDFCBANK/ICICIBANK on gap or relative-volume days)** — direct port of the strategy whose SSRN paper produced the highest Sharpe in the entire survey, applied to the most liquid NSE names.
4. **VWAP-anchored trend on large-caps with India VIX gate** — institutionally self-reinforcing reference price; combined with #7 overlay to avoid trend-failure regimes.
5. **BANKNIFTY 30-min ORB** — wider opening range absorbs BANKNIFTY's well-known whipsaw; same mechanism family as #2 with a parameter that suits BANKNIFTY's higher intraday range.

---

## 3. Top 3 index option strategies

Caveat on naked short premium at ₹5L: post-SEBI Oct 2024 reforms (lot size hikes, expiry rationalization) reduced both premium-per-margin-rupee and signal density; tail risk on undefined-risk short premium remains the dominant failure mode. Defined-risk preferred.

1. **BANKNIFTY weekly expiry-day short straddle, 09:20 entry, 25% per-leg SL, intraday exit by 15:15** — well-known mechanism, theta accelerates on expiry. Vendor backtests show ~7% MDD Jan–Sep 2024, ~12.75% over longer windows ([tradingqna](https://tradingqna.com/t/reports-of-the-death-of-920-short-straddle-are-greatly-exaggerated/179061)). Size small.
2. **NIFTY weekly expiry short strangle (10–15 delta OTM, defined SL)** — lower premium, lower gamma; safer tail than ATM straddle at the cost of expectancy.
3. **Long straddle around scheduled events (RBI policy, Union Budget, large-cap earnings)** — defined risk = premium paid; aligns with ₹5L capital preservation. Trade selectively, ~6–10 events/year.

---

## 4. Best strategy for ₹5L capital

**Pick: ORB-15min on NIFTY futures + size by ATR.**

**Reasoning:**
- **Margin:** NIFTY futures intraday margin (intraday MIS, ~₹40–60K depending on broker leverage and SEBI's prevailing rules in 2026) is compatible with 1 lot at ₹5L without breaching any single-instrument concentration cap.
- **Defined risk:** stop at opposite end of opening range is mechanical, not discretionary; 1% account risk maps cleanly to a stop distance in NIFTY points.
- **Expectancy stability:** the mechanism (institutional flow imbalance in the open) is the most-evidenced in the survey — peer-reviewed Sharpe 2.81 on adjacent market, multi-year NIFTY vendor backtest, PF 1.23 and win rate near 50% (asymmetry, not accuracy, drives PnL).
- **Why not short straddle:** despite higher headline returns, tail risk + SEBI regime change after Oct 2024 + ₹5L size make naked premium-selling inappropriate as the core engine.
- **Why not pairs (rank #1):** pairs is excellent but its evidence is for multi-day holds; pure intraday pairs on NSE bleeds in costs. Use pairs as a complementary swing book (overnight, not the intraday engine).

```
max_risk_per_trade: 0.5–1% (₹2,500–₹5,000)
max_daily_loss: 2% (₹10,000)
max_drawdown: 10% kill-switch (₹50,000) — halt trading, review
position_sizing: ATR-based — size = (account_risk_₹) / (stop_distance_pts × ₹_per_pt_per_lot). Default stop = opening range width (typically 0.6–1.2× 14-period 15m ATR). 1 NIFTY lot at typical 30-pt stop ≈ ₹2,250 risk fits 0.5%.
```

---

## 5. Best fully automated strategy (lowest discretion)

**Pick: Cointegrated pairs trading on NSE large-cap pairs (z-score band entries / exits).**

**Reasoning:**
- All decisions are mechanical: cointegration test on rolling window, z-score threshold ±2 for entry, 0 for exit, time-stop, leg-failure stop.
- No discretionary feature engineering (unlike ML), no regime call (the pair selection IS the regime check), no event interpretation.
- Peer-reviewed Indian Sharpe ~1.34 is the highest credibly-attributed Indian-market number in the survey.
- Market-neutral construction inherently caps directional drawdown.

```
max_risk_per_trade: 0.5–1% of equity per pair (₹2,500–₹5,000)
max_daily_loss: 2% (₹10,000)
max_drawdown: 10% kill-switch (₹50,000)
position_sizing: dollar-neutral — equal ₹ notional on each leg, scaled so stop (z-score widens to ±3.5) maps to per-trade risk budget. Hedge ratio from rolling OLS or Johansen vector.
```

---

## 6. Recommended hybrid (trend + mean-revert + regime gate)

**Architecture:**

```
                  ┌────────────────────────────┐
                  │  Regime classifier (HMM    │
                  │  on NIFTY 5m returns +     │
                  │  India VIX level + ADX(14) │
                  │  on daily NIFTY)           │
                  └──────────────┬─────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
   Trend regime              Range regime             Crisis regime
   (ADX>22, VIX 12–22)       (ADX<18, VIX<15)         (VIX>25 OR HMM=crisis)
        │                        │                        │
   ORB-15m NIFTY,           Bollinger MR on          FLAT — no new positions.
   Supertrend+ADX           large-caps,              Close existing.
   on BANKNIFTY,            VWAP fade 2σ
   VWAP-trend on            with tight stops.
   large-caps.              
        │                        │
        └────────────┬───────────┘
                     │
            Pairs book runs continuously
            in all non-crisis regimes
            (market-neutral, regime-agnostic).
```

**Gating logic:**

1. **Daily pre-open:** read prior day's HMM state (3-state Gaussian HMM trained on 252-day rolling NIFTY 5m returns + realized vol) and India VIX close.
2. **Regime assignment:**
   - VIX > 25 OR HMM crisis state → **crisis** → no new trend/MR trades; pairs only at reduced size (×0.5).
   - VIX 15–25 AND daily ADX(14) > 22 → **trend** → enable ORB-15m NIFTY, Supertrend+ADX BANKNIFTY, VWAP-trend.
   - VIX < 15 AND ADX < 18 → **range** → enable Bollinger MR and VWAP MR on large-caps; disable trend strategies.
   - Otherwise (transition) → all strategies at half size.
3. **Intra-day overrides:** kill-switch on -2% daily; if first hour realized range > 1.5× 20-day average, force trend regime regardless of pre-open classification.
4. **Pairs book** runs continuously (it is the regime-agnostic core).

**Why this construction:** raises evidence base by combining the two most-validated approaches in the survey (ORB + pairs) and gating both with a regime classifier whose mechanism has SSRN support — even though no India-specific HMM trading paper exists, the overlay can only reduce trade count in adverse regimes, which is risk-additive only if the classifier is well-calibrated.

```
max_risk_per_trade: 0.5–1% (₹2,500–₹5,000) — applies to every leg/strategy independently
max_daily_loss: 2% (₹10,000) — aggregate across all books
max_drawdown: 10% kill-switch (₹50,000) — halts entire system; manual reset
position_sizing:
  • ORB-15m / Supertrend / VWAP-trend: ATR-based, stop = OR width or 1.5× ATR(14, 15m)
  • Bollinger / VWAP MR: fixed-fractional, smaller — 0.3% per trade because lower expectancy
  • Pairs: dollar-neutral, hedge ratio from rolling Johansen, position sized so z=±3.5 stop hits 0.5% account
  • Regime multiplier: ×0.5 in transition regime, ×0.0 in crisis (no new), ×1.0 in clear trend/range
```

---

## Honest caveats

- The numeric evidence base for Indian intraday strategies is thin. 9 of 13 strategy families in the survey have INSUFFICIENT EVIDENCE on most fields. The strongest evidence (peer-reviewed, India-specific) was for **pairs trading**. The next-strongest (peer-reviewed but US) was for **ORB**.
- Vendor backtests dominate everywhere else. Treat the win-rate and profit-factor numbers in those sources as upper bounds — they generally underestimate slippage, ignore impact, and rarely publish out-of-sample windows.
- SEBI 2024 evidence (93% of F&O traders lose money; ₹26K/year transaction cost average) is the binding base rate. Any strategy that does not visibly account for transaction cost in its backtest should be considered unproven.
- Naked short premium (short straddle/strangle) is the highest-headline-return strategy in this survey AND the strategy most vulnerable to regime shifts and tail events. ₹5L capital cannot underwrite an undefined-risk-per-trade book responsibly.
