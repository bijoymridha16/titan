# TITAN

Algorithmic intraday trading platform for NSE (Angel One SmartAPI), starting in paper mode.

**Status:** scaffold. **NOT READY FOR LIVE CAPITAL.** See `docs/05_live_readiness_checklist.md`.

## Quick start

```bash
cp .env.example .env
# fill ANGELONE_* once you have credentials (paper mode does not need them)
docker compose up -d postgres redis
pip install -e ".[dev]"
alembic upgrade head
uvicorn titan.api.main:app --reload
streamlit run titan/dashboard/app.py
pytest
```

## Layout

| Path | Purpose |
|---|---|
| `titan/brokers/` | Broker adapters: `base.py` ABC, `paper.py` simulator, `angelone.py` SmartAPI (stubbed) |
| `titan/data/` | WebSocket tick feed → Redis Streams → TimescaleDB OHLCV |
| `titan/strategies/` | Pluggable strategies (ORB, VWAP-revert, Supertrend+ADX) |
| `titan/risk/` | Pre-trade risk engine, sizing, limits — **gates every order** |
| `titan/execution/` | Order state machine + reconciler |
| `titan/backtest/` | VectorBT (sweeps) + Backtrader (event-driven) runners |
| `titan/api/` | FastAPI control plane: `/kill`, `/flatten`, `/status` |
| `titan/dashboard/` | Streamlit 7-section dashboard |
| `titan/telemetry/` | Structured logging + Telegram alerts |
| `docs/` | Strategy research, architecture, risk framework, readiness checklist |

## Design invariants

- Every order goes through `risk.engine.RiskEngine.check()`. No exceptions.
- Backtest, paper, and live use the same `Strategy` interface and same `RiskEngine`.
- `TITAN_MODE=live` requires an explicit additional confirmation flag at process start (`--i-understand-this-trades-real-money`).
- Kill switch is a single Redis key (`titan:kill`); any component checks it before placing an order.
- No silent retries on broker errors — fail loudly, alert, halt the strategy.
