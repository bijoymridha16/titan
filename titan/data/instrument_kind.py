"""Resolve an underlying signal to the instrument we actually trade (D1).

Strategies are written against the underlying (NIFTY, SENSEX, RELIANCE…). The
execution instrument is configurable (settings.instrument_kind); default ETF.
This module maps underlying → tradable tradingsymbol using config/instrument_map.yaml.

ETF and EQUITY are live-wireable (NSE cash). OPTION returns the option root for a
future router (strike/expiry selection not implemented). INDEX is paper-only.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from titan.config import settings

log = logging.getLogger(__name__)
_MAP_FILE = Path(__file__).resolve().parents[2] / "config" / "instrument_map.yaml"


@lru_cache(maxsize=1)
def _map() -> dict:
    try:
        import yaml
        return yaml.safe_load(_MAP_FILE.read_text()) or {}
    except Exception as e:
        log.warning("instrument_map load failed (%s) — passthrough", e)
        return {}


def tradable_symbol(underlying: str, kind: str | None = None) -> str:
    """Underlying → execution tradingsymbol for the configured instrument kind.
    Falls back to the underlying itself if no mapping exists (single-name equities)."""
    kind = (kind or settings.instrument_kind).upper()
    m = _map()
    if kind == "ETF":
        return m.get("etf", {}).get(underlying, underlying)
    if kind == "OPTION":
        return m.get("option_root", {}).get(underlying, underlying)
    # EQUITY / INDEX → trade/paper the symbol as-is
    return underlying


def is_directly_tradable(kind: str | None = None) -> bool:
    """INDEX can only be paper-traded (no directly tradable instrument)."""
    return (kind or settings.instrument_kind).upper() != "INDEX"
