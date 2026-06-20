"""Angel One SmartAPI broker adapter.

IMPLEMENTED:
    - connect()      → password + TOTP login, stores jwt/refresh/feed tokens
    - get_funds()    → /user/v1/getRMS, returns cash + margin breakdown
    - get_ltp()      → /order/v1/getLtpData for a single symbol

NOT IMPLEMENTED (deliberate — order paths require paper-trading gate first):
    - place_order, cancel_order, get_positions, disconnect

Login flow:
    POST /rest/auth/angelbroking/user/v1/loginByPassword
    body: {clientcode, password (MPIN), totp}
    headers: X-PrivateKey (api_key), X-UserType=USER, X-SourceID=WEB,
             X-ClientLocalIP, X-ClientPublicIP, X-MACAddress, Content-Type=application/json

Tokens:
    jwtToken    — 23h validity, used in Authorization: Bearer <jwt>
    refreshToken — refresh JWT without re-doing TOTP
    feedToken   — WebSocket V2 auth

Refs:
    https://smartapi.angelone.in/docs/
    https://smartapi.angelone.in/docs/User
"""
from __future__ import annotations

import logging
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pyotp

from titan.brokers.base import (
    BrokerAdapter, Order, OrderSide, OrderStatus, OrderType, Position, Product,
)
from titan.config import angelone_settings, settings
from titan.data.instruments import lookup, resolve_universe

log = logging.getLogger(__name__)

REST_BASE = "https://apiconnect.angelone.in"
LOGIN_PATH = "/rest/auth/angelbroking/user/v1/loginByPassword"
REFRESH_PATH = "/rest/auth/angelbroking/jwt/v1/generateTokens"
RMS_PATH = "/rest/secure/angelbroking/user/v1/getRMS"
LTP_PATH = "/rest/secure/angelbroking/order/v1/getLtpData"
PLACE_ORDER_PATH = "/rest/secure/angelbroking/order/v1/placeOrder"
CANCEL_ORDER_PATH = "/rest/secure/angelbroking/order/v1/cancelOrder"
ORDER_BOOK_PATH = "/rest/secure/angelbroking/order/v1/getOrderBook"
ORDER_DETAILS_PATH = "/rest/secure/angelbroking/order/v1/details"
POSITIONS_PATH = "/rest/secure/angelbroking/order/v1/getPosition"
LOGOUT_PATH = "/rest/secure/angelbroking/user/v1/logout"
MARGIN_BATCH_PATH = "/rest/secure/angelbroking/margin/v1/batch"

WS_URL = "wss://smartapisocket.angelone.in/smart-stream"
IST = ZoneInfo("Asia/Kolkata")


def session_needs_refresh(jwt, token_day, today, expires_at, now) -> bool:
    """Pure decision: must we do a fresh login? (SEBI 2026 daily session reset)

    True when: no token yet, the JWT has expired, OR the token was minted on a
    different trading day (forces a fresh OAuth+2FA handshake each new day).
    """
    if not jwt:
        return True
    if expires_at and now >= expires_at:
        return True
    if token_day is not None and today != token_day:
        return True
    return False


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _mac() -> str:
    n = uuid.getnode()
    return ":".join(f"{(n >> i) & 0xff:02x}" for i in range(40, -1, -8))


def _public_ip(client: httpx.Client) -> str:
    try:
        return client.get("https://api.ipify.org", timeout=3.0).text.strip()
    except Exception:
        return "0.0.0.0"


class AngelOneAuthError(Exception):
    pass


