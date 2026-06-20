-- 2026-06-17: news fire rule v2 emits long/short. Track direction so the
-- downstream strategy module knows which side to take.

ALTER TABLE news_signals
    ADD COLUMN IF NOT EXISTS direction TEXT
    CHECK (direction IN ('long', 'short') OR direction IS NULL);

CREATE INDEX IF NOT EXISTS news_signals_dir_idx
    ON news_signals (direction)
    WHERE direction IS NOT NULL;
