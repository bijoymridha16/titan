-- TITAN initial schema. Run via psql or alembic.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS instruments (
    symbol          TEXT PRIMARY KEY,
    exchange        TEXT NOT NULL,
    token           TEXT NOT NULL,
    instrument_type TEXT NOT NULL,            -- EQ / FUT / CE / PE / IDX
    lot_size        INTEGER NOT NULL DEFAULT 1,
    tick_size       NUMERIC(10,4) NOT NULL DEFAULT 0.05,
    expiry          DATE,
    strike          NUMERIC(12,2)
);

CREATE TABLE IF NOT EXISTS ohlcv (
    ts          TIMESTAMPTZ NOT NULL,
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,                -- 1m / 3m / 5m / 15m
    o NUMERIC(12,4), h NUMERIC(12,4), l NUMERIC(12,4), c NUMERIC(12,4),
    v BIGINT,
    PRIMARY KEY (symbol, timeframe, ts)
);
SELECT create_hypertable('ohlcv', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS orders (
    id              UUID PRIMARY KEY,
    broker_order_id TEXT,
    strategy        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,            -- BUY / SELL
    qty             INTEGER NOT NULL,
    price           NUMERIC(12,4),
    order_type      TEXT NOT NULL,            -- MARKET / LIMIT / SL / SL-M
    product         TEXT NOT NULL,            -- INTRADAY / MIS / NRML
    status          TEXT NOT NULL,            -- NEW / OPEN / FILLED / REJECTED / CANCELLED
    placed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    filled_at       TIMESTAMPTZ,
    avg_fill_price  NUMERIC(12,4),
    reject_reason   TEXT,
    is_paper        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS trades (
    id              UUID PRIMARY KEY,
    strategy        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    side            TEXT NOT NULL,
    entry_ts        TIMESTAMPTZ NOT NULL,
    entry_price     NUMERIC(12,4) NOT NULL,
    exit_ts         TIMESTAMPTZ,
    exit_price      NUMERIC(12,4),
    stop_loss       NUMERIC(12,4),
    target          NUMERIC(12,4),
    pnl             NUMERIC(14,2),
    exit_reason     TEXT,
    is_paper        BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_trades_strategy_ts ON trades(strategy, entry_ts DESC);

CREATE TABLE IF NOT EXISTS risk_events (
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,                -- DAILY_LOSS_HALT / DD_HALT / CONSEC_LOSS / KILL_SWITCH / SIZING_REJECT
    detail      JSONB
);
SELECT create_hypertable('risk_events', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS equity_curve (
    ts      TIMESTAMPTZ NOT NULL,
    equity  NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (ts)
);
SELECT create_hypertable('equity_curve', 'ts', if_not_exists => TRUE);
