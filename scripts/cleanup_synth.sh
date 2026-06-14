#!/usr/bin/env bash
# Wipe synthetic bars + trades + equity points + redis cache so the system is
# clean before Monday's real-market session.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "wiping synthetic OHLCV + trades + equity + risk_events …"
docker compose exec -T postgres psql -U titan -d titan <<'SQL'
TRUNCATE ohlcv, trades, equity_curve, risk_events;
SQL

echo "clearing redis state …"
.venv/bin/python - <<'PY'
import redis
r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
for key in r.scan_iter("titan:ltp:*"):     r.delete(key)
for key in r.scan_iter("titan:heartbeat:*"): r.delete(key)
for key in r.scan_iter("ticks:*"):          r.delete(key)
for k in ("titan:mode:synthetic", "titan:consec_losses",
          "titan:kill", "titan:kill:reason"): r.delete(k)
print("redis cleaned")
PY

echo "done. dashboard will repopulate from live data Monday 09:15 IST."
