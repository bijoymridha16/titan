-- News-Driven Event Trading (NDET) schema. See docs/research/02_news_driven.md.

-- raw, deduped news as ingested. one row per (source, source_id).
CREATE TABLE IF NOT EXISTS news_events (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,                 -- nse_ann | bse_ann | mc_rss | et_rss | mc_html | et_html
    source_id       TEXT NOT NULL,                 -- the source's own id / hash of url
    published_at    TIMESTAMPTZ NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    headline        TEXT NOT NULL,
    body            TEXT,
    url             TEXT,
    raw_symbol      TEXT,                          -- whatever the source said (NSE may give the ticker directly)
    raw             JSONB,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS news_events_published_idx ON news_events (published_at DESC);
CREATE INDEX IF NOT EXISTS news_events_raw_symbol_idx ON news_events (raw_symbol);

-- one row per (news_event × resolved ticker). a single headline may mention 2+ names.
CREATE TABLE IF NOT EXISTS news_entities (
    news_event_id   BIGINT NOT NULL REFERENCES news_events(id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,                 -- our internal symbol e.g. RELIANCE
    matched_alias   TEXT NOT NULL,                 -- the literal string that matched
    confidence      REAL NOT NULL,                 -- 0..1
    method          TEXT NOT NULL,                 -- exact | alias | fuzzy
    PRIMARY KEY (news_event_id, ticker)
);
CREATE INDEX IF NOT EXISTS news_entities_ticker_idx ON news_entities (ticker);

-- FinBERT cache keyed by sha256 of the (model_id, headline). reused across rows.
CREATE TABLE IF NOT EXISTS sentiment_cache (
    cache_key       TEXT PRIMARY KEY,              -- sha256(model_id || ':' || headline)
    model_id        TEXT NOT NULL,
    headline        TEXT NOT NULL,
    label           TEXT NOT NULL,                 -- negative | neutral | positive
    score           REAL NOT NULL,                 -- max-probability
    neg_p           REAL NOT NULL,
    neu_p           REAL NOT NULL,
    pos_p           REAL NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- the joined product. one row per (news_event × ticker), enriched with
-- sentiment + category + would_fire decision. this is what the dry-run CSV
-- reads from, and what NewsStrategy.on_event() will consume in phase 5.
CREATE TABLE IF NOT EXISTS news_signals (
    id              BIGSERIAL PRIMARY KEY,
    news_event_id   BIGINT NOT NULL REFERENCES news_events(id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL,
    headline        TEXT NOT NULL,
    source          TEXT NOT NULL,
    category        TEXT NOT NULL,                 -- earnings | m_and_a | regulatory | dividend | block_deal | other
    sentiment_label TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    entity_conf     REAL NOT NULL,
    would_fire      BOOLEAN NOT NULL DEFAULT FALSE,
    fire_reason     TEXT,
    UNIQUE (news_event_id, ticker)
);
CREATE INDEX IF NOT EXISTS news_signals_ticker_pub_idx ON news_signals (ticker, published_at DESC);
CREATE INDEX IF NOT EXISTS news_signals_fire_idx ON news_signals (would_fire) WHERE would_fire = TRUE;
