-- Per-trade latency telemetry.
--   signal_emitted_at — wall-clock when strategy returned the Signal
--   order_filled_at   — wall-clock when broker confirmed FILLED
-- entry_ts stays the BAR timestamp (so trades align with candles on charts);
-- latency analysis uses (order_filled_at - signal_emitted_at).

ALTER TABLE trades ADD COLUMN IF NOT EXISTS signal_emitted_at TIMESTAMPTZ;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS order_filled_at   TIMESTAMPTZ;
