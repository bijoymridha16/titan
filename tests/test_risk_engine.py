from datetime import time

import pytest

from titan.brokers.base import Order, OrderSide, OrderType, Product
from titan.risk.engine import RiskEngine, RiskState
from titan.risk.limits import RiskLimits


def make_limits(**overrides) -> RiskLimits:
    base = dict(
        capital=500_000.0,
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=2.0,
        max_daily_profit_pct=4.0,
        max_weekly_loss_pct=5.0,
        max_drawdown_pct=10.0,
        max_consecutive_losses=3,
        max_concurrent_positions=2,
        intraday_square_off=time(15, 15),
    )
    base.update(overrides)
    return RiskLimits(**base)


def make_state(equity=500_000.0, **overrides) -> RiskState:
    s = RiskState(starting_equity=equity, peak_equity=equity, current_equity=equity)
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def order(entry=100.0, qty=10) -> Order:
    return Order(symbol="NIFTY", side=OrderSide.BUY, qty=qty,
                 order_type=OrderType.MARKET, product=Product.INTRADAY, price=entry)


def test_approves_normal_order(ist_now_factory):
    eng = RiskEngine(make_limits(), make_state(), now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert dec.approved


def test_kill_switch_blocks(ist_now_factory):
    s = make_state()
    s.kill_switch = True
    eng = RiskEngine(make_limits(), s, now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved
    assert "kill" in dec.reason


def test_after_cutoff_blocks(ist_now_factory):
    eng = RiskEngine(make_limits(), make_state(), now_fn=ist_now_factory(15, 20))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved
    assert "cutoff" in dec.reason


def test_pre_market_blocks(ist_now_factory):
    eng = RiskEngine(make_limits(), make_state(), now_fn=ist_now_factory(9, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved


def _weekend_now():
    # 2026-06-13 is a Saturday, mid-session time
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return lambda: datetime(2026, 6, 13, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_market_closed_weekend_blocks_in_real_mode():
    eng = RiskEngine(make_limits(), make_state(), now_fn=_weekend_now())
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved
    assert "market closed" in dec.reason


def test_market_closed_after_hours_blocks(ist_now_factory):
    eng = RiskEngine(make_limits(), make_state(), now_fn=ist_now_factory(16, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved
    assert "market closed" in dec.reason


def test_market_closed_is_not_sticky(ist_now_factory):
    # A 'market closed' rejection must NOT permanently halt the day (transient).
    eng = RiskEngine(make_limits(), make_state(), now_fn=ist_now_factory(16, 0))
    eng.check(order(), per_unit_risk=2.0, available_cash=500_000)  # rejected, closed
    assert eng.state.halted_today is False        # not sticky
    eng._now = ist_now_factory(10, 0)             # later, market open again
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert dec.approved                            # trades resume


def test_sim_mode_bypasses_market_hours(ist_now_factory):
    # explicit simulation: time gates relaxed even at 4pm / weekend
    eng = RiskEngine(make_limits(), make_state(),
                     now_fn=ist_now_factory(16, 0), sim_mode_fn=lambda: True)
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert dec.approved


def test_daily_loss_cap(ist_now_factory):
    s = make_state(realized_pnl_today=-10_000.0)  # cap is 2% of 5L = 10k
    eng = RiskEngine(make_limits(), s, now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved
    assert "daily loss" in dec.reason


def test_daily_profit_lock(ist_now_factory):
    # target is 4% of 5L = 20k. Once realized today >= 20k, lock new entries.
    s = make_state(realized_pnl_today=20_000.0)
    eng = RiskEngine(make_limits(), s, now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved
    assert "profit target" in dec.reason


def test_daily_profit_lock_disabled_when_pct_zero(ist_now_factory):
    s = make_state(realized_pnl_today=50_000.0)  # way past any target
    eng = RiskEngine(make_limits(max_daily_profit_pct=0.0), s, now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert dec.approved  # lock disabled → profits don't halt trading


def test_below_profit_target_still_trades(ist_now_factory):
    s = make_state(realized_pnl_today=19_999.0)  # just under 20k target
    eng = RiskEngine(make_limits(), s, now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert dec.approved


def test_drawdown_cap(ist_now_factory):
    s = make_state(current_equity=450_000, peak_equity=500_000)  # 10% DD = cap
    eng = RiskEngine(make_limits(), s, now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=450_000)
    assert not dec.approved
    assert "drawdown" in dec.reason


def test_consecutive_losses(ist_now_factory):
    s = make_state(consecutive_losses=3)
    eng = RiskEngine(make_limits(max_consecutive_losses=3), s, now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved
    assert "consecutive" in dec.reason


def test_concurrent_positions(ist_now_factory):
    s = make_state(open_positions=2)
    eng = RiskEngine(make_limits(max_concurrent_positions=2), s, now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved


def test_per_trade_cap_shrinks_qty(ist_now_factory):
    # cap = 1% of 5L = 5k. qty=10 × per_unit_risk=2000 = 20k → over cap.
    # max qty = 5000//2000 = 2
    eng = RiskEngine(make_limits(), make_state(), now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(qty=10), per_unit_risk=2000, available_cash=500_000)
    assert dec.approved
    assert dec.adjusted_qty == 2


def test_per_trade_cap_unreachable_rejects(ist_now_factory):
    # per_unit_risk 6000 > cap 5000 → cannot fit even qty 1
    eng = RiskEngine(make_limits(), make_state(), now_fn=ist_now_factory(10, 0))
    dec = eng.check(order(qty=1), per_unit_risk=6000, available_cash=500_000)
    assert not dec.approved


def test_session_halt_is_sticky(ist_now_factory):
    eng = RiskEngine(make_limits(), make_state(), now_fn=ist_now_factory(15, 20))
    eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    # later, before cutoff — but state should now be halted_today
    eng._now = ist_now_factory(10, 0)
    dec = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not dec.approved
    assert "halted" in dec.reason


def test_halt_reason_does_not_compound(ist_now_factory):
    # once halted, repeated checks must NOT keep prefixing "session halted: …"
    s = make_state(realized_pnl_today=-10_000.0)  # daily loss cap
    eng = RiskEngine(make_limits(), s, now_fn=ist_now_factory(10, 0))
    for _ in range(5):
        eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert eng.state.halt_reason.count("session halted") <= 1
    assert "daily loss" in eng.state.halt_reason


def test_state_on_trade_closed_loss_increments_consec():
    s = make_state()
    s.on_trade_closed(-1000)
    s.on_trade_closed(-500)
    assert s.consecutive_losses == 2
    s.on_trade_closed(+200)
    assert s.consecutive_losses == 0


def test_state_peak_equity_tracks_high_water_mark():
    s = make_state()
    s.on_trade_closed(+10_000)
    assert s.peak_equity == 510_000
    s.on_trade_closed(-3_000)
    assert s.peak_equity == 510_000
    assert s.drawdown_inr == 3_000


def test_trigger_kill_sets_state():
    eng = RiskEngine(make_limits(), make_state())
    eng.trigger_kill("test")
    assert eng.state.kill_switch
    assert eng.state.halted_today
    assert "KILL" in eng.state.halt_reason


def test_daily_halt_resets_next_sim_day():
    # Regression: a daily halt (here: consecutive-loss streak) must self-recover
    # at the next trading day, not latch forever (operator finding 2026-06-22 —
    # the streak halt stayed latched across ~13 sim-days, freezing trading).
    from datetime import datetime
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    clk = {"t": datetime(2026, 6, 22, 10, 0, tzinfo=IST)}
    eng = RiskEngine(make_limits(max_consecutive_losses=3), make_state(),
                     now_fn=lambda: clk["t"])
    for _ in range(3):
        eng.state.on_trade_closed(-100.0)
    blocked = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert not blocked.approved and "consecutive" in blocked.reason
    # next sim-day → daily counters + halt reset → trades again
    clk["t"] = datetime(2026, 6, 23, 10, 0, tzinfo=IST)
    resumed = eng.check(order(), per_unit_risk=2.0, available_cash=500_000)
    assert resumed.approved
    assert eng.state.consecutive_losses == 0 and not eng.state.halted_today
