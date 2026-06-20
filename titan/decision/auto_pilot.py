"""Auto-pilot — the long-lived decision loop that makes TITAN self-driving.

    every autopilot_interval_s seconds:
        now    = IST clock (synth-aware, like the supervisor)
        bars   = last N 5m bars of the reference symbol (NIFTY) from Postgres
        vix    = optional India VIX from Redis key titan:vix (only if a feed sets it)
        read   = RegimeClassifier.classify(bars, now, vix)
        Selector.decide(read, apply = master-armed?)  → arms/disarms validated strategies

Run:
    python -m titan.decision.auto_pilot

ARM/DISARM:
    Master flag resolves in this order (first wins):
      1. Redis key  titan:autopilot:enabled   ("1"/"0")  — live, set via API
      2. settings.autopilot_enabled (.env default)
    When DISARMED, the loop still classifies + logs every decision (observe-only),
    so you can watch exactly what it *would* do before handing it the keys. This is
    the dress rehearsal for automation, mirroring the broker's dry-run philosophy.

SAFETY:
    • Never enables a strategy outside settings.autopilot_validated_set (H1).
    • Honors the global kill switch (titan:kill): when killed, it disarms its
      whole controlled lane so no new strategy can fire.
    • A classify/DB error is logged and skipped — it never crashes the loop and
      never silently leaves stale strategies armed (on error it makes no change).
"""
from __future__ import annotations

import logging
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import redis as _redis
from sqlalchemy import text

from titan.config import settings
from titan.data.store import engine
from titan.decision.regime import RegimeClassifier, Regime
from titan.decision.selector import ENABLED_KEY, Selector

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

KILL_KEY = "titan:kill"
AUTOPILOT_KEY = "titan:autopilot:enabled"
VIX_KEY = "titan:vix"
SYNTH_KEY = "titan:mode:synthetic"


class AutoPilot:
    def __init__(self):
        self.r = _redis.from_url(settings.redis_url, decode_responses=True)
        self.classifier = RegimeClassifier(settings.autopilot_ref_symbol)
        self.selector = Selector(self.r, db_engine=engine())
        self.ref = settings.autopilot_ref_symbol
        self.lookback = settings.regime_lookback_bars

    # ──────────────── inputs ────────────────
    def _now_ist(self) -> datetime:
        """Honest clock via the central clock module: real IST in real mode, an
        explicit labeled simulation clock only when sim_mode is opted into. No
        silent override — when the market is really closed and sim is off, the
        regime classifier will read CLOSED and arm nothing."""
        from titan import clock
        return clock.trading_now(self.r)

    def _load_ref_bars(self) -> pd.DataFrame:
        with engine().connect() as cx:
            df = pd.read_sql(text("""
                SELECT ts, o, h, l, c, v FROM ohlcv
                WHERE symbol=:s AND timeframe='5m'
                ORDER BY ts DESC LIMIT :n
            """), cx, params={"s": self.ref, "n": self.lookback},
                parse_dates=["ts"], index_col="ts")
        return df.sort_index()

    def _india_vix(self) -> float | None:
        v = self.r.get(VIX_KEY)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _armed(self) -> bool:
        flag = self.r.get(AUTOPILOT_KEY)
        if flag is not None:
            return flag == "1"
        return settings.autopilot_enabled

    # ──────────────── one decision cycle ────────────────
    def tick(self) -> None:
        now = self._now_ist()
        armed = self._armed()

        # Kill switch dominates everything: disarm the controlled lane, stop.
        if self.r.get(KILL_KEY) == "1":
            controlled = settings.autopilot_validated_set
            cur = set(self.r.smembers(ENABLED_KEY) or set())
            doomed = controlled & cur
            if doomed and armed:
                self.r.srem(ENABLED_KEY, *doomed)
                log.warning("kill switch active — auto-pilot disarmed %s", sorted(doomed))
            self.r.set("titan:regime:current", "KILLED")
            self.r.set("titan:regime:reason", "kill switch active — no new strategies")
            return

        bars = self._load_ref_bars()
        vix = self._india_vix()
        reading = self.classifier.classify(bars, now, india_vix=vix)
        self.selector.decide(reading, apply=armed)

    def run(self) -> None:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        log.info("auto-pilot starting: ref=%s interval=%ds validated=%s default_armed=%s",
                 self.ref, settings.autopilot_interval_s,
                 sorted(settings.autopilot_validated_set), settings.autopilot_enabled)
        while True:
            try:
                self.tick()
            except Exception as e:
                # Never crash the loop and never leave a half-applied change:
                # decide() applies atomically per call, so skipping a tick is safe.
                log.exception("auto-pilot tick failed (no change applied): %s", e)
            _time.sleep(settings.autopilot_interval_s)


def main():
    AutoPilot().run()


if __name__ == "__main__":
    main()
