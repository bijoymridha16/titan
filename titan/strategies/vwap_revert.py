"""VWAP mean-reversion (skeleton).

Logic:
  - Compute session VWAP from start-of-day cumulative (price*vol)/vol.
  - When price deviates > k * rolling_std(price-VWAP), fade toward VWAP.
  - Stop = entry +/- atr * atr_mult; Target = VWAP.
  - Skip in trending sessions (ADX > 25 on a higher TF) — handled by
    a regime overlay, not inside this class.

Indian-market evidence: INSUFFICIENT EVIDENCE for naked VWAP-revert intraday.
Use only as one leg of the regime-gated hybrid (range regime).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from titan.strategies import indicators as ind
from titan.strategies.base import Signal, SignalKind, Strategy


class VWAPRevert(Strategy):
    name = "vwap_revert"
    timeframe = "5m"

    # rsi_gate is OFF by default → baseline behaviour is unchanged. The VWAPRevertRSI
    # variant turns it on (and widens the stop) per the external-analysis triage.
    DEFAULTS = {"k_sigma": 2.0, "atr_period": 14, "atr_mult": 1.0, "lookback": 20,
                "rsi_gate": False, "rsi_period": 14, "rsi_hi": 65.0, "rsi_lo": 35.0}

    def __init__(self, symbol: str, params: Optional[dict] = None):
        super().__init__(symbol, {**self.DEFAULTS, **(params or {})})

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        if len(bars) < max(self.params["atr_period"], self.params["lookback"]) + 2:
            return []
        today = bars[bars.index.date == bars.index[-1].date()]  # type: ignore[attr-defined]
        if today.empty:
            return []

        pv = (today["c"] * today["v"]).cumsum()
        vv = today["v"].cumsum().replace(0, np.nan)
        vwap = (pv / vv).iloc[-1]
        if not np.isfinite(vwap):
            return []

        dev = today["c"] - (pv / vv)
        sigma = dev.tail(self.params["lookback"]).std()
        if not np.isfinite(sigma) or sigma == 0:
            return []

        last_c = float(today["c"].iloc[-1])
        z = (last_c - vwap) / sigma
        k = self.params["k_sigma"]

        tr = pd.concat([
            bars["h"] - bars["l"],
            (bars["h"] - bars["c"].shift()).abs(),
            (bars["l"] - bars["c"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(self.params["atr_period"]).mean().iloc[-1]
        if not np.isfinite(atr) or atr <= 0:
            return []

        # optional RSI confirmation: only fade when momentum is also exhausted
        # (overbought for shorts, oversold for longs). Off for the baseline.
        rsi_ok_short = rsi_ok_long = True
        if self.params.get("rsi_gate"):
            rv = ind.rsi(bars["c"], int(self.params["rsi_period"])).iloc[-1]
            if not np.isfinite(rv):
                return []
            rsi_ok_short = rv >= float(self.params["rsi_hi"])
            rsi_ok_long = rv <= float(self.params["rsi_lo"])

        ts = bars.index[-1]
        if z > k and rsi_ok_short:
            return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT,
                           entry=last_c, stop=last_c + self.params["atr_mult"] * atr,
                           target=float(vwap), reason=f"VWAP+{z:.1f}σ revert short")]
        if z < -k and rsi_ok_long:
            return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG,
                           entry=last_c, stop=last_c - self.params["atr_mult"] * atr,
                           target=float(vwap), reason=f"VWAP{z:.1f}σ revert long")]
        return []
