#!/usr/bin/env bash
# run_load_test.sh — one-command Locust runner for Kapa RAG
#
# Usage:
#   ./tests/load/run_load_test.sh             # defaults: 10 users, 60s
#   USERS=20 DURATION=120s ./tests/load/run_load_test.sh
#   ./tests/load/run_load_test.sh --ui        # open browser UI instead

set -euo pipefail

# Load variables from .env so LOAD_TEST_EMAIL / LOAD_TEST_PASSWORD are available
# to locust (which runs on the host, not inside Docker).
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

USERS="${USERS:-10}"
SPAWN_RATE="${SPAWN_RATE:-2}"       # users added per second during ramp
DURATION="${DURATION:-60s}"
HOST="${HOST:-http://localhost:8000}"
OUT_DIR="tests/load/results"

mkdir -p "$OUT_DIR"

# Check locust is installed
if ! command -v locust &> /dev/null; then
  echo "locust not found. Install with: pip install locust"
  exit 1
fi

# UI mode: open browser dashboard
if [[ "${1:-}" == "--ui" ]]; then
  echo "Starting Locust web UI at http://localhost:8089"
  echo "Open that URL in your browser, then start the test manually."
  locust -f tests/load/locustfile.py --host "$HOST"
  exit 0
fi

echo "================================================"
echo " Kapa RAG Load Test"
echo " Users: $USERS  |  Spawn rate: $SPAWN_RATE/s  |  Duration: $DURATION"
echo " Target: $HOST"
echo " Results: $OUT_DIR/"
echo "================================================"
echo ""

locust -f tests/load/locustfile.py \
  --headless \
  --users "$USERS" \
  --spawn-rate "$SPAWN_RATE" \
  --run-time "$DURATION" \
  --host "$HOST" \
  --csv "$OUT_DIR/$(date +%Y%m%d_%H%M%S)" \
  --html "$OUT_DIR/report_$(date +%Y%m%d_%H%M%S).html"

echo ""
echo "Done. Check $OUT_DIR/ for CSV stats and HTML report."
