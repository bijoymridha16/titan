"""The recorder must (a) build correct SQL params and (b) NEVER raise into the
trading loop, even when the DB is broken."""
from __future__ import annotations

from titan.analytics import recorder as rec


class _FakeCx:
    def __init__(self, sink): self.sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, _stmt, params): self.sink.append(params)


class _FakeEngine:
    def __init__(self): self.rows = []
    def begin(self): return _FakeCx(self.rows)


class _BrokenEngine:
    def begin(self): raise RuntimeError("db down")


def test_record_signal_writes_row():
    eng = _FakeEngine()
    rec.record_signal(
        signal_id="s1", strategy="orb", symbol="NIFTY", kind="ENTRY_LONG",
        entry=100.0, stop=98.0, target=104.0, per_unit_risk=2.0, confidence=1.0,
        regime="TREND", accepted=True, reject_reason=None, order_id="o1",
        reason="breakout", engine=eng,
    )
    assert len(eng.rows) == 1
    assert eng.rows[0]["sym"] == "NIFTY"
    assert eng.rows[0]["acc"] is True


def test_record_signal_never_raises_on_db_error():
    # the whole point: a logging failure must not break trading
    rec.record_signal(
        signal_id="s1", strategy="orb", symbol="NIFTY", kind="ENTRY_LONG",
        entry=100.0, stop=98.0, target=None, per_unit_risk=2.0, confidence=1.0,
        regime=None, accepted=False, reject_reason="x", order_id=None,
        reason="", engine=_BrokenEngine(),
    )  # must not raise


def test_record_fill_computes_realized_slippage_signed_by_side():
    eng = _FakeEngine()
    # BUY filled above reference → positive (adverse) slippage
    rec.record_fill(order_id="o1", strategy="orb", symbol="NIFTY", side="BUY",
                    qty=10, fill_price=100.2, ltp_at_decision=100.0,
                    modeled_slippage_bps=2.0, engine=eng)
    assert eng.rows[0]["rsb"] > 0
    eng2 = _FakeEngine()
    # SELL filled below reference → also adverse → positive after sign flip
    rec.record_fill(order_id="o2", strategy="orb", symbol="NIFTY", side="SELL",
                    qty=10, fill_price=99.8, ltp_at_decision=100.0,
                    modeled_slippage_bps=2.0, engine=eng2)
    assert eng2.rows[0]["rsb"] > 0


def test_record_order_attempt_and_feature_snapshot_smoke():
    eng = _FakeEngine()
    rec.record_order_attempt(
        order_id="o1", signal_id="s1", strategy="orb", symbol="NIFTY", side="BUY",
        qty_requested=10, qty_final=10, order_type="MARKET", product="INTRADAY",
        price=100.0, risk_approved=True, risk_reason=None, broker="paper",
        status="FILLED", broker_order_id="PAPER-x", avg_fill_price=100.2,
        reject_reason=None, engine=eng,
    )
    rec.record_feature_snapshot(strategy="orb", symbol="NIFTY", signal_id="s1",
                                features={"c": 100.0, "window_bars": 200}, engine=eng)
    assert len(eng.rows) == 2
