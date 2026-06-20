-- P5: full data capture for pre-live analytics.
--
-- The trading loop previously kept only FILLED trades. Everything else — every
-- signal a strategy emitted, every signal we REJECTED (and why), every routed
-- order attempt, the realized-vs-modeled slippage on each fill, and the feature
-- vector at decision time — was thrown away. These tables capture all of it, so
-- the paper→live decision rests on complete evidence, not just the winners.
--
-- Regular (non-hyper) tables: analytics-event volume is low (a handful of
-- signals/orders per symbol per day). Raw-tick archival (high volume) is a
-- separate, deferred decision (see docs/09 D8/D9) and would use a hypertable +
-- Timescale compression.

-- Every signal a strategy produced — accepted OR rejected, with the reason.
CREATE TABLE IF NOT EXISTS signals (
    id              UUID PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    strategy        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    kind            TEXT NOT NULL,          -- ENTRY_LONG / ENTRY_SHORT / EXIT
    entry           NUMERIC(14,4),
    stop            NUMERIC(14,4),
    target          NUMERIC(14,4),
    per_unit_risk   NUMERIC(14,4),
    confidence      NUMERIC(6,4),
    regime          TEXT,                   -- market regime at decision time
    accepted        BOOLEAN NOT NULL,       -- did it pass to execution?
    reject_reason   TEXT,                   -- why not (dedup, exit-handled, risk, sizing…)
    order_id        UUID,                   -- link to order_attempts when accepted
    reason          TEXT                    -- the strategy's own signal reason
);
CREATE INDEX IF NOT EXISTS idx_signals_ts        ON signals(ts DESC);
CREATE INDEX IF NOT EXISTS idx_signals_strat_sym ON signals(strategy, symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_signals_accepted  ON signals(accepted, ts DESC);

-- Every order routed through the RiskEngine — including risk rejections.
CREATE TABLE IF NOT EXISTS order_attempts (
    id              UUID PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal_id       UUID,
    strategy        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,          -- BUY / SELL
    qty_requested   INTEGER,
    qty_final       INTEGER,
    order_type      TEXT,
    product         TEXT,
    price           NUMERIC(14,4),
    risk_approved   BOOLEAN NOT NULL,
    risk_reason     TEXT,
    broker          TEXT,                   -- paper / angelone(shadow)
    status          TEXT,                   -- FILLED / REJECTED / OPEN …
    broker_order_id TEXT,
    avg_fill_price  NUMERIC(14,4),
    reject_reason   TEXT
);
CREATE INDEX IF NOT EXISTS idx_order_attempts_ts  ON order_attempts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_order_attempts_sig ON order_attempts(signal_id);

-- Realized fill quality — for slippage analytics (modeled vs realized).
CREATE TABLE IF NOT EXISTS fills (
    id                  UUID PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    order_id            UUID,
    strategy            TEXT,
    symbol              TEXT NOT NULL,
    side                TEXT NOT NULL,
    qty                 INTEGER,
    fill_price          NUMERIC(14,4),
    ltp_at_decision     NUMERIC(14,4),
    modeled_slippage_bps NUMERIC(10,4),
    realized_slippage_bps NUMERIC(10,4),
    is_paper            BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_fills_ts  ON fills(ts DESC);
CREATE INDEX IF NOT EXISTS idx_fills_sym ON fills(symbol, ts DESC);

-- The feature vector the decision was made on (indicators/window snapshot).
-- JSONB so the schema never churns as strategies evolve.
CREATE TABLE IF NOT EXISTS feature_snapshots (
    id          UUID PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    strategy    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    signal_id   UUID,
    features    JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_ts ON feature_snapshots(ts DESC);
