from titan.news.entities import resolve


def test_exact_match_from_raw_symbol():
    out = resolve("RELIANCE", "Some unrelated headline")
    assert len(out) == 1
    assert out[0].ticker == "RELIANCE"
    assert out[0].method == "exact"
    assert out[0].confidence == 1.0


def test_alias_full_name():
    out = resolve(None, "Reliance Industries reports Q1 profit up 22%")
    assert any(h.ticker == "RELIANCE" and h.method == "alias" for h in out)


def test_alias_abbreviation():
    out = resolve(None, "TCS wins multi-year contract")
    assert any(h.ticker == "TCS" for h in out)


def test_alias_special_chars():
    out = resolve(None, "L&T bags ₹15,000 cr defence order")
    assert any(h.ticker == "LT" for h in out)


def test_multi_symbol_split():
    out = resolve(None, "HDFC Bank and ICICI Bank announce rate cuts")
    tickers = {h.ticker for h in out}
    assert {"HDFCBANK", "ICICIBANK"}.issubset(tickers)


def test_bse_numeric_scrip_code_resolves():
    out = resolve(None, "500325 - corporate disclosure")
    assert any(h.ticker == "RELIANCE" for h in out)


def test_no_match_returns_empty():
    out = resolve(None, "Cricket score update from IPL final")
    assert out == []


def test_fuzzy_threshold_blocks_weak_match():
    # "non-NIFTY company XYZ" used to fuzzy-match TITAN ("Titan Company").
    # The 85-threshold must reject this.
    out = resolve(None, "Random non-NIFTY company XYZ wins case")
    assert out == []
