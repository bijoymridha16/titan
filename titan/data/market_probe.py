"""Runtime probe: did NSE actually trade today?

The clock module's `is_trading_day()` reads a static YAML (config/nse_holidays.yaml)
that is incomplete by design — movable festival dates and unforeseen halts
(circuit-breakers, regulatory closures) are not in it. The static gate is
therefore too permissive, and the system can spend an entire session wondering
why "the feed is broken" when in fact the exchange is shut.

This probe asks the broker for actual minute candles on a benchmark symbol after
the session has had time to print. Zero candles past 09:25 IST means no one
traded — treat the day as CLOSED regardless of the calendar.

The result is cached in Redis until end-of-day so we only hit the REST endpoint
once per session per process.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from titan.brokers.angelone import AngelOneBroker
from titan.config import angelone_settings

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
PROBE_AFTER = time(9, 25)
# RELIANCE NSE token; one of the most liquid symbols, always prints in the first
# minute of any open session. Hardcoded to keep the probe self-contained.
PROBE_TOKEN = "2885"
REST_URL = ("https://apiconnect.angelone.in/rest/secure/angelbroking/"
            "historical/v1/getCandleData")


def cache_key(d) -> str:
    return f"titan:market:traded:{d.isoformat()}"


async def _fetch_candles(jwt: str) -> int:
    now = datetime.now(IST)
    headers = {
        "Authorization": f"Bearer {jwt}",
        "X-PrivateKey": angelone_settings.api_key,
        "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "X-UserType": "USER", "X-SourceID": "WEB",
        "Accept": "application/json", "Content-Type": "application/json",
    }
    body = {
        "exchange": "NSE", "symboltoken": PROBE_TOKEN, "interval": "ONE_MINUTE",
        "fromdate": now.replace(hour=9, minute=15, second=0).strftime("%Y-%m-%d %H:%M"),
        "todate": now.strftime("%Y-%m-%d %H:%M"),
    }
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(REST_URL, headers=headers, json=body)
        d = r.json()
    if d.get("errorcode"):
        raise RuntimeError(f"angel probe errorcode={d.get('errorcode')} msg={d.get('message')}")
    return len(d.get("data") or [])


async def probe_traded_today(r) -> bool | None:
    """Return True (market trading), False (closed/holiday), or None (too early
    to tell). Caches the verdict in Redis until end-of-day."""
    now = datetime.now(IST)
    key = cache_key(now.date())
    if r is not None:
        cached = r.get(key)
        if cached in ("1", "0"):
            return cached == "1"
    if now.time() < PROBE_AFTER:
        return None  # too early; ask again later

    try:
        broker = AngelOneBroker()
        await broker.connect()
        n = await _fetch_candles(broker._jwt)
    except Exception as e:
        log.warning("market probe failed: %s", e)
        return None

    open_today = n > 0
    if r is not None:
        # cache until midnight IST
        ttl = max(60, int(((now + timedelta(days=1)).replace(
            hour=0, minute=0, second=5) - now).total_seconds()))
        r.set(key, "1" if open_today else "0", ex=ttl)
    log.info("market probe: candles=%d → traded_today=%s", n, open_today)
    return open_today
