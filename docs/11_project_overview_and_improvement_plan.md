# 11 — TITAN: System Specification, Status & Improvement Plan

> Technical reference for the whole system: scope, goals, architecture, full
> flow charts, a subsystem-by-subsystem spec (exact thresholds, formulas, Redis
> keys, DB schema, API surface), current status, and the improvement backlog.
> Written 2026-06-20; numbers cross-checked against source on that date — if code
> and doc disagree, code wins, fix the doc. Companions: `docs/03` (architecture),
> `docs/06` (risk), `docs/08` (automation), `docs/09` (roadmap analysis),
> `docs/10` (changes & decisions), `AUTOPSY_FINDINGS.md`.

---

## 1. Scope

Event-driven intraday algo-trading system for NSE. Pipeline: ingest ticks →
aggregate OHLCV → strategies emit signals → risk engine gates → broker fills →
persist + observe. Target deployment: ₹5,000 live capital via Angel One SmartAPI.
Current state: **paper-mode rehearsal** (no live capital). Core invariant:
backtest, paper, and live share the same `Strategy` interface and the same
`RiskEngine` — paper-validated behaviour is what runs live.

Runtime topology: 5 long-lived processes (feed/feed_supervisor, bar_writer,
supervisor, FastAPI `:8000`, Streamlit `:8501`) + optional auto_pilot process;
state plane is Redis (control/keys/streams) + TimescaleDB/Postgres (durable).

---

## 2. Goals & status

Maps to the five requirements in `docs/09`.

| # | Goal | Scope | Status |
|---|------|-------|--------|
| **G1** | Trade NIFTY & SENSEX at ₹5K | Indices not directly tradable at ₹5K; resolve instrument (ETF now / weekly options later) + routing layer. | ⚠️ ETF mapping done; options routing not built |
| **G2** | Real-time UI with trade overlays | TradingView-grade terminal: candles + trade markers + live push. | ⚠️ Streamlit working; React rebuild scaffold only |
| **G3** | 50+ strategies vetted → promote winners | Variant library + mass walk-forward + multiple-testing correction + leaderboard → validated allowlist. | ✅ Engine built (59 variants); needs real-data runs |
| **G4** | Real feed, paper fills | Real Angel One WS during session → PaperBroker; retire synth from live path. | ✅ Feed + supervisor built; live streaming unverified until market open |
| **G5** | Capture everything for pre-live analytics | Persist every signal/decision/order/fill incl. rejected + feature vectors. | ✅ Capture + schema built |

**Exit criterion (paper → live):** a strategy that clears the walk-forward gate
(§5.9) on real backfilled history, accrues real-data paper evidence (§5.10),
passes all 6 readiness gates (`scripts/readiness_check.sh`), under live dry-run
shadow for ≥1 week, with kill switch reachable.

---

## 3. Subsystems

| Subsystem | Folder | What it does |
|-----------|--------|--------------|
| **Data feed** | `titan/data/feed.py`, `feed_supervisor.py`, `synth_feed.py` | Brings in live ticks (real Angel One WS, or a labelled synthetic feed). Supervisor auto-manages it around market hours. |
| **Bar writer** | `titan/data/bar_writer.py`, `aggregator.py` | Turns raw ticks into 1m/3m/5m/15m/1d OHLCV candles in TimescaleDB. |
| **Strategies** | `titan/strategies/` | The trading logic: ORB (validated), 4 named strategies, a 59-variant library, factory, registry, indicators. |
| **Decision engine** | `titan/decision/` | The "auto-pilot": classifies market regime and auto-selects which *validated* strategies to run. |
| **Risk engine** | `titan/risk/` | 10 safety gates + per-trade-risk sizing + funds check on every order. |
| **Execution** | `titan/execution/`, `titan/brokers/` | Routes approved orders to the paper broker (always) or Angel One (shadow/live, 5 more gates). |
| **Backtest** | `titan/backtest/` | Event-driven backtester + walk-forward vetting harness with predeclared thresholds. |
| **Analytics** | `titan/analytics/` | Records every signal, order attempt, fill, and feature snapshot — the pre-live evidence base. |
| **Clock** | `titan/clock.py` | Honest market-hours / trading-day logic; gates trading to real session times. |
| **News** | `titan/news/` | Ingests corp announcements + RSS, runs FinBERT sentiment + category rules (dry-run CSV only, no trading). |
| **API** | `titan/api/main.py` | FastAPI control plane: kill, flatten, arm auto-pilot, start/stop strategies, data endpoints. |
| **Dashboard** | `titan/dashboard/app.py` | Streamlit UI (the working one). `frontend/` is the React replacement (scaffold). |
| **Telemetry** | `titan/telemetry/` | Logging + Telegram alerts. |

---

## 4. Flow charts

### 4.1 Master data & control flow

```
                          ┌───────────────────────────┐
                          │      MARKET (NSE)          │
                          │  live prices, 09:15–15:30  │
                          └─────────────┬──────────────┘
                                        │ ticks (paise → ₹)
                    ┌───────────────────▼────────────────────┐
                    │  FEED LAYER                              │
                    │  • feed.py  (Angel One WS V2, MODE_QUOTE)│
                    │  • feed_supervisor.py (auto on/off,      │
                    │    reconnect w/ backoff, staleness >30s) │
                    │  • synth_feed.py (dev only, 🧪 labelled) │
                    └───────────────────┬─────────────────────┘
                                        │ ticks:<symbol>  (Redis Stream, maxlen 10k)
                                        │ titan:ltp:<symbol>, titan:heartbeat:feed
                    ┌───────────────────▼─────────────────────┐
                    │  BAR WRITER (aggregator.py)              │
                    │  ticks → 1m/3m/5m/15m/1d OHLCV           │
                    │  (1d aligns to UTC midnight)             │
                    └───────┬───────────────────────┬─────────┘
                            │ store (upsert)         │ publish
                            ▼                        ▼
                  ┌──────────────────┐     ┌──────────────────────┐
                  │  TimescaleDB     │     │  Redis pub/sub        │
                  │  ohlcv (hyper)   │     │  bars:<sym>:<tf>      │
                  └────────┬─────────┘     └──────────┬───────────┘
                           │ window read (200 bars)   │ "new bar" event
                           └────────────┬─────────────┘
                                        ▼
              ┌─────────────────────────────────────────────────┐
              │  SUPERVISOR (strategies/supervisor.py)           │
              │  on each new bar:                                │
              │   1. _check_exits() — SL/TP on open trades       │
              │   2. read titan:strategies:enabled (Redis set)   │
              │   3. feed 200-bar window to each strategy.on_bar()│
              │   4. record EVERY signal (incl. rejected)        │
              │   5. heartbeat titan:heartbeat:<strategy>        │
              └───────────────────────┬─────────────────────────┘
                                      │ Signal → ExecutionRouter
                                      ▼
              ┌─────────────────────────────────────────────────┐
              │  RISK ENGINE (risk/engine.py)                    │
              │  10 GATES (sticky halt the day, transient don't):│
              │  ① kill ② session-halt ③ market-hours(T)         │
              │  ④ cutoff ⑤ daily-loss ⑥ daily-profit-lock       │
              │  ⑦ weekly-loss ⑧ drawdown ⑨ consec-losses        │
              │  ⑩ concurrent-positions(T)                       │
              │  then: per-trade-risk (auto-downsizes) + funds   │
              └───────────────────────┬─────────────────────────┘
                          approved Order│      ✗ rejected → logged + signals.reject_reason
                                        ▼
              ┌──────────────────┐         ┌──────────────────────────┐
              │  PAPER BROKER    │         │  ANGEL ONE BROKER        │
              │  (always on)     │         │  (shadow / live)         │
              │  fill @ LTP ±    │         │  5 GATES:                │
              │  2bps slippage,  │         │  ① live-enabled ② product│
              │  full MIS charges│         │  ③ exchange ④ order-value│
              │                  │         │  ⑤ dry-run               │
              └────────┬─────────┘         └────────────┬─────────────┘
                       │ fill                            │ fill / "would-have-sent"
                       └──────────────┬──────────────────┘
                                      ▼
              ┌─────────────────────────────────────────────────┐
              │  PERSISTENCE & ANALYTICS  (Postgres/Timescale)   │
              │  trades · orders · order_attempts · fills ·      │
              │  signals · feature_snapshots · equity_curve ·    │
              │  risk_events · regime_decisions · leaderboard    │
              └───────────────────────┬─────────────────────────┘
                                      ▼
        ┌──────────────────────────────────────────────────────────┐
        │  OBSERVABILITY & CONTROL                                   │
        │  • FastAPI (:8000) — kill, flatten, arm, start/stop, data │
        │  • Streamlit dashboard (:8501) — the working UI           │
        │  • React frontend (:5173) — scaffold, future replacement  │
        │  • Telegram alerts                                        │
        └──────────────────────────────────────────────────────────┘
```

