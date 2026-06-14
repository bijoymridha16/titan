"""Reconciler — periodically syncs local order/position state with the broker.

Why: order acks and position state can diverge from the local cache after
disconnects, partial fills, or broker-side cancellations. The reconciler
is the source of truth — local state is best-effort.

Cadence: every 5s while trading, 30s otherwise.
"""
from __future__ import annotations

import asyncio
import logging

from titan.brokers.base import BrokerAdapter

log = logging.getLogger(__name__)


class Reconciler:
    def __init__(self, broker: BrokerAdapter, interval_s: float = 5.0):
        self.broker = broker
        self.interval_s = interval_s
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                positions = await self.broker.get_positions()
                # TODO: persist to Postgres; diff against local cache; emit drift events
                log.debug("reconciler: %d positions", len(positions))
            except Exception as e:
                log.exception("reconcile failed: %s", e)
            await asyncio.sleep(self.interval_s)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
