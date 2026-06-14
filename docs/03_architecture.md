# 03 — System architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Angel One SmartAPI                              │
│   REST: apiconnect.angelone.in    WSv2: smartapisocket.angelone.in     │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │
                       ┌───────┴────────┐
                       │ AngelOneBroker │  (stub — implement & test
                       │   (brokers/    │   in sandbox before live)
                       │    angelone.py)│
                       └───────┬────────┘
            tick stream        │           order / state
        ┌──────────────────────┴───────────────────────────────────┐
        │                                                          │
        ▼                                                          ▼
┌───────────────┐  Redis Streams ┌──────────────┐  bars   ┌────────────────┐
│ data/feed.py  │ ──ticks:SYM──> │ aggregator   │ ──────> │ strategies/*   │
│ (WS consumer) │                │ (1m/3m/5m/15)│         │ on_bar()       │
└───────────────┘                └──────┬───────┘         └──────┬─────────┘
                                        │                        │ Signal
                                        ▼                        ▼
                              ┌────────────────┐         ┌────────────────┐
                              │ TimescaleDB    │         │ execution/     │
                              │ ohlcv hyper-   │         │   router.py    │
                              │ table          │         └──────┬─────────┘
                              └────────────────┘                │
                                                                ▼
                                                       ┌────────────────┐
                                                       │ risk/engine.py │
                                                       │ pre-trade gate │
                                                       └──────┬─────────┘
                                                              │ approved
                                                              ▼
                                                  ┌────────────────────────┐
                                                  │ BrokerAdapter          │
                                                  │  paper.py  |  angelone │
                                                  └──────┬─────────────────┘
                                                         │ orders / fills
                                                         ▼
                                                  ┌────────────────┐
                                                  │ Postgres       │
                                                  │  orders/trades │
                                                  │  equity_curve  │
                                                  │  risk_events   │
                                                  └──────┬─────────┘
                                                         │
                                ┌────────────────────────┴──────────────────┐
                                ▼                                           ▼
                       ┌────────────────┐                          ┌─────────────────┐
                       │ FastAPI        │                          │ Streamlit       │
                       │ /status /kill  │ <── Redis pub/sub ───>  │ 7-section dash  │
                       │ /flatten       │   (titan:control,        │                 │
                       │                │    titan:kill)           │                 │
                       └────────────────┘                          └─────────────────┘
                                ▲
                                │
                       Telegram alerts (telemetry/alerts.py)
```

## Process layout (single host, paper phase)

| Container | Purpose |
|---|---|
| `postgres`  | TimescaleDB 16 — OHLCV hypertable, orders/trades, equity_curve, risk_events |
| `redis`     | Streams (ticks/bars), control pub/sub, kill switch, heartbeats |
| `feed`      | One process per market segment; SmartAPI WS → Redis Streams |
| `strategy-*`| One process per strategy; consumes bars, emits orders via router |
| `api`       | FastAPI control plane (status / kill / flatten) |
| `dashboard` | Streamlit (Phase 1); replace with React+TradingView in Phase 2 |

Sub-second latency is not required (intraday on 1m+). Single-host (DO/Hetzner
Mumbai) is sufficient through paper and small-cap live. Move to dedicated
network when notional ≥ ₹25L or strategy count > 5.

## Why this shape

- **Same `Strategy` interface across backtest, paper, live.** The bt_runner
  drives strategies with historical bars and a PaperBroker — exact same
  router + risk path as live. Eliminates "works in backtest, breaks live"
  by construction.
- **Risk engine is a pre-trade gate, not an afterthought.** Every order
  passes `RiskEngine.check()` before reaching any broker call. Sticky
  daily halts; kill switch is a Redis flag any component can flip.
- **Reconciler over local cache.** Local position state is best-effort;
  reconciler polls the broker every 5s and emits drift events. Source of
  truth lives at the broker.
- **No silent retries.** Broker errors halt the strategy and Telegram-alert.
  Capital preservation > uptime.

## Data flow specifics

1. Angel One WS V2 returns binary frames. Parser is per the published spec
   (mode 1 LTP / mode 2 quote / mode 3 snapquote). Frame size depends on mode.
2. Aggregator is stateless given `(symbol, timeframe)`. Restart-safe by
   re-reading ticks back from `XLEN`'s prior position (Redis Streams retain
   `maxlen=10_000` ticks ~= 8 minutes at 20 tps).
3. Bars are written to Timescale on close. Strategies subscribe via Redis
   pub/sub on `bars:<symbol>:<tf>` for low-latency triggers; replay from
   Postgres on restart.

## Live cutover plan

Listed for completeness — the readiness checklist gates this.

1. Replace `AngelOneBroker.connect()` stub with real login + TOTP.
2. Implement binary tick parser in `data/feed.py`.
3. Implement `place_order/cancel_order/get_positions/get_ltp/get_funds`.
4. Add daily 05:30 IST cron to refresh JWT (tokens expire daily).
5. Run paper-trading mode against live data for ≥60 days.
6. Pass readiness checklist (`docs/05_live_readiness_checklist.md`).
7. Set `TITAN_MODE=live` + start with `--i-understand-this-trades-real-money`.
8. Start with ≤ ₹50k notional; scale only after 100 live trades and PF ≥ 1.5.
