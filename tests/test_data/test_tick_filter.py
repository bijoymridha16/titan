"""Tick sanitizer — rejects corrupted quotes (manifesto Scenario A)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from titan.data.tick_filter import TickSanitizer


def _ts(i: int) -> datetime:
    return datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc) + timedelta(seconds=i)


def test_warmup_accepts_everything():
    san = TickSanitizer(n_sigma=4.0, window_s=300, min_samples=20)
    # even a wild value is accepted before the window is warm
    assert san.accept(_ts(0), 100.0) is True
    assert san.accept(_ts(1), 1_000_000.0) is True


def test_rejects_obvious_outlier_after_warmup():
    san = TickSanitizer(n_sigma=4.0, window_s=300, min_samples=20)
    for i in range(30):
        assert san.accept(_ts(i), 100.0 + (i % 2) * 0.1) is True   # ~100, tiny spread
    # a 100x spike must be rejected
    assert san.accept(_ts(40), 10_000.0) is False


def test_outlier_does_not_poison_window():
    san = TickSanitizer(n_sigma=4.0, window_s=300, min_samples=20)
    for i in range(30):
        san.accept(_ts(i), 100.0 + (i % 2) * 0.1)
    san.accept(_ts(40), 10_000.0)            # rejected
    # a normal tick right after is still accepted (ref wasn't dragged up)
    assert san.accept(_ts(41), 100.05) is True


def test_normal_drift_accepted():
    san = TickSanitizer(n_sigma=4.0, window_s=300, min_samples=20)
    price = 100.0
    for i in range(60):
        price += 0.05                         # steady trend
        assert san.accept(_ts(i), price) is True


def test_window_prunes_old_ticks():
    # max_ts_drift_s set wide so this isolates window-pruning from the ts guard.
    san = TickSanitizer(n_sigma=4.0, window_s=10, min_samples=5, max_ts_drift_s=10_000)
    for i in range(5):
        san.accept(_ts(i), 100.0)
    # 60s later the old ticks are pruned → back to warm-up → accept-all
    assert san.accept(_ts(100), 5_000.0) is True


def test_rejects_far_future_timestamp_corruption():
    # regression: a corrupt tick dated far ahead must NOT prune the window and
    # warm-up-accept its bad price (live finding 2026-06-20).
    san = TickSanitizer(n_sigma=4.0, window_s=300, min_samples=20)
    for i in range(30):
        san.accept(_ts(i), 100.0 + (i % 2) * 0.1)
    # tick dated 13 min ahead with an absurd price → rejected on the ts guard
    assert san.accept(_ts(30 + 13 * 60), 999_999.0) is False
    # normal progression still accepted
    assert san.accept(_ts(31), 100.05) is True


def test_rejects_far_past_timestamp_replay():
    san = TickSanitizer(n_sigma=4.0, window_s=300, min_samples=20)
    for i in range(30):
        san.accept(_ts(100 + i), 100.0)
    # replayed/stale tick from 10 min before the latest seen → rejected
    assert san.accept(_ts(100 + 29 - 600), 100.0) is False


def test_legit_forward_progress_within_drift_ok():
    san = TickSanitizer(n_sigma=4.0, window_s=300, min_samples=5)
    # ticks 60s apart (within 300s drift) advance fine
    price = 100.0
    for i in range(20):
        assert san.accept(_ts(i * 60), price + i * 0.01) is True


def test_volume_weighted_reference_used():
    # heavy volume concentrated near 200 pulls the vwap up, so 200 is normal
    san = TickSanitizer(n_sigma=3.0, window_s=300, min_samples=5)
    for i in range(5):
        san.accept(_ts(i), 100.0, volume=1)
    for i in range(5, 25):
        san.accept(_ts(i), 200.0, volume=1000)
    assert san.accept(_ts(30), 200.0, volume=10) is True
