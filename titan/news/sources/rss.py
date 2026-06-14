"""RSS-based news sources. Public feeds, no ToS issue. Used for MC + ET.

Each concrete class just declares `name` and a list of feed URLs.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Iterable

import feedparser

from titan.news.sources._base import NewsSource, RawNews

log = logging.getLogger(__name__)


class _RSSBase(NewsSource):
    feeds: list[str] = []

    extra_headers: dict[str, str] = {}

    def fetch(self, since: datetime) -> Iterable[RawNews]:
        out: list[RawNews] = []
        for url in self.feeds:
            self.throttle()
            try:
                r = self.http.get(url, headers={
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                    **self.extra_headers,
                })
                if r.status_code != 200:
                    log.warning("%s rss %s non-200: %s", self.name, url, r.status_code)
                    continue
                parsed = feedparser.parse(r.content)
            except Exception as e:
                log.warning("%s rss %s err: %s", self.name, url, e)
                continue
            for entry in parsed.entries:
                published = _entry_dt(entry)
                if published < since:
                    continue
                title = (entry.get("title") or "").strip()
                if not title:
                    continue
                link = entry.get("link") or ""
                sid = entry.get("id") or link or hashlib.sha1(
                    (title + str(published)).encode("utf-8")).hexdigest()
                summary = (entry.get("summary") or entry.get("description") or "").strip()
                out.append(RawNews(
                    source=self.name,
                    source_id=str(sid)[:512],
                    published_at=published,
                    headline=title[:500],
                    body=summary[:2000] if summary else None,
                    url=link or None,
                    raw_symbol=None,
                    raw={"feed": url, "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")]},
                ))
        log.info("%s: %d items since %s", self.name, len(out), since.date())
        return out


def _entry_dt(entry) -> datetime:
    for k in ("published_parsed", "updated_parsed"):
        tt = entry.get(k)
        if tt:
            try:
                return datetime(*tt[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


class MoneycontrolRSS(_RSSBase):
    # NOTE: as of 2026, MC's published /rss/*.xml endpoints respond 200 with
    # a stale shell (lastBuildDate frozen in 2016) and no items. Kept here as
    # a stub for whenever MC reinstates the feed; in the meantime we rely on
    # ET RSS + the experimental MC HTML scraper (gated by NEWS_SCRAPE_ENABLED).
    name = "mc_rss"
    feeds = [
        "https://www.moneycontrol.com/rss/MCtopnews.xml",
    ]
    extra_headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Referer": "https://www.moneycontrol.com/",
        "Accept-Encoding": "gzip, deflate",
    }


class EconomicTimesRSS(_RSSBase):
    name = "et_rss"
    feeds = [
        # ET section IDs are stable. Markets / Stocks-News / Earnings.
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        "https://economictimes.indiatimes.com/markets/earnings/rssfeeds/1808634275.cms",
        "https://economictimes.indiatimes.com/news/company/corporate-trends/rssfeeds/1809375600.cms",
    ]
