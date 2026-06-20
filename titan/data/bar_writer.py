"""Consume Redis Streams `ticks:<symbol>` → aggregate to OHLCV → write to
TimescaleDB and publish closed bars to Redis pub/sub `bars:<symbol>:<tf>`.

Run:
    python -m titan.data.bar_writer
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict

import redis
from sqlalchemy import text

from titan.config import settings
from titan.data.aggregator import Bar, _bucket_start
from titan.data.store import engine
from titan.data.tick_filter import TickSanitizer

log = logging.getLogger(__name__)
# 1d included so daily-timeframe strategies (e.g. TSMOM) actually receive bars
# (AUTOPSY_FINDINGS M1). NOTE: the 1d bucket aligns to UTC midnight, not the IST
# session — close enough for daily-trend strategies; a session-aligned daily
# roll-up is a future refinement.
TIMEFRAMES = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "1d": 86400}


class _BucketState:
    __slots__ = ("bar", "end_ts")
    def __init__(self, bar: Bar, end_ts: float):
        self.bar = bar
        self.end_ts = end_ts


def _new_bar(start: datetime, price: float, vol: int) -> Bar:
    return Bar(start, price, price, price, price, vol)


def _insert_bar(symbol: str, tf: str, b: Bar) -> None:
    sql = text("""
        INSERT INTO ohlcv (ts, symbol, timeframe, o, h, l, c, v)
        VALUES (:ts, :s, :tf, :o, :h, :l, :c, :v)
        ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET
          o=EXCLUDED.o, h=EXCLUDED.h, l=EXCLUDED.l, c=EXCLUDED.c, v=EXCLUDED.v
    """)
    with engine().begin() as cx:
        cx.execute(sql, {"ts": b.ts, "s": symbol, "tf": tf,
                         "o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": b.v})


def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    r = redis.from_url(settings.redis_url, decode_responses=True)
    streams = {f"ticks:{s}": "$" for s in settings.symbols}
    state: Dict[tuple[str, str], _BucketState] = {}
    sanitizers: Dict[str, TickSanitizer] = {}
    log.info("bar_writer: streams=%s timeframes=%s tick_filter=%s",
             list(streams.keys()), list(TIMEFRAMES), settings.tick_filter_enabled)

    while True:
        try:
            resp = r.xread(streams, count=200, block=2000)
        except Exception as e:
            log.exception("xread failed: %s", e); time.sleep(2); continue
        if not resp:
            continue
        for stream_key, entries in resp:
            symbol = stream_key.split(":", 1)[1]
            for entry_id, fields in entries:
                streams[stream_key] = entry_id
                try:
                    t = json.loads(fields["data"])
                except Exception:
                    continue
                ts = datetime.fromisoformat(t["ts"].replace("Z", "+00:00"))
                price = float(t["ltp"]); vol = int(t.get("volume", 0))

                # Scenario A: drop corrupted quotes before they reach the OHLCV
                # path. Rejected ticks go to a dead-letter stream for inspection.
                if settings.tick_filter_enabled:
                    san = sanitizers.get(symbol)
                    if san is None:
                        san = sanitizers[symbol] = TickSanitizer(
                            n_sigma=settings.tick_outlier_sigma,
                            window_s=settings.tick_filter_window_s,
                            min_samples=settings.tick_filter_min_samples)
                    if not san.accept(ts, price, vol):
                        log.warning("tick outlier dropped: %s price=%.2f", symbol, price)
                        try:
                            r.xadd(f"ticks:deadletter:{symbol}",
                                   {"data": fields["data"]},
                                   maxlen=2_000, approximate=True)
                        except Exception:
                            pass
                        continue

                for tf, secs in TIMEFRAMES.items():
                    key = (symbol, tf)
                    start = _bucket_start(ts, secs)
                    end = start.timestamp() + secs
                    st = state.get(key)
                    if st is None:
                        state[key] = _BucketState(_new_bar(start, price, vol), end)
                        continue
                    if ts.timestamp() >= st.end_ts:
                        # close previous bar
                        _insert_bar(symbol, tf, st.bar)
                        r.publish(f"bars:{symbol}:{tf}", json.dumps({
                            "ts": st.bar.ts.isoformat(),
                            "o": st.bar.o, "h": st.bar.h,
                            "l": st.bar.l, "c": st.bar.c, "v": st.bar.v,
                        }))
                        state[key] = _BucketState(_new_bar(start, price, vol), end)
                    else:
                        b = st.bar
                        b.h = max(b.h, price); b.l = min(b.l, price)
                        b.c = price; b.v += vol


if __name__ == "__main__":
    run()
