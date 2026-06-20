"""Daily session reset + logout (manifesto Scenario B)."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from titan.brokers.angelone import AngelOneBroker, session_needs_refresh

NOW = datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc)
TODAY = date(2026, 6, 12)


def test_no_token_needs_refresh():
    assert session_needs_refresh(None, None, TODAY, None, NOW) is True


def test_fresh_token_same_day_ok():
    exp = NOW + timedelta(hours=10)
    assert session_needs_refresh("jwt", TODAY, TODAY, exp, NOW) is False


def test_expired_token_needs_refresh():
    exp = NOW - timedelta(seconds=1)
    assert session_needs_refresh("jwt", TODAY, TODAY, exp, NOW) is True


def test_stale_day_forces_relogin():
    # token minted yesterday → mandatory fresh handshake today
    exp = NOW + timedelta(hours=10)
    assert session_needs_refresh("jwt", date(2026, 6, 11), TODAY, exp, NOW) is True


class _FakeClient:
    def __init__(self): self.posts = []
    def post(self, path, headers=None, json=None, timeout=None):
        self.posts.append(path)
        class _R:  # noqa
            pass
        return _R()


def test_logout_clears_tokens():
    b = AngelOneBroker()
    b._jwt = "jwt"; b._refresh = "r"; b._feed_token = "f"
    b._token_day = TODAY
    b._client = _FakeClient()
    asyncio.run(b.logout())
    assert b._jwt is None and b._refresh is None and b._feed_token is None
    assert b._token_day is None
    assert any("logout" in p for p in b._client.posts)
