"""Selector safety + correctness.

The single most important test in this package:
    auto-pilot must NEVER enable a strategy that is not on the validated
    allowlist — not in any regime, not ever. That is the code-level enforcement
    of AUTOPSY_FINDINGS H1.
"""
from __future__ import annotations

from titan.config import settings
from titan.decision.regime import Regime, RegimeReading, SessionPhase
from titan.decision.selector import (
    REGIME_CANDIDATES, Selector, target_for,
)


ENABLED_K = "titan:strategies:enabled"


class FakeRedis:
    """Minimal key-aware in-memory stand-in for the bits Selector touches.
    `enabled` seeds the enabled set; the validated set is left empty so the
    selector falls back to the .env default (settings.autopilot_validated_set)."""
    def __init__(self, enabled=None, validated=None):
        self.sets = {ENABLED_K: set(enabled or [])}
        if validated is not None:
            self.sets["titan:autopilot:validated"] = set(validated)
        self.kv = {}

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def sadd(self, key, *vals):
        self.sets.setdefault(key, set()).update(vals)

    def srem(self, key, *vals):
        self.sets.setdefault(key, set()).difference_update(vals)

    def set(self, k, v):
        self.kv[k] = v


def _reading(regime):
    return RegimeReading(regime=regime, session_phase=SessionPhase.MORNING,
                         ref_symbol="NIFTY", reason=f"test {regime}")


def test_validated_set_default_is_orb_only():
    assert settings.autopilot_validated_set == {"orb"}


def test_killed_and_unvalidated_never_enabled_in_any_regime():
    # vwap_revert & supertrend_adx are candidates but NOT validated → must be filtered.
    for regime in Regime:
        target = target_for(_reading(regime))
        assert target <= settings.autopilot_validated_set
        assert "tsmom" not in target          # killed
        assert "vwap_revert" not in target     # unvalidated
        assert "supertrend_adx" not in target  # unvalidated


def test_trend_arms_orb():
    r = FakeRedis(enabled=set())
    d = Selector(r).decide(_reading(Regime.TREND), apply=True)
    assert d.target == {"orb"}
    assert "orb" in r.smembers("titan:strategies:enabled")
    assert d.applied is True


def test_crisis_disarms_everything_in_lane():
    r = FakeRedis(enabled={"orb"})
    d = Selector(r).decide(_reading(Regime.CRISIS), apply=True)
    assert d.target == set()
    assert "orb" in d.removed
    assert "orb" not in r.smembers("titan:strategies:enabled")


def test_closed_disarms():
    r = FakeRedis(enabled={"orb"})
    Selector(r).decide(_reading(Regime.CLOSED), apply=True)
    assert "orb" not in r.smembers("titan:strategies:enabled")


def test_observe_only_does_not_touch_redis():
    r = FakeRedis(enabled=set())
    d = Selector(r).decide(_reading(Regime.TREND), apply=False)
    assert d.target == {"orb"}        # decision is computed
    assert d.applied is False
    assert r.smembers("titan:strategies:enabled") == set()  # but nothing applied
    assert d.added == set()


def test_does_not_stomp_strategies_outside_its_lane():
    # A human manually enabled an experimental strategy not under auto-pilot control.
    r = FakeRedis(enabled={"my_experiment"})
    Selector(r).decide(_reading(Regime.CRISIS), apply=True)
    # CRISIS disarms auto-pilot's lane, but must leave the manual one alone.
    assert "my_experiment" in r.smembers("titan:strategies:enabled")


def test_publishes_regime_for_dashboard():
    r = FakeRedis(enabled=set())
    Selector(r).decide(_reading(Regime.RANGE), apply=True)
    assert r.kv["titan:regime:current"] == "RANGE"
    assert "titan:regime:reason" in r.kv


def test_regime_candidate_map_matches_research_intent():
    # trend = breakout+trend-follow, range = mean-revert, crisis/closed = flat
    assert "orb" in REGIME_CANDIDATES[Regime.TREND]
    assert "vwap_revert" in REGIME_CANDIDATES[Regime.RANGE]
    assert REGIME_CANDIDATES[Regime.CRISIS] == set()
    assert REGIME_CANDIDATES[Regime.CLOSED] == set()
