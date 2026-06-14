"""Telegram alerts. Fire-and-forget; never raises into trading logic."""
from __future__ import annotations

import logging

import httpx

from titan.config import alert_settings

log = logging.getLogger(__name__)


async def telegram(text: str) -> None:
    cfg = alert_settings
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        log.debug("telegram: not configured, skipping: %s", text[:120])
        return
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(url, json={"chat_id": cfg.telegram_chat_id, "text": text})
    except Exception as e:
        log.warning("telegram alert failed: %s", e)


SEVERITY_PREFIX = {
    "info": "ℹ️", "warn": "⚠️", "error": "🚨", "kill": "🛑",
}


async def alert(severity: str, msg: str) -> None:
    await telegram(f"{SEVERITY_PREFIX.get(severity, '')} [TITAN] {msg}")
