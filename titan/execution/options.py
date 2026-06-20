"""Options routing helpers — map an underlying signal to a tradable contract.

Manifesto Multiplier 1 / Scenario C: at ₹5K the ETF path bleeds capital to
slippage on illiquid ETFs. The pivot trades liquid weekly index options sized to
the 2026 lot sizes. Strategies keep signalling on the UNDERLYING; this layer
resolves the concrete option contract (ATM strike, weekly expiry, CE/PE), sizes
in whole lots, and (optionally) builds a midpoint limit order to nullify
negative slippage.

The pure helpers here are fully unit-tested. The DB-backed contract lookup
(`resolve_option_contract`) reads the Angel instruments master and is guarded.
NOTE: nothing here enables LIVE trading — that stays gated by live_enabled /
live_dry_run in the broker.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from titan.brokers.base import OrderSide
from titan.config import settings

log = logging.getLogger(__name__)


def lot_size_for(underlying: str, default: int = 1) -> int:
    return settings.lot_size_map.get(underlying.upper(), default)


def strike_step_for(underlying: str, default: float = 50.0) -> float:
    return settings.strike_step_map.get(underlying.upper(), default)


def nearest_strike(spot: float, step: float) -> int:
    """Round spot to the nearest strike step (e.g. 24 537 @ step 50 → 24 550)."""
    if step <= 0:
        return int(round(spot))
    return int(round(spot / step) * step)


def atm_strike(underlying: str, spot: float, offset_steps: int = 0) -> int:
    """ATM strike (±offset_steps strikes OTM, signed by convention at call site)."""
    step = strike_step_for(underlying)
    return nearest_strike(spot, step) + int(offset_steps * step)


def option_type_for(side: OrderSide) -> str:
    """Long underlying → CE (call); short underlying → PE (put)."""
    return "CE" if side == OrderSide.BUY else "PE"


def weekly_expiry(today: date, weekday: int) -> date:
    """Next occurrence of `weekday` (Mon=0…Sun=6) on/after today."""
    days_ahead = (weekday - today.weekday()) % 7
    return today + timedelta(days=days_ahead)


def midpoint(bid: float | None, ask: float | None, fallback: float) -> float:
    """Bid-ask midpoint; falls back to `fallback` (e.g. LTP) when depth absent."""
    if bid and ask and bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 2)
    return fallback


def lots_to_qty(lots: int, lot_size: int) -> int:
    return max(1, lots) * max(1, lot_size)


def fits_margin(required: float, available: float, buffer_pct: float) -> bool:
    """True if `required` margin fits within `available` after a safety buffer."""
    return required <= available * (1.0 - buffer_pct / 100.0)


def resolve_option_contract(underlying: str, spot: float, side: OrderSide,
                            today: date, offset_steps: int | None = None) -> dict | None:
    """Look up the concrete weekly ATM option in the instruments master.

    Returns the instrument dict (token, symbol, lotsize, strike, expiry…) or
    None if it can't be resolved. Best-effort — never raises into the caller.
    """
    from titan.data.instrument_kind import tradable_symbol
    from titan.data.instruments import lookup

    root = tradable_symbol(underlying, "OPTION")
    off = settings.option_offset_steps if offset_steps is None else offset_steps
    strike = atm_strike(underlying, spot, off)
    opt_type = option_type_for(side)
    expiry = weekly_expiry(today, settings.option_expiry_weekday)
    itype = "OPTIDX" if underlying.upper() in settings.lot_size_map else "OPTSTK"
    try:
        inst = lookup(root, settings.option_exchange, instrumenttype=itype,
                      expiry=expiry, strike=float(strike))
    except Exception as e:
        log.warning("option lookup failed for %s %s %s @%s: %s",
                    root, expiry, strike, opt_type, e)
        return None
    if not inst:
        log.warning("no option contract found: %s %s %d %s (exp %s)",
                    root, settings.option_exchange, strike, opt_type, expiry)
    return inst
