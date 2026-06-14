# News-Driven Event Trading (NDET) — v1

**Status:** Phase 1 build → Gate review → ship/kill decision
**Last updated:** 2026-06-14

## 1. What we're building

A batch pipeline that turns Indian equity headlines into trading signals:

```
ingest sources → dedup → entity-map to NSE ticker → FinBERT sentiment →
  category classifier → would_fire decision → dry-run CSV (Gate) →
    [if Gate passes] NewsStrategy → existing RiskEngine → broker
```

The "Gate" is mandatory and predates any trading code. We produce ≥5 trading
days of `out/news_signals_dryrun_<date>.csv` and review the signal quality
before writing `NewsStrategy`.

## 2. Academic basis

Two well-documented phenomena drive earnings-surprise momentum, the v1 strategy:

1. **Post-Earnings Announcement Drift (PEAD)** — Bernard & Thomas (1989) on US
   data, and Sehgal & Bijoy (2015) on India: stocks that beat earnings consensus
   drift *up* for ~3–60 days post-announcement. Drift magnitude scales with the
   *magnitude* of the surprise.
2. **Initial under-reaction** — first-day move captures ~40% of the eventual
   60-day drift in US data, less in India where information flows slower. The
   gap is our edge: trade the next-open after a positive earnings headline,
   exit at end-of-day.

For India specifically:
- **Sehgal, Bijoy (2015)** — *Indian Journal of Finance* — PEAD on BSE-500
  2003-2013. Quintile 5 (highest surprise) beat Quintile 1 by ~8%/year, t-stat
  3.1. Net of 0.5% round-trip costs, the spread halves but stays positive.
- **Tijori / Trendlyne quarterly reports** — repeatable 0.7–1.4% next-day
  return on top-decile surprise; 0.3–0.6% net after MIS costs at retail size.

What we will NOT claim:
- That FinBERT-tagged "positive" maps cleanly to "earnings beat." It tags
  sentiment, not surprise. Many "positive" earnings headlines are
  pre-announced guidance reaffirmations with no surprise → no drift.
- That we'll capture the full drift in a single intraday window. Most of the
  drift literature is multi-day; intraday capture is the *fastest, noisiest*
  slice.

## 3. Sources (v1)

| Source | Type | Latency | Reliability | Default |
|---|---|---|---|---|
| NSE corporate announcements | Official JSON API | seconds | highest | ON |
| BSE corporate announcements | Official JSON API | seconds | highest | ON |
| Moneycontrol RSS | Public RSS | minutes | high | ON |
| Economic Times RSS | Public RSS | minutes | high | ON |
| Moneycontrol HTML | Scrape | seconds | medium (ToS, Cloudflare) | **OFF** (`NEWS_SCRAPE_ENABLED=0`) |
| Economic Times HTML | Scrape | seconds | medium (Cloudflare bot detection) | **OFF** |

The official + RSS combination is expected to produce 50–150 deduped
headlines per trading day for NIFTY-50 names. Scraping is wired but
default-disabled — user flips on after seeing the official signal quality.

## 4. Pipeline stages

### 4a. Ingest
Batch job. CLI: `python -m titan.news.ingest --since 2026-06-01`.
Each adapter pulls its source, normalises to `news_events` (source, source_id,
published_at, headline, body, url, raw_symbol). Idempotent: `UNIQUE (source,
source_id)` collisions are skipped.

### 4b. Entity mapping
`titan/news/entities.py`. Three-pass match against `config/nifty50_aliases.yaml`:
1. Exact match on `raw_symbol` (NSE/BSE supply ticker directly) → confidence 1.0
2. Alias match on the headline text against the curated list → 0.85
3. `rapidfuzz` fallback against all NIFTY-50 names → confidence = ratio/100, drop below 0.7

Multi-symbol headlines (e.g. "Adani group stocks rally") split to multiple rows.

### 4c. FinBERT sentiment
`titan/news/sentiment.py`. Loads `ProsusAI/finbert` (~440MB) once, batched
inference (16 headlines/batch). Cached by sha256(model_id + headline) in
`sentiment_cache` so re-runs are free. Returns `{label, score, neg_p, neu_p,
pos_p}`. CPU latency ~100ms/headline on M1.

### 4d. Category classifier
`titan/news/category.py`. Rules-based — not ML, no labelled data yet:

| Category | Trigger (case-insensitive regex) |
|---|---|
| `earnings` | results, profit, revenue, ebitda, q[1-4]fy, eps, beat/miss |
| `m_and_a` | acquire, acquisition, merger, takeover, stake purchase |
| `regulatory` | sebi, rbi, cci, penalty, fine, ban, raid |
| `dividend` | dividend, record date, bonus issue, buyback |
| `block_deal` | block deal, bulk deal, large trade, stake sale |
| `other` | (default) |

`block_deal` is on the **noise list** — flagged but `would_fire=false`.

### 4e. "would_fire" decision (v1 — earnings-surprise momentum)

A signal fires iff:
- `category == "earnings"` AND
- `sentiment_label == "positive"` AND `sentiment_score > 0.70` AND
- `entity_conf > 0.7` AND
- ticker is in NIFTY-50 AND
- `published_at` is within the last 18 trading hours (no stale signals)

These thresholds will be tuned only on the dry-run CSV review, never on backtest P&L.

## 5. What we measure during the Gate

For ≥5 trading days of dry-run output, look at:

| Metric | Target | Killer if … |
|---|---|---|
| Headlines/day | 50–500 | < 20 (sources broken) or > 5000 (too noisy) |
| Distinct tickers/day with `would_fire` | 1–5 | 0 means trigger never fires |
| Entity-mapping precision (manual review of 50) | ≥ 80% | < 60% — fix aliases |
| Sentiment plausibility (manual review of 50) | ≥ 70% agree | < 50% — try yiyanghkust/finbert-tone |
| `would_fire` rows with same-day OHLCV move ≥ +0.5% | ≥ 50% | < 30% means signal has no edge |

That last metric is the real gate. If positive-sentiment earnings headlines do
not coincide with positive next-day moves on this universe ≥50% of the time,
the strategy has no edge and we kill it before writing the trading half.

## 6. SEBI compliance posture

- ₹5K own-capital retail trading, below algo-registration threshold per SEBI's
  2024 Algo Trading Framework
- `ALGO_ID` env var supported but optional; tagged onto orders if set
- All orders go through the existing 5-gate live broker path (`live_enabled`,
  product whitelist, exchange whitelist, notional cap, dry-run)
- News signals are logged to `news_signals` with `would_fire` reasoning —
  satisfies the SEBI audit-trail requirement should it apply later

## 7. What's explicitly out of scope for v1

- LLM summarization of bodies
- Twitter/X sentiment (legal grey zone)
- Earnings transcript NLP (no transcript vendor)
- Hindi-language headlines
- Multi-day holding period (intraday only v1)
- Short signals (no shorting at ₹5K MIS cash)
- Reinforcement-learning execution timing
