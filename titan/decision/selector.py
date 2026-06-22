"""Regime → strategy selector.

Turns a RegimeReading into a concrete decision: which strategies should be
ENABLED right now. Then reconciles that against Redis `titan:strategies:enabled`
— the exact same set the supervisor already reads, so this plugs into the
existing architecture with zero supervisor changes.

TWO HARD SAFETY INVARIANTS:
  1. Auto-pilot can ONLY enable strategies in settings.autopilot_validated_set.
     That set contains only strategies that passed their walk-forward ship/kill
     gate. This is the code-level enforcement of AUTOPSY_FINDINGS H1 —
     unvalidated / killed strategies can never be auto-armed, by construction.
  2. Auto-pilot only ever adds/removes strategies WITHIN its controlled universe
     (the validated set). Anything a human enabled outside that universe is left
     untouched — auto-pilot manages its own lane, it doesn't stomp manual work.

The regime→candidate map is the research's gating logic (docs/02 §6), but the
intersection with the validated set is what actually ships. With the default
validated set = {orb}, auto-pilot arms ORB in TREND/TRANSITION, and disarms
everything in CRISIS/RANGE/CLOSED — honest and safe until more strategies earn
their place on the allowlist.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from titan.config import settings
from titan.decision.regime import Regime, RegimeReading

log = logging.getLogger(__name__)

ENABLED_KEY = "titan:strategies:enabled"

# Regime → strategies that are *theoretically* appropriate (before validation gate).
# Grounded in docs/02_strategy_rankings.md §6:
#   trend regime → breakout + trend-follow ; range regime → mean-revert ;
#   crisis → flat ; transition → only the most-evidenced single strategy.
REGIME_CANDIDATES: dict[Regime, set[str]] = {
    # trend / breakout / momentum styles
    Regime.TREND: {"orb", "orb_confirmed", "supertrend_adx",
                   "ma_cross", "donchian", "momentum"},
    # mean-reversion styles
    Regime.RANGE: {"vwap_revert", "vwap_rsi", "rsi_revert", "bollinger_revert"},
    # ambiguous: breakout-from-compression + confirmed breakout
    Regime.TRANSITION: {"orb", "orb_confirmed", "donchian", "bb_squeeze"},
    Regime.CRISIS: set(),
    Regime.CLOSED: set(),
}


@dataclass
class SelectionDecision:
    reading: RegimeReading
    target: set[str]          # what should be enabled (post validation gate)
    enabled_before: set[str]
    enabled_after: set[str]
    added: set[str]
    removed: set[str]
    applied: bool             # False in observe-only / dry mode
    reason: str


VALIDATED_KEY = "titan:autopilot:validated"


def validated_set(r=None) -> set[str]:
    """The strategies cleared to trade. The promotion job writes survivors to the
    `titan:autopilot:validated` Redis set; absent that, fall back to the .env
    default. This is how walk-forward winners become live-eligible automatically."""
    if r is not None:
        try:
            v = r.smembers(VALIDATED_KEY)
            if v:
                return set(v)
        except Exception:
            pass
    return set(settings.autopilot_validated_set)


def target_for(reading: RegimeReading, validated: set[str] | None = None) -> set[str]:
    """Pure: regime → validated strategies to enable. No I/O."""
    candidates = REGIME_CANDIDATES.get(reading.regime, set())
    return candidates & (validated if validated is not None
                         else set(settings.autopilot_validated_set))


class Selector:
    """Reconciles the desired strategy set against Redis. I/O is injectable for tests."""

    def __init__(self, redis_client, db_engine=None):
        self.r = redis_client
        self._engine = db_engine  # lazy; only needed for the audit-log row

    def decide(self, reading: RegimeReading, apply: bool) -> SelectionDecision:
        controlled = validated_set(self.r)
        target = target_for(reading, controlled)

        current = set(self.r.smembers(ENABLED_KEY) or set())
        # Only act within our controlled lane.
        to_enable = target - current
        to_disable = (controlled & current) - target

        after = set(current)
        if apply and (to_enable or to_disable):
            if to_enable:
                self.r.sadd(ENABLED_KEY, *to_enable)
            if to_disable:
                self.r.srem(ENABLED_KEY, *to_disable)
            after = (current | to_enable) - to_disable

        # Publish current regime for the dashboard / observability.
        self._publish_regime(reading)

        verb = "applied" if apply else "observe-only (autopilot disarmed)"
        reason = f"{reading.reason} → target={sorted(target) or '∅'} [{verb}]"
        decision = SelectionDecision(
            reading=reading, target=target, enabled_before=current, enabled_after=after,
            added=to_enable if apply else set(), removed=to_disable if apply else set(),
            applied=apply, reason=reason,
        )
        self._persist(decision)
        if to_enable or to_disable:
            log.info("regime=%s armed=%s disarmed=%s (%s)",
                     reading.regime, sorted(to_enable) or "—", sorted(to_disable) or "—", verb)
        return decision

    # ──────────────── observability ────────────────
    def _publish_regime(self, reading: RegimeReading) -> None:
        try:
            self.r.set("titan:regime:current", str(reading.regime))
            self.r.set("titan:regime:reason", reading.reason)
            self.r.set("titan:regime:reading", json.dumps(reading.as_log(), default=str))
        except Exception as e:  # never let observability break the decision
            log.warning("publish regime failed: %s", e)

    def _persist(self, d: SelectionDecision) -> None:
        if self._engine is None:
            return
        try:
            from sqlalchemy import text
            with self._engine.begin() as cx:
                cx.execute(text("""
                    INSERT INTO regime_decisions
                      (ref_symbol, regime, adx, realized_vol, vol_pctile, or_expansion,
                       india_vix, session_phase, enabled_before, enabled_after, reason)
                    VALUES (:rs, :rg, :adx, :rv, :vp, :oe, :vix, :sp, :eb, :ea, :reason)
                """), {
                    "rs": d.reading.ref_symbol, "rg": str(d.reading.regime),
                    "adx": d.reading.adx, "rv": d.reading.realized_vol,
                    "vp": d.reading.vol_pctile, "oe": d.reading.or_expansion,
                    "vix": d.reading.india_vix, "sp": str(d.reading.session_phase),
                    "eb": json.dumps(sorted(d.enabled_before)),
                    "ea": json.dumps(sorted(d.enabled_after)),
                    "reason": d.reason,
                })
        except Exception as e:  # audit log must never block trading decisions
            log.warning("persist regime decision failed: %s", e)
