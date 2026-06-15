from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class Product(StrEnum):
    INTRADAY = "INTRADAY"   # MIS on Angel One
    DELIVERY = "DELIVERY"   # CNC
    NORMAL = "NORMAL"       # NRML (F&O carryforward)


class OrderStatus(StrEnum):
    NEW = "NEW"
    OPEN = "OPEN"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass
class Order:
    symbol: str
    side: OrderSide
    qty: int
    order_type: OrderType = OrderType.MARKET
    product: Product = Product.INTRADAY
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    strategy: str = "manual"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    broker_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    avg_fill_price: Optional[float] = None
    placed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    filled_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    is_paper: bool = True


@dataclass
class Position:
    symbol: str
    qty: int                    # signed: +long / -short
    avg_price: float
    unrealized_pnl: float = 0.0


class BrokerAdapter(ABC):
    """Broker contract. Paper and live implementations share this surface
    so the strategy/risk/execution layers are broker-agnostic."""

    name: str = "abstract"

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def place_order(self, order: Order) -> Order:
        """Submit the order. Must return the same Order with status updated
        (broker_order_id set, or rejected with reject_reason)."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_ltp(self, symbol: str) -> float: ...

    @abstractmethod
    async def get_funds(self) -> dict: ...
