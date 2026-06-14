"""Historical OHLCV backfill from Angel SmartAPI getCandleData.

Why we need this:
  - All strategies need history. Live feed only fills bars going forward.
  - Backtests need 2+ years of daily / 5m data.
  - Angel's free API gives historical candles for any subscribed instrument.

API surface (per SmartAPI docs):
  POST /rest/secure/angelbroking/historical/v1/getCandleData
  body: {exchange, symboltoken, interval, fromdate, todate}
  interval: ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR, ONE_DAY
  date fmt: "YYYY-MM-DD HH:MM"
  response.data: [[ts_iso, o, h, l, c, v], ...]

Rate limits (Angel):
  - 3 req/sec, 180 req/min for historical endpoint
  - Per-request max range: 30 days for 5m, 2000 days for 1d
  - We page in (max_range - 1 day) windows and sleep between requests.

Usage:
  python -m titan.data.backfill --symbols RELIANCE,HDFCBANK,ICICIBANK \
                                --interval ONE_DAY --years 2

Idempotent — uses INSERT ... ON CONFLICT DO NOTHING. Re-runnable.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy import text

from titan.brokers.angelone import AngelOneBroker, REST_BASE
from titan.config import settings
from titan.data.instruments import resolve_universe
from titan.data.store import engine

log = logging.getLogger(__name__)

CANDLE_PATH = "/rest/secure/angelbroking/historical/v1/getCandleData"

# Per-request max window per Angel docs. Conservative: stay under the limit.
WINDOW_DAYS = {
    "ONE_MINUTE":      25,
    "FIVE_MINUTE":     25,
    "FIFTEEN_MINUTE":  50,
    "THIRTY_MINUTE":   90,
    "ONE_HOUR":       180,
    "ONE_DAY":       1800,
}

# Map Angel interval string → our compact tf code used in ohlcv.timeframe
TF_CODE = {
    "ONE_MINUTE":     "1m",
    "FIVE_MINUTE":    "5m",
    "FIFTEEN_MINUTE": "15m",
    "THIRTY_MINUTE":  "30m",
    "ONE_HOUR":       "1h",
    "ONE_DAY":        "1d",
}

REQ_SLEEP_S = 0.4   # ~2.5 req/s, well under the 3/s limit


def nifty50_symbols() -> list[str]:
    """Read NIFTY-50 tickers from the alias YAML — single source of truth."""
    import yaml
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "config" / "nifty50_aliases.yaml"
    with p.open() as f:
        return sorted((yaml.safe_load(f) or {}).keys())


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


class HistoricalClient:
    def __init__(self, broker: AngelOneBroker):
        self.broker = broker
        self._http = httpx.Client(base_url=REST_BASE, timeout=15.0)

    def fetch(self, exch_seg: str, symboltoken: str, interval: str,
              start: datetime, end: datetime) -> list[list]:
        self.broker._ensure_token()
        payload = {
            "exchange": exch_seg,
            "symboltoken": str(symboltoken),
            "interval": interval,
            "fromdate": _fmt(start),
            "todate": _fmt(end),
        }
        headers = self.broker._auth_headers()
        r = self._http.post(CANDLE_PATH, headers=headers, json=payload)
        try:
            data = self.broker._unwrap(r, "getCandleData") or []
        except Exception as e:
            log.warning("candle fetch %s %s..%s failed: %s",
                        interval, _fmt(start), _fmt(end), e)
            return []
        return data if isinstance(data, list) else []


def _persist(symbol: str, tf: str, rows: list[list]) -> int:
    if not rows:
        return 0
    with engine().begin() as cx:
        for row in rows:
            ts_str, o, h, l, c, v = row
            cx.execute(text("""
                INSERT INTO ohlcv (ts, symbol, timeframe, o, h, l, c, v)
                VALUES (:ts, :s, :tf, :o, :h, :l, :c, :v)
                ON CONFLICT (symbol, timeframe, ts) DO NOTHING
            """), {"ts": ts_str, "s": symbol, "tf": tf,
                   "o": o, "h": h, "l": l, "c": c, "v": int(v or 0)})
    return len(rows)


def backfill_symbol(broker: AngelOneBroker, symbol: str,
                    interval: str, start: datetime, end: datetime) -> int:
    hits = resolve_universe([symbol])
    if not hits:
        log.warning("skip %s — instrument not found", symbol)
        return 0
    inst = hits[0]
    client = HistoricalClient(broker)
    window = timedelta(days=WINDOW_DAYS[interval])
    tf = TF_CODE[interval]
    total = 0
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + window, end)
        rows = client.fetch(inst["exch_seg"], inst["token"],
                            interval, cursor, chunk_end)
        n = _persist(symbol, tf, rows)
        total += n
        log.info("  %s %s %s..%s → %d rows",
                 symbol, tf, cursor.date(), chunk_end.date(), n)
        cursor = chunk_end + timedelta(minutes=1)
        time.sleep(REQ_SLEEP_S)
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(settings.symbols),
                        help="comma-separated trading symbols (or 'nifty50')")
    parser.add_argument("--interval", default="ONE_DAY",
                        choices=list(WINDOW_DAYS.keys()))
    parser.add_argument("--years", type=float, default=2.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    end = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)
    start = end - timedelta(days=int(args.years * 365))

    import asyncio
    broker = AngelOneBroker()
    asyncio.run(broker.connect())

    if args.symbols.strip().lower() == "nifty50":
        symbols = nifty50_symbols()
    else:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    grand_total = 0
    for sym in symbols:
        log.info("── %s ──", sym)
        grand_total += backfill_symbol(broker, sym, args.interval, start, end)
    log.info("done. inserted %d rows total.", grand_total)


if __name__ == "__main__":
    main()
