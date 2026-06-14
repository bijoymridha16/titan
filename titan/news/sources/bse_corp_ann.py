"""BSE corporate announcements ingester.

BSE's `AnnSubCategoryGetData` endpoint takes:
    strCat, strPrevDate (DD/MM/YYYY), strScrip, strSearch, strToDate, strType, subcategory
Returns JSON with a `Table` list of announcement rows. Fields we care about:
    NEWSID            unique id           → source_id
    NEWS_DT (ISO)     announcement time   → published_at
    NEWSSUB           subject             → headline
    HEADLINE          short subject       → fallback
    SCRIP_CD          numeric BSE code    → raw
    SLONGNAME         company             → raw
    NSURL             attachment URL      → url

Same browser-header trick as NSE; BSE is less hostile but still wants a UA.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from titan.news.sources._base import NewsSource, RawNews, parse_dt

log = logging.getLogger(__name__)

API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
REFERER = "https://www.bseindia.com/corporates/ann.html"

BSE_DT_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
    "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S",
]


class BSECorpAnn(NewsSource):
    name = "bse_ann"

    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Referer": REFERER,
        "Origin": "https://www.bseindia.com",
    }

    # BSE's date-filter params are flaky; omitting them and paginating
    # by `pageno` reliably returns most-recent-first announcements. We
    # paginate until we cross `since` or hit MAX_PAGES.
    MAX_PAGES = 25

    def fetch(self, since: datetime) -> Iterable[RawNews]:
        out: list[RawNews] = []
        for page in range(1, self.MAX_PAGES + 1):
            params = {
                "pageno": str(page),
                "strCat": "-1",
                "strScrip": "",
                "strSearch": "P",
                "strType": "C",
                "subcategory": "-1",
            }
            self.throttle()
            try:
                r = self.http.get(API, params=params, headers=self.HEADERS,
                                  timeout=30.0)
            except Exception as e:
                log.warning("bse fetch p=%d error: %s", page, e)
                break
            if r.status_code != 200:
                log.warning("bse p=%d non-200: %s", page, r.status_code)
                break
            try:
                data = r.json()
            except Exception:
                break
            rows = data.get("Table") or []
            if not rows:
                break
            page_out, oldest = self._normalize(rows, since)
            out.extend(page_out)
            if oldest is not None and oldest < since:
                break
        log.info("bse_ann: %d announcements since %s", len(out), since.date())
        return out

    def _normalize(self, rows: list, since: datetime
                   ) -> tuple[list[RawNews], datetime | None]:
        out: list[RawNews] = []
        oldest: datetime | None = None
        out: list[RawNews] = []
        for row in rows:
            nid = str(row.get("NEWSID") or "").strip()
            news_dt = row.get("NEWS_DT") or row.get("DT_TM")
            published = parse_dt(str(news_dt), BSE_DT_FORMATS) or datetime.now(timezone.utc)
            published = published.replace(tzinfo=published.tzinfo or timezone.utc)
            oldest = published if oldest is None or published < oldest else oldest
            if published < since:
                continue
            headline = (row.get("NEWSSUB") or row.get("HEADLINE") or "").strip()
            company  = (row.get("SLONGNAME") or "").strip()
            scrip_cd = str(row.get("SCRIP_CD") or "").strip() or None
            url = row.get("NSURL") or row.get("ATTACHMENTNAME")
            out.append(RawNews(
                source=self.name,
                source_id=nid or f"{scrip_cd}|{news_dt}|{headline[:60]}",
                published_at=published.astimezone(timezone.utc),
                headline=(headline or f"{company}: BSE filing")[:500],
                body=None,
                url=url,
                raw_symbol=None,
                raw={**row, "_bse_scrip_cd": scrip_cd, "_bse_company": company},
            ))
        return out, oldest
