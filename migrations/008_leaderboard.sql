-- Strategy vetting leaderboard. One row per factory variant after a
-- walk-forward run, with its multiple-testing-corrected verdict (SHIP/KILL).
-- This is the evidence that decides which strategies earn a place on the
-- auto-pilot's validated allowlist before any real capital is risked.
CREATE TABLE IF NOT EXISTS leaderboard (
    variant_key         TEXT PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    family              TEXT,
    params              JSONB,
    trades              INTEGER,
    net_pnl             NUMERIC(16,2),
    sharpe              NUMERIC(10,4),
    deflated_threshold  NUMERIC(10,4),   -- Sharpe a best-of-N fluke would reach
    profit_factor       NUMERIC(10,4),
    max_dd_pct          NUMERIC(10,4),
    symbols_tested      INTEGER,
    symbols_profitable  INTEGER,
    passed              BOOLEAN NOT NULL DEFAULT FALSE,
    verdict             TEXT,            -- SHIP / KILL
    reasons             TEXT
);
CREATE INDEX IF NOT EXISTS idx_leaderboard_verdict ON leaderboard(verdict, sharpe DESC);
