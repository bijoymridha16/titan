"""Time-Series Momentum with vol-targeting.

See docs/research/01_tsmom.md for the rationale, evidence, and decision criteria.

Logic (long-only, equity cash MIS — no shorting allowed at our capital tier):
  1. Once per bar (typically daily close): compute sign of return over `lookback`
  2. If positive → emit ENTRY_LONG sized via inverse-vol targeting
  3. If negative or zero → emit EXIT (close any long)

Stops are intentionally wide (~2σ daily move) so the strategy isn't whipsawed
out by intraday noise — TSMOM is a multi-day trend bet, not a breakout.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from titan.strategies.base import Signal, SignalKind, Strategy

ANN = 252  # trading days for vol annualisation


class TSMOM(Strategy):
    name = "tsmom"
    timeframe = "1d"

    def __init__(self, symbol: str, params: Optional[dict] = None):
        super().__init__(symbol, params)
        self.lookback     = int(self.params.get("lookback", 20))
        self.vol_window   = int(self.params.get("vol_window", 60))
        self.vol_target   = float(self.params.get("vol_target", 0.10))   # 10% annualised
        self.stop_sigma   = float(self.params.get("stop_sigma", 2.0))    # 2σ wide stop
        self._last_state: str = "flat"   # "flat" | "long"

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        # need enough history for both windows
        if len(bars) < max(self.lookback, self.vol_window) + 1:
            return []

        close = bars["c"].astype(float)
        last_ts = bars.index[-1]
        last_px = float(close.iloc[-1])

        # 1) lookback return (log-return; sign is what matters)
        r_lb = math.log(close.iloc[-1] / close.iloc[-1 - self.lookback])

        # 2) realised vol (annualised) from daily log-returns
        log_rets = np.log(close / close.shift(1)).dropna()
        recent = log_rets.iloc[-self.vol_window:]
        realised_vol = float(recent.std() * math.sqrt(ANN))
        if realised_vol <= 0:
            return []

        # 3) vol-target scaling — caps at 1.0 (no leverage at our capital tier)
        scale = min(1.0, self.vol_target / realised_vol)

        # 4) daily stdev for stop sizing
        daily_sigma = float(recent.std())
        stop_px = last_px * math.exp(-self.stop_sigma * daily_sigma)

        signals: list[Signal] = []

        if r_lb > 0:
            if self._last_state != "long":
                signals.append(Signal(
                    ts=last_ts, symbol=self.symbol,
                    kind=SignalKind.ENTRY_LONG,
                    entry=last_px, stop=stop_px, target=None,
                    confidence=scale,
                    reason=f"TSMOM L={self.lookback} r={r_lb*100:+.2f}% "
                           f"vol={realised_vol*100:.1f}% scale={scale:.2f}",
                ))
                self._last_state = "long"
        else:
            if self._last_state == "long":
                signals.append(Signal(
                    ts=last_ts, symbol=self.symbol,
                    kind=SignalKind.EXIT,
                    entry=last_px, stop=last_px,
                    reason=f"TSMOM flip r={r_lb*100:+.2f}%",
                ))
                self._last_state = "flat"
        return signals
