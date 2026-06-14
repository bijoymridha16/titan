#!/usr/bin/env bash
# Start the whole pipeline in synthetic mode so you can see TITAN run end-to-end
# right now, even though NSE is closed.
#
# Components started (3 background processes):
#   1. synth_feed   — generates fake ticks → Redis
#   2. bar_writer   — ticks → OHLCV bars → Postgres + pub/sub
#   3. supervisor   — bars → strategies → paper fills → trades table
#
# API + dashboard are assumed already running (they were started earlier).
#
# Ctrl-C this script to stop everything cleanly.

set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
LOGS=/tmp

pids=()
cleanup() {
  echo
  echo "stopping demo …"
  for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
  $PY -c "import redis; r=redis.from_url('redis://localhost:6379/0', decode_responses=True); r.delete('titan:mode:synthetic'); r.delete('titan:heartbeat:feed')"
  echo "done."
}
trap cleanup INT TERM EXIT

echo "▶ synth_feed   → $LOGS/titan-synth.log"
$PY -m titan.data.synth_feed   > $LOGS/titan-synth.log     2>&1 & pids+=($!)

echo "▶ bar_writer   → $LOGS/titan-bars.log"
$PY -m titan.data.bar_writer   > $LOGS/titan-bars.log      2>&1 & pids+=($!)

echo "▶ supervisor   → $LOGS/titan-supervisor.log"
$PY -m titan.strategies.supervisor > $LOGS/titan-supervisor.log 2>&1 & pids+=($!)

echo
echo "demo running. open http://localhost:8501 — you should see:"
echo "  • 🧪 SYNTH pill in the topbar"
echo "  • ticker tape scrolling with live prices"
echo "  • feed dot green"
echo "  • bars forming on the 📈 Charts tab in seconds"
echo "  • once you enable a strategy (🤖 tab) trades show up in 📒 Journal"
echo
echo "tail logs:  tail -f $LOGS/titan-supervisor.log"
echo "stop:       Ctrl-C here"
wait
