"""Daily risk-state snapshot persistence.

The supervisor calls persist_risk_state(...) after each trade close so the
current day's risk counters (realized PnL, drawdown, consecutive losses, halt
status) are inspectable and survive a same-day restart. Best-effort telemetry —
it must never raise into the trading loop.

(This module backs the import in supervisor.py; main referenced it but the file
was not committed there — supplied here so the merged tree runs.)
"""
from __future__ import annotations

from datetime import date as _date


def persist_risk_state(state, redis_client, day: _date) -> None:
    """Write a snapshot of `state` to a per-day Redis hash. Never raises."""
    try:
        key = f"titan:risk:state:{day.isoformat()}"
        redis_client.hset(key, mapping={
            "realized_pnl_today": f"{getattr(state, 'realized_pnl_today', 0.0):.2f}",
            "realized_pnl_week": f"{getattr(state, 'realized_pnl_week', 0.0):.2f}",
            "current_equity": f"{getattr(state, 'current_equity', 0.0):.2f}",
            "peak_equity": f"{getattr(state, 'peak_equity', 0.0):.2f}",
            "drawdown_inr": f"{getattr(state, 'drawdown_inr', 0.0):.2f}",
            "open_positions": str(getattr(state, "open_positions", 0)),
            "consecutive_losses": str(getattr(state, "consecutive_losses", 0)),
            "halted_today": "1" if getattr(state, "halted_today", False) else "0",
            "halt_reason": getattr(state, "halt_reason", None) or "",
        })
        redis_client.expire(key, 7 * 24 * 3600)   # keep a week
        redis_client.set("titan:risk:state:latest", key)
    except Exception:
        pass
