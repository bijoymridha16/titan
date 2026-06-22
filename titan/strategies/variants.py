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
from titan.strategies.library import _Base
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


class MACDCross(_Base):
    """MACD line crossing its signal line (trend/momentum)."""
    name = "macd_cross"
    family = "trend"
    DEFAULTS = {"fast": 12, "slow": 26, "signal": 9,
                "atr_period": 14, "atr_mult": 2.0, "target_r": 2.0}

    def on_bar(self, bars):
        f, s, sg = (int(self.params[k]) for k in ("fast", "slow", "signal"))
        if len(bars) < s + sg + 2:
            return []
        line, sig, _ = ind.macd(bars["c"], f, s, sg)
        if not all(np.isfinite(x) for x in (line.iloc[-1], sig.iloc[-1], line.iloc[-2], sig.iloc[-2])):
            return []
        up = line.iloc[-1] > sig.iloc[-1] and line.iloc[-2] <= sig.iloc[-2]
        dn = line.iloc[-1] < sig.iloc[-1] and line.iloc[-2] >= sig.iloc[-2]
        c = float(bars["c"].iloc[-1]); ts = bars.index[-1]; tr = self.params.get("target_r")
        if up and self._last_dir <= 0:
            stop = self._atr_stop(bars, c, +1, self.params["atr_mult"])
            if stop:
                self._last_dir = 1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=stop,
                               target=self._target(c, stop, +1, tr), reason="MACD cross up")]
        if dn and self._last_dir >= 0:
            stop = self._atr_stop(bars, c, -1, self.params["atr_mult"])
            if stop:
                self._last_dir = -1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=stop,
                               target=self._target(c, stop, -1, tr), reason="MACD cross dn")]
        return []


class StochRSIADX(_Base):
    """Stochastic-RSI %K/%D crossover, gated by ADX trend strength (only act when
    a trend is present). Momentum-with-confirmation."""
    name = "stoch_adx"
    family = "momentum"
    DEFAULTS = {"rsi_period": 14, "stoch_period": 14, "k": 3, "d": 3,
                "adx_period": 14, "adx_min": 20.0,
                "atr_period": 14, "atr_mult": 2.0, "target_r": 2.0}

    def on_bar(self, bars):
        need = max(self.params["rsi_period"] + self.params["stoch_period"],
                   self.params["adx_period"] * 2) + 5
        if len(bars) < need:
            return []
        kk, dd = ind.stoch_rsi(bars["c"], int(self.params["rsi_period"]),
                               int(self.params["stoch_period"]),
                               int(self.params["k"]), int(self.params["d"]))
        a = ind.adx(bars, int(self.params["adx_period"])).iloc[-1]
        if not (np.isfinite(kk.iloc[-1]) and np.isfinite(dd.iloc[-1])
                and np.isfinite(kk.iloc[-2]) and np.isfinite(dd.iloc[-2]) and np.isfinite(a)):
            return []
        if a < self.params["adx_min"]:
            return []
        up = kk.iloc[-1] > dd.iloc[-1] and kk.iloc[-2] <= dd.iloc[-2] and kk.iloc[-1] < 50
        dn = kk.iloc[-1] < dd.iloc[-1] and kk.iloc[-2] >= dd.iloc[-2] and kk.iloc[-1] > 50
        c = float(bars["c"].iloc[-1]); ts = bars.index[-1]; tr = self.params.get("target_r")
        if up and self._last_dir <= 0:
            stop = self._atr_stop(bars, c, +1, self.params["atr_mult"])
            if stop:
                self._last_dir = 1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=stop,
                               target=self._target(c, stop, +1, tr), reason=f"StochRSI x up ADX={a:.0f}")]
        if dn and self._last_dir >= 0:
            stop = self._atr_stop(bars, c, -1, self.params["atr_mult"])
            if stop:
                self._last_dir = -1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=stop,
                               target=self._target(c, stop, -1, tr), reason=f"StochRSI x dn ADX={a:.0f}")]
        return []


