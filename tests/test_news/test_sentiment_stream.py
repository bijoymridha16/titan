"""Live news-sentiment → Redis bridge (manifesto Multiplier 2)."""
from __future__ import annotations

from titan.news import sentiment_stream as ss


class _FakeRedis:
    def __init__(self): self.kv = {}
    def set(self, k, v, ex=None): self.kv[k] = v
    def get(self, k): return self.kv.get(k)


def test_publish_and_read_roundtrip():
    r = _FakeRedis()
    ss.publish_neg_p(r, 0.873)
    assert abs(ss.latest_neg_p(r) - 0.873) < 1e-6


def test_latest_none_when_absent():
    assert ss.latest_neg_p(_FakeRedis()) is None


def test_latest_handles_garbage():
    r = _FakeRedis(); r.kv[ss.NEG_P_KEY] = "not-a-number"
    assert ss.latest_neg_p(r) is None


def test_aggregate_takes_max_negative():
    rows = [
        {"sentiment_label": "positive", "sentiment_score": 0.99},
        {"sentiment_label": "negative", "sentiment_score": 0.70},
        {"sentiment_label": "negative", "sentiment_score": 0.91},
        {"sentiment_label": "neutral", "sentiment_score": 0.80},
    ]
    assert ss.aggregate_neg_p(rows) == 0.91


def test_aggregate_none_when_no_negatives():
    rows = [{"sentiment_label": "positive", "sentiment_score": 0.99}]
    assert ss.aggregate_neg_p(rows) is None
