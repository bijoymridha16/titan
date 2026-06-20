"""Walk-forward gate logic — the multiple-testing correction must get STRICTER
with more trials and with less data (the whole point of the safeguard)."""
from __future__ import annotations

import math

from titan.backtest.walk_forward import deflated_sharpe_threshold


def test_threshold_rises_with_more_trials():
    # more strategies tested → higher bar to clear (best-of-N fluke is larger)
    t_few = deflated_sharpe_threshold(n_trials=2, n_obs=500)
    t_many = deflated_sharpe_threshold(n_trials=200, n_obs=500)
    assert t_many > t_few > 0


def test_threshold_rises_with_less_data():
    # fewer observations → noisier Sharpe → higher bar
    t_lots = deflated_sharpe_threshold(n_trials=59, n_obs=2000)
    t_few = deflated_sharpe_threshold(n_trials=59, n_obs=100)
    assert t_few > t_lots


def test_threshold_infinite_when_no_data():
    assert deflated_sharpe_threshold(n_trials=59, n_obs=3) == math.inf


def test_threshold_is_finite_and_positive_for_normal_inputs():
    t = deflated_sharpe_threshold(n_trials=59, n_obs=500)
    assert 0 < t < 10
