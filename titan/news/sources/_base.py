"""Shared scaffolding for news sources.

Every adapter implements `fetch(since: datetime) -> Iterable[RawNews]`. The
batch ingest runner is responsible for dedup + persist to news_events; adapters
only emit normalised records.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import httpx

from titan.config import news_settings

log = logging.getLogger(__name__)


@dataclass
class RawNews:
    source: str
    source_id: str                      # MUST be stable for dedup
    published_at: datetime              # tz-aware
    headline: str
    body: Optional[str] = None
    url: Optional[str] = None
    raw_symbol: Optional[str] = None    # e.g. "RELIANCE" if the source supplies it
    raw: dict[str, Any] = field(default_factory=dict)


class NewsSource(ABC):
    name: str = "abstract"
    needs_scrape_flag: bool = False     # True for HTML scrapers; gated by env

    def __init__(self):
        self._http: Optional[httpx.Client] = None
        self._last_req_at: float = 0.0

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                timeout=news_settings.http_timeout,
                headers={
                    "User-Agent": news_settings.user_agent,
                    "Accept-Language": "en-IN,en;q=0.9",
                },
                follow_redirects=True,
            )
        return self._http

    def throttle(self) -> None:
        """Block until at least rate_sleep_s seconds have passed since the
        previous request from this source. Polite-citizen behaviour."""
        gap = time.monotonic() - self._last_req_at
        if gap < news_settings.rate_sleep_s:
            time.sleep(news_settings.rate_sleep_s - gap)
        self._last_req_at = time.monotonic()

    @abstractmethod
    def fetch(self, since: datetime) -> Iterable[RawNews]: ...

    def close(self) -> None:
        if self._http:
            self._http.close()
            self._http = None


def parse_dt(s: str, fmts: list[str], default_tz=timezone.utc) -> Optional[datetime]:
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=default_tz) if dt.tzinfo is None else dt
        except (ValueError, TypeError):
            continue
    return None
