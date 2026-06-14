"""Entity → NSE ticker resolver.

Three-pass match against config/nifty50_aliases.yaml:

  1. EXACT     — raw_symbol from the source matches a ticker         conf 1.00
  2. ALIAS     — any alias appears as a whole-word substring in
                 the headline                                         conf 0.85
  3. FUZZY     — rapidfuzz best partial-ratio match to either the
                 ticker or the company name, threshold ≥ 70           conf = ratio/100

Multi-symbol headlines (e.g. "Reliance and ITC report Q1 results") yield
one EntityMatch per resolved ticker. Confidence below 0.70 is dropped.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz

log = logging.getLogger(__name__)

ALIASES_PATH = Path(__file__).resolve().parents[2] / "config" / "nifty50_aliases.yaml"
MIN_CONF = 0.70


@dataclass
class EntityMatch:
    ticker: str
    matched_alias: str
    confidence: float
    method: str           # "exact" | "alias" | "fuzzy"


@lru_cache(maxsize=1)
def _load_aliases() -> dict[str, dict]:
    with ALIASES_PATH.open() as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def _alias_index() -> list[tuple[str, str]]:
    """Flat list of (alias_lower, ticker), longest-first so multi-word names
    win over substring collisions."""
    out: list[tuple[str, str]] = []
    for ticker, meta in _load_aliases().items():
        out.append((ticker.lower(), ticker))
        out.append((meta["name"].lower(), ticker))
        for a in meta.get("aliases", []):
            out.append((str(a).lower(), ticker))
    out.sort(key=lambda kv: len(kv[0]), reverse=True)
    return out


def _whole_word(needle: str, haystack: str) -> bool:
    # numeric BSE scrip codes can collide with years etc. — require word boundary.
    pat = r"(?<![A-Za-z0-9])" + re.escape(needle) + r"(?![A-Za-z0-9])"
    return re.search(pat, haystack, flags=re.IGNORECASE) is not None


def resolve(raw_symbol: Optional[str], headline: str,
            body: Optional[str] = None) -> list[EntityMatch]:
    aliases = _load_aliases()
    text = f"{headline} {body or ''}"

    # 1) EXACT — raw_symbol is the source-supplied ticker.
    if raw_symbol:
        rs = raw_symbol.strip().upper()
        if rs in aliases:
            return [EntityMatch(rs, rs, 1.00, "exact")]

    # 2) ALIAS — scan whole-word substrings.
    found: dict[str, EntityMatch] = {}
    for alias_low, ticker in _alias_index():
        if len(alias_low) < 2:
            continue
        if _whole_word(alias_low, text):
            # keep the first (longest) match per ticker
            found.setdefault(ticker, EntityMatch(ticker, alias_low, 0.85, "alias"))
    if found:
        return list(found.values())

    # 3) FUZZY — best partial ratio over the company-name column only.
    best_ticker: Optional[str] = None
    best_score = 0
    best_alias = ""
    for ticker, meta in aliases.items():
        score = fuzz.partial_ratio(meta["name"].lower(), text.lower())
        if score > best_score:
            best_score = score
            best_ticker = ticker
            best_alias = meta["name"]
    # Fuzzy threshold deliberately tight (85) — anything looser produces
    # false positives like "Titan Company" matching random text.
    if best_ticker and best_score >= 85:
        return [EntityMatch(best_ticker, best_alias, round(best_score / 100, 2), "fuzzy")]
    return []
