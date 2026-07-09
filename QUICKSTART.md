# TITAN — Quickstart

> Single-source-of-truth for installing the project, starting all four daemons
> end-to-end, and verifying it is alive. Paper mode only — see
> `docs/11_go_live_readiness.md` before flipping to real money.

Three audiences:
- **First-time setup** → §1–§4
- **Daily pre-market restart** → §5
- **Something broke** → §7 (Troubleshooting)

---

## 1. Prerequisites

| Need                  | Version            | Why                                  |
|-----------------------|--------------------|--------------------------------------|
| Python                | 3.11+ (3.14 tested)| Runtime                              |
| Docker + Compose      | recent             | Postgres (Timescale) + Redis         |
| Git                   | any                | Source control                       |
| Angel One SmartAPI    | live account       | Real ticks; paper-only works without |
| Disk space            | ~5 GB              | TimescaleDB + FinBERT model          |

macOS / Linux / WSL2 all work. Dev loop tested on macOS (Darwin 25).

---

## 2. One-time install

```bash
# Clone
git clone https://github.com/bijoymridha16/titan.git
cd titan

# Python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Infrastructure (Postgres + Redis as containers)
docker compose up -d postgres redis

# Wait ~5s for Postgres to be ready, then apply migrations
for f in migrations/*.sql; do
  psql 'postgresql://titan:titan@localhost:5432/titan' -f "$f"
done

# Config
cp .env.example .env
# edit .env — see §3 below for the minimum changes
```

Test the install:

```bash
.venv/bin/python -c "from titan.config import settings; print('OK, capital=', settings.capital)"
```

---

## 3. Configure `.env`

The defaults in `.env.example` are sane except for credentials and capital.
**For paper mode, you only need to set capital and (optionally) Angel One
keys if you want real ticks instead of synthetic.**

```bash
# Mode
TITAN_MODE=paper            # paper | live  (live needs explicit live-readiness gates)
TITAN_ENV=dev

# Capital (paper rehearsal number)
TITAN_CAPITAL=50000

# Risk caps — current paper-validation profile (see docs/11 §C Gate 1)
TITAN_MAX_RISK_PER_TRADE_PCT=0.5
TITAN_MAX_DAILY_LOSS_PCT=2.0
TITAN_MAX_DAILY_PROFIT_PCT=4.0
TITAN_MAX_WEEKLY_LOSS_PCT=5.0
TITAN_MAX_DRAWDOWN_PCT=5.0
TITAN_MAX_CONSECUTIVE_LOSSES=3
TITAN_MAX_CONCURRENT_POSITIONS=3
TITAN_INTRADAY_SQUARE_OFF=15:15

# Autopilot — disarmed during paper validation; vwap_revert is the only edge cell today
TITAN_AUTOPILOT_ENABLED=false
TITAN_AUTOPILOT_VALIDATED=vwap_revert

# Live safety gates (must STAY 0 until docs/11 Gate 3 passes)
TITAN_LIVE_ENABLED=0
TITAN_LIVE_DRY_RUN=1

# Postgres + Redis (defaults match docker-compose; only change if not using compose)
TITAN_DB_URL=postgresql+psycopg://titan:titan@localhost:5432/titan
TITAN_REDIS_URL=redis://localhost:6379/0

# Angel One — required only for real ticks (paper trading still works without)
ANGELONE_API_KEY=...
ANGELONE_CLIENT_CODE=...
ANGELONE_PASSWORD=...
ANGELONE_TOTP_SECRET=...

# Universe (NSE tradingsymbols, comma-separated)
TITAN_UNIVERSE=NIFTY,BANKNIFTY,RELIANCE,HDFCBANK,ICICIBANK,INFY,TCS  # trim as you wish
```

> **Heads-up.** Capital, risk caps, and the autopilot block are cached by the
> Python process on import. If you change `.env` while daemons are running,
> restart them.

---

