"""Clock honesty: market-hours detection + explicit sim mode."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from titan import clock

IST = ZoneInfo("Asia/Kolkata")


def dt(y, mo, d, h, m):
    return datetime(y, mo, d, h, m, tzinfo=IST)


def test_market_open_during_session_weekday():
    # 2026-06-12 is a Friday
    assert clock.is_market_open(dt(2026, 6, 12, 10, 30)) is True
    assert clock.is_market_open(dt(2026, 6, 12, 9, 15)) is True   # open edge inclusive
    assert clock.is_market_open(dt(2026, 6, 12, 15, 29)) is True


def test_market_closed_outside_session():
    assert clock.is_market_open(dt(2026, 6, 12, 9, 0)) is False    # pre-open
    assert clock.is_market_open(dt(2026, 6, 12, 15, 30)) is False  # close edge exclusive
    assert clock.is_market_open(dt(2026, 6, 12, 18, 0)) is False   # evening


def test_market_closed_on_weekend():
    # 2026-06-13 Sat, 2026-06-14 Sun
    assert clock.is_market_open(dt(2026, 6, 13, 11, 0)) is False
    assert clock.is_market_open(dt(2026, 6, 14, 11, 0)) is False


def test_market_closed_on_nse_holiday():
    # 2026-01-26 (Republic Day, a Monday) is in config/nse_holidays.yaml
    assert clock.is_trading_day(dt(2026, 1, 26, 11, 0)) is False
    assert clock.is_market_open(dt(2026, 1, 26, 11, 0)) is False
    # a normal weekday is still a trading day
    assert clock.is_trading_day(dt(2026, 6, 12, 11, 0)) is True


def test_sim_session_now_is_always_in_tradable_window():
    # whatever the real time, the sim clock maps into 09:15..15:15
    for h in (0, 3, 9, 16, 23):
        s = clock.sim_session_now(dt(2026, 6, 13, h, 7))  # even on a Saturday
        t = s.timetz().replace(tzinfo=None)
        assert clock.SESSION_OPEN <= t < datetime(2026, 1, 1, 15, 15).time()


def test_sim_mode_default_from_settings(monkeypatch):
    monkeypatch.setattr(clock.settings, "sim_mode", False)
    assert clock.sim_mode(None) is False
    monkeypatch.setattr(clock.settings, "sim_mode", True)
    assert clock.sim_mode(None) is True


class _FakeRedis:
    def __init__(self, val): self._v = val
    def get(self, _k): return self._v


def test_sim_mode_redis_override_wins(monkeypatch):
    monkeypatch.setattr(clock.settings, "sim_mode", False)
    assert clock.sim_mode(_FakeRedis("1")) is True   # redis overrides config default
    assert clock.sim_mode(_FakeRedis("0")) is False
    assert clock.sim_mode(_FakeRedis(None)) is False  # falls back to config
