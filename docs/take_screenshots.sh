#!/usr/bin/env bash
# Regenerate docs/screenshots/ from SIMULATED sample data using headless Chrome.
# Usage (from the repo root): bash docs/take_screenshots.sh
set -euo pipefail

PORT="${BB_PORT:-5055}"
DB="backend/sample.db"
CHROME="${CHROME:-google-chrome}"
END="${SAMPLE_END:-$(date -u +%Y-%m-%dT%H:%M:%S+00:00)}"
OUT="docs/screenshots"
export TZ="${TZ:-Asia/Kolkata}"

python analysis/simulate_readings.py --db "$DB" --end "$END"
BB_DB_PATH="$DB" BB_PORT="$PORT" python backend/app.py >/dev/null 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID' EXIT
sleep 2

shot() {  # shot <file> <width,height> <path> [scale]
  "$CHROME" --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
    --virtual-time-budget=5000 --window-size="$2" \
    --force-device-scale-factor="${4:-2}" \
    --screenshot="$OUT/$1" "http://127.0.0.1:$PORT$3" 2>/dev/null
}

mkdir -p "$OUT"
shot dashboard.png      1100,1180 "/dashboard"
shot dashboard-24h.png  1100,1000 "/dashboard?hours=24"
shot dashboard-full.png 1100,3150 "/dashboard" 1
echo "Screenshots saved to $OUT/"
