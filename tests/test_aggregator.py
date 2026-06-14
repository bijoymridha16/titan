from datetime import datetime, timezone

from titan.data.aggregator import Tick, aggregate


def t(h, m, s, p, v=1):
    return Tick(datetime(2026, 6, 12, h, m, s, tzinfo=timezone.utc), p, v)


def test_aggregates_to_1m_bars_with_ohlc():
    ticks = [
        t(9, 15, 0, 100),
        t(9, 15, 30, 102),
        t(9, 15, 45, 99),
        t(9, 16, 0, 101),     # crosses bucket → closes prior bar
        t(9, 16, 30, 103),
        t(9, 17, 0, 104),     # closes the 9:16 bar
    ]
    bars = list(aggregate(ticks, "1m"))
    assert len(bars) == 2
    assert bars[0].o == 100 and bars[0].h == 102 and bars[0].l == 99 and bars[0].c == 99
    assert bars[1].o == 101 and bars[1].c == 103


def test_aggregates_volume():
    ticks = [t(9, 15, 0, 100, 5), t(9, 15, 30, 101, 7), t(9, 16, 0, 102, 1)]
    bars = list(aggregate(ticks, "1m"))
    assert bars[0].v == 12


def test_5m_bucketing():
    ticks = [t(9, 15, 0, 100), t(9, 19, 59, 105), t(9, 20, 0, 106)]
    bars = list(aggregate(ticks, "5m"))
    assert len(bars) == 1
    assert bars[0].o == 100 and bars[0].h == 105 and bars[0].c == 105


def test_open_bar_not_yielded():
    ticks = [t(9, 15, 0, 100), t(9, 15, 30, 101)]
    bars = list(aggregate(ticks, "1m"))
    assert bars == []  # never crossed into 9:16, stays open
