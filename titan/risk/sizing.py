"""Position sizing primitives.

All functions return integer quantity (lots * lot_size for derivatives).
They never round up — undersizing is safer than oversizing.
"""
from __future__ import annotations

import math


def fixed_fractional_qty(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    lot_size: int = 1,
) -> int:
    """Risk a fixed fraction of equity per trade.

    qty = floor( (equity * risk_pct/100) / |entry - stop| )
    Then floor to a multiple of lot_size.
    """
    if entry <= 0 or stop <= 0 or entry == stop:
        return 0
    risk_rupees = equity * (risk_pct / 100.0)
    per_unit_risk = abs(entry - stop)
    raw = risk_rupees / per_unit_risk
    qty = int(math.floor(raw))
    qty -= qty % lot_size
    return max(qty, 0)


def atr_position_size(
    equity: float,
    risk_pct: float,
    atr: float,
    atr_multiple: float = 1.5,
    lot_size: int = 1,
) -> int:
    """ATR-based: stop is `atr_multiple * ATR` away from entry."""
    if atr <= 0:
        return 0
    per_unit_risk = atr * atr_multiple
    risk_rupees = equity * (risk_pct / 100.0)
    qty = int(math.floor(risk_rupees / per_unit_risk))
    qty -= qty % lot_size
    return max(qty, 0)
