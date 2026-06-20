"""Feed lifecycle manager — keeps the REAL Angel One feed running, but only
when it should be.

P4: "the simulator should work with the real market only, but paper trading."
This is the operational glue for that: it runs `titan.data.feed` (the real
SmartAPI WebSocket) as a child process during NSE market hours, restarts it with
backoff if it drops or goes stale, and stops it at the close. Outside market
hours (real mode) it does nothing — so nothing trades when the market is shut,
honestly. In explicit sim mode it stays out of the way (synth feed is the
offline-replay tool).

Publishes for the dashboard:
    titan:feed:status   RUNNING / STOPPED / STALE
    titan:feed:age_s    seconds since the last tick heartbeat

Run:
    python -m titan.data.feed_supervisor
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time as _time
from datetime import datetime

import redis

from titan import clock
from titan.config import settings

log = logging.getLogger(__name__)

HEARTBEAT_KEY = "titan:heartbeat:feed"
STATUS_KEY = "titan:feed:status"
AGE_KEY = "titan:feed:age_s"

POLL_S = 5
BACKOFF_START_S = 5
BACKOFF_MAX_S = 60


def feed_action(age: float | None, bridge_after: float, restart_after: float) -> str:
    """Pure decision: what to do given the heartbeat age (seconds since last tick).

    Returns one of: "ok" (fresh), "bridge" (soft-stale → REST LTP poll),
    "restart" (hard-stale → recycle the feed process). `age is None` means we
    have never seen a heartbeat yet, which is treated as "ok" (the feed may be
    starting up — the restart timer only runs against a real, stale heartbeat).
    """
    if age is None:
        return "ok"
    if age >= restart_after:
        return "restart"
    if age >= bridge_after:
        return "bridge"
    return "ok"


def heartbeat_age_s(r) -> float | None:
    """Seconds since the feed last wrote its heartbeat, or None if never."""
    hb = r.get(HEARTBEAT_KEY)
    if not hb:
        return None
    try:
        # feed writes naive UTC isoformat
        return (datetime.utcnow() - datetime.fromisoformat(hb)).total_seconds()
    except Exception:
        return None


def should_run(r, now: datetime | None = None) -> bool:
    """Run the real feed only during a real NSE session. In explicit sim mode the
    synthetic/offline tooling owns the feed, so we stand down."""
    if clock.sim_mode(r):
        return False
    return clock.is_market_open(now or clock.real_now())


class FeedSupervisor:
    def __init__(self):
        self.r = redis.from_url(settings.redis_url, decode_responses=True)
        self.proc: subprocess.Popen | None = None
        self.backoff = BACKOFF_START_S
        self._bridge = None   # lazily created LtpBridge (REST fallback)

    def _bridge_ltp(self) -> int:
        """Bridge the data gap with REST LTP polling. Lazily constructs the
        bridge so a supervisor with the fallback disabled never logs in."""
        if not settings.feed_rest_fallback:
            return 0
        if self._bridge is None:
            from titan.data.rest_fallback import LtpBridge
            self._bridge = LtpBridge()
        try:
            return self._bridge.poll_once(self.r)
        except Exception as e:
            log.warning("REST bridge poll failed: %s", e)
            return 0

    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _start(self) -> None:
        if self._alive():
            return
        log.info("starting real feed (titan.data.feed) …")
        self.proc = subprocess.Popen([sys.executable, "-m", "titan.data.feed"])
        self.backoff = BACKOFF_START_S

    def _stop(self, why: str) -> None:
        if self._alive():
            log.info("stopping feed (%s)", why)
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def _publish(self, status: str, age: float | None) -> None:
        try:
            self.r.set(STATUS_KEY, status)
            self.r.set(AGE_KEY, "" if age is None else f"{age:.0f}")
        except Exception:
            pass

    def tick(self) -> None:
        if not should_run(self.r):
            self._stop("market closed / sim mode")
            self._publish("STOPPED", None)
            return

        if not self._alive():
            self._start()
            self._publish("RUNNING", None)
            return

        # running — check staleness with the two-stage policy
        age = heartbeat_age_s(self.r)
        action = feed_action(age, settings.feed_rest_bridge_after_s,
                             settings.feed_stale_after_s)
        if action == "restart":
            log.warning("feed stale (%.0fs since last tick) — restarting (backoff %ds)",
                        age, self.backoff)
            self._publish("STALE", age)
            self._stop("stale")
            _time.sleep(self.backoff)
            self.backoff = min(self.backoff * 2, BACKOFF_MAX_S)
            self._start()
        elif action == "bridge":
            # soft-stale: WS quiet but not dead — bridge with REST LTP so
            # downstream keeps receiving prices while the socket recovers.
            n = self._bridge_ltp()
            log.warning("feed soft-stale (%.0fs) — REST-bridged %d symbols", age, n)
            self._publish("BRIDGING", age)
        else:
            self._publish("RUNNING", age)

    def run(self) -> None:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        log.info("feed supervisor up — real feed runs only during NSE hours "
                 "(sim_mode=%s)", clock.sim_mode(self.r))
        try:
            while True:
                try:
                    self.tick()
                except Exception as e:
                    log.exception("feed supervisor tick failed: %s", e)
                _time.sleep(POLL_S)
        finally:
            self._stop("supervisor exit")


def main():
    FeedSupervisor().run()


if __name__ == "__main__":
    main()
