-- Rebuild instruments to match Angel One scrip master shape.
-- Natural key: (exch_seg, token). Symbol is NOT unique (NIFTY exists in NSE as
-- index and in NFO with date-suffixed futures/options symbols).

DROP TABLE IF EXISTS instruments CASCADE;

CREATE TABLE instruments (
    exch_seg        TEXT NOT NULL,           -- NSE / BSE / NFO / MCX / CDS
    token           TEXT NOT NULL,           -- Angel symboltoken
    symbol          TEXT NOT NULL,           -- tradingsymbol (e.g. NIFTY28AUG25FUT)
    name            TEXT,                    -- base ticker (e.g. NIFTY, RELIANCE)
    instrumenttype  TEXT,                    -- AMXIDX / FUTIDX / OPTIDX / FUTSTK / OPTSTK / EQ
    expiry          DATE,
    strike          NUMERIC(12,2),
    lotsize         INTEGER DEFAULT 1,
    tick_size       NUMERIC(10,4) DEFAULT 0.05,
    refreshed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (exch_seg, token)
);

CREATE INDEX idx_instr_name   ON instruments(name);
CREATE INDEX idx_instr_symbol ON instruments(symbol);
CREATE INDEX idx_instr_expiry ON instruments(expiry);
