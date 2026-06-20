"""Per-symbol tick sanitizer — rejects corrupted quotes before aggregation.

Manifesto Scenario A: the Angel One WS sometimes transmits corrupted quote data
(absurd highs/lows) that, if aggregated, poison the OHLCV series and can fake a
volatility spike that flips the regime classifier into CRISIS. This guard keeps
a trailing window of recent ticks per symbol and rejects any whose price is more
than `n_sigma` standard deviations from the trailing volume-weighted price.

Design notes:
- Stateful but self-contained (no Redis/DB) so it is trivially unit-tested.
- Warm-up: until the window holds `min_samples` ticks we cannot estimate a
  meaningful spread, so everything is accepted (fail-open — never block a real
  feed on startup).
- Volume-weighted reference when volume is present; falls back to the simple
  mean when all volumes are zero (e.g. REST-bridge ticks carry no volume).
- An outlier does NOT enter the window — otherwise a burst of corrupt ticks
  would drag the reference toward the garbage and start accepting it.
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime


class TickSanitizer:
    def __init__(self, n_sigma: float = 4.0, window_s: int = 300,
                 min_samples: int = 20):
        self.n_sigma = n_sigma
        self.window_s = window_s
        self.min_samples = min_samples
        self._buf: deque[tuple[float, float, float]] = deque()  # (epoch, price, volume)

    def _prune(self, now_epoch: float) -> None:
        cutoff = now_epoch - self.window_s
        while self._buf and self._buf[0][0] < cutoff:
            self._buf.popleft()

    def _reference(self) -> tuple[float, float]:
        """(vwap-or-mean, stdev) over the current window."""
        prices = [p for _, p, _ in self._buf]
        vols = [v for _, _, v in self._buf]
        n = len(prices)
        mean = sum(prices) / n
        tot_v = sum(vols)
        ref = (sum(p * v for p, v in zip(prices, vols)) / tot_v) if tot_v > 0 else mean
        var = sum((p - mean) ** 2 for p in prices) / n
        return ref, math.sqrt(var)

    def accept(self, ts: datetime, price: float, volume: float = 0.0) -> bool:
        """Return True if the tick is plausible (and record it); False to reject.

        Rejected ticks are NOT added to the window.
        """
        epoch = ts.timestamp()
        self._prune(epoch)

        if len(self._buf) < self.min_samples:
            self._buf.append((epoch, price, volume))   # warm-up: accept + learn
            return True

        ref, std = self._reference()
        if std > 0 and abs(price - ref) > self.n_sigma * std:
            return False   # outlier — drop, do not poison the window

        self._buf.append((epoch, price, volume))
        return True
