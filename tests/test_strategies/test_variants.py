"""Tests for the activated library families + new structural variants."""
from __future__ import annotations

import numpy as np
import pandas as pd

from titan.strategies.base import SignalKind
from titan.strategies.registry import BASE_STRATEGIES
from titan.strategies.variants import BollingerSqueeze, ConfirmationORB, VWAPRevertRSI


def _bars(closes, vols=None, start="2026-06-22 09:15", freq="5min"):
    n = len(closes)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    c = np.asarray(closes, dtype=float)
    v = np.asarray(vols if vols is not None else [100] * n, dtype=float)
    return pd.DataFrame({"o": c, "h": c + 0.2, "l": c - 0.2, "c": c, "v": v}, index=idx)


def test_registry_all_strategies_instantiate():
    assert len(BASE_STRATEGIES) >= 12
    for name, cls in BASE_STRATEGIES.items():
        inst = cls("NIFTY")
        assert hasattr(inst, "on_bar")
        # on_bar must run on a trivial history without raising
        inst.on_bar(_bars([100.0] * 60))


def test_vwap_rsi_variant_defaults():
    s = VWAPRevertRSI("NIFTY")
    assert s.params["rsi_gate"] is True
    assert s.params["atr_mult"] == 2.5


def test_confirmation_orb_gate():
    s = ConfirmationORB("NIFTY")
    # rising EMA, but flat volume on the last bar → confirmation fails
    rising = _bars(list(np.linspace(100, 110, 40)), vols=[100] * 40)
    assert s._confirm(rising, +1) is False
    # rising EMA + volume spike on the last bar → confirmation passes (long)
    vols = [100] * 39 + [400]
    rising_vol = _bars(list(np.linspace(100, 110, 40)), vols=vols)
    assert s._confirm(rising_vol, +1) is True
    # volume spike but FALLING ema → long not confirmed
    falling_vol = _bars(list(np.linspace(110, 100, 40)), vols=vols)
    assert s._confirm(falling_vol, +1) is False


def test_bollinger_squeeze_breaks_out():
    # 130 low-vol bars (tight band) then a high-volume breakout up
    base = [100.0 + (0.3 if i % 2 else 0.0) for i in range(130)]
    closes = base + [104.0]
    vols = [100] * 130 + [1000]
    s = BollingerSqueeze("NIFTY")
    out = s.on_bar(_bars(closes, vols=vols))
    assert out and out[0].kind == SignalKind.ENTRY_LONG
    assert out[0].stop < out[0].entry  # long stop below entry


def test_bollinger_squeeze_no_breakout_when_calm():
    closes = [100.0 + (0.3 if i % 2 else 0.0) for i in range(131)]  # stays in band
    s = BollingerSqueeze("NIFTY")
    assert s.on_bar(_bars(closes)) == []
