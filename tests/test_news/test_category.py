from titan.news.category import NEVER_FIRE, classify


def test_earnings():
    assert classify("Reliance reports Q1 profit up 22%, beats estimates") == "earnings"
    assert classify("HDFC Bank Q4FY26 results announced") == "earnings"


def test_guidance_is_its_own_category():
    # v2 split: guidance changes get their own category (rubric treats
    # guidance ±20 separately from earnings results).
    assert classify("Infosys cuts FY guidance to 4-6%") == "guidance_down"


def test_m_and_a():
    assert classify("TCS to acquire German consulting firm for $420 million") == "m_and_a"
    assert classify("Adani Group announces takeover of Ambuja Cements") == "m_and_a"


def test_regulatory():
    assert classify("SEBI imposes Rs 50 cr penalty on XYZ for disclosure violations") == "regulatory"
    assert classify("RBI cease and desist order on bank") == "regulatory"


def test_dividend():
    assert classify("HDFC Bank declares interim dividend of Rs 19.5") == "dividend"
    assert classify("Buyback announcement: 1 cr shares at Rs 2000") == "dividend"


def test_block_deal_never_fires():
    cat = classify("Block deal: 1.2 cr shares of Adani Power exchange hands")
    assert cat == "block_deal"
    assert cat in NEVER_FIRE


def test_generic_noise():
    assert classify("SIS Limited has informed the Exchange regarding BRSR") == "generic_noise"
    assert classify("Notice of Annual General Meeting") == "generic_noise"


def test_other_fallback():
    assert classify("Random sports headline no financial content") == "other"
