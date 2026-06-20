"""RegimeClassifier is a pure, deterministic function of bars + clock.

These tests build synthetic 5m bar frames with known character (trending,
ranging, explosive) and assert the classifier labels them as expected, and that
the same input always yields the same output (no hallucination)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from titan.decision.regime import (
    Regime, RegimeClassifier, SessionPhase, session_phase,
)

IST = ZoneInfo("Asia/Kolkata")


def _bars(closes, start_hour=9, start_min=15, base=24000.0):
    """Build a 5m OHLCV frame from a close path, indexed in IST (tz-aware).

    The classifier converts tz-aware indices via tz_convert, so an IST index is
    preserved as-is — the cleanest way to place bars at known session times."""
    n = len(closes)
    start = datetime(2026, 6, 12, start_hour, start_min, tzinfo=IST)
    idx = [start + timedelta(minutes=5 * i) for i in range(n)]
    closes = np.asarray(closes, dtype=float)
    highs = closes + 5
    lows = closes - 5
    opens = np.concatenate([[closes[0]], closes[:-1]])
    return pd.DataFrame(
        {"o": opens, "h": highs, "l": lows, "c": closes, "v": [1000] * n},
        index=pd.DatetimeIndex(idx),
    )


def _now(h, m):
    return datetime(2026, 6, 12, h, m, tzinfo=IST)


def test_session_phase_boundaries():
    assert session_phase(_now(9, 0)) == SessionPhase.PREOPEN
    assert session_phase(_now(9, 20)) == SessionPhase.OPENING_RANGE
    assert session_phase(_now(10, 30)) == SessionPhase.MORNING
    assert session_phase(_now(12, 0)) == SessionPhase.LUNCH
    assert session_phase(_now(14, 0)) == SessionPhase.AFTERNOON
    assert session_phase(_now(15, 20)) == SessionPhase.CUTOFF
    assert session_phase(_now(15, 45)) == SessionPhase.CLOSED


def test_closed_outside_session_regardless_of_bars():
    clf = RegimeClassifier("NIFTY")
    bars = _bars(np.linspace(24000, 24500, 250))  # strong trend
    r = clf.classify(bars, _now(8, 30))  # pre-open
    assert r.regime == Regime.CLOSED
    r2 = clf.classify(bars, _now(15, 45))  # closed
    assert r2.regime == Regime.CLOSED


def test_strong_trend_is_trend():
    clf = RegimeClassifier("NIFTY")
    # monotonic ramp → high ADX
    bars = _bars(np.linspace(24000, 25200, 250))
    r = clf.classify(bars, _now(10, 30))
    assert r.regime == Regime.TREND
    assert r.adx is not None and r.adx >= 22.0


def test_flat_choppy_is_range():
    clf = RegimeClassifier("NIFTY")
    # tiny oscillation around a level → low ADX, low vol
    osc = 24000 + 3 * np.sin(np.arange(250) / 2.0)
    bars = _bars(osc)
    r = clf.classify(bars, _now(10, 30))
    assert r.regime in (Regime.RANGE, Regime.TRANSITION)  # never trend on noise
    assert r.regime != Regime.TREND


def test_determinism_same_input_same_output():
    clf = RegimeClassifier("NIFTY")
    bars = _bars(np.linspace(24000, 25000, 250))
    a = clf.classify(bars, _now(11, 0))
    b = clf.classify(bars, _now(11, 0))
    assert a.regime == b.regime
    assert a.reason == b.reason
    assert a.adx == b.adx


def test_insufficient_bars_defaults_transition_not_crash():
    clf = RegimeClassifier("NIFTY")
    r = clf.classify(_bars([24000, 24010, 24005]), _now(10, 0))
    assert r.regime == Regime.TRANSITION  # safe default = ORB-only
    r2 = clf.classify(pd.DataFrame(), _now(10, 0))
    assert r2.regime == Regime.TRANSITION


def test_reading_is_serialisable():
    clf = RegimeClassifier("NIFTY")
    bars = _bars(np.linspace(24000, 25000, 250))
    log = clf.classify(bars, _now(11, 0)).as_log()
    assert set(log) >= {"regime", "session_phase", "ref_symbol", "reason"}
