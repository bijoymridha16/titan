# 10 — Changes & Decisions Log

> Record of the fixes and the judgement calls made while executing the roadmap
> (`docs/09`). Companion to `AUTOPSY_FINDINGS.md`. Date: 2026-06-17.
> **Status of the test suite at time of writing: all green.**

---

## A. AUTOPSY findings fixed (with how)

### H1 — unvalidated strategies could be enabled
- **Auto-pilot path:** `titan/decision/selector.py` can only ever enable strategies in the validated set (`target_for(reading, validated)`), now resolved from Redis `titan:autopilot:validated` with `.env` fallback.
- **Manual path (newly closed):** `POST /strategies/{name}/start` returns **409** unless the strategy is validated; `?force=true` overrides for deliberate experimentation. Killed strategies are always blocked.

### M1 — `1d` bars never published
- `bar_writer.TIMEFRAMES` and `aggregator._TF` now include `"1d": 86400`. The supervisor already subscribed to `1d`; daily-timeframe strategies (e.g. TSMOM) can now receive bars.
- **Caveat (documented in code):** the `1d` bucket aligns to UTC midnight, not the IST session. Good enough for daily-trend strategies; a session-aligned daily roll-up is a future refinement.

### M2 — strategy `EXIT` signals were dropped
- The supervisor now honours `SignalKind.EXIT`: if the (strategy, symbol) has an open trade, it closes it at the bar close via a new shared `_close_trade()` method (the same path SL/TP exits use). Exit signals with no open position are recorded as rejected with a clear reason.

### M3 — `confidence` never affected sizing
- `fixed_fractional_qty(..., confidence)` scales the risk budget by `signal.confidence`, clamped to **[0.1, 1.0]** (low conviction → smaller sleeve, never zero from conviction alone; never upsizes beyond the risk budget). The router passes `signal.confidence`. `Signal.confidence` doc updated.

### M4 — `atr_position_size` was dead code
- **Removed** (and its tests). Rationale: every strategy supplies an explicit stop, so `fixed_fractional_qty` on `|entry − stop|` already achieves ATR-equivalent risk sizing. One sizer, one code path. New tests cover the confidence behaviour instead.

### M5 — two backtest engines
- `bt_runner.py` **deleted**. `backtest/engine.py` is the single authoritative event-driven backtester. `vbt_runner.py` comments updated to reference it.

### L1–L3 — doc drift
- L1: README now says **11** gates (kill, market-hours, cutoff, daily-loss, daily-profit, weekly-loss, drawdown, consecutive-losses, concurrent-positions, per-trade-risk, funds).
- L2: README "What TITAN does" lists ORB + the 59-variant vetting library + auto-pilot.
- L3: `synth_feed` timing comment corrected (2 ticks = 1 sim-minute; 5m bar ≈ 2 real seconds).

### L4 / L5 — undeclared dependencies (fixed earlier)
- `rapidfuzz` and `streamlit-autorefresh` added to `pyproject.toml`.

---

## B. Tech-debt items fixed

### Backtester margin model
- Position size is capped by **leverage** (`notional ≤ equity × leverage`, default 5× MIS) so a single trade can't be sized beyond what the account could carry.
- A **ruin guard** stops trading once equity ≤ 0 (account blown) instead of letting equity go negative.
- `summarize()` CAGR is guarded against non-positive equity (was producing `NaN` via a fractional power of a negative number). This is what caused the >100% drawdowns and the `RuntimeWarning` in the first vetting run.

### Promotion automation (leaderboard → live-eligible)
- `walk_forward.py --promote` writes SHIP survivors to the Redis `titan:autopilot:validated` set.
- The selector and the API both read that set (Redis-first, `.env` fallback), so a walk-forward run can make winners auto-pilot-eligible with no manual env edits. No survivors → the allowlist is cleared (nothing earns a live slot by default).

### Real historical backfill (verified)
- `titan/data/backfill.py` (Angel `getCandleData`, paged, rate-limited, idempotent) already existed; it had never been run. Verified end-to-end: loaded the 172k-row scrip master, then fetched **35 real RELIANCE daily bars**. P3 vetting can now run on real data, not synthetic.

---

## C. Decisions (the ones delegated to me — with rationale)

