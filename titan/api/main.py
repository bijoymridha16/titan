"""FastAPI control plane.

Endpoints:
    GET  /status        — mode, equity, positions, risk state
    POST /kill          — flip the kill switch (sticky; clears on restart only)
    POST /flatten       — close all open positions at market
    GET  /strategies    — list registered strategies + status
    POST /strategies/{name}/start
    POST /strategies/{name}/stop

Auth: none by default. Behind a reverse proxy with IP allowlist + Basic Auth.
NEVER expose this port publicly without auth — it can flatten or kill the system.
"""
from __future__ import annotations

import os

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException

from titan.config import settings

KILL_KEY = "titan:kill"

app = FastAPI(title="TITAN Control Plane", version="0.0.1")
_redis: redis.Redis | None = None


def r() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


@app.get("/auth/test")
async def auth_test():
    """Live SmartAPI login + funds fetch. Use ONLY for smoke testing.
    Returns scrubbed funds (no token leakage) or a clear error."""
    from titan.brokers.angelone import AngelOneBroker, AngelOneAuthError
    b = AngelOneBroker()
    try:
        await b.connect()
        funds = await b.get_funds()
        return {
            "ok": True,
            "login": "success",
            "feed_token_present": bool(b.feed_token),
            "funds": {
                "net":            funds.get("net"),
                "availablecash":  funds.get("availablecash"),
                "availableintradaypayin": funds.get("availableintradaypayin"),
                "utiliseddebits": funds.get("utiliseddebits"),
            },
        }
    except AngelOneAuthError as e:
        raise HTTPException(401, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.get("/status")
async def status():
    killed = await r().get(KILL_KEY)
    return {
        "mode": settings.mode,
        "env": settings.env,
        "capital": settings.capital,
        "kill_switch": killed == "1",
        "universe": settings.symbols,
        "limits": {
            "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "max_drawdown_pct": settings.max_drawdown_pct,
        },
    }


@app.post("/kill")
async def kill(reason: str = "manual"):
    await r().set(KILL_KEY, "1")
    await r().set(KILL_KEY + ":reason", reason)
    return {"ok": True, "kill_switch": True, "reason": reason}


@app.post("/flatten")
async def flatten():
    # Publishes a flatten request; strategy supervisors consume it and submit
    # market exits for every open position. Synchronous flattening is broker-
    # specific and lives in the supervisor, not here.
    await r().publish("titan:control", "FLATTEN")
    return {"ok": True, "broadcast": "FLATTEN"}


@app.get("/strategies")
async def strategies():
    keys = await r().smembers("titan:strategies")
    return {"strategies": sorted(keys)}


# Strategies killed by walk-forward — kept in code for future re-evaluation
# but blocked from activation. To re-enable, run the backtest, get a SHIP
# verdict in docs/research/, then remove from this set.
KILLED_STRATEGIES = {"tsmom"}


@app.post("/strategies/{name}/start")
async def start(name: str):
    if not name.isidentifier():
        raise HTTPException(400, "invalid name")
    if name in KILLED_STRATEGIES:
        raise HTTPException(
            409,
            f"{name} was killed by walk-forward backtest; "
            "see docs/research/ for the verdict before re-enabling",
        )
    await r().sadd("titan:strategies:enabled", name)
    return {"ok": True, "started": name}


@app.post("/strategies/{name}/stop")
async def stop(name: str):
    await r().srem("titan:strategies:enabled", name)
    return {"ok": True, "stopped": name}


def run():
    import uvicorn
    uvicorn.run("titan.api.main:app", host="0.0.0.0",
                port=int(os.getenv("PORT", 8000)), reload=False)