## 4. First-data load (instrument master)

The feed needs to know which Angel One token maps to each NSE symbol. This is
a one-time fetch of the instrument master (refresh weekly, not daily).

```bash
.venv/bin/python -m titan.data.instruments
```

You should see lines like `loaded 172000 instruments`. Confirm in Postgres:

```bash
psql 'postgresql://titan:titan@localhost:5432/titan' -c \
  "SELECT exch_seg, COUNT(*) FROM instruments GROUP BY 1;"
```

---

## 5. Daily start — five daemons, in order

These four-plus-one processes are the live system. They must all be up during
NSE hours (09:15–15:30 IST).

```bash
# from repo root, venv active
PY=.venv/bin/python
mkdir -p out

# 1. Feed supervisor — manages the Angel WS connection (auto-stops outside market hours)
nohup $PY -m titan.data.feed_supervisor >> out/feed.log 2>&1 &

# 2. Bar writer — ticks → 1m/3m/5m/15m bars (Redis pub/sub + Postgres)
nohup $PY -m titan.data.bar_writer >> out/bar_writer.log 2>&1 &

# 3. Strategy supervisor — strategies → paper fills → trades table + 15:15 flatten
nohup $PY -m titan.strategies.supervisor >> out/supervisor.log 2>&1 &

# 4. FastAPI control plane — :8000
nohup $PY -m uvicorn titan.api.main:app --port 8000 >> out/api.log 2>&1 &

# 5. Streamlit dashboard — :8501
nohup $PY -m streamlit run titan/dashboard/app.py --server.port 8501 \
  --server.headless true >> out/dash.log 2>&1 &
```

Then prime Redis with the strategy gate (this is what the supervisor reads
each bar to decide what runs):

```bash
$PY - <<'EOF'
import redis
r = redis.Redis.from_url('redis://localhost:6379/0', decode_responses=True)
r.set('titan:autopilot:enabled', '0')           # autopilot off during validation
r.delete('titan:strategies:enabled')
r.sadd('titan:strategies:enabled', 'vwap_revert') # only the validated cell
from datetime import date
r.set('titan:risk:date', date.today().isoformat())
r.set('titan:risk:halted_today', '0')
r.delete('titan:risk:halt_reason')
r.set('titan:risk:consecutive_losses', '0')
print('redis state primed')
EOF
```

Open the surfaces:
- Dashboard: http://localhost:8501
- API docs: http://localhost:8000/docs
- API status: `curl http://localhost:8000/status | jq`

---

## 6. Verify it's alive

```bash
# Are all 5 daemons up?
ps aux | grep -E 'titan.data.feed|bar_writer|titan.strategies.supervisor|uvicorn|streamlit' | grep -v grep

# Did the feed connect and is it streaming?
tail -20 out/feed.log
.venv/bin/python -c "
import redis; r = redis.Redis.from_url('redis://localhost:6379/0', decode_responses=True)
print('feed status:', r.get('titan:feed:status'))
print('feed age (s):', r.get('titan:feed:age_s'))
print('last RELIANCE tick:', r.xrevrange('ticks:RELIANCE', count=1))
"

# Is the strategy supervisor receiving bars and (eventually) firing signals?
tail -20 out/supervisor.log | grep -E 'OPEN|REJECT|on_bar'

# Did the runtime market probe declare today a trading day?
.venv/bin/python -c "
import redis; from datetime import date
r = redis.Redis.from_url('redis://localhost:6379/0', decode_responses=True)
print('market traded today:', r.get(f'titan:market:traded:{date.today()}'))
"
```

Expected after 09:25 IST on a real trading day:
- `feed status: RUNNING`, `feed age (s): <30`
- `last RELIANCE tick` shows a timestamp within the last few seconds
- `market traded today: 1`
- Supervisor log has `_on_bar_event` / `OPEN` / `REJECT` activity within minutes of 09:30

---

## 7. Stop everything

