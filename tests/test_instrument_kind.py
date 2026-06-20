"""D1: underlying → tradable-instrument resolution."""
from __future__ import annotations

from titan.data import instrument_kind as ik


def test_etf_default_maps_indices():
    assert ik.tradable_symbol("NIFTY", "ETF") == "NIFTYBEES"
    assert ik.tradable_symbol("BANKNIFTY", "ETF") == "BANKBEES"
    assert ik.tradable_symbol("SENSEX", "ETF") == "SENSEXBEES"


def test_equity_passthrough():
    assert ik.tradable_symbol("RELIANCE", "EQUITY") == "RELIANCE"
    assert ik.tradable_symbol("RELIANCE", "ETF") == "RELIANCE"  # no etf entry → self


def test_option_returns_root():
    assert ik.tradable_symbol("NIFTY", "OPTION") == "NIFTY"


def test_index_is_not_directly_tradable():
    assert ik.is_directly_tradable("INDEX") is False
    assert ik.is_directly_tradable("ETF") is True
