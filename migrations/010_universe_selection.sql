-- 010: dynamic universe-selection analysis log
--
-- One row per candidate per selection run: its rank, liquidity score, realized
-- vol (if data existed), and whether it made the traded universe — so the
-- operator's "analyze before selecting" step is auditable.

CREATE TABLE IF NOT EXISTS universe_selection (
    id           BIGSERIAL PRIMARY KEY,
    selected_at  TIMESTAMPTZ NOT NULL,
    symbol       TEXT NOT NULL,
    rank         INTEGER NOT NULL,
    score        NUMERIC(12,4),
    liquidity    NUMERIC(12,4),
    realized_vol NUMERIC(10,4),
    selected     BOOLEAN NOT NULL DEFAULT FALSE,
    reason       TEXT
);

CREATE INDEX IF NOT EXISTS idx_universe_selection_at ON universe_selection (selected_at DESC, rank);
