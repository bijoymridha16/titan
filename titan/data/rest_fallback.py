"""REST LTP bridge — keeps prices flowing when the WebSocket feed stalls.

Manifesto Scenario A ("Brokerage Infrastructure Asphyxiation"): the Angel One
WS drops or goes silent during volatile opens. Rather than sit blind until a
full feed restart, the supervisor calls this bridge to poll the REST LTP
endpoint for each universe symbol and write the SAME Redis keys the live feed
writes (`ticks:<symbol>`, `titan:ltp:<symbol>`, `titan:heartbeat:feed`). That
keeps the bar writer + dashboard alive and refreshes the heartbeat so the
hard-restart timer only fires on a genuinely dead socket.

This is a degraded mode: REST LTP has no real volume and is rate-limited, so it
is a stopgap during reconnection, never the primary path. All writes are
best-effort — a failing poll must never crash the supervisor loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from titan.brokers.angelone import AngelOneBroker
from titan.config import settings
from titan.data.instruments import resolve_universe

log = logging.getLogger(__name__)

HEARTBEAT_KEY = "titan:heartbeat:feed"


class LtpBridge:
    """Lazily logs into Angel and polls REST LTP for the configured universe."""

    def __init__(self):
        self.broker: AngelOneBroker | None = None
        self._instruments: list[dict] | None = None

    def _ensure(self) -> None:
        if self._instruments is None:
            self._instruments = resolve_universe(settings.symbols)
        if self.broker is None:
            self.broker = AngelOneBroker()
            # connect() does the sync login under the hood
            asyncio.run(self.broker.connect())

    def poll_once(self, r) -> int:
        """Poll REST LTP for every universe symbol and write tick/ltp/heartbeat.

        Returns the number of symbols successfully bridged. Best-effort: any
        per-symbol failure is logged and skipped, never raised.
        """
        try:
            self._ensure()
        except Exception as e:
            log.warning("ltp bridge: login/resolve failed, cannot bridge: %s", e)
            return 0

        bridged = 0
        for ins in self._instruments or []:
            symbol = ins.get("name") or ins["symbol"]
            try:
                ltp = asyncio.run(self.broker.get_ltp(
                    ins["symbol"], ins["exch_seg"], str(ins["token"])))
            except Exception as e:
                log.warning("ltp bridge: %s failed: %s", symbol, e)
                continue
            tick = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "token": str(ins["token"]),
                "ltp": ltp,
                "volume": 0,            # REST LTP carries no trade volume
                "source": "rest_bridge",
            }
            try:
                r.xadd(f"ticks:{symbol}", {"data": json.dumps(tick)},
                       maxlen=10_000, approximate=True)
                r.set(f"titan:ltp:{symbol}", ltp)
                bridged += 1
            except Exception as e:
                log.warning("ltp bridge: redis write for %s failed: %s", symbol, e)
        if bridged:
            try:
                r.set(HEARTBEAT_KEY, datetime.now(timezone.utc).isoformat())
            except Exception:
                pass
            log.info("ltp bridge: refreshed %d/%d symbols via REST",
                     bridged, len(self._instruments or []))
        return bridged
