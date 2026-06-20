from titan.risk.sizing import fixed_fractional_qty


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


def test_confidence_scales_size_down():
    # M3: half confidence → half the risk budget → half the qty
    full = fixed_fractional_qty(500_000, 1.0, 100, 90, confidence=1.0)
    half = fixed_fractional_qty(500_000, 1.0, 100, 90, confidence=0.5)
    assert half == full // 2 == 250


def test_confidence_clamped_low():
    # confidence below 0.1 floors at 0.1 (a min sleeve, never zero from conviction)
    tiny = fixed_fractional_qty(500_000, 1.0, 100, 90, confidence=0.0)
    assert tiny == fixed_fractional_qty(500_000, 1.0, 100, 90, confidence=0.1)
    assert tiny == 50


def test_confidence_above_one_does_not_upsize():
    base = fixed_fractional_qty(500_000, 1.0, 100, 90, confidence=1.0)
    assert fixed_fractional_qty(500_000, 1.0, 100, 90, confidence=5.0) == base