class RSIDivergence(_Base):
    """Lightweight RSI divergence: price makes a lower low while RSI makes a
    higher low (bullish) / mirror for bearish. Mean-reversion at momentum
    exhaustion."""
    name = "rsi_divergence"
    family = "mean_reversion"
    DEFAULTS = {"rsi_period": 14, "lookback": 5,
                "atr_period": 14, "atr_mult": 1.5, "target_r": 2.0}

    def on_bar(self, bars):
        p, lb = int(self.params["rsi_period"]), int(self.params["lookback"])
        if len(bars) < p + lb + 2:
            return []
        r = ind.rsi(bars["c"], p)
        c0, cprev = float(bars["c"].iloc[-1]), float(bars["c"].iloc[-1 - lb])
        r0, rprev = r.iloc[-1], r.iloc[-1 - lb]
        if not (np.isfinite(r0) and np.isfinite(rprev)):
            return []
        c = c0; ts = bars.index[-1]; tr = self.params.get("target_r")
        bull = c0 < cprev and r0 > rprev and r0 < 45      # price down, momentum up
        bear = c0 > cprev and r0 < rprev and r0 > 55       # price up, momentum down
        if bull and self._last_dir <= 0:
            stop = self._atr_stop(bars, c, +1, self.params["atr_mult"])
            if stop:
                self._last_dir = 1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=stop,
                               target=self._target(c, stop, +1, tr), reason="bullish RSI divergence")]
        if bear and self._last_dir >= 0:
            stop = self._atr_stop(bars, c, -1, self.params["atr_mult"])
            if stop:
                self._last_dir = -1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=stop,
                               target=self._target(c, stop, -1, tr), reason="bearish RSI divergence")]
        return []


class SupertrendMulti(_Base):
    """Two Supertrends (fast + slow) must AGREE on direction — filters the chop
    that a single Supertrend gets whipsawed by."""
    name = "supertrend_multi"
    family = "trend"
    DEFAULTS = {"p1": 10, "m1": 3.0, "p2": 20, "m2": 5.0,
                "atr_period": 14, "target_r": 2.0}

    def on_bar(self, bars):
        if len(bars) < max(self.params["p1"], self.params["p2"]) * 3:
            return []
        l1, d1 = ind.supertrend(bars, int(self.params["p1"]), float(self.params["m1"]))
        l2, d2 = ind.supertrend(bars, int(self.params["p2"]), float(self.params["m2"]))
        if not (np.isfinite(l1.iloc[-1]) and np.isfinite(l2.iloc[-1])):
            return []
        long_now = d1.iloc[-1] == 1 and d2.iloc[-1] == 1
        short_now = d1.iloc[-1] == -1 and d2.iloc[-1] == -1
        c = float(bars["c"].iloc[-1]); ts = bars.index[-1]; tr = self.params.get("target_r")
        if long_now and self._last_dir <= 0:
            stop = min(float(l1.iloc[-1]), float(l2.iloc[-1]))
            if stop < c:
                self._last_dir = 1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=stop,
                               target=self._target(c, stop, +1, tr), reason="2×Supertrend agree up")]
        if short_now and self._last_dir >= 0:
            stop = max(float(l1.iloc[-1]), float(l2.iloc[-1]))
            if stop > c:
                self._last_dir = -1
                return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=stop,
                               target=self._target(c, stop, -1, tr), reason="2×Supertrend agree dn")]
        return []


class InsideBar(_Base):
    """Inside-bar breakout: when the previous bar is contained inside its mother
    bar (volatility contraction), trade the break of the mother bar's range."""
    name = "inside_bar"
    family = "breakout"
    DEFAULTS = {"atr_period": 14, "target_r": 2.0}

    def on_bar(self, bars):
        if len(bars) < max(4, self.params["atr_period"] + 2):
            return []
        mother, inside, cur = bars.iloc[-3], bars.iloc[-2], bars.iloc[-1]
        is_inside = inside["h"] < mother["h"] and inside["l"] > mother["l"]
        if not is_inside:
            return []
        c = float(cur["c"]); ts = bars.index[-1]; tr = self.params.get("target_r")
        mh, ml = float(mother["h"]), float(mother["l"])
        if c > mh and self._last_dir <= 0:
            self._last_dir = 1
            return [Signal(ts, self.symbol, SignalKind.ENTRY_LONG, entry=c, stop=ml,
                           target=self._target(c, ml, +1, tr), reason="inside-bar break up")]
        if c < ml and self._last_dir >= 0:
            self._last_dir = -1
            return [Signal(ts, self.symbol, SignalKind.ENTRY_SHORT, entry=c, stop=mh,
                           target=self._target(c, mh, -1, tr), reason="inside-bar break dn")]
        return []
