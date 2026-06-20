"""Synthetic tick generator — for when the market is closed but you want to
see the full pipeline (ticks → bars → strategy → paper fills → dashboard) run
end-to-end.

Writes:
  - Redis Streams `ticks:<symbol>` (consumed by bar_writer.py)
  - Redis key `titan:ltp:<symbol>` (for ticker tape)
  - Redis key `titan:heartbeat:feed` (turns the green feed dot on)
  - Redis key `titan:mode:synthetic=1` (dashboard shows 🧪 SYNTH pill)

Behavior:
  - Generates 1 tick every 0.2s per symbol — fast enough to fill 5m bars within
    a minute of wall-clock so strategies start producing signals immediately.
  - Time-axis is FAKE: each tick advances simulated time by 30s. So 2 ticks =
    1 simulated minute, and a 5m bar (10 ticks) closes in ~2 real seconds.
  - Random walk anchored at realistic NSE prices; small chance of a "shock" leg
    each minute so ORB / Supertrend get something to bite on.

Stop with Ctrl-C; the synth pill auto-clears.
"""
from __future__ import annotations

import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import redis

from titan.config import settings

log = logging.getLogger(__name__)

ANCHORS = {
    "NIFTY": 24_500.0, "BANKNIFTY": 52_000.0, "FINNIFTY": 24_000.0,
    "RELIANCE": 2_950.0, "HDFCBANK": 1_680.0, "ICICIBANK": 1_280.0,
}
PER_TICK_VOL = 0.00035  # ~3.5 bps per tick
SHOCK_PROB = 0.012      # ~1% of ticks get a 20-50 bp jump (one direction)


class SynthFeed:
    def __init__(self, tick_interval_s: float = 0.2,
                 sim_seconds_per_tick: int = 30):
        self.r = redis.from_url(settings.redis_url, decode_responses=True)
        self.symbols = [s for s in settings.symbols if s in ANCHORS]
        self.prices = {s: ANCHORS[s] for s in self.symbols}
        self.tick_interval_s = tick_interval_s
        self.sim_step = timedelta(seconds=sim_seconds_per_tick)
        self.rng = np.random.default_rng()
        self._stop = False
        self.sim_now = datetime.now(timezone.utc).replace(
            hour=3, minute=45, second=0, microsecond=0)  # 09:15 IST

    def _advance(self) -> None:
        for s in self.symbols:
            p = self.prices[s]
            ret = self.rng.normal(0, PER_TICK_VOL)
            if self.rng.random() < SHOCK_PROB:
                ret += self.rng.choice([-1, 1]) * self.rng.uniform(0.002, 0.005)
            p = p * (1 + ret)
            self.prices[s] = p
            tick = {
                "ts": self.sim_now.isoformat(),
                "symbol": s,
                "token": "SYNTH",
                "ltp": float(round(p, 2)),
                "volume": int(self.rng.integers(40, 200)),
            }
            self.r.xadd(f"ticks:{s}", {"data": json.dumps(tick)},
                        maxlen=20_000, approximate=True)
            self.r.set(f"titan:ltp:{s}", float(round(p, 2)))
        self.r.set("titan:heartbeat:feed", datetime.now(timezone.utc).isoformat())
        self.sim_now += self.sim_step
        # Wrap 15:30 IST (10:00 UTC) → next day's 09:15 IST (03:45 UTC) so
        # ORB / session-bound strategies keep firing on overnight demos.
        if self.sim_now.hour >= 10:
            self.sim_now = (self.sim_now + timedelta(days=1)).replace(
                hour=3, minute=45, second=0, microsecond=0)

    def run(self):
        self.r.set("titan:mode:synthetic", "1")
        log.info("synth feed running; sim_step=%s symbols=%s",
                 self.sim_step, self.symbols)
        signal.signal(signal.SIGINT,  self._sig)
        signal.signal(signal.SIGTERM, self._sig)
        try:
            while not self._stop:
                self._advance()
                time.sleep(self.tick_interval_s)
        finally:
            self.r.delete("titan:mode:synthetic")
            log.info("synth feed stopped, synth flag cleared")

    def _sig(self, *_):
        self._stop = True


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    SynthFeed().run()


if __name__ == "__main__":
    main()
