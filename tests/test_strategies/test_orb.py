from datetime import datetime, timedelta

import pandas as pd

from titan.strategies.base import SignalKind
from titan.strategies.orb import IST, OpeningRangeBreakout


def _bar_index(start: datetime, n: int, freq_min: int = 5) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        [start + timedelta(minutes=freq_min * i) for i in range(n)], tz=IST,
    )


def make_bars(prices: list[tuple[float, float, float, float]],
              start=datetime(2026, 6, 12, 9, 15)) -> pd.DataFrame:
    idx = _bar_index(start, len(prices))
    return pd.DataFrame(prices, columns=["o", "h", "l", "c"], index=idx).assign(v=1)


def test_long_breakout_signal_after_or():
    # OR is 9:15–9:30, two 5m bars (9:15 and 9:20 windows; OR ends at 9:30)
    # Use 5m bars: bars at 9:15, 9:20 = inside OR; 9:25 finalizes; 9:30 close > OR_high should fire
    bars = make_bars([
        (100, 102, 99,  101),   # 9:15
        (101, 103, 100, 102),   # 9:20
        (102, 104, 101, 103),   # 9:25  → still pre-OR-end? OR end = 9:30
        (103, 110, 103, 109),   # 9:30  → first bar at/after OR end, breakout long
    ])
    s = OpeningRangeBreakout("NIFTY", {"or_minutes": 15})
    sigs = []
    for i in range(1, len(bars) + 1):
        sigs.extend(s.on_bar(bars.iloc[:i]))
    longs = [x for x in sigs if x.kind == SignalKind.ENTRY_LONG]
    assert len(longs) == 1
    assert longs[0].entry == 109
    assert longs[0].stop == 99  # OR low


def test_no_second_long_after_first():
    bars = make_bars([
        (100, 102, 99, 101),
        (101, 103, 100, 102),
        (102, 104, 101, 103),
        (103, 110, 103, 109),
        (109, 112, 108, 111),  # would breakout again but already taken
    ])
    s = OpeningRangeBreakout("NIFTY", {"or_minutes": 15})
    sigs = []
    for i in range(1, len(bars) + 1):
        sigs.extend(s.on_bar(bars.iloc[:i]))
    assert len([x for x in sigs if x.kind == SignalKind.ENTRY_LONG]) == 1


def test_short_breakout_signal():
    bars = make_bars([
        (100, 102, 99, 101),
        (101, 103, 100, 102),
        (102, 104, 101, 103),
        (103, 103, 95, 96),  # 9:30 close < OR_low (99) → short
    ])
    s = OpeningRangeBreakout("NIFTY", {"or_minutes": 15})
    sigs = []
    for i in range(1, len(bars) + 1):
        sigs.extend(s.on_bar(bars.iloc[:i]))
    shorts = [x for x in sigs if x.kind == SignalKind.ENTRY_SHORT]
    assert len(shorts) == 1
    assert shorts[0].stop == 104  # OR_high


def test_no_signal_inside_opening_range():
    bars = make_bars([(100, 105, 99, 104)])
    s = OpeningRangeBreakout("NIFTY", {"or_minutes": 15})
    assert s.on_bar(bars) == []


def test_cutoff_blocks_late_entries():
    # bars from 14:30 onward shouldn't generate entries (cutoff)
    bars = make_bars([
        (100, 102, 99, 101),
        (101, 103, 100, 102),
        (102, 104, 101, 103),
    ], start=datetime(2026, 6, 12, 9, 15))
    # then a late bar at 14:35 with extreme close
    late_idx = pd.DatetimeIndex(list(bars.index) + [datetime(2026, 6, 12, 14, 35)], tz=IST)
    bars2 = pd.DataFrame(
        list(bars[["o", "h", "l", "c"]].itertuples(index=False, name=None)) +
        [(103, 200, 103, 199)],
        columns=["o", "h", "l", "c"], index=late_idx).assign(v=1)
    s = OpeningRangeBreakout("NIFTY", {"or_minutes": 15, "cutoff": "14:30"})
    sigs = []
    for i in range(1, len(bars2) + 1):
        sigs.extend(s.on_bar(bars2.iloc[:i]))
    assert sigs == []
