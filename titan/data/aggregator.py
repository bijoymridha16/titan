"""Tick → OHLCV aggregator.

Stateless given (symbol, timeframe). Consumes ticks from Redis Stream
`ticks:<symbol>` and emits closed bars on `bars:<symbol>:<tf>`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Iterator


@dataclass
class Tick:
    ts: datetime
    price: float
    volume: int = 0


@dataclass
class Bar:
    ts: datetime  # bar OPEN time
    o: float
    h: float
    l: float
    c: float
    v: int


_TF = {"1m": 60, "3m": 180, "5m": 300, "15m": 900}


def _bucket_start(ts: datetime, seconds: int) -> datetime:
    epoch = int(ts.timestamp())
    bucket = epoch - (epoch % seconds)
    return datetime.fromtimestamp(bucket, tz=ts.tzinfo)


def aggregate(ticks: Iterable[Tick], timeframe: str) -> Iterator[Bar]:
    """Yield CLOSED bars only. Open bar is held back until a tick crosses
    into the next bucket (or stream ends — but then we don't yield it)."""
    secs = _TF[timeframe]
    cur: Bar | None = None
    cur_end: datetime | None = None

    for t in ticks:
        start = _bucket_start(t.ts, secs)
        end = start + timedelta(seconds=secs)

        if cur is None:
            cur = Bar(start, t.price, t.price, t.price, t.price, t.volume)
            cur_end = end
            continue

        if t.ts >= cur_end:
            yield cur
            cur = Bar(start, t.price, t.price, t.price, t.price, t.volume)
            cur_end = end
            continue

        cur.h = max(cur.h, t.price)
        cur.l = min(cur.l, t.price)
        cur.c = t.price
        cur.v += t.volume
