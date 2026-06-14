"""VectorBT runner — for fast parameter sweeps. NOT authoritative.

Use bt_runner for any decision that approaches real capital. VectorBT's
vectorized fills do not respect risk-engine state machines (daily caps,
consecutive losses, kill switch) — sweeps are only for finding plausible
parameter neighborhoods to then validate event-driven.
"""
from __future__ import annotations

import pandas as pd


def sweep_orb(bars: pd.DataFrame, or_minutes_grid=(5, 15, 30), target_r_grid=(1.0, 1.5, 2.0)):
    """Returns a DataFrame of (or_minutes, target_r) → coarse stats.
    Intentionally a placeholder; wire vectorbt.Portfolio.from_signals once
    a real free-data source is plumbed in."""
    raise NotImplementedError(
        "Plumb your bars source first, then implement vbt.Portfolio.from_signals "
        "with per-day OR computation. Do not trust raw VBT P&L until matched against bt_runner."
    )
