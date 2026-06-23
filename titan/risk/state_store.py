"""Durable risk state snapshot to Redis.

Persisted so dashboards / API can read live state, and so EOD flatten records
the closing PnL even if the supervisor restarts.

Keys are stamped with the trading date — anything stale is owned by yesterday
and must NOT be silently rehydrated into today's session.
"""
from __future__ import annotations

from datetime import date

from titan.risk.engine import RiskState


def persist_risk_state(state: RiskState, r, today: date) -> None:
    """Write a snapshot. Tagged with `today` so a date mismatch is detectable."""
    pipe = r.pipeline()
    pipe.set("titan:risk:date", today.isoformat())
    pipe.set("titan:risk:halted_today", "1" if state.halted_today else "0")
    pipe.set("titan:risk:halt_reason", state.halt_reason or "")
    pipe.set("titan:risk:consecutive_losses", str(state.consecutive_losses))
    pipe.set("titan:risk:realized_pnl_today", f"{state.realized_pnl_today:.4f}")
    pipe.set("titan:risk:current_equity", f"{state.current_equity:.4f}")
    pipe.set("titan:risk:open_positions", str(state.open_positions))
    pipe.execute()
