"""Sentiment-cache plumbing tests — no model load, no network."""
from unittest.mock import patch

from titan.news.sentiment import FinBERT, _key


def test_key_stable():
    a = _key("ProsusAI/finbert", "hello")
    b = _key("ProsusAI/finbert", "hello")
    c = _key("OtherModel/x",     "hello")
    assert a == b
    assert a != c


def test_cache_hit_skips_load():
    fb = FinBERT()
    cached_one = {
        _key(fb.model_id, "cached headline"): {
            "label": "positive", "score": 0.9,
            "neg_p": 0.05, "neu_p": 0.05, "pos_p": 0.90,
        }
    }
    with patch.object(fb, "_cache_lookup", return_value=cached_one), \
         patch.object(fb, "_load") as load_mock:
        out = fb.score(["cached headline"])
        assert load_mock.call_count == 0     # never loaded the model
        assert out[0]["label"] == "positive"
        assert out[0]["pos_p"] == 0.90


def test_empty_input_short_circuits():
    fb = FinBERT()
    with patch.object(fb, "_load") as load_mock:
        assert fb.score([]) == []
        assert load_mock.call_count == 0
