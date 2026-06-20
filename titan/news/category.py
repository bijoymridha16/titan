"""Headline category classifier — rules-based.

We deliberately avoid ML here: we have zero labelled headlines, and a text
classifier trained on weak labels would just overfit. Regex/keyword rules are
transparent, auditable, and tunable by editing one YAML.

Categories (priority-ordered — first match wins):

  1. block_deal       — block/bulk/large trades. Noise list — never fires.
  2. regulatory       — SEBI/RBI/CCI penalties, fines, raids, bans.
  3. promoter_buying  — promoter / insider acquisition.
  4. promoter_selling — promoter / insider disposal.
  5. order_win        — contract wins, deals, partnerships-as-customer.
  6. partnership      — JVs, strategic investments, tie-ups, hubs.
  7. guidance_up      — raised guidance / upgraded outlook.
  8. guidance_down    — cut guidance / downgraded outlook / warning.
  9. earnings         — quarterly results, beat/miss numbers.
 10. m_and_a          — acquisitions, mergers, takeovers, stake purchases.
 11. debt_reduce      — debt repayment, deleveraging.
 12. debt_raise       — debt issuance, bond offerings.
 13. dividend         — dividend / bonus / buyback / record date.
 14. generic_noise    — AGM, board outcome, "Live Updates" recaps. Never fires.
 15. other            — everything else.

Priority matters: "promoter buys 5% stake" should be `promoter_buying`,
not `m_and_a`. "Guidance cut" should be `guidance_down`, not `earnings`.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

NOISE_PATH = Path(__file__).resolve().parents[2] / "config" / "news_noise_filters.yaml"

CATEGORIES = (
    "block_deal", "regulatory",
    "promoter_buying", "promoter_selling",
    "order_win", "partnership",
    "guidance_up", "guidance_down",
    "earnings", "m_and_a",
    "debt_reduce", "debt_raise",
    "dividend",
    "generic_noise", "other",
)
NEVER_FIRE = {"block_deal", "generic_noise", "other"}

# Patterns are evaluated in the order categories appear above (first match wins).
REGULATORY_PATTERNS = [
    r"\bsebi\b.*\b(penalty|fine|ban|order|notice|imposes?|crackdown|debar)",
    r"\b(rbi|reserve bank).*\b(action|fine|penalty|directive|cease and desist)",
    r"\bcci\b.*\b(investigation|raid|penalty)",
    r"\b(ed|enforcement directorate|cbi|sfio|income tax)\b.*\b(raid|probe|investigation)",
    r"\b(suspend(?:s|ed)?|bans?)\s+trading\b",
    r"\bdebar(?:s|red)?\b",
]
PROMOTER_BUYING_PATTERNS = [
    r"\bpromoter[s]?\b.*\b(buy|buys|bought|acquire[sd]?|purchase[sd]?|raised stake|increased stake|pledge release)",
    r"\binsider\b.*\b(buy|buys|bought|acquir)",
    r"\b(creeping acquisition|open offer)\b",
]
PROMOTER_SELLING_PATTERNS = [
    r"\bpromoter[s]?\b.*\b(sell|sells|sold|offload|trim|reduce[sd]? stake|stake sale|pledge)",
    r"\binsider\b.*\b(sell|sells|sold|offload)",
]
# Order win / contract / customer-deal patterns. Important catalyst per rubric.
# Allow up to ~4 modifier words between the verb and the noun
# (e.g. "bags multi-year project", "awarded multi-year IT mandate").
_OW_GAP = r"(?:\s+\S+){0,4}\s+"
ORDER_WIN_PATTERNS = [
    r"\bwins?" + _OW_GAP + r"(?:contract|deal|order|mandate|tender|project)",
    r"\bbag(?:s|ged)" + _OW_GAP + r"(?:contract|deal|order|mandate|project)",
    r"\bsecure[sd]?" + _OW_GAP + r"(?:contract|deal|order|mandate|tender)",
    r"\bawarded" + _OW_GAP + r"(?:contract|deal|order|mandate|tender|project)",
    r"\bemerges?\s+(?:as\s+)?lowest bidder\b",
    r"\bL1 bidder\b",
    r"\bselects?\s+\w+\s+to\s+(?:accelerate|transform|implement|deploy|build|provide|deliver|modernize)",
    r"\bselected\s+by\s+\w+",
    r"\bnew (?:order|contract)\b.*\b(worth|valued|crore|million|billion)",
    r"\border (?:book|inflow)\b.*\b(at|rose|jumped|surged|record)",
]
# Note: m_and_a's "strategic investment in" matches before partnership's
# "strategic alliance/partnership" because m_and_a is checked later but the
# more-specific "strategic investment" lives in m_and_a. We keep partnership
# patterns scoped to JV/MoU/tie-up/hub language only.
PARTNERSHIP_PATTERNS = [
    r"\bpartners?\s+with\b",
    r"\bpartnership\s+with\b",
    r"\bjoint venture\b|\bjv\s+with\b",
    r"\bcollaborat(?:e|es|ion)\s+with\b",
    r"\btie[-\s]?up\s+with\b",
    r"\bstrategic\s+(?:alliance|partnership)\b",
    r"\bmou\b.*\bwith\b",
    r"\bunveil(?:s|ing|ed)?(?:\s+\S+){0,5}\s+(?:hub|centre|center|lab|platform)",
    r"\b(?:opens|launches?|inaugurates?)\s+(?:new\s+)?(?:innovation|R&D|AI|tech)\s+(?:hub|centre|center|lab)",
]
# Guidance verbs may have several words between them and "guidance" itself
# (e.g. "raises FY27 revenue guidance to 4-6%"). Allow a small gap.
_G_GAP = r"(?:\s+\S+){0,4}\s+"
GUIDANCE_UP_PATTERNS = [
    r"\b(raises?|raised|hikes?|upgrades?|lifts?)" + _G_GAP + r"(?:guidance|outlook|forecast|target)",
    r"\b(guidance|outlook|forecast)\s+(?:raised|upgraded|hiked|lifted)",
    r"\bstrong(?:er)?\s+(?:fy\d*|full[-\s]?year)?\s*guidance",
]
GUIDANCE_DOWN_PATTERNS = [
    r"\b(cuts?|cut|lowers?|trims?|slashes?|reduces?|downgrades?)" + _G_GAP + r"(?:guidance|outlook|forecast|target)",
    r"\b(guidance|outlook|forecast)\s+(?:cut|lowered|trimmed|slashed|reduced|downgraded|weaker|disappointing)",
    r"\bweaker[-\s]?than[-\s]?(?:expected|estimated)\b.*\bguidance",
    r"\bprofit warning\b",
]
EARNINGS_PATTERNS = [
    r"\bq[1-4]\s*(?:fy\d*|results?)\b",
    r"\b(quarterly results?|annual results?)\b",
    r"\b(profit|net profit|pat|loss|net loss)\s+(?:up|down|rose|fell|jump|surged|slumps?)",
    r"\b(revenue|topline|ebitda|operating margin|gross margin)\s+(?:up|down|rose|fell|jump|surged|miss|beat)",
    r"\b(beat|miss|missed|misses|beats?)\s+(?:estimates?|consensus|street)",
    r"\b(eps|earnings per share)\s+(?:at|of|up|down|rose|fell)",
    r"\bposts?\s+(?:net\s+)?(?:profit|loss|revenue)\b",
]
M_AND_A_PATTERNS = [
    r"\bacquir(?:e|es|ed|ing|sition)\b",
    r"\b(merger|takeover|amalgamation|demerger)\b",
    r"\bstake (?:purchase|acquisition|sale)\b",
    r"\b(buyout|controlling stake|majority stake)\b",
    r"\bto buy\b.*\b(stake|equity|shares)\b",
    r"\bstrategic investment in\b",
]
DEBT_REDUCE_PATTERNS = [
    r"\b(?:repays?|repaid|prepays?|prepaid|retires?|pays? down)\b.*\b(debt|loan|borrowing|bond)",
    r"\bdebt[-\s]?free\b",
    r"\b(deleveraging|deleverages?|reduces? debt)\b",
]
DEBT_RAISE_PATTERNS = [
    r"\b(?:raises?|raised|issues?|issued|prices?)\b.*\b(bond|debenture|ncd|loan|borrowing)",
    r"\bbond (?:issue|offering|sale)\b",
    r"\bdebt issuance\b",
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


_REG              = _compile(REGULATORY_PATTERNS)
_PROMOTER_BUYING  = _compile(PROMOTER_BUYING_PATTERNS)
_PROMOTER_SELLING = _compile(PROMOTER_SELLING_PATTERNS)
_ORDER_WIN        = _compile(ORDER_WIN_PATTERNS)
_PARTNERSHIP      = _compile(PARTNERSHIP_PATTERNS)
_GUIDANCE_UP      = _compile(GUIDANCE_UP_PATTERNS)
_GUIDANCE_DOWN    = _compile(GUIDANCE_DOWN_PATTERNS)
_EARNINGS         = _compile(EARNINGS_PATTERNS)
_M_AND_A          = _compile(M_AND_A_PATTERNS)
_DEBT_REDUCE      = _compile(DEBT_REDUCE_PATTERNS)
_DEBT_RAISE       = _compile(DEBT_RAISE_PATTERNS)
_DIVIDEND         = _compile(DIVIDEND_PATTERNS)


@lru_cache(maxsize=1)
def _noise_filters() -> tuple[list[re.Pattern], list[re.Pattern]]:
    with NOISE_PATH.open() as f:
        cfg = yaml.safe_load(f) or {}
    block = _compile([re.escape(p) for p in cfg.get("block_deal_patterns", [])])
    generic = _compile([re.escape(p) for p in cfg.get("generic_noise_patterns", [])])
    return block, generic


def classify(headline: str, body: str | None = None) -> str:
    """Return one of CATEGORIES. Priority-ordered: first match wins."""
    text = f"{headline} {body or ''}"
    block, generic = _noise_filters()
    if any(p.search(text) for p in block):
        return "block_deal"
    if any(p.search(text) for p in _REG):
        return "regulatory"
    if any(p.search(text) for p in _PROMOTER_BUYING):
        return "promoter_buying"
    if any(p.search(text) for p in _PROMOTER_SELLING):
        return "promoter_selling"
    if any(p.search(text) for p in _ORDER_WIN):
        return "order_win"
    if any(p.search(text) for p in _PARTNERSHIP):
        return "partnership"
    if any(p.search(text) for p in _GUIDANCE_DOWN):
        return "guidance_down"
    if any(p.search(text) for p in _GUIDANCE_UP):
        return "guidance_up"
    if any(p.search(text) for p in _EARNINGS):
        return "earnings"
    if any(p.search(text) for p in _M_AND_A):
        return "m_and_a"
    if any(p.search(text) for p in _DEBT_REDUCE):
        return "debt_reduce"
    if any(p.search(text) for p in _DEBT_RAISE):
        return "debt_raise"
    if any(p.search(text) for p in _DIVIDEND):
        return "dividend"
    if any(p.search(text) for p in generic):
        return "generic_noise"
    return "other"
