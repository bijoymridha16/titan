"""Feed-supervisor decision logic — runs the real feed only during a real NSE
session, and only when not in explicit sim mode."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from titan.data import feed_supervisor as fs

IST = ZoneInfo("Asia/Kolkata")


class _FakeRedis:
    def __init__(self, kv=None): self.kv = dict(kv or {})
    def get(self, k): return self.kv.get(k)
    def set(self, k, v): self.kv[k] = v


def dt(y, mo, d, h, m):
    return datetime(y, mo, d, h, m, tzinfo=IST)


def test_should_run_true_during_session_real_mode():
    r = _FakeRedis()  # no sim flag → real mode
    assert fs.should_run(r, dt(2026, 6, 12, 11, 0)) is True   # Fri mid-session


def test_should_not_run_outside_session():
    r = _FakeRedis()
    assert fs.should_run(r, dt(2026, 6, 12, 16, 0)) is False  # after close
    assert fs.should_run(r, dt(2026, 6, 13, 11, 0)) is False  # Saturday


def test_should_not_run_on_holiday():
    r = _FakeRedis()
    assert fs.should_run(r, dt(2026, 1, 26, 11, 0)) is False  # Republic Day


def test_sim_mode_stands_down():
    # explicit simulation → real feed supervisor stays out of the way
    r = _FakeRedis({"titan:sim:enabled": "1"})
    assert fs.should_run(r, dt(2026, 6, 12, 11, 0)) is False


def test_heartbeat_age_none_when_missing():
    assert fs.heartbeat_age_s(_FakeRedis()) is None


def test_heartbeat_age_computed():
    old = (datetime.utcnow() - timedelta(seconds=42)).isoformat()
    age = fs.heartbeat_age_s(_FakeRedis({"titan:heartbeat:feed": old}))
    assert age is not None and 40 < age < 60


# ── two-stage staleness policy (manifesto Scenario A) ──

def test_feed_action_fresh_is_ok():
    assert fs.feed_action(2.0, bridge_after=5, restart_after=30) == "ok"


def test_feed_action_none_age_is_ok():
    # never-seen heartbeat (feed still warming up) must not trigger a restart
    assert fs.feed_action(None, bridge_after=5, restart_after=30) == "ok"


def test_feed_action_soft_stale_bridges():
    assert fs.feed_action(5.0, bridge_after=5, restart_after=30) == "bridge"
    assert fs.feed_action(29.9, bridge_after=5, restart_after=30) == "bridge"


def test_feed_action_hard_stale_restarts():
    assert fs.feed_action(30.0, bridge_after=5, restart_after=30) == "restart"
    assert fs.feed_action(120.0, bridge_after=5, restart_after=30) == "restart"
