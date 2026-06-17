"""Parametrized strategy families.

Each class is a real, self-contained strategy whose behaviour is fully
determined by its params — so the factory (factory.py) can expand each family
into many variants for the pre-live vetting harness. All emit entries on the
EVENT (crossover / breakout / band touch), not every bar the condition holds,
and carry an explicit stop (+ optional target) so the RiskEngine can size them.

These are deliberately textbook constructions. They are NOT validated edges —
they exist to be run through walk-forward and mostly KILLED. Only survivors of
the predeclared ship/kill gate reach the auto-pilot's validated allowlist.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from titan.strategies import indicators as ind
from titan.strategies.base import Signal, SignalKind, Strategy


class _Base(Strategy):
    timeframe = "5m"
    family = "generic"

    def __init__(self, symbol: str, params: Optional[dict] = None):
        super().__init__(symbol, {**getattr(self, "DEFAULTS", {}), **(params or {})})
        self._last_dir = 0  # -1 short, 0 flat, +1 long — to emit on transitions only

    def _atr_stop(self, bars, entry, direction, mult):
        a = ind.atr(bars, int(self.params.get("atr_period", 14))).iloc[-1]
        if not np.isfinite(a) or a <= 0:
            return None
        return entry - mult * a if direction > 0 else entry + mult * a

    @staticmethod
    def _min_bars(*vals) -> int:
        return max(vals) + 2


class MACrossover(_Base):
    name = "ma_cross"
    family = "trend"
    DEFAULTS = {"fast": 9, "slow": 21, "atr_period": 14, "atr_mult": 2.0}

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        f, s = int(self.params["fast"]), int(self.params["slow"])
        if len(bars) < self._min_bars(f, s):
            return []
        ef, es = ind.ema(bars["c"], f), ind.ema(bars["c"], s)
        up = ef.iloc[-1] > es.iloc[-1] and ef.iloc[-2] <= es.iloc[-2]
        dn = ef.iloc[-1] < es.iloc[-1] and ef.iloc[-2] >= es.iloc[-2]
        c = float(bars["c"].iloc[-1]); ts = bars.index[-1]
        if up and self._last_dir <= 0:
            stop = self._atr_stop(bars, c, +1, self.params["atr_mult"])
            if stop:
                self._last_dir = 1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=stop,
                               target=None, reason=f"EMA{f}>EMA{s}")]
        if dn and self._last_dir >= 0:
            stop = self._atr_stop(bars, c, -1, self.params["atr_mult"])
            if stop:
                self._last_dir = -1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=stop,
                               target=None, reason=f"EMA{f}<EMA{s}")]
        return []


class DonchianBreakout(_Base):
    name = "donchian"
    family = "breakout"
    DEFAULTS = {"period": 20, "atr_period": 14, "target_r": 2.0}

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        p = int(self.params["period"])
        if len(bars) < self._min_bars(p):
            return []
        hi, lo = ind.donchian(bars, p)
        h, l = hi.iloc[-1], lo.iloc[-1]
        if not (np.isfinite(h) and np.isfinite(l)):
            return []
        c = float(bars["c"].iloc[-1]); ts = bars.index[-1]
        tgt_r = float(self.params["target_r"])
        if c > h and self._last_dir <= 0:
            self._last_dir = 1
            rng = c - l
            return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=float(l),
                           target=c + tgt_r * rng, reason=f"Donchian{p} break up")]
        if c < l and self._last_dir >= 0:
            self._last_dir = -1
            rng = h - c
            return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=float(h),
                           target=c - tgt_r * rng, reason=f"Donchian{p} break dn")]
        return []


class RSIReversion(_Base):
    name = "rsi_revert"
    family = "mean_reversion"
    DEFAULTS = {"period": 14, "lo": 30.0, "hi": 70.0, "atr_period": 14, "atr_mult": 1.5}

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        p = int(self.params["period"])
        if len(bars) < self._min_bars(p):
            return []
        r = ind.rsi(bars["c"], p)
        cur, prev = r.iloc[-1], r.iloc[-2]
        if not (np.isfinite(cur) and np.isfinite(prev)):
            return []
        c = float(bars["c"].iloc[-1]); ts = bars.index[-1]
        lo, hi = float(self.params["lo"]), float(self.params["hi"])
        if prev >= lo > cur and self._last_dir <= 0:  # crossed down into oversold → fade up
            stop = self._atr_stop(bars, c, +1, self.params["atr_mult"])
            if stop:
                self._last_dir = 1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=stop,
                               target=None, reason=f"RSI{p}<{lo:.0f}")]
        if prev <= hi < cur and self._last_dir >= 0:  # crossed up into overbought → fade down
            stop = self._atr_stop(bars, c, -1, self.params["atr_mult"])
            if stop:
                self._last_dir = -1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=stop,
                               target=None, reason=f"RSI{p}>{hi:.0f}")]
        return []


class BollingerReversion(_Base):
    name = "bollinger_revert"
    family = "mean_reversion"
    DEFAULTS = {"period": 20, "k": 2.0, "atr_period": 14, "atr_mult": 1.5}

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        p = int(self.params["period"])
        if len(bars) < self._min_bars(p):
            return []
        mid, up, low = ind.bollinger(bars["c"], p, float(self.params["k"]))
        m, u, lw = mid.iloc[-1], up.iloc[-1], low.iloc[-1]
        if not (np.isfinite(m) and np.isfinite(u) and np.isfinite(lw)):
            return []
        c = float(bars["c"].iloc[-1]); ts = bars.index[-1]
        if c < lw and self._last_dir <= 0:
            stop = self._atr_stop(bars, c, +1, self.params["atr_mult"])
            if stop:
                self._last_dir = 1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=stop,
                               target=float(m), reason=f"BB{p} lower")]
        if c > u and self._last_dir >= 0:
            stop = self._atr_stop(bars, c, -1, self.params["atr_mult"])
            if stop:
                self._last_dir = -1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=stop,
                               target=float(m), reason=f"BB{p} upper")]
        return []


class MomentumROC(_Base):
    name = "momentum"
    family = "momentum"
    DEFAULTS = {"lookback": 20, "atr_period": 14, "atr_mult": 2.0}

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        lb = int(self.params["lookback"])
        if len(bars) < self._min_bars(lb):
            return []
        r = ind.roc(bars["c"], lb)
        cur, prev = r.iloc[-1], r.iloc[-2]
        if not (np.isfinite(cur) and np.isfinite(prev)):
            return []
        c = float(bars["c"].iloc[-1]); ts = bars.index[-1]
        if cur > 0 >= prev and self._last_dir <= 0:  # momentum turns positive
            stop = self._atr_stop(bars, c, +1, self.params["atr_mult"])
            if stop:
                self._last_dir = 1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=stop,
                               target=None, reason=f"ROC{lb}>0")]
        if cur < 0 <= prev and self._last_dir >= 0:  # momentum turns negative
            stop = self._atr_stop(bars, c, -1, self.params["atr_mult"])
            if stop:
                self._last_dir = -1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=stop,
                               target=None, reason=f"ROC{lb}<0")]
        return []


FAMILIES = [MACrossover, DonchianBreakout, RSIReversion, BollingerReversion, MomentumROC]
