"""FinBERT sentiment with persistent cache.

Wraps ProsusAI/finbert (default; env-overridable via NEWS_FINBERT_MODEL).
Loaded lazily on first call. Inference is batched to amortise tokenizer cost.
Results cached in `sentiment_cache` keyed by sha256(model_id || ':' || headline),
so re-runs of the same headlines are free.

Returns a dict per headline:
    {label: "negative"|"neutral"|"positive",
     score: max-prob,
     neg_p, neu_p, pos_p: float}

Latency on M1 CPU: ~50ms first item (loader warmup), ~30ms/headline batched.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from sqlalchemy import text

from titan.config import news_settings
from titan.data.store import engine

log = logging.getLogger(__name__)

LABELS = ("negative", "neutral", "positive")


def _key(model_id: str, headline: str) -> str:
    return hashlib.sha256(f"{model_id}:{headline}".encode("utf-8")).hexdigest()


class FinBERT:
    def __init__(self, model_id: Optional[str] = None):
        self.model_id = model_id or news_settings.finbert_model
        self._pipe = None

    def _load(self):
        if self._pipe is not None:
            return
        log.info("loading FinBERT %s …", self.model_id)
        # Imports kept lazy so test runs don't pay the cost.
        from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
        import torch
        tok = AutoTokenizer.from_pretrained(self.model_id)
        mdl = AutoModelForSequenceClassification.from_pretrained(self.model_id)
        device = 0 if torch.cuda.is_available() else -1
        self._pipe = pipeline("text-classification", model=mdl, tokenizer=tok,
                              top_k=None, device=device, truncation=True,
                              max_length=256)
        log.info("FinBERT ready on %s", "cuda" if device >= 0 else "cpu")

    # ─────────────── public ───────────────
    def score(self, headlines: list[str]) -> list[dict]:
        """Returns one result dict per input headline, in order. Uses the
        DB cache transparently; only un-cached headlines hit the model."""
        if not headlines:
            return []
        results: list[Optional[dict]] = [None] * len(headlines)
        keys = [_key(self.model_id, h) for h in headlines]

        cached = self._cache_lookup(keys)
        to_run: list[tuple[int, str]] = []
        for i, (k, h) in enumerate(zip(keys, headlines)):
            hit = cached.get(k)
            if hit is not None:
                results[i] = hit
            else:
                to_run.append((i, h))

        if to_run:
            self._load()
            batch_size = max(1, news_settings.batch_size)
            for chunk_start in range(0, len(to_run), batch_size):
                chunk = to_run[chunk_start:chunk_start + batch_size]
                texts = [h for _, h in chunk]
                raw = self._pipe(texts)
                for (idx, headline), per_label_scores in zip(chunk, raw):
                    parsed = self._parse(per_label_scores)
                    results[idx] = parsed
                    self._cache_put(_key(self.model_id, headline), headline, parsed)

        return [r or {"label": "neutral", "score": 1/3,
                      "neg_p": 1/3, "neu_p": 1/3, "pos_p": 1/3}
                for r in results]

    # ─────────────── internals ───────────────
    def _parse(self, raw) -> dict:
        probs = {"negative": 0.0, "neutral": 0.0, "positive": 0.0}
        # transformers pipeline returns either a flat dict or list[dict]
        items = raw if isinstance(raw, list) else [raw]
        for item in items:
            lbl = (item.get("label") or "").lower()
            if lbl in probs:
                probs[lbl] = float(item.get("score") or 0.0)
        label = max(probs, key=probs.get)
        return {
            "label": label,
            "score": probs[label],
            "neg_p": probs["negative"],
            "neu_p": probs["neutral"],
            "pos_p": probs["positive"],
        }

    def _cache_lookup(self, keys: list[str]) -> dict[str, dict]:
        if not keys:
            return {}
        with engine().connect() as cx:
            rows = cx.execute(text("""
                SELECT cache_key, label, score, neg_p, neu_p, pos_p
                FROM sentiment_cache WHERE cache_key = ANY(:keys)
            """), {"keys": keys}).mappings().all()
        return {r["cache_key"]: dict(r) for r in rows}

    def _cache_put(self, key: str, headline: str, parsed: dict) -> None:
        with engine().begin() as cx:
            cx.execute(text("""
                INSERT INTO sentiment_cache
                  (cache_key, model_id, headline, label, score, neg_p, neu_p, pos_p)
                VALUES (:k, :m, :h, :l, :s, :ng, :nu, :ps)
                ON CONFLICT (cache_key) DO NOTHING
            """), {"k": key, "m": self.model_id, "h": headline,
                   "l": parsed["label"], "s": parsed["score"],
                   "ng": parsed["neg_p"], "nu": parsed["neu_p"], "ps": parsed["pos_p"]})
