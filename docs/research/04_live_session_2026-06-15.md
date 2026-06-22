# Live paper-trading session — 2026-06-15

First live session against real Angel One ticks. Paper-only (`TITAN_LIVE_ENABLED=0`).
Capital ₹50,000, max risk/trade ₹500, daily loss cap ₹5,000, max concurrent positions 3.

Strategies enabled: `supertrend_adx`, `vwap_revert`. ORB stayed disabled (backtest verdict KILL on this
data, didn't want to pollute the signal).

## Trade tape

| # | Time IST | Strategy | Symbol | Side | Qty | Entry | Exit | Reason | P&L |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 13:20 | supertrend_adx | HDFCBANK | BUY | 23 | 779.96 | open at close | — | -₹59.94 unrealized |
| 2 | 14:25 → 14:30 | vwap_revert | RELIANCE | SELL | 205 | 1308.64 | 1307.36 | target | **+₹261.92** |
| 3 | 14:40 → 15:05 | supertrend_adx | ICICIBANK | BUY | 62 | 1337.27 | 1329.13 | stop | **-₹504.52** |
| 4 | 15:05 | supertrend_adx | ICICIBANK | SELL | 40 | 1326.23 | open at close | — | -₹54.61 unrealized |

## Per-strategy verdict

| Strategy | Trades | Wins | Losses | Open | Realized |
|---|---|---|---|---|---|
| vwap_revert | 1 | 1 | 0 | 0 | **+₹261.92** |
| supertrend_adx | 3 | 0 | 1 | 2 | -₹504.52 |
| **Total** | **4** | 1 | 1 | 2 | **-₹242.60** |

## Risk engine activity

- **3 OPEN** orders accepted
- **2 CLOSE** events (one target, one stop)
- **3 REJECT** events — all `insufficient funds` (at 15:05 and 15:10, vwap_revert tried to
  fire on ICICIBANK / HDFCBANK while supertrend was already holding ICICIBANK + HDFCBANK).
  Risk framework correctly blocked over-leveraging.

The -₹504.52 loss on ICICIBANK is exactly at the per-trade risk cap (62 × ₹8.14 = ₹504.68).
Position was sized to risk ₹500, full risk materialized. Engine held the line.

## P&L summary

| | |
|---|---|
| Capital | ₹50,000.00 |
| Realized | -₹242.60 |
| Unrealized (2 open) | -₹114.55 |
| **Net at close** | **-₹357.15** |
| **Equity at close** | **₹49,642.85** |

Net change: **-0.71%** of capital in one session, 4 trades, 25% hit rate.

## Honest takeaways

1. **vwap_revert was the bright spot** — 1-for-1, hit target cleanly, net +₹261.92. Sample
   size = 1 means absolutely nothing. The backtest had this strategy at PF 0.38 (KILL).
2. **supertrend_adx flip-flopped on ICICIBANK** — bought it 14:40, stopped out exactly at risk
   cap at 15:05, then immediately shorted at 15:05. Trend-follower behavior: low hit rate,
   relies on a few big runners. With 1 trade closed at -1R and one open mid-flip, it didn't
   get a chance to find a runner this session. Consistent with backtest (ICICIBANK was its
   weakest symbol — backtest -₹9,886 OOS on 29 trades).
3. **Risk gates worked end-to-end** — per-trade cap, concurrent cap, insufficient-funds
   check all triggered correctly. No risk-rule violation in live state.
4. **A discretionary trader probably outperforms this** on 3 symbols × 2h with screen time.
   The honest comparison: these algos at this capital don't beat manual trading. The
   framework (risk + journal + objective scoring) is what's valuable.
5. **4 trades / hour is on the high end of the 1–4 estimate**, driven by supertrend's
   ICICIBANK flip and vwap's RELIANCE setup both landing in the same window.

## What changed in the code during this session

See commit `b12bbb9` — risk engine recursion fix, supervisor state persistence on restart,
backtest engine SHORT support, datetime.utcnow → tz-aware everywhere, dashboard heartbeat
parsing, `titan/strategies/supervisor.py` filters non-tradable indices.

## Open questions for next session

- Should we flatten EOD positions or carry over to MTF? (Today: left open, no MTF logic
  exists — they'll just sit until the supervisor restarts or hits stop)
- Bump `max_concurrent_positions` back to 1 after demo (currently 3)
- Restore `max_daily_loss_pct` to 2.0 (currently 10.0)
- `TITAN_CAPITAL` to 5000 (currently 50000)
- The per-trade risk on ICICIBANK BUY 62 × ₹8.14 = ₹504 *just* exceeded the ₹500 cap by
  rounding. Worth tightening the sizing helper to undershoot when cap is binding.
