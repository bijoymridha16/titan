# 09 — Roadmap Analysis (5 requirements)

> **Status: ANALYSIS ONLY — nothing here is executed.** This is the deep-dive
> the work was paused to produce: each of the five requirements examined from
> ten angles, with my engineering input, a concrete (un-executed) plan, the
> open decisions that must be made first, and an effort estimate.
> **Date:** 2026-06-16. Audited against commit `6f51113` + the uncommitted
> decision-engine / honest-clock / profit-lock work.

How to read each point: **Ask → Intent → 10-lens analysis → My input → Plan →
Open decisions → Effort.** The 10 lenses are fixed so every point gets the same
rigor: `1 Intent · 2 Current state · 3 Feasibility · 4 Indian-market reality ·
5 Architecture impact · 6 Risks/conflicts · 7 Data/storage · 8 Cost/limits/
compliance · 9 Edge cases · 10 Verdict`.

---

## Point 1 — "Keep only NIFTY and SENSEX, remove everything else"

**Ask:** Trade only NIFTY and SENSEX; drop BANKNIFTY, FINNIFTY, RELIANCE, HDFCBANK, ICICIBANK.

**Intent:** Narrow the universe to the two flagship Indian indices.

**10-lens analysis**
1. **Intent.** Reduce scope to two instruments. Simple at the config layer (`TITAN_UNIVERSE`); deceptively hard at the execution layer.
2. **Current state.** Universe = `NIFTY,BANKNIFTY,FINNIFTY,RELIANCE,HDFCBANK,ICICIBANK`. `resolve_universe()` resolves NSE index (`AMXIDX`) and NSE equities (`-EQ`) only. `feed.py` already supports BSE (`EXCH_CODE["BSE"]=3`). Order path `angelone.py` gate-3 + `TITAN_ALLOWED_EXCHANGES=NSE` block anything non-NSE.
3. **Feasibility.** Config change is one line. **The catch: SENSEX is a BSE index, NIFTY is an NSE index — and *indices are not directly tradable*.** You cannot "buy NIFTY". You trade a derivative (futures/options) or an ETF.
4. **Indian-market reality (the crux).** At ₹5,000 capital:
   - **Index futures** — NIFTY/SENSEX futures margin is ~₹1–1.5L for 1 lot. **Impossible at ₹5K.**
   - **Index options** — buying 1 lot of a weekly ATM option can cost ₹3k–₹15k premium; *sometimes* fits ₹5K for cheap OTM/expiry-day. This is the only realistically tradable form — but it's **options**, with strike selection, expiry, premium decay, and Greeks. Our strategies signal on the *underlying price*, not option premium.
   - **ETFs** — NIFTYBEES (NSE) is liquid and cheap (~₹250/unit) → tradable at ₹5K. For SENSEX, ETFs exist (e.g. BSE Sensex ETFs) but are far less liquid; intraday fills are questionable.
   - **NIFTY is NSE, SENSEX is BSE.** Supporting SENSEX means enabling **BFO/BSE** across exchange whitelist, instrument resolution, and order routing — today all NSE-only.
5. **Architecture impact.** Touches: `config.universe`, `instruments.resolve_universe` (add BSE index + a strike/expiry resolver if options), `angelone.py` gates (allow BSE/BFO, product types), `TITAN_ALLOWED_EXCHANGES`, and — if options — a **new options-execution layer** (option chain fetch, strike selector, expiry roll, premium-based sizing). The strategies themselves can stay price-on-underlying *if* we add a signal→option-contract mapper.
6. **Risks/conflicts.** "Keep only NIFTY+SENSEX" silently assumes they're tradable like stocks — they aren't. Picking options changes risk shape entirely (a long option can go to zero; the per-trade-risk model and SL semantics differ). Mixing NSE+BSE doubles the data/holiday/calendar surface.
7. **Data/storage.** Need BSE index ticks (feed.py supports it) + option-chain snapshots if trading options. OHLCV schema is fine; add an `instrument_kind` so analytics can tell index/option/ETF apart.
8. **Cost/limits/compliance.** BSE/BFO data may need a separate Angel subscription; option lot sizes are SEBI-revised periodically (post-Oct-2024 reforms hit index options hardest). Verify current NIFTY (lot 75) and SENSEX (lot 20) sizes before sizing math.
9. **Edge cases.** Expiry-day liquidity/cliffs; index ≠ tradable token mismatch; BSE holiday calendar differs subtly; SENSEX ETF illiquidity → paper fills look great, live fills slip badly.
10. **Verdict.** **Two-track.** (a) *Signal/paper track* — set universe to NIFTY+SENSEX as **index price series** and paper-trade them notionally now (validates strategies immediately, no blocker). (b) *Real-execution track* — decide the instrument (NIFTY weekly options + SENSEX weekly options is the only ₹5K-viable directional path) and build the options-routing layer **before** live. Don't conflate the two.

