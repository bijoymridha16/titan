"""Opening Range Breakout.

Definition (intraday, NSE):
  - Opening range = first `or_minutes` of the session (default 15m, 09:15–09:30 IST).
  - LONG entry  : first close > OR_high after the range closes.
  - SHORT entry : first close < OR_low after the range closes.
  - Stop        : opposite side of the OR.
  - Target      : `target_r * range_size` (default 1.5R).
  - One trade per side per day. No re-entry after stop hit.
  - No new entries after 14:30 IST (avoid late-session chop / square-off rush).

Per the research doc, ORB is the only intraday entry mechanism with
peer-reviewed evidence (Zarattini & Aziz, SSRN 4729284) — but applied to US
equities. Indian-market numbers in vendor blogs are encouraging but not
peer-reviewed. Treat as a candidate, not a known edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from titan.strategies.base import Signal, SignalKind, Strategy

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class ORBState:
    or_high: Optional[float] = None
    or_low: Optional[float] = None
    long_taken: bool = False
    short_taken: bool = False
    range_ready: bool = False
    last_day: Optional[object] = None


class OpeningRangeBreakout(Strategy):
    name = "orb"
    timeframe = "5m"

    DEFAULTS = {"or_minutes": 15, "target_r": 1.5, "cutoff": "14:30",
                "session_open": "09:15"}

    def __init__(self, symbol: str, params: Optional[dict] = None):
        super().__init__(symbol, {**self.DEFAULTS, **(params or {})})
        self._state = ORBState()

    def _reset_for_day(self, day) -> None:
        self._state = ORBState(last_day=day)

    @staticmethod
    def _to_ist(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
        if idx.tz is None:
            # naive — assume UTC (matches our Postgres ohlcv writes)
            return idx.tz_localize("UTC").tz_convert(IST)
        return idx.tz_convert(IST)

    def on_bar(self, bars: pd.DataFrame) -> list[Signal]:
        if bars.empty:
            return []
        # NSE session times are IST. Bars may arrive with naive, UTC, or IST
        # timestamps depending on the source — always convert to IST before
        # comparing against session boundaries.
        idx_ist = self._to_ist(bars.index)
        ts_ist = idx_ist[-1]
        last = bars.iloc[-1]
        day = ts_ist.date()
        if self._state.last_day != day:
            self._reset_for_day(day)

        open_t = time.fromisoformat(self.params["session_open"])
        cutoff = time.fromisoformat(self.params["cutoff"])
        or_end_minute = open_t.minute + self.params["or_minutes"]
        or_end = time(open_t.hour + or_end_minute // 60, or_end_minute % 60)

        bar_t = ts_ist.time()
        # rows for today (in IST)
        today_mask = idx_ist.date == day        # type: ignore[attr-defined]
        today = bars[today_mask]
        today_idx_ist = idx_ist[today_mask]

        # Before market open: don't trade
        if bar_t < open_t:
            return []

        # Build the OR while inside the opening window
        if bar_t < or_end:
            self._state.or_high = float(today["h"].max())
            self._state.or_low = float(today["l"].min())
            return []

        # First bar AT/AFTER or_end finalizes the range
        if not self._state.range_ready:
            opening_mask = today_idx_ist.time < or_end   # type: ignore[attr-defined]
            opening = today[opening_mask]
            if opening.empty:
                return []
            self._state.or_high = float(opening["h"].max())
            self._state.or_low = float(opening["l"].min())
            self._state.range_ready = True

        if bar_t >= cutoff:
            return []

        hi, lo = self._state.or_high, self._state.or_low
        if hi is None or lo is None or hi <= lo:
            return []
        rng = hi - lo
        tgt_r = float(self.params["target_r"])

        signals: list[Signal] = []
        if not self._state.long_taken and float(last["c"]) > hi:
            signals.append(Signal(
                ts=ts_ist, symbol=self.symbol, kind=SignalKind.ENTRY_LONG,
                entry=float(last["c"]), stop=lo,
                target=float(last["c"]) + tgt_r * rng,
                reason=f"ORB long: close>{hi:.2f}",
            ))
            self._state.long_taken = True
        elif not self._state.short_taken and float(last["c"]) < lo:
            signals.append(Signal(
                ts=ts_ist, symbol=self.symbol, kind=SignalKind.ENTRY_SHORT,
                entry=float(last["c"]), stop=hi,
                target=float(last["c"]) - tgt_r * rng,
                reason=f"ORB short: close<{lo:.2f}",
            ))
            self._state.short_taken = True
        return signals
