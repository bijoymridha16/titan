"""Angel One scrip master loader.

Downloads the full instrument list (~80k rows, ~10 MB) once daily and persists
to `instruments` table. Lookups are O(1) via name+exch_seg index.

Master URL:
    https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json

Run as a module to (re)load:
    python -m titan.data.instruments
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import httpx
from sqlalchemy import text

from titan.data.store import engine

log = logging.getLogger(__name__)

MASTER_URL = ("https://margincalculator.angelbroking.com/OpenAPI_File/"
              "files/OpenAPIScripMaster.json")


def _to_int(x) -> int:
    try: return int(float(x)) if x not in (None, "", "-") else 1
    except Exception: return 1


def _to_float(x) -> Optional[float]:
    try: return float(x) if x not in (None, "", "-") else None
    except Exception: return None


def _to_date(x) -> Optional[date]:
    if not x or x == "-": return None
    for fmt in ("%d%b%Y", "%Y-%m-%d", "%d-%b-%Y"):
        try: return datetime.strptime(str(x).upper(), fmt).date()
        except ValueError: continue
    return None


def download_master() -> list[dict]:
    log.info("downloading scrip master from Angel One (~10 MB)…")
    with httpx.Client(timeout=60.0) as c:
        r = c.get(MASTER_URL)
        r.raise_for_status()
        data = r.json()
    log.info("downloaded %d instruments", len(data))
    return data


def persist(rows: list[dict]) -> int:
    sql = text("""
        INSERT INTO instruments
            (exch_seg, token, symbol, name, instrumenttype, expiry, strike,
             lotsize, tick_size, refreshed_at)
        VALUES
            (:exch_seg, :token, :symbol, :name, :instrumenttype, :expiry, :strike,
             :lotsize, :tick_size, now())
        ON CONFLICT (exch_seg, token) DO UPDATE SET
            symbol=EXCLUDED.symbol, name=EXCLUDED.name,
            instrumenttype=EXCLUDED.instrumenttype, expiry=EXCLUDED.expiry,
            strike=EXCLUDED.strike, lotsize=EXCLUDED.lotsize,
            tick_size=EXCLUDED.tick_size, refreshed_at=now()
    """)
    payload = [
        {
            "exch_seg": r.get("exch_seg") or "",
            "token":    str(r.get("token") or ""),
            "symbol":   r.get("symbol") or "",
            "name":     r.get("name") or None,
            "instrumenttype": r.get("instrumenttype") or None,
            "expiry":   _to_date(r.get("expiry")),
            "strike":   _to_float(r.get("strike")),
            "lotsize":  _to_int(r.get("lotsize")),
            "tick_size": _to_float(r.get("tick_size")) or 0.05,
        }
        for r in rows
        if r.get("token") and r.get("exch_seg")
    ]
    with engine().begin() as cx:
        # Chunk inserts; ~80k rows in one execute can spike memory.
        BATCH = 5000
        for i in range(0, len(payload), BATCH):
            cx.execute(sql, payload[i : i + BATCH])
    return len(payload)


# ─────────────── lookup API ───────────────

def lookup(name: str, exch_seg: str = "NSE",
           instrumenttype: str | None = None,
           expiry: date | None = None,
           strike: float | None = None) -> Optional[dict]:
    """Find a single instrument. Returns None if not found, dict on hit."""
    sql_parts = ["name = :name", "exch_seg = :exch"]
    params: dict = {"name": name, "exch": exch_seg}
    if instrumenttype:
        sql_parts.append("instrumenttype = :it")
        params["it"] = instrumenttype
    if expiry:
        sql_parts.append("expiry = :exp")
        params["exp"] = expiry
    if strike is not None:
        sql_parts.append("strike = :strike")
        params["strike"] = strike
    sql = text(f"""
        SELECT exch_seg, token, symbol, name, instrumenttype, expiry, strike,
               lotsize, tick_size
        FROM instruments WHERE {' AND '.join(sql_parts)}
        ORDER BY expiry NULLS FIRST LIMIT 1
    """)
    with engine().connect() as cx:
        row = cx.execute(sql, params).mappings().first()
        return dict(row) if row else None


def resolve_universe(symbols: list[str]) -> list[dict]:
    """Resolve simple names (NIFTY, RELIANCE) to (exch_seg, token) for ticking.
    Indices live in NSE as `AMXIDX`; equities live in NSE as `EQ`. Index futures
    are NFO/FUTIDX (used by strategies but not for plain ticking)."""
    out: list[dict] = []
    for s in symbols:
        # Try index first (NIFTY, BANKNIFTY, FINNIFTY)
        hit = lookup(s, "NSE", instrumenttype="AMXIDX")
        if not hit:
            # Cash equity — Angel master leaves instrumenttype NULL for EQ.
            # Match by suffix "-EQ" on tradingsymbol.
            from sqlalchemy import text
            with engine().connect() as cx:
                row = cx.execute(text("""
                    SELECT exch_seg, token, symbol, name, instrumenttype, expiry,
                           strike, lotsize, tick_size
                    FROM instruments
                    WHERE name = :n AND exch_seg = 'NSE' AND symbol LIKE '%-EQ'
                    LIMIT 1
                """), {"n": s}).mappings().first()
                hit = dict(row) if row else None
        if hit:
            out.append(hit)
        else:
            log.warning("instrument not found: %s", s)
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rows = download_master()
    n = persist(rows)
    log.info("persisted %d instruments", n)


if __name__ == "__main__":
    main()
