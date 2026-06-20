"""Deterministic market-regime classifier for NSE intraday.

PHILOSOPHY — "no hallucination":
    Every output is a pure function of observable inputs (OHLCV bars already in
    our DB + the IST clock + an optional India-VIX value IF a real feed provides
    one). There is no ML model, no opaque scoring, no fabricated data. Given the
    same bars and the same clock, the regime is always the same and the reason
    string explains exactly why. This is auditable after the fact.

WHY THESE FEATURES (Indian-market grounded):
    • ADX(14) on 5m — trend strength. NSE large-caps/indices trend cleanly on
      directional days and chop on balance days; ADX is the standard, mechanical
      separator (this is exactly the filter supertrend_adx/vwap_revert assume).
    • Realized volatility percentile — derived from 5m log-returns over the
      session lookback. We do NOT depend on an India-VIX feed (none exists in
      this stack); VIX is used ONLY if a value is explicitly supplied. Realized
      vol is the honest, always-available proxy.
    • Session phase — the NSE day is not homogeneous. The first 15 min is the
      opening-range build (no breakout entries yet); ~11:30–13:30 IST is the
      well-documented "lunch lull" (thin volume, false breakouts); entries must
      stop before the 15:15 square-off rush. Time-of-day is a first-class input,
      not an afterthought.

REGIMES:
    CLOSED       — outside the NSE session, or pre-09:15. Trade nothing.
    OPENING_RANGE flagged via session_phase, not a regime — handled by ORB itself.
    CRISIS       — realized vol above the crisis percentile (or VIX >= threshold).
                   Capital-preservation: arm nothing, let open positions exit.
    TREND        — ADX >= trend threshold. Breakout / trend-follow regime.
    RANGE        — ADX < range threshold AND vol not in crisis. Mean-revert regime.
    TRANSITION   — everything else (ADX between range and trend bands). Ambiguous;
                   only the single most-evidenced strategy (ORB) is appropriate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from titan.config import settings

IST = ZoneInfo("Asia/Kolkata")

# NSE cash session (IST). Pre-open auction 09:00–09:15 is not tradable here.
SESSION_OPEN = time(9, 15)
OPENING_RANGE_END = time(9, 30)   # first 15m = OR build
LUNCH_START = time(11, 30)
LUNCH_END = time(13, 30)
SESSION_CLOSE = time(15, 30)


class Regime(StrEnum):
    CLOSED = "CLOSED"
    CRISIS = "CRISIS"
    TREND = "TREND"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"


class SessionPhase(StrEnum):
    PREOPEN = "PREOPEN"
    OPENING_RANGE = "OPENING_RANGE"
    MORNING = "MORNING"
    LUNCH = "LUNCH"
    AFTERNOON = "AFTERNOON"
    CUTOFF = "CUTOFF"
    CLOSED = "CLOSED"


@dataclass
class RegimeReading:
    """Full, serialisable decision record — persisted verbatim to regime_decisions."""
    regime: Regime
    session_phase: SessionPhase
    ref_symbol: str
    adx: Optional[float] = None
    realized_vol: Optional[float] = None
    vol_pctile: Optional[float] = None
    or_expansion: Optional[float] = None
    india_vix: Optional[float] = None
    reason: str = ""
    features: dict = field(default_factory=dict)

    def as_log(self) -> dict:
        return {
            "regime": str(self.regime),
            "session_phase": str(self.session_phase),
            "ref_symbol": self.ref_symbol,
            "adx": self.adx,
            "realized_vol": self.realized_vol,
            "vol_pctile": self.vol_pctile,
            "or_expansion": self.or_expansion,
            "india_vix": self.india_vix,
            "reason": self.reason,
        }


# ──────────────── deterministic indicators (no external TA dep) ────────────────
def _atr(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = bars["h"].astype(float), bars["l"].astype(float), bars["c"].astype(float)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _adx(bars: pd.DataFrame, period: int = 14) -> float:
    """Wilder-style ADX, last value. Returns nan if not enough history."""
    if len(bars) < period * 3:
        return float("nan")
    h, l = bars["h"].astype(float), bars["l"].astype(float)
    up = h.diff()
    dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)).astype(float) * up
    minus_dm = ((dn > up) & (dn > 0)).astype(float) * dn
    atr = _atr(bars, period)
    plus_di = 100 * plus_dm.rolling(period).mean() / atr
    minus_di = 100 * minus_dm.rolling(period).mean() / atr
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    adx = dx.rolling(period).mean().iloc[-1]
    return float(adx) if np.isfinite(adx) else float("nan")


def _realized_vol_annualised(bars: pd.DataFrame, bars_per_day: int = 75) -> float:
    """Annualised realized vol from 5m log-returns.
    NSE cash day ≈ 6h15m = 375 min ≈ 75 five-minute bars. Annualise with 252 days."""
    c = bars["c"].astype(float)
    rets = np.log(c / c.shift(1)).dropna()
    if len(rets) < 5:
        return float("nan")
    return float(rets.std() * math.sqrt(bars_per_day * 252))


def _vol_percentile(bars: pd.DataFrame, window_bars: int, lookback: int) -> tuple[float, float]:
    """Return (current_realized_vol, its percentile in the recent distribution).
    Rolling realized vol over `window_bars`, percentile-ranked over `lookback`."""
    c = bars["c"].astype(float)
    rets = np.log(c / c.shift(1))
    roll = rets.rolling(window_bars).std() * math.sqrt(75 * 252)
    roll = roll.dropna()
    if len(roll) < 5:
        return float("nan"), float("nan")
    cur = float(roll.iloc[-1])
    tail = roll.tail(lookback)
    pctile = float((tail <= cur).mean())
    return cur, pctile


def _opening_range_expansion(bars: pd.DataFrame, day) -> float:
    """OR width (09:15–09:30) divided by 14-bar ATR. >1 ⇒ wide, energetic open."""
    idx = _to_ist(bars.index)
    today = bars[(idx.date == day) & (idx.time < OPENING_RANGE_END) & (idx.time >= SESSION_OPEN)]
    if today.empty:
        return float("nan")
    width = float(today["h"].astype(float).max() - today["l"].astype(float).min())
    atr = _atr(bars, 14).iloc[-1]
    if not np.isfinite(atr) or atr <= 0:
        return float("nan")
    return width / float(atr)


def _to_ist(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if idx.tz is None:
        return idx.tz_localize("UTC").tz_convert(IST)
    return idx.tz_convert(IST)


def session_phase(now_ist: datetime) -> SessionPhase:
    t = now_ist.timetz().replace(tzinfo=None)
    if t < SESSION_OPEN:
        return SessionPhase.PREOPEN
    if t < OPENING_RANGE_END:
        return SessionPhase.OPENING_RANGE
    if t >= SESSION_CLOSE:
        return SessionPhase.CLOSED
    if t >= settings.intraday_square_off:
        return SessionPhase.CUTOFF
    if LUNCH_START <= t < LUNCH_END:
        return SessionPhase.LUNCH
    if t < LUNCH_START:
        return SessionPhase.MORNING
    return SessionPhase.AFTERNOON


class RegimeClassifier:
    """Stateless. classify(bars, now) → RegimeReading. Pure function."""

    def __init__(self, ref_symbol: Optional[str] = None):
        self.ref_symbol = ref_symbol or settings.autopilot_ref_symbol

    def classify(self, bars: pd.DataFrame, now_ist: datetime,
                 india_vix: Optional[float] = None,
                 news_neg_p: Optional[float] = None) -> RegimeReading:
        phase = session_phase(now_ist)

        # 1) Outside the tradable session → CLOSED, regardless of any indicator.
        if phase in (SessionPhase.PREOPEN, SessionPhase.CLOSED, SessionPhase.CUTOFF):
            return RegimeReading(
                regime=Regime.CLOSED, session_phase=phase, ref_symbol=self.ref_symbol,
                india_vix=india_vix,
                reason=f"session phase {phase} — outside tradable window",
            )

        # 1b) Predictive news override (Multiplier 2). A strong negative FinBERT
        # reading forces CRISIS *ahead* of lagging ADX/ATR — fires even on thin
        # bars, so a shock disarms trend strategies before price reflects it.
        if (settings.regime_news_override and news_neg_p is not None
                and news_neg_p >= settings.regime_news_crisis_p):
            return RegimeReading(
                regime=Regime.CRISIS, session_phase=phase, ref_symbol=self.ref_symbol,
                india_vix=india_vix, features={"news_neg_p": news_neg_p},
                reason=(f"CRISIS: FinBERT negative sentiment p={news_neg_p:.2f} ≥ "
                        f"{settings.regime_news_crisis_p} — preemptive, arm nothing"),
            )

        if bars is None or bars.empty or len(bars) < 20:
            return RegimeReading(
                regime=Regime.TRANSITION, session_phase=phase, ref_symbol=self.ref_symbol,
                india_vix=india_vix,
                reason="insufficient bars to classify — defaulting to TRANSITION (ORB-only)",
            )

        # 2) Deterministic features
        lookback = settings.regime_lookback_bars
        win = bars.tail(lookback)
        adx = _adx(win, 14)
        rvol = _realized_vol_annualised(win)
        cur_vol, vol_pctile = _vol_percentile(bars, window_bars=12, lookback=lookback)
        day = _to_ist(bars.index)[-1].date()
        or_exp = _opening_range_expansion(bars, day)

        reading = RegimeReading(
            regime=Regime.TRANSITION, session_phase=phase, ref_symbol=self.ref_symbol,
            adx=_round(adx), realized_vol=_round(rvol, 4), vol_pctile=_round(vol_pctile, 3),
            or_expansion=_round(or_exp, 4), india_vix=india_vix,
            features={"cur_vol": cur_vol},
        )

        # 3) Decision ladder — order matters (most-protective first).
        # CRISIS: an explicit VIX reading dominates; otherwise realized-vol percentile.
        if india_vix is not None and india_vix >= settings.regime_vix_crisis:
            reading.regime = Regime.CRISIS
            reading.reason = (f"CRISIS: India VIX {india_vix:.1f} ≥ "
                              f"{settings.regime_vix_crisis} — capital preservation, arm nothing")
            return reading
        if np.isfinite(vol_pctile) and vol_pctile >= settings.regime_vol_crisis_pctile:
            reading.regime = Regime.CRISIS
            reading.reason = (f"CRISIS: realized-vol percentile {vol_pctile:.0%} ≥ "
                              f"{settings.regime_vol_crisis_pctile:.0%} (rvol {rvol:.1%}) — arm nothing")
            return reading

        # TREND vs RANGE vs TRANSITION via ADX bands.
        if np.isfinite(adx) and adx >= settings.regime_adx_trend:
            reading.regime = Regime.TREND
            reading.reason = (f"TREND: ADX {adx:.1f} ≥ {settings.regime_adx_trend} "
                              f"(rvol {rvol:.1%}, OR×ATR {or_exp:.2f}) — breakout/trend regime")
            return reading
        if np.isfinite(adx) and adx < settings.regime_adx_range:
            reading.regime = Regime.RANGE
            reading.reason = (f"RANGE: ADX {adx:.1f} < {settings.regime_adx_range} "
                              f"(rvol {rvol:.1%}) — mean-revert regime")
            return reading

        reading.regime = Regime.TRANSITION
        reading.reason = (f"TRANSITION: ADX {adx:.1f} between {settings.regime_adx_range}"
                          f"–{settings.regime_adx_trend} — ambiguous, ORB-only")
        return reading


def _round(x, n: int = 3):
    try:
        return round(float(x), n) if x is not None and np.isfinite(x) else None
    except (TypeError, ValueError):
        return None
