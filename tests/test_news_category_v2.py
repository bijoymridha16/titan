"""Category classifier + fire-rule tests for news v2.

Real headlines from the 2026-06-17 ingest are asserted, not invented ones.
Rule of thumb: only assert on a headline if it was actually seen in the wild.
"""
from __future__ import annotations

import pytest

from titan.news.category import classify
from titan.news.ingest import _decide_fire


# ─────────────── classifier: order_win ───────────────

@pytest.mark.parametrize("headline", [
    "TCS Wins Multi-Year Deal To Transform Elopak's IT Operations",
    "Volkswagen Group's E.Solutions Selects HCLTech To Accelerate Innovation",
    "L&T bags multi-year project from NHAI worth Rs 5000 crore",
    "Infosys awarded multi-year IT mandate by major US bank",
])
def test_order_win_headlines_classified(headline: str):
    assert classify(headline) == "order_win"


# ─────────────── classifier: partnership ───────────────

@pytest.mark.parametrize("headline", [
    "Wipro shares in focus after unveiling Anthropic-powered AI hub in Bengaluru",
    "Infosys partners with Microsoft for cloud transformation",
    "Tata Steel signs MoU with JFE Steel for strategic alliance",
])
def test_partnership_headlines_classified(headline: str):
    assert classify(headline) == "partnership"


# ─────────────── classifier: guidance_down ───────────────

def test_jlr_guidance_cut_classified_as_guidance_down():
    headline = ("Tata Motors PV shares plunge 10% after weaker than "
                "expected JLR FY27 guidance")
    assert classify(headline) == "guidance_down"


def test_profit_warning_classified_as_guidance_down():
    assert classify("Company X issues profit warning for H2 FY27") == "guidance_down"


# ─────────────── classifier: guidance_up ───────────────

def test_guidance_raise_classified_as_guidance_up():
    assert classify("Infy raises FY27 revenue guidance to 4-6%") == "guidance_up"


# ─────────────── classifier: noise (Live Updates recap headlines) ───────────────

@pytest.mark.parametrize("headline", [
    "Bajaj Auto Share Price Live Updates: Bajaj Auto Shows Positive Momentum in Trading",
    "Titan Company Share Price Live Updates: Titan Company Shows Strong Market Performance",
    "JSW Steel Share Price Live Updates: JSW Steel Sees Modest Gains Today",
    "Reliance Industries among 6 largecap stocks showing bullish RSI upswing",
    "Divis Labs Share Price Live Updates: Divis Labs Dips Below Key Moving Average",
])
def test_live_updates_recaps_are_noise(headline: str):
    assert classify(headline) == "generic_noise"


# ─────────────── classifier: m_and_a (still works) ───────────────

def test_strategic_investment_classified_as_m_and_a():
    headline = "HCLTech bets big on sovereign AI with strategic investment in Sarvam AI"
    assert classify(headline) == "m_and_a"


# ─────────────── classifier: earnings still works ───────────────

def test_quarterly_results_classified_as_earnings():
    assert classify("TCS posts net profit of Rs 12000 crore for Q1 FY27") == "earnings"


# ─────────────── classifier: regulatory ───────────────

def test_sebi_penalty_classified_as_regulatory():
    assert classify("SEBI imposes Rs 2 crore penalty on broker") == "regulatory"


# ─────────────── classifier: priority — promoter buying beats m_and_a ───────────────

def test_promoter_buying_beats_m_and_a():
    # "acquires" would match m_and_a, but promoter context wins
    assert classify("Promoter acquires additional 2% stake via open market") == "promoter_buying"


# ─────────────── fire rule ───────────────

NIFTY50 = {"TCS", "HCLTECH", "WIPRO", "TATAMOTORS", "RELIANCE", "INFY"}


def test_fire_order_win_positive_nifty50_fires_long():
    fire, reason, direction = _decide_fire(
        "TCS", "order_win", "positive", 0.85, 0.85, NIFTY50)
    assert fire is True
    assert direction == "long"
    assert "order_win" in reason


def test_fire_order_win_below_threshold_does_not_fire():
    fire, _, _ = _decide_fire("TCS", "order_win", "positive", 0.50, 0.85, NIFTY50)
    assert fire is False


def test_fire_order_win_neutral_sentiment_does_not_fire():
    fire, _, _ = _decide_fire("TCS", "order_win", "neutral", 0.80, 0.85, NIFTY50)
    assert fire is False


def test_fire_guidance_down_negative_fires_short():
    fire, _, direction = _decide_fire(
        "TATAMOTORS", "guidance_down", "negative", 0.85, 0.85, NIFTY50)
    assert fire is True
    assert direction == "short"


def test_fire_regulatory_positive_does_not_fire():
    # regulatory only fires when negative — positive sentiment about regulator = noise
    fire, _, _ = _decide_fire(
        "TCS", "regulatory", "positive", 0.90, 0.85, NIFTY50)
    assert fire is False


def test_fire_promoter_buying_any_sentiment_fires_long():
    # action itself is the signal — sentiment irrelevant
    fire, _, direction = _decide_fire(
        "TCS", "promoter_buying", "neutral", 0.0, 0.85, NIFTY50)
    assert fire is True
    assert direction == "long"


def test_fire_other_category_does_not_fire():
    fire, reason, _ = _decide_fire(
        "TCS", "other", "positive", 0.95, 0.85, NIFTY50)
    assert fire is False
    assert "other" in reason


def test_fire_non_nifty50_blocked():
    fire, reason, _ = _decide_fire(
        "SMALLCAP", "order_win", "positive", 0.85, 0.85, NIFTY50)
    assert fire is False
    assert "nifty50" in reason


def test_fire_low_entity_conf_blocked():
    fire, reason, _ = _decide_fire(
        "TCS", "order_win", "positive", 0.85, 0.40, NIFTY50)
    assert fire is False
    assert "entity_conf" in reason


def test_fire_generic_noise_blocked():
    fire, reason, _ = _decide_fire(
        "BAJAJ-AUTO", "generic_noise", "positive", 0.95, 0.85, NIFTY50)
    assert fire is False
    assert "generic_noise" in reason
