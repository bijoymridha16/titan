-- 009: operator decision journal
--
-- An audit trail of decisions made by the autonomous operator (Claude) while
-- running TITAN: WHAT was changed, WHY, and the reasoning behind it. The system
-- already journals trades/signals/fills/regime automatically; this captures the
-- human-equivalent operator layer so the run can be analysed and the platform
-- optimised afterwards.

CREATE TABLE IF NOT EXISTS operator_decisions (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       TEXT NOT NULL DEFAULT 'claude-operator',
    category    TEXT NOT NULL,             -- config | risk | strategy | ops | analysis | hypothesis
    title       TEXT NOT NULL,             -- short headline
    action      TEXT NOT NULL,             -- exactly what was done
    rationale   TEXT NOT NULL,             -- why it was done
    thinking    TEXT,                      -- deeper reasoning / context
    params      JSONB,                     -- structured before/after values
    expected    TEXT,                      -- hypothesis / expected effect to verify later
    status      TEXT NOT NULL DEFAULT 'applied'   -- applied | reverted | observed
);

CREATE INDEX IF NOT EXISTS idx_operator_decisions_ts  ON operator_decisions (ts DESC);
CREATE INDEX IF NOT EXISTS idx_operator_decisions_cat ON operator_decisions (category, ts DESC);