### 4.2 The auto-pilot (decision engine) loop — runs every 30s

```
   ohlcv NIFTY 5m (last 200 bars)
        │
        ▼
   REGIME CLASSIFIER (decision/regime.py)  — computes ADX(14), realized-vol %ile, ATR, OR-expansion
        │  applies ladder, most-protective-first:
        ▼
   ┌──────────┬──────────────────────┬──────────────────────┬───────────────┬──────────────┐
   │ CLOSED   │ CRISIS               │ TREND                │ RANGE         │ TRANSITION   │
   │ outside  │ VIX≥25 OR            │ ADX ≥ 22             │ ADX < 18      │ everything   │
   │ 09:15–   │ vol_pctile ≥ 0.90    │                      │ (& not crisis)│ else (18–22) │
   │ 15:15    │                      │                      │               │              │
   └────┬─────┴──────────┬───────────┴──────────┬───────────┴──────┬────────┴──────┬───────┘
        ▼                ▼                       ▼                  ▼               ▼
     arm none         arm none          {orb, supertrend_adx}   {vwap_revert}    {orb}
                                              │                       │              │
                                              └───────────┬───────────┴──────────────┘
                                                          ▼
                                  SELECTOR (decision/selector.py)
                                  target = regime_candidates  ∩  VALIDATED allowlist
                                  (Redis titan:autopilot:validated, .env fallback "orb")
                                  → unvalidated & killed strategies are UNREACHABLE
                                                          │
                                       observe-only (default): log only, change nothing
                                       ARMED: sadd/srem titan:strategies:enabled
                                                          │
                                                          ▼
                                  every tick → regime_decisions table
                                  + titan:regime:current / :reason / :reading (Redis)
                                  (full audit trail of WHY each choice was made)
```

### 4.3 The strategy promotion funnel (how a strategy earns real money)

```
   59 strategy variants (factory.py: 5 families × param grids)
        │
        ▼
   WALK-FORWARD BACKTEST (backtest/walk_forward.py)
   each variant run on EVERY symbol; 70% in-sample / 30% out-of-sample.
   PREDECLARED ship/kill thresholds (no tuning after the fact):
        • ≥ 30 OOS trades (total)
        • profit factor ≥ 1.10 (trade-weighted)
        • max drawdown ≤ 25%
        • profitable on ≥ 60% of symbols (persistence)
        • OOS Sharpe > DEFLATED bar  σ_SR·√(2·ln N),  σ_SR = √(252/n_obs)
          (the level a best-of-N fluke reaches by chance — anti data-dredging)
        │
        ├─ FAIL ─► verdict KILL → leaderboard row, shelved
        │          (e.g. TSMOM — also hard-blocked at API + hidden in UI)
        │
        └─ PASS ─► verdict SHIP → leaderboard table (008)
                     │  walk_forward.py --promote
                     ▼
                  validated allowlist (Redis titan:autopilot:validated)
                     │   (delete + re-add survivors; no survivors → cleared)
                     ▼
                  auto-pilot may now arm it for the right regime
                     │
                     ▼
                  paper trade on REAL data → readiness_check.sh (6 gates)
                     │
                     ▼
                  LIVE (₹5K; dry-run shadow week first; kill switch ready)
```

### 4.4 Roadmap dependency graph (recommended build order)

```
        ┌─────────────────────────────────────────────┐
        │  G4 real-data paper feed  (foundational) ✅   │
        └───────────────┬───────────────┬──────────────┘
                        │               │
              ┌─────────▼───┐     ┌──────▼─────────────┐
              │ G5 store     │✅   │ G1 real instrument │⚠️
              │ everything   │     │ (NIFTY/SENSEX)     │
              └─────┬────────┘     └────────────────────┘
                    │
          ┌─────────▼───────────────┐
          │ G3 strategy SDK + mass   │✅ engine built
          │ walk-forward + leaderbd  │   (needs real-data runs)
          └──────────────────────────┘
   G2 (UI) is independent — proceeds in parallel anytime. ⚠️ scaffold

   Recommended sequence: G4 → G5 → G3 → G1, with G2 throughout.
```

---

## 5. System specification

### 5.1 Configuration reference (Pydantic `BaseSettings`, prefix `TITAN_`, reads `.env`)

**Core trading**
| Setting | Env var | Default | Meaning |
|---|---|---|---|
| mode | `TITAN_MODE` | `paper` | paper vs live |
| sim_mode | `TITAN_SIM_MODE` | `0` (False) | use simulation clock |
| capital | `TITAN_CAPITAL` | `500000.0` | paper notional (large for statistical signal) |
| universe | `TITAN_UNIVERSE` | `NIFTY,BANKNIFTY,FINNIFTY,RELIANCE,HDFCBANK,ICICIBANK` | traded symbols |
| instrument_kind | `TITAN_INSTRUMENT_KIND` | `ETF` | ETF / OPTION / INDEX / EQUITY |

**Risk limits** (all % are of `capital`; INR values shown for ₹500K)
| Setting | Env var | Default | INR @500K |
|---|---|---|---|
| max_risk_per_trade_pct | `TITAN_MAX_RISK_PER_TRADE_PCT` | `1.0` | ₹5,000 |
| max_daily_loss_pct | `TITAN_MAX_DAILY_LOSS_PCT` | `2.0` | ₹10,000 |
| max_daily_profit_pct | `TITAN_MAX_DAILY_PROFIT_PCT` | `4.0` | ₹20,000 |
| max_weekly_loss_pct | `TITAN_MAX_WEEKLY_LOSS_PCT` | `5.0` | ₹25,000 |
| max_drawdown_pct | `TITAN_MAX_DRAWDOWN_PCT` | `10.0` | ₹50,000 |
| max_consecutive_losses | `TITAN_MAX_CONSECUTIVE_LOSSES` | `5` | count |
| max_concurrent_positions | `TITAN_MAX_CONCURRENT_POSITIONS` | `3` | count |
| intraday_square_off | `TITAN_INTRADAY_SQUARE_OFF` | `15:15` | IST cutoff |

