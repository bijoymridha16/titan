from titan.data.universe import CANDIDATES, anchor


def test_candidate_pool_well_formed():
    assert len(CANDIDATES) > 50  # pool larger than target so selection is a real ranking
    for sym, meta in CANDIDATES.items():
        assert meta["anchor"] > 0 and meta["weight"] > 0


def test_anchor_lookup_and_default():
    assert anchor("RELIANCE") == 2_950.0
    assert anchor("NOT_A_SYMBOL") == 1_000.0  # DEFAULT_ANCHOR


def test_indices_rank_top_by_liquidity():
    # NIFTY/BANKNIFTY carry the highest liquidity proxy → always selected
    assert CANDIDATES["NIFTY"]["weight"] > max(
        v["weight"] for k, v in CANDIDATES.items() if k not in ("NIFTY", "BANKNIFTY"))