class AngelOneBroker(BrokerAdapter):
    name = "angelone"

    def __init__(self):
        self.cfg = angelone_settings
        self._jwt: str | None = None
        self._refresh: str | None = None
        self._feed_token: str | None = None
        self._expires_at: datetime | None = None
        self._token_day = None          # IST trading date the token was minted for
        self._client: httpx.Client | None = None

    # ─────────────── public ───────────────
    async def connect(self) -> None:
        self._login_sync()

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    async def get_funds(self) -> dict:
        self._ensure_token()
        r = self._client.get(RMS_PATH, headers=self._auth_headers(), timeout=10.0)
        return self._unwrap(r, "getRMS")

    async def get_ltp(self, symbol: str, exchange: str = "NSE",
                      symboltoken: str | None = None) -> float:
        """Caller MUST pass symboltoken — instrument lookup happens in data/instruments.py."""
        if symboltoken is None:
            raise ValueError("symboltoken required (no instrument master integrated yet)")
        self._ensure_token()
        r = self._client.post(
            LTP_PATH,
            headers=self._auth_headers(),
            json={"exchange": exchange, "tradingsymbol": symbol, "symboltoken": symboltoken},
            timeout=10.0,
        )
        data = self._unwrap(r, "getLtpData")
        return float(data["ltp"])

    @property
    def feed_token(self) -> str | None:
        return self._feed_token

    async def batch_margin(self, legs: list[dict]) -> float | None:
        """Required total margin (SPAN+Exposure) for a basket via the batch
        endpoint (manifesto Multiplier 3). `legs` = list of position dicts
        (exchange, qty, price, productType, token, tradeType…). Returns the
        total margin required, or None if it can't be computed (best-effort)."""
        self._ensure_token()
        try:
            r = self._client.post(MARGIN_BATCH_PATH, headers=self._auth_headers(),
                                 json={"positions": legs}, timeout=10.0)
            data = self._unwrap(r, "marginBatch") or {}
            val = data.get("totalMarginRequired") or data.get("total_margin_required")
            return float(val) if val is not None else None
        except Exception as e:
            log.warning("batch margin failed: %s", e)
            return None

    async def get_order_details(self, unique_order_id: str) -> dict | None:
        """Reconcile an ambiguous dispatch: fetch the authoritative order state
        from `/details/{UniqueOrderID}` (manifesto Scenario A). Best-effort —
        returns the order dict, or None if it can't be resolved."""
        self._ensure_token()
        try:
            r = self._client.get(f"{ORDER_DETAILS_PATH}/{unique_order_id}",
                                 headers=self._auth_headers(), timeout=10.0)
            return self._unwrap(r, "orderDetails")
        except Exception as e:
            log.warning("order details lookup failed for %s: %s", unique_order_id, e)
            return None

    # ─────────────── live order path ───────────────
    # Multiple safety gates. ALL must pass or the order is rejected before
    # touching Angel's API. Order of checks matters — cheapest/most-fatal first.
    async def place_order(self, order: Order) -> Order:
        # gate 1: global live flag
        if not settings.live_enabled:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "live_disabled (TITAN_LIVE_ENABLED=0)"
            log.warning("REJECT order %s: %s", order.id, order.reject_reason)
            return order

        # gate 2: product whitelist (no NORMAL/F&O carryforward at ₹5K)
        if order.product.value not in settings.allowed_products_set:
            order.status = OrderStatus.REJECTED
            order.reject_reason = f"product_not_allowed: {order.product.value}"
            return order

        # gate 3: resolve instrument + exchange whitelist
        inst = lookup(order.symbol, "NSE", instrumenttype="AMXIDX")
        if not inst:
            hits = resolve_universe([order.symbol])
            inst = hits[0] if hits else None
        if not inst:
            order.status = OrderStatus.REJECTED
            order.reject_reason = f"instrument_not_found: {order.symbol}"
            return order
        if inst["exch_seg"].upper() not in settings.allowed_exchanges_set:
            order.status = OrderStatus.REJECTED
            order.reject_reason = f"exchange_not_allowed: {inst['exch_seg']}"
            return order

        # gate 4: notional value cap (market orders use last LTP estimate)
        ref_price = float(order.price) if order.price else float(inst.get("tick_size") or 0) * 0
        if not ref_price:
            try:
                ref_price = await self.get_ltp(
                    order.symbol, inst["exch_seg"], str(inst["token"]))
            except Exception as e:
                order.status = OrderStatus.REJECTED
                order.reject_reason = f"ltp_lookup_failed: {e}"
                return order
        notional = ref_price * order.qty
        if notional > settings.live_max_order_value:
            order.status = OrderStatus.REJECTED
            order.reject_reason = (
                f"notional_exceeds_cap: ₹{notional:.0f} > ₹{settings.live_max_order_value:.0f}"
            )
            log.warning("REJECT order %s: %s", order.id, order.reject_reason)
            return order

        # build payload (Angel SmartAPI placeOrder schema)
        variety = "NORMAL" if order.order_type == OrderType.MARKET else "STOPLOSS"
        producttype = {"INTRADAY": "INTRADAY", "DELIVERY": "DELIVERY",
                       "NORMAL": "CARRYFORWARD"}[order.product.value]
        ordertype = {"MARKET": "MARKET", "LIMIT": "LIMIT",
                     "SL": "STOPLOSS_LIMIT", "SL-M": "STOPLOSS_MARKET"}[order.order_type.value]
        payload = {
            "variety": variety,
            "tradingsymbol": inst["symbol"],
            "symboltoken": str(inst["token"]),
            "transactiontype": order.side.value,           # BUY / SELL
            "exchange": inst["exch_seg"],                  # NSE
            "ordertype": ordertype,
            "producttype": producttype,
            "duration": "DAY",
            "price": f"{order.price:.2f}" if order.price else "0",
            "triggerprice": f"{order.trigger_price:.2f}" if order.trigger_price else "0",
            "quantity": str(order.qty),
        }
        # SEBI 2026: tag every order with its exchange-registered Strategy ID.
        if order.strategy_id:
            payload["strategyid"] = order.strategy_id

        # gate 5: dry-run — log the exact payload, do NOT call Angel.
        # This is the most important gate for week 1: lets you watch what would
        # have been submitted in real conditions without risking a paisa.
        if settings.live_dry_run:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "dry_run (would have sent: " + str(payload) + ")"
            order.is_paper = False
            log.warning("DRY-RUN order %s payload=%s", order.id, payload)
            return order

        # ─── actually send ───
        self._ensure_token()
        try:
            r = self._client.post(
                PLACE_ORDER_PATH,
                headers=self._auth_headers(),
                json=payload,
                timeout=10.0,
            )
            data = self._unwrap(r, "placeOrder")
        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.reject_reason = f"api_error: {e}"
            log.exception("placeOrder failed for %s", order.id)
            return order

        order.broker_order_id = data.get("orderid")
        order.is_paper = False
        order.status = OrderStatus.OPEN  # confirmation via order book poll
        order.placed_at = datetime.now(timezone.utc)
        log.info("LIVE ORDER PLACED %s → angel_id=%s %s %s qty=%d",
                 order.id, order.broker_order_id, order.side.value,
                 order.symbol, order.qty)

        # poll order book briefly to capture fill price
        fill = await self._poll_fill(order.broker_order_id, timeout_s=8.0)
        if fill:
            order.status = OrderStatus(fill["status"])
            order.avg_fill_price = fill["avg_price"]
            order.filled_at = datetime.now(timezone.utc)
        return order

    async def cancel_order(self, broker_order_id: str,
                           variety: str = "NORMAL") -> bool:
        if not settings.live_enabled or settings.live_dry_run:
            log.info("cancel_order skipped (live_enabled=%s dry_run=%s)",
                     settings.live_enabled, settings.live_dry_run)
            return False
        self._ensure_token()
        r = self._client.post(
            CANCEL_ORDER_PATH, headers=self._auth_headers(),
            json={"variety": variety, "orderid": broker_order_id}, timeout=10.0,
        )
        self._unwrap(r, "cancelOrder")
        return True

    async def get_positions(self) -> list[Position]:
        self._ensure_token()
        r = self._client.get(POSITIONS_PATH, headers=self._auth_headers(),
                             timeout=10.0)
        data = self._unwrap(r, "getPosition") or []
        out: list[Position] = []
        for p in data if isinstance(data, list) else []:
            qty = int(p.get("netqty", 0) or 0)
            if qty == 0:
                continue
            out.append(Position(
                symbol=p["tradingsymbol"],
                qty=qty,
                avg_price=float(p.get("avgnetprice") or p.get("buyavgprice") or 0),
                unrealized_pnl=float(p.get("unrealised") or 0),
            ))
        return out

    async def _poll_fill(self, broker_order_id: str, timeout_s: float = 8.0):
        """Poll order book until status terminal or timeout. Returns dict or None."""
        import asyncio
        deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_s)
        terminal = {"complete", "rejected", "cancelled"}
        while datetime.now(timezone.utc) < deadline:
            try:
                r = self._client.get(ORDER_BOOK_PATH,
                                     headers=self._auth_headers(), timeout=5.0)
                book = self._unwrap(r, "getOrderBook") or []
                for row in book if isinstance(book, list) else []:
                    if row.get("orderid") == broker_order_id:
                        st = (row.get("status") or "").lower()
                        if st in terminal:
                            mapped = {"complete": "FILLED",
                                      "rejected": "REJECTED",
                                      "cancelled": "CANCELLED"}[st]
                            return {
                                "status": mapped,
                                "avg_price": float(row.get("averageprice") or 0),
                            }
            except Exception as e:
                log.warning("order book poll failed: %s", e)
            await asyncio.sleep(0.5)
        log.warning("order %s did not reach terminal status in %.1fs",
                    broker_order_id, timeout_s)
        return None

    # ─────────────── internals ───────────────
    def _client_lazy(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=REST_BASE, timeout=10.0)
        return self._client

    def _login_sync(self) -> None:
        c = self._client_lazy()
        for key in ("api_key", "client_code", "password", "totp_secret"):
            if not getattr(self.cfg, key):
                raise AngelOneAuthError(f"ANGELONE_{key.upper()} missing in .env")

        totp = pyotp.TOTP(self.cfg.totp_secret).now()
        log.info("angelone: logging in as %s", self.cfg.client_code)
        r = c.post(
            LOGIN_PATH,
            json={
                "clientcode": self.cfg.client_code,
                "password": self.cfg.password,
                "totp": totp,
            },
            headers=self._login_headers(c),
        )
        body = self._unwrap(r, "loginByPassword")
        self._jwt = body["jwtToken"]
        self._refresh = body["refreshToken"]
        self._feed_token = body["feedToken"]
        self._expires_at = datetime.now(timezone.utc) + timedelta(hours=22)
        self._token_day = datetime.now(IST).date()
        log.info("angelone: login OK, jwt expires ~%s (day=%s)",
                 self._expires_at.isoformat(), self._token_day)

    def _ensure_token(self) -> None:
        if session_needs_refresh(self._jwt, self._token_day, datetime.now(IST).date(),
                                 self._expires_at, datetime.now(timezone.utc)):
            self._login_sync()

    async def logout(self) -> None:
        """Sever the API session (SEBI 2026 mandatory daily logout). Best-effort;
        always clears local tokens so the next call forces a fresh handshake."""
        if self._jwt and self._client:
            try:
                self._client.post(LOGOUT_PATH, headers=self._auth_headers(),
                                  json={"clientcode": self.cfg.client_code}, timeout=10.0)
                log.info("angelone: session logged out")
            except Exception as e:
                log.warning("angelone: logout call failed (clearing tokens anyway): %s", e)
        self._jwt = self._refresh = self._feed_token = None
        self._expires_at = None
        self._token_day = None

    def _login_headers(self, c: httpx.Client) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": _local_ip(),
            "X-ClientPublicIP": _public_ip(c),
            "X-MACAddress": _mac(),
            "X-PrivateKey": self.cfg.api_key,
        }

    def _auth_headers(self) -> dict[str, str]:
        h = self._login_headers(self._client_lazy())
        h["Authorization"] = f"Bearer {self._jwt}"
        return h

    @staticmethod
    def _unwrap(r: httpx.Response, op: str) -> dict[str, Any]:
        try:
            j = r.json()
        except Exception:
            raise AngelOneAuthError(f"{op}: non-JSON response {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400 or not j.get("status", False):
            code = j.get("errorcode", "?")
            msg = j.get("message", j)
            raise AngelOneAuthError(f"{op}: [{code}] {msg}")
        return j.get("data") or {}
