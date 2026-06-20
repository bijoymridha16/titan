-- Link each trade to the market regime it was opened in, so we can answer the
-- single most important pre-live question: "which regimes does this strategy
-- actually make money in?" Enables regime-conditioned P&L in the Analytics tab.
ALTER TABLE trades ADD COLUMN IF NOT EXISTS regime TEXT;
CREATE INDEX IF NOT EXISTS idx_trades_regime ON trades(regime);