### D1 — how to trade NIFTY/SENSEX at ₹5K → **configurable, default ETF**
- New `TITAN_INSTRUMENT_KIND` (`ETF` default | `OPTION` | `INDEX` | `EQUITY`) + `config/instrument_map.yaml` (NIFTY→NIFTYBEES, BANKNIFTY→BANKBEES, SENSEX→SENSEXBEES) + resolver `titan/data/instrument_kind.py`.
- **Why ETF default:** it is the only index exposure genuinely tradable at ₹5K on the NSE cash path today (NIFTYBEES ≈ ₹250/unit), and it reuses the existing equity order path — no new options-routing layer required to start. `OPTION` (weekly ATM) is mapped but its strike/expiry router is explicitly future work; `INDEX` is paper-only (not directly tradable). **SENSEX is a BSE index** — its ETF/options need `TITAN_LIVE_ALLOWED_EXCHANGES` to include BSE/BFO before live.

### D3 — UI → **full React rebuild** (scaffolded; see §D)
- The user chose a full React rebuild. A production React/Next app replacing the Streamlit dashboard is genuinely multi-session work, so this is delivered as a **scaffold + migration plan**, with Streamlit remaining the live UI until the rebuild reaches parity. Doing otherwise would mean shipping a half-working UI over real-money logic. See `frontend/README.md`.

### D4 / D5 — strategy sourcing & promotion thresholds → **predeclared, in code**
- Sourcing: parametrized variant families (59 variants), not hand-ported blogs (chosen earlier).
- Thresholds (predeclared in `walk_forward.py`, no post-hoc tuning): min 30 OOS trades, profit factor ≥ 1.10, max drawdown ≤ 25%, profitable on ≥ 60% of symbols (persistence), and OOS Sharpe above the **deflated** bar `σ·√(2·lnN)` (the level a best-of-N fluke reaches by chance).

### D7 — synthetic feed → **keep as explicit, labeled offline-replay**
- Not deleted. It's useful for dev/CI when the market is closed, and it's already firewalled behind explicit `TITAN_SIM_MODE`/`titan:sim:enabled` with loud 🧪 labeling. The **real** feed (`feed_supervisor`) is the documented default.

### D8 / D9 / D10 — tick archival & retention → **deferred, documented**
- Decision: **do not** archive raw ticks yet. Rationale: at the current 2-index universe the analytics value is low and the storage/write cost is real; the bar + signal + fill + feature capture (P5) already covers the pre-live evidence need. When the universe grows or options chains are added, add a compressed `ticks_archive` hypertable with a 90-day hot / Parquet-cold retention split. Logged here so the omission is explicit, not silent.

---

## D. React rebuild — scope & plan (foundation, not finished)

A complete replacement of the Streamlit dashboard is staged in `frontend/` with a
documented migration plan. **Streamlit remains the working UI.** The plan:

1. **Backend**: the FastAPI control plane already exposes `/status`, `/autopilot`,
   `/sim`, `/strategies`, `/kill`, `/flatten`. Add read endpoints the React app
   needs (bars, trades, positions, journal, analytics, leaderboard) — thin wrappers
   over the same queries the Streamlit app runs today.
2. **Frontend**: React + Vite + TypeScript; TradingView **Lightweight Charts** for
   the candlestick + trade overlays (the genuinely "modern" terminal look D3 wants);
   a WebSocket/SSE channel for live ticks (kills Streamlit's 5s full-rerun + the
   tab-reset quirk).
3. **Parity checklist**: header/regime pills, KPI strip (incl. daily-profit lock),
   chart with trade markers, Positions, Journal, Strategies (+ auto-pilot control),
   Analytics, Risk (kill/flatten), System.
4. **Cutover**: run both UIs in parallel; switch the default port once parity +
   sign-off; retire Streamlit.

Until parity is reached, **use the Streamlit dashboard** (`:8501`) — it has every
feature wired and tested.

---

## E. Still open (explicitly)
- Live tick **streaming** unverified until market open (auth/feed-token path is verified).
- React app is a **scaffold**, not feature-complete.
- OPTION execution routing (strike/expiry selection) — mapped but not built.
- P3 verdicts are only meaningful once vetting runs on **backfilled real history** (now possible) rather than synthetic data.
