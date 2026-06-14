"""NSE corporate announcements ingester.

The official NSE corporate-announcements feed lives at
    https://www.nseindia.com/api/corporate-announcements?index=equities

It requires a cookie/session handshake first: an unauthenticated GET to
www.nseindia.com sets `nsit` / `nseappid` cookies that the API requires.
Without it the API returns 401/403. This is the standard NSE retail-API
dance — well documented in third-party clients (nsetools, nsepy, etc.).

We re-handshake on every batch run. Polite throttle between requests.
Returns one RawNews per announcement.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from titan.news.sources._base import NewsSource, RawNews, parse_dt

log = logging.getLogger(__name__)

BASE = "https://www.nseindia.com"
ANN_URL = f"{BASE}/api/corporate-announcements?index=equities"
HANDSHAKE_URL = f"{BASE}/companies-listing/corporate-filings-announcements"

NSE_DT_FORMATS = ["%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]


class NSECorpAnn(NewsSource):
    name = "nse_ann"

    # NSE explicitly blocks non-browser UAs and demands a full header set.
    BROWSER_HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/webp,*/*;q=0.8"),
        "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    def _handshake(self) -> None:
        self.throttle()
        try:
            r = self.http.get(HANDSHAKE_URL, headers=self.BROWSER_HEADERS,
                              timeout=30.0)
            if r.status_code != 200:
                log.warning("nse handshake non-200: %s", r.status_code)
        except Exception as e:
            log.warning("nse handshake error: %s", e)

    def fetch(self, since: datetime) -> Iterable[RawNews]:
        self._handshake()
        self.throttle()
        try:
            r = self.http.get(ANN_URL, headers={
                **self.BROWSER_HEADERS,
                "Accept": "application/json, text/plain, */*",
                "Referer": HANDSHAKE_URL,
                "X-Requested-With": "XMLHttpRequest",
            }, timeout=30.0)
        except Exception as e:
            log.warning("nse fetch error: %s", e)
            return []
        if r.status_code != 200:
            log.warning("nse ann non-200: %s body=%s", r.status_code, r.text[:200])
            return []
        try:
            data = r.json()
        except Exception as e:
            log.warning("nse non-json: %s body=%s", e, r.text[:200])
            return []

        rows = data if isinstance(data, list) else data.get("data") or data.get("rows") or []
        out: list[RawNews] = []
        for row in rows:
            symbol = (row.get("symbol") or "").strip().upper()
            company = (row.get("sm_name") or "").strip()
            category = (row.get("desc") or "").strip()         # e.g. "General Updates"
            subject = (row.get("attchmntText") or row.get("more_link_desc") or "").strip()
            # headline is the actual subject; fall back to category+company.
            headline = subject or f"{company}: {category}".strip(": ").strip()
            an_dt = row.get("an_dt") or row.get("sort_date")
            url = row.get("attchmntFile")
            published = parse_dt(str(an_dt), NSE_DT_FORMATS) or datetime.now(timezone.utc)
            if published.replace(tzinfo=published.tzinfo or timezone.utc) < since:
                continue
            source_id = str(row.get("seq_id") or row.get("attchmntFile")
                            or f"{symbol}|{an_dt}|{headline[:60]}")
            out.append(RawNews(
                source=self.name,
                source_id=source_id,
                published_at=published.astimezone(timezone.utc),
                headline=headline[:500] or f"NSE filing: {symbol}",
                body=subject if subject != headline else None,
                url=url,
                raw_symbol=symbol or None,
                raw=row,
            ))
        log.info("nse_ann: %d announcements since %s", len(out), since.date())
        return out