**My input**
- The honest framing: *"trade NIFTY & SENSEX"* at ₹5K = *"trade NIFTY & SENSEX **weekly options***" (buy-side, defined risk = premium). Recommend **long-option-only** to cap risk (no naked selling — aligns with the ₹5K capital-preservation mandate in `docs/02`).
- Keep strategy logic on the **underlying index**; add a thin **`signal → ATM/ITM option contract`** resolver + premium-based sizing. This reuses all existing strategy code.
- For paper validation *right now*, trade the index notionally — zero new infra — and defer options routing to the pre-live phase.
- Add `instrument_kind` (INDEX / OPTION / ETF / EQ) to the data model from the start (point 5 synergy).

**Plan (not executed)**
1. `TITAN_UNIVERSE=NIFTY,SENSEX`; add SENSEX (BSE index) to `resolve_universe` (BSE `AMXIDX`/index token).
2. Enable BSE in `allowed_exchanges` **only when** options routing exists (keep NSE-only until then).
3. New module `titan/execution/option_router.py`: fetch chain, pick weekly ATM±, size by premium ≤ per-trade risk, map underlying signal → option order.
4. Backtest/paper on index series first; gate options routing behind the live-readiness checklist.

**Open decisions**
- **D1 (blocking):** Instrument for real trading — weekly **options** (recommended), **ETF** (NIFTYBEES works; SENSEX ETF weak), or **index-notional paper only** for now?
- **D2:** Enable BSE/BFO now or stay NSE-only until options layer is built?

**Effort:** Universe config **S** · index-paper **S** · BSE+options real routing **XL**.

---

## Point 2 — "Fix the UI: see trades on the graph, modern, not generic"

**Ask:** Better dashboard; show live trades on the chart; a modern (non-generic) look.

**Intent:** Trade markers/overlays on the candlestick chart + a visually premium, real-time terminal feel.

