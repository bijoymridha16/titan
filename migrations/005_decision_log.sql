-- Auto-pilot decision audit trail.
-- Every regime classification + strategy-selection decision is persisted here
-- with its full input vector and human-readable reason. This is the
-- "no hallucination" guarantee: every automated decision is reproducible and
-- explainable after the fact from the exact features it saw.

CREATE TABLE IF NOT EXISTS regime_decisions (
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    ref_symbol      TEXT NOT NULL,             -- the symbol the regime was read from (usually NIFTY)
    regime          TEXT NOT NULL,             -- TREND / RANGE / CRISIS / TRANSITION / CLOSED
    -- raw deterministic features that produced the regime
    adx             NUMERIC(8,3),
    realized_vol    NUMERIC(8,4),              -- annualised, from 5m log-returns
    vol_pctile      NUMERIC(6,3),              -- percentile of realized_vol vs lookback
    or_expansion    NUMERIC(8,4),              -- opening-range width / ATR
    india_vix       NUMERIC(8,3),              -- NULL when no VIX feed present
    session_phase   TEXT,                      -- PREOPEN / OPENING_RANGE / MORNING / LUNCH / AFTERNOON / CUTOFF / CLOSED
    -- the decision
    enabled_before  JSONB,                     -- strategy set before this decision
    enabled_after   JSONB,                     -- strategy set written to Redis
    reason          TEXT NOT NULL              -- plain-English explanation
);
SELECT create_hypertable('regime_decisions', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_regime_decisions_ts ON regime_decisions(ts DESC);
