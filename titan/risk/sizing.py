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
    confidence: float = 1.0,
) -> int:
    """Risk a fixed fraction of equity per trade, scaled by signal confidence.

    qty = floor( (equity * risk_pct/100 * confidence) / |entry - stop| )
    then floored to a multiple of lot_size.

    `confidence` ∈ (0, 1] lets a strategy express conviction (e.g. TSMOM's
    inverse-vol scale) and have it actually affect size — see AUTOPSY_FINDINGS M3.
    It is clamped to [0.1, 1.0] so a low-confidence signal still trades a minimum
    sleeve rather than rounding to zero, and never upsizes beyond the risk budget.

    NOTE: this is the single position sizer. An ATR-based variant was removed as
    dead code (M4) — every strategy supplies an explicit stop, so risk-based
    fixed-fractional sizing on |entry-stop| already achieves ATR-equivalent
    sizing without a second code path.
    """
    if entry <= 0 or stop <= 0 or entry == stop:
        return 0
    conf = min(1.0, max(0.1, float(confidence)))
    risk_rupees = equity * (risk_pct / 100.0) * conf
    per_unit_risk = abs(entry - stop)
    raw = risk_rupees / per_unit_risk
    qty = int(math.floor(raw))
    qty -= qty % lot_size
    return max(qty, 0)
