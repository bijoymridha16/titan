"""The factory must generate a large, valid set of vetting candidates, and every
one must honour the Strategy.on_bar contract (return a list of Signals, no raise)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from titan.strategies.base import Signal
from titan.strategies.factory import all_variants, variant_count
from titan.strategies.registry import BASE_STRATEGIES, KILLED_STRATEGIES, candidate_count

IST = ZoneInfo("Asia/Kolkata")


def _frame(n=300, seed=1):
    rng = np.random.default_rng(seed)
    close = 24000 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    idx = pd.DatetimeIndex([datetime(2026, 6, 12, 9, 15, tzinfo=IST) + timedelta(minutes=5 * i)
                            for i in range(n)])
    return pd.DataFrame({"o": close, "h": close * 1.001, "l": close * 0.999,
                         "c": close, "v": rng.integers(1000, 5000, n)}, index=idx)


def test_factory_generates_50_plus_variants():
    n = variant_count()
    assert n >= 50, f"expected 50+ vetting variants, got {n}"


def test_variant_keys_are_unique():
    keys = [v.key for v in all_variants()]
    assert len(keys) == len(set(keys))


def test_no_ma_cross_with_fast_ge_slow():
    for v in all_variants():
        if "fast" in v.params and "slow" in v.params:
            assert v.params["fast"] < v.params["slow"]


def test_every_variant_conforms_to_on_bar_contract():
    bars = _frame()
    for v in all_variants():
        strat = v.build("NIFTY")
        # feed the whole history once; must return a list[Signal] and never raise
        out = strat.on_bar(bars)
        assert isinstance(out, list)
        for s in out:
            assert isinstance(s, Signal)
            assert s.stop is not None and s.entry is not None


def test_variants_run_incrementally_without_error():
    # simulate the live loop: expanding window, several variants
    bars = _frame(seed=7)
    for v in all_variants()[:15]:
        strat = v.build("NIFTY")
        for i in range(60, len(bars), 20):
            strat.on_bar(bars.iloc[:i])  # must not raise


def test_registry_single_source_of_truth():
    assert "orb" in BASE_STRATEGIES
    assert "tsmom" in KILLED_STRATEGIES
    assert candidate_count() == variant_count()
