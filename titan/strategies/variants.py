"""Structural strategy variants derived from the external-analysis triage
(docs/13). These are *new* strategies — the baselines (orb, vwap_revert,
bollinger_revert) are left untouched so they remain a stable comparison.

  • ConfirmationORB  — ORB that only takes a breakout confirmed by volume
                       expansion AND EMA-slope agreement (kills false breakouts).
  • VWAPRevertRSI    — VWAP mean-reversion with a wider stop and an RSI
                       momentum-exhaustion gate (addresses the 30-stop/7-target
                       skew on the baseline).
  • BollingerSqueeze — trades the EXPANSION out of a low-volatility squeeze
                       (BBW at a rolling low), the opposite of fading the band.

All emit on the event with an explicit stop so the RiskEngine can size them.
Parameter VALUES here are starting points — they must be earned on real
backfilled data via walk-forward, not trusted from synthetic behaviour.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from titan.strategies import indicators as ind
from titan.strategies.base import Signal, SignalKind, Strategy
from titan.strategies.orb import OpeningRangeBreakout
from titan.strategies.vwap_revert import VWAPRevert


class ConfirmationORB(OpeningRangeBreakout):
    """ORB + false-breakout filter: the breakout bar must show volume expansion
    and agree with the EMA(trend_ema) slope. Reuses all the opening-range /
    session machinery from the base via the `_confirm` hook."""
    name = "orb_confirmed"

    DEFAULTS = {**OpeningRangeBreakout.DEFAULTS,
                "vol_mult": 1.2, "trend_ema": 21}

    def _confirm(self, bars: pd.DataFrame, direction: int) -> bool:
        vol_mult = float(self.params.get("vol_mult", 1.2))
        n = int(self.params.get("trend_ema", 21))
        if len(bars) < n + 2:
            return False
        v = bars["v"].astype(float)
        # volume expansion vs the recent average (exclude the current bar)
        avg_v = v.iloc[-(n + 1):-1].mean()
        if np.isfinite(avg_v) and avg_v > 0 and v.iloc[-1] < vol_mult * avg_v:
            return False
        # EMA slope must agree with the breakout direction
        e = ind.ema(bars["c"], n)
        slope = e.iloc[-1] - e.iloc[-2]
        if not np.isfinite(slope):
            return False
        return bool(slope > 0) if direction > 0 else bool(slope < 0)


class VWAPRevertRSI(VWAPRevert):
    """VWAP-revert with a wider ATR stop and RSI momentum-exhaustion gate."""
    name = "vwap_rsi"

    DEFAULTS = {**VWAPRevert.DEFAULTS,
                "atr_mult": 2.5, "rsi_gate": True, "rsi_hi": 65.0, "rsi_lo": 35.0}


class BollingerSqueeze(Strategy):
    """Volatility-squeeze breakout: when Bollinger Band Width sits at a rolling
    low (compression), trade the FIRST close beyond a band in the breakout
    direction, with volume confirmation. Distinct from BollingerReversion, which
    fades band touches."""
    name = "bb_squeeze"
    timeframe = "5m"

    DEFAULTS = {"period": 20, "k": 2.0, "squeeze_lookback": 100,
                "squeeze_pctile": 0.20, "vol_mult": 1.2,
                "atr_period": 14, "atr_mult": 2.0}

    def __init__(self, symbol: str, params: Optional[dict] = None):
        super().__init__(symbol, {**self.DEFAULTS, **(params or {})})
        self._last_dir = 0

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        p = int(self.params["period"])
        lb = int(self.params["squeeze_lookback"])
        if len(bars) < max(p, self.params["atr_period"]) + 3:
            return []
        mid, up, low = ind.bollinger(bars["c"], p, float(self.params["k"]))
        m, u, lw = mid.iloc[-1], up.iloc[-1], low.iloc[-1]
        if not (np.isfinite(m) and np.isfinite(u) and np.isfinite(lw) and m != 0):
            return []
        bbw = (up - low) / mid
        # was the PRIOR bar in a squeeze (BBW in the low percentile of its history)?
        hist = bbw.iloc[-(lb + 1):-1].dropna()
        if len(hist) < max(10, p):
            return []
        thresh = hist.quantile(float(self.params["squeeze_pctile"]))
        prev_bbw = bbw.iloc[-2]
        if not (np.isfinite(prev_bbw) and prev_bbw <= thresh):
            return []

        # volume expansion on the breakout bar
        v = bars["v"].astype(float)
        avg_v = v.iloc[-(p + 1):-1].mean()
        if np.isfinite(avg_v) and avg_v > 0 and v.iloc[-1] < float(self.params["vol_mult"]) * avg_v:
            return []

        a = ind.atr(bars, int(self.params["atr_period"])).iloc[-1]
        if not np.isfinite(a) or a <= 0:
            return []
        c = float(bars["c"].iloc[-1]); ts = bars.index[-1]
        mult = float(self.params["atr_mult"])
        if c > u and self._last_dir <= 0:
            self._last_dir = 1
            return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c,
                           stop=c - mult * a, target=None,
                           reason=f"BB squeeze break up (BBW≤p{int(self.params['squeeze_pctile']*100)})")]
        if c < lw and self._last_dir >= 0:
            self._last_dir = -1
            return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c,
                           stop=c + mult * a, target=None,
                           reason=f"BB squeeze break dn (BBW≤p{int(self.params['squeeze_pctile']*100)})")]
        return []
