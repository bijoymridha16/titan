"""Shared, dependency-free technical indicators (pandas/numpy only).

One implementation per indicator so every strategy family computes them the same
way. All return pandas Series aligned to the input index; insufficient history
yields NaN at the head (callers guard on length). No look-ahead: every value at
bar i uses only bars ≤ i.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.astype(float).ewm(span=period, adjust=False).mean()


def sma(s: pd.Series, period: int) -> pd.Series:
    return s.astype(float).rolling(period).mean()


def roc(s: pd.Series, period: int) -> pd.Series:
    """Rate of change (fractional) over `period` bars."""
    s = s.astype(float)
    return s / s.shift(period) - 1.0


def true_range(bars: pd.DataFrame) -> pd.Series:
    h, l, c = bars["h"].astype(float), bars["l"].astype(float), bars["c"].astype(float)
    return pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)


def atr(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(bars).rolling(period).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    s = s.astype(float)
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def bollinger(s: pd.Series, period: int = 20, k: float = 2.0):
    """Return (mid, upper, lower) bands."""
    s = s.astype(float)
    mid = s.rolling(period).mean()
    sd = s.rolling(period).std()
    return mid, mid + k * sd, mid - k * sd


def donchian(bars: pd.DataFrame, period: int = 20):
    """Return (upper, lower) channel using bars STRICTLY BEFORE the current one
    (shifted) so a breakout of the prior channel is detectable on the current bar
    without look-ahead."""
    hi = bars["h"].astype(float).rolling(period).max().shift(1)
    lo = bars["l"].astype(float).rolling(period).min().shift(1)
    return hi, lo


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, signal_line, histogram)."""
    s = s.astype(float)
    line = ema(s, fast) - ema(s, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def stoch_rsi(s: pd.Series, rsi_period: int = 14, stoch_period: int = 14,
              k: int = 3, d: int = 3):
    """Stochastic RSI → (%K, %D), 0..100. Stochastic oscillator applied to RSI."""
    r = rsi(s, rsi_period)
    lo = r.rolling(stoch_period).min()
    hi = r.rolling(stoch_period).max()
    sr = 100 * (r - lo) / (hi - lo).replace(0, np.nan)
    kk = sr.rolling(k).mean()
    dd = kk.rolling(d).mean()
    return kk, dd


def adx(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder) — trend-strength, 0..100."""
    h, l = bars["h"].astype(float), bars["l"].astype(float)
    up, dn = h.diff(), -l.diff()
    plus_dm = ((up > dn) & (up > 0)) * up
    minus_dm = ((dn > up) & (dn > 0)) * dn
    a = atr(bars, period)
    plus_di = 100 * (plus_dm.rolling(period).mean() / a)
    minus_di = 100 * (minus_dm.rolling(period).mean() / a)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean()


def supertrend(bars: pd.DataFrame, period: int = 10, mult: float = 3.0):
    """Return (line, direction) where direction is +1 (up) / -1 (down).
    Volatility-adjusted trailing stop on hl2 ± mult·ATR."""
    h, l, c = bars["h"].astype(float), bars["l"].astype(float), bars["c"].astype(float)
    hl2 = (h + l) / 2.0
    a = atr(bars, period)
    upper, lower = hl2 + mult * a, hl2 - mult * a
    line = pd.Series(index=bars.index, dtype=float)
    direction = pd.Series(index=bars.index, dtype=float)
    prev_line, prev_dir = None, -1
    for i in range(len(bars)):
        if prev_line is None or not np.isfinite(a.iloc[i]):
            line.iloc[i] = upper.iloc[i]; direction.iloc[i] = -1
            prev_line, prev_dir = line.iloc[i], -1
            continue
        if prev_dir == -1:
            ln = min(upper.iloc[i], prev_line)
            d = 1 if c.iloc[i] > ln else -1
            if d == 1:
                ln = lower.iloc[i]
        else:
            ln = max(lower.iloc[i], prev_line)
            d = -1 if c.iloc[i] < ln else 1
            if d == -1:
                ln = upper.iloc[i]
        line.iloc[i], direction.iloc[i] = ln, d
        prev_line, prev_dir = ln, d
    return line, direction
