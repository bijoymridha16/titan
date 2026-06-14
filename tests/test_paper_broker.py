import pytest

from titan.brokers.base import Order, OrderSide, OrderType, Product
from titan.brokers.paper import PaperBroker


@pytest.fixture
def ltp():
    holder = {"NIFTY": 22_000.0}
    return holder, (lambda s: holder.get(s, 0.0))


def mk(side: OrderSide, qty: int = 10, price: float | None = None,
       order_type: OrderType = OrderType.MARKET) -> Order:
    return Order(symbol="NIFTY", side=side, qty=qty, order_type=order_type,
                 product=Product.INTRADAY, price=price)


async def test_market_buy_fills_with_slippage(ltp):
    holder, getter = ltp
    pb = PaperBroker(cash=500_000, ltp_provider=getter, slippage_bps=10)
    o = await pb.place_order(mk(OrderSide.BUY))
    # 10 bps slippage on 22000 = 22; BUY fills above LTP
    assert o.avg_fill_price == pytest.approx(22_000 + 22, rel=1e-6)
    assert o.broker_order_id and o.broker_order_id.startswith("PAPER-")


async def test_market_sell_fills_below_ltp(ltp):
    holder, getter = ltp
    pb = PaperBroker(cash=500_000, ltp_provider=getter, slippage_bps=10)
    o = await pb.place_order(mk(OrderSide.SELL))
    assert o.avg_fill_price == pytest.approx(22_000 - 22, rel=1e-6)


async def test_buy_then_sell_realizes_pnl(ltp):
    holder, getter = ltp
    pb = PaperBroker(cash=500_000, ltp_provider=getter, slippage_bps=0)
    await pb.place_order(mk(OrderSide.BUY, qty=10))
    holder["NIFTY"] = 22_100.0
    await pb.place_order(mk(OrderSide.SELL, qty=10))
    funds = await pb.get_funds()
    # gross +1000; charges trim it but realized must be positive and < 1000
    assert 0 < funds["realized_pnl"] < 1000


async def test_limit_buy_above_market_rests(ltp):
    holder, getter = ltp
    pb = PaperBroker(cash=500_000, ltp_provider=getter, slippage_bps=0)
    o = await pb.place_order(mk(OrderSide.BUY, price=21_000.0, order_type=OrderType.LIMIT))
    # LTP 22000, BUY limit 21000 → not marketable, rests OPEN
    assert o.status.value == "OPEN"


async def test_limit_buy_marketable_fills_at_limit(ltp):
    holder, getter = ltp
    pb = PaperBroker(cash=500_000, ltp_provider=getter, slippage_bps=0)
    o = await pb.place_order(mk(OrderSide.BUY, price=22_500.0, order_type=OrderType.LIMIT))
    assert o.status.value == "FILLED"
    # pessimistic: fills at the limit, not the LTP
    assert o.avg_fill_price == 22_500.0


async def test_position_tracking(ltp):
    holder, getter = ltp
    pb = PaperBroker(cash=500_000, ltp_provider=getter, slippage_bps=0)
    await pb.place_order(mk(OrderSide.BUY, qty=10))
    positions = await pb.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "NIFTY"
    assert positions[0].qty == 10


async def test_no_ltp_rejects(ltp):
    holder, getter = ltp
    pb = PaperBroker(cash=500_000, ltp_provider=getter, slippage_bps=0)
    o = await pb.place_order(mk(OrderSide.BUY, qty=10))  # NIFTY OK
    assert o.status.value == "FILLED"
    o2 = Order(symbol="UNKNOWN", side=OrderSide.BUY, qty=1,
               order_type=OrderType.MARKET, product=Product.INTRADAY)
    o2 = await pb.place_order(o2)
    assert o2.status.value == "REJECTED"
