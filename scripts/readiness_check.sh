#!/usr/bin/env bash
# Run end-of-Thursday before flipping TITAN_LIVE_DRY_RUN=0.
# Each check prints PASS / FAIL. Exits non-zero if any FAIL.
#
# Checks:
#   1. Paper journal has >= 5 closed trades
#   2. Risk engine fired at least once (any kill/halt/reject row in risk_events)
#   3. Shadow dry-run payloads match paper fills (count parity within ±2)
#   4. No "instrument not found" errors in any log
#   5. Account funded with >= ₹5,000 cash (Angel RMS query)
#   6. Credentials are NOT the originals shared in chat (rotated)
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
fails=0
ok()   { echo "  ✅ PASS  $1"; }
bad()  { echo "  ❌ FAIL  $1"; fails=$((fails+1)); }

echo "── TITAN live-trading readiness check ──"
echo

# 1. paper journal
echo "[1/6] paper journal …"
n_trades=$(docker compose exec -T postgres psql -U titan -d titan -tAc \
  "SELECT COUNT(*) FROM trades WHERE exit_ts IS NOT NULL AND is_paper=true;")
n_trades=${n_trades//[[:space:]]/}
if [[ "$n_trades" -ge 5 ]]; then ok "$n_trades closed paper trades"
else bad "only $n_trades closed paper trades (need ≥ 5)"; fi

# 2. risk events
echo "[2/6] risk engine activity …"
n_events=$(docker compose exec -T postgres psql -U titan -d titan -tAc \
  "SELECT COUNT(*) FROM risk_events;")
n_events=${n_events//[[:space:]]/}
if [[ "$n_events" -ge 1 ]]; then ok "$n_events risk events logged"
else bad "0 risk events — guardrails never exercised"; fi

# 3. shadow payload parity
echo "[3/6] shadow dry-run vs paper trade count …"
n_shadow=$(grep -E "SHADOW-DRY (entry|exit)" /tmp/titan-supervisor.log 2>/dev/null | wc -l | tr -d ' ')
n_paper_fills=$(grep -E " (OPEN|CLOSE) " /tmp/titan-supervisor.log 2>/dev/null | wc -l | tr -d ' ')
n_shadow=${n_shadow:-0}
n_paper_fills=${n_paper_fills:-0}
diff=$(( n_shadow > n_paper_fills ? n_shadow - n_paper_fills : n_paper_fills - n_shadow ))
if [[ "$n_paper_fills" -ge 1 ]] && [[ "$diff" -le 2 ]]; then
  ok "$n_shadow shadow vs $n_paper_fills paper (diff=$diff)"
else
  bad "shadow=$n_shadow paper=$n_paper_fills diff=$diff (>2 = live path is buggy)"
fi

# 4. instrument resolution errors
echo "[4/6] instrument resolution errors …"
n_missing=$(grep -hE "instrument_not_found|instrument not found" /tmp/titan-*.log 2>/dev/null | wc -l | tr -d ' ')
n_missing=${n_missing:-0}
if [[ "$n_missing" -eq 0 ]]; then ok "no instrument lookup failures"
else bad "$n_missing instrument-not-found errors — fix master before going live"; fi

# 5. account funding
echo "[5/6] Angel account funding …"
cash=$($PY -c "
import asyncio
from titan.brokers.angelone import AngelOneBroker
async def f():
    b = AngelOneBroker(); await b.connect()
    r = await b.get_funds()
    print(float(r.get('availablecash') or 0))
try: asyncio.run(f())
except Exception as e: print('ERR:', e)
" 2>&1 | tail -1)
if [[ "$cash" =~ ^[0-9]+\.?[0-9]*$ ]] && [[ $(echo "$cash >= 5000" | bc -l) -eq 1 ]]; then
  ok "availablecash = ₹$cash"
else
  bad "availablecash=$cash (need ≥ ₹5000)"
fi

# 6. credentials rotated
echo "[6/6] credentials rotated …"
if grep -q "GJksXKQ3\|PXMZDKYJ34G27TF7POK4MSAQYY" .env 2>/dev/null; then
  bad "original API key / TOTP secret still in .env — ROTATE before going live"
else
  ok "credentials no longer match the originals shared in chat"
fi

echo
if [[ $fails -eq 0 ]]; then
  echo "✅ ALL CHECKS PASSED — safe to set TITAN_LIVE_DRY_RUN=0 for Friday."
  exit 0
else
  echo "❌ $fails CHECK(S) FAILED — DO NOT flip DRY_RUN. Fix above first."
  exit 1
fi