**Auto-pilot**
| Setting | Env var | Default |
|---|---|---|
| autopilot_enabled | `TITAN_AUTOPILOT_ENABLED` | `False` (observe-only) |
| autopilot_validated | `TITAN_AUTOPILOT_VALIDATED` | `orb` |
| autopilot_interval_s | `TITAN_AUTOPILOT_INTERVAL_S` | `30` |
| autopilot_ref_symbol | `TITAN_AUTOPILOT_REF_SYMBOL` | `NIFTY` |

**Regime thresholds**
| Setting | Env var | Default |
|---|---|---|
| regime_adx_trend | `TITAN_REGIME_ADX_TREND` | `22.0` |
| regime_adx_range | `TITAN_REGIME_ADX_RANGE` | `18.0` |
| regime_vol_crisis_pctile | `TITAN_REGIME_VOL_CRISIS_PCTILE` | `0.90` |
| regime_vix_crisis | `TITAN_REGIME_VIX_CRISIS` | `25.0` |
| regime_lookback_bars | `TITAN_REGIME_LOOKBACK_BARS` | `200` |

**Live safety gates**
| Setting | Env var | Default |
|---|---|---|
| live_enabled | `TITAN_LIVE_ENABLED` | `False` |
| live_dry_run | `TITAN_LIVE_DRY_RUN` | `True` |
| live_max_order_value | `TITAN_LIVE_MAX_ORDER_VALUE` | `25000.0` |
| live_allowed_products | `TITAN_LIVE_ALLOWED_PRODUCTS` | `INTRADAY` |
| live_allowed_exchanges | `TITAN_LIVE_ALLOWED_EXCHANGES` | `NSE` |

**Connectivity:** `TITAN_DB_URL` (`postgresql+psycopg://titan:titan@localhost:5432/titan`),
`TITAN_REDIS_URL` (`redis://localhost:6379/0`). Angel creds: `ANGELONE_API_KEY`,
`ANGELONE_CLIENT_CODE`, `ANGELONE_PIN`, `ANGELONE_TOTP_SECRET`.

### 5.2 Redis key map

| Key / pattern | Type | Written by | Read by | Purpose |
|---|---|---|---|---|
| `ticks:<symbol>` | Stream (maxlen 10k) | feed / synth_feed | bar_writer | raw ticks |
| `titan:ltp:<symbol>` | String | feed / synth_feed | dashboard | last price (ticker tape) |
| `bars:<symbol>:<tf>` | Pub/Sub | bar_writer | supervisor, dashboard | closed-bar events |
| `titan:heartbeat:feed` | String (ISO UTC) | feed / synth_feed | feed_supervisor | feed liveness |
| `titan:feed:status` | String | feed_supervisor | dashboard | RUNNING/STOPPED/STALE |
| `titan:feed:age_s` | String | feed_supervisor | dashboard | seconds since last tick |
| `titan:heartbeat:<strategy>` | String (ISO) | supervisor | dashboard | strategy liveness |
| `titan:strategies:enabled` | Set | API, auto-pilot | supervisor | which strategies trade |
| `titan:autopilot:enabled` | String "0"/"1" | API | auto-pilot | armed vs observe-only |
| `titan:autopilot:validated` | Set | walk_forward --promote | selector, API | live-eligible allowlist |
| `titan:regime:current` | String | selector / auto-pilot | dashboard, API | current regime |
| `titan:regime:reason` | String | selector / auto-pilot | dashboard, API | decision justification |
| `titan:regime:reading` | String (JSON) | selector | dashboard | full RegimeReading |
| `titan:kill` | String "1" | API `/kill` | risk engine, auto-pilot | halt new orders |
| `titan:control` | Pub/Sub | API `/flatten` | supervisor | "FLATTEN" → close all |
| `titan:vix` | String | (external) | auto-pilot | India VIX input |
| `titan:sim:enabled` | String "0"/"1" | API `/sim/*` | clock, feed_supervisor | simulation clock toggle |
| `titan:mode:synthetic` | String "1" | synth_feed | dashboard | 🧪 SYNTH pill |

### 5.3 Data feed & bars

- **Connection:** `SmartWebSocketV2` (official `smartapi-python`) to
  `wss://smartapisocket.angelone.in/smart-stream`, **MODE_QUOTE** (=2).
