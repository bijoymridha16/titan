# 04 — Dashboard spec

Implementation: `titan/dashboard/app.py` (Streamlit, Phase 1).
Phase 2: React + TradingView Lightweight Charts, reading the same
Postgres/Redis. The data contract below is what changes between phases —
the visual layer can be swapped.

## 1 — Account overview

Source: `equity_curve` (latest), `trades` (today).

| Field | Source |
|---|---|
| `equity` | `SELECT equity FROM equity_curve ORDER BY ts DESC LIMIT 1` |
| `today_pnl` | `SUM(pnl) FROM trades WHERE entry_ts::date = CURRENT_DATE` |
| `available_cash` | `BrokerAdapter.get_funds().cash` (cached in Redis `titan:funds`) |
| `drawdown_pct` | `(peak_equity - equity) / peak_equity * 100` |
| `kill_switch` | `GET titan:kill` |

## 2 — Open positions

`SELECT * FROM trades WHERE exit_ts IS NULL`. Columns:
symbol, qty, side, entry_price, current_price (LTP from Redis),
stop_loss, target, unrealized_pnl, trade_duration.

## 3 — Trade journal

`SELECT * FROM trades WHERE exit_ts IS NOT NULL ORDER BY exit_ts DESC LIMIT 50`.
Add filters for strategy, date range, P&L sign. Export to CSV.

## 4 — Strategy health

For each strategy in `titan:strategies:enabled`:
- last heartbeat (`titan:heartbeat:<name>`, ISO timestamp updated every bar close)
- bars processed today
- signals emitted today / approved / rejected
- current regime tag (from regime overlay, when wired)
- VIX snapshot

## 5 — Risk monitor (color-coded)

| Metric | Source | Green | Yellow | Red |
|---|---|---|---|---|
| Daily loss | `today_pnl` | < 50% cap | 50–80% cap | ≥ 80% cap |
| Drawdown | session peak - current | < 50% cap | 50–80% | ≥ 80% |
| Consec losses | `titan:consec_losses` | < N-2 | N-1 | ≥ N |
| Open risk (R) | sum of open positions' (entry-stop)*qty | < 2R | 2–3R | ≥ 3R |

If Red on any → display `🛑 HALT — risk cap`; UI prompts manual confirmation
to override (override does not exist by design; only restart clears).

## 6 — System health

| Service | Check |
|---|---|
| Broker | `BrokerAdapter.get_funds()` succeeds in <500ms |
| Market data feed | Last tick age < 5s during market hours |
| Latency | p95 order-ack from Redis Streams `latency:orders` |
| API | `GET /status` 200 within 1s |
| Last signal time | `titan:last_signal_ts` |
| Last trade time | from `trades` table |

## 7 — Performance analytics

Equity curve (Plotly), monthly returns heatmap, drawdown underwater plot,
win-rate trend (rolling 30-trade), profit factor trend, trade-duration
distribution, hourly P&L distribution, per-strategy comparison table.

## Refresh cadence

- Sections 1, 5, 6: every 5s (lightweight Redis reads).
- Sections 2, 4: every 5s.
- Sections 3, 7: every 60s.

Streamlit Phase 1 uses `st_autorefresh` at 5s; heavy sections use cached
queries with TTL.
