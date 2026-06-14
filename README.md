# TITAN

> Institutional-grade intraday algorithmic trading platform for the Indian NSE markets, targeting **₹5,000 live capital** via Angel One SmartAPI.

**Status:** paper-mode rehearsal. **NOT YET TRADING LIVE.** See `docs/05_live_readiness_checklist.md`.

---

## Table of Contents

1. [What TITAN does](#what-titan-does)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Setup (first time)](#setup-first-time)
5. [Running the stack](#running-the-stack)
6. [Daily workflow](#daily-workflow)
7. [Strategies](#strategies)
8. [Risk & safety rails](#risk--safety-rails)
9. [Going live](#going-live)
10. [Configuration reference](#configuration-reference)
11. [Project layout](#project-layout)
12. [Testing](#testing)
13. [Troubleshooting](#troubleshooting)

---

## What TITAN does

TITAN is an end-to-end algo trading stack:

- Ingests live ticks from Angel One SmartAPI (or a synthetic feed for testing)
- Aggregates ticks → 1m/3m/5m/15m OHLCV bars in TimescaleDB
- Runs pluggable strategies (currently **ORB** — Opening Range Breakout)
- Executes via a **paper broker** (always) with optional **shadow live dry-run** on Angel One
- Gates every order through an 8-check RiskEngine + 5-check live broker
- Surfaces everything in a Streamlit dashboard and a FastAPI control plane

The design invariant: **backtest, paper, and live use the same `Strategy` interface and the same `RiskEngine`** — what passes paper is exactly what will run live.

## Architecture

```
                ┌──────────────────┐
                │  Angel One WS    │   (or SynthFeed)
                └────────┬─────────┘
                         │ ticks
                         ▼
                 ┌────────────────┐         ┌──────────────────┐
                 │  Redis Streams │ ──────► │   bar_writer     │
                 │  ticks:<sym>   │         │ ticks → OHLCV    │
                 └────────────────┘         └────────┬─────────┘
                                                     │
                            ┌────────────────────────┼──────────────────┐
                            ▼                        ▼                  ▼
                  ┌────────────────┐    ┌──────────────────┐   ┌────────────────┐
                  │  TimescaleDB   │    │  Redis pub/sub   │   │ news/ingest    │
                  │  ohlcv hyper   │    │  bars:<sym>:<tf> │   │ FinBERT → CSV  │
                  └────────┬───────┘    └────────┬─────────┘   └────────────────┘
                           │ window read         │
                           └──────────┬──────────┘
                                      ▼
                            ┌──────────────────┐
                            │   Supervisor     │ ── orchestrates strategies
                            │  on_bar_event()  │
                            └────────┬─────────┘
                                     │ Signal
                                     ▼
                          ┌─────────────────────┐
                          │     RiskEngine      │ ── 8 gates
                          └──────────┬──────────┘
                                     │ approved Order
                            ┌────────┴────────┐
                            ▼                 ▼
                   ┌────────────────┐  ┌──────────────────┐
                   │  PaperBroker   │  │ AngelOneBroker   │ ── 5 gates
                   │ (always)       │  │ (shadow / live)  │
                   └────────┬───────┘  └────────┬─────────┘
                            │                   │
                            └─────────┬─────────┘
                                      ▼
                            ┌──────────────────┐
                            │ trades / journal │ ── Postgres + dashboard
                            └──────────────────┘
```

Control plane: **FastAPI** at `:8000`. Dashboard: **Streamlit** at `:8501`.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.11+ (3.14 tested) | Runtime |
| Docker + Docker Compose | any recent | Postgres + Redis |
| Git | any | Source control |
| Angel One SmartAPI credentials | — | Only for live or shadow-live runs. **Paper mode works without them.** |
| ~5 GB free disk | — | TimescaleDB + FinBERT model |

macOS, Linux, and WSL2 all work. The dev loop is tested on macOS (Darwin 25).

## Setup (first time)

```bash
git clone https://github.com/bijoymridha16/titan.git
cd titan

# 1. Python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Infra (Postgres + Redis)
docker compose up -d postgres redis

# 3. DB schema (TimescaleDB hypertables + news tables)
psql "$(grep TITAN_DB_URL .env.example | cut -d= -f2-)" -f migrations/001_init.sql
psql "$(grep TITAN_DB_URL .env.example | cut -d= -f2-)" -f migrations/002_instruments_master.sql
psql "$(grep TITAN_DB_URL .env.example | cut -d= -f2-)" -f migrations/003_news_tables.sql

# 4. Config
cp .env.example .env
# edit .env — see "Configuration reference" below

# 5. Smoke test
pytest                       # all tests should pass
```

For news ingestion (optional in Phase 1):

```bash
# downloads ProsusAI/finbert (~440 MB) on first run
python -m titan.news.ingest --hours 24 --csv
```

## Running the stack

TITAN runs as **five long-lived processes** plus the synth feed (only in dev). The simplest dev cycle:

```bash
# terminal 1: tick source (synthetic — or live Angel WS)
python -m titan.data.synth_feed                    # synth (recommended for dev)
# OR
python -m titan.data.angelone_ws                   # live ticks (needs creds)

# terminal 2: tick → bar aggregator
python -m titan.data.bar_writer

# terminal 3: strategy supervisor (runs ORB, manages exits, persists trades)
python -m titan.strategies.supervisor

# terminal 4: control plane
uvicorn titan.api.main:app --port 8000

# terminal 5: dashboard
streamlit run titan/dashboard/app.py --server.port 8501
```

Then open:
- Dashboard: http://localhost:8501
- API docs: http://localhost:8000/docs

**Shortcut** — `scripts/demo.sh` brings everything up with logs redirected to `/tmp/titan-*.log`.

### Enabling / disabling a strategy at runtime

```bash
curl -X POST http://localhost:8000/strategies/orb/start
curl -X POST http://localhost:8000/strategies/orb/stop
```

Strategies are tracked in a Redis set `titan:strategies:enabled`. The supervisor checks this on every bar.

### Kill switch

```bash
curl -X POST http://localhost:8000/kill              # halts new orders
curl -X POST http://localhost:8000/flatten           # closes open positions
```

Or from the dashboard's red "KILL" button. Backed by Redis key `titan:kill`.

## Daily workflow

### Paper-only day (default)

1. Start the stack (`scripts/demo.sh` or 5 terminals).
2. Open dashboard → confirm **🧪 SYNTH** pill or **NSE OPEN** indicator.
3. Enable ORB: `curl -X POST :8000/strategies/orb/start`.
4. Watch trades flow into the "Open Positions" and "Journal" panels.
5. At end of day, review PnL and trade quality.

### Pre-live readiness check

Before flipping live, run:

```bash
bash scripts/readiness_check.sh
```

This validates 6 gates:
1. ≥5 trading days of paper trades captured
2. Walk-forward Sharpe ≥ predeclared threshold
3. Max drawdown ≤ predeclared threshold
4. Daily loss limit configured
5. AngelOne credentials present + JWT obtainable
6. Live broker in `dry_run=true` shadow mode for ≥1 paper week

## Strategies

| Name | Status | Timeframe | Description |
|---|---|---|---|
| **ORB** (Opening Range Breakout) | 🟢 **live candidate** | 5m | Long > OR_high / short < OR_low after 09:30 IST. Stop = opposite OR side. Target = 1.5R. Cutoff 14:30 IST. |
| **TSMOM** (Time-Series Momentum) | 🔴 **KILLED** | 1d | Killed by walk-forward backtest — Sharpe/DD failed predeclared thresholds. Endpoint returns 409. |
| **NDET** (News-Driven Event Trading) | 🟡 **Phase 1 only** | event | Ingests NSE/BSE corp announcements + RSS, FinBERT sentiment, dry-run CSV only. No trading code until Gate review passes. |

Strategy code lives in `titan/strategies/`. Each implements `on_bar(bars: pd.DataFrame) -> list[Signal]`.

To add a new strategy:
1. Create `titan/strategies/my_strat.py` subclassing `Strategy`
2. Add to `STRATEGIES` dict in `titan/strategies/supervisor.py`
3. Write unit tests under `tests/test_strategies/`
4. **Run walk-forward backtest** with predeclared ship/kill thresholds — don't tune them after the fact
5. If it ships, add to dashboard toggle list

## Risk & safety rails

Defense in depth — every order passes through **two layers** before reaching the exchange.

**Layer 1 — RiskEngine (8 gates, in `titan/risk/engine.py`):**
1. Kill switch off
2. Within trading hours (09:15–15:15 IST)
3. Strategy enabled
4. Symbol not on blocklist
5. Position size ≤ per-trade risk budget
6. Daily loss limit not breached
7. Max open positions not exceeded
8. Notional limit not exceeded

**Layer 2 — Live broker (5 gates, in `titan/brokers/angelone.py`):**
1. `live_enabled=true` (env flag)
2. Product in `allowed_products`
3. Exchange in `allowed_exchanges`
4. Order value ≤ `max_order_value`
5. `dry_run=false` (otherwise logs intent and returns)

A signal can fail at any gate and the order won't go through. Rejections are logged with the failing gate name.

**Also:**
- TSMOM is killed at the API layer (returns 409) AND hidden from the dashboard
- Synth mode is clearly badged with 🧪 SYNTH pill
- All processes log to `/tmp/titan-*.log` — `tail -f` everything during ramp-up

## Going live

⚠️ **Read `docs/05_live_readiness_checklist.md` first.**

1. Set `TITAN_LIVE_DRY_RUN=1` and run shadow live for at least one full paper week (Mon–Fri)
2. Confirm shadow orders match paper orders (1:1 signal generation)
3. Confirm `readiness_check.sh` passes all 6 gates
4. Confirm tradable instrument routing — **indices are not directly tradable**; use NIFTYBEES/BANKBEES ETFs at ₹5K capital
5. Flip `TITAN_LIVE_DRY_RUN=0` Friday morning, monitor first 30 min closely
6. Keep kill switch reachable from phone (dashboard or `/kill` endpoint)

## Configuration reference

All config in `.env`. See `.env.example` for the full template. Key vars:

| Var | Default | Purpose |
|---|---|---|
| `TITAN_DB_URL` | `postgresql://titan:titan@localhost:5432/titan` | TimescaleDB |
| `TITAN_REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `TITAN_SYMBOLS` | `NIFTY,BANKNIFTY,FINNIFTY,RELIANCE,HDFCBANK,ICICIBANK` | Universe |
| `TITAN_PAPER_CAPITAL` | `500000` | Paper-mode notional (larger for statistical signal) |
| `TITAN_LIVE_CAPITAL` | `5000` | Live notional cap |
| `TITAN_LIVE_ENABLED` | `0` | Master live switch |
| `TITAN_LIVE_DRY_RUN` | `1` | If 1, live broker logs intent but doesn't submit |
| `TITAN_ALLOWED_PRODUCTS` | `INTRADAY` | Live broker whitelist |
| `TITAN_ALLOWED_EXCHANGES` | `NSE` | Live broker whitelist |
| `TITAN_MAX_ORDER_VALUE` | `5000` | Live notional cap per order |
| `ANGELONE_API_KEY` | — | SmartAPI key |
| `ANGELONE_CLIENT_CODE` | — | Login code |
| `ANGELONE_PIN` | — | Login PIN |
| `ANGELONE_TOTP_SECRET` | — | TOTP seed for 2FA |
| `NEWS_SCRAPE_ENABLED` | `0` | Set 1 to enable Moneycontrol/ET HTML scrapers (RSS always on) |

## Project layout

```
titan/
├── titan/                  # main package
│   ├── api/                # FastAPI control plane (kill, flatten, strategies/*)
│   ├── backtest/           # event-driven backtester with walk-forward harness
│   ├── brokers/            # paper.py, angelone.py (live + shadow)
│   ├── dashboard/          # Streamlit UI
│   ├── data/               # synth_feed.py, bar_writer.py, backfill.py
│   ├── execution/          # order router, fills, reconciler
│   ├── news/               # sources/, entities, sentiment (FinBERT), ingest
│   ├── risk/               # RiskEngine + sizing
│   ├── strategies/         # base, supervisor, orb, tsmom (killed)
│   └── telemetry/          # logging, Telegram alerts
├── tests/                  # pytest suite (~60 tests)
├── docs/                   # research, architecture, readiness checklist
├── config/                 # nifty50_aliases.yaml, news_noise_filters.yaml
├── migrations/             # SQL migrations (manual, not alembic)
├── scripts/                # demo.sh, readiness_check.sh, backtests
├── pyproject.toml
├── docker-compose.yml      # postgres + redis
├── .env.example
└── README.md               # this file
```

## Testing

```bash
pytest                              # full suite
pytest tests/test_strategies/       # strategy tests only
pytest -k orb                       # tests matching 'orb'
pytest -x                           # stop at first failure
```

Backtests (walk-forward, with predeclared thresholds):

```bash
python scripts/run_tsmom_backtest.py    # killed strategy; left as reference
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Dashboard shows "NSE CLOSED" during synth run | Real time after 15:30 IST | The synth pill should override. If not, restart dashboard. |
| No bars flowing in pub/sub | `bar_writer` not running OR no ticks | Check `ps`, check Redis stream `XLEN ticks:NIFTY`. |
| ORB never fires | Sim clock outside session OR stale OHLCV ordering | Synth wraps 15:30→09:15 IST every cycle. If still silent, truncate intraday OHLCV: `DELETE FROM ohlcv WHERE timeframe IN ('1m','3m','5m','15m')`. |
| `TimeoutError: Timeout reading from localhost:6379` in supervisor | Redis pub/sub idle past socket timeout | Already hardened — uses `get_message(timeout=5)` + catch. Restart supervisor if older code. |
| AngelOne login fails | Wrong creds / TOTP drift / IP block | Re-check `.env`, re-sync TOTP, try from a fresh IP. |
| FinBERT model download stalls | First-run pulling ~440 MB | Wait, or pre-download: `python -c "from transformers import pipeline; pipeline('sentiment-analysis', model='ProsusAI/finbert')"` |

For anything else, check `/tmp/titan-*.log` — every process logs there.

---

## Design invariants

- Every order goes through `risk.engine.RiskEngine.check()`. No exceptions.
- Backtest, paper, and live share the **same** `Strategy` interface and **same** `RiskEngine`.
- Live trading is gated by an env flag + dry-run flag + product/exchange whitelists + per-order cap.
- Kill switch is a single Redis key (`titan:kill`); any component checks it before placing an order.
- No silent retries on broker errors — fail loudly, alert, halt the strategy.
- **No tuning to pass a backtest.** Ship/kill thresholds are predeclared; failing strategies are killed, not re-tuned.

## License

Private. Not for distribution.
