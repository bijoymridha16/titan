"""Experimental Economic Times HTML scraper. Gated by NEWS_SCRAPE_ENABLED=1.

ET has Cloudflare bot detection — this WILL get blocked over time and is
not a reliable long-term source. Kept as a fallback in case ET's RSS feeds
go down. Prefer EconomicTimesRSS in production.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Iterable

from bs4 import BeautifulSoup

from titan.config import news_settings
from titan.news.sources._base import NewsSource, RawNews

log = logging.getLogger(__name__)


class EconomicTimesHTML(NewsSource):
    name = "et_html"
    needs_scrape_flag = True

    URLS = [
        "https://economictimes.indiatimes.com/markets/stocks/news",
        "https://economictimes.indiatimes.com/markets/earnings",
    ]
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://economictimes.indiatimes.com/markets",
    }

    def fetch(self, since: datetime) -> Iterable[RawNews]:
        if not news_settings.scrape_enabled:
            log.info("et_html: NEWS_SCRAPE_ENABLED=0, skipping")
            return []
        out: list[RawNews] = []
        for url in self.URLS:
            self.throttle()
            try:
                r = self.http.get(url, headers=self.HEADERS, timeout=30.0)
            except Exception as e:
                log.warning("et_html %s err: %s", url, e)
                continue
            if r.status_code != 200:
                log.warning("et_html %s non-200: %s — likely Cloudflare; consider disabling",
                            url, r.status_code)
                continue
            soup = BeautifulSoup(r.text, "lxml")
            # ET uses <div class="eachStory"> wrapping <h3><a>...</a></h3>
            count_before = len(out)
            for story in soup.select("div.eachStory, div.story-box"):
                a = story.find("a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = a.get("href") or ""
                if not (title and href):
                    continue
                if href.startswith("/"):
                    href = "https://economictimes.indiatimes.com" + href
                sid = hashlib.sha1(href.encode("utf-8")).hexdigest()
                out.append(RawNews(
                    source=self.name,
                    source_id=sid,
                    published_at=datetime.now(timezone.utc),
                    headline=title[:500],
                    body=None,
                    url=href,
                    raw_symbol=None,
                    raw={"listing_url": url},
                ))
            log.info("et_html %s → %d", url, len(out) - count_before)
        log.info("et_html: %d items total", len(out))
        return out
