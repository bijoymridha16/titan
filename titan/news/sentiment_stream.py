"""Live news-sentiment → Redis bridge (manifesto Multiplier 2).

Turns the (previously dry-run) news pipeline into a live signal: publishes the
aggregate FinBERT negative-sentiment probability for the universe to
`titan:news:neg_p`, which the regime classifier reads to force a preemptive
CRISIS when it spikes.

`publish_neg_p` / `latest_neg_p` are the Redis bridge (unit-testable with a fake
client). `compute_recent_neg_p` derives the aggregate from recently-stored news
signals (DB-backed, best-effort).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

NEG_P_KEY = "titan:news:neg_p"


def publish_neg_p(r, value: float, ttl_s: int = 1800) -> None:
    """Publish the aggregate negative-sentiment probability (0..1). TTL'd so a
    stale reading auto-expires and stops forcing CRISIS."""
    try:
        r.set(NEG_P_KEY, f"{float(value):.4f}", ex=ttl_s)
    except Exception as e:
        log.warning("publish neg_p failed: %s", e)


def latest_neg_p(r) -> float | None:
    """Read the latest published negative-sentiment probability, or None."""
    try:
        v = r.get(NEG_P_KEY)
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def aggregate_neg_p(rows: list[dict]) -> float | None:
    """Aggregate negative-sentiment probability over recent signal rows.

    Each row: {"sentiment_label": str, "sentiment_score": float}. Takes the MAX
    negative score (a single strong negative headline should be able to trip the
    crisis gate). Returns None when there are no negative rows.
    """
    negs = [float(r["sentiment_score"]) for r in rows
            if (r.get("sentiment_label") or "").lower() == "negative"
            and r.get("sentiment_score") is not None]
    return max(negs) if negs else None


def compute_recent_neg_p(window_minutes: int = 30) -> float | None:
    """Derive the aggregate negative-sentiment probability from news_signals in
    the last `window_minutes`. Best-effort; returns None on any failure."""
    from sqlalchemy import text
    from titan.data.store import engine
    try:
        with engine().connect() as cx:
            rows = cx.execute(text(
                "SELECT sentiment_label, sentiment_score FROM news_signals "
                "WHERE published_at >= NOW() - (:m::text || ' minutes')::interval"
            ), {"m": window_minutes}).mappings().all()
        return aggregate_neg_p([dict(r) for r in rows])
    except Exception as e:
        log.warning("compute_recent_neg_p failed: %s", e)
        return None
