"""Distributed order-dispatch lock — prevents duplicate orders on timeouts.

Manifesto Scenario A: when `placeOrder` times out, the dispatcher doesn't know
whether the order reached the exchange. A naive retry double-fires. This guards
each (strategy, symbol) dispatch with a short-lived Redis lock:

- Acquire (SET NX EX) before sending. If the lock is already held, a dispatch is
  already in flight → refuse the duplicate.
- On a DEFINITE broker response (accepted or rejected) → release immediately.
- On an AMBIGUOUS outcome (exception/timeout) → KEEP the lock until its TTL so a
  retry can't double-fire; the order must be reconciled via the broker's order
  details before the symbol is freed.

Pure helpers over a redis-like client (`set(name, value, nx=, ex=)`, `delete`)
so they unit-test without a live Redis.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def order_lock_key(strategy: str, symbol: str) -> str:
    return f"titan:lock:order:{strategy}:{symbol}"


def acquire_order_lock(r, key: str, ttl_s: int, token: str) -> bool:
    """Try to take the lock. True if acquired, False if already held."""
    if r is None:
        return True   # idempotency disabled → always proceed
    try:
        return bool(r.set(key, token, nx=True, ex=ttl_s))
    except Exception as e:
        log.warning("order lock acquire failed (%s) — proceeding without lock", e)
        return True


def release_order_lock(r, key: str) -> None:
    if r is None:
        return
    try:
        r.delete(key)
    except Exception as e:
        log.warning("order lock release failed (%s)", e)
