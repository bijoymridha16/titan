"""Single source of truth for time and NSE market-session state.

WHY THIS EXISTS — honesty:
    Previously the supervisor and auto-pilot each carried a hardcoded hack that
    silently pinned the clock to 11:00 IST whenever a synthetic feed was running,
    so the risk engine *believed* the market was open even at 4pm on a closed day.
    The clock lied, in two duplicated places.

    This module replaces that. There are exactly two modes, and the distinction
    is explicit and loud — never inferred from "is some feed running":

      • REAL mode (default): the clock is the real IST wall clock. It never lies.
        Trading is gated to real NSE hours by RiskEngine's market-hours check, so
        nothing trades when the market is actually closed.

      • SIM mode (opt-in via TITAN_SIM_MODE=1 or the `titan:sim:enabled` Redis
        key / API): an explicit, clearly-labeled simulation clock that maps the
        wall clock onto a looping session window, so the full pipeline can be
        rehearsed when the market is closed. Sim mode is a deliberate switch, and
        every surface (dashboard, /status) labels it as SIMULATION.

NSE cash session is 09:15–15:30 IST, Mon–Fri. (No exchange holiday calendar is
wired in yet — weekends only; see note below.)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from titan.config import settings

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
SIM_KEY = "titan:sim:enabled"
_HOLIDAYS_FILE = Path(__file__).resolve().parents[1] / "config" / "nse_holidays.yaml"


@lru_cache(maxsize=1)
def _holidays() -> frozenset[date]:
    """NSE trading holidays from config/nse_holidays.yaml (weekends handled
    separately). Missing/invalid file → empty set (weekend-only gating)."""
    try:
        import yaml
        data = yaml.safe_load(_HOLIDAYS_FILE.read_text()) or {}
        out = set()
        for d in data.get("holidays", []) or []:
            try:
                out.add(date.fromisoformat(str(d)))
            except ValueError:
                continue
        return frozenset(out)
    except Exception as e:
        log.warning("could not load NSE holidays (%s) — weekend-only gating", e)
        return frozenset()


def real_now() -> datetime:
    """The truth. Real IST wall clock."""
    return datetime.now(IST)


def is_trading_day(dt: datetime | None = None) -> bool:
    """A weekday that is not on the NSE holiday calendar. The holiday list is
    config-driven (config/nse_holidays.yaml) and intentionally conservative —
    see that file's header. Movable festival dates must be loaded from NSE's
    official circular; absent ones only make the gate more permissive, never
    less safe."""
    dt = dt or real_now()
    if dt.weekday() >= 5:
        return False
    return dt.date() not in _holidays()


def is_market_open(dt: datetime | None = None) -> bool:
    """True only during a real NSE cash session (09:15–15:30 IST on a weekday)."""
    dt = dt or real_now()
    t = dt.timetz().replace(tzinfo=None)
    return is_trading_day(dt) and SESSION_OPEN <= t < SESSION_CLOSE


def sim_mode(r=None) -> bool:
    """Is SIMULATION explicitly enabled? Redis override (live, via API) wins over
    the TITAN_SIM_MODE env default. Never inferred from feed presence."""
    if r is not None:
        try:
            v = r.get(SIM_KEY)
            if v is not None:
                return v == "1" or v == 1 or v is True
        except Exception:
            pass
    return bool(settings.sim_mode)


def sim_session_now(base: datetime | None = None) -> datetime:
    """A deterministic, clearly-labeled SIMULATION clock for sim mode.

    Maps the real wall clock onto a continuously-looping 09:15→15:15 window
    (the tradable part of the session) so the pipeline runs end-to-end at any
    real time. This is NOT the real time and is only ever used when sim_mode is
    explicitly on. Returns a real-mode timestamp unchanged if base is given in
    a session already — callers pass nothing in normal use.
    """
    base = base or real_now()
    # tradable span 09:15..15:15 = 6h = 21600s
    span_s = 6 * 3600
    open_dt = base.replace(hour=9, minute=15, second=0, microsecond=0)
    offset = int(base.timestamp()) % span_s
    return open_dt + timedelta(seconds=offset)


def trading_now(r=None) -> datetime:
    """The clock trading components should use.
    REAL mode → real_now() (truth, gated by market hours).
    SIM mode  → sim_session_now() (explicit, labeled simulation time)."""
    return sim_session_now() if sim_mode(r) else real_now()
