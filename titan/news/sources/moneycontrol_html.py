"""Experimental Moneycontrol HTML scraper. Gated by NEWS_SCRAPE_ENABLED=1.

Scrapes MC's public "Business / Markets" listing pages. Polite throttle,
realistic browser headers, respects robots.txt for the section URLs we use
(verified 2026-06: /news/business, /news/markets allowed; /rss/ allowed).

ToS caveat: MC's general ToS prohibit "automated extraction." This is
research-only; do not redistribute scraped content. If MC starts returning
403 or Cloudflare challenges, stop and respect that.
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


class MoneycontrolHTML(NewsSource):
    name = "mc_html"
    needs_scrape_flag = True

    URLS = [
        "https://www.moneycontrol.com/news/business/markets/",
        "https://www.moneycontrol.com/news/business/earnings/",
        "https://www.moneycontrol.com/news/business/companies/",
    ]
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    def fetch(self, since: datetime) -> Iterable[RawNews]:
        if not news_settings.scrape_enabled:
            log.info("mc_html: NEWS_SCRAPE_ENABLED=0, skipping")
            return []
        out: list[RawNews] = []
        for url in self.URLS:
            self.throttle()
            try:
                r = self.http.get(url, headers=self.HEADERS, timeout=30.0)
            except Exception as e:
                log.warning("mc_html %s err: %s", url, e)
                continue
            if r.status_code != 200:
                log.warning("mc_html %s non-200: %s", url, r.status_code)
                continue
            soup = BeautifulSoup(r.text, "lxml")
            # MC listing pages: <li class="clearfix"> with <h2><a>headline</a></h2>
            for li in soup.select("li.clearfix"):
                a = li.find("a")
                if not a:
                    continue
                title = (a.get_text(strip=True) or "").strip()
                href = a.get("href") or ""
                if not (title and href and href.startswith("http")):
                    continue
                # MC sometimes puts the date in <span class="article_schedule">
                ts = li.find(class_="article_schedule")
                # we don't always have a reliable timestamp from the listing —
                # default to fetch-time minus a small offset; dedup by URL hash.
                published = datetime.now(timezone.utc)
                sid = hashlib.sha1(href.encode("utf-8")).hexdigest()
                out.append(RawNews(
                    source=self.name,
                    source_id=sid,
                    published_at=published,
                    headline=title[:500],
                    body=None,
                    url=href,
                    raw_symbol=None,
                    raw={"listing_url": url, "schedule": ts.get_text(strip=True) if ts else None},
                ))
        log.info("mc_html: %d items", len(out))
        return out
