# 14 — External Strategy Research & Mapping to TITAN

> Review of 7 external sources (user-supplied, 2026-06-22) on trading strategies,
> distilled into: what each offers, the recurring techniques, what TITAN already
> has, and what's genuinely worth adding — cross-referenced with the day's data
> analysis (`docs/analysis/2026-06-22_session_analysis.md`).

## Sources reviewed

| # | Source | What it is | Useful for TITAN |
|---|---|---|---|
| 1 | GeorgeHigham/Intraday-Trading | 3 rule-based intraday strategies (gradient momentum, MA-cross, mean-reversion) on S&P 500 5m | Confirms our core families; gradient/slope as a momentum signal |
| 2 | algobulls/pyalgostrategypool | Strategy pool for the AlgoBulls platform; **same code runs backtest/paper/live** | Validates TITAN's design; strategy menu (below) |
| 3 | iamc1oud/Tradingview-Scripts | Pine scripts: MA, RSI, trendline breaks, S/R+MFI, inside-bar, **Smart Money Concepts**, demarker | Inside-bar, trendline-break, MFI confirmation ideas |
| 4 | sushant1827/Trading_Strategies | Large Python set: **many Supertrend variants**, EMA crosses, RSI+ADX, **ML (KNN/ensemble)**, options; NIFTY/BankNIFTY 5/15/60m | Multi-Supertrend, StochRSI+ADX, ML direction — most directly relevant (Indian indices) |
| 5 | paperswithbacktest/awesome-systematic-trading | Curated taxonomy across asset classes + tools (vectorbt) | Taxonomy: momentum, mean-rev, **pairs/stat-arb**, vol, carry, seasonality |
| 6 | github topics/algorithmic-strategies | Mixed quality (screeners, FIX sims, broker scripts) | Low — mostly infra/screeners |
| 7 | kdnuggets — 10 repos to master quant | StockSharp, **Riskfolio-Lib**, EliteQuant, **TradeMaster (RL)**, QuantMuse, options repos, Howtrader | Riskfolio-Lib (portfolio/risk), TradeMaster (RL) for later |

## The recurring strategy menu (union across all sources)

Trend/breakout: **MA/EMA crossover** (2/3-EMA, golden cross), **Supertrend** (+ double/triple/adaptive/McGinley/kernel variants), **Donchian/trendline breakout**, **Aroon crossover**, gradient/slope.
Mean-reversion/oscillator: **RSI** (overbought/oversold + **divergence**), **Bollinger** (revert + **squeeze**), **Stochastic / StochRSI**, **DeMarker**, VWAP-revert.
Confirmation/filters: **ADX** (trend strength), **MFI/volume**, multi-timeframe, **MACD**.
Volatility/contraction: **Inside-Bar / NR7**, Bollinger squeeze.
Cross-sectional: **pairs trading / statistical arbitrage**.
Options: straddle/strangle/**iron condor**, ladders, butterflies.
ML/RL: **KNN**, ensembles, **reinforcement learning** (TradeMaster).
Portfolio: **risk parity / mean-variance optimization** (Riskfolio-Lib).

## What TITAN already has (covered)

ORB (+confirmed), VWAP-revert (+RSI gate), Supertrend+ADX, MA-crossover, Donchian
breakout, RSI-reversion, Bollinger-reversion, **Bollinger squeeze**, Momentum-ROC,
TSMOM (killed). Unified backtest/paper/live on one `Strategy.on_bar` interface
(same as algobulls). Walk-forward + deflated-Sharpe vetting. vectorbt available.
→ **TITAN's library already covers the bread-and-butter single-indicator families.**

## The cross-cutting lesson (matches our own data)

Every source's better strategies **stack confirmations** — MA+RSI, RSI+ADX,
Supertrend+ADX, MACD+filter, breakout+volume. Today's TITAN data independently
showed the same thing: **`orb_confirmed` (61% win) beat raw `orb` (39%)**. And our
0%-win strategies (`ma_cross`, `supertrend_adx`, `momentum`) are exactly the
**no-target / no-confirmation** ones. So the highest-value move isn't *more*
strategies — it's **adding confirmation + exits to the ones we have.**

## Genuinely-new, worth adding to TITAN (prioritized)

**Tier 1 — slot into the existing factory/registry, high value:**
1. **MACD crossover** (+ histogram) — TITAN has no MACD; a standard, well-evidenced trend/momentum trigger. Add `macd_cross`.
2. **Stochastic / StochRSI + ADX** — oscillator with a trend-strength gate (the confirmation pattern that works). Add `stoch_adx`.
3. **RSI divergence** — price lower-low vs RSI higher-low (the *quality* version of RSI-revert, per source 3/4). Upgrade `rsi_revert` or add `rsi_divergence`.
4. **Multi-Supertrend confirmation** (double/triple) — require 2–3 Supertrends to agree; directly targets our chopped-out `supertrend_adx`. Add `supertrend_multi`.
5. **Inside-Bar / NR7 breakout** — volatility-contraction → expansion (cousin of bb_squeeze). Add `inside_bar`.
6. **Targets/trailing for the no-target strategies** — give `ma_cross`/`momentum`/`supertrend_adx` an ATR target or trailing stop (today they only ever exit at a loss).

**Tier 2 — new capability, bigger build:**
7. **Pairs / statistical arbitrage** — cross-sectional mean-reversion between correlated names. **Our new 50-symbol universe makes this possible** (it was impossible with 2 indices). High value, genuinely different edge.
8. **Portfolio/risk allocator** (Riskfolio-Lib style risk-parity / min-variance) — the multi-strategy capital allocator (also Gemini #10).

**Tier 3 — defer to real-data / Track-B:**
9. **ML/RL direction models** (KNN, ensembles, TradeMaster RL) — only meaningful on real, non-stationary data; pairs well with the HMM/GMM regime work.
10. **Options strategies** (iron condor / straddle) — needs the options-routing layer (not built).

## Recommendation

Don't bulk-import strategies. The data says **confirmation + exits beat breadth**.
Best sequence:
1. Add **targets/trailing** to the 0%-win strategies and re-measure (cheap, directly fixes the biggest losers).
2. Add **MACD-cross**, **StochRSI+ADX**, **multi-Supertrend**, **RSI-divergence**, **inside-bar** as new factory families (reuses our vetting harness).
3. Build **pairs/stat-arb** to exploit the 50-symbol universe.
4. Then the real-data backfill → walk-forward → only survivors go live.

*All of this stays gated behind walk-forward on REAL data before any live use —
synthetic results (good or bad) are plumbing checks, not verdicts.*