**10-lens analysis**
1. **Intent.** Two things: (a) *trade visibility on chart* (entry/exit markers, SL/TP lines), (b) *aesthetic/UX upgrade* beyond stock Streamlit.
2. **Current state.** `dashboard/app.py` (Streamlit + Plotly): candles + VWAP + volume, dark theme, ticker tape, KPI strip (now with profit/loss/regime), tabs. No trade overlays on the chart. 5s full-rerun via `st_autorefresh`.
3. **Feasibility.** Trade markers = **easy** (Plotly scatter: ▲ entry / ▼ exit at trade price+ts from the `trades` table, dashed SL/TP lines, entry→exit connector colored by P&L). Aesthetic upgrade = **medium→large** depending on ambition.
4. **Indian-market reality.** Traders expect a TradingView-grade chart. Streamlit's generic chrome reads as "dashboard", not "trading terminal". Bridging that gap is the real ask.
5. **Architecture impact.** Incremental: more Plotly traces + CSS (low risk). Ambitious: embed **TradingView Lightweight Charts** via a Streamlit custom component, or rebuild the front-end (React/Next) on the existing FastAPI. The API already exposes control endpoints; a React SPA + WebSocket push is the "modern, real-time" end-state.
6. **Risks/conflicts.** Streamlit's full-page 5s rerun fights "live" feel and **resets the active tab to Charts** (st.tabs renders all tabs; selection isn't persisted — a real, pre-existing quirk). True real-time needs WebSocket push, which Streamlit resists. Over-investing in Streamlit may be throwaway if we later rebuild.
7. **Data/storage.** Trade markers need per-trade entry/exit ts+price (already in `trades`). Live overlay of *open* positions needs the open-trade rows (exist). No new storage.
8. **Cost/limits.** TradingView Lightweight Charts is free/open-source (Apache-2). React rebuild = real dev cost. Plotly upgrade = near-zero.
9. **Edge cases.** Marker time-axis must match candle tz (IST vs UTC — same bug class as ORB's tz handling); dense markers on long windows; synthetic vs real bars.
10. **Verdict.** **Phase it.** Phase A (now, high ROI): trade markers + SL/TP lines + open-position overlay + equity/drawdown panel + fix tab-reset, all in Plotly/Streamlit. Phase B (if "modern" means premium): TradingView Lightweight Charts custom component. Phase C (only if needed): full React/Next front-end.

**My input**
- Phase A is ~1 day and delivers 80% of the perceived value (seeing your trades on the chart). Do it first.
- Replace `st.tabs` with a query-param or `streamlit-option-menu` nav to kill the tab-reset-on-refresh annoyance.
- For "modern", TradingView Lightweight Charts (Phase B) gives the genuine terminal look without a full rebuild — best effort/value ratio.
- Add: per-trade hover (strategy, R-multiple, reason), a session P&L sparkline, and a "regime ribbon" under the chart (color band = TREND/RANGE/CRISIS over time) — ties the decision-engine into the UI visually.

**Plan (not executed)**
1. Plotly: add entry ▲ / exit ▼ markers, dashed SL/TP, entry→exit connector (green/red), from `trades` for the selected symbol.
2. Overlay open positions (live) + an equity-curve & drawdown subplot.
3. Fix tab persistence; refine spacing/typography; add regime ribbon.
4. (Phase B) Prototype TradingView Lightweight Charts component; (Phase C) scope React rebuild only if A+B insufficient.

**Open decisions**
- **D3:** Ambition level — Phase A only / A+B (TradingView) / full rebuild?

**Effort:** Phase A **M** · Phase B **M-L** · Phase C **XL**.

---

## Point 3 — "Fetch 50+ strategies from the internet; run all on paper before live"

**Ask:** Source 50+ strategies; run them all in paper; promote winners to live.

**Intent:** A broad strategy library, vetted in paper, with survivors graduating to real money.

**10-lens analysis**
1. **Intent.** Breadth of edges + a funnel that only lets proven ones reach capital.
2. **Current state.** 4 strategies coded (`orb` validated; `vwap_revert`/`supertrend_adx` unvalidated; `tsmom` killed). Strong existing discipline: **predeclared walk-forward ship/kill, no tuning** (`scripts/run_tsmom_backtest.py`, `docs/01-02`). The auto-pilot already enforces a **validated allowlist** — the perfect graduation mechanism.
3. **Feasibility.** Coding 50 strategies is bounded if done as **parametrized families** (one Breakout class × params = many variants) rather than 50 bespoke files. Running 50 in paper is compute-cheap; the hard parts are vetting and capital allocation.
4. **Indian-market reality.** Most "internet strategies" are vendor/blog claims with survivorship bias, no OOS, no cost modeling. SEBI 2024: 93% of F&O traders lose. Evidence quality must be tracked (peer-reviewed > vendor > blog), exactly as `docs/02` already does.
5. **Architecture impact.** Need: (a) a **strategy plugin SDK** (drop-in `Strategy` subclass + auto-registration, removing the hardcoded `STRATEGIES` dict), (b) a **strategy factory** for param families, (c) a **mass walk-forward harness** + **leaderboard** table, (d) a **portfolio allocator** (max-concurrent-positions=3, ₹5K capital — can't run 50 live at once), (e) a **correlation filter** (many strategies are near-duplicates).
6. **Risks/conflicts (critical).** **Multiple-testing / data-dredging:** test 50 strategies, pick the best on the same data → you *will* find false winners. **Must** apply OOS persistence across folds + a multiple-comparison haircut (deflated Sharpe / Bonferroni-style). This is the #1 quant trap and the single most important safeguard for this point. Also: running 50 simultaneously in *paper* needs per-strategy capital sleeves or the position-limit starves most of them (skewing results).
7. **Data/storage.** Every strategy's every signal (incl. rejected) + per-fold backtest metrics must be stored (point 5 synergy) → the leaderboard *is* the analytics layer.
8. **Cost/limits/compliance.** SEBI algo-trading rules: many automated strategies placing orders may require broker-approved/registered algo (note `ALGO_ID` already in env). Flag before live.
9. **Edge cases.** Strategies on different timeframes (need `1d` bars published — open finding M1); correlated signals firing together breaching risk caps; look-ahead bugs in ported code; cost model must be applied uniformly (the backtester already does).
10. **Verdict.** **Don't hand-port 50 blog strategies.** Build a **strategy SDK + factory (families) + mass walk-forward + leaderboard + multiple-testing correction + portfolio allocator**, generate 50+ *variants* across well-understood families, vet them honestly, and let the auto-pilot's validated allowlist be the live gate. This scales and stays disciplined.

**My input**
- Reframe "fetch 50 from internet" → "**generate 50+ vetted variants across a curated taxonomy**": ORB (timeframes/targets), Donchian, Keltner, Bollinger-MR, RSI(2)/Connors, MACD, Supertrend, VWAP-trend, VWAP-revert, opening-drive, gap-fade/-go, NR7/inside-bar, momentum, pairs/stat-arb. Families → dozens of variants from a few classes.
- **Hard gate:** a strategy reaches the auto-pilot allowlist only after passing walk-forward on **multiple OOS folds** with a **deflated-Sharpe** haircut. Encode the thresholds, predeclared, no tuning.
- Add a **portfolio/capital allocator** + **correlation cluster filter** so survivors aren't 10 copies of the same edge.
- The leaderboard table feeds both point 5 (analytics) and the dashboard (a "Strategy Lab" tab).
- Honest expectation: of 50 variants, history says a handful survive OOS. The funnel's job is to *find those few and kill the rest* — not to run 50 live.

**Plan (not executed)**
1. Strategy SDK: auto-discovery registry (replace hardcoded `STRATEGIES`); metadata (family, evidence tier, params, source).
2. Strategy factory: param-grid → variants.
3. Mass walk-forward harness (reuses `backtest/engine.py`) → `strategy_results` + `leaderboard` tables; deflated-Sharpe / multi-fold persistence.
4. Portfolio allocator + correlation filter; capital sleeves for multi-strategy paper.
5. Promotion job: leaderboard survivors → `TITAN_AUTOPILOT_VALIDATED`.
6. "Strategy Lab" dashboard tab.

**Open decisions**
- **D4 (blocking):** Generate variants from curated families (recommended) vs literally hand-port 50 named internet strategies?
- **D5:** Promotion thresholds (OOS Sharpe, folds, deflated-Sharpe cutoff, max correlation) — predeclare them.
- **D6:** Publish `1d` bars (finding M1) to enable daily-timeframe strategies?

**Effort:** SDK+factory **M** · mass walk-forward+leaderboard **L** · portfolio/correlation **L** · 50 variants **M** → overall **XL**.

---

## Point 4 — "Simulator should work with the real market only, but paper trading"

**Ask:** No synthetic data. Use the *real* live market feed, but fills are paper.

**Intent:** Real Angel One ticks during real market hours → strategies → **paper** fills. Retire the fake feed/clock.

**10-lens analysis**
1. **Intent.** "Realistic rehearsal": real prices, real timing, simulated money. This is *forward paper trading on live data*.
2. **Current state.** `feed.py` is a real SmartAPI WebSocket V2 consumer (already exists, BSE-aware). Honest market-hours gate (just built) already blocks trading when NSE is closed. `PaperBroker` already fills against real LTP. So **most of this is already in place** — the synthetic feed + sim-clock are the things to retire from the live path.
3. **Feasibility.** High. Swap `synth_feed` → `feed.py`; keep `PaperBroker`; default `TITAN_SIM_MODE=0` (honest clock). The pipeline is unchanged downstream.
4. **Indian-market reality.** Real feed only ticks 09:15–15:30 weekdays; auto-pilot will correctly sit in `CLOSED` otherwise (already verified). Need Angel creds + feed_token (wired) + instrument tokens loaded (`instruments.py`).
5. **Architecture impact.** Minimal code; mostly operational: run `feed.py` instead of `synth_feed`. Add a **feed lifecycle manager** (auto-connect 09:15, disconnect 15:30, reconnect-on-drop) and a **data-quality/staleness monitor**. Decide the fate of `synth_feed`/`sim_mode`.
6. **Risks/conflicts.** This **supersedes the sim-mode clock I just added** — in the desired end-state `sim_mode` is effectively always OFF; synthetic is at most an *offline-replay dev tool*, clearly walled off from the live/paper path. WS reliability (drops, token expiry at ~23h, rate limits) becomes real. Paper fills on real LTP can be optimistic (no real queue/impact) — keep the pessimistic slippage model.
7. **Data/storage.** Real ticks should be archived (point 5) for replay/backtests — this is how you build a real historical dataset instead of synthetic.
8. **Cost/limits/compliance.** Angel WS token limits (per-connection token cap), feed subscription scope (BSE for SENSEX), JWT 23h refresh. Free with the account.
9. **Edge cases.** Half-days/holidays (no holiday calendar yet — weekend-only check); WS silent stalls (need staleness watchdog); first-tick-of-day warmup; reconnect storms.
10. **Verdict.** **Straightforward and already 80% built.** Make `feed.py` the default source, retire synthetic from the live path, add lifecycle + staleness monitoring. This is the cleanest of the five and reinforces the honest-clock work.

**My input**
- Build `titan/data/feed_supervisor.py`: auto start at 09:15 / stop at 15:30 IST, exponential-backoff reconnect, JWT/feed-token refresh, and a `titan:feed:stale` watchdog → dashboard alert.
- Keep `synth_feed` **only** as an explicitly-labeled offline/replay dev tool; remove it from any "rehearsal" path. Consider renaming sim_mode → `replay_mode` to avoid confusion now that "simulation = real-data paper".
- Archive every real tick (compressed) → real historical dataset for point 3 backtests.
- Integrate a (lightweight) **NSE/BSE holiday calendar** so the gate is correct on holidays, not just weekends (current `is_trading_day` is weekday-only — documented limitation in `clock.py`).

**Plan (not executed)**
1. Default runbook: `feed.py` (not synth); `TITAN_SIM_MODE=0`.
2. Feed lifecycle manager + staleness watchdog + dashboard health.
3. Tick archival to TimescaleDB (compressed) / Parquet.
4. Holiday calendar in `clock.is_trading_day`.
5. Smoke-test live login + WS during market hours with real creds.

**Open decisions**
- **D7:** Remove `synth_feed`/`sim_mode` entirely, or keep as labeled offline-replay only (recommended)?
- **D8:** Archive *every* tick (storage cost) or downsample/compress?

**Effort:** Swap-to-real **S** · lifecycle+watchdog **M** · holiday calendar **S** · tick archival **M**.

---

## Point 5 — "Store every piece of data — for analytics before going live"

**Ask:** Persist everything, to analyze before committing real money.

**Intent:** A complete, queryable record of market data, signals, decisions, orders, fills, and outcomes → the evidence base for the paper→live decision.

**10-lens analysis**
1. **Intent.** Full observability + an analytics substrate; nothing ephemeral that matters to the go-live call.
2. **Current state.** Stored: `ohlcv`, `trades`, `orders`, `equity_curve`, `risk_events`, `news_*`, and the new `regime_decisions`. **Ephemeral (lost) today:** every *signal* (only filled ones become trades), *rejected* orders' full context, the *feature vector* at decision time, realized-vs-modeled slippage, raw ticks.
3. **Feasibility.** High — additive tables + a few write calls. TimescaleDB is already the backbone (hypertables + compression).
4. **Indian-market reality.** To trust a strategy with real money you need: hit rate, PF, OOS Sharpe, slippage realism, regime-conditioned performance, and *why-we-didn't-trade* (rejected signals). That requires capturing far more than just closed trades.
5. **Architecture impact.** New tables: `signals` (ALL, incl. rejected + reject reason + feature snapshot), `order_attempts` (every risk decision), `fills` (realized slippage), `feature_snapshots` (indicators/window at decision time — ML-ready), optional `ticks_archive`. Add write-throughs in router/supervisor/risk. Add retention + compression policies. Add an export job (Parquet) + a DuckDB/notebook analytics surface.
6. **Risks/conflicts.** "Store everything" naively = tick storage explosion if options chains are added later. Need retention/compression and sampling decisions up front. Write-amplification on the hot path must stay async/non-blocking (the regime/session writes already swallow errors so they never block trading — same pattern).
7. **Data/storage sizing.** 2 index symbols of ticks/day ≈ small (MBs). Full option chains or many symbols ≈ large (GBs/yr) → Timescale native compression + 30–90d hot / Parquet cold.
8. **Cost/limits/compliance.** Disk only (local/Docker volume). Keep an immutable audit trail (regime_decisions already is) — also useful for any SEBI algo audit.
9. **Edge cases.** Schema drift as strategies evolve (use JSONB feature blobs for flexibility, like `risk_events.detail`); clock/tz consistency across tables (store tz-aware UTC); dedupe on replays.
10. **Verdict.** **The connective tissue for points 3 & 4.** Capture signals + decisions + features + fills now (cheap, high value); tick archive with compression; Parquet/DuckDB for offline analysis. This *is* the paper→live evidence base.

**My input**
- Highest-value, lowest-cost first: a **`signals` table that logs ALL signals including rejected ones with the reject reason** — today we're blind to "what we skipped and why", which is exactly what you need before risking money.
- Add a **`feature_snapshots`** JSONB table (indicators/window at decision time) — future-proofs ML without schema churn.
- Enable **Timescale compression + retention**; nightly **Parquet export** + a **DuckDB analytics notebook** (`docs/` or `notebooks/`).
- Define a single **"promotion dataset" view** that the paper→live gate (and point 3 leaderboard) reads from — one source of truth for the go-live decision.
- Reuse the error-swallowing write pattern (never block the trading loop on a log write).

**Plan (not executed)**
1. Migration `005_analytics.sql`: `signals`, `order_attempts`, `fills`, `feature_snapshots`, optional `ticks_archive`; hypertables + compression + retention.
2. Write-throughs: router (every decision), supervisor (every signal incl. rejected), broker (realized slippage).
3. Nightly Parquet export + DuckDB notebook; a `promotion_dataset` SQL view.
4. Dashboard "Analytics" tab (rejected-signal funnel, slippage realized-vs-model, regime-conditioned P&L).

**Open decisions**
- **D9:** Archive raw ticks (yes, compressed, recommended) or only bars + signals?
- **D10:** Hot-retention window before Parquet cold storage (30/60/90d)?

**Effort:** schema+write-throughs **M** · compression/retention **S** · Parquet/DuckDB **M** · analytics tab **M**.

---

## Cross-cutting: dependencies, sequencing, and the decisions that block everything

**Dependency graph**
```
        ┌─────────────────────────────────────────────┐
        │  P4 real-data paper feed  (foundational)      │
        └───────────────┬───────────────┬──────────────┘
                        │               │
              ┌─────────▼───┐     ┌──────▼─────────────┐
              │ P5 store     │     │ P1 real instrument │
              │ everything   │     │ (NIFTY/SENSEX opt) │
              └─────┬────────┘     └────────────────────┘
                    │
          ┌─────────▼───────────────┐
          │ P3 strategy SDK + mass   │   ← vetting runs ON P4 real data,
          │ walk-forward + leaderbd  │     stored BY P5, promoted to auto-pilot
          └──────────────────────────┘
   P2 (UI) is independent — can proceed in parallel anytime.
```

**Recommended sequence:** **P4 → P5 → P3 → P1 → (P2 throughout).**
Real data first (P4), so everything downstream is real; capture it (P5); use it to vet strategies (P3); then solve real-instrument routing (P1) for the survivors before live; improve the UI (P2) continuously.

**The four decisions that unblock real work (in priority order)**
- **D1 — How do we actually trade NIFTY & SENSEX at ₹5K?** (weekly options recommended / ETF / index-notional-paper-only). *Biggest scope driver; blocks live, not paper.*
- **D4 — Strategy sourcing:** curated param-family variants (recommended) vs hand-port 50 internet strategies. *Plus D5 promotion thresholds incl. multiple-testing correction.*
- **D7 — Retire synthetic feed?** (keep as labeled offline-replay only, recommended) — confirms P4's end-state.
- **D3 — UI ambition:** Plotly Phase-A / +TradingView / full React rebuild.

**My one strong opinion across all five:** the highest-leverage, lowest-risk path is **P4 + P5 first** (real-data paper + full data capture) — they're mostly built, they're honest, and they create the evidence base. Then P3 as a *disciplined variant factory with multiple-testing correction* (not a blind 50-blog import). P1's options-routing and P2's UI are real but should follow, not lead. The one trap to avoid at all costs is **P3 without P5's rejected-signal capture and without a deflated-Sharpe gate** — that's how a 50-strategy paper run produces confident, false winners and loses real money.

**Effort summary:** P1 S→XL · P2 M→XL · P3 XL · P4 S→M · P5 M.
