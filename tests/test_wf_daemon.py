"""Walk-forward daemon scheduler (manifesto §3)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from titan.backtest.wf_daemon import seconds_until_next_run

IST = ZoneInfo("Asia/Kolkata")
HOUR = 3600
DAY = 86400


def dt(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


def test_same_day_before_hour():
    # Saturday 2026-06-13 10:00, target Sat 18:00 → 8h away
    now = dt(2026, 6, 13, 10)        # 2026-06-13 is a Saturday (weekday 5)
    assert now.weekday() == 5
    assert seconds_until_next_run(now, weekday=5, hour=18) == 8 * HOUR


def test_same_day_after_hour_rolls_a_week():
    now = dt(2026, 6, 13, 19)        # past 18:00 on the target weekday
    assert seconds_until_next_run(now, weekday=5, hour=18) == 7 * DAY - HOUR


def test_target_later_in_week():
    # Wednesday 2026-06-10 12:00 → next Saturday 18:00
    now = dt(2026, 6, 10, 12)
    assert now.weekday() == 2
    secs = seconds_until_next_run(now, weekday=5, hour=18)
    # 3 days ahead to Sat, plus 6h from 12:00 → 18:00
    assert secs == 3 * DAY + 6 * HOUR


def test_target_earlier_in_week_rolls_forward():
    # Sunday 2026-06-14 → next Saturday is 6 days away
    now = dt(2026, 6, 14, 9)
    assert now.weekday() == 6
    secs = seconds_until_next_run(now, weekday=5, hour=18)
    assert secs == 6 * DAY + 9 * HOUR
