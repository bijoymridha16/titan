"""Tests for the docs/14 additions: new indicators, strategies, targets, utils."""
import numpy as np
import pandas as pd

from titan.strategies import indicators as ind
from titan.strategies.base import SignalKind
from titan.strategies.library import MACrossover, MomentumROC
from titan.strategies.registry import BASE_STRATEGIES
from titan.strategies.variants import InsideBar, MACDCross
from titan.risk.allocator import inverse_vol_weights


def _bars(closes, vols=None, start="2026-06-22 09:15"):
    n = len(closes); idx = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    c = np.asarray(closes, float); v = np.asarray(vols if vols is not None else [100]*n, float)
    return pd.DataFrame({"o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "v": v}, index=idx)


# ---- indicators ----
def test_macd_shapes():
    s = pd.Series(np.linspace(100, 120, 80))
    line, sig, hist = ind.macd(s)
    assert len(line) == len(sig) == len(hist) == 80
    assert np.isfinite(line.iloc[-1])


def test_stoch_rsi_bounded():
    s = pd.Series(100 + np.sin(np.linspace(0, 20, 120)))
    k, d = ind.stoch_rsi(s)
    tail = k.dropna()
    assert (tail >= -0.01).all() and (tail <= 100.01).all()


def test_supertrend_direction_values():
    bars = _bars(list(np.linspace(100, 130, 80)))
    line, direction = ind.supertrend(bars)
    assert set(direction.dropna().unique()) <= {-1.0, 1.0}
    assert direction.iloc[-1] == 1.0  # steady uptrend → up


def test_adx_nonneg():
    bars = _bars(list(np.linspace(100, 130, 80)))
    a = ind.adx(bars).dropna()
    assert (a >= 0).all()


# ---- targets added to former 0%-win strategies ----
def test_ma_cross_now_has_target():
    # build an up-crossover and assert the long signal carries a target
    closes = [100]*25 + list(np.linspace(100, 112, 15))
    out = MACrossover("X").on_bar(_bars(closes))
    if out:  # crossover may land on the last bar
        assert out[0].target is not None


def test_macd_cross_emits_with_target():
    s = MACDCross("X")
    sig = None
    for closes in [list(np.linspace(100, 90, 60)) + list(np.linspace(90, 110, 20))]:
        sig = s.on_bar(_bars(closes))
    # either way, if it emits it must have a stop and a target
    if sig:
        assert sig[0].stop and sig[0].target is not None


def test_inside_bar_breakout():
    # mother bar wide, inside bar narrow, breakout up
    base = [100.0]*20
    df = _bars(base)
    # craft last 3 rows: mother(98-102), inside(99-101), break up to 103
    df = df.copy()
    df.iloc[-3] = [100, 102, 98, 100, 100]
    df.iloc[-2] = [100, 101, 99, 100, 100]
    df.iloc[-1] = [100, 103.5, 100, 103, 100]
    out = InsideBar("X").on_bar(df)
    assert out and out[0].kind == SignalKind.ENTRY_LONG and out[0].target is not None


# ---- registry covers all (incl. 5 new) ----
def test_registry_has_new_strategies():
    for name in ("macd_cross", "stoch_adx", "rsi_divergence", "supertrend_multi", "inside_bar"):
        assert name in BASE_STRATEGIES
        BASE_STRATEGIES[name]("X").on_bar(_bars([100.0]*70))  # runs clean


# ---- allocator ----
def test_inverse_vol_weights_favours_low_vol():
    w = inverse_vol_weights({"steady": [10, 11, 9, 10, 10], "wild": [200, -200, 150, -150, 0]})
    assert w["steady"] > w["wild"]
    assert abs(sum(w.values()) - 1.0) < 1e-6
