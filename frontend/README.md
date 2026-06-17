# TITAN frontend (React rebuild — D3)

> **Status: scaffold / work-in-progress.** This is the foundation of the React
> terminal that will replace the Streamlit dashboard. **Until it reaches parity,
> the Streamlit dashboard (`:8501`) remains the live UI** — it has every feature
> wired and tested. Don't route real-money monitoring through this yet.

## Why a rebuild (the D3 decision)
Streamlit is great for an internal dashboard but reads as "generic", does a full
5-second page rerun (no true live feel), and resets the active tab on every
refresh. A React + TradingView-Lightweight-Charts terminal gives the modern,
real-time look — live candles, trade markers, no full reruns.

## Stack
- **React + Vite + TypeScript**
- **lightweight-charts** (TradingView) for candles + trade overlays
- Talks to the existing **FastAPI** control plane (`titan/api/main.py`)

## Run (dev)
```bash
# 1. backend (control plane) must be up
uvicorn titan.api.main:app --port 8000

# 2. frontend dev server (proxies /api → :8000)
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## What's wired in this scaffold
- `Header` — mode / market-open / regime pills + live clock (from `/status`, `/autopilot`)
- `KpiStrip` — capital, mode, market, clock, kill (from `/status`)
- `Chart` — candlesticks + entry markers (from `/data/bars`, `/data/trades`)
- `api.ts` — typed client (status, autopilot, bars, trades, positions, leaderboard, arm/disarm/kill)

Backend read endpoints added for this: `/data/bars`, `/data/trades`,
`/data/positions`, `/data/leaderboard`, `/data/analytics/funnel` (+ CORS).

## Parity checklist (to replace Streamlit)
- [x] Header + regime pills
- [x] KPI strip (extend: daily-profit lock, drawdown, P&L)
- [x] Chart + trade markers (extend: VWAP, SL/TP lines, volume, regime ribbon)
- [ ] Positions tab
- [ ] Journal tab (closed trades + stats)
- [ ] Strategies tab (+ auto-pilot arm/disarm; manual toggles read-only when armed)
- [ ] Analytics tab (signal funnel, slippage, per-strategy × regime P&L, leaderboard)
- [ ] Risk tab (kill / flatten / budgets)
- [ ] System tab (feed health, market state, universe)
- [ ] Live ticks via WebSocket/SSE (replace 5s polling)
- [ ] Auth before exposing beyond localhost

## Cutover plan
Run both UIs in parallel → reach parity → flip the default → retire Streamlit.
See `docs/10_changes_and_decisions.md` §D.
