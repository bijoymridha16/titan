"""Headline category classifier — rules-based.

We deliberately avoid ML here: we have zero labelled headlines, and a 5-class
text classifier trained on weak labels would just overfit. Regex/keyword
rules are transparent, easy to audit, and easy for the user to tune by
editing one YAML.

Categories (priority-ordered — first match wins):

  1. block_deal     — block/bulk/large trades. Noise list — never fires.
  2. earnings       — quarterly results, profit, revenue, EBITDA, beat/miss.
  3. m_and_a        — acquisitions, mergers, takeovers, stake purchases.
  4. regulatory     — SEBI/RBI/CCI penalties, fines, raids, bans.
  5. dividend       — dividend / bonus / buyback / record date.
  6. generic_noise  — AGM, board outcome boilerplate. Never fires.
  7. other          — everything else.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

NOISE_PATH = Path(__file__).resolve().parents[2] / "config" / "news_noise_filters.yaml"

CATEGORIES = ("block_deal", "earnings", "m_and_a", "regulatory",
              "dividend", "generic_noise", "other")
NEVER_FIRE = {"block_deal", "generic_noise", "other"}

EARNINGS_PATTERNS = [
    r"\bq[1-4]\s*(?:fy\d*|results?)\b",
    r"\b(quarterly results?|annual results?)\b",
    r"\b(profit|net profit|pat|loss|net loss)\s+(?:up|down|rose|fell|jump|surged|slumps?)",
    r"\b(revenue|topline|ebitda|operating margin|gross margin)\b",
    r"\b(beat|miss|missed|misses|beats?)\s+(?:estimates?|consensus|street)",
    r"\b(eps|earnings per share)\b",
    r"\b(guidance|outlook|raises?|cuts?)\s+(?:fy|guidance|outlook)",
]
M_AND_A_PATTERNS = [
    r"\bacquir(?:e|es|ed|ing|sition)\b",
    r"\b(merger|takeover|amalgamation|demerger)\b",
    r"\bstake (?:purchase|acquisition|sale)\b",
    r"\b(buyout|controlling stake|majority stake)\b",
    r"\bto buy\b.*\b(stake|equity|shares)\b",
]
REGULATORY_PATTERNS = [
    r"\bsebi\b.*\b(penalty|fine|ban|order|notice|imposes?|crackdown)\b",
    r"\b(rbi|reserve bank).*\b(action|fine|penalty|directive|cease and desist)\b",
    r"\bcci\b.*\b(approval|order|investigation|raid)\b",
    r"\b(ed|enforcement directorate|cbi|sfio|incomex tax)\b.*\b(raid|probe|investigation)\b",
    r"\b(suspend(?:s|ed)?|bans?)\s+trading\b",
    r"\bdebar(?:s|red)?\b",
]
DIVIDEND_PATTERNS = [
    r"\bdividend\b",
    r"\brecord date\b",
    r"\bbonus (?:issue|shares?)\b",
    r"\bbuyback\b",
    r"\bsplit of shares?\b",
]


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_EARNINGS  = _compile(EARNINGS_PATTERNS)
_M_AND_A   = _compile(M_AND_A_PATTERNS)
_REG       = _compile(REGULATORY_PATTERNS)
_DIVIDEND  = _compile(DIVIDEND_PATTERNS)


@lru_cache(maxsize=1)
def _noise_filters() -> tuple[list[re.Pattern], list[re.Pattern]]:
    with NOISE_PATH.open() as f:
        cfg = yaml.safe_load(f) or {}
    block = _compile([re.escape(p) for p in cfg.get("block_deal_patterns", [])])
    generic = _compile([re.escape(p) for p in cfg.get("generic_noise_patterns", [])])
    return block, generic


def classify(headline: str, body: str | None = None) -> str:
    """Return one of CATEGORIES."""
    text = f"{headline} {body or ''}"
    block, generic = _noise_filters()
    if any(p.search(text) for p in block):
        return "block_deal"
    if any(p.search(text) for p in _EARNINGS):
        return "earnings"
    if any(p.search(text) for p in _M_AND_A):
        return "m_and_a"
    if any(p.search(text) for p in _REG):
        return "regulatory"
    if any(p.search(text) for p in _DIVIDEND):
        return "dividend"
    if any(p.search(text) for p in generic):
        return "generic_noise"
    return "other"
