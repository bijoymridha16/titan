"""TSMOM unit tests — verify the *implementation* is correct.
The strategy was killed by walk-forward on our universe, but the code must
still be correct so future tests on other universes are valid.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from titan.strategies.base import SignalKind
from titan.strategies.tsmom import TSMOM


def _bars(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({
        "o": prices, "h": prices, "l": prices, "c": prices,
        "v": [1000] * len(prices),
    }, index=idx)


def test_emits_long_when_trend_positive():
    # straight uptrend → positive lookback return → ENTRY_LONG
    prices = list(np.linspace(100, 130, 80))
    s = TSMOM("TEST")
    sigs = s.on_bar(_bars(prices))
    assert len(sigs) == 1
    assert sigs[0].kind == SignalKind.ENTRY_LONG
    assert sigs[0].stop < sigs[0].entry, "long stop must sit below entry"


def test_emits_exit_when_trend_flips_negative():
    # need >= vol_window+1 = 61 bars before the strategy can score anything
    up = list(np.linspace(100, 130, 90))
    dn = list(np.linspace(130, 95, 40))
    s = TSMOM("TEST")
    long_sigs = s.on_bar(_bars(up))
    assert long_sigs and long_sigs[0].kind == SignalKind.ENTRY_LONG
    exit_sigs = s.on_bar(_bars(up + dn))
    assert exit_sigs and exit_sigs[0].kind == SignalKind.EXIT


def test_no_double_entry_when_already_long():
    prices = list(np.linspace(100, 130, 80))
    s = TSMOM("TEST")
    df = _bars(prices)
    first = s.on_bar(df)
    assert first and first[0].kind == SignalKind.ENTRY_LONG
    # call again with same frame → no new ENTRY (state is long)
    second = s.on_bar(df)
    assert second == []


def test_returns_empty_when_not_enough_history():
    s = TSMOM("TEST", params={"lookback": 20, "vol_window": 60})
    assert s.on_bar(_bars([100.0] * 30)) == []


def test_vol_target_caps_at_one():
    # extreme low-vol → scale would be huge; must clamp to 1.0 (confidence)
    prices = list(np.linspace(100, 130, 80))  # smooth ramp, tiny vol
    s = TSMOM("TEST", params={"vol_target": 0.50})
    sigs = s.on_bar(_bars(prices))
    assert sigs
    assert sigs[0].confidence <= 1.0


def test_flat_market_no_signal():
    prices = [100.0] * 80
    s = TSMOM("TEST")
    # all-equal prices → vol = 0 → guard returns []
    assert s.on_bar(_bars(prices)) == []
