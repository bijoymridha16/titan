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
