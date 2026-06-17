"""Central strategy registry.

Single source of truth for:
  • the named, hand-written strategies the supervisor/auto-pilot can run live
    (orb, vwap_revert, supertrend_adx, tsmom), and
  • the killed set (blocked from activation), and
  • the full factory-generated vetting candidate set (50+ variants).

The supervisor imports BASE_STRATEGIES from here instead of hardcoding its dict,
so adding a strategy is a one-line registration. The vetting harness imports the
factory variants. The auto-pilot still only enables what's on the validated
allowlist — registration ≠ permission to trade.
"""
from __future__ import annotations

from typing import Type

from titan.strategies.base import Strategy
from titan.strategies.factory import VariantSpec, all_variants
from titan.strategies.orb import OpeningRangeBreakout
from titan.strategies.supertrend_adx import SupertrendADX
from titan.strategies.tsmom import TSMOM
from titan.strategies.vwap_revert import VWAPRevert

# Named live-capable strategies (what the supervisor can instantiate by name).
BASE_STRATEGIES: dict[str, Type[Strategy]] = {
    "orb": OpeningRangeBreakout,
    "vwap_revert": VWAPRevert,
    "supertrend_adx": SupertrendADX,
    "tsmom": TSMOM,
}

# Killed by walk-forward — blocked at the API and never auto-armed.
KILLED_STRATEGIES: set[str] = {"tsmom"}


def vetting_candidates() -> list[VariantSpec]:
    """All factory variants to run through the pre-live walk-forward harness."""
    return all_variants()


def candidate_count() -> int:
    return len(vetting_candidates())
