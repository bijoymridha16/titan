-- 010_trades_integrity.sql
-- Guard rails for the trades table.
--
-- 1. exit_ts must not precede entry_ts. Bug fixed in supervisor._check_exits
--    where 1d-bar evaluations stamped exit_ts at start-of-day (before entry).
-- 2. regime must be set. Cold-start before regime classifier wrote NULL;
--    supervisor now defaults to 'UNKNOWN'.

ALTER TABLE trades
  ADD CONSTRAINT trades_exit_after_entry
  CHECK (exit_ts IS NULL OR exit_ts >= entry_ts);

ALTER TABLE trades
  ADD CONSTRAINT trades_regime_required
  CHECK (regime IS NOT NULL);
