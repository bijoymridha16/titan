"""TimescaleDB OHLCV reader/writer (thin wrapper over psycopg)."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import pandas as pd
from sqlalchemy import create_engine, text

from titan.config import settings


_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.db_url, pool_pre_ping=True, future=True)
    return _engine


def write_bars(symbol: str, timeframe: str, bars: Iterable) -> None:
    rows = [
        {"ts": b.ts, "symbol": symbol, "timeframe": timeframe,
         "o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": b.v}
        for b in bars
    ]
    if not rows:
        return
    sql = text("""
        INSERT INTO ohlcv (ts, symbol, timeframe, o, h, l, c, v)
        VALUES (:ts, :symbol, :timeframe, :o, :h, :l, :c, :v)
        ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET
            o=EXCLUDED.o, h=EXCLUDED.h, l=EXCLUDED.l, c=EXCLUDED.c, v=EXCLUDED.v
    """)
    with engine().begin() as cx:
        cx.execute(sql, rows)


def read_bars(symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
    sql = text("""
        SELECT ts, o, h, l, c, v FROM ohlcv
        WHERE symbol = :s AND timeframe = :tf AND ts BETWEEN :a AND :b
        ORDER BY ts
    """)
    with engine().connect() as cx:
        return pd.read_sql(sql, cx, params={"s": symbol, "tf": timeframe, "a": start, "b": end},
                           parse_dates=["ts"], index_col="ts")
