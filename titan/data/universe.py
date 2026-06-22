"""Dynamic trading-universe selection.

Instead of a hardcoded TITAN_UNIVERSE, the operator analyses a candidate pool of
liquid NSE names and selects the top-N to trade for the session. The selection
rule is liquidity/turnover (you trade the most liquid names — tightest spreads,
lowest slippage), with realized-volatility from any existing OHLCV folded in as
supplementary analysis. The regime-reference symbol (settings.autopilot_ref_symbol)
is always retained so regime classification keeps working.

Outputs:
  - Redis `titan:universe:selected`     — CSV of chosen symbols (read by config.symbols)
  - Redis `titan:universe:selected_at`  — ISO timestamp
  - DB `universe_selection`             — one row per candidate with score + reason

In SIM the candidate "market" is this curated pool (with anchor prices the synth
feed uses). In a real deployment the pool/scores come from the instrument master
+ live turnover; the selection logic is identical.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import redis
from sqlalchemy import create_engine, text

from titan.config import settings

log = logging.getLogger(__name__)

SELECTED_KEY = "titan:universe:selected"
SELECTED_AT_KEY = "titan:universe:selected_at"
DEFAULT_ANCHOR = 1_000.0

# Candidate pool: liquid NSE names. weight = liquidity/turnover proxy (≈ free-float
# mcap in ₹ lakh-crore) used as the primary selection score; anchor = synth price.
# Pool is intentionally LARGER than the target N so selection is a real ranking.
CANDIDATES: dict[str, dict] = {
    # index proxies (regime ref + liquid index exposure)
    "NIFTY":      {"anchor": 24_500.0, "weight": 999.0},
    "BANKNIFTY":  {"anchor": 52_000.0, "weight": 900.0},
    # NIFTY-50 constituents (approx prices / mcap-proxy weights)
    "RELIANCE":   {"anchor": 2_950.0, "weight": 19.5},
    "HDFCBANK":   {"anchor": 1_680.0, "weight": 12.8},
    "TCS":        {"anchor": 3_900.0, "weight": 14.1},
    "ICICIBANK":  {"anchor": 1_280.0, "weight": 9.0},
    "BHARTIARTL": {"anchor": 1_620.0, "weight": 9.6},
    "INFY":       {"anchor": 1_850.0, "weight": 7.7},
    "SBIN":       {"anchor": 840.0,   "weight": 7.5},
    "LICI":       {"anchor": 960.0,   "weight": 6.1},
    "ITC":        {"anchor": 470.0,   "weight": 5.9},
    "HINDUNILVR": {"anchor": 2_450.0, "weight": 5.8},
    "LT":         {"anchor": 3_600.0, "weight": 5.0},
    "BAJFINANCE": {"anchor": 7_200.0, "weight": 4.5},
    "KOTAKBANK":  {"anchor": 1_780.0, "weight": 3.6},
    "AXISBANK":   {"anchor": 1_150.0, "weight": 3.5},
    "MARUTI":     {"anchor": 12_500.0,"weight": 3.4},
    "SUNPHARMA":  {"anchor": 1_750.0, "weight": 4.2},
    "HCLTECH":    {"anchor": 1_800.0, "weight": 4.9},
    "NTPC":       {"anchor": 360.0,   "weight": 3.5},
    "ONGC":       {"anchor": 250.0,   "weight": 3.1},
    "TATAMOTORS": {"anchor": 720.0,   "weight": 2.7},
    "ADANIENT":   {"anchor": 2_450.0, "weight": 2.8},
    "TITAN":      {"anchor": 3_400.0, "weight": 3.0},
    "POWERGRID":  {"anchor": 320.0,   "weight": 3.0},
    "ULTRACEMCO": {"anchor": 11_500.0,"weight": 3.3},
    "WIPRO":      {"anchor": 290.0,   "weight": 3.0},
    "ADANIPORTS": {"anchor": 1_320.0, "weight": 2.9},
    "COALINDIA":  {"anchor": 400.0,   "weight": 2.5},
    "BAJAJFINSV": {"anchor": 1_650.0, "weight": 2.6},
    "NESTLEIND":  {"anchor": 2_350.0, "weight": 2.3},
    "ASIANPAINT": {"anchor": 2_900.0, "weight": 2.8},
    "DMART":      {"anchor": 4_100.0, "weight": 2.6},
    "TATASTEEL":  {"anchor": 145.0,   "weight": 1.8},
    "JSWSTEEL":   {"anchor": 920.0,   "weight": 2.2},
    "M&M":        {"anchor": 2_900.0, "weight": 3.4},
    "HINDALCO":   {"anchor": 650.0,   "weight": 1.5},
    "TECHM":      {"anchor": 1_550.0, "weight": 1.5},
    "POWERFIN":   {"anchor": 480.0,   "weight": 1.6},
    "PFC":        {"anchor": 450.0,   "weight": 1.5},
    "GRASIM":     {"anchor": 2_500.0, "weight": 1.7},
    "INDUSINDBK": {"anchor": 1_000.0, "weight": 1.0},
    "DRREDDY":    {"anchor": 1_250.0, "weight": 2.0},
    "CIPLA":      {"anchor": 1_500.0, "weight": 2.4},
    "BRITANNIA":  {"anchor": 4_900.0, "weight": 1.3},
    "EICHERMOT":  {"anchor": 4_800.0, "weight": 1.6},
    "BPCL":       {"anchor": 320.0,   "weight": 1.4},
    "HEROMOTOCO": {"anchor": 4_700.0, "weight": 1.1},
    "DIVISLAB":   {"anchor": 5_900.0, "weight": 1.7},
    "TATACONSUM": {"anchor": 1_000.0, "weight": 1.1},
    "BAJAJ-AUTO": {"anchor": 9_500.0, "weight": 2.0},
    "SHRIRAMFIN": {"anchor": 620.0,   "weight": 1.3},
    "APOLLOHOSP": {"anchor": 6_800.0, "weight": 1.3},
    "SBILIFE":    {"anchor": 1_550.0, "weight": 1.2},
    "HDFCLIFE":   {"anchor": 680.0,   "weight": 1.2},
    "JIOFIN":     {"anchor": 330.0,   "weight": 2.0},
    "TRENT":      {"anchor": 6_400.0, "weight": 1.9},
    "ADANIGREEN": {"anchor": 1_050.0, "weight": 1.4},
    "VEDL":       {"anchor": 450.0,   "weight": 1.3},
    "GAIL":       {"anchor": 200.0,   "weight": 1.0},
    "DLF":        {"anchor": 800.0,   "weight": 1.6},
}


def anchor(symbol: str) -> float:
    return float(CANDIDATES.get(symbol, {}).get("anchor", DEFAULT_ANCHOR))


def _engine():
    return create_engine(settings.db_url)


def _recent_realized_vol(eng) -> dict[str, float]:
    """Annualized realized vol per symbol from recent 5m closes, if any OHLCV
    exists. Supplementary 'analysis' — absent for fresh symbols."""
    out: dict[str, float] = {}
    try:
        with eng.connect() as cx:
            rows = cx.execute(text("""
                SELECT symbol, stddev_samp(ln_ret) * sqrt(75*252) AS rvol
                FROM (
                    SELECT symbol,
                           ln(c / NULLIF(lag(c) OVER (PARTITION BY symbol ORDER BY ts), 0)) AS ln_ret
                    FROM ohlcv WHERE timeframe='5m'
                      AND ts > now() - interval '5 days'
                ) s
                WHERE ln_ret IS NOT NULL
                GROUP BY symbol
            """)).fetchall()
        for sym, rvol in rows:
            if rvol is not None and np.isfinite(float(rvol)):
                out[sym] = float(rvol)
    except Exception as e:  # best-effort
        log.warning("realized-vol analysis skipped: %s", e)
    return out


def analyze_and_select(n: int = 50, persist: bool = True) -> list[dict]:
    """Rank the candidate pool by liquidity (primary) and return the top-N to
    trade. Always retains the regime-reference symbol. Persists the full analysis."""
    eng = _engine()
    rvol = _recent_realized_vol(eng)

    ranked = []
    for sym, meta in CANDIDATES.items():
        w = float(meta["weight"])
        rv = rvol.get(sym)
        # score = liquidity; record realized vol as supplementary analysis
        ranked.append({"symbol": sym, "score": w, "liquidity": w,
                       "realized_vol": rv,
                       "reason": f"liquidity={w:.1f}" + (f", rvol={rv:.2f}" if rv else ", rvol=n/a")})
    ranked.sort(key=lambda d: d["score"], reverse=True)

    chosen = ranked[:n]
    chosen_syms = [d["symbol"] for d in chosen]

    # always keep the regime reference so classification keeps working
    ref = settings.autopilot_ref_symbol
    if ref in CANDIDATES and ref not in chosen_syms:
        chosen_syms.append(ref)
        for d in ranked:
            if d["symbol"] == ref:
                d["reason"] += " [forced: regime reference]"
                chosen.append(d)

    selected_at = datetime.now(timezone.utc).isoformat()
    for rank, d in enumerate(ranked, 1):
        d["rank"] = rank
        d["selected"] = d["symbol"] in chosen_syms

    if persist:
        r = redis.from_url(settings.redis_url, decode_responses=True)
        r.set(SELECTED_KEY, ",".join(chosen_syms))
        r.set(SELECTED_AT_KEY, selected_at)
        try:
            with eng.begin() as cx:
                cx.execute(text("DELETE FROM universe_selection WHERE selected_at < :t"),
                           {"t": selected_at})
                for d in ranked:
                    cx.execute(text("""
                        INSERT INTO universe_selection
                          (selected_at, symbol, rank, score, liquidity, realized_vol, selected, reason)
                        VALUES (:t,:s,:r,:sc,:l,:rv,:sel,:rsn)
                    """), {"t": selected_at, "s": d["symbol"], "r": d["rank"],
                           "sc": d["score"], "l": d["liquidity"], "rv": d.get("realized_vol"),
                           "sel": d["selected"], "rsn": d["reason"]})
        except Exception as e:
            log.warning("universe_selection persist skipped: %s", e)

    log.info("universe: selected %d of %d candidates (top by liquidity)",
             len(chosen_syms), len(ranked))
    return ranked


def main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=50, help="size of the trading universe")
    args = ap.parse_args()
    ranked = analyze_and_select(args.n)
    print(f"\nTop {args.n} of {len(ranked)} candidates (by liquidity):")
    for d in ranked:
        mark = "✓" if d["selected"] else " "
        print(f"  {mark} {d['rank']:>2}. {d['symbol']:<12} {d['reason']}")


if __name__ == "__main__":
    main()
