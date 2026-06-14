"""Batch news ingest + dry-run CSV emitter.

Pipeline:
  1. Run every enabled source's fetch(since) → list[RawNews]
  2. Upsert into news_events
  3. For each new event: resolve entities → news_entities
  4. Batch FinBERT sentiment on the headlines
  5. Classify category
  6. Compute would_fire decision per the v1 rule (see docs/research/02)
  7. Upsert news_signals
  8. Write a CSV snapshot of today's signals to out/news_signals_dryrun_<date>.csv

CLI:
    python -m titan.news.ingest --since 2026-06-12
    python -m titan.news.ingest --hours 24
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from titan.config import news_settings
from titan.data.store import engine
from titan.news.category import NEVER_FIRE, classify
from titan.news.entities import resolve
from titan.news.sentiment import FinBERT
from titan.news.sources._base import RawNews
from titan.news.sources.bse_corp_ann import BSECorpAnn
from titan.news.sources.et_html import EconomicTimesHTML
from titan.news.sources.moneycontrol_html import MoneycontrolHTML
from titan.news.sources.nse_corp_ann import NSECorpAnn
from titan.news.sources.rss import EconomicTimesRSS, MoneycontrolRSS

log = logging.getLogger(__name__)

ALL_SOURCES = [
    NSECorpAnn,
    BSECorpAnn,
    MoneycontrolRSS,
    EconomicTimesRSS,
    MoneycontrolHTML,   # gated by NEWS_SCRAPE_ENABLED
    EconomicTimesHTML,  # gated by NEWS_SCRAPE_ENABLED
]

OUT_DIR = Path(__file__).resolve().parents[2] / "out"

# v1 fire rule (mirrored from docs/research/02_news_driven.md §4e)
FIRE_CATEGORY = "earnings"
FIRE_SENTIMENT = "positive"
FIRE_SENT_THRESHOLD = 0.70
FIRE_ENTITY_CONF_THRESHOLD = 0.70
FIRE_NIFTY50_ONLY = True


# ───────────────── persistence ─────────────────
def _upsert_event(e: RawNews) -> int | None:
    """Insert if new; return event id either way. None on irrecoverable error."""
    with engine().begin() as cx:
        row = cx.execute(text("""
            INSERT INTO news_events
              (source, source_id, published_at, headline, body, url, raw_symbol, raw)
            VALUES (:src, :sid, :pub, :hl, :body, :url, :rs, :raw)
            ON CONFLICT (source, source_id) DO NOTHING
            RETURNING id
        """), {
            "src": e.source, "sid": e.source_id, "pub": e.published_at,
            "hl": e.headline, "body": e.body, "url": e.url,
            "rs": e.raw_symbol, "raw": json.dumps(e.raw, default=str),
        }).first()
        if row:
            return int(row[0])
        existing = cx.execute(text("""
            SELECT id FROM news_events WHERE source=:src AND source_id=:sid
        """), {"src": e.source, "sid": e.source_id}).first()
        return int(existing[0]) if existing else None


def _persist_entities(event_id: int, hits) -> None:
    if not hits:
        return
    with engine().begin() as cx:
        for h in hits:
            cx.execute(text("""
                INSERT INTO news_entities (news_event_id, ticker, matched_alias, confidence, method)
                VALUES (:eid, :t, :a, :c, :m)
                ON CONFLICT (news_event_id, ticker) DO NOTHING
            """), {"eid": event_id, "t": h.ticker, "a": h.matched_alias,
                   "c": h.confidence, "m": h.method})


def _persist_signal(event_id: int, ticker: str, published_at: datetime,
                    headline: str, source: str, category: str,
                    sent_label: str, sent_score: float, entity_conf: float,
                    would_fire: bool, fire_reason: str) -> None:
    with engine().begin() as cx:
        cx.execute(text("""
            INSERT INTO news_signals
              (news_event_id, ticker, published_at, headline, source, category,
               sentiment_label, sentiment_score, entity_conf, would_fire, fire_reason)
            VALUES (:e, :t, :p, :h, :s, :c, :sl, :ss, :ec, :wf, :fr)
            ON CONFLICT (news_event_id, ticker) DO UPDATE
              SET sentiment_label = EXCLUDED.sentiment_label,
                  sentiment_score = EXCLUDED.sentiment_score,
                  category = EXCLUDED.category,
                  would_fire = EXCLUDED.would_fire,
                  fire_reason = EXCLUDED.fire_reason
        """), {"e": event_id, "t": ticker, "p": published_at, "h": headline,
               "s": source, "c": category, "sl": sent_label, "ss": sent_score,
               "ec": entity_conf, "wf": would_fire, "fr": fire_reason})


# ───────────────── fire logic ─────────────────
def _nifty50_set() -> set[str]:
    from titan.data.backfill import nifty50_symbols
    return set(nifty50_symbols())


def _decide_fire(ticker: str, category: str, sent_label: str, sent_score: float,
                 entity_conf: float, n50: set[str]) -> tuple[bool, str]:
    if category in NEVER_FIRE:
        return False, f"category={category}"
    if FIRE_NIFTY50_ONLY and ticker not in n50:
        return False, "not_nifty50"
    if entity_conf < FIRE_ENTITY_CONF_THRESHOLD:
        return False, f"entity_conf={entity_conf:.2f}<{FIRE_ENTITY_CONF_THRESHOLD}"
    if category != FIRE_CATEGORY:
        return False, f"category={category}!=earnings"
    if sent_label != FIRE_SENTIMENT:
        return False, f"sentiment={sent_label}!=positive"
    if sent_score < FIRE_SENT_THRESHOLD:
        return False, f"sent_score={sent_score:.2f}<{FIRE_SENT_THRESHOLD}"
    return True, (f"earnings+positive {sent_score:.2f} "
                  f"entity_conf={entity_conf:.2f}")


# ───────────────── orchestration ─────────────────
def run(since: datetime) -> dict[str, int]:
    log.info("──── news ingest since %s ────", since.isoformat())
    counts = {"events": 0, "new_events": 0, "entities": 0, "signals": 0, "fires": 0}

    fb = FinBERT()
    n50 = _nifty50_set()

    # 1) ingest
    raw_by_event: dict[int, tuple[RawNews, list]] = {}
    for cls in ALL_SOURCES:
        src = cls()
        try:
            for raw in src.fetch(since):
                counts["events"] += 1
                eid = _upsert_event(raw)
                if eid is None:
                    continue
                hits = resolve(raw.raw_symbol, raw.headline, raw.body)
                if hits:
                    _persist_entities(eid, hits)
                    counts["entities"] += len(hits)
                raw_by_event[eid] = (raw, hits)
        finally:
            src.close()

    # 2) sentiment in one pass (cached)
    eids = list(raw_by_event)
    headlines = [raw_by_event[e][0].headline for e in eids]
    sent_results = fb.score(headlines) if headlines else []

    # 3) classify + decide fire + persist signal
    for eid, sent in zip(eids, sent_results):
        raw, hits = raw_by_event[eid]
        category = classify(raw.headline, raw.body)
        if not hits:
            continue
        for h in hits:
            fire, reason = _decide_fire(h.ticker, category, sent["label"],
                                        float(sent["score"]), h.confidence, n50)
            _persist_signal(eid, h.ticker, raw.published_at, raw.headline,
                            raw.source, category, sent["label"],
                            float(sent["score"]), h.confidence, fire, reason)
            counts["signals"] += 1
            if fire:
                counts["fires"] += 1

    log.info("ingest done %s", counts)
    return counts


# ───────────────── CSV snapshot ─────────────────
def emit_csv(since: datetime, only_fires: bool = False) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    suffix = "_fires" if only_fires else ""
    path = OUT_DIR / f"news_signals_dryrun_{today}{suffix}.csv"
    with engine().connect() as cx:
        rows = cx.execute(text(f"""
            SELECT published_at, ticker, source, category,
                   sentiment_label, sentiment_score, entity_conf,
                   would_fire, fire_reason, headline
            FROM news_signals
            WHERE published_at >= :since
            {'AND would_fire = TRUE' if only_fires else ''}
            ORDER BY published_at DESC
        """), {"since": since}).mappings().all()
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ts", "ticker", "source", "category",
                         "sentiment", "sent_score", "entity_conf",
                         "would_fire", "fire_reason", "headline"])
        for r in rows:
            writer.writerow([
                r["published_at"].isoformat() if r["published_at"] else "",
                r["ticker"], r["source"], r["category"],
                r["sentiment_label"], f"{r['sentiment_score']:.3f}",
                f"{r['entity_conf']:.2f}",
                int(r["would_fire"]),
                r["fire_reason"] or "",
                r["headline"][:200],
            ])
    log.info("wrote %d rows → %s", len(rows), path)
    return path


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--since", help="ISO date e.g. 2026-06-12")
    g.add_argument("--hours", type=int, default=24)
    p.add_argument("--csv", action="store_true",
                   help="emit out/news_signals_dryrun_<date>.csv after ingest")
    p.add_argument("--csv-fires-only", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    else:
        since = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    counts = run(since)
    if args.csv or args.csv_fires_only:
        emit_csv(since, only_fires=args.csv_fires_only)
    print("\n── ingest summary ──")
    for k, v in counts.items():
        print(f"  {k:12} {v}")


if __name__ == "__main__":
    main()