```bash
pkill -f 'titan.data.feed'
pkill -f 'titan.data.bar_writer'
pkill -f 'titan.strategies.supervisor'
pkill -f 'uvicorn titan.api'
pkill -f 'streamlit run titan/dashboard'

# Verify all gone
ps aux | grep -E 'titan|streamlit|uvicorn' | grep -v grep || echo 'all stopped'

# Postgres + Redis stay up (other devs / runs may need them)
# To stop infra too:
# docker compose down
```

---

## 8. Troubleshooting (lived-experience gotchas)

| Symptom | Cause | Fix |
|---|---|---|
| Dashboard shows "NSE · OPEN" but `0 trades` and `feed dot` red | Possible market holiday (movable festival not in `config/nse_holidays.yaml`) | Wait until 09:25 IST and check `titan:market:traded:$(date +%F)`. If `"0"`, it's a holiday — stand down for the day. |
| Feed log shows `Websocket connected` but ticks are repeating the same LTP forever | Multiple Angel WS sessions on the same client_code, or you logged into Angel mobile/web | Kill ALL `titan.data.feed*` processes, log out of any Angel app, wait 60s, restart only the feed_supervisor. |
| Supervisor logs `REJECT … session halted: consecutive loss limit` early in the morning | Yesterday's in-memory risk state survived across midnight (supervisor wasn't restarted before open) | Always restart `titan.strategies.supervisor` at 09:00 IST before market open. |
| Supervisor logs OPEN+CLOSE in the same millisecond with no DB row showing today | Stale bar replay on restart (yesterday's last bar) — fixed 2026-06-26 with a 5-min freshness gate | Pull the row by symbol: `select … from trades where symbol='…' order by entry_ts desc`. If `entry_ts < today`, the fix worked (row exists but on yesterday's date). |
| `REJECT … insufficient funds` on many symbols at the open | The leverage gate was rejecting at 1× cash before the 2026-06-26 fix | Confirm `titan/risk/engine.py:144` reads `settings.mis_leverage`, and `.env` does not override `TITAN_MIS_LEVERAGE` lower than 5. |
| `out/supervisor.log` silent — no bar events | Either feed is silent (see above) OR `bar_writer` is dead (it's a separate process from feed_supervisor) | `ps aux | grep bar_writer` — restart it if missing. |
| Dashboard shows correct equity but `trades = 0` for today, even though logs show fills | DB persistence wrote with the wrong `entry_ts` (stale-bar bug). | Check `select entry_ts::date, count(*) from trades where exit_ts::date = current_date group by 1;` — if rows land on yesterday's date, the stale-bar guard didn't fire. |
| `import titan` fails after a `git pull` | New dependency added | `pip install -e ".[dev]"` again. |

---

## 9. What to read next

- `docs/03_architecture.md` — full system design, data flow, every component
- `docs/06_risk_framework.md` — the 11 risk gates, why each exists
- `docs/11_go_live_readiness.md` — **read before considering real money**; 4-gate staged plan
- `docs/12_new_strategies.md` — research candidates, walk-forward bar
- `docs/10_changes_and_decisions.md` §F — session log; one entry per day

---

## 10. Status (as of 2026-06-26)

- **Mode:** paper only. `TITAN_LIVE_ENABLED=0`.
- **Strategy roster active:** `vwap_revert` only (the one paying cell across 6
  paper sessions / 210 trades; see `docs/11` §A2).
- **ORB SHORT, `supertrend_adx`:** disabled until walk-forward shows edge.
- **Earliest responsible live date:** 2026-08-10. See `docs/11` §C.

If you want to validate the install end-to-end while NSE is closed, you can
run the synthetic feed instead of the real one — but it's clearly labeled
🧪 SIMULATION on the dashboard and is not for production:

```bash
TITAN_SIM_MODE=1 .venv/bin/python -m titan.data.synth_feed
# leave the other 4 daemons as in §5
```