- **Token→symbol mapping** keys everything by the **universe name** (token →
  "NIFTY", not Angel's "Nifty 50") and enforces an invariant: every configured
  symbol must resolve to a token or the feed refuses to start. Exchange codes:
  NSE=1, NFO=2, BSE=3, MCX=5, NCDEX=7, CDS=13.
- **Price conversion:** Angel sends paise → divided by 100 to rupees.
- **feed_supervisor:** runs the real feed only when `should_run()` (not sim mode
  AND `clock.is_market_open()`). Staleness threshold **30s**, poll **5s**,
  exponential backoff **5s → 60s**. Spawns `python -m titan.data.feed` as a
  subprocess; graceful stop with 10s timeout then SIGKILL.
- **Timeframes (seconds):** `1m=60, 3m=180, 5m=300, 15m=900, 1d=86400`. Bucket =
  `epoch − (epoch % seconds)`. **1d aligns to UTC midnight**, not the IST session
  (documented as a future refinement).
- **Storage:** `ohlcv` hypertable, PK `(symbol, timeframe, ts)`, upsert on
  conflict. **Publish:** `bars:<symbol>:<tf>` JSON `{ts,o,h,l,c,v}`.
- **synth_feed (dev only):** 1 tick / 0.2s, sim-time +30s per tick (a 5m bar
  closes in ~2 real seconds), ~1.2% of ticks get a 20–50bp shock; wraps 15:30 →
  next-day 09:15 so session-bound strategies (ORB) can run overnight.

### 5.4 Clock

- **Session:** `SESSION_OPEN = 09:15`, `SESSION_CLOSE = 15:30` IST.
  `is_market_open()` = trading day AND `09:15 ≤ t < 15:30`.
- **Trading day:** weekdays only **plus** `config/nse_holidays.yaml` (fixed-date
  holidays pre-loaded; movable festivals — Holi/Diwali/Eid — must be added yearly
  from the NSE circular). Missing dates fail *permissive* (never wrongly block).
- **Sim mode:** opt-in via `TITAN_SIM_MODE=1` or Redis `titan:sim:enabled=1`
  (Redis wins at runtime). `sim_session_now()` maps the wall clock onto a looping
  09:15→15:15 (21,600s) window so demos work at any real time. **Real mode is the
  honest default** — no silent "pretend it's 11am" override anymore.

### 5.5 Strategies

**Interface (`base.py`).** A `Strategy` implements one method:
`on_bar(bars: pd.DataFrame) -> list[Signal]` (full history up to the just-closed
bar, ascending, columns `o,h,l,c,v`). Class vars: `name`, `timeframe`
(`"5m"`/`"1d"`). A **`Signal`** = `ts, symbol, kind, entry, stop, target?,
reason, confidence(=1.0)` with property `per_unit_risk = |entry − stop|`.
**`SignalKind(StrEnum)`** = {`ENTRY_LONG`, `ENTRY_SHORT`, `EXIT`}.

**Named, live-capable strategies (`registry.BASE_STRATEGIES`):**

**ORB (`orb.py`)** — defaults `or_minutes=15, target_r=1.5, cutoff="14:30",
session_open="09:15"` (all IST). Opening range = high/low over
`[session_open, session_open+or_minutes)` (09:15–09:30), finalized at first bar
≥ `or_end`. LONG: `close > or_high` → entry=close, stop=`or_low`,
target=`close + 1.5·(or_high−or_low)`. SHORT: mirror with stop=`or_high`. One
long + one short per day (`long_taken`/`short_taken`), no entries ≥ 14:30, full
state reset on date change. All time compares done in IST (`_to_ist`).

**VWAPRevert (`vwap_revert.py`)** — defaults `k_sigma=2.0, atr_period=14,
atr_mult=1.0, lookback=20`. Session-scoped (today only): `vwap =
cumsum(c·v)/cumsum(v)`; `dev = c − vwap`; `σ = std(dev[-20:])`;
`z = (c[-1]−vwap[-1])/σ`. SHORT if `z > 2.0` (stop=`c+1.0·atr`, target=vwap);
LONG if `z < −2.0` (stop=`c−1.0·atr`, target=vwap). ADX>25 regime overlay is
applied externally by the decision layer, not in-class.

**SupertrendADX (`supertrend_adx.py`)** — defaults `st_period=10, st_mult=3.0,
adx_period=14, adx_min=20.0`. Supertrend: `hl2=(h+l)/2`,
`upper=hl2+mult·atr`, `lower=hl2−mult·atr`; iterative carry — in a downtrend
`st=min(upper, prev_st)`, flip to up when `close>st` (then `st=lower`); in an
uptrend `st=max(lower, prev_st)`, flip to down when `close<st` (then
`st=upper`). ADX: `+DM=(up>dn & up>0)·up`, `−DM=(dn>up & dn>0)·dn`,
`±DI=100·SMA(±DM,p)/atr`, `DX=100·|+DI−−DI|/(+DI+−DI)`, `ADX=SMA(DX,p)`. Entry
only on a direction flip (`dir[-1]≠dir[-2]`) **and** `ADX>20`; stop = the ST
line; no target.

**TSMOM (`tsmom.py`)** — defaults `lookback=20, vol_window=60, vol_target=0.10,
stop_sigma=2.0`, `ANN=252`. `r_lb = log(c[-1]/c[-lookback-1])`. Enter LONG if
`r_lb>0`; sizing `confidence = min(1.0, vol_target/realised_vol)` where
`realised_vol = std(logret[-60:])·√252`; stop `= last·exp(−2.0·daily_σ)`. EXIT
when `r_lb≤0` while long. State machine (`flat`/`long`) emits on transitions
only. **KILLED** by walk-forward → `KILLED_STRATEGIES={tsmom}`, API returns 409,
hidden in UI.

**The 59-variant library (`library.py` + `factory.py`).** Five families, each
emitting only on a direction *transition*. Variant `key =
"{cls.name}.{slug}"`, slug = `"_".join(f"{k[:3]}{v}")` over params (e.g.
`ma_cross.fas9_slo21_atr2.0`). Exact `PARAM_GRID`:

| Family (`name`) | Grid | Logic | Stop / Target | Variants |
|---|---|---|---|---|
| MACrossover (`ma_cross`) | fast `[5,9,12,20]` × slow `[21,50,100]` × atr_mult `[2.0,3.0]` | EMA(fast)×EMA(slow) cross | ATR stop / none | **24** (skip fast≥slow) |
| DonchianBreakout (`donchian`) | period `[10,20,55]` × target_r `[1.5,2.0,3.0]` | break of N-bar channel | opposite side / `target_r`×range | **9** |
| RSIReversion (`rsi_revert`) | period `[2,7,14]` × lo `[20,30]` × hi `[70,80]` | RSI cross of lo/hi | ATR stop / none | **12** |
| BollingerReversion (`bollinger_revert`) | period `[20,50]` × k `[2.0,2.5,3.0]` | touch of band | ATR stop / SMA(period) | **6** |
| MomentumROC (`momentum`) | lookback `[10,20,40,60]` × atr_mult `[2.0,3.0]` | ROC crosses zero | ATR stop / none | **8** |

Total **59**. `factory.all_variants()` → `VariantSpec(key, family, cls, params)`
with `build(symbol)`; the vetting harness builds and tests each.

**Indicators (`indicators.py`), leak-free pandas series:** `ema`
(`ewm(span,adjust=False)`), `sma`, `roc` (`s/s.shift(p)−1`), `true_range`,
`atr` (default 14), `rsi` (Wilder `ewm(alpha=1/p)`, 14), `bollinger` (20, k=2 →
mid/upper/lower), `donchian` (20, `.shift(1)` no look-ahead → upper/lower).

**Supervisor orchestration (`supervisor.py`).** On each `bars:<sym>:<tf>` event:
(1) `_check_exits()` — SL/TP against open trades; (2) for each enabled strategy
whose `timeframe` matches, load a 200-bar window and call `on_bar()`; (3) record
*every* signal incl. rejected (with reason); EXIT signals close the matching open
trade via the shared `_close_trade()`; index symbols are skipped for entries;
(4) heartbeat. It **reconstructs equity from realized PnL on restart** and
**reloads open trades** (`exit_ts IS NULL`) so a restart doesn't lose positions.
Three concurrent loops: `_bar_loop` (subscribe), `_control_loop` (FLATTEN), and
`_eod_scheduler` (publishes FLATTEN at the 15:15 square-off).

### 5.6 Decision engine (regime → selection → audit)

**Regimes (`regime.py`):** `CLOSED, CRISIS, TREND, RANGE, TRANSITION`. Classified
most-protective-first from NIFTY 5m (200 bars):
- **CLOSED** — session phase is PREOPEN (<09:15), CUTOFF (≥15:15) or CLOSED (≥15:30).
- **CRISIS** — `india_vix ≥ 25.0` **or** `vol_pctile ≥ 0.90`.
- **TREND** — `ADX ≥ 22.0`.
- **RANGE** — `ADX < 18.0` (and not crisis).
- **TRANSITION** — everything else (ADX 18–22, or insufficient data).

ADX is Wilder-style (needs ≥42 bars); realized vol is annualized
(`σ × √(75·252)`, 75 = 5m bars/day); vol percentile is rolling over the lookback.
`RegimeReading` captures every feature + a plain-English `reason`.

**Selector (`selector.py`):** `REGIME_CANDIDATES = {TREND:{orb,
supertrend_adx}, RANGE:{vwap_revert}, TRANSITION:{orb}, CRISIS:set(),
CLOSED:set()}`. The target is `candidates ∩ validated_set` — so an unvalidated or
killed strategy **cannot** be armed even if its regime is active. Validated set
reads Redis `titan:autopilot:validated` (fallback `.env` `orb`). When armed it
reconciles `titan:strategies:enabled` (sadd/srem within its own lane); always
publishes `titan:regime:current/reason/reading` and inserts a `regime_decisions`
row (enabled_before/after + features + reason).

**Auto-pilot (`auto_pilot.py`):** loops every **30s**. Each tick: read clock,
read armed flag (Redis `titan:autopilot:enabled`, fallback `.env`), honor kill
switch (disarms its lane, sets regime=KILLED), load bars, read optional VIX,
classify, then `selector.decide(apply=armed)`. **Observe-only** (default) logs and
persists what it *would* do but changes nothing; **armed** actually toggles
strategies. Crash-safe: a failing tick is logged and skipped, never half-applied.

### 5.7 Risk engine

**`check(order, per_unit_risk, available_cash)`** runs gates in order. *Sticky*
gates set `state.halted_today` (halt the rest of the day); *transient* (T) ones
reject without halting:

1. **kill** (sticky) — Redis `titan:kill` active.
2. **session-halt** (sticky) — already halted today.
3. **market-hours (T)** — weekday and `09:15 ≤ t < 15:30` IST.
4. **cutoff** (sticky) — `now ≥ intraday_square_off` (15:15).
5. **daily-loss** (sticky) — `−realized_pnl_today ≥ max_daily_loss_inr`.
6. **daily-profit-lock** (sticky) — `realized_pnl_today ≥ max_daily_profit_inr` (disabled if pct≤0).
7. **weekly-loss** (sticky) — `−realized_pnl_week ≥ max_weekly_loss_inr`.
8. **drawdown** (sticky) — `peak_equity − current_equity ≥ max_drawdown_inr`.
9. **consecutive-losses** (sticky) — `consecutive_losses ≥ max_consecutive_losses`.
10. **concurrent-positions (T)** — `open_positions ≥ max_concurrent_positions`.

Then **per-trade-risk**: `trade_risk = per_unit_risk × qty`; if it exceeds
`max_risk_per_trade_inr` the order is **auto-downsized** (`adjusted_qty`) rather
than rejected. Finally a **funds** check for BUYs. (README's "11 gates" = these 10
+ the per-trade-risk/funds checks.)

**`RiskState`:** starting/peak/current equity, realized_pnl_today/week,
open_positions, consecutive_losses (reset to 0 on any win), halted_today,
halt_reason, kill_switch. `on_trade_closed(pnl)` updates equity, peak, and the
loss streak.

**Sizing (`fixed_fractional_qty`):**
`qty = floor( equity × (risk_pct/100) × conf / |entry−stop| )`, then floored to
`lot_size`, never negative. **Confidence is clamped to [0.1, 1.0]** — low
conviction shrinks the sleeve but never to zero, and never upsizes beyond budget.
(The old ATR-based sizer was removed as redundant — explicit stops already give
ATR-equivalent risk sizing.)

### 5.8 Execution router, order model & brokers

**Order model (`brokers/base.py`).** `Order` fields: `symbol, side, qty,
order_type=MARKET, product=INTRADAY, price?, trigger_price?, strategy="manual",
id(uuid4), broker_order_id?, status=NEW, avg_fill_price?, placed_at(utc now),
filled_at?, reject_reason?, is_paper=True`. Enums (StrEnum):
`OrderSide{BUY,SELL}`, `OrderType{MARKET,LIMIT,SL,SL-M}`,
`Product{INTRADAY,DELIVERY,NORMAL}`, `OrderStatus{NEW,OPEN,FILLED,REJECTED,
CANCELLED}`. `Position{symbol, qty(signed), avg_price, unrealized_pnl}`.
`BrokerAdapter` ABC: `connect, disconnect, place_order, cancel_order,
get_positions, get_ltp, get_funds`.

**ExecutionRouter.submit(signal, strategy_name) → ExecutionResult** (`signal,
order?, approved, reason?`): (1) EXIT → early return ("exit handled elsewhere");
(2) `equity = broker.get_funds()["equity"]`; (3) `qty = fixed_fractional_qty(
equity, max_risk_per_trade_pct, signal.entry, signal.stop, lot_size,
signal.confidence)`; (4) `qty<1` → reject "sizing → 0 qty"; (5) build market
INTRADAY Order, side from signal kind; (6) `risk.check(order, per_unit_risk,
cash)` — reject if not approved; (7) apply `decision.adjusted_qty` if set;
(8) `broker.place_order`; (9) REJECTED → propagate reason; (10) else approved.

**PaperBroker (`paper.py`, always on):** market orders fill at `LTP ±
LTP·(slippage_bps/1e4)` (default **2.0 bps**, BUY up / SELL down); limit orders
fill only if marketable. `_apply_fill` keys positions by symbol: opening/adding
recomputes weighted `avg_price`; reducing/closing books
`pnl=(fill−avg)·closed_signed` into `cash` and `_realized_pnl_by_symbol`, handles
reversals. Full **Angel One MIS charge model** deducted from cash + tracked as
cost: brokerage `min(₹20, 0.03%)`, STT 0.025%, exchange 0.00345%, GST 18% of
(brokerage+exchange), SEBI 0.0001%, stamp 0.003%.

**AngelOneBroker (`angelone.py`, shadow/live) — 5 sequential gates:**
1. **live-enabled** — `TITAN_LIVE_ENABLED` true.
2. **product** — `order.product` ∈ `live_allowed_products` (INTRADAY).
3. **exchange** — resolved `exch_seg` ∈ `live_allowed_exchanges` (NSE).
4. **order-value** — `ref_price × qty ≤ live_max_order_value` (ref from order.price or `get_ltp`).
5. **dry-run** — if `TITAN_LIVE_DRY_RUN` (default true): **log exact payload,
   return REJECTED("dry_run …")** without sending. Week-1 safety net.

**Auth/REST:** base `https://apiconnect.angelone.in`. Login
`POST /rest/auth/.../loginByPassword` with `{clientcode, password(MPIN),
totp}` (`pyotp.TOTP(secret).now()`) + headers `X-PrivateKey, X-UserType=USER,
X-SourceID=WEB, X-ClientLocalIP/PublicIP/MACAddress`; stores jwt(~22h)/refresh/
feed tokens. `getLtpData` → `data.ltp`. On a real send, `_poll_fill` polls
`getOrderBook` every **0.5s up to 8s**, mapping complete→FILLED / rejected→
REJECTED / cancelled→CANCELLED with `averageprice`. Creds:
`ANGELONE_API_KEY/CLIENT_CODE/PASSWORD/TOTP_SECRET`.

### 5.9 Backtest & walk-forward

**Engine (`backtest/engine.py`):** fills at **next-bar open ± slippage** (default
5 bps; no look-ahead). Sizing = `min(risk-based, leverage-capped)`:
`qty_risk = (0.01·equity)/per_unit_risk`, `qty_pos = (equity·min(max_pos_pct,1)·
leverage)/entry` (default leverage **5×**, MIS-style), `qty = max(1, min(...))`.
**Ruin guard:** equity ≤ 0 freezes trading. Exit priority: intrabar SL → TP →
signal EXIT → end-of-data flatten. Same MIS charge model as the paper broker.
`summarize()` returns n_trades, hit_rate, avg_win/loss, profit_factor, total_pnl,
total_costs, **max_dd_pct**, **sharpe** (daily, ×√252), **cagr** (guarded against
non-positive equity), avg_bars_held, exposure_pct.

**Walk-forward (`walk_forward.py`):** runs each variant on every symbol, **70/30
IS/OOS** split. Predeclared SHIP gate (all must hold): trades ≥ **30**, sharpe >
**deflated threshold**, profit_factor ≥ **1.10**, max_dd ≤ **25%**, ≥ **60%** of
symbols profitable. **Deflated-Sharpe** (anti data-dredging):
`σ_SR·√(2·ln N)` with `σ_SR = √(252/n_obs)`, `N` = number of variants tested.
`--promote` rewrites Redis `titan:autopilot:validated` (delete + sadd survivors;
none → cleared). Results land in the `leaderboard` table.

**Scripts:** `run_orb_backtest.py` (ORB, real 5m, 70/30, writes
`docs/research/03_orb_results.md`; note: engine processes LONG entries — verdict
is long-only), `run_tsmom_backtest.py` (daily, predeclared date-range OOS),
`compare_strategies.py` (ORB vs VWAPRevert vs SupertrendADX head-to-head, ₹50K).

### 5.10 Analytics & data model

**Recorder (`analytics/recorder.py`):** app-generated UUIDs link
signal → order → fill without DB round-trips. **Every write is best-effort** —
exceptions logged, never raised into the trading loop. Realized slippage =
`(fill_price − ltp_at_decision)/ltp_at_decision × 1e4` bps.

**17 tables (4 TimescaleDB hypertables on `ts`: `ohlcv`, `risk_events`,
`equity_curve`, `regime_decisions`). No compression/retention policy set yet.**
Numeric types omitted for brevity — all prices `NUMERIC(12–14,4)`, pnl `(14–16,2)`.

| Migration | Table | Columns (PK **bold**; → = FK) |
|---|---|---|
| 001 | `ohlcv` *(hyper)* | **symbol, timeframe, ts**, o, h, l, c, v(bigint) |
| 001 | `orders` | **id**(uuid), broker_order_id, strategy, symbol, side, qty, price, order_type, product, status, placed_at(now), filled_at, avg_fill_price, reject_reason, is_paper(t) |
| 001 | `trades` | **id**(uuid), strategy, symbol, qty, side, entry_ts, entry_price, exit_ts, exit_price, stop_loss, target, pnl, exit_reason, is_paper(t) · idx(strategy, entry_ts↓) |
| 001 | `risk_events` *(hyper)* | ts(now), kind, detail(jsonb) |
| 001 | `equity_curve` *(hyper)* | **ts**, equity |
| 002 | `instruments` | **exch_seg, token**, symbol, name, instrumenttype, expiry, strike, lotsize(1), tick_size(0.05), refreshed_at(now) · idx(name),(symbol),(expiry) |
| 003 | `news_events` | **id**(bigserial), source, source_id, published_at, fetched_at(now), headline, body, url, raw_symbol, raw(jsonb) · uniq(source, source_id) · idx(published_at↓),(raw_symbol) |
| 003 | `news_entities` | **news_event_id→news_events, ticker**, matched_alias, confidence(real), method · idx(ticker) · ON DELETE CASCADE |
| 003 | `sentiment_cache` | **cache_key**(sha256), model_id, headline, label, score, neg_p, neu_p, pos_p, computed_at(now) |
| 003 | `news_signals` | **id**(bigserial), news_event_id→news_events, ticker, published_at, headline, source, category, sentiment_label, sentiment_score, entity_conf, would_fire(f), fire_reason · uniq(news_event_id, ticker) · idx(ticker, published_at↓), partial(would_fire) WHERE true |
| 004 | `news_signals.direction` | TEXT CHECK in ('long','short') OR NULL · partial idx WHERE not null |
| 005 | `regime_decisions` *(hyper)* | ts(now), ref_symbol, regime, adx, realized_vol, vol_pctile, or_expansion, india_vix, session_phase, enabled_before(jsonb), enabled_after(jsonb), reason · idx(ts↓) |
| 006 | `signals` | **id**(uuid), ts(now), strategy, symbol, kind, entry, stop, target, per_unit_risk, confidence, regime, accepted(bool), reject_reason, order_id(uuid), reason · idx(ts↓),(strategy,symbol,ts↓),(accepted,ts↓) |
| 006 | `order_attempts` | **id**(uuid), ts(now), signal_id, strategy, symbol, side, qty_requested, qty_final, order_type, product, price, risk_approved(bool), risk_reason, broker, status, broker_order_id, avg_fill_price, reject_reason · idx(ts↓),(signal_id) |
| 006 | `fills` | **id**(uuid), ts(now), order_id, strategy, symbol, side, qty, fill_price, ltp_at_decision, modeled_slippage_bps, realized_slippage_bps, is_paper(t) · idx(ts↓),(symbol,ts↓) |
| 006 | `feature_snapshots` | **id**(uuid), ts(now), strategy, symbol, signal_id, features(jsonb) · idx(ts↓) |
| 007 | `trades.regime` | TEXT · idx(regime) |
| 008 | `leaderboard` | **variant_key**, ts(now), family, params(jsonb), trades, net_pnl, sharpe, deflated_threshold, profit_factor, max_dd_pct, symbols_tested, symbols_profitable, passed(f), verdict, reasons · idx(verdict, sharpe↓) |

Constraints summary: 3 FKs (news_entities, news_signals → news_events, ON DELETE
CASCADE), 2 uniq (news_events, news_signals), 1 CHECK (direction), 2 partial
indexes (would_fire, direction).

### 5.11 API surface (FastAPI, `:8000`)

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/status` | — | `{mode, env, capital, kill_switch, sim_mode, market_open, server_time_ist, universe[], limits{max_risk_per_trade_pct, max_daily_loss_pct, max_daily_profit_pct, max_drawdown_pct}}` |
| GET | `/sim` | — | `{sim_mode, source("redis"\|"config_default"), market_open, server_time_ist}` |
| POST | `/sim/on` · `/sim/off` | — | `{ok, sim_mode}` |
| POST | `/kill` | `?reason=manual` | `{ok, kill_switch:true, reason}` |
| POST | `/flatten` | — | `{ok, broadcast:"FLATTEN"}` |
| GET | `/strategies` | — | `{strategies[]}` (sorted) |
| POST | `/strategies/{name}/start` | path `name`, `?force=false` | `{ok, started, forced}` · **400** bad name · **409** killed / not-validated (unless force) |
| POST | `/strategies/{name}/stop` | path `name` | `{ok, stopped}` |
| GET | `/autopilot` | — | `{armed, source, validated_strategies[], ref_symbol, interval_s, regime, regime_reason, enabled_now[]}` |
| POST | `/autopilot/arm` · `/autopilot/disarm` | — | `{ok, armed}` |
| GET | `/data/bars` | `symbol`(req), `tf=5m`, `n=200` | `[{ts,o,h,l,c,v}]` asc |
| GET | `/data/trades` | `limit=100` | `[{id, strategy, symbol, side, qty, entry_ts, entry_price, exit_ts, exit_price, pnl, exit_reason, regime, stop_loss, target}]` |
| GET | `/data/positions` | — | `[{strategy, symbol, side, qty, entry_price, stop_loss, target, entry_ts}]` (exit_ts IS NULL) |
| GET | `/data/leaderboard` | `limit=60` | `[{variant_key, family, trades, sharpe, deflated_threshold, profit_factor, max_dd_pct, verdict, reasons}]` |
| GET | `/data/analytics/funnel` | — | `[{reason, n}]` (reject_reason or "(accepted)") |
| GET | `/auth/test` | — | `{ok, login, feed_token_present, funds{net, availablecash, availableintradaypayin, utiliseddebits}}` · 401/500 on failure |

Entry points (`pyproject`): `titan-api` → `titan.api.main:run`, `titan-dash` →
`titan.dashboard.app:run`.

### 5.12 News pipeline (dry-run only — no trading)

**Sources (`news/sources/`, fetch order):** `NSECorpAnn` (`nse_ann`, NSE
corporate-announcements API + cookie handshake), `BSECorpAnn` (`bse_ann`,
paginated API, ≤25 pages), `MoneycontrolRSS` (`mc_rss`, stub — feed stale),
`EconomicTimesRSS` (`et_rss`, 4 feeds via feedparser: markets/stocks/earnings/
corporate-trends), `MoneycontrolHTML` (`mc_html`) + `EconomicTimesHTML`
(`et_html`) — both gated by `NEWS_SCRAPE_ENABLED`, SHA1-of-URL dedup, Cloudflare-
fragile. Base `NewsSource.fetch(since) → RawNews{source, source_id, published_at,
headline, body, url, raw_symbol, raw}`.

**Pipeline (`ingest.py`):** fetch all → upsert `news_events` (ON CONFLICT
(source, source_id)) → **entity resolution** (`entities.py`): 3-pass against
`config/nifty50_aliases.yaml` — exact (raw_symbol, conf **1.0**) / alias
(whole-word, conf **0.85**) / fuzzy (`rapidfuzz.partial_ratio`, threshold **≥85**,
conf=ratio/100), `MIN_CONF=0.70` → `news_entities` → batch **FinBERT**
(`sentiment.py`, model `ProsusAI/finbert`, labels neg/neu/pos, top_k=None,
max_length=256, CUDA-if-available, SHA256-cached in `sentiment_cache`) →
**category** (`category.py`, 15 priority-ordered regex categories from
`config/news_noise_filters.yaml`) → `_decide_fire()` → upsert `news_signals` →
CSV `out/news_signals_dryrun_<date>.csv`.

**Fire rule v2:** `FIRE_ENTITY_CONF_THRESHOLD=0.70`, `FIRE_NIFTY50_ONLY=True`,
per-category `(sentiment, min_score, direction)` — e.g. earnings(pos,0.70,long),
order_win/partnership/guidance_up/m_and_a(pos,0.60,long), debt_reduce(pos,0.50,
long), dividend(pos,0.60,long), guidance_down(neg,0.60,short), regulatory(neg,
0.70,short), promoter_buying/selling(any,0.0,long/short). `NEVER_FIRE =
{block_deal, generic_noise, other}`. **No order is ever placed** — Phase-1
evidence only.

### 5.13 Dashboard (Streamlit, `:8501`)

8 tabs (`st.tabs`), 5s `st_autorefresh`: **📈 Charts** (ohlcv + VWAP + volume +
trade overlays/markers/SL-TP lines; synthetic fallback when DB empty),
**📊 Positions** (open trades), **📒 Journal** (closed trades + win-rate KPIs),
**🤖 Strategies** (4 strategies; heartbeat; toggles — disabled when killed or
auto-pilot armed; arm/disarm control; regime pill), **🔬 Analytics** (signal
funnel, realized-vs-modeled slippage, P&L by strategy×regime, rejected signals),
**📰 News** (news_signals with lookback/fires/score filters), **🛡️ Risk**
(session status banner, profit/loss/drawdown budget bars, kill + flatten
controls, risk_events log), **⚙️ System** (mode/redis/pg/api health, feed
status+age, clock, universe). Reads Redis (`titan:ltp:*`, `:heartbeat:*`,
`:kill`, `:strategies:enabled`, `:sim:enabled`, `:mode:synthetic`,
`:regime:current/reason`, `:autopilot:enabled`, `:session:status/reason`,
`:feed:status/age_s`) + Postgres queries + API calls (`/status`, `/kill`,
`/flatten`, `/autopilot/{arm,disarm}`, `/strategies/{name}/{start,stop}`).

### 5.14 Telemetry (`telemetry/`)

Structured JSON logging via **structlog** (ISO timestamps, log level, exc info,
JSONRenderer). Telegram alerts: `telegram(text)` → POST
`api.telegram.org/bot{token}/sendMessage` (5s timeout, fire-and-forget, never
raises); `alert(severity, msg)` prefixes ℹ️/⚠️/🚨/🛑. Env (empty = disabled):
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

### 5.15 Instruments & backfill (`data/`)

**`instruments.py`:** `resolve_universe(symbols)` resolves each name —
index-first (`lookup(name,"NSE",instrumenttype="AMXIDX")` for NIFTY/BANKNIFTY/
FINNIFTY), else NSE cash equity (`symbol LIKE '%-EQ'`, instrumenttype NULL) →
list of dicts `{exch_seg, token, symbol, name, instrumenttype, expiry, strike,
lotsize, tick_size}`. `lookup(...)` = O(1) by name+exch_seg index. Scrip master
(~80k rows, ~10 MB) from Angel `OpenAPIScripMaster.json`, persisted via `INSERT
… ON CONFLICT (exch_seg, token) DO UPDATE`, batched 5000.

**`backfill.py`:** Angel `POST .../historical/v1/getCandleData`; rate limit 3/s,
180/min → `REQ_SLEEP_S=0.4`; window per interval (5m=25d … 1d=1800d); cursor
paging +1min to avoid gaps; idempotent `INSERT … ON CONFLICT (symbol,timeframe,
ts) DO NOTHING`. **Instrument map (`config/instrument_map.yaml`):** etf
NIFTY→NIFTYBEES, BANKNIFTY→BANKBEES, FINNIFTY→NIFTYBEES, SENSEX→SENSEXBEES;
option_root pass-through; `equity_passthrough:true`. **`instrument_kind.py`:**
`tradable_symbol(underlying, kind)` maps by kind (ETF→etf map, OPTION→
option_root, EQUITY/INDEX→underlying); `is_directly_tradable()` False only for
INDEX.

### 5.16 Deployment, dependencies & tests

**`pyproject.toml`:** pkg `titan` 0.0.1, Python ≥3.11, hatchling. Runtime:
fastapi≥0.110, uvicorn[standard]≥0.27, pydantic≥2.6/-settings≥2.2,
sqlalchemy≥2.0, psycopg[binary]≥3.1, alembic≥1.13, redis≥5.0, httpx≥0.27,
websockets≥12, pandas≥2.2, numpy≥1.26, numba≥0.59, vectorbt≥0.26,
backtrader≥1.9, streamlit≥1.32 + streamlit-autorefresh≥1.0, plotly≥5.20,
pyotp≥2.9, smartapi-python≥1.4 (+logzero, websocket-client), structlog≥24.1,
python-telegram-bot≥21, pytz, click, rapidfuzz≥3.0. Dev: pytest≥8 +
pytest-asyncio (asyncio_mode=auto), ruff (line 100), mypy.

**Deploy:** Dockerfile `python:3.11-slim`, `pip install -e .[dev]`, expose
8000/8501. docker-compose: **postgres** `timescale/timescaledb:latest-pg16`
(titan/titan/titan, 5432, `pgdata` vol, healthcheck pg_isready), **redis**
`redis:7-alpine` (6379, appendonly, `redisdata` vol), **api**, **dashboard**,
**feed** (restart unless-stopped).

**Scripts:** `demo.sh` (synth_feed + bar_writer + supervisor, cleanup on exit);
`cleanup_synth.sh` (truncate ohlcv/trades/equity_curve/risk_events + clear
Redis); `readiness_check.sh` **6 gates** — ≥5 paper closed trades · ≥1
risk_event · shadow-dry vs paper diff ≤2 · 0 instrument_not_found · Angel
availablecash ≥₹5000 · creds rotated (no default key/TOTP in `.env`).

**Tests (~20 files):** `test_aggregator`, `test_analytics_recorder`,
`test_clock`, `test_feed_supervisor`, `test_instrument_kind`,
`test_news_category_v2`, `test_paper_broker`, `test_risk_engine`, `test_sizing`,
`test_strategy_factory`, `test_supervisor_flatten`, `test_walk_forward`,
`test_data/test_feed_symbol_mapping` (the 2026-06-15 ORB-silence regression),
`test_decision/{test_regime,test_selector}`, `test_news/{test_category,
test_entities,test_sentiment_cache}`, `test_strategies/{test_orb,test_tsmom}`.
123 pass (1 `bs4`-dependency news test excluded in the current env).

---

## 6. How we are doing (honest status)

**Strong / done:**
- ✅ Full data pipeline (feed → bars → strategies → risk → broker → storage) works end-to-end in paper mode.
- ✅ 123 automated tests pass.
- ✅ Real Angel One feed + feed supervisor (auto lifecycle, 30s staleness watchdog, backoff reconnect).
- ✅ Honest market clock + NSE holiday file — no more "pretend it's 11am" hacks.
- ✅ Decision engine / auto-pilot with full `regime_decisions` audit trail.
- ✅ Analytics capture: every signal, order attempt, fill, and feature snapshot (best-effort, non-blocking).
- ✅ Strategy factory (59 variants) + walk-forward vetting with **deflated-Sharpe** (anti data-dredging) + leaderboard + `--promote`.
- ✅ Defense in depth: 10 risk gates + per-trade auto-downsizing + 5 broker gates + kill switch + EOD square-off.
- ✅ Real historical backfill verified (so vetting can run on real data).

**In progress / partial:**
- ⚠️ React UI is a **scaffold** (header, KPI strip, chart wired; positions/journal/strategies/analytics/risk tabs + live WebSocket not built). Streamlit remains the working UI.
- ⚠️ G1 instrument routing: ETF mapping exists; **options routing (strike/expiry) not built**.

**Not yet verified / open:**
- 🔴 Not trading real money.
- 🔴 Live tick **streaming** unverified until a real market-open session (auth path verified).
- 🔴 P3 verdicts only become meaningful once vetting runs at scale on **backfilled real history**.
- 🔴 1d bars align to UTC midnight, not the IST session (fine for daily-trend, refine later).
- 🔴 Backtest engine path is effectively **LONG-only** today — SHORT-side verdicts not yet measured.

---

## 7. How we can improve it — prioritised plan

Ordered by leverage (highest value / lowest risk first). Effort: S/M/L/XL.

### Tier 1 — finish the evidence base (do these first)
1. **Run mass walk-forward on real backfilled history** across all 59 variants → populate the leaderboard with trustworthy verdicts. *The whole go-live decision rests on this.* **[M]**
2. **Verify the live feed during a real market-open session** — WS streaming, JWT (~23h) + feed-token refresh, reconnect-on-drop, correct universe-name mapping. **[S–M]**
3. **Backfill more symbols / more history** so walk-forward clears the ≥30-trade and ≥60%-persistence bars with statistical weight. **[M]**
4. **Add SHORT-side support to the backtest engine** (it currently sizes/fills LONG) so short strategies get honest verdicts, not silent zeros. **[M]**
5. **Session-align the 1d bar roll-up** to the IST close instead of UTC midnight. **[S]**

### Tier 2 — make the real-instrument path real (blocks live, not paper)
6. **Wire the ETF path end-to-end** (NIFTY→NIFTYBEES etc.) — the only ₹5K-viable route that reuses the equity order path today. **[M]**
7. **Build the options-routing layer** (`execution/option_router.py`): fetch chain → weekly ATM±, size by premium ≤ per-trade risk, map underlying signal → option order. Long-option-only (defined risk). Defer until the ETF path is proven. **[XL]**
8. **Enable BSE/BFO** in the exchange whitelist *only when* the instrument it unlocks (SENSEX ETF/options) is actually routed. **[M]**

### Tier 3 — strengthen analytics & risk
9. **Realized-vs-modeled slippage monitoring** (the `fills` table already captures both) — confirm paper fills aren't optimistic before trusting them with money. **[S–M]**
10. **Tick archival** (compressed Timescale hypertable / Parquet) so today's real ticks become tomorrow's backtest dataset. Deferred by design at 2-index scale — revisit as the universe grows. **[M]**
11. **Parquet export + DuckDB notebook** + a single `promotion_dataset` SQL view that the go-live gate and leaderboard both read. **[M]**
12. **Portfolio/capital allocator + correlation filter** so multiple promoted strategies don't trade the same edge or starve each other at ₹5K / max-3 positions. **[L]**
13. **Feed an India-VIX source into `titan:vix`** so the CRISIS gate uses VIX, not just realized-vol percentile. **[S]**

### Tier 4 — the UI rebuild (parallel, independent)
14. **Finish the React terminal to parity:** Positions, Journal, Strategies (+ auto-pilot arm/disarm; read-only when armed), Analytics, Risk (kill/flatten), System tabs. **[L]**
15. **Live ticks via WebSocket/SSE** to replace 5s polling. **[M]**
16. **Trade overlays on the chart** — entry/exit markers, SL/TP lines, regime ribbon, equity/drawdown subplot. **[M]**
17. **Auth** before exposing the UI beyond localhost. **[S]**
18. **Cutover:** run both UIs in parallel → reach parity → flip default port → retire Streamlit. **[S]**

### Tier 5 — operational hardening (before & during live)
19. **Shadow-live for ≥1 full paper week** (`TITAN_LIVE_DRY_RUN=1`); confirm shadow orders match paper 1:1. **[calendar-bound]**
20. **Pass all 6 readiness gates** (`scripts/readiness_check.sh`): ≥5 paper days, walk-forward Sharpe ≥ threshold, max DD ≤ threshold, loss limit set, creds + JWT, shadow week done. **[S]**
21. **Phone-reachable kill switch** + alerting on feed staleness, risk halts, and reconnect storms. **[M]**
22. **Maintain the NSE/BSE holiday calendar** yearly (movable festivals) and add BSE holidays before BSE goes live. **[S, recurring]**
23. **SEBI algo-compliance check** — automated order placement may need broker-approved/registered algo (`ALGO_ID` already in env). Resolve before live. **[?]**

### The one trap to avoid (from `docs/09`)
> **Never run a large strategy search without (a) rejected-signal capture and
> (b) a deflated-Sharpe gate.** That's how a 50-strategy paper run produces
> confident-but-false winners and loses real money. Both safeguards are already
> built — keep them in the loop for every promotion.

---

## 8. Quick reference — where to look

| You want to… | Go to |
|---|---|
| Understand the architecture | `docs/03_architecture.md`, this file §4 + §5 |
| See the exact risk rules / sizing | this §5.7, `titan/risk/engine.py`, `docs/06` |
| Understand auto-pilot decisions | this §5.6, `docs/08`, `titan/decision/` |
| See strategy logic / the 59 variants | this §5.5, `titan/strategies/library.py` |
| Understand the vetting gate | this §5.9, `titan/backtest/walk_forward.py` |
| See the full data model | this §5.10, `migrations/` |
| See the API request/response schemas | this §5.11, `titan/api/main.py` |
| Understand execution & broker gates | this §5.8, `titan/execution/router.py`, `titan/brokers/` |
| See the dashboard tabs & data sources | this §5.13, `titan/dashboard/app.py` |
| See instrument mapping / backfill | this §5.15, `config/instrument_map.yaml`, `titan/data/` |
| Deploy / dependencies / tests | this §5.16, `pyproject.toml`, `docker-compose.yml` |
| Find a Redis key or env var | this §5.1 + §5.2 |
| Read the deep roadmap analysis | `docs/09_roadmap_analysis.md` |
| See what changed recently & why | `docs/10_changes_and_decisions.md`, `AUTOPSY_FINDINGS.md` |
| Check go-live requirements | `docs/05_live_readiness_checklist.md`, `scripts/readiness_check.sh` |
| Run the stack | `README.md` → "Running the stack" / `scripts/demo.sh` |
| Track the React rebuild | `frontend/README.md` |

---

*This is a living document — update §2, §5, and §6 as goals are met, thresholds
change, or new subsystems land. The numbers in §5 were cross-checked against
source on 2026-06-20; if code and doc disagree, the code wins — fix the doc.*
