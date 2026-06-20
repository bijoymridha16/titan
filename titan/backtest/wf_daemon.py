"""Self-healing walk-forward daemon (manifesto §3).

Turns the episodic walk-forward into a continuous background process: on a
schedule (default Saturday 18:00 IST) it re-runs the full vetting on the latest
OHLCV and re-promotes the survivors to the validated allowlist. Strategies whose
live edge has decayed below the deflated-Sharpe hurdle fall out of the SHIP set
and are demoted automatically; fresh survivors are promoted in their place — so
the auto-pilot always arms the currently-best, multiple-testing-corrected set.

Run:
    python -m titan.backtest.wf_daemon            # loop on schedule
    python -m titan.backtest.wf_daemon --once     # run a single pass now
"""
from __future__ import annotations

import argparse
import logging
import time as _time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from titan.backtest.walk_forward import promote, vet_all
from titan.config import settings

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def seconds_until_next_run(now: datetime, weekday: int, hour: int) -> float:
    """Seconds from `now` until the next occurrence of weekday@hour:00 (strictly
    in the future). weekday: Mon=0 … Sun=6."""
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    days_ahead = (weekday - now.weekday()) % 7
    if days_ahead == 0 and target <= now:
        days_ahead = 7
    target = target + timedelta(days=days_ahead)
    return (target - now).total_seconds()


def run_once() -> int:
    """Run one vetting pass and re-promote survivors. Returns survivor count."""
    max_bars = settings.wf_daemon_max_bars or None
    scores = vet_all(settings.symbols, settings.wf_daemon_tf, max_bars=max_bars)
    survivors = [s for s in scores if s.passed]
    promoted = promote(survivors)   # empty → clears the allowlist (nothing earns a slot)
    log.info("walk-forward pass complete: %d/%d SHIP, promoted=%s",
             len(survivors), len(scores), sorted(promoted) or "—")
    return len(survivors)


class WalkForwardDaemon:
    def run(self) -> None:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        log.info("walk-forward daemon up — schedule: weekday=%d hour=%d IST",
                 settings.wf_daemon_weekday, settings.wf_daemon_hour)
        while True:
            delay = seconds_until_next_run(datetime.now(IST),
                                           settings.wf_daemon_weekday,
                                           settings.wf_daemon_hour)
            log.info("next walk-forward run in %.1f h", delay / 3600)
            _time.sleep(delay)
            try:
                run_once()
            except Exception as e:
                log.exception("walk-forward pass failed: %s", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run a single pass and exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.once:
        run_once()
    else:
        WalkForwardDaemon().run()


if __name__ == "__main__":
    main()
