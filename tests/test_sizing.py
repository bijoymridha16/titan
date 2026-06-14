from titan.risk.sizing import atr_position_size, fixed_fractional_qty


def test_fixed_fractional_basic():
    # ₹5L equity, 1% risk = ₹5,000; ₹10 per-unit risk → 500 qty
    assert fixed_fractional_qty(500_000, 1.0, entry=100, stop=90) == 500


def test_fixed_fractional_lot_size_floors():
    # 500 qty with lot_size 75 → floor to 7 lots = 525? no — 500 // 75 * 75 = 450
    assert fixed_fractional_qty(500_000, 1.0, 100, 90, lot_size=75) == 450


def test_fixed_fractional_zero_when_stop_equals_entry():
    assert fixed_fractional_qty(500_000, 1.0, 100, 100) == 0


def test_fixed_fractional_zero_when_bad_inputs():
    assert fixed_fractional_qty(500_000, 1.0, 0, 5) == 0
    assert fixed_fractional_qty(500_000, 1.0, 5, 0) == 0


def test_atr_sizing():
    # ATR=10, mult=1.5 → per-unit risk 15; 1% of 5L = 5k → 333 qty
    assert atr_position_size(500_000, 1.0, atr=10, atr_multiple=1.5) == 333


def test_atr_sizing_lot_size():
    assert atr_position_size(500_000, 1.0, atr=10, atr_multiple=1.5, lot_size=25) == 325


def test_atr_zero_when_atr_zero():
    assert atr_position_size(500_000, 1.0, atr=0) == 0
