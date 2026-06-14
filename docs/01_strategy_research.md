# Strategy Research Survey — NSE Intraday System (₹5L capital)

**Scope:** NIFTY / BANKNIFTY / FINNIFTY index + options + liquid large-caps (RELIANCE, HDFCBANK, ICICIBANK). Timeframes 1m / 3m / 5m / 15m.
**Date:** June 2026.
**Evidence bar:** Every numeric claim is either cited or marked `INSUFFICIENT EVIDENCE`. Influencer / Telegram / YouTube P&L claims excluded. Where the only available numbers come from a single vendor backtest without out-of-sample disclosure, confidence is lowered.

**Important context — SEBI 2024 study:** 93% of individual F&O traders incurred losses FY22–FY24, aggregate ₹1.8 lakh crore; transaction costs ~₹26K per trader per year (source: [SEBI press release Sep 2024](https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html); [Business Standard FY25 update](https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html)). This is the baseline against which any retail intraday system must justify itself.

---

### 1. Opening Range Breakout (ORB) — 5/15/30-min variants

**Category:** breakout / momentum
**Mechanics:** Mark the high/low of the first N minutes after the open (5/15/30). Enter long on break of OR high, short on break of OR low. Stop typically at opposite end of range; targets at 1R/2R or trailing. Best evidence is for a 5-min ORB on US "Stocks in Play" with intraday news-driven volume.
**Indian-market applicability:** Indian equity opens 09:15 IST; the first 15–30 minutes commonly form the day's range. Adapted by Indian retail desks for NIFTY, BANKNIFTY index, and high-ADV large-caps. Works on trend days; chops on range days. Friday and high-gap days improve hit rates per US data (unverified for India).
**Known failure modes:** false breakouts on low-volume days, whipsaw inside OR on event days, gap-and-fade behavior on BANKNIFTY expiry, narrow OR on listless days inflating noise. Slippage on illiquid stocks kills edge.
**Automation feasibility:** 9/10 — pure price-time rules.
**Discretion surface:** low
**Cited performance:**
  - win_rate: ~48.7% (NIFTY 15-min ORB, vendor backtest 2017–2026, 2,122 trades) — source: [Intraday Lab](https://intradaylab.com/blog/nifty-orb-breakout-strategy-backtest); 63.2% reported on alternate US backtest, [QuantifiedStrategies](https://www.quantifiedstrategies.com/opening-range-breakout-strategy/)
  - profit_factor: 1.23 (NIFTY 15-min, vendor); 2.34 (US ORB+filters, QuantifiedStrategies); 2.51 reported in same source
  - sharpe: 2.81 — US "Stocks in Play" 5-min ORB portfolio, 2016–2023, Zarattini/Barbon/Aziz [SSRN 4729284](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284). NIFTY-specific Sharpe: INSUFFICIENT EVIDENCE.
  - max_drawdown: INSUFFICIENT EVIDENCE for NIFTY ORB
  - sample/period: NIFTY 50 15-min OHLC July 2017–March 2026 (vendor); US 7,000 stocks 2016–2023 (SSRN, peer-reviewed working paper)
**Confidence:** M (High evidence in US equities, Medium in India because the only multi-year NIFTY backtest is vendor-published without methodology disclosure)
**Sources:**
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- https://intradaylab.com/blog/nifty-orb-breakout-strategy-backtest
- https://www.quantifiedstrategies.com/opening-range-breakout-strategy/
- https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/

---

### 2. VWAP mean reversion + VWAP-anchored trend

**Category:** mean-reversion / trend hybrid
**Mechanics:** Compute session VWAP plus ±1σ, ±2σ bands. Mean-revert: fade extensions to 2σ when volume tapers, exit at VWAP. Trend variant: only long above VWAP / short below VWAP, treating VWAP as dynamic support/resistance. Often combined with relative-volume filter.
**Indian-market applicability:** VWAP is institutionally tracked on NSE — large desks execute against it, which creates self-reinforcing magnet behavior intraday. Works well on large-cap single stocks (RELIANCE, HDFCBANK) and index futures.
**Known failure modes:** trend days break VWAP early and never return — fading those produces large losses. Counter-trend version is the dangerous one. Costs erode small mean-reversion targets.
**Automation feasibility:** 9/10
**Discretion surface:** low
**Cited performance:**
  - win_rate: INSUFFICIENT EVIDENCE for Indian intraday published; vendor cites ~60% generic
  - profit_factor: INSUFFICIENT EVIDENCE
  - sharpe: INSUFFICIENT EVIDENCE for Indian
  - max_drawdown: INSUFFICIENT EVIDENCE
  - sample/period: vendor backtests only; no peer-reviewed or QuantInsti EPAT paper isolating NIFTY VWAP MR found
**Confidence:** L (mechanism is well-accepted; quantitative Indian-specific evidence is weak)
**Sources:**
- https://www.quantifiedstrategies.com/vwap-trading-strategy/
- https://www.mstock.com/articles/mean-reversion-trading-indian-stock-market

---

### 3. Supertrend + ADX filter (NIFTY / BANKNIFTY futures)

**Category:** trend
**Mechanics:** Supertrend uses ATR-based bands; flip signal = entry. ADX>threshold (commonly 20–25) gates entries so signals only fire when a trend is present. Exit on Supertrend flip or ADX collapse.
**Indian-market applicability:** Widely deployed on BANKNIFTY/NIFTY futures and options 5m/15m by retail algo desks (Tradetron strategies, etc.). Adapts to volatility because of ATR component.
**Known failure modes:** late entries (ADX confirms trend after the move), repeated whipsaw on ADX threshold flicker, choppy expiry days, parameter sensitivity (ATR period, multiplier).
**Automation feasibility:** 10/10 — fully deterministic.
**Discretion surface:** low
**Cited performance:**
  - win_rate: INSUFFICIENT EVIDENCE for BANKNIFTY-specific peer-reviewed
  - profit_factor: INSUFFICIENT EVIDENCE
  - sharpe: INSUFFICIENT EVIDENCE
  - max_drawdown: INSUFFICIENT EVIDENCE
  - sample/period: QuantInsti EPAT blog describes the construction but does not publish a Sharpe for BANKNIFTY; QuantifiedStrategies cites "avg 11.07% per trade" on unspecified market — not credible for India.
**Confidence:** L (construction is well-described; numeric Indian backtests are all vendor/blog without methodology disclosure)
**Sources:**
- https://blog.quantinsti.com/strategy-using-trend-following-indicators-macd-st-adx/
- https://www.quantifiedstrategies.com/supertrend-indicator/

---

### 4. Multi-EMA crossover (8 / 21 / 55)

**Category:** trend
**Mechanics:** Stack three EMAs; entry when shortest crosses above next two (aligned uptrend), exit on opposite alignment. Often combined with price-above-55EMA filter for long bias.
**Indian-market applicability:** Common retail template on NIFTY/BANKNIFTY 5m/15m; performance highly regime-dependent.
**Known failure modes:** notorious for whipsaw in low-volatility regimes; multi-EMA confirmation adds lag, so trend-day entries are late. Equity-curve flat-to-negative on choppy markets.
**Automation feasibility:** 10/10
**Discretion surface:** low
**Cited performance:**
  - win_rate: INSUFFICIENT EVIDENCE specific to 8/21/55 on NIFTY
  - profit_factor: INSUFFICIENT EVIDENCE
  - sharpe: ~0.43 reported on 1-min EMA crossover Indian-stock vendor backtest — [QuantifiedStrategies / Quant-Signals references](https://quant-signals.com/ema-crossover-strategy/) — low and not robust
  - max_drawdown: INSUFFICIENT EVIDENCE
**Confidence:** L
**Sources:**
- https://quant-signals.com/ema-crossover-strategy/
- https://www.quantifiedstrategies.com/9-ema-strategy/

---

### 5. Donchian / Turtle breakout

**Category:** breakout / trend
**Mechanics:** Classic Turtle: enter on break of N-day Donchian high (20-day for entry, 10-day for exit), ATR-sized position. Intraday adaptation: 20-bar high/low on 15m or 5m timeframe.
**Indian-market applicability:** Originally a futures/commodities daily-bar system. Intraday adaptation on NIFTY/BANKNIFTY is plausible but unproven in peer-reviewed work.
**Known failure modes:** long, deep drawdowns are a known feature of the original system. Intraday version exacerbates whipsaw. Most NSE retail equity is mean-reverting at short horizons — breakout fails more than on futures markets.
**Automation feasibility:** 10/10
**Discretion surface:** low
**Cited performance:**
  - win_rate: classic Turtle ~30–40% (industry-standard, not Indian)
  - profit_factor: INSUFFICIENT EVIDENCE for NIFTY intraday
  - sharpe: INSUFFICIENT EVIDENCE for NIFTY; researchgate Turtle reproduction shows mixed
  - max_drawdown: INSUFFICIENT EVIDENCE
**Confidence:** L
**Sources:**
- https://drpress.org/ojs/index.php/HBEM/article/download/7933/7723
- https://tosindicators.com/research/modern-turtle-trading-strategy-rules-and-backtest

---

### 6. Bollinger Band mean reversion (intraday)

**Category:** mean-reversion
**Mechanics:** 20-period SMA ± 2σ. Enter long when price tags lower band in a non-trending market, exit at middle band (or upper band on momentum exit). Mirror for shorts. Needs explicit regime filter (e.g. ADX<20) to avoid trending regimes.
**Indian-market applicability:** Plausible on large-cap single stocks (RELIANCE, HDFCBANK) where intraday mean-reversion dominates short horizons. Index futures less suitable because of stronger trends on event days.
**Known failure modes:** band-walking in trends; standard counter-example is "mean reversion in a trending market is a blowup."
**Automation feasibility:** 10/10
**Discretion surface:** low
**Cited performance:**
  - win_rate: ~60–78% (QuantifiedStrategies multi-market backtests, includes MACD+BB variant 78%) — [QuantifiedStrategies](https://www.quantifiedstrategies.com/macd-and-bollinger-bands-strategy/)
  - profit_factor: INSUFFICIENT EVIDENCE for Indian intraday
  - sharpe: INSUFFICIENT EVIDENCE for Indian intraday
  - max_drawdown: INSUFFICIENT EVIDENCE for Indian intraday
  - sample/period: vendor backtests, mixed markets, time period not always disclosed
**Confidence:** L (well-established mechanism, weak Indian-specific evidence)
**Sources:**
- https://www.quantifiedstrategies.com/macd-and-bollinger-bands-strategy/
- https://www.quantifiedstrategies.com/bollinger-bands-trading-strategy/

---

### 7. RSI(2) Connors-style mean reversion

**Category:** mean-reversion
**Mechanics:** Larry Connors 2-period RSI: enter long on RSI(2) < 10 with price > 200-SMA (trend filter), exit when RSI > 70 or price crosses 5-SMA. Designed for end-of-day swing; intraday adaptation is non-standard.
**Indian-market applicability:** Connors' original work is daily US equities; intraday Indian application is conjectural. Could be ported to 5–15m on large-caps but loses the long-term trend filter.
**Known failure modes:** raw RSI(2) without trend filter generates noise; loses edge in bear markets / trending regimes.
**Automation feasibility:** 10/10
**Discretion surface:** low
**Cited performance:**
  - win_rate: 75–79% on daily US equities — [QuantifiedStrategies](https://www.quantifiedstrategies.com/rsi-2-strategy/); 62–68% on crypto daily
  - profit_factor: 1.4–1.8 on crypto (no Indian data)
  - sharpe: INSUFFICIENT EVIDENCE for Indian intraday
  - max_drawdown: 15–31% depending on configuration (US equities, [QuantifiedStrategies](https://www.quantifiedstrategies.com/rsi-2-strategy/))
  - sample/period: multi-decade US equities, daily bars — not directly applicable to NSE intraday
**Confidence:** M for daily US equities; L for NSE intraday
**Sources:**
- https://www.quantifiedstrategies.com/rsi-2-strategy/
- https://stratbase.ai/en/blog/rsi-2-strategy-larry-connors

---

### 8. ATR / NR7 volatility expansion breakout

**Category:** breakout / volatility expansion
**Mechanics:** Identify a day whose range is the narrowest of the last N (NR4, NR7). Enter on break of that day's high or low next session — premise is volatility compression precedes expansion. ATR variant: trigger on multi-ATR move from open.
**Indian-market applicability:** Pattern is regime-agnostic and works on any liquid instrument. Plausible on NIFTY/BANKNIFTY and liquid large-caps.
**Known failure modes:** NR7 days are rare → low trade count → high statistical noise; fakeouts on news days; needs follow-through volume.
**Automation feasibility:** 10/10
**Discretion surface:** low
**Cited performance:**
  - win_rate: INSUFFICIENT EVIDENCE for Indian market — Crabel's original work is futures-floor era, modern replication results vary
  - profit_factor: INSUFFICIENT EVIDENCE
  - sharpe: INSUFFICIENT EVIDENCE
  - max_drawdown: INSUFFICIENT EVIDENCE
  - sample/period: Crabel 1990 book is the canonical reference; no NSE peer-reviewed replication found
**Confidence:** L
**Sources:**
- https://www.quantifiedstrategies.com/nr7-trading-strategy-toby-crabel/
- https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/narrow-range-day-nr7

---

### 9. Index options — short straddle / strangle on expiry day (BANKNIFTY weekly)

**Category:** options / short premium
**Mechanics:** Sell ATM call + ATM put (straddle) at 09:20 AM on expiry day; hold to ~15:15 PM. Per-leg stop loss (commonly 25–30%) and/or overall SL. Captures theta decay which accelerates on expiry day. Variants: 09:30, "shift on SL," delta-hedged.
**Indian-market applicability:** Heavily traded on NSE BANKNIFTY/NIFTY weekly expiries by retail and prop. SEBI's 2024–25 expiry rationalization (one weekly expiry per exchange, lot size increases) has materially shrunk this edge — the regime that produced 2019–2022 returns no longer exists.
**Known failure modes:** trend days produce catastrophic losses (the loss leg compounds while the winning leg is capped at premium received); SL whipsaw (both legs SL'd then market reverts); IV expansion on event days; gap risk if held overnight (don't); SEBI lot-size hikes raise margin and drag PnL per trade.
**Automation feasibility:** 10/10
**Discretion surface:** low (but the strategy itself has tail risk that no automation can fix)
**Cited performance:**
  - win_rate: ~69% on vendor "920 Straddle" Indian backtest — [Medium / Nomad Trader](https://medium.com/@amit179.iitk2/optimized-920-straddle-strategy-to-get-more-than-80-return-annually-e977453dca80)
  - profit_factor: INSUFFICIENT EVIDENCE peer-reviewed
  - sharpe: INSUFFICIENT EVIDENCE
  - max_drawdown: 7% (Jan–Sep 2024 BANKNIFTY backtest, vendor) — [tradingqna.com discussion](https://tradingqna.com/t/reports-of-the-death-of-920-short-straddle-are-greatly-exaggerated/179061); 12.75% over longer period (vendor)
  - sample/period: vendor backtests, no peer-reviewed source; one trader-reported 2023 live record showed 12% YTD followed by -7% May drawdown
**Confidence:** M (the mechanism is real — theta decay is observable. The numbers are vendor-only and the regime has shifted post-SEBI 2024)
**Sources:**
- https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html
- https://medium.com/@amit179.iitk2/optimized-920-straddle-strategy-to-get-more-than-80-return-annually-e977453dca80
- https://www.marketcalls.in/futures-and-options/is-the-920-straddle-no-more-working.html
- https://tradingqna.com/t/reports-of-the-death-of-920-short-straddle-are-greatly-exaggerated/179061
- https://newsletter.upsurge.club/p/banknifty-option-selling-strategy-backtested

---

### 10. Index options — long straddle / long gamma (event / gap)

**Category:** options / long premium
**Mechanics:** Buy ATM call + ATM put pre-event (RBI policy, budget, gap-open Mon, expiry day open). Profit if move > combined premium. Defined max loss = premium paid.
**Indian-market applicability:** Defined risk aligns with ₹5L capital preservation mandate. NSE BANKNIFTY/NIFTY ATM weekly straddles are liquid enough. Edge: events that the market underprices.
**Known failure modes:** time decay if move doesn't materialize; IV crush post-event eats both legs even if direction was right; expiry-day long straddle bleeds theta intraday — "last 100 points of premium can evaporate in a few hours."
**Automation feasibility:** 8/10 (entry rule is straightforward; exit / IV-adjustment logic is harder)
**Discretion surface:** med (event selection is the discretionary part)
**Cited performance:**
  - win_rate: INSUFFICIENT EVIDENCE
  - profit_factor: INSUFFICIENT EVIDENCE
  - sharpe: INSUFFICIENT EVIDENCE
  - max_drawdown: INSUFFICIENT EVIDENCE
  - sample/period: vendor-only; no peer-reviewed NSE long-straddle backtest located
**Confidence:** L
**Sources:**
- https://algotest.in/blog/bank-nifty-expiry-day/
- https://www.quora.com/Are-there-any-backtest-results-for-the-long-straddle-options-strategy-for-Nifty-Bank-s-intraday-options

---

### 11. Regime detection overlay (HMM, volatility regimes, VIX gating)

**Category:** overlay / regime filter
**Mechanics:** Use Hidden Markov Model on returns/volatility, or VIX thresholds (low <15, normal 15–20, elevated 20–30, crisis >30), or realized-vol percentile, to gate base strategies. Trend strategies on high-vol/trend regime; mean-reversion in low-vol range regime.
**Indian-market applicability:** India VIX is published and tradable; HMM has been implemented on QuantConnect and in SSRN papers. The overlay concept is sound regardless of market.
**Known failure modes:** regime classification is itself overfittable; states may be unstable in real time vs. retrospective; HMM lookahead bias in backtests is common.
**Automation feasibility:** 8/10 (HMM training cadence is the engineering question)
**Discretion surface:** low
**Cited performance:**
  - win_rate: N/A (overlay)
  - profit_factor: N/A
  - sharpe: ~1.76 vs 1.16 buy-and-hold reported for one regime-adaptive backtest; HMM SSRN study reports lower DD (-20% vs -28%) — [QuantifiedStrategies HMM](https://www.quantifiedstrategies.com/hidden-markov-model-market-regimes-how-hmm-detects-market-regimes-in-trading-strategies/); [SSRN 3406068](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID3406068_code3576909.pdf?abstractid=3406068)
  - max_drawdown: -20% (regime-aware) vs -28% (BH) — same source; not Indian-specific
  - sample/period: FTSE100, Euro Stoxx 50, US ETFs 2004–2025; no India HMM study located
**Confidence:** M for the concept; L for India specificity
**Sources:**
- https://www.quantconnect.com/research/17900/intraday-application-of-hidden-markov-models/
- https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID3406068_code3576909.pdf?abstractid=3406068
- https://www.mdpi.com/1911-8074/13/12/311

---

### 12. ML overlays (XGBoost / LightGBM intraday)

**Category:** ML
**Mechanics:** Train gradient-boosted trees on engineered features (returns, vol, microstructure, technicals) to predict next-bar direction or magnitude. Use as signal or as filter on a rules strategy.
**Indian-market applicability:** Tooling is universal; data availability for NIFTY tick/minute bars is good via brokers. Real edge in retail Indian intraday is questionable — feature space tends to be the same as everyone else's.
**Known failure modes (the headline):** overfitting is endemic. Feature space too large → in-sample Sharpe of 3+ collapses out-of-sample. Walk-forward validation often itself overfit by re-tuning hyperparameters. Survivorship and look-ahead bias common. Most published "intraday XGBoost" results don't disclose transaction costs or use proper purged k-fold. Regime shifts (e.g. post-Covid microstructure) break models trained on prior eras.
**Automation feasibility:** 9/10 to deploy; 4/10 to maintain edge.
**Discretion surface:** med (feature engineering is the discretion)
**Cited performance:**
  - win_rate: INSUFFICIENT EVIDENCE for credible intraday Indian-specific
  - profit_factor: INSUFFICIENT EVIDENCE
  - sharpe: INSUFFICIENT EVIDENCE for honest OOS; published numbers from KTH thesis, arxiv on volume/volatility forecasting are forecast-accuracy metrics, not tradeable strategy Sharpe.
  - max_drawdown: INSUFFICIENT EVIDENCE
  - sample/period: arxiv/journal papers focus on volatility/volume forecasting (RMSE), not net-of-cost intraday PnL
**Confidence:** L (and explicitly: most retail ML intraday claims fail when costs and proper OOS are applied)
**Sources:**
- https://arxiv.org/html/2505.08180v1
- https://arxiv.org/pdf/2202.08962
- https://www.degruyterbrill.com/document/doi/10.1515/jisys-2025-0027/html

---

### 13. Pairs / stat-arb on NIFTY constituents

**Category:** stat-arb / mean-reversion
**Mechanics:** Identify cointegrated NSE pairs (e.g. HDFCBANK–ICICIBANK, RELIANCE–ONGC) via Engle-Granger / Johansen; trade z-score of spread (entry ±2σ, exit at 0). Market-neutral by construction.
**Indian-market applicability:** Multiple QuantInsti EPAT projects and academic papers explicitly on NSE pairs. Capital-efficient on the equity side (positions offset) but harder on cash equity intraday due to STT/brokerage on both legs; better as positional / multi-day.
**Known failure modes:** cointegration breaks; one leg dividends/corporate actions; high transaction cost as % of spread profit on Indian intraday; capacity is real but small at retail size.
**Automation feasibility:** 9/10
**Discretion surface:** low
**Cited performance:**
  - win_rate: INSUFFICIENT EVIDENCE per-trade for NSE intraday
  - profit_factor: INSUFFICIENT EVIDENCE
  - sharpe: **1.34** (cointegration-based NSE sectoral pairs, peer-reviewed academia.edu / arxiv [2211.07080](https://arxiv.org/abs/2211.07080)); ~2.28 vendor (Wright Research with 3.5× leverage — not directly comparable); >1.4 for Indian commodity cointegrated pairs ([arxiv 1907.08397](https://arxiv.org/pdf/1907.08397))
  - max_drawdown: INSUFFICIENT EVIDENCE peer-reviewed
  - sample/period: NSE 5 sectors 2018–2020, evaluation 2021 (arxiv 2211.07080); 2015–2025 walk-forward in QuantInsti EPAT blog
**Confidence:** M (best peer-reviewed Indian-market evidence in this survey, after ORB)
**Sources:**
- https://arxiv.org/abs/2211.07080
- https://blog.quantinsti.com/cointegrated-pairs-trading-indian-equity-market-epat-project/
- https://blog.quantinsti.com/pair-trading-statistical-arbitrage-on-cash-stocks/
- https://arxiv.org/pdf/1907.08397
- https://www.wrightresearch.in/blog/pairs-trading-strategy/

---

## Evidence summary

| Strategy | Credible Indian-specific numbers? | Confidence |
|---|---|---|
| 1. ORB | Partial (vendor NIFTY, peer-reviewed US) | M |
| 2. VWAP MR | No | L |
| 3. Supertrend+ADX | No (mechanics only) | L |
| 4. EMA crossover | Marginal vendor numbers (Sharpe ~0.43) | L |
| 5. Donchian/Turtle | No | L |
| 6. Bollinger MR | No | L |
| 7. RSI(2) | Daily US only | M (US) / L (India) |
| 8. NR7/ATR | No | L |
| 9. Short straddle expiry | Vendor only; regime shifted | M |
| 10. Long straddle | No | L |
| 11. HMM/VIX overlay | Concept-strong, no India | M concept / L India |
| 12. ML (XGBoost) | No honest OOS | L |
| 13. Pairs/stat-arb | **Yes, peer-reviewed** Sharpe 1.34 | M |

**Strategies with peer-reviewed/credible academic evidence specifically validated on Indian data: 1 (pairs, arxiv 2211.07080).**
**Strategies with peer-reviewed evidence on adjacent markets that's mechanism-portable: 2 (ORB on US equities, HMM on US/EU).**
**Strategies that are INSUFFICIENT EVIDENCE on most numeric fields: 9 of 13.**
