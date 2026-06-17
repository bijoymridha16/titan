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
from fastapi.middleware.cors import CORSMiddleware

from titan.config import settings

KILL_KEY = "titan:kill"

app = FastAPI(title="TITAN Control Plane", version="0.0.1")
# allow the React dev server (and any local origin) to call the API in dev
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
_redis: redis.Redis | None = None
_db = None


def r() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


# ─── read API for the React front-end (thin wrappers over the dashboard queries) ───
def _rows(sql: str, **params) -> list[dict]:
    """Run a query and return list[dict]. Read-only; safe defaults on error."""
    try:
        from sqlalchemy import create_engine, text
        global _db
        if _db is None:
            _db = create_engine(settings.db_url, pool_pre_ping=True)
        with _db.connect() as cx:
            res = cx.execute(text(sql), params)
            return [dict(row) for row in res.mappings().all()]
    except Exception:
        return []


@app.get("/data/bars")
def data_bars(symbol: str, tf: str = "5m", n: int = 200):
    rows = _rows("""SELECT ts, o, h, l, c, v FROM ohlcv
                    WHERE symbol=:s AND timeframe=:tf ORDER BY ts DESC LIMIT :n""",
                 s=symbol, tf=tf, n=n)
    return list(reversed(rows))


@app.get("/data/trades")
def data_trades(limit: int = 100):
    return _rows("""SELECT id, strategy, symbol, side, qty, entry_ts, entry_price,
                           exit_ts, exit_price, pnl, exit_reason, regime, stop_loss, target
                    FROM trades ORDER BY entry_ts DESC LIMIT :n""", n=limit)


@app.get("/data/positions")
def data_positions():
    return _rows("""SELECT strategy, symbol, side, qty, entry_price, stop_loss, target, entry_ts
                    FROM trades WHERE exit_ts IS NULL ORDER BY entry_ts DESC""")


@app.get("/data/leaderboard")
def data_leaderboard(limit: int = 60):
    return _rows("""SELECT variant_key, family, trades, sharpe, deflated_threshold,
                           profit_factor, max_dd_pct, verdict, reasons
                    FROM leaderboard ORDER BY sharpe DESC LIMIT :n""", n=limit)


@app.get("/data/analytics/funnel")
def data_funnel():
    return _rows("""SELECT COALESCE(reject_reason,'(accepted)') reason, COUNT(*) n
                    FROM signals GROUP BY reason ORDER BY n DESC LIMIT 12""")


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
    from titan import clock
    killed = await r().get(KILL_KEY)
    sim = await r().get(clock.SIM_KEY)
    sim_on = (sim == "1") if sim is not None else settings.sim_mode
    return {
        "mode": settings.mode,
        "env": settings.env,
        "capital": settings.capital,
        "kill_switch": killed == "1",
        "sim_mode": sim_on,
        "market_open": clock.is_market_open(),
        "server_time_ist": clock.real_now().strftime("%Y-%m-%d %H:%M:%S"),
        "universe": settings.symbols,
        "limits": {
            "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "max_daily_profit_pct": settings.max_daily_profit_pct,
            "max_drawdown_pct": settings.max_drawdown_pct,
        },
    }


@app.get("/sim")
async def sim_status():
    """Is the explicit SIMULATION clock on? In real mode, trading is gated to
    real NSE hours and nothing trades when the market is closed."""
    from titan import clock
    v = await r().get(clock.SIM_KEY)
    sim_on = (v == "1") if v is not None else settings.sim_mode
    return {
        "sim_mode": sim_on,
        "source": "redis" if v is not None else "config_default",
        "market_open": clock.is_market_open(),
        "server_time_ist": clock.real_now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.post("/sim/on")
async def sim_on():
    """Explicitly enable the labeled simulation clock (rehearse when market closed)."""
    from titan import clock
    await r().set(clock.SIM_KEY, "1")
    return {"ok": True, "sim_mode": True}


@app.post("/sim/off")
async def sim_off():
    """Return to honest real-clock mode — trading only during real NSE hours."""
    from titan import clock
    await r().set(clock.SIM_KEY, "0")
    return {"ok": True, "sim_mode": False}


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


# ─────────────── auto-pilot (decision-driven strategy selection) ───────────────
AUTOPILOT_KEY = "titan:autopilot:enabled"


@app.get("/autopilot")
async def autopilot_status():
    """Current auto-pilot arm state + last regime decision (for dashboard/ops)."""
    armed = await r().get(AUTOPILOT_KEY)
    armed_bool = (armed == "1") if armed is not None else settings.autopilot_enabled
    return {
        "armed": armed_bool,
        "source": "redis" if armed is not None else "config_default",
        "validated_strategies": sorted(settings.autopilot_validated_set),
        "ref_symbol": settings.autopilot_ref_symbol,
        "interval_s": settings.autopilot_interval_s,
        "regime": await r().get("titan:regime:current"),
        "regime_reason": await r().get("titan:regime:reason"),
        "enabled_now": sorted(await r().smembers("titan:strategies:enabled") or []),
    }


@app.post("/autopilot/arm")
async def autopilot_arm():
    """Hand the keys to the decision engine: it now owns its validated lane."""
    await r().set(AUTOPILOT_KEY, "1")
    return {"ok": True, "armed": True}


@app.post("/autopilot/disarm")
async def autopilot_disarm():
    """Drop to observe-only: auto-pilot keeps classifying + logging but stops
    touching the enabled set. Existing positions are unaffected (use /flatten)."""
    await r().set(AUTOPILOT_KEY, "0")
    return {"ok": True, "armed": False}


# Strategies killed by walk-forward — single source of truth in the registry.
# To re-enable, run the backtest, get a SHIP verdict, then remove it there.
from titan.strategies.registry import KILLED_STRATEGIES

VALIDATED_KEY = "titan:autopilot:validated"


async def _validated_set() -> set[str]:
    """The strategies cleared to trade. Live-updatable via Redis (set by the
    promotion job); falls back to the .env default."""
    rv = await r().smembers(VALIDATED_KEY)
    return set(rv) if rv else set(settings.autopilot_validated_set)


@app.post("/strategies/{name}/start")
async def start(name: str, force: bool = False):
    """Enable a strategy. By default only VALIDATED (walk-forward-passed)
    strategies may be enabled — closing AUTOPSY_FINDINGS H1 for the manual path
    too. Pass ?force=true to override for deliberate experimentation."""
    if not name.isidentifier():
        raise HTTPException(400, "invalid name")
    if name in KILLED_STRATEGIES:
        raise HTTPException(
            409, f"{name} was killed by walk-forward backtest; not enableable.")
    validated = await _validated_set()
    if name not in validated and not force:
        raise HTTPException(
            409,
            f"{name} is not on the validated allowlist {sorted(validated)}. "
            "Pass it through the walk-forward gate (titan.backtest.walk_forward) "
            "and promote it, or use ?force=true to override deliberately.",
        )
    await r().sadd("titan:strategies:enabled", name)
    return {"ok": True, "started": name, "forced": force and name not in validated}


@app.post("/strategies/{name}/stop")
async def stop(name: str):
    await r().srem("titan:strategies:enabled", name)
    return {"ok": True, "stopped": name}


def run():
    import uvicorn
    uvicorn.run("titan.api.main:app", host="0.0.0.0",
                port=int(os.getenv("PORT", 8000)), reload=False)
