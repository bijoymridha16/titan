"""Regression test for the 2026-06-15 ORB silence incident.

The feed used `ins["symbol"]` (NSE tradingsymbol like "Nifty 50",
"RELIANCE-EQ") as the Redis stream key. Every downstream consumer
(bar_writer, supervisor, dashboard) reads `ticks:<short_name>` where
short_name = "NIFTY", "RELIANCE". Real ticks landed in orphan streams,
strategies ran on stale data, no signals fired.
"""
from decimal import Decimal
from unittest.mock import patch

from titan.data.feed import Feed


_FAKE_INSTRUMENTS = [
    {"exch_seg": "NSE", "token": "99926000", "symbol": "Nifty 50",
     "name": "NIFTY", "instrumenttype": "AMXIDX", "expiry": None,
     "strike": Decimal("0"), "lotsize": 1, "tick_size": Decimal("0.05")},
    {"exch_seg": "NSE", "token": "2885", "symbol": "RELIANCE-EQ",
     "name": "RELIANCE", "instrumenttype": None, "expiry": None,
     "strike": Decimal("-1"), "lotsize": 1, "tick_size": Decimal("10")},
]


@patch("titan.data.feed.resolve_universe", return_value=_FAKE_INSTRUMENTS)
@patch("titan.data.feed.settings")
@patch("titan.data.feed.redis")
def test_tok_map_uses_short_name_not_tradingsymbol(_redis, _settings, _resolve):
    _settings.symbols = ["NIFTY", "RELIANCE"]
    _settings.redis_url = "redis://localhost:6379/0"
    f = Feed()
    _token_list, tok_map = f._build_subscriptions()
    assert tok_map == {"99926000": "NIFTY", "2885": "RELIANCE"}, (
        "feed must publish ticks under the short name (NIFTY, RELIANCE) — "
        "not the tradingsymbol (Nifty 50, RELIANCE-EQ) — or every downstream "
        "consumer reads stale data")


@patch("titan.data.feed.resolve_universe", return_value=_FAKE_INSTRUMENTS[:1])
@patch("titan.data.feed.settings")
@patch("titan.data.feed.redis")
def test_missing_symbol_aborts_startup(_redis, _settings, _resolve):
    _settings.symbols = ["NIFTY", "RELIANCE"]
    _settings.redis_url = "redis://localhost:6379/0"
    f = Feed()
    import pytest
    with pytest.raises(RuntimeError, match="not resolved in instrument master"):
        f._build_subscriptions()
