"""Best-effort analytics recorder.

Every function swallows its own exceptions and logs a warning — capturing a row
must NEVER raise into the trading loop. The engine is injectable so this is unit
-testable without a database.

Design notes:
  • IDs are app-generated UUIDs (strings) so callers can link rows
    (signal → order_attempt → fill) without a DB round-trip.
  • The same error-isolation pattern the supervisor/selector already use:
    log and move on.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from titan.data.store import engine as default_engine

log = logging.getLogger(__name__)


def new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_signal(
    *, signal_id: str, strategy: str, symbol: str, kind: str,
    entry: Optional[float], stop: Optional[float], target: Optional[float],
    per_unit_risk: Optional[float], confidence: Optional[float],
    regime: Optional[str], accepted: bool, reject_reason: Optional[str],
    order_id: Optional[str], reason: str, engine=None,
) -> None:
    eng = engine or default_engine()
    try:
        with eng.begin() as cx:
            cx.execute(text("""
                INSERT INTO signals
                  (id, ts, strategy, symbol, kind, entry, stop, target,
                   per_unit_risk, confidence, regime, accepted, reject_reason,
                   order_id, reason)
                VALUES (:id, :ts, :st, :sym, :k, :e, :sl, :tg, :pur, :cf, :rg,
                        :acc, :rej, :oid, :rsn)
            """), {
                "id": signal_id, "ts": _now(), "st": strategy, "sym": symbol,
                "k": kind, "e": entry, "sl": stop, "tg": target,
                "pur": per_unit_risk, "cf": confidence, "rg": regime,
                "acc": accepted, "rej": reject_reason, "oid": order_id,
                "rsn": reason,
            })
    except Exception as ex:  # never break the trading loop on a log write
        log.warning("record_signal failed: %s", ex)


def record_order_attempt(
    *, order_id: str, signal_id: Optional[str], strategy: str, symbol: str,
    side: str, qty_requested: Optional[int], qty_final: Optional[int],
    order_type: str, product: str, price: Optional[float],
    risk_approved: bool, risk_reason: Optional[str], broker: str,
    status: Optional[str], broker_order_id: Optional[str],
    avg_fill_price: Optional[float], reject_reason: Optional[str], engine=None,
) -> None:
    eng = engine or default_engine()
    try:
        with eng.begin() as cx:
            cx.execute(text("""
                INSERT INTO order_attempts
                  (id, ts, signal_id, strategy, symbol, side, qty_requested,
                   qty_final, order_type, product, price, risk_approved,
                   risk_reason, broker, status, broker_order_id, avg_fill_price,
                   reject_reason)
                VALUES (:id, :ts, :sig, :st, :sym, :sd, :qr, :qf, :ot, :pr, :px,
                        :ra, :rr, :bk, :stt, :boid, :afp, :rej)
            """), {
                "id": order_id, "ts": _now(), "sig": signal_id, "st": strategy,
                "sym": symbol, "sd": side, "qr": qty_requested, "qf": qty_final,
                "ot": order_type, "pr": product, "px": price, "ra": risk_approved,
                "rr": risk_reason, "bk": broker, "stt": status,
                "boid": broker_order_id, "afp": avg_fill_price, "rej": reject_reason,
            })
    except Exception as ex:
        log.warning("record_order_attempt failed: %s", ex)


def record_fill(
    *, order_id: str, strategy: str, symbol: str, side: str, qty: int,
    fill_price: float, ltp_at_decision: Optional[float],
    modeled_slippage_bps: Optional[float], is_paper: bool = True, engine=None,
) -> None:
    eng = engine or default_engine()
    realized = None
    if ltp_at_decision and ltp_at_decision > 0 and fill_price:
        # realized slippage vs the reference price, signed against trade direction
        diff = (fill_price - ltp_at_decision) / ltp_at_decision * 10_000.0
        realized = diff if side == "BUY" else -diff
    try:
        with eng.begin() as cx:
            cx.execute(text("""
                INSERT INTO fills
                  (id, ts, order_id, strategy, symbol, side, qty, fill_price,
                   ltp_at_decision, modeled_slippage_bps, realized_slippage_bps,
                   is_paper)
                VALUES (:id, :ts, :oid, :st, :sym, :sd, :q, :fp, :ltp, :msb,
                        :rsb, :paper)
            """), {
                "id": new_id(), "ts": _now(), "oid": order_id, "st": strategy,
                "sym": symbol, "sd": side, "q": qty, "fp": fill_price,
                "ltp": ltp_at_decision, "msb": modeled_slippage_bps,
                "rsb": realized, "paper": is_paper,
            })
    except Exception as ex:
        log.warning("record_fill failed: %s", ex)


def record_feature_snapshot(
    *, strategy: str, symbol: str, signal_id: Optional[str], features: dict,
    engine=None,
) -> None:
    eng = engine or default_engine()
    try:
        with eng.begin() as cx:
            cx.execute(text("""
                INSERT INTO feature_snapshots (id, ts, strategy, symbol, signal_id, features)
                VALUES (:id, :ts, :st, :sym, :sig, :ft)
            """), {
                "id": new_id(), "ts": _now(), "st": strategy, "sym": symbol,
                "sig": signal_id, "ft": json.dumps(features, default=str),
            })
    except Exception as ex:
        log.warning("record_feature_snapshot failed: %s", ex)
