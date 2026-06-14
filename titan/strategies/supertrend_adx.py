"""Supertrend + ADX trend-follower (skeleton).

Entries only when:
  - Supertrend flips direction.
  - ADX(14) > 20 (trend filter; avoids whipsaws in range regime).
  - Bar close is in the new Supertrend direction.

Stop = Supertrend line. Trail with the line. Exit on flip.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from titan.strategies.base import Signal, SignalKind, Strategy


def _atr(bars: pd.DataFrame, period: int) -> pd.Series:
    h, l, c = bars["h"], bars["l"], bars["c"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _supertrend(bars: pd.DataFrame, period: int, mult: float) -> tuple[pd.Series, pd.Series]:
    atr = _atr(bars, period)
    hl2 = (bars["h"] + bars["l"]) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    st = pd.Series(index=bars.index, dtype=float)
    dirn = pd.Series(index=bars.index, dtype=int)
    for i in range(len(bars)):
        if i == 0 or np.isnan(atr.iloc[i]):
            st.iloc[i] = upper.iloc[i]
            dirn.iloc[i] = -1
            continue
        prev_st = st.iloc[i - 1]
        prev_dir = dirn.iloc[i - 1]
        if prev_dir == -1:  # was downtrend
            st.iloc[i] = min(upper.iloc[i], prev_st)
            dirn.iloc[i] = 1 if bars["c"].iloc[i] > st.iloc[i] else -1
            if dirn.iloc[i] == 1:
                st.iloc[i] = lower.iloc[i]
        else:
            st.iloc[i] = max(lower.iloc[i], prev_st)
            dirn.iloc[i] = -1 if bars["c"].iloc[i] < st.iloc[i] else 1
            if dirn.iloc[i] == -1:
                st.iloc[i] = upper.iloc[i]
    return st, dirn


def _adx(bars: pd.DataFrame, period: int) -> pd.Series:
    up = bars["h"].diff()
    dn = -bars["l"].diff()
    plus_dm = ((up > dn) & (up > 0)).astype(float) * up
    minus_dm = ((dn > up) & (dn > 0)).astype(float) * dn
    atr = _atr(bars, period)
    plus_di = 100 * plus_dm.rolling(period).mean() / atr
    minus_di = 100 * minus_dm.rolling(period).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean()


class SupertrendADX(Strategy):
    name = "supertrend_adx"
    timeframe = "5m"

    DEFAULTS = {"st_period": 10, "st_mult": 3.0, "adx_period": 14, "adx_min": 20.0}

    def __init__(self, symbol: str, params: Optional[dict] = None):
        super().__init__(symbol, {**self.DEFAULTS, **(params or {})})

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        if len(bars) < max(self.params["st_period"], self.params["adx_period"]) * 3:
            return []
        st, dirn = _supertrend(bars, self.params["st_period"], self.params["st_mult"])
        adx = _adx(bars, self.params["adx_period"])
        if not np.isfinite(adx.iloc[-1]) or adx.iloc[-1] < self.params["adx_min"]:
            return []
        if dirn.iloc[-1] == dirn.iloc[-2]:
            return []
        ts, c = bars.index[-1], float(bars["c"].iloc[-1])
        s = float(st.iloc[-1])
        if dirn.iloc[-1] == 1:
            return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=s,
                           reason=f"ST flip long, ADX={adx.iloc[-1]:.1f}")]
        return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=s,
                       reason=f"ST flip short, ADX={adx.iloc[-1]:.1f}")]
