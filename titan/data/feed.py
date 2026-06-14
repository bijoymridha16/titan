"""SmartAPI WebSocket V2 → Redis Streams tick consumer.

Uses the official smartapi-python SDK's `SmartWebSocketV2` class so we don't
hand-roll the binary frame decoder. Tested layout: mode 2 (quote) with index
+ equity subscriptions; pushes each tick as JSON onto `ticks:<symbol>`.

Run:
    python -m titan.data.feed
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
from datetime import datetime, timezone

import redis
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from titan.brokers.angelone import AngelOneBroker
from titan.config import angelone_settings, settings
from titan.data.instruments import resolve_universe

log = logging.getLogger(__name__)

# Angel One WS exchangeType codes
EXCH_CODE = {"NSE": 1, "NFO": 2, "BSE": 3, "MCX": 5, "NCDEX": 7, "CDS": 13}

CORRELATION_ID = "titan-feed-1"
MODE_LTP, MODE_QUOTE, MODE_SNAP = 1, 2, 3


class Feed:
    def __init__(self):
        self.r = redis.from_url(settings.redis_url, decode_responses=True)
        self.broker = AngelOneBroker()
        self.ws: SmartWebSocketV2 | None = None
        self.token_to_symbol: dict[str, str] = {}

    def _build_subscriptions(self) -> tuple[list[dict], dict[str, str]]:
        instruments = resolve_universe(settings.symbols)
        if not instruments:
            raise RuntimeError("no instruments resolved; run "
                               "`python -m titan.data.instruments` first")
        by_exch: dict[int, list[str]] = {}
        tok_map: dict[str, str] = {}
        for ins in instruments:
            code = EXCH_CODE.get(ins["exch_seg"])
            if not code:
                continue
            by_exch.setdefault(code, []).append(str(ins["token"]))
            tok_map[str(ins["token"])] = ins["symbol"]
        token_list = [{"exchangeType": k, "tokens": v} for k, v in by_exch.items()]
        return token_list, tok_map

    # ─────────────── WS callbacks (sync, called from SDK thread) ───────────────
    def on_open(self, wsapp):
        log.info("WS open; subscribing")
        token_list, self.token_to_symbol = self._build_subscriptions()
        self.r.set("titan:heartbeat:feed", datetime.utcnow().isoformat())
        self.ws.subscribe(CORRELATION_ID, MODE_QUOTE, token_list)

    def on_data(self, wsapp, message):
        # message is a dict (SDK decoded the binary frame)
        if not isinstance(message, dict):
            return
        token = str(message.get("token") or message.get("tk") or "")
        symbol = self.token_to_symbol.get(token, token)
        ltp = message.get("last_traded_price")
        if ltp is None:
            return
        # SDK gives prices in paise (×100); convert to rupees
        try: ltp = float(ltp) / 100.0
        except Exception: return
        tick = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "token": token,
            "ltp": ltp,
            "volume": int(message.get("volume_trade_for_the_day") or 0),
        }
        self.r.xadd(f"ticks:{symbol}", {"data": json.dumps(tick)},
                    maxlen=10_000, approximate=True)
        self.r.set(f"titan:ltp:{symbol}", ltp)
        self.r.set("titan:heartbeat:feed", datetime.utcnow().isoformat())

    def on_error(self, wsapp, error):
        log.error("WS error: %s", error)

    def on_close(self, wsapp):
        log.warning("WS closed")

    # ─────────────── lifecycle ───────────────
    async def run(self):
        await self.broker.connect()
        assert self.broker.feed_token, "no feed token after login"

        self.ws = SmartWebSocketV2(
            auth_token=self.broker._jwt,
            api_key=angelone_settings.api_key,
            client_code=angelone_settings.client_code,
            feed_token=self.broker.feed_token,
        )
        self.ws.on_open = self.on_open
        self.ws.on_data = self.on_data
        self.ws.on_error = self.on_error
        self.ws.on_close = self.on_close

        log.info("connecting to %s ...", "wss://smartapisocket.angelone.in/smart-stream")
        # SDK's connect() blocks; run in thread so we can keep asyncio.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.ws.connect)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    f = Feed()
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, loop.stop)
    try: loop.run_until_complete(f.run())
    finally: loop.close()


if __name__ == "__main__":
    main()
